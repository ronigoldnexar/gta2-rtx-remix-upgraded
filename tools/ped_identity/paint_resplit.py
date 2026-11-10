#!/usr/bin/env python3
"""ASSET-PEDS-3: re-split a zoned avatar's body texture by its garment's UV triangles.

import_assets.py (ped_zones) cut the clothing out of a body texture by COLOUR: a texel inside the
garment that passed the skin rule (classic RGB test + within 0.06 of the face's chromaticity) stayed
in the rest half in its own colour. On a brown leather jacket (f004), a pink shirt (f001) or a
brown sleeve (m009) the garment's bright folds pass that test, so under any tint those folds, a
diagonal and 1-px speckle show through in the avatar's old colour (qav14).

This tool keeps the rest half's skin only where it is skin: the texels of the garment's UV
triangles (the #pt / #pb paint meshes of the .mesh, rasterised in UV space) that are not in the
paint half are kept in the rest half only if they belong to a SOLID skin region (a connected
region of them that contains a (2r+1)x(2r+1) square) AND that region is lit like skin (luminance
and green chromaticity: hands, a bare forearm, the neckline, m009's pale tan vest). Every other garment texel (folds, diagonals, speckle)
moves to the paint half with its own luminance, by the same rule import_assets.py used (contrast
eased by 0.75 around the zone's mean, mean -> 128), with the zone's mean recovered from the
texels already in the paint half so those stay byte-identical.

The gutters between UV islands are then shared out between the two halves (--pad rings, edge padding),
so filtering across a garment's edge never reaches the rest half's opaque gutter (1-px specks on seams).

Files are written to --out (never in place: assets/models shares inodes with repo/stage).

usage: paint_resplit.py <models dir> --out <dir> [--radius 5] [--preview <png>] <model>_<tag> ...
       e.g. human_female_adult_04_f004 human_female_01_f001 human_male_adult_05_m009
A second run on its own output changes nothing.
"""
import os, sys, struct, argparse
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmsh

CONTRAST, REF = 0.75, 128.0

def read_tga(path):
    return np.asarray(Image.open(path).convert('RGBA')).copy()

def write_tga(a, path):
    """32-bit uncompressed bottom-up TGA, as tools/import_assets.py write_tga."""
    h, w = a.shape[:2]
    bgra = a[::-1][..., [2, 1, 0, 3]].astype(np.uint8)
    with open(path, 'wb') as f:
        f.write(struct.pack('<BBBHHBHHHHBB', 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 8))
        f.write(bgra.tobytes())

def zone_map(mesh, paint_tex, W, H):
    """1 = top (#pt) garment texel, 2 = bottom (#pb), 0 = elsewhere."""
    nodes_by_mesh = {n['mesh']: n['name'] for n in mesh['nodes'] if n['mesh'] >= 0}
    z = Image.new('L', (W, H), 0); d = ImageDraw.Draw(z)
    for mi, me in enumerate(mesh['meshes']):
        if me['tex'] != paint_tex: continue
        nm = nodes_by_mesh.get(mi, '')
        val = 1 if nm.endswith('#pt') else 2 if nm.endswith('#pb') else 0
        if not val: continue
        uv = me['v'][:, 6:8]
        for k in range(0, len(me['idx']) - 2, 3):
            t = me['idx'][k:k + 3]
            d.polygon([(float(uv[j, 0]) * W, float(uv[j, 1]) * H) for j in t], fill=val, outline=val)
    return np.asarray(z)

def covered_map(mesh, texs, W, H):
    """Texels under any triangle drawn with one of texs (the rest half's and the paint half's meshes)."""
    z = Image.new('L', (W, H), 0); d = ImageDraw.Draw(z)
    for me in mesh['meshes']:
        if me['tex'] not in texs: continue
        uv = me['v'][:, 6:8]
        for k in range(0, len(me['idx']) - 2, 3):
            t = me['idx'][k:k + 3]
            d.polygon([(float(uv[j, 0]) * W, float(uv[j, 1]) * H) for j in t], fill=255, outline=255)
    return np.asarray(z) > 0

def _grow(m):
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 0

def pad_edges(rest, paint, covered, rings):
    """Edge padding. The texels under no triangle (the gutters between UV islands) were opaque in the rest
    half in the avatar's old colour, and empty in the paint half, so where bilinear filtering or a mip level
    reaches across a garment island's edge the alpha test let the rest half's gutter colour through: 1-px
    dark specks along the seams. The gutters are now shared out ring by ring (a Voronoi growth, ties to the
    rest half) between the paint texels and the rest's opaque texels; a gutter texel the paint reaches is
    paint (the mean grey of its paint neighbours, opaque) and see-through in the rest half."""
    P = (paint[..., 3] >= 128) & covered
    R = (rest[..., 3] >= 128) & covered
    gutter = ~covered
    paint[..., 3][gutter] = 0; rest[..., 3][gutter] = 255
    g = paint[..., 0].astype(np.float32) * P
    for _ in range(rings):
        free = gutter & ~P & ~R
        gp, gr = _grow(P) & free, _grow(R) & free
        gp &= ~gr
        if gp.any():
            num = np.zeros_like(g); den = np.zeros_like(g)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    num += np.roll(np.roll(g, dy, 0), dx, 1); den += np.roll(np.roll(P.astype(np.float32), dy, 0), dx, 1)
            v = np.clip(num / np.maximum(den, 1.0), 0, 255)
            g = np.where(gp, v, g)
            for c in range(3): paint[..., c][gp] = v[gp].round().astype(np.uint8)
            paint[..., 3][gp] = 255; rest[..., 3][gp] = 0
        P |= gp; R |= gr
    return int((P & gutter).sum())

def solid_regions(mask, r):
    """The connected regions of mask that contain a (2r+1)^2 square (morphological reconstruction
    of the opening): solid skin, not folds or speckle."""
    m = Image.fromarray((mask * 255).astype(np.uint8))
    seed = m.filter(ImageFilter.MinFilter(2 * r + 1)).filter(ImageFilter.MaxFilter(2 * r + 1))
    cur = np.asarray(seed) > 0
    cur &= mask
    while True:
        nxt = (np.asarray(Image.fromarray((cur * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 0) & mask
        if (nxt == cur).all(): return cur
        cur = nxt

def components(mask):
    """4-connected components of a boolean mask: a list of (ys, xs) index arrays."""
    from collections import deque
    H, W = mask.shape; seen = np.zeros_like(mask); out = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]: continue
        q = deque([(y0, x0)]); seen[y0, x0] = True; ys = []; xs = []
        while q:
            y, x = q.popleft(); ys.append(y); xs.append(x)
            for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= yy < H and 0 <= xx < W and mask[yy, xx] and not seen[yy, xx]:
                    seen[yy, xx] = True; q.append((yy, xx))
        out.append((np.array(ys), np.array(xs)))
    return out

def is_skin(rgb, min_lum, min_g):
    """A solid region is skin (or a pale whole-panel design the split keeps) when it is lit like skin:
    luminance >= min_lum and green chromaticity >= min_g. A leather fold is dark (L ~70), a pink
    shirt's flat patch has g ~0.26; the avatars' hands, forearms and necklines are L 120-175, g 0.31-0.32."""
    m = rgb.astype(np.float32).mean(axis=0); s = max(float(m.sum()), 1.0)
    return float(0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2]) >= min_lum and float(m[1]) / s >= min_g

def lum(a):
    a = a.astype(np.float32)
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]

def resplit(models, name, out, r, min_lum=100.0, min_g=0.295, rings=4):
    model, tag = name.rsplit('_', 1)
    mesh = gmsh.load(os.path.join(models, model + '.mesh'))
    body_n, paint_n = f'{name}_body.tga', f'{name}_body_paint.tga'
    rest = read_tga(os.path.join(models, body_n)); paint = read_tga(os.path.join(models, paint_n))
    H, W = rest.shape[:2]
    Z = zone_map(mesh, paint_n, W, H)
    in_paint = paint[..., 3] >= 128
    outside = (Z > 0) & ~in_paint                    # garment texels the colour cut left in the rest half
    solid = solid_regions(outside, r)               # folds, diagonals and speckle are not solid
    keep = np.zeros_like(solid)
    for ys, xs in components(solid):                # a solid region stays only if it is lit like skin
        if is_skin(rest[ys, xs, :3], min_lum, min_g): keep[ys, xs] = True
    move = outside & ~keep
    L = lum(rest)
    new_paint, new_rest = paint.copy(), rest.copy()
    report = []
    for zv in (1, 2):
        sel_old = in_paint & (Z == zv); sel_new = move & (Z == zv)
        if not sel_new.any(): continue
        g = paint[..., 0][sel_old].astype(np.float32); l = L[sel_old]
        ok = (g > 40) & (g < 250) & (l > 4)
        # g/128 = 1 - CONTRAST + CONTRAST * L/mean  ->  mean = CONTRAST*L / (g/128 - (1-CONTRAST))
        den = g[ok] / REF - (1.0 - CONTRAST)
        good = den > 0.05
        mean = float(np.median(CONTRAST * l[ok][good] / den[good])) if good.sum() > 64 else float(l.mean()) if l.size else 128.0
        rel = np.clip(L[sel_new] / max(mean, 4.0), 0.0, 3.0)
        grey = np.clip((1.0 + (rel - 1.0) * CONTRAST) * REF, 0, 255).round().astype(np.uint8)
        for c in range(3): new_paint[..., c][sel_new] = grey
        new_paint[..., 3][sel_new] = 255
        new_rest[..., 3][sel_new] = 0
        report.append(f"zone {'tb'[zv-1]}: mean {mean:.1f}, {int(sel_new.sum())} texels moved")
    print(f"{name}: garment {int((Z>0).sum())}, paint before {int(in_paint.sum())}, left in rest {int(outside.sum())}, "
          f"kept as solid skin/design {int(keep.sum())}, moved {int(move.sum())}; " + '; '.join(report))
    covered = covered_map(mesh, (body_n, paint_n), W, H)
    padded = pad_edges(new_rest, new_paint, covered, rings) if rings > 0 else 0
    print(f"  gutter texels given to the paint half: {padded}")
    os.makedirs(out, exist_ok=True)
    for n, a in ((body_n, new_rest), (paint_n, new_paint)):
        p = os.path.join(out, n)
        if os.path.lexists(p): os.remove(p)        # a new inode, never a write through a hard link
        write_tga(a, p)
    return rest, paint, new_rest, new_paint, Z, keep, move

def preview(rows, path, tint=(150, 175, 140)):
    """original | old composite under a tint | new composite | the masks (red kept skin, yellow moved)."""
    tiles = []
    t = np.array(tint, np.float32) / REF
    for rest, paint, nrest, npaint, Z, keep, move in rows:
        def comp(rs, pt):
            o = rs[..., :3].astype(np.float32).copy(); s = pt[..., 3] >= 128
            o[s] = np.clip(pt[..., :3][s].astype(np.float32) * t, 0, 255)
            return o.astype(np.uint8)
        m = np.zeros(rest.shape[:2] + (3,), np.uint8); m[Z > 0] = (60, 60, 60); m[keep] = (255, 0, 0); m[move] = (255, 255, 0)
        tiles.append(np.concatenate([rest[..., :3], comp(rest, paint), comp(nrest, npaint), m], axis=1))
    Image.fromarray(np.concatenate(tiles, axis=0)).save(path)

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('models'); ap.add_argument('names', nargs='+')
    ap.add_argument('--out', required=True); ap.add_argument('--radius', type=int, default=5)
    ap.add_argument('--min-lum', type=float, default=100.0); ap.add_argument('--min-g', type=float, default=0.295)
    ap.add_argument('--pad', type=int, default=4, help='gutter rings shared out between the halves (edge padding)')
    ap.add_argument('--preview'); ap.add_argument('--tint', default='150,175,140')
    a = ap.parse_args()
    rows = [resplit(a.models, n, a.out, a.radius, a.min_lum, a.min_g, a.pad) for n in a.names]
    if a.preview: preview(rows, a.preview, tuple(int(x) for x in a.tint.split(',')))
