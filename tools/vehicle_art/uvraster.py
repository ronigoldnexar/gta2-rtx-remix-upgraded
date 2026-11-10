"""Shared helpers (VEHICLE-ART-8): UV-rasterise a glb mesh (each texel -> its point and face normal on the body)
and splat texel colours into orthographic z-buffered views for checking a texture against the geometry."""
import numpy as np


def raster(V, F, uv, H, W):
    fid = np.full((H, W), -1, np.int64); pos = np.zeros((H, W, 3), np.float32); cov = np.zeros((H, W), bool)
    FN = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    FN /= np.maximum(np.linalg.norm(FN, axis=1, keepdims=True), 1e-12)
    U = uv[:, 0] * W; Vv = (1 - uv[:, 1]) * H
    for fi, f in enumerate(F):
        x, y = U[f], Vv[f]
        x0, x1 = int(max(0, np.floor(x.min()))), int(min(W - 1, np.ceil(x.max())))
        y0, y1 = int(max(0, np.floor(y.min()))), int(min(H - 1, np.ceil(y.max())))
        if x1 < x0 or y1 < y0:
            continue
        X, Y = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
        if abs(d) < 1e-12:
            continue
        l0 = ((y[1] - y[2]) * (X - x[2]) + (x[2] - x[1]) * (Y - y[2])) / d
        l1 = ((y[2] - y[0]) * (X - x[2]) + (x[0] - x[2]) * (Y - y[2])) / d
        l2 = 1 - l0 - l1
        m = (l0 >= -0.02) & (l1 >= -0.02) & (l2 >= -0.02)
        if not m.any():
            continue
        yy, xx = np.nonzero(m); yy += y0; xx += x0
        pos[yy, xx] = l0[m, None] * V[f[0]] + l1[m, None] * V[f[1]] + l2[m, None] * V[f[2]]
        cov[yy, xx] = True; fid[yy, xx] = fi
    nrm = np.zeros((H, W, 3), np.float32)
    nrm[cov] = FN[fid[cov]]
    return pos, nrm, cov, fid


def views(pos, cov, rgb, size=360):
    """Side (+x looking -x), top, front (+z), rear (-z), 3/4 rear: z-buffered splats of every covered texel."""
    P = pos[cov]; C = rgb[cov]
    lo, hi = P.min(0), P.max(0); span = (hi - lo).max()
    out = []
    a = np.radians(35)
    rot34 = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    for ax_u, ax_v, ax_d, sgn, R in ((2, 1, 0, 1, None), (0, 2, 1, 1, None), (0, 1, 2, 1, None), (0, 1, 2, -1, None), (0, 1, 2, -1, rot34)):
        Q = P if R is None else (P - (lo + hi) / 2) @ R.T + (lo + hi) / 2
        qlo, qhi = Q.min(0), Q.max(0)
        span = max(qhi[ax_u] - qlo[ax_u], qhi[ax_v] - qlo[ax_v]) * 1.02
        u = ((Q[:, ax_u] - qlo[ax_u]) / span * (size - 1)).astype(int)
        if ax_d == 2 and sgn == -1:
            u = size - 1 - u
        v = (size - 1 - (Q[:, ax_v] - qlo[ax_v]) / span * (size - 1)).astype(int)
        if ax_v == 2:
            v = size - 1 - v
        d = Q[:, ax_d] * sgn
        img = np.zeros((size, size, 3), np.float32) + 40
        zb = np.full((size, size), -1e9)
        order = np.argsort(d)
        u, v, d, c = np.clip(u[order], 0, size - 1), np.clip(v[order], 0, size - 1), d[order], C[order]
        img[v, u] = c   # later (nearer) writes win
        out.append(img)
    return np.concatenate(out, 1)
