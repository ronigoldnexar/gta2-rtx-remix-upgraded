#!/usr/bin/env python3
"""VEHICLE-ART-28: ortho side view (+x camera) of a .mesh incl. underpan, painter by depth, textured by mean colour of tga, flat sun shade.
usage: side_view.py <models dir> <name> <out.png> [zoom_z0 zoom_z1 y1]"""
import sys, os, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vehicle_art"))
import mesh_io
from PIL import Image, ImageDraw
d, name, out = sys.argv[1:4]
m = mesh_io.read(os.path.join(d, name + ".mesh"))
W = mesh_io.world(m)
P = np.concatenate([w[2] for w in W]); lo, hi = P.min(0), P.max(0)
z0, z1, y1 = (float(a) for a in sys.argv[4:7]) if len(sys.argv) > 6 else (lo[2], hi[2], hi[1])
S = 1600 / (z1 - z0); H = int((y1 - lo[1]) * S) + 20
im = Image.new("RGB", (1600, H), (90, 140, 200)); dr = ImageDraw.Draw(im)
tris = []
cache = {}
for n, me, Pw, Nw, UV, F in W:
    t = me["tex"]
    if t not in cache:
        try:
            a = np.asarray(Image.open(os.path.join(d, t)).convert("RGB"))
            cache[t] = a
        except Exception: cache[t] = np.full((4, 4, 3), 255, np.uint8)
    a = cache[t]
    for f in F:
        p = Pw[f]
        if p[:, 0].max() < -0.02: continue   # camera at +x: skip far side parts
        nrm = np.cross(p[1] - p[0], p[2] - p[0]); ln = np.linalg.norm(nrm)
        if ln < 1e-12: continue
        nrm /= ln
        uv = UV[f].mean(0) % 1.0
        c = a[int(uv[1] * (a.shape[0] - 1)), int(uv[0] * (a.shape[1] - 1))].astype(float)
        sh = 0.45 + 0.55 * abs(nrm @ np.array([0.6, 0.6, 0.3]) / np.linalg.norm([0.6, 0.6, 0.3]))
        tris.append((p[:, 0].mean(), [((q[2] - z0) * S, H - 10 - (q[1] - lo[1]) * S) for q in p], tuple((c * sh).clip(0, 255).astype(int)), t))
tris.sort(key=lambda x: x[0])
for _, pts, col, t in tris:
    dr.polygon(pts, fill=col)
im.save(out); print(out, im.size, len(tris))
