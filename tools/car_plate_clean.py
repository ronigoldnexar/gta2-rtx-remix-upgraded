#!/usr/bin/env python3
"""FIX-CAR-TEX (pm70): replace the garbled number plates the image-to-3D generator baked into a car's texture
with a clean plate drawn in the plate's own 3D frame.

Why: the generated cars' (cars/models3d/*.glb) textures carry plates the generator hallucinated: a white patch with
torn edges and glyph-like smears ("EPEN3" on the 040 Maurice), read at chase distance in third person.

What, per car (the manifest's paint_split entries with a single-texture glb; authored carkit bodies are skipped):
  1. rasterise the glb's triangles into the imported texture's UV space (each texel: its point on the body and its
     face normal);
  2. at each end (rear, then front: the faces within 12 % of the length from the end, facing out along the length,
     the middle 40 % of the width, below 65 % of the height), the plate is the connected patch of pale, unsaturated
     texels whose extent on the body is plate-shaped (0.05..0.22 blocks wide, 1.4..6 times its height) with dark
     strokes inside it (the garbled glyphs);
  3. every end-facing texel whose body point lies in that rectangle (grown by a texel) is repainted from a plate
     picture sampled in the rectangle's own (across, up) frame, so it is straight on the car whatever the UV
     island's rotation or skew: a pale plate, a dark border, and the characters when the plate is at least
     --text-min texels wide (otherwise a plain plate: neutral rather than garbled).
  The texel is written to both halves (<tex>.tga and <tex>_paint.tga RGB: the soft paint path draws the paint
  picture's RGB everywhere) and taken out of the paint (paint alpha 0, rest alpha 255): a plate is not body paint.
Writes in place (unlinking first: assets/models shares inodes with stages) or to --out. Deterministic.
--sheet DIR writes a before/after crop per car. Needs numpy, Pillow, scipy (the gen3d venv has them).

  python3 tools/car_plate_clean.py assets/models --src assets-src [--only 040,018] [--dry-run] [--sheet /tmp/p]
"""
import argparse, io, json, os, struct, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

CT = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


def load_glb(path):
    d = open(path, 'rb').read()
    n = struct.unpack('<I', d[12:16])[0]
    j = json.loads(d[20:20 + n])
    off = 20 + n
    bl = struct.unpack('<I', d[off:off + 4])[0]
    b = d[off + 8:off + 8 + bl]

    def acc(i):
        a = j['accessors'][i]
        bv = j['bufferViews'][a['bufferView']]
        o = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
        return np.frombuffer(b, CT[a['componentType']], a['count'] * NC[a['type']], o).reshape(a['count'], -1)
    pos, uv, idx = [], [], []
    base = 0
    for m in j['meshes']:
        for p in m['primitives']:
            at = p['attributes']
            if 'TEXCOORD_0' not in at:
                continue
            P = acc(at['POSITION']).astype(np.float64)
            pos.append(P); uv.append(acc(at['TEXCOORD_0']).astype(np.float64))
            idx.append(acc(p['indices']).reshape(-1, 3).astype(np.int64) + base)
            base += len(P)
    return j, np.concatenate(pos), np.concatenate(uv), np.concatenate(idx)


def rasterise(P, UV, F, W, H):
    """per texel: body point, face normal, valid (top-down image rows: v * H, as the glb image)."""
    pos = np.zeros((H, W, 3)); nrm = np.zeros((H, W, 3)); ok = np.zeros((H, W), bool)
    n = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    for t, f in enumerate(F):
        u = UV[f, 0] * W; v = UV[f, 1] * H
        x0, x1 = int(max(0, np.floor(u.min()))), int(min(W - 1, np.ceil(u.max())))
        y0, y1 = int(max(0, np.floor(v.min()))), int(min(H - 1, np.ceil(v.max())))
        if x1 < x0 or y1 < y0 or x1 - x0 > W / 2 or y1 - y0 > H / 2:
            continue
        den = (v[1] - v[2]) * (u[0] - u[2]) + (u[2] - u[1]) * (v[0] - v[2])
        if abs(den) < 1e-12:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        l1 = ((v[1] - v[2]) * (xs - u[2]) + (u[2] - u[1]) * (ys - v[2])) / den
        l2 = ((v[2] - v[0]) * (xs - u[2]) + (u[0] - u[2]) * (ys - v[2])) / den
        l3 = 1 - l1 - l2
        e = -0.5 / np.sqrt(abs(den))
        inside = (l1 >= e) & (l2 >= e) & (l3 >= e)
        if not inside.any():
            continue
        yy, xx = np.nonzero(inside)
        pt = l1[inside, None] * P[f[0]] + l2[inside, None] * P[f[1]] + l3[inside, None] * P[f[2]]
        pos[yy + y0, xx + x0] = pt; nrm[yy + y0, xx + x0] = n[t]; ok[yy + y0, xx + x0] = True
    return pos, nrm, ok


def read_tga(path):
    return np.asarray(Image.open(path).convert('RGBA')).astype(np.float32)


def write_tga(arr, path):
    if os.path.lexists(path):
        os.unlink(path)
    px = np.clip(arr + 0.5, 0, 255).astype(np.uint8)[::-1][..., [2, 1, 0, 3]]
    h, w = px.shape[:2]
    with open(path, 'wb') as f:
        f.write(struct.pack('<BBBHHBHHHHBB', 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 8))
        f.write(px.tobytes())


def plate_picture(text, pw, ph, bg, show_text):
    """the plate in its own frame at (pw x ph) texels: pale field, dark border, characters if legible."""
    S = 16
    W, H = max(8, pw * S), max(4, ph * S)
    im = Image.new('RGB', (W, H), tuple(int(c) for c in bg))
    d = ImageDraw.Draw(im)
    ink = (28, 30, 34)
    bw = max(S, int(min(W, H) * 0.10))
    d.rectangle([0, 0, W - 1, H - 1], outline=ink, width=bw)
    if show_text:
        try:
            font = ImageFont.truetype('DejaVuSansMono-Bold.ttf', int(H * 0.62))
        except OSError:
            font = ImageFont.load_default()
        box = d.textbbox((0, 0), text, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        sc = min(1.0, (W - 3 * bw) / max(tw, 1))
        if sc < 1.0:
            font = ImageFont.truetype('DejaVuSansMono-Bold.ttf', max(6, int(H * 0.62 * sc))) if hasattr(font, 'path') else font
            box = d.textbbox((0, 0), text, font=font); tw, th = box[2] - box[0], box[3] - box[1]
        d.text(((W - tw) / 2 - box[0], (H - th) / 2 - box[1]), text, font=font, fill=ink)
    return np.asarray(im.resize((max(2, pw * 2), max(2, ph * 2)), Image.LANCZOS)).astype(np.float32)


def find_plates(rgb, pos, nrm, ok, axis, lo, hi, args):
    L = hi - lo
    side = 0 if axis == 2 else 2
    mid = (lo[side] + hi[side]) / 2
    lum = rgb.mean(-1); mx = rgb.max(-1); mn = rgb.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1)
    plates = []
    for end, sgn in (('rear', -1), ('front', 1)):
        a = (pos[..., axis] - lo[axis]) / L[axis]
        endset = ok & (((a < 0.12) if sgn < 0 else (a > 0.88))) & (nrm[..., axis] * sgn > 0.45)
        endset &= np.abs(pos[..., side] - mid) < 0.20 * L[side]
        endset &= (pos[..., 1] - lo[1]) / L[1] < 0.65
        pale = endset & (lum > args.pale) & (sat < 0.30)
        # the glyphs: dark texels on a pale field (ink with pale within two texels), merged into words
        ink = endset & (lum < args.dark) & ndimage.binary_dilation(pale, iterations=2)
        lab, nlab = ndimage.label(ndimage.binary_closing(ink, iterations=2) & endset)
        best = None
        for k in range(1, nlab + 1):
            m = lab == k
            if m.sum() < 6:
                continue
            xs, ys = pos[..., side][m], pos[..., 1][m]
            x0, x1 = xs.min(), xs.max(); y0, y1 = ys.min(), ys.max()
            w, h = x1 - x0, y1 - y0
            if not (0.045 <= w <= 0.17 and 0.012 <= h <= 0.07 and 1.5 <= w / h <= 6.5):
                continue
            box = endset & (pos[..., side] >= x0) & (pos[..., side] <= x1) & (pos[..., 1] >= y0) & (pos[..., 1] <= y1)
            nb = max(1, box.sum())
            dark = (box & (lum < args.dark)).sum() / nb
            palef = (box & pale).sum() / nb
            if not (0.06 <= dark <= 0.75 and palef >= 0.25):
                continue
            score = m.sum() / (1 + abs((x0 + x1) / 2 - mid) / (0.05 * L[side]))
            if best is None or score > best[0]:
                yy, xx = np.nonzero(m)
                gy, gx = max(3, int((yy.max() - yy.min()) * 0.4)), max(3, int((xx.max() - xx.min()) * 0.4))
                uvbox = (max(0, yy.min() - gy), yy.max() + gy + 1, max(0, xx.min() - gx), xx.max() + gx + 1)
                depth = float(np.median(pos[..., axis][m]))
                best = (score, x0, x1, y0, y1, dark, int((box & pale).sum()), int(box.sum()), uvbox, depth)
        if best:
            plates.append(dict(end=end, sgn=sgn, x0=best[1], x1=best[2], y0=best[3], y1=best[4], dark=best[5], pale=best[6],
                               texels=best[7], uvbox=best[8], depth=best[9], endset=endset))
    return plates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('models'); ap.add_argument('--src', required=True); ap.add_argument('--out', default=None)
    ap.add_argument('--only', default=''); ap.add_argument('--dry-run', action='store_true'); ap.add_argument('--sheet', default='')
    ap.add_argument('--pale', type=float, default=150.0); ap.add_argument('--dark', type=float, default=95.0)
    ap.add_argument('--text-min', type=int, default=28, help='plate width in texels from which characters are drawn')
    args = ap.parse_args()
    out = args.out or args.models
    man = json.load(open(os.path.join(args.models, 'manifest.json')))
    only = {s.strip().zfill(3) for s in args.only.split(',') if s.strip()}
    if not only and not args.dry_run:
        sys.exit('--only is required for a write: the detector also fires on tail lamps and chrome (see the doc); '
                 'review a --dry-run --sheet first and list the cars whose crop shows a plate')
    for e in man['models']:
        name = e['name']
        if not name[:3].isdigit() or not e.get('paint_split') or (only and name[:3] not in only):
            continue
        glbp = os.path.join(args.src, e['glb'])
        tex = os.path.join(args.models, name + '_0.tga'); ptex = os.path.join(args.models, name + '_0_paint.tga')
        if not (os.path.exists(glbp) and os.path.exists(tex) and os.path.exists(ptex)):
            print(f'{name}: skipped (no glb or no _0 pair)'); continue
        j, P, UV, F = load_glb(glbp)
        if len(j.get('images', [])) != 1:
            print(f'{name}: skipped ({len(j.get("images", []))} images)'); continue
        base = read_tga(tex); paint = read_tga(ptex)
        H, W = base.shape[:2]
        lo, hi = P.min(0), P.max(0)
        axis = 2 if (hi - lo)[2] >= (hi - lo)[0] else 0
        pos, nrm, ok = rasterise(P, UV, F, W, H)
        rgb = paint[..., :3]
        plates = find_plates(rgb, pos, nrm, ok, axis, lo, hi, args)
        if not plates:
            print(f'{name}: no plate found'); continue
        side = 0 if axis == 2 else 2
        before = rgb.copy()
        msgs = []
        for pl in plates:
            gx = (pl['x1'] - pl['x0']) * 0.02; gy = (pl['y1'] - pl['y0']) * 0.04
            x0, x1, y0, y1 = pl['x0'] - gx, pl['x1'] + gx, pl['y0'] - gy, pl['y1'] + gy
            near = np.zeros_like(pl['endset'])
            r0, r1, c0, c1 = pl['uvbox']; near[r0:r1, c0:c1] = True   # the plate's own UV island, not every end face
            near &= np.abs(pos[..., axis] - pl['depth']) < 0.03
            sel = pl['endset'] & near & (pos[..., side] >= x0) & (pos[..., side] <= x1) & (pos[..., 1] >= y0) & (pos[..., 1] <= y1)
            n = int(sel.sum())
            aspect = (x1 - x0) / (y1 - y0)
            pw = max(4, int(round(np.sqrt(n * aspect)))); ph = max(2, int(round(np.sqrt(n / aspect))))
            pal = (paint[..., :3][sel & (paint[..., :3].mean(-1) > args.pale)])
            bg = np.clip(np.median(pal, 0) if len(pal) else np.array([226, 226, 218.0]), 200, 236)
            bg = np.full(3, bg.mean()) * np.array([1.0, 1.0, 0.97])
            text = f'{name[4].upper()}{name[:3]}'   # the model's initial and number, M040
            pic = plate_picture(text, pw, ph, bg, pw >= args.text_min)
            # (across, up) in the plate frame; across runs left to right as seen from outside the end
            s = (pos[..., side][sel] - x0) / (x1 - x0)
            if pl['sgn'] < 0:   # seen from behind, +x is on the viewer's right only for a -z end facing -z ... keep text readable
                s = s if axis == 2 else 1 - s
            else:
                s = 1 - s if axis == 2 else s
            t = 1 - (pos[..., 1][sel] - y0) / (y1 - y0)
            ph2, pw2 = pic.shape[:2]
            ci = np.clip((s * pw2).astype(int), 0, pw2 - 1); ri = np.clip((t * ph2).astype(int), 0, ph2 - 1)
            col = pic[ri, ci]
            yy, xx = np.nonzero(sel)
            for arr in (base, paint):
                arr[yy, xx, :3] = col
            base[yy, xx, 3] = 255; paint[yy, xx, 3] = 0
            msgs.append(f"{pl['end']} {pw}x{ph} texels ({n}), {(pl['x1']-pl['x0']):.3f}x{(pl['y1']-pl['y0']):.3f} blocks, "
                        f"strokes {pl['dark']:.2f}, {'text' if pw >= args.text_min else 'plain'}")
        print(f'{name}: ' + '; '.join(msgs))
        if args.sheet:
            os.makedirs(args.sheet, exist_ok=True)
            m = np.zeros((H, W), bool)
            for pl in plates:
                r0, r1, c0, c1 = pl['uvbox']; m[r0:r1, c0:c1] = True
            ys, xs = np.nonzero(m)
            if len(ys):
                y0, y1, x0, x1 = max(0, ys.min() - 6), min(H, ys.max() + 7), max(0, xs.min() - 6), min(W, xs.max() + 7)
                a = np.concatenate([before[y0:y1, x0:x1], paint[y0:y1, x0:x1, :3]], 1)
                Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).resize((a.shape[1] * 6, a.shape[0] * 6), Image.NEAREST) \
                    .save(os.path.join(args.sheet, name + '.png'))
        if not args.dry_run:
            write_tga(base, os.path.join(out, name + '_0.tga'))
            write_tga(paint, os.path.join(out, name + '_0_paint.tga'))


if __name__ == '__main__':
    main()
