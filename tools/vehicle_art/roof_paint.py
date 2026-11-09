#!/usr/bin/env python3
"""VEHICLE-ART-7 (vr-roof-sprite-keeps-sprite-paint-mismatched-roof-colour): give a generated car's roof the body's
paint. The fit projected the x4 sprite onto the roof, whose paler top-down lighting kept its own hue in the
texture's untinted half: a yellow roof on a red Eddy, a tan roof on an orange Miara. The GTA2 roof panel is the
same paint as the flanks on these cars, so the roof's texels move into the paint half with the sprite's
luminance pattern only; the identity record's live tint (identity.cpp) then colours roof and flanks alike.

Works on the imported pair <name>_<k>.tga / <name>_<k>_paint.tga (binary alpha: the base is opaque where it is
"the rest", the paint twin where it is paint). Every texel is mapped to its point on the body by rasterising the
glb's UVs; a roof texel is one on an upward face (normal y > --ny) above --height of the body's top, not dark
(glass, seals: luminance < --dark), not already paint. Its paint value is its luminance, scaled so the roof's median
matches the existing paint texels' median times --lift. Geometry, UVs and the rest of the texture are untouched.

  gen3d/venv/bin/python tools/vehicle_art/roof_paint.py <body.glb> <models dir> <name> <out dir> [--tex 0]
      [--ny 0.55] [--height 0.80] [--dark 0.24] [--lift 1.06] [--preview p.png --tint r,g,b]
"""
import argparse
import os

import numpy as np
from PIL import Image


def raster(g, W, H):
    uv = g.visual.uv; V = g.vertices; F = g.faces; FN = g.face_normals
    pos = np.zeros((H, W, 3), np.float32); nrm = np.zeros((H, W, 3), np.float32); cov = np.zeros((H, W), bool)
    U = uv[:, 0] * W; Vv = (1 - uv[:, 1]) * H
    for fi, f in enumerate(F):
        x, y = U[f], Vv[f]
        x0, x1 = int(max(0, np.floor(x.min()))), int(min(W - 1, np.ceil(x.max())))
        y0, y1 = int(max(0, np.floor(y.min()))), int(min(H - 1, np.ceil(y.max())))
        if x1 < x0 or y1 < y0: continue
        X, Y = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
        if abs(d) < 1e-12: continue
        l0 = ((y[1] - y[2]) * (X - x[2]) + (x[2] - x[1]) * (Y - y[2])) / d
        l1 = ((y[2] - y[0]) * (X - x[2]) + (x[0] - x[2]) * (Y - y[2])) / d
        l2 = 1 - l0 - l1
        m = (l0 >= -0.02) & (l1 >= -0.02) & (l2 >= -0.02)
        if not m.any(): continue
        yy, xx = np.nonzero(m); yy += y0; xx += x0
        pos[yy, xx] = l0[m, None] * V[f[0]] + l1[m, None] * V[f[1]] + l2[m, None] * V[f[2]]
        nrm[yy, xx] = FN[fi]; cov[yy, xx] = True
    return pos, nrm, cov


def read_tga(p):
    return np.asarray(Image.open(p).convert("RGBA")).astype(np.float32)


def write_tga(a, p):
    if os.path.exists(p): os.unlink(p)      # assets/models shares inodes with stages
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA").save(p)


def main():
    import trimesh
    ap = argparse.ArgumentParser()
    ap.add_argument("glb"); ap.add_argument("models"); ap.add_argument("name"); ap.add_argument("out")
    ap.add_argument("--tex", type=int, default=0)
    ap.add_argument("--ny", type=float, default=0.55)
    ap.add_argument("--height", type=float, default=0.80)
    ap.add_argument("--dark", type=float, default=0.24)
    ap.add_argument("--lift", type=float, default=1.06)
    ap.add_argument("--preview", default=None); ap.add_argument("--tint", default="190,40,36")
    a = ap.parse_args()
    base_p = os.path.join(a.models, f"{a.name}_{a.tex}.tga"); paint_p = os.path.join(a.models, f"{a.name}_{a.tex}_paint.tga")
    B = read_tga(base_p); P = read_tga(paint_p)
    H, W = B.shape[:2]
    scene = trimesh.load(a.glb, force="scene")
    g = next(iter(scene.geometry.values()))
    pos, nrm, cov = raster(g, W, H)
    top = g.vertices[:, 1].max()
    is_paint = P[..., 3] > 127
    rest = B[..., :3] / 255.0
    lum = 0.30 * rest[..., 0] + 0.59 * rest[..., 1] + 0.11 * rest[..., 2]
    mx = rest.max(2); mn = rest.min(2); sat = (mx - mn) / np.maximum(mx, 1e-3)
    chrome = (sat < 0.14) & (lum > 0.55)
    roof = cov & (nrm[..., 1] > a.ny) & (pos[..., 1] > a.height * top) & ~is_paint & (lum > a.dark) & ~chrome
    # grow one texel into the roof's own neighbours (bilinear filtering at the seam) only where they are roof-like too
    pl = 0.30 * P[..., 0] + 0.59 * P[..., 1] + 0.11 * P[..., 2]
    ref = np.median(pl[is_paint & cov]) if (is_paint & cov).any() else 200.0
    r_med = np.median(lum[roof]) * 255.0 if roof.any() else 1.0
    k = ref * a.lift / max(r_med, 1.0)
    val = np.clip(lum * 255.0 * k, 0, 255)
    B2 = B.copy(); P2 = P.copy()
    B2[roof, 3] = 0
    P2[roof, 0] = P2[roof, 1] = P2[roof, 2] = val[roof]
    P2[roof, 3] = 255
    os.makedirs(a.out, exist_ok=True)
    write_tga(B2, os.path.join(a.out, os.path.basename(base_p))); write_tga(P2, os.path.join(a.out, os.path.basename(paint_p)))
    print(f"{a.name}: {int(roof.sum())} roof texels moved to the paint ({roof.sum() / max(cov.sum(), 1) * 100:.1f} % of the body), "
          f"roof lum median {r_med:.0f} -> paint median {ref:.0f} x {a.lift}")
    if a.preview:
        tint = np.array([float(c) for c in a.tint.split(",")]) / 255.0
        own = np.mean(P[is_paint & cov][:, :3], 0) / 255.0
        def comp(Bx, Px):
            pm = Px[..., 3:4] > 127
            col = np.where(pm, Px[..., :3] / 255.0 * tint / np.maximum(own, 1e-3), Bx[..., :3] / 255.0)
            return np.clip(col, 0, 1)
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from preview import render
        from PIL import ImageDraw
        Nw = g.vertex_normals
        tiles = []
        for Bx, Px in ((B, P), (B2, P2)):
            rgb = comp(Bx, Px)[::-1].copy().astype(np.float32)
            grp = [dict(V=g.vertices * 5.0, N=Nw, UV=g.visual.uv, F=g.faces.astype(np.int32), rgb=rgb)]
            for v in (dict(eye=(4.0, 3.2, 5.0), tgt=(0, 0.8, 0), fov=42), dict(eye=(-2.0, 4.5, -6.5), tgt=(0, 0.8, 0.3), fov=45),
                      dict(ortho=(3.2, 5.6), eye=(0, 20, 0), tgt=(0, 0, 0), up=(0, 0, -1))):
                tiles.append(render(grp, dict(v, halfw=1.2, halfl=2.5), size=(420, 300)))
        S = Image.new("RGB", (420 * 3, 600))
        for i, t in enumerate(tiles):
            S.paste(t, ((i % 3) * 420, (i // 3) * 300))
        ImageDraw.Draw(S).text((6, 4), f"{a.name} before (top) / after, tint {a.tint}", fill=(255, 255, 0))
        S.save(a.preview)


if __name__ == "__main__":
    main()
