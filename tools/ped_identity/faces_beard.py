"""PEDS-FACES-3: the moustache, goatee and full beard as shells over the head mesh with their alpha painted in the
head's own UV layout (an atlas cell per kind in one 256 px map per hair colour, <avatar>~hair[~hcN].tga): the edge
comes from a smooth 3D region (feathered with fine strand noise), not from the triangles, so the inside is solid
(no holes) and the border is hair, not a ragged patch. The same 256 px map per colour as the strand texture it
replaces: no added memory."""
import math, numpy as np

ATLAS = 256
CELLS = {'beard': (0, 0, 256, 160), 'goatee': (0, 160, 128, 96), 'moustache': (128, 160, 128, 96)}   # x, y (rows down), w, h
FEATHER = 0.0022     # normalized units (head half-width 0.0375): the soft band at the edge
NOISE = 0.0013       # strand noise amplitude on the edge

def coords(h, P):
    nx, ny, nz = h['nose']; S = h['hw'] / 0.0375
    return np.abs(P[..., 0]) / S, (P[..., 2] - nz) / S, (P[..., 1] - ny) / S

def smin(*a):
    return np.minimum.reduce([np.asarray(x, float) for x in a])

def smax(*a):
    return np.maximum.reduce([np.asarray(x, float) for x in a])

def mouth_z(h):
    """The mouth line (normalized z): the mouth cavity's vertices on the midline (deep behind the lips)."""
    if 'mouth_z' not in h:
        x, z, d = coords(h, h['V'])
        m = (x < 0.006) & (z < -0.008) & (z > -0.026) & (d > 0.022) & (d < 0.045)
        h['mouth_z'] = float(np.median(z[m])) if m.sum() >= 2 else -0.0145
    return h['mouth_z']

def field(kind, x, z, d, mz):
    """Signed margin (normalized units): > 0 inside the facial hair. mz: the mouth line."""
    w = z - mz                                                                           # above the mouth: > 0
    top_t = -0.0060 - 0.22 * x                                                           # under the nose, rising outward
    bot_t = 0.0010 - 0.20 * np.clip(x - 0.011, 0, 0.012)                                 # the lip line, drooping at the corners
    tache = smin(0.0215 - x, 0.024 - d, w - bot_t, top_t - z)
    rz = np.where(w > -0.0004, 0.0026, 0.0046)
    lips = (np.sqrt((x / 0.0125) ** 2 + ((w + 0.0004) / rz) ** 2) - 1.0) * 0.0035          # > 0 outside the lips
    if kind == 'moustache': return tache
    chin_b = mz - 0.037
    if kind == 'goatee':
        chin = smin(0.0150 - 0.12 * np.maximum(0, chin_b + 0.010 - z) - x, -0.0040 - w, z - chin_b, 0.034 - d)
        ring = smin(0.0225 - x, 0.0020 - w, w + 0.0075, 0.030 - d)
        return smin(smax(tache, chin, ring), lips)
    # beard: the moustache joined to the cheeks, jaw and chin; the top a line from the mouth corners up to the
    # sideburns, the back in front of the ear, the bottom under the jaw
    top = mz + 0.0065 + 0.55 * np.clip(d - 0.022, 0, 0.05)
    back = 0.058 + 0.45 * np.clip(-0.012 - z, 0, 0.03)
    bottom = chin_b - 0.006 + 0.60 * np.clip(d - 0.025, 0, 0.045)
    cheek = smin(top - z, back - d, z - bottom)
    bare = smin(x - 0.021, z + 0.010, 0.026 - d)                                         # beside the nostrils: bare
    cheek = smin(cheek, -bare)
    return smin(smax(tache, cheek), lips)

def select(h, kind, margin=0.004):
    x, z, d = coords(h, h['V'])
    f = field(kind, x, z, d, mouth_z(h))
    keep = np.array([f[t].max() > -margin for t in h['I']])
    return f, h['I'][keep]

def strand_noise(W, H, seed):
    rng = np.random.default_rng(seed)
    col = rng.random(W)                                                                  # one value per texel column...
    n = np.repeat(col[None, :], H, 0) * 0.7 + rng.random((H, W)) * 0.3                   # ...streaked down the rows
    # a little smoothing along the rows: strands, not salt
    n = (n + np.roll(n, 1, 0) + np.roll(n, -1, 0)) / 3
    n = (2 * n + np.roll(n, 1, 1) + np.roll(n, -1, 1)) / 4                              # (two texels wide: no single-texel teeth)
    return n * 2 - 1

def raster(h, kind, F):
    """Per texel of the kind's cell: the region field from the interpolated head-space positions (NaN: uncovered).
    Returns (field cell, uv per used vertex in atlas space, used vertex ids)."""
    cx, cy, cw, ch = CELLS[kind]
    UV = h['UV']; used = np.unique(F.ravel())
    u0, u1 = UV[used, 0].min(), UV[used, 0].max(); v0, v1 = UV[used, 1].min(), UV[used, 1].max()
    pad = 2
    def to_px(uv):   # head uv -> pixel in the cell (column, row from the top of the cell)
        return np.c_[pad + (uv[:, 0] - u0) / max(u1 - u0, 1e-6) * (cw - 2 * pad - 1), pad + (v1 - uv[:, 1]) / max(v1 - v0, 1e-6) * (ch - 2 * pad - 1)]
    px = to_px(UV)
    x, z, d = coords(h, h['V'])
    att = np.c_[x, z, d]
    acc = np.full((ch, cw, 3), np.nan)
    for t in F:
        p = px[t]; a = att[t]
        c0, c1 = int(np.floor(p[:, 0].min())), int(np.ceil(p[:, 0].max())); r0, r1 = int(np.floor(p[:, 1].min())), int(np.ceil(p[:, 1].max()))
        den = (p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1])
        if abs(den) < 1e-9: continue
        rr, cc = np.mgrid[max(r0, 0):min(r1, ch - 1) + 1, max(c0, 0):min(c1, cw - 1) + 1]
        X, Y = cc + 0.5, rr + 0.5
        l0 = ((p[1, 1] - p[2, 1]) * (X - p[2, 0]) + (p[2, 0] - p[1, 0]) * (Y - p[2, 1])) / den
        l1 = ((p[2, 1] - p[0, 1]) * (X - p[2, 0]) + (p[0, 0] - p[2, 0]) * (Y - p[2, 1])) / den
        l2 = 1 - l0 - l1
        m = (l0 >= -0.03) & (l1 >= -0.03) & (l2 >= -0.03)
        val = l0[..., None] * a[0] + l1[..., None] * a[1] + l2[..., None] * a[2]
        acc[rr[m], cc[m]] = val[m]
    # fill the uncovered texels from their neighbours (the bilinear filter at an island's edge)
    for _ in range(6):
        miss = np.isnan(acc[..., 0])
        if not miss.any(): break
        s = np.zeros_like(acc); n = np.zeros(acc.shape[:2])
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = np.roll(np.roll(acc, dr, 0), dc, 1); ok = ~np.isnan(sh[..., 0])
            s[ok] += sh[ok]; n[ok] += 1
        fill = miss & (n > 0); acc[fill] = s[fill] / n[fill][:, None]
    f = field(kind, acc[..., 0], acc[..., 1], acc[..., 2], mouth_z(h))
    auv = np.c_[(cx + px[:, 0]) / ATLAS, (cy + px[:, 1]) / ATLAS]                            # atlas uv (D3D: v down, row 0 at the top)
    return f, auv

def alpha_cell(h, kind, f, seed):
    ch, cw = f.shape
    nz = strand_noise(cw, ch, seed)
    f = np.nan_to_num(f, nan=-1.0)
    n01 = (nz + 1) / 2
    g = f + NOISE * n01 * np.clip(1.0 + f / NOISE, 0, 1) * (f < 0) - 0.0006 * (1 - n01) * (f < 0.0012)
    return np.clip(0.5 + g / FEATHER, 0, 1)

def atlas(h, rgb, seed=7):
    """The 256 px map for one colour: the three cells' alpha (cached on h) x a strand-streaked colour."""
    if 'beard_alpha' not in h:
        A = np.zeros((ATLAS, ATLAS), np.float32); FL = np.full((ATLAS, ATLAS), -1.0, np.float32)
        h['beard_uv'] = {}
        for i, kind in enumerate(('beard', 'goatee', 'moustache')):
            fv, F = select(h, kind)
            if not len(F): continue
            f, auv = raster(h, kind, F)
            cx, cy, cw, ch = CELLS[kind]
            A[cy:cy + ch, cx:cx + cw] = alpha_cell(h, kind, f, seed + i)
            FL[cy:cy + ch, cx:cx + cw] = np.nan_to_num(f, nan=-1)
            h['beard_uv'][kind] = (F, auv)
        h['beard_alpha'] = A; h['beard_field'] = FL
    A, FL = h['beard_alpha'], h['beard_field']
    rng = np.random.default_rng(seed + 11)
    st = np.repeat(rng.normal(0, 1, (1, ATLAS)), ATLAS, 0) * 0.7 + rng.normal(0, 1, (ATLAS, ATLAS)) * 0.3
    st = (st + np.roll(st, 1, 0) + np.roll(st, -1, 0)) / 3
    fine = rng.normal(0, 1, (ATLAS, ATLAS))
    shade = np.clip(1 + 0.10 * st + 0.08 * fine, 0.75, 1.25) * (0.82 + 0.18 * np.clip(FL / 0.005, 0, 1))   # a little darker at the thin edge
    out = np.zeros((ATLAS, ATLAS, 4), np.float32)
    for k in range(3): out[..., k] = np.clip(rgb[k] * shade, 0, 255)
    out[..., 3] = A * 255
    return out.astype(np.uint8)

def shell(h, kind):
    """The kind's shell: the selected head faces, pushed out by the region's depth (the core thicker), atlas uvs."""
    if 'beard_uv' not in h: atlas(h, (60, 40, 30))
    if kind not in h['beard_uv']: return None
    F, auv = h['beard_uv'][kind]
    V, N = h['V'], h['N']; S = h['hw'] / 0.0375
    x, z, d = coords(h, V)
    f = field(kind, x, z, d, mouth_z(h))
    s = np.clip(f / 0.006, 0, 1)
    used = np.unique(F.ravel()); remap = -np.ones(len(V), int); remap[used] = np.arange(len(used))
    P0, N0, s0, z0 = V[used], N[used], s[used], z[used]
    thick = {'moustache': 0.0020, 'goatee': 0.0040, 'beard': 0.0050}[kind]
    push = (0.0009 + thick * s0) * S
    P = P0 + N0 * push[:, None]
    if kind in ('beard', 'goatee'):
        low = np.clip(-0.040 - z0, 0, None)                    # under the chin: a little fuller, hanging down
        P[:, 2] -= 0.10 * low * s0 * S
    Fn = remap[F]
    # smoothed (three passes over the shell's edges), as the Haredi beard
    edges = set()
    for t in Fn:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])): edges.add((min(a, b), max(a, b)))
    E = np.array(sorted(edges))
    for _ in range(3):
        acc = P.copy(); cnt = np.ones(len(P))
        np.add.at(acc, E[:, 0], P[E[:, 1]]); np.add.at(acc, E[:, 1], P[E[:, 0]])
        np.add.at(cnt, E[:, 0], 1); np.add.at(cnt, E[:, 1], 1)
        P = 0.5 * P + 0.5 * acc / cnt[:, None]
    return P, N0, auv[used], Fn
