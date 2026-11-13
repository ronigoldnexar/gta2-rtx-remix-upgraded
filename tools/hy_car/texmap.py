"""Texel -> surface maps for a UV-mapped mesh: each texel's 3D position and face normal (its triangle rasterised in
UV space), so a texture edit can be decided in model space (a panel below the belt line, a door's rectangle)."""
import numpy as np


def texel_maps(V, F, UV, size):
    """-> pos (size, size, 3), nrm (size, size, 3), valid (size, size) bool. Image row 0 = v 1 (glTF/trimesh v up)."""
    pos = np.zeros((size, size, 3), np.float32); nrm = np.zeros((size, size, 3), np.float32)
    valid = np.zeros((size, size), bool)
    P = np.stack([UV[:, 0] % 1.0 * size, (1.0 - UV[:, 1] % 1.0) * size], 1)
    tri = V[F]; fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    for t in range(len(F)):
        a, b, c = P[F[t]]
        x0 = int(max(0, np.floor(min(a[0], b[0], c[0])))); x1 = int(min(size - 1, np.ceil(max(a[0], b[0], c[0]))))
        y0 = int(max(0, np.floor(min(a[1], b[1], c[1])))); y1 = int(min(size - 1, np.ceil(max(a[1], b[1], c[1]))))
        if x1 < x0 or y1 < y0 or (x1 - x0) * (y1 - y0) > 40000: continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12: continue
        l1 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / d
        l2 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / d
        l3 = 1 - l1 - l2
        m = (l1 >= -0.02) & (l2 >= -0.02) & (l3 >= -0.02)
        if not m.any(): continue
        yy = (ys[m] - 0.5).astype(int); xx = (xs[m] - 0.5).astype(int)
        p = l1[m, None] * tri[t, 0] + l2[m, None] * tri[t, 1] + l3[m, None] * tri[t, 2]
        pos[yy, xx] = p; nrm[yy, xx] = fn[t]; valid[yy, xx] = True
    return pos, nrm, valid
