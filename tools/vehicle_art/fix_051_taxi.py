#!/usr/bin/env python3
"""VEHICLE-ART-6 (vr-taxi-056-051-chequer-band-torn-blotch): repaint the 051 Taxi Xpress's generated texture in
object space. TRELLIS smeared the sprite's chequers into torn blotches: a "QR code" patch on each rear door, a
blotch on the bonnet, broken squares on the roof and a smeared belt band. Every texel is mapped to its point on the
body (UV rasterisation of the glb), then:
  - the belt band (side-facing, y 0.200-0.238) is redrawn as two clean rows of black/white squares;
  - the door patches and the bonnet/roof blotches go back to the body's own yellow;
  - a chequered centre stripe (the sprite's, |x| < 0.042) runs over the bonnet, roof and boot tops.
Geometry and UVs are untouched; the importer's paint split then takes the yellow as paint.
  gen3d/venv/bin/python tools/vehicle_art/fix_051_taxi.py <in.glb> <out.glb>
"""
import io, sys
import numpy as np
import trimesh
from PIL import Image

src, out = sys.argv[1], sys.argv[2]
scene = trimesh.load(src, force="scene")
name, g = next(iter(scene.geometry.items()))
mat = g.visual.material
img = np.asarray(mat.baseColorTexture.convert("RGB")).astype(np.float32) / 255.0
H, W = img.shape[:2]
# 0. the boot lid: TRELLIS stood it up behind the rear window as a torn fin to 0.42 (above the roof); with no other
# boot top under it, cutting it opens the boot, so its vertices fold down onto the boot line (0.255), the faces
# that end up facing down are turned over, and its texels are painted as body (below).
Vn = g.vertices.copy()
lidv = (Vn[:, 2] < -0.305) & (Vn[:, 1] > 0.255)
Vn[lidv, 1] = 0.255 - 0.004 * np.clip((Vn[lidv, 2] + 0.305) / -0.19, 0, 1)
g.vertices = Vn
lidf = lidv[g.faces].any(1)
Fx = g.faces.copy()
down = lidf & (g.face_normals[:, 1] < 0)
Fx[down] = Fx[down][:, ::-1]
g.faces = Fx
print("lid vertices folded", int(lidv.sum()), "faces", int(lidf.sum()), "turned over", int(down.sum()))
uv = g.visual.uv; V = g.vertices; F = g.faces; FN = g.face_normals
fid = np.full((H, W), -1, np.int64); pos = np.zeros((H, W, 3), np.float32); nrm = np.zeros((H, W, 3), np.float32); cov = np.zeros((H, W), bool)
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
    e = -0.02
    m = (l0 >= e) & (l1 >= e) & (l2 >= e)
    if not m.any(): continue
    yy, xx = np.nonzero(m); yy += y0; xx += x0
    P = l0[m, None] * V[f[0]] + l1[m, None] * V[f[1]] + l2[m, None] * V[f[2]]
    pos[yy, xx] = P; nrm[yy, xx] = FN[fi]; cov[yy, xx] = True; fid[yy, xx] = fi

px, py, pz = pos[..., 0], pos[..., 1], pos[..., 2]
nx, ny = nrm[..., 0], nrm[..., 1]
mx = img.max(2); mn = img.min(2); sat = (mx - mn) / np.maximum(mx, 1e-3); lum = img.mean(2)
yellow = cov & (sat > 0.45) & (img[..., 0] > 0.55) & (img[..., 1] > 0.40) & (img[..., 2] < 0.45)
paint = np.median(img[yellow], axis=0)
print("paint", (paint * 255).round(), "yellow texels", int(yellow.sum()))
rng = np.random.default_rng(1)
def put_paint(m, keep_shade=True):
    # the body's yellow, keeping a little of the texel's own shading so it does not read flat (not over a
    # patterned patch: its dots would stay as darker spots)
    shade = np.clip(lum[m] / max(paint.mean(), 1e-3), 0.85, 1.08) if keep_shade else np.full(int(m.sum()), 0.97)
    img[m] = np.clip(paint[None, :] * shade[:, None] * (1 + 0.015 * rng.standard_normal(m.sum()))[:, None], 0, 1)
WHITE, BLACK = np.array([0.92, 0.91, 0.87]), np.array([0.07, 0.07, 0.08])
side = cov & (np.abs(nx) > 0.45)
top = cov & (ny > 0.55)
offpaint = ~yellow
# 1. door "QR" patches and anything chequer-like on the flanks under the band -> paint
put_paint(side & (py > 0.105) & (py < 0.200) & (pz > -0.30) & (pz < 0.30) & offpaint & (lum > 0.12))
put_paint(side & (py > 0.105) & (py < 0.200) & (pz > -0.30) & (pz < 0.30) & offpaint & (lum <= 0.12) & (np.abs(px) > 0.24))
# the rear doors' patch itself, dots and all (its dark dots are a dull yellow the colour test calls paint)
put_paint(side & (py > 0.112) & (py < 0.199) & (pz > -0.23) & (pz < -0.04), keep_shade=False)
# 2. bonnet blotch and roof chequer remnants -> paint (outside the stripe)
stripe = np.abs(px) < 0.042
put_paint(top & (pz > 0.20) & (pz < 0.46) & (np.abs(px) < 0.16) & offpaint & ~stripe, keep_shade=False)
roof = top & (py > 0.36) & (pz > -0.26) & (pz < 0.20)
sign = roof & (np.abs(px) < 0.075) & (pz > -0.15) & (pz < 0.06)
put_paint(roof & offpaint & ~stripe & ~sign & ((lum > 0.55) | (sat < 0.25)))
# the folded lid: body paint (flat: its texels were the lid's torn edge and underside)
lidt = cov & (fid >= 0) & lidf[np.maximum(fid, 0)]
put_paint(lidt, keep_shade=False)
# 3. the belt band: two rows of squares, s = band height / 2
y0b, y1b = 0.200, 0.242; s = (y1b - y0b) / 2
band = side & (py >= y0b) & (py < y1b) & (pz > -0.48) & (pz < 0.43)
chk = (np.floor(pz / s) + np.floor((py - y0b) / s)).astype(int) % 2 == 0
img[band & chk] = BLACK; img[band & ~chk] = WHITE
# 4. the centre stripe: bonnet, roof (round the sign) and boot, 3 squares across
ss = 0.028
flat = cov & (ny > 0.82)   # the stripe stays on the flat tops: not down the nose, not over the screen header
st = flat & stripe & (((pz > 0.20) & (pz < 0.46)) | (roof & ~sign) | ((pz < -0.30) & (pz > -0.50)) | (lidt & stripe))
chk2 = (np.floor((px + 0.042) / ss) + np.floor(pz / ss)).astype(int) % 2 == 0
img[st & chk2] = BLACK; img[st & ~chk2] = WHITE
print("band texels", int(band.sum()), "stripe texels", int(st.sum()))
im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
mat.baseColorTexture = im
scene.export(out)
im.save(out[:-4] + "_tex.png")
