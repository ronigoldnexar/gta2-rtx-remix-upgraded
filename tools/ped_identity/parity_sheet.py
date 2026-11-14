#!/usr/bin/env python3
"""PEDS-CONSISTENT parity sheet: civilians side by side as the classic view shows them (the game's sprite in the
remap's palette: the top-down walking frame and the full figure) and as the 3D views dress them (outfits.crowd(),
the DLL's CrowdVariety: 3/4 and from above), with the sprite's top/bottom colours, the shown 3D colours and the
CIEDE2000 between them.

    CUDA_VISIBLE_DEVICES=0 gen3d/venv/bin/python tools/ped_identity/parity_sheet.py <models dir> <out.jpg> [--n 48] [--manifest m.json]"""
import argparse, json, os, sys
here = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, here)
import render
from outfits import crowd, pool_model, sprite_colours
from outfit_parity_de import de2000
from PIL import Image, ImageDraw
ROOT = os.environ.get('GTA2_ROOT', '/mnt/gta2/gta2-linux')
sys.path.insert(0, ROOT + '/assets-src/cars'); import parse_sty
ap = argparse.ArgumentParser(); ap.add_argument('models'); ap.add_argument('out')
ap.add_argument('--n', type=int, default=48); ap.add_argument('--manifest', default=None); ap.add_argument('--first', type=int, default=300)
a = ap.parse_args()
M = a.models.rstrip('/') + '/'
man = json.load(open(a.manifest or M + 'manifest.json'))
imp = {e['name']: e for e in json.load(open(M + 'manifest.json'))['imported']}
rows = man['ped_outfits']
civ = [t for t in man['ped_types'] if t['name'].startswith('civilian')]
st = parse_sty.parse(ROOT + '/game/data/wil.sty')
def spr(i, remap):
    abs_i = st['sprb'][0] + i
    return st['sprite_rgba'](abs_i, st['palette'](st['phys'](st['bases']['ped_remap'] + remap)))
CW, CH = 120, 200
cols = 4
cells = []   # one row per remap (cols peds of it: the variety within its colours), rows spread over the remaps
step = max(1, len(civ) // max(1, a.n // cols))
for q in range(a.n // cols):
    t = civ[(q * step) % len(civ)]; r = t['remaps'][0]
    for c in range(cols):
        seed = a.first + 37 * (q * cols + c)
        name = pool_model(seed, t['models'], r); e = imp[name]
        cells.append((r, seed, name, e, crowd(seed, r, name, e, rows[r], True, models=imp)))
W = 4 * CW + 10
sheet = Image.new('RGB', (cols * W, ((len(cells) + cols - 1) // cols) * (CH + 30)), (36, 38, 42)); d = ImageDraw.Draw(sheet)
for i, (r, seed, name, e, rec) in enumerate(cells):
    x0, y0 = (i % cols) * W, (i // cols) * (CH + 30)
    top_down, full = spr(0, r), spr(113, r)
    for j, im in enumerate((top_down, full)):
        im = im.convert('RGBA'); s = min(CW / im.width, CH / im.height) * (0.9 if j else 0.8)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.NEAREST)
        bg = Image.new('RGB', (CW, CH), (128, 128, 128)); bg.paste(im, ((CW - im.width) // 2, (CH - im.height) // 2), im)
        sheet.paste(bg, (x0 + j * CW, y0))
    def tints(tex, node, rec=rec):
        if rec['zone'] is not None:
            if '#pt' in node: return rec['zone'][0]
            if '#pb' in node: return rec['zone'][1]
        return None
    n = rec.get('model', name); af = M + name + '.mesh' if n != name else None
    hd = rec.get('head'); HIDE = (lambda tex, node: tex.endswith('_head.tga') or '_opacity' in tex or '_glasses' in tex) if hd else None
    im = render.render(M + n + '.mesh', [(25, 8)], tints=tints if rec['zone'] else None, size=(CW, CH), anim_from=af,
                       extra=[M + hd + '.mesh'] if hd else [], hide=HIDE)[0]
    sheet.paste(im, (x0 + 2 * CW, y0))
    big = render.render(M + n + '.mesh', [(0, 85)], tints=tints if rec['zone'] else None, size=(CW * 3, CH * 3), anim_from=af,
                        extra=[M + hd + '.mesh'] if hd else [], hide=HIDE)[0]
    sheet.paste(big.crop((CW, CH, 2 * CW, 2 * CH)), (x0 + 3 * CW, y0))
    sc = sprite_colours(rows[r]); ref = max(8.0, e.get('zone_ref') or 128.0)
    if rec['zone']:
        shown = [tuple(int(min(255.0, z * ref) + 0.5) for z in rec['zone'][j]) for j in range(2)]
        des = [de2000(sc[j], shown[j]) for j in range(2)]
        for j in range(2):   # swatches: sprite | 3D, top then bottom
            d.rectangle([x0 + 2 * CW + 2, y0 + 4 + j * 22, x0 + 2 * CW + 18, y0 + 22 + j * 22], fill=sc[j])
            d.rectangle([x0 + 2 * CW + 18, y0 + 4 + j * 22, x0 + 2 * CW + 34, y0 + 22 + j * 22], fill=shown[j])
        lab = f'dE {des[0]:.1f} / {des[1]:.1f}'
    else:
        lab = 'fixed look'
    d.text((x0 + 2, y0 + CH + 2), f'remap {r} seed {seed} {n.replace("human_", "")[:20]}', fill=(250, 210, 120))
    d.text((x0 + 2, y0 + CH + 15), f'sprite {sc[0]} / {sc[1]}  {lab}', fill=(220, 220, 220))
sheet.save(a.out, quality=88); print(a.out, sheet.size, len(cells))
