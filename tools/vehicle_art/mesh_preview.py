#!/usr/bin/env python3
"""VEHICLE-ART-20: offline preview sheet of a SHIPPED car .mesh (assets/models), its textures as the game
composes them (a base texture's see-through texels show its _paint twin times the tint), framed by preview.sheet.

  mesh_preview.py <models dir> <stem> <out.png> [R,G,B tint] [sprite.png]
"""
import os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh_io, preview


def groups_for(mdir, stem, tint=(235, 235, 235)):
    m = mesh_io.read(os.path.join(mdir, stem + ".mesh"))
    gs = []
    t = np.asarray(tint, float) / 235.0
    for n, me, P, N, UV, F in mesh_io.world(m):
        tex = me["tex"]
        if tex.endswith("_paint.tga") and os.path.exists(os.path.join(mdir, tex.replace("_paint.tga", ".tga"))):
            continue   # drawn with its base below
        p = os.path.join(mdir, tex)
        a = np.asarray(Image.open(p).convert("RGBA"), np.float32) / 255.0 if os.path.exists(p) else np.ones((4, 4, 4), np.float32)
        rgb = a[..., :3].copy()
        tw = os.path.join(mdir, tex[:-4] + "_paint.tga")
        if tex.endswith("_paint.tga"):
            rgb = rgb * t
        elif os.path.exists(tw):
            b = np.asarray(Image.open(tw).convert("RGBA"), np.float32) / 255.0
            if b.shape == a.shape:
                k = (a[..., 3:4] >= 0.5)
                rgb = np.where(k, a[..., :3], b[..., :3] * t)
        gs.append(dict(V=P, N=N, UV=UV, F=F, rgb=np.ascontiguousarray(rgb), name="paint" if "_paint" in tex else tex))
    return gs


if __name__ == "__main__":
    mdir, stem, out = sys.argv[1:4]
    tint = tuple(float(x) for x in sys.argv[4].split(",")) if len(sys.argv) > 4 and sys.argv[4] else (235, 235, 235)
    sprite = sys.argv[5] if len(sys.argv) > 5 else None
    gs = groups_for(mdir, stem, tint)
    V = np.vstack([g["V"] for g in gs]); lo, hi = V.min(0), V.max(0); ext = hi - lo
    # preview frames a car of ~4.4 m centred at the origin on y=0: scale to that
    L = max(ext[0], ext[2]); s = 4.4 / L
    for g in gs:
        g["V"] = (g["V"] - np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])) * s
    e = ext * s
    preview.sheet(gs, max(e[0], e[2]), min(e[0], e[2]), e[1], sprite_path=sprite, out=out, title=f"{stem} (shipped mesh, scaled to 4.4 m)")
