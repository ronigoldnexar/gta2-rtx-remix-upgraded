#!/usr/bin/env python3
"""CARS-V3 per-car gate: old (shipped assets/models) vs new (hy_convert output), the old model by default.

    gate.py score <old run dir>[,<more>] <new run dir>[,<more>] <out dir>      # metrics + contact sheets
    gate.py emit <out dir>/scores.json <verdicts.txt> <converted manifest> <entries out.json>

score: cv3_own.sh frames own_<pose>_<NNN>_<set>.png of the same set (default "game": the car's own game paint) in
both runs. Per run and pose the background is the per-pixel median over all cars' frames (clock paused, fixed
camera: only the car changes), the car is where a frame differs from it. Per car and pose:
  noise   mean |Laplacian| of the luminance inside the eroded mask (hard facets, baked-in speckle, torn texels)
  blotch  share of the car's pixels that are near-white and grey (generator highlights / white smears)
  hue     distance of the car's dominant saturated hue to the sprite's (assets-src/cars/sprites NNN_*_default.png),
          only when the sprite carries a saturated identity colour (liveries: taxi yellow, hot dog, cop blue)
  fill    mask area against the old model's (proportions: a new shell far smaller/larger than the fitted old one)
The machine says "new" only when the new model is no worse on every metric by a margin; the verdict file
(NNN new|old  reason) is the reviewer's call after opening the sheets and overrides it. emit writes the
converted-manifest entries of the cars whose verdict is new (the input of the stage builder; every other car
keeps the shipped entry), and prints the gate table for docs/car-3d-pipeline.md.
"""
import colorsys, glob, json, os, re, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

SPRITES = os.path.expanduser('~/gta2-linux/assets-src/cars/sprites')
POSES = ('front34', 'rear34', 'side', 'high')
SET = os.environ.get('GATE_SET', 'game')


def frames(dirs, pose):
    out = {}
    for d in dirs.split(','):
        for p in glob.glob(os.path.join(d, f'own_{pose}_[0-9][0-9][0-9]_{SET}.png')):
            out[re.search(r'_(\d\d\d)_', os.path.basename(p)).group(1)] = p
    return out


def load(p):
    return np.asarray(Image.open(p).convert('RGB'), np.float32)


def hud_mask(h, w):
    m = np.ones((h, w), bool)
    m[: int(h * 0.16), : int(w * 0.20)] = False; m[: int(h * 0.18), int(w * 0.82):] = False   # HUD corners
    m[int(h * 0.62):, : int(w * 0.20)] = False                                                 # minimap
    return m


def car_mask(img, bg, keep):
    d = np.abs(img - bg).max(axis=2)
    m = ndimage.binary_opening(d > 28, iterations=2) & keep
    lab, n = ndimage.label(m)
    if not n:
        return m
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    return lab == (1 + int(np.argmax(sizes)))


def dom_hue(rgb):
    """the dominant saturated hue (deg) and the share of saturated pixels."""
    px = rgb.reshape(-1, 3) / 255.0
    mx, mn = px.max(1), px.min(1); s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    sat = (s > 0.45) & (mx > 0.25)
    if sat.mean() < 0.08:
        return None, float(sat.mean())
    h = np.array([colorsys.rgb_to_hsv(*c)[0] for c in px[sat][:: max(1, sat.sum() // 4000)]]) * 360
    hist, edges = np.histogram(h, bins=36, range=(0, 360))
    return float(edges[int(np.argmax(hist))] + 5), float(sat.mean())


def sprite_hue(car):
    p = sorted(glob.glob(os.path.join(SPRITES, f'{car}_*_default.png')))
    if not p:
        return None
    a = np.asarray(Image.open(p[0]).convert('RGBA'), np.float32)
    rgb = a[..., :3][a[..., 3] > 128]
    return dom_hue(rgb[None])[0] if len(rgb) else None


def metrics(img, m):
    if m.sum() < 400:
        return None
    lum = img @ np.array([0.299, 0.587, 0.114], np.float32)
    inner = ndimage.binary_erosion(m, iterations=4)
    lap = np.abs(ndimage.laplace(lum))
    rgb = img[m]; mx, mn = rgb.max(1), rgb.min(1)
    blotch = float(((mx > 215) & (mx - mn < 28)).mean())
    return dict(noise=float(lap[inner].mean()) if inner.any() else 0.0, blotch=blotch, area=int(m.sum()),
                hue=dom_hue(rgb[None])[0])


def hdist(a, b):
    if a is None or b is None:
        return None
    d = abs(a - b) % 360
    return min(d, 360 - d)


def score(olds, news, out):
    os.makedirs(out, exist_ok=True)
    res = {}
    for pose in POSES:
        fo, fn = frames(olds, pose), frames(news, pose)
        cars = sorted(set(fo) & set(fn))
        if not cars:
            continue
        print(f'{pose}: {len(cars)} cars', flush=True)
        bgs = {}
        for k, f in (('old', fo), ('new', fn)):
            stack = np.stack([load(f[c])[::2, ::2] for c in cars[:: max(1, len(cars) // 24)]])
            bgs[k] = np.median(stack, axis=0)
        for c in cars:
            r = res.setdefault(c, {})
            for k, f in (('old', fo), ('new', fn)):
                img = load(f[c])[::2, ::2]
                m = car_mask(img, bgs[k], hud_mask(*img.shape[:2]))
                r.setdefault(pose, {})[k] = metrics(img, m)
    for c, r in res.items():
        sh = sprite_hue(c); r['sprite_hue'] = sh
        worse = []; better = []
        for pose in POSES:
            o, n = r.get(pose, {}).get('old'), r.get(pose, {}).get('new')
            if not o or not n:
                continue
            if n['noise'] > o['noise'] * 1.15: worse.append(f'{pose}:noise')
            elif n['noise'] < o['noise'] * 0.85: better.append(f'{pose}:noise')
            if n['blotch'] > o['blotch'] + 0.02: worse.append(f'{pose}:blotch')
            if not (0.7 < n['area'] / max(1, o['area']) < 1.4): worse.append(f'{pose}:fill')
            if sh is not None:
                dn, do = hdist(n['hue'], sh), hdist(o['hue'], sh)
                if dn is not None and (do is None or dn > do + 15): worse.append(f'{pose}:hue')
        r['machine'] = 'new' if (not worse and better) else 'old'
        r['worse'], r['better'] = worse, better
    json.dump(res, open(os.path.join(out, 'scores.json'), 'w'), indent=1)
    sheets(olds, news, sorted(res), out)
    print('scores:', os.path.join(out, 'scores.json'))


def sheets(olds, news, cars, out, per=6):
    fo = {p: frames(olds, p) for p in ('front34', 'rear34')}; fn = {p: frames(news, p) for p in ('front34', 'rear34')}
    cw, ch = 400, 225
    for i in range(0, len(cars), per):
        grp = cars[i: i + per]
        sheet = Image.new('RGB', (cw * 4 + 90, ch * len(grp)), (30, 30, 30)); d = ImageDraw.Draw(sheet)
        for j, c in enumerate(grp):
            sp = sorted(glob.glob(os.path.join(SPRITES, f'{c}_*_default.png')))
            if sp:
                s = Image.open(sp[0]).convert('RGBA'); s.thumbnail((86, ch - 20)); sheet.paste(s, (2, j * ch + 18), s)
            d.text((4, j * ch + 2), c, fill=(255, 255, 0))
            for k, (src, p) in enumerate(((fo, 'front34'), (fn, 'front34'), (fo, 'rear34'), (fn, 'rear34'))):
                if c in src[p]:
                    im = Image.open(src[p][c]).convert('RGB')
                    w, h = im.size; im = im.crop((int(w * 0.18), int(h * 0.08), int(w * 0.86), int(h * 0.88))).resize((cw, ch))
                    sheet.paste(im, (90 + k * cw, j * ch))
                    d.text((94 + k * cw, j * ch + 2), ('old ', 'NEW ', 'old ', 'NEW ')[k] + p, fill=(255, 255, 255))
        sheet.save(os.path.join(out, f'sheet_{grp[0]}_{grp[-1]}.jpg'), quality=85)


def emit(scores_p, verdicts_p, conv_man, out_p):
    sc = json.load(open(scores_p))
    ver = {}
    for line in open(verdicts_p):
        line = line.split('#')[0].strip()
        if line:
            c, v, *why = line.split(None, 2)
            ver[c.zfill(3)] = (v, why[0] if why else '')
    conv = {e['name'][:3]: e for e in json.load(open(conv_man))['models']}
    win = [];
    print('| Car | Machine (worse / better) | Verdict | Why |\n|---|---|---|---|')
    for c in sorted(set(sc) | set(ver)):
        r = sc.get(c, {}); v, why = ver.get(c, ('old', 'default (no review)'))
        if v == 'new' and c in conv:
            win.append({k: x for k, x in conv[c].items() if k != 'material_textures'})
        m = r.get('machine', '-'); wb = f"{len(r.get('worse', []))} / {len(r.get('better', []))}"
        print(f'| {c} | {m} ({wb}) | **{v}** | {why} |')
    json.dump({'models': win}, open(out_p, 'w'), indent=1)
    print(f'\n{len(win)} cars take the new model: {" ".join(e["name"][:3] for e in win)} -> {out_p}')


if __name__ == '__main__':
    if len(sys.argv) >= 5 and sys.argv[1] == 'score':
        score(*sys.argv[2:5])
    elif len(sys.argv) >= 6 and sys.argv[1] == 'emit':
        emit(*sys.argv[2:6])
    else:
        print(__doc__); sys.exit(2)
