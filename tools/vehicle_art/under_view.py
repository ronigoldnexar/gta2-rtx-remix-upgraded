#!/usr/bin/env python3
"""VEHICLE-ART-13: offline sheet of a shipped car's underside (the .mesh + its .tga files as the game loads them):
upright from a low eye under the sill, flipped (rolled 180 deg, as a car on its roof) from above at 3/4 and straight
down. Paint halves tinted by r,g,b / 235 as the identity record does.
  gen3d/venv/bin/python tools/vehicle_art/under_view.py <models_dir> <name> <out.png> [r,g,b] [length_m]"""
import os, sys
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh_io, preview

d, name, out = sys.argv[1:4]
tint = np.array([float(t) for t in (sys.argv[4] if len(sys.argv) > 4 else "150,110,90").split(",")])
Lm = float(sys.argv[5]) if len(sys.argv) > 5 else 5.0


def tga(n):
    im = Image.open(os.path.join(d, n)).convert("RGBA")
    w = 1 << max(6, (max(im.size) - 1).bit_length())          # power of two, >= 64 (the preview's mip chain)
    return np.asarray(im.resize((w, w), Image.BILINEAR)).astype(np.float32) / 255


def groups(flip):
    m = mesh_io.read(os.path.join(d, name + ".mesh"))
    W = mesh_io.world(m)
    gs = []
    for i, (n, me, P, N, UV, F) in enumerate(W):
        tex = me["tex"]
        if tex.endswith("_glass.tga"):
            continue
        im = tga(tex)
        if tex.endswith("_paint.tga"):
            base = tex[:-10] + ".tga"
            if os.path.exists(os.path.join(d, base)) and any(w[1]["tex"] == base and len(w[2]) == len(P) for w in W):
                continue                      # composited onto its base below
            rgb = im[..., :3] * tint / 235.0
        else:
            rgb = im[..., :3]
            pp = tex[:-4] + "_paint.tga"
            if any(w[1]["tex"] == pp and len(w[2]) == len(P) for w in W):
                pa = tga(pp); a = pa[..., 3:]
                rgb = rgb * (1 - a) + pa[..., :3] * tint / 235.0 * a
        V = P * Lm; Nn = N.copy()
        if flip:                               # roll 180 about the length axis, roof on the ground
            V = V * np.array([-1, -1, 1]); Nn = Nn * np.array([-1, -1, 1]); V[:, 1] -= V[:, 1].min() if False else 0
        gs.append(dict(V=V.astype(np.float32), N=Nn.astype(np.float32), UV=UV.astype(np.float32),
                       F=F[:, ::-1].astype(np.int32) if False else F.astype(np.int32), rgb=np.ascontiguousarray(rgb[::-1])))
    if flip:
        lo = min(g["V"][:, 1].min() for g in gs)
        for g in gs: g["V"][:, 1] -= lo
    return gs


up = groups(False); fl = groups(True)
allv = np.vstack([g["V"] for g in up]); lo, hi = allv.min(0), allv.max(0)
hl, hw, H = (hi[2] - lo[2]) / 2, (hi[0] - lo[0]) / 2, hi[1] - lo[1]
views = [
    (up, dict(name="upright, eye 0.15 m beside the sill", eye=(hw + 2.2, 0.15, 1.2), tgt=(0, 0.25, 0), fov=55), True),
    (fl, dict(name="flipped, 3/4 above", eye=(hw + 2.6 * max(1, hl / 2.5), H + 2.2 * max(1, hl / 2.5), hl + 2.0 * max(1, hl / 2.5)), tgt=(0, 0.6 * H, 0), fov=45), True),
    (fl, dict(name="flipped, chase 3/4 rear", eye=(-hw - 1.8 * max(1, hl / 2.5), H + 2.5 * max(1, hl / 2.5), -hl - 3.0 * max(1, hl / 2.5)), tgt=(0, 0.6 * H, 0), fov=45), True),
]
tiles = []
for g, v, gr in views:
    v.setdefault("halfw", hw); v.setdefault("halfl", hl)
    im = preview.render(g, v, ground=gr)
    ImageDraw.Draw(im).text((6, 4), v["name"], fill=(0, 0, 0)); tiles.append(im)
top = preview.render(fl, dict(ortho=(hw * 2.3, hl * 2.16), eye=(0, 20, 0), tgt=(0, 0, 0), up=(0, 0, -1), halfw=hw, halfl=hl),
                     size=(int(400 * hw / hl * 1.15 / 1.08), 400), ground=False)
tw, th = tiles[0].size
S = Image.new("RGB", (tw * 2 + top.width + 10, th * 2 + 20), (40, 40, 40))
for i, t in enumerate(tiles):
    S.paste(t, ((i % 2) * tw, 20 + (i // 2) * th))
S.paste(top, (tw * 2 + 10, 20))
ImageDraw.Draw(S).text((6, 4), f"{name} underside (flipped top view: nose down)", fill=(255, 255, 255))
S.save(out)
print(out)
