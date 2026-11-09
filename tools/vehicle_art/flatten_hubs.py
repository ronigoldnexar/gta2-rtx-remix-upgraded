#!/usr/bin/env python3
"""VEHICLE-ART-7: press an image-to-3D body's crumpled hubs into smooth domed hubcaps (the 018 Shark's front and rear
hubs were jagged spiked lumps, which the shell wheel split then spins). Vertices only move along x (outward),
so UVs, triangles and textures are untouched; every other mesh in the glb (add_lamps.py pods) is byte-identical.

At each wheel (glb units: axle z, centre height y, the tyre's face x0, dome radius R and crown height h, mirrored
to -x) every vertex of the body within R of the centre (in z/y) that stands proud of x0 is set onto the dome
x0 + h (1 - (d/R)^2); one standing proud of x0 between R and 1.3 R is pressed back to x0.

  gen3d/venv/bin/python tools/vehicle_art/flatten_hubs.py <in.glb> <out.glb> z,y,x0,R,h [z,y,x0,R,h ...]
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from smooth_shell import read_glb, acc_view, vertex_normals
import json, struct


def main():
    src, dst = sys.argv[1], sys.argv[2]
    d, j, binc, _ = read_glb(src)
    prim = j["meshes"][0]["primitives"][0]
    P, pstart = acc_view(j, binc, prim["attributes"]["POSITION"])
    N, nstart = acc_view(j, binc, prim["attributes"]["NORMAL"])
    F, _ = acc_view(j, binc, prim["indices"]); F = F.reshape(-1, 3).astype(np.int64)
    P = P.astype(np.float64); P0 = P.copy()
    for spec in sys.argv[3:]:
        z, y, x0, R, h = [float(v) for v in spec.split(",")]
        for sx in (1, -1):
            dd = np.hypot(P[:, 2] - z, P[:, 1] - y)
            out = sx * P[:, 0] - x0
            dome = (dd < R) & (out > -0.25 * h)
            P[dome, 0] = sx * (x0 + h * (1 - (dd[dome] / R) ** 2))
            ring = (dd >= R) & (dd < 1.3 * R) & (out > 0)
            P[ring, 0] = sx * x0
            print(f"wheel z {z:+.3f} side {sx:+d}: {int(dome.sum())} vertices on the dome, {int(ring.sum())} pressed back")
    moved = np.linalg.norm(P - P0, axis=1) > 1e-9
    key = np.round(P * 1e5).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    Nn = vertex_normals(P[first], inv[F])[inv]
    N1 = np.where(moved[:, None], Nn, N).astype(np.float32)
    P1 = P.astype(np.float32)
    binc[pstart:pstart + P1.nbytes] = P1.tobytes(); binc[nstart:nstart + N1.nbytes] = N1.tobytes()
    acc = j["accessors"][prim["attributes"]["POSITION"]]
    acc["min"] = [float(v) for v in P1.min(0)]; acc["max"] = [float(v) for v in P1.max(0)]
    js = json.dumps(j, separators=(",", ":")).encode(); js += b" " * ((4 - len(js) % 4) % 4)
    out = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + 8 + len(binc)) + struct.pack("<I", len(js)) + b"JSON" + js + \
        struct.pack("<I", len(binc)) + b"BIN\x00" + bytes(binc)
    open(dst, "wb").write(out)


if __name__ == "__main__":
    main()
