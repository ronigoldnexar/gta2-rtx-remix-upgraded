#!/usr/bin/env python3
"""VEHICLE-ART-8 (pmm1: the bil 082 Jagular XK was orange only on its roof and bonnet; boot, rear wings and flanks
near-black teal): re-split a generated (image-to-3D) car's paint by GEOMETRY, not by colour.

Why: tools/car_paint_resplit.py picks the paint by the body's hue. Many generated cars were baked with deep shading,
so the shaded half of the body (the boot, the rear wings, the lower flanks and valances) is near-black: no hue, so it
stays in the untinted half, and the car in 3D shows the generator's dark undercoat with patches of the sprite's colour.

What: every texel of the body atlas is mapped to its point and normal on the mesh (UV rasterisation, uvraster.py).
A texel is paint when it lies on the outer shell and is not part of something else:
  - shell: covered, not on the underside (normal y > --under-ny), above the sills (y > --sill of the height);
  - not a wheel: outside a cylinder round each axle (axles found from the ground-contact vertices; --wheel-r is
    the tyre radius as a share of the car's length) on the outer --wheel-x of the half width;
  - not glass, chrome, lamps or whitewalls: texels that are bright and grey (chrome, glass, whitewalls: lum >
    --keep-lum, saturation < --keep-sat) or strongly coloured in another hue than the body (lamps, badges) keep
    their colour; dark texels (the undercoat) and texels of the body's hue are paint;
  - not the grille: --grille "x0,x1,y0,y1" (shares of half width / height) on the front face keeps its colour;
  - --glass-zone "y0" plus --glass-ny: texels above y0 (share of height) that face sideways or fore/aft
    (|ny| < --glass-ny) keep their colour: the window band of a car whose glass is dark.
The paint is written neutral and nearly flat: --level times (1 + the texel's fine detail, a high-pass of the
original luminance clipped to +---detail): panel lines and badges survive, the generator's baked light and
undercoat do not (the renderer lights the car). The base half keeps the original colours with alpha = 1 - paint
alpha (the importer's convention); so does the paint half outside the paint (the soft-mask draw shows a coverage-0
texel's own RGB: model_store.cpp softPaint). Output: <out>/<name>_0.tga and _0_paint.tga (unlink before write: stages share
inodes) and <out>/<name>_geo_paint_check.png (side/top/front/rear/rear-3/4 splats: tinted composite, then the mask).

  gen3d/venv/bin/python tools/vehicle_art/geo_paint.py <glb> <models dir> <name> <out dir> [--tint r,g,b] [options]
"""
import argparse
import os
import struct
import sys

import numpy as np
import trimesh
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvraster import raster, views  # noqa


def write_tga(arr, path):
    if os.path.lexists(path):
        os.unlink(path)
    px = np.clip(arr + 0.5, 0, 255).astype(np.uint8)[::-1][..., [2, 1, 0, 3]]
    h, w = px.shape[:2]
    with open(path, "wb") as f:
        f.write(struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 8))
        f.write(px.tobytes())


def hsv(rgb):
    mx = rgb.max(-1); mn = rgb.min(-1); dl = np.maximum(mx - mn, 1e-6)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    h = np.where(mx == r, ((g - b) / dl) % 6, np.where(mx == g, (b - r) / dl + 2, (r - g) / dl + 4)) * 60.0
    return h, (mx - mn) / np.maximum(mx, 1.0), mx


def box_blur(img, r):
    out = img.astype(np.float64)
    for ax in (0, 1):
        for _ in range(3):
            c = np.cumsum(np.pad(out, [(r + 1, r) if i == ax else (0, 0) for i in range(2)], mode="edge"), axis=ax)
            out = (np.take(c, range(2 * r + 1, c.shape[ax]), axis=ax) - np.take(c, range(0, c.shape[ax] - 2 * r - 1), axis=ax)) / (2 * r + 1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb"); ap.add_argument("models"); ap.add_argument("name"); ap.add_argument("out")
    ap.add_argument("--tint", default="139,87,45", help="preview tint (the sprite's paint) for the check sheet")
    ap.add_argument("--level", type=float, default=200.0)
    ap.add_argument("--detail", type=float, default=0.18)
    ap.add_argument("--under-ny", type=float, default=-0.45)
    ap.add_argument("--sill", type=float, default=0.10)
    ap.add_argument("--wheel-r", type=float, default=0.085)
    ap.add_argument("--wheel-x", type=float, default=0.30)
    ap.add_argument("--keep-lum", type=float, default=120.0)
    ap.add_argument("--keep-sat", type=float, default=0.22)
    ap.add_argument("--hue", type=float, default=None, help="body hue (deg); default: histogram peak of shell texels")
    ap.add_argument("--hue-tol", type=float, default=40.0)
    ap.add_argument("--other-sat", type=float, default=0.45, help="texels of another hue at least this saturated keep their colour")
    ap.add_argument("--grille", default="", help="x0,x1,y0,y1 on the front face (shares of half width / height) kept")
    ap.add_argument("--rear-keep", default="", help="x0,x1,y0,y1 on the rear face kept (a plate, lamps)")
    ap.add_argument("--glass-zone", type=float, default=None)
    ap.add_argument("--glass-ny", type=float, default=0.55)
    ap.add_argument("--glass-lum", type=float, default=999.0, help="in the glass zone only texels darker than this are kept as glass")
    ap.add_argument("--chrome-ends", type=float, default=None,
                    help="bright grey texels stay out of the paint only beyond this share of the half length (bumpers), in the "
                         "glass zone (window frames) or below --chrome-low of the height; elsewhere they are baked highlights: paint")
    ap.add_argument("--chrome-low", type=float, default=0.0)
    ap.add_argument("--gutter", type=int, default=6, help="texels of uncovered gutter round painted islands that take the paint")
    ap.add_argument("--grille-lum", type=float, default=60.0, help="in the grille zone texels darker than this keep their colour")
    a = ap.parse_args()

    sc = trimesh.load(a.glb, force="scene")
    g = max(sc.geometry.values(), key=lambda q: len(q.faces))
    base_p = os.path.join(a.models, f"{a.name}_0.tga")
    B = np.asarray(Image.open(base_p).convert("RGBA")).astype(np.float32)
    H, W = B.shape[:2]
    T = np.asarray(g.visual.material.baseColorTexture.convert("RGB").resize((W, H), Image.LANCZOS)).astype(np.float32)
    pos, nrm, cov, _ = raster(np.asarray(g.vertices, np.float64), np.asarray(g.faces), np.asarray(g.visual.uv), H, W)
    lo, hi = g.bounds
    hgt = hi[1] - lo[1]; hw = max(-lo[0], hi[0]); length = hi[2] - lo[2]
    px, py, pz = pos[..., 0], pos[..., 1] - lo[1], pos[..., 2]
    nx, ny, nz = nrm[..., 0], nrm[..., 1], nrm[..., 2]

    # axles from the ground-contact vertices (front and rear halves)
    V = np.asarray(g.vertices)
    low = V[V[:, 1] < lo[1] + 0.03 * hgt]
    zf = low[low[:, 2] > 0][:, 2].mean() if (low[:, 2] > 0).any() else 0.3 * length
    zr = low[low[:, 2] < 0][:, 2].mean() if (low[:, 2] < 0).any() else -0.3 * length
    r = a.wheel_r * length
    wheel = np.zeros_like(cov)
    for zc in (zf, zr):
        wheel |= (np.hypot(py - r, pz - zc) < r * 1.10) & (np.abs(px) > hw * (1 - a.wheel_x))

    lum = T.mean(-1)
    h, s, mx = hsv(T)
    shell = cov & (ny > a.under_ny) & (py > a.sill * hgt) & ~wheel
    if a.hue is None:
        lit = shell & (mx > 50) & (s > 0.12)
        hist, _ = np.histogram(h[lit], bins=36, range=(0, 360))
        sm = hist + 0.5 * (np.roll(hist, 1) + np.roll(hist, -1))
        hue = (int(np.argmax(sm)) + 0.5) * 10.0
    else:
        hue = a.hue
    dh = np.abs((h - hue + 180.0) % 360.0 - 180.0)
    bright_grey = (lum > a.keep_lum) & (s < a.keep_sat)
    other_colour = (dh > a.hue_tol) & (s > a.other_sat) & (mx > 70)
    if a.chrome_ends is not None:
        halfl = length / 2
        gz = (py > (a.glass_zone if a.glass_zone is not None else 9) * hgt) & (np.abs(ny) < a.glass_ny)
        bright_grey &= (np.abs(pz) > a.chrome_ends * halfl) | gz | (py < a.chrome_low * hgt)
    keep = bright_grey | other_colour
    def zone(spec, face):
        if not spec:
            return np.zeros_like(cov)
        x0, x1, y0, y1 = [float(t) for t in spec.split(",")]
        return face & (np.abs(px) >= x0 * hw) & (np.abs(px) <= x1 * hw) & (py >= y0 * hgt) & (py <= y1 * hgt)
    keep |= zone(a.grille, nz > 0.5) & ((lum < a.grille_lum) | ((lum > a.keep_lum) & (s < a.keep_sat)))
    keep |= zone(a.rear_keep, nz < -0.5)
    if a.glass_zone is not None:
        keep |= (py > a.glass_zone * hgt) & (np.abs(ny) < a.glass_ny) & (lum < a.glass_lum)
    paint = shell & ~keep
    # fill single-texel holes in the paint (a speck of chrome-grey inside a panel) and drop isolated paint specks
    pf = paint.astype(np.float32)
    nb = box_blur(pf, 1)
    paint = (paint | (nb > 0.80)) & shell & ~(nb < 0.20)

    grey = 0.30 * T[..., 0] + 0.59 * T[..., 1] + 0.11 * T[..., 2]
    m = paint.astype(np.float32)
    lowf = box_blur(grey * m, 3) / np.maximum(box_blur(m, 3), 1e-3)
    hp = np.clip((grey - lowf) / np.maximum(lowf, 20.0), -a.detail, a.detail * 0.5)
    pv = a.level * (1 + hp)
    # gutter: the uncovered texels round each painted UV island take the nearest paint (6 texels out), or bilinear and
    # mip sampling at an island's edge blend the generator's pale/teal gutter into the panel (pale seams in game)
    pv = np.where(paint, pv, 0.0)
    filled = paint.copy()
    for _ in range(a.gutter):
        acc = np.zeros((H, W), np.float64); cnt = np.zeros((H, W), np.float64)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            acc += np.roll(np.roll(np.where(filled, pv, 0.0), dy, 0), dx, 1)
            cnt += np.roll(np.roll(filled, dy, 0), dx, 1)
        grow = ~filled & ~cov & (cnt > 0)
        pv = np.where(grow, acc / np.maximum(cnt, 1), pv)
        filled |= grow
    gutter = filled & ~paint
    paint = filled
    newP = np.zeros((H, W, 4), np.float32); newB = np.zeros((H, W, 4), np.float32)
    # outside the paint the _paint texture keeps the original colours: with car_paint_soft_mask the renderer draws the
    # paint mesh opaque as texel * lerp(1, tint, coverage), so a texel of coverage 0 shows its own RGB (black if 0)
    for c in range(3):
        newP[..., c] = np.where(paint, pv, T[..., c])
    newP[..., 3] = np.where(paint, 255, 0)
    newB[..., :3] = T
    newB[..., 3] = np.where(paint, 0, 255)
    os.makedirs(a.out, exist_ok=True)
    write_tga(newP, os.path.join(a.out, f"{a.name}_0_paint.tga"))
    write_tga(newB, os.path.join(a.out, f"{a.name}_0.tga"))
    tint = np.array([float(t) for t in a.tint.split(",")]) / 235.0
    comp = np.where(paint[..., None], newP[..., :3] * tint, T)
    mk = np.zeros_like(T); mk[..., 0] = paint * 255; mk[..., 1] = keep * cov * 200; mk[..., 2] = wheel * 255
    sheet = np.concatenate([views(pos, cov, comp), views(pos, cov, mk)], 0)
    Image.fromarray(np.clip(sheet, 0, 255).astype(np.uint8)).save(os.path.join(a.out, f"{a.name}_geo_paint_check.png"))
    A = g.area_faces
    sh = (pos[..., 1] - lo[1] > 0.30 * hgt) & (ny > -0.3) & cov
    print(f"{a.name}: body hue {hue:.0f}, axles z {zf:.3f} {zr:.3f} r {r:.3f}; paint {int(paint.sum())} texels "
          f"({paint[sh].mean() * 100:.1f}% of the upper shell texels, was {(np.asarray(Image.open(os.path.join(a.models, a.name + '_0_paint.tga')).convert('RGBA'))[..., 3] > 127)[sh].mean() * 100:.1f}%)")


if __name__ == "__main__":
    main()
