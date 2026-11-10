#!/usr/bin/env python3
"""VEHICLE-ART-8: preview a generated car's glb with a (base, paint) texture pair from assets/models style files,
the paint tinted by the sprite colour: the same composite the renderer draws (identity.cpp tint on the _paint half).
  gen3d/venv/bin/python tools/vehicle_art/preview_pair.py <glb> <base.tga> <paint.tga> <out.png> [r,g,b] [length_m] [sprite.png]"""
import os, sys
import numpy as np, trimesh
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preview

glb, bp, pp, out = sys.argv[1:5]
tint = np.array([float(t) for t in (sys.argv[5] if len(sys.argv) > 5 else "139,87,45").split(",")])
Lm = float(sys.argv[6]) if len(sys.argv) > 6 else 4.4
sprite = sys.argv[7] if len(sys.argv) > 7 else None
groups = []
B = np.asarray(Image.open(bp).convert("RGBA")).astype(np.float32) / 255
P = np.asarray(Image.open(pp).convert("RGBA")).astype(np.float32) / 255
a = P[..., 3:]
comp = B[..., :3] * (1 - a) + P[..., :3] * (tint / 235.0) * a
sc = trimesh.load(glb, force="scene")
k = Lm / 1.0
for gname, g in sc.geometry.items():
    V = np.asarray(g.vertices, np.float32) * k
    uv = np.asarray(g.visual.uv, np.float32).copy()
    tex = comp if len(g.faces) == max(len(q.faces) for q in sc.geometry.values()) else \
        np.asarray(g.visual.material.baseColorTexture.convert("RGB")).astype(np.float32) / 255
    groups.append(dict(V=V, N=np.asarray(g.vertex_normals, np.float32), UV=uv, F=np.asarray(g.faces, np.int32), rgb=np.ascontiguousarray(tex[::-1])))
lo, hi = np.vstack([gg["V"] for gg in groups]).min(0), np.vstack([gg["V"] for gg in groups]).max(0)
preview.sheet(groups, hi[2] - lo[2], hi[0] - lo[0], hi[1] - lo[1], sprite, out, title=os.path.basename(pp))
