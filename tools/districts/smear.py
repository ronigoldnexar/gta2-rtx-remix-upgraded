#!/usr/bin/env python3
"""smear.py <kit> [x y r]: the facade kit's tile-art stretch detector (GDK1 stream, e.g. <lvl>_stream0.kit).

Two modes, both over the tile-art groups (tile >= 0):
  1. constant uv (KIT-SIDEUV): quad edges >= 0.05 block long whose uv does not change along them (one texel stretched);
  2. low density (KIT-DENSITY): triangles whose texture density is far below the front face's. The front of a wall shows
     one tile (uv span UV_MAX - UV_MIN = 0.984) per block, density 1.0; the smaller singular value of the triangle's
     d(uv)/d(world) is the density along its worst direction, so a triangle under LOW (0.45) is stretched at least 2.2x:
     uv that changes, but far too slowly (a face running past the tile's edge clamped to the edge column, a sill top
     reusing the front's rows, ...). Triangles with a world edge under 0.04 are left out (hairlines between parts).
     Also counted: uv outside the tile's inset range (a vertex sampling past the tile; wrapped groups, flag 4, excepted).
Counts by face kind (side / top / bottom / slope); with x y r (map coordinates, the y of the map: world z = 256 - y)
the offenders within r blocks of the point are listed. Exit status 1 if anything is found."""
import struct, sys, numpy as np
from collections import Counter
H = 256
LOW = 0.45
UV_MIN, UV_MAX = 0.5 / 64, 1.0 - 0.5 / 64
d = open(sys.argv[1], "rb").read(); ng = struct.unpack_from("<I", d, 8)[0]; o = 12
near = None if len(sys.argv) < 5 else tuple(map(float, sys.argv[2:5]))
cnt = Counter(); dcnt = Counter(); hits = []; outside = 0


def smin_of(v, ix):
    """per triangle: the singular values of d(uv)/d(world) (uv per block), area, longest edge, unit normal"""
    a, b, c = v[ix[:, 0]], v[ix[:, 1]], v[ix[:, 2]]
    e1 = b[:, :3].astype(np.float64) - a[:, :3]; e2 = c[:, :3].astype(np.float64) - a[:, :3]
    l1 = np.linalg.norm(e1, axis=1)
    x = e1 / np.maximum(l1[:, None], 1e-12)
    cr = np.cross(e1, e2); area = np.linalg.norm(cr, axis=1)
    nn = cr / np.maximum(area[:, None], 1e-12)
    y = np.cross(nn, x)
    W = np.stack([np.stack([l1, np.zeros_like(l1)], 1), np.stack([(e2 * x).sum(1), (e2 * y).sum(1)], 1)], 2)
    U = np.stack([b[:, 6:8] - a[:, 6:8], c[:, 6:8] - a[:, 6:8]], 2).astype(np.float64)
    det = W[:, 0, 0] * W[:, 1, 1] - W[:, 0, 1] * W[:, 1, 0]
    ok = np.abs(det) > 1e-12
    Wi = np.zeros_like(W)
    Wi[ok, 0, 0] = W[ok, 1, 1] / det[ok]; Wi[ok, 1, 1] = W[ok, 0, 0] / det[ok]
    Wi[ok, 0, 1] = -W[ok, 0, 1] / det[ok]; Wi[ok, 1, 0] = -W[ok, 1, 0] / det[ok]
    s = np.linalg.svd(U @ Wi, compute_uv=False)
    le = np.max([np.linalg.norm(v[ix[:, i], :3].astype(np.float64) - v[ix[:, (i + 1) % 3], :3], axis=1) for i in range(3)], axis=0)
    return s, area, le, nn


for _ in range(ng):
    t, fl, nv, ni = struct.unpack_from("<iIII", d, o); o += 16
    v = np.frombuffer(d, np.float32, nv * 8, o).reshape(nv, 8); o += nv * 32
    ix = np.frombuffer(d, np.uint32, ni, o).reshape(-1, 3); o += ni * 4
    if t < 0: continue
    uvv = v[:, 6:8]
    if not fl & 4:      # flag 4: uv wraps on purpose (the stacks' art), not a tile's inset range
        outside += int(((uvv < UV_MIN - 1e-4) | (uvv > UV_MAX + 1e-4)).any(1).sum())
    q = ix[(ix[:, 1] == ix[:, 0] + 1) & (ix[:, 2] == ix[:, 0] + 2), 0]
    q = q[q + 3 < nv]
    for e0, e1 in ((0, 1), (1, 2), (2, 3), (3, 0)):
        a, b = v[q + e0], v[q + e1]
        L = np.linalg.norm(a[:, :3] - b[:, :3], axis=1)
        du = np.linalg.norm(a[:, 6:8] - b[:, 6:8], axis=1)
        bad = (L >= 0.05) & (du < 1e-6)
        for i in np.where(bad)[0]:
            n = v[q[i] + e0, 3:6]
            kind = "side" if abs(n[1]) < 0.5 else ("top" if n[1] > 0 else "bottom")
            hor = abs(a[i, 1] - b[i, 1]) < 1e-4
            k = (kind, "horizontal edge" if hor else "vertical edge", round(float(L[i]), 2))
            cnt[k] += 1
            if near:
                mx, my = (a[i, 0] + b[i, 0]) / 2, H - (a[i, 2] + b[i, 2]) / 2
                if (mx - near[0]) ** 2 + (my - near[1]) ** 2 < near[2] ** 2:
                    hits.append((round(float(mx), 2), round(float(my), 2), round(float(a[i, 1]), 2), k, t, [round(float(c), 2) for c in n]))
    if len(ix):
        s, area, le, nn = smin_of(v, ix)
        bad = (area > 1e-7) & (le >= 0.04) & (s[:, 1] < LOW)
        for i in np.where(bad)[0]:
            ny = nn[i][1]
            kind = "side" if abs(ny) < 0.3 else ("top" if ny > 0.9 else ("bottom" if ny < -0.9 else "slope"))
            k = (kind, "density %.1f" % (np.floor(s[i, 1] * 10) / 10), "edge %.2f" % (round(float(le[i]) * 10) / 10))
            dcnt[k] += 1
            if near:
                tri = v[ix[i]]
                mx, my = tri[:, 0].mean(), H - tri[:, 2].mean()
                if (mx - near[0]) ** 2 + (my - near[1]) ** 2 < near[2] ** 2:
                    hits.append((round(float(mx), 2), round(float(my), 2), round(float(tri[:, 1].mean()), 2), k, t, [round(float(c), 2) for c in nn[i]]))
print("-- constant uv along an edge >= 0.05")
for k, c in sorted(cnt.items(), key=lambda kv: -kv[1])[:25]: print(c, k)
print("total", sum(cnt.values()))
print("-- texture density under %.2f of the front's (smaller singular value of d(uv)/d(world))" % LOW)
for k, c in sorted(dcnt.items(), key=lambda kv: -kv[1])[:25]: print(c, k)
print("total density", sum(dcnt.values()))
print("vertices with uv outside the tile", outside)
for h in sorted(hits, key=lambda q: q[2])[:60]: print(h)
sys.exit(1 if (sum(cnt.values()) + sum(dcnt.values()) + outside) else 0)
