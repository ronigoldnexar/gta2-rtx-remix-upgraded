#!/usr/bin/env python3
"""VEHICLE-ART-19 (qaexp13: the 054 Tank's hull drew a desaturated grey-olive with no camouflage in the street views;
the classic sprite is saturated green camo with light-green deck panels).

What: the sprite's own picture is projected straight down onto the generated body. Every covered texel of the body
atlas (UV rasterisation, uvraster.py) is mapped to its point on the mesh; the point's (x, z) picks the nose-down sprite
pixel (sprite columns -> +x, rows -> +z with the nose row at the front, livery_stripes.py's convention). The texel
takes that colour times a little of its own fine detail (its luminance over a blur of it, to the power --detail,
clipped): panel lines and hatches survive, the generator's grey undercoat and baked light do not. Faces that look
down (normal y < --under-ny) take the colour darkened by --under (the hull's belly and the track insides).
Written into the BASE half (<name>_0.tga: untinted, the camo is the sprite's art, not the record's paint) and into the
paint half's RGB where its alpha is 0 (the soft paint mask draws that RGB: geo_paint.py's rule); paint texels
(alpha > 0) are left alone. Unlinks before writing (stages share inodes). Deterministic.

  gen3d/venv/bin/python tools/vehicle_art/sprite_camo.py <models dir> <name> <sprite.png> <out dir> [--tex 054_tank_0]
"""
import argparse, os, sys
import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh_io, uvraster
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import import_assets

ap = argparse.ArgumentParser()
ap.add_argument("models"); ap.add_argument("name"); ap.add_argument("sprite"); ap.add_argument("out")
ap.add_argument("--tex", default=None, help="base texture stem (default <name>_0)")
ap.add_argument("--detail", type=float, default=0.45)
ap.add_argument("--clip", type=float, default=0.35, help="detail factor kept within 1 +- clip")
ap.add_argument("--under-ny", type=float, default=-0.35)
ap.add_argument("--under", type=float, default=0.45)
ap.add_argument("--gain", type=float, default=1.0, help="sprite colour scale (the sprite carries baked light)")
ap.add_argument("--sheet", default=None)
a = ap.parse_args()
stem = a.tex or a.name + "_0"

base = np.asarray(Image.open(os.path.join(a.models, stem + ".tga")).convert("RGBA")).astype(np.float32)
pp = os.path.join(a.models, stem + "_paint.tga")
paint = np.asarray(Image.open(pp).convert("RGBA")).astype(np.float32) if os.path.exists(pp) else None
H, W = base.shape[:2]

m = mesh_io.read(os.path.join(a.models, a.name + ".mesh"))
groups = [g for g in mesh_io.world(m) if g[1]["tex"] in (stem + ".tga", stem + "_paint.tga")]
allP = np.vstack([g[2] for g in mesh_io.world(m)])
lo, hi = allP.min(0), allP.max(0)
pos = np.zeros((H, W, 3), np.float32); nrm = np.zeros((H, W, 3), np.float32); cov = np.zeros((H, W), bool)
for (_, me, P, N, UV, F) in groups:
    p, n, c, _ = uvraster.raster(P, F, UV, H, W)
    pos[c] = p[c]; nrm[c] = n[c]; cov |= c
print("covered texels", int(cov.sum()), "of", H * W)

spr = np.asarray(Image.open(a.sprite).convert("RGBA")).astype(np.float32)
ys, xs = np.nonzero(spr[..., 3] > 128)
c0, c1, r0, r1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
rgb_s = spr[..., :3]
# pixels outside the body (alpha 0) take their nearest body pixel, so the hull's edge never samples the background
from scipy import ndimage
inside = spr[..., 3] > 128
_, (iy, ix) = ndimage.distance_transform_edt(~inside, return_indices=True)
rgb_s = rgb_s[iy, ix]
rgb_s = np.asarray(Image.fromarray(rgb_s.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))).astype(np.float32)

P = pos[cov]
col = (P[:, 0] - lo[0]) / (hi[0] - lo[0]) * (c1 - c0) + c0
row = (P[:, 2] - lo[2]) / (hi[2] - lo[2]) * (r1 - r0) + r0          # +z (nose) -> the last row (nose down)
col = np.clip(col, c0, c1 - 1).astype(int); row = np.clip(row, r0, r1 - 1).astype(int)
C = rgb_s[row, col] * a.gain

L = base[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32)
Lb = np.asarray(Image.fromarray(L.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(6))).astype(np.float32)
det = ((L + 4) / (Lb + 4)) ** a.detail
det = np.clip(det, 1 - a.clip, 1 + a.clip)[cov]
under = np.where(nrm[cov][:, 1] < a.under_ny, a.under, 1.0)
new = (C * det[:, None] * under[:, None]).clip(0, 255)

out_b = base.copy(); out_b[cov, :3] = new
# dilate into the uncovered gutter by 3 texels so mip/bilinear seams take the camo, not the old grey
filled = cov.copy()
for _ in range(3):
    grow = ndimage.binary_dilation(filled) & ~filled
    if not grow.any(): break
    _, (gy, gx) = ndimage.distance_transform_edt(~filled, return_indices=True)
    out_b[grow, :3] = out_b[gy[grow], gx[grow], :3]; filled |= grow
os.makedirs(a.out, exist_ok=True)
def save(arr, name):
    p = os.path.join(a.out, name)
    if os.path.exists(p): os.unlink(p)
    import_assets.write_tga(Image.fromarray(arr.clip(0, 255).round().astype(np.uint8), "RGBA"), p)
save(out_b, stem + ".tga")
if paint is not None:
    out_p = paint.copy(); z = paint[..., 3] == 0
    out_p[z, :3] = out_b[z, :3]
    save(out_p, stem + "_paint.tga")
if a.sheet:
    rgb = out_b[..., :3]
    Image.fromarray(np.concatenate([uvraster.views(pos, cov, base[..., :3]), uvraster.views(pos, cov, rgb)], 0).clip(0, 255).astype(np.uint8)).save(a.sheet)
print("wrote", stem, "sprite body cols", c0, c1, "rows", r0, r1)
