#!/usr/bin/env python3
"""VEHICLE-ART-7 (vr-generated-bodies-hard-facets): iron the crumples out of an image-to-3D body's panels.

TRELLIS bodies carry real dents in their geometry (the 050 B-Type's bonnet and wings: ripples of 1-3 cm a few
faces wide), which smoothed normals (33c34be) cannot hide: the silhouette and the light still show them. This
moves the body's vertices ALONG THEIR NORMALS only (a Taubin lambda/mu pass of the normal component of the
umbrella Laplacian, over the mesh welded across its UV seams), so the panels relax into smooth pressed-steel
curves while nothing slides across the texture: UVs, triangles, materials and every other mesh in the glb
(add_lamps.py pods) are byte-for-byte the same. The imported textures stay valid: re-import and copy only the
.mesh file.

Where it works is a weight per vertex (0..1): a box in glb units, feathered, minus keep-out cylinders along z
(lamps, which add_lamps.py sat on the blob's front). Mesh boundary vertices never move.

  gen3d/venv/bin/python tools/vehicle_art/smooth_shell.py <in.glb> <out.glb> [--mesh 0] [--iters 30]
      [--box x0,x1,y0,y1,z0,z1] [--feather 0.02] [--keep x,y,r ...] [--max-move 0.012] [--preview p.png]
"""
import argparse
import json
import struct
import sys

import numpy as np


def read_glb(path):
    d = open(path, "rb").read()
    assert d[:4] == b"glTF"
    jl = struct.unpack("<I", d[12:16])[0]
    j = json.loads(d[20:20 + jl])
    off = 20 + jl
    bl = struct.unpack("<I", d[off:off + 4])[0]
    binc = bytearray(d[off + 8:off + 8 + bl])
    return d, j, binc, off + 8


def acc_view(j, binc, ai):
    a = j["accessors"][ai]
    bv = j["bufferViews"][a["bufferView"]]
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    dt = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}[a["componentType"]]
    assert bv.get("byteStride", 0) in (0, ncomp * np.dtype(dt).itemsize)
    arr = np.frombuffer(bytes(binc[start:start + a["count"] * ncomp * np.dtype(dt).itemsize]), dt).reshape(a["count"], ncomp)
    return arr.copy(), start


def weights(P, a):
    w = np.ones(len(P))
    if a.box:
        x0, x1, y0, y1, z0, z1 = [float(v) for v in a.box.split(",")]
        f = a.feather
        for k, (lo, hi) in enumerate(((x0, x1), (y0, y1), (z0, z1))):
            t = np.minimum((P[:, k] - lo) / f, (hi - P[:, k]) / f)
            w *= np.clip(t, 0, 1)
    for kp in a.keep or []:
        x, y, r = [float(v) for v in kp.split(",")]
        for sx in (1, -1):
            d = np.hypot(P[:, 0] - sx * x, P[:, 1] - y)
            w *= np.clip((d - r) / a.feather, 0, 1)
    return w


def vertex_normals(P, F):
    e1 = P[F[:, 1]] - P[F[:, 0]]; e2 = P[F[:, 2]] - P[F[:, 0]]
    fn = np.cross(e1, e2)
    N = np.zeros_like(P)
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    return N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--mesh", type=int, default=0)
    ap.add_argument("--iters", type=int, default=30)
    ap.add_argument("--lam", type=float, default=0.5)
    ap.add_argument("--mu", type=float, default=-0.53)
    ap.add_argument("--box", default=None)
    ap.add_argument("--feather", type=float, default=0.02)
    ap.add_argument("--keep", action="append")
    ap.add_argument("--max-move", type=float, default=0.012, help="cap on any vertex's total move (glb units)")
    ap.add_argument("--preview", default=None)
    a = ap.parse_args()

    d, j, binc, bin_at = read_glb(a.src)
    prim = j["meshes"][a.mesh]["primitives"][0]
    P0, pstart = acc_view(j, binc, prim["attributes"]["POSITION"])
    N0, nstart = acc_view(j, binc, prim["attributes"]["NORMAL"])
    F, _ = acc_view(j, binc, prim["indices"])
    F = F.reshape(-1, 3).astype(np.int64)
    P0 = P0.astype(np.float64)

    # weld the UV-seam copies
    key = np.round(P0 * 1e5).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    Q = P0[first].copy()
    FW = inv[F]
    n = len(Q)
    # adjacency (unique undirected edges) and boundary
    E = np.concatenate([FW[:, [0, 1]], FW[:, [1, 2]], FW[:, [2, 0]]])
    Es = np.sort(E, 1)
    ue, cnt = np.unique(Es, axis=0, return_counts=True)
    boundary = np.zeros(n, bool); boundary[ue[cnt == 1].ravel()] = True
    nb = [[] for _ in range(n)]
    for i, k in ue:
        nb[i].append(k); nb[k].append(i)
    deg = np.array([len(x) for x in nb], float)
    rows = np.repeat(np.arange(n), [len(x) for x in nb]); cols = np.concatenate([np.array(x, int) for x in nb])
    w = weights(Q, a)
    w[boundary] = 0.0
    w[deg < 3] = 0.0
    Qs = Q.copy()

    def lap(X):
        S = np.zeros_like(X)
        np.add.at(S, rows, X[cols])
        return S / np.maximum(deg, 1)[:, None] - X

    for it in range(a.iters):
        for f in (a.lam, a.mu):
            Nw = vertex_normals(Qs, FW)
            L = lap(Qs)
            dn = (L * Nw).sum(1, keepdims=True) * Nw      # normal component only: no slide across the texture
            Qs = Qs + f * w[:, None] * dn
    mv = Qs - Q
    m = np.linalg.norm(mv, axis=1)
    over = m > a.max_move
    mv[over] *= (a.max_move / m[over])[:, None]
    Qs = Q + mv
    print(f"{n} welded vertices, {int((w > 0).sum())} free, move mean {m[w > 0].mean() * 1000:.2f} p95 {np.percentile(m[w > 0], 95) * 1000:.2f} "
          f"max {m.max() * 1000:.2f} (x1e-3 glb units), capped {int(over.sum())}")

    P1 = Qs[inv].astype(np.float32)
    # the normals: recomputed only where something moved (the renderer re-welds them anyway, car_smooth_normals)
    Nn = vertex_normals(Qs, FW)[inv].astype(np.float32)
    moved = (m[inv] > 1e-7)[:, None]
    N1 = np.where(moved, Nn, N0).astype(np.float32)
    binc[pstart:pstart + P1.nbytes] = P1.tobytes()
    binc[nstart:nstart + N1.nbytes] = N1.tobytes()
    acc = j["accessors"][prim["attributes"]["POSITION"]]
    acc["min"] = [float(v) for v in P1.min(0)]; acc["max"] = [float(v) for v in P1.max(0)]
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    out = bytearray()
    out += b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + 8 + len(binc))
    out += struct.pack("<I", len(js)) + b"JSON" + js
    out += struct.pack("<I", len(binc)) + b"BIN\x00" + bytes(binc)
    open(a.dst, "wb").write(out)
    if a.preview:
        preview([a.src, a.dst], a.preview, a.mesh)


def preview(paths, out, mesh=0):
    """before | after: untextured clay under a raking light (dents show), then textured, close front 3/4 and side"""
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from PIL import Image, ImageDraw
    import io
    from preview import render
    rows = []
    for p in paths:
        d, j, binc, _ = read_glb(p)
        groups_tex, groups_clay = [], []
        for mi, m in enumerate(j["meshes"]):
            pr = m["primitives"][0]
            V, _ = acc_view(j, binc, pr["attributes"]["POSITION"])
            N, _ = acc_view(j, binc, pr["attributes"]["NORMAL"])
            UV, _ = acc_view(j, binc, pr["attributes"]["TEXCOORD_0"])
            F, _ = acc_view(j, binc, pr["indices"])
            F = F.reshape(-1, 3).astype(np.int32)
            # welded smooth normals, like the renderer's car_smooth_normals
            key = np.round(V * 1e5).astype(np.int64)
            _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
            inv = inv.ravel()
            Nw = vertex_normals(V[first].astype(np.float64), inv[F])[inv]
            rgb = np.full((4, 4, 3), 0.7, np.float32)
            mat = j["materials"][pr.get("material", 0)]
            ti = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture", {}).get("index")
            if ti is not None:
                img = j["images"][j["textures"][ti]["source"]]
                bv = j["bufferViews"][img["bufferView"]]
                s = bv.get("byteOffset", 0)
                im = Image.open(io.BytesIO(bytes(binc[s:s + bv["byteLength"]]))).convert("RGB")
                rgb = np.asarray(im, np.float32)[::-1].copy() / 255.0
            S = 5.0      # glb blocks -> metres for the preview's camera
            g = dict(V=V.astype(np.float64) * S, N=Nw, UV=UV, F=F)
            groups_tex.append(dict(g, rgb=rgb))
            groups_clay.append(dict(g, rgb=np.full((4, 4, 3), 0.72, np.float32)))
        views = [dict(eye=(1.9, 1.25, 3.9), tgt=(0, 0.75, 1.3), fov=42), dict(eye=(0.15, 1.6, 4.6), tgt=(0, 0.7, 1.4), fov=38),
                 dict(eye=(7.0, 1.1, 0.4), tgt=(0, 0.75, 0.4), fov=36)]
        row = []
        for v in views:
            row.append(render(groups_clay, dict(v, halfw=0.7, halfl=2.5), size=(480, 300), sun=(-0.8, 0.45, 0.35)))
        for v in views[:2]:
            row.append(render(groups_tex, dict(v, halfw=0.7, halfl=2.5), size=(480, 300)))
        rows.append(row)
    W, H = 480, 300
    S = Image.new("RGB", (W * 5, H * len(rows)), (30, 30, 30))
    for r, row in enumerate(rows):
        for c, im in enumerate(row):
            S.paste(im, (c * W, r * H))
        ImageDraw.Draw(S).text((6, r * H + 4), os.path.basename(paths[r]) + (" (before)" if r == 0 else " (after)"), fill=(255, 255, 0))
    S.save(out)


if __name__ == "__main__":
    main()
