#!/usr/bin/env python3
"""PEDS-FACES: head and face accessories and hair-colour variants for the civilian avatars.

    faces.py <models dir> <out dir> [--manifest <manifest.json>] [--only a,b] [--sheet-only]

For each eligible avatar (EYE, HEAD, FACIAL below) writes rigid accessory models <avatar>~<kind>.mesh, built in the
avatar's head-bone space from its own head mesh (they ride on the head bone: the DLL draws them at the head's posed
matrix, identity.cpp FaceVariety / live_geometry), and hair-colour variants of the head map and the hair cards
(<head map>~hcN.tga, <hair cards>~hcN.tga, N = 1, 2 natural colours, 3 greying) with the facial hair's strand
texture in each colour (<avatar>~hair[~hcN].tga). Shared accessory textures: acc_*.tga (+ ~cK colours for caps).
Skin is never touched (the hair mask keeps the face, ears and neck). With --manifest, the accessory models' entries
are added ("accessory_of")."""
import sys, os, json, struct, math, numpy as np
from PIL import Image, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmsh
from paint_resplit import read_tga, write_tga

# ---------------------------------------------------------------- eligibility (judged on the head close-up sheet)
MEN = ['human_male_01', 'human_male_07', 'human_male_10', 'human_male_13', 'human_male_adult_02', 'human_male_adult_06',
       'human_male_adult_08', 'human_male_adult_09', 'human_male_adult_12', 'human_male_adult_16', 'human_male_adult_18',
       'human_male_adult_20', 'human_business_male_04', 'human_business_male_06', 'human_business_male_07', 'human_male_04',
       'human_male_adult_05']
WOMEN = ['human_female_01', 'human_female_03', 'human_female_05', 'human_female_08', 'human_female_adult_02',
         'human_female_adult_04', 'human_female_adult_07', 'human_female_adult_09', 'human_female_adult_11',
         'human_female_adult_12', 'human_female_adult_13', 'human_female_adult_14', 'human_female_adult_15',
         'human_female_adult_17', 'human_female_party_02', 'human_business_female_01', 'human_business_female_02',
         'human_business_female_04', 'human_sports_female_02']
BEARDED = {'human_male_04', 'human_male_adult_05'}                  # their own beards: no facial hair added
HOODED = {'human_male_adult_18', 'human_male_04', 'human_female_party_02'}   # a hood up, or big curly hair: no headwear
BALD = {'human_business_male_04', 'human_business_male_07', 'human_male_13'}  # little hair: greying only
DARK = {'human_male_adult_12', 'human_male_04', 'human_male_adult_18', 'human_female_party_02', 'human_business_female_01'}
NO_GREY = {'human_female_adult_12'}                                     # the mask reads her fringe band as hair: a white band
UPDO = {'human_female_adult_02', 'human_female_adult_07', 'human_female_adult_11', 'human_female_adult_17',
        'human_female_01', 'human_female_adult_09'}                 # a bun or a high ponytail: no headwear
FACIAL = ['stubble', 'moustache', 'goatee', 'beard']
EYE = ['glasses', 'glasses_dark', 'sunglasses']
HEAD_M = ['cap', 'flatcap', 'beanie']; HEAD_F = ['cap', 'beanie']
CAP_COLOURS = {'cap': [(40, 52, 88), (52, 54, 60), (84, 90, 58), (100, 34, 44), (150, 130, 100)],
               'beanie': [(52, 54, 60), (38, 46, 70), (46, 72, 56), (96, 36, 44), (176, 166, 146)],
               'flatcap': [(92, 88, 82), (88, 70, 54), (60, 62, 66), (70, 76, 64), (110, 100, 86)]}
HAIR = {'black': (26, 22, 20), 'dark brown': (58, 40, 28), 'light brown': (112, 80, 52), 'auburn': (124, 58, 30),
        'blonde': (186, 150, 92)}

# ---------------------------------------------------------------- GMSH writing (rigid: one node per mesh)
def write_rigid(path, meshes):
    """meshes: [(V Nx3, N Nx3, UV Nx2, I Mx3, texture name)] in head-bone space."""
    b = bytearray(b'GMSH') + struct.pack('<5I', 2, len(meshes) + 1, len(meshes), 0, 0)
    def node(name, parent, mesh):
        return name.encode()[:31].ljust(32, b'\0') + struct.pack('<i3f4f3fi', parent, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, mesh)
    b += node('acc', -1, -1)
    for i in range(len(meshes)): b += node(f'acc{i}', 0, i)
    for V, N, UV, I, tex in meshes:
        b += struct.pack('<II', len(V), I.size) + tex.encode().ljust(64, b'\0') + struct.pack('<i', -1)
        b += np.c_[V, N, UV].astype('<f4').tobytes() + I.astype('<u4').ravel().tobytes()
    open(path, 'wb').write(bytes(b))

# ---------------------------------------------------------------- the avatar's head
def head(M, name):
    m = gmsh.load(M + name + '.mesh'); names = [n['name'] for n in m['nodes']]
    jn, ibm = m['skins'][0]
    L = ibm[[k for k, j in enumerate(jn) if names[j] == 'Bip01 Head'][0]].T          # model -> head-bone space
    hm = [me for me in m['meshes'] if me['tex'].endswith('_head.tga')][0]
    op = [me['tex'] for me in m['meshes'] if '_opacity' in me['tex']]
    V, N, UV = hm['v'][:, :3].astype(np.float64), hm['v'][:, 3:6].astype(np.float64), hm['v'][:, 6:8]
    I = hm['idx'].reshape(-1, 3)
    mid = V[np.abs(V[:, 0]) < 0.004]; nose = mid[np.argmin(mid[:, 1])]            # model space: z up, -y forward
    top = V[:, 2].max()
    s = (top - nose[2]) / 0.155 * 0.54 / 0.54                                       # ~1 for an adult head (mesh units)
    hw = np.abs(V[np.abs(V[:, 2] - (nose[2] + 0.012)) < 0.004][:, 0]).max()
    hairv = np.vstack([me['v'][:, :3] for me in m['meshes'] if '_opacity' in me['tex']] + [V]).astype(np.float64)
    return dict(L=L, V=V, N=N, UV=UV, I=I, nose=nose, top=max(top, hairv[:, 2].max()), hw=hw, s=(top - nose[2]) / 0.083,
                head_tex=hm['tex'], op_tex=op[0] if op else None, hairv=hairv)

def to_head(h, V, N):
    P = np.c_[V, np.ones(len(V))] @ h['L'].T
    R = h['L'][:3, :3]; n = N @ R.T; n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9
    return P[:, :3], n

# ---------------------------------------------------------------- primitives (model space)
def tube(path, r, closed=True, sides=6):
    """A tube along a polyline (Kx3), radius r: (V, N, UV, I)."""
    P = np.asarray(path, float); K = len(P)
    Vs, Ns = [], []
    for i in range(K):
        a, b = P[(i - 1) % K if closed or i > 0 else 0], P[(i + 1) % K if closed or i < K - 1 else K - 1]
        t = b - a; t /= np.linalg.norm(t) + 1e-12
        u = np.cross(t, [0, 0, 1.0]);  u = u if np.linalg.norm(u) > 1e-6 else np.cross(t, [1.0, 0, 0]); u /= np.linalg.norm(u)
        w = np.cross(t, u)
        for k in range(sides):
            ang = 2 * math.pi * k / sides; d = math.cos(ang) * u + math.sin(ang) * w
            Vs.append(P[i] + r * d); Ns.append(d)
    I = []
    seg = K if closed else K - 1
    for i in range(seg):
        j = (i + 1) % K
        for k in range(sides):
            a, b, c, d = i * sides + k, i * sides + (k + 1) % sides, j * sides + k, j * sides + (k + 1) % sides
            I += [[a, c, b], [b, c, d]]
    V = np.array(Vs); return V, np.array(Ns), np.tile([[0.5, 0.5]], (len(V), 1)), np.array(I)

def rrect(cx, cz, w, h, y, rad=0.3, n=6):
    """A rounded rectangle in the x-z plane at depth y (the lens rim)."""
    pts = []
    for qx, qz, a0 in ((1, 1, 0), (-1, 1, 90), (-1, -1, 180), (1, -1, 270)):
        ox, oz = cx + qx * (w / 2 - rad * w / 2), cz + qz * (h / 2 - rad * h / 2)
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n); pts.append((ox + rad * w / 2 * math.cos(a), y, oz + rad * h / 2 * math.sin(a)))
    return pts

def merge(parts):
    V, N, UV, I = [], [], [], []; o = 0
    for v, n, uv, i in parts:
        V.append(v); N.append(n); UV.append(uv); I.append(np.asarray(i) + o); o += len(v)
    return np.vstack(V), np.vstack(N), np.vstack(UV), np.vstack(I)

def two_sided(v, n, uv, i):
    return merge([(v, n, uv, i), (v.copy(), -n, uv.copy(), np.asarray(i)[:, ::-1])])

def eyewear(h, kind):
    nz, ny, hw = h['nose'][2], h['nose'][1], h['hw']
    ze = nz + 0.36 * hw; yf = ny + 0.10 * hw; lw, lh = 0.62 * hw, (0.40 if kind != 'sunglasses' else 0.46) * hw
    r = (0.016 if kind == 'glasses' else 0.030) * hw
    parts = []
    for sx in (-1, 1):
        cx = sx * 0.43 * hw
        parts.append(tube(rrect(cx, ze, lw, lh, yf, 0.45 if kind == 'glasses' else 0.3), r))
        ex = sx * (0.43 * hw + lw / 2)                                              # the temple arm, back to the ear
        parts.append(tube([(ex, yf, ze + 0.1 * lh), (sx * 1.02 * hw, yf + 0.25 * hw, ze + 0.1 * lh), (sx * 1.04 * hw, yf + 1.15 * hw, ze - 0.05 * hw)], r * 0.8, closed=False))
    parts.append(tube([(-0.43 * hw + lw / 2, yf, ze + 0.12 * lh), (0, yf - 0.03 * hw, ze + 0.2 * lh), (0.43 * hw - lw / 2, yf, ze + 0.12 * lh)], r * 0.9, closed=False))
    frame = merge(parts)
    out = [(frame, 'acc_glasses_metal.tga' if kind == 'glasses' else 'acc_glasses_dark.tga')]
    if kind == 'sunglasses':                                                         # dark lenses, both sides
        lv, li = [], []
        for sx in (-1, 1):
            cx = sx * 0.43 * hw; ring = rrect(cx, ze, lw * 0.98, lh * 0.98, yf - 0.004 * hw, 0.3)
            c0 = len(lv); lv.append((cx, yf - 0.004 * hw, ze)); lv += ring
            for k in range(len(ring)): li.append([c0, c0 + 1 + k, c0 + 1 + (k + 1) % len(ring)])
        lv = np.array(lv); ln = np.tile([[0, -1.0, 0]], (len(lv), 1))
        out.append((two_sided(lv, ln, np.tile([[0.5, 0.5]], (len(lv), 1)), li), 'acc_lens_dark.tga'))
    return out

def skull(h):
    """The cranium with its hair as an ellipsoid: front (forehead), back, sides and top from the head and hair-card
    vertices above the eye line (a ponytail or bun below the crown does not count)."""
    V = h['hairv']; nz, ny, hw = h['nose'][2], h['nose'][1], h['hw']
    ze = nz + 0.36 * hw
    up = V[(V[:, 2] > ze) & (V[:, 1] < ny + 2.9 * hw)]
    front, back = np.percentile(up[:, 1], 1), np.percentile(up[:, 1], 99.5)
    cy, ry = 0.5 * (front + back), 0.5 * (back - front)
    cz = ze; rz = h['top'] - cz
    rx = max(hw, np.percentile(np.abs(up[:, 0]), 99.5))
    return cy, ry, cz, rz, rx

def dome(h, front_z, back_z, grow, flat=1.0, segs=40, rings=16):
    """The upper skull as an ellipsoid shell, grown by `grow`, cut by a plane from front_z (forehead) to back_z."""
    cy, ry, cz, rz, rx0 = skull(h); hw = h['hw']
    rx = rx0 + grow; ry2 = ry + grow; rz2 = rz * flat + grow
    V, N, I = [], [], []
    for i in range(rings + 1):
        for j in range(segs):
            th = 2 * math.pi * j / segs
            y0, x0 = math.cos(th), math.sin(th)                                       # y0 = -1 the front
            cut = front_z + (back_z - front_z) * (0.5 + 0.5 * y0)
            phi_cut = math.asin(max(-1, min(1, (cut - cz) / rz2)))
            phi = phi_cut + (math.pi / 2 - phi_cut) * i / rings
            p = np.array([rx * math.cos(phi) * x0, cy + ry2 * math.cos(phi) * y0, cz + rz2 * math.sin(phi)])
            n = np.array([(p[0]) / rx ** 2, (p[1] - cy) / ry2 ** 2, (p[2] - cz) / rz2 ** 2]); n /= np.linalg.norm(n)
            V.append(p); N.append(n)
    for i in range(rings):
        for j in range(segs):
            a, b = i * segs + j, i * segs + (j + 1) % segs; c, d = a + segs, b + segs
            I += [[a, b, c], [b, d, c]]
    V = np.array(V); return V, np.array(N), np.c_[np.linspace(0, 1, len(V)), np.zeros(len(V))], np.array(I)

def front_y(h, z, grow):
    cy, ry, cz, rz, rx = skull(h); rz2 = rz + grow; ry2 = ry + grow
    c = math.cos(math.asin(max(-1.0, min(1.0, (z - cz) / rz2))))
    return cy - ry2 * c

def visor(h, z, grow, length, half_angle, droop, width):
    fy = front_y(h, z, grow) + 0.01 * h['hw']; hw = h['hw']
    bv, bi = [], []
    for k in range(13):
        a = math.radians(-half_angle + 2 * half_angle * k / 12)
        for t in (0.0, 1.0):
            L = length * t
            bv.append((math.sin(a) * width, fy - (0.0 if t == 0 else L) * math.cos(a) + abs(math.sin(a)) * 0.35 * width * (1 - t) * 0 , z - droop * L))
    # the inner edge follows the crown's curve
    for k in range(13):
        a = math.radians(-half_angle + 2 * half_angle * k / 12)
        x = math.sin(a) * width
        bv[2 * k] = (x, front_y(h, z, grow) + (x / (skull(h)[4] + grow)) ** 2 * skull(h)[1] * 0.9, z)
    for k in range(12):
        a0, a1, b0, b1 = 2 * k, 2 * k + 1, 2 * k + 2, 2 * k + 3
        bi += [[a0, b0, a1], [a1, b0, b1]]
    bv = np.array(bv); bn = np.tile([[0, -droop, 1.0]], (len(bv), 1)); bn /= np.linalg.norm(bn[0])
    return two_sided(bv, bn, np.tile([[0.5, 0.5]], (len(bv), 1)), bi)

def headwear(h, kind):
    nz, hw = h['nose'][2], h['hw']
    if kind == 'beanie':
        g = 0.11 * hw
        d = dome(h, nz + 0.80 * hw, nz - 0.10 * hw, g)
        c = dome(h, nz + 0.80 * hw, nz - 0.10 * hw, g + 0.035 * hw, rings=3)
        cv = c[0].copy(); base = cv[:40, 2].copy()
        for r in range(1, 4): cv[r * 40:(r + 1) * 40, 2] = base + 0.30 * hw * r / 3   # a turned-up cuff, a band of its own
        return [(merge([d, (cv, c[1], c[2], c[3])]), 'acc_beanie.tga')]
    if kind == 'cap':
        g = 0.10 * hw; z = nz + 0.92 * hw
        d = dome(h, z, nz + 0.40 * hw, g)
        return [(merge([d, visor(h, z, g, 0.95 * hw, 62, 0.18, 0.92 * hw)]), 'acc_cap.tga')]
    if kind == 'flatcap':
        g = 0.11 * hw; z = nz + 0.95 * hw
        d = dome(h, z, nz + 0.50 * hw, g, flat=0.92)
        v = d[0].copy(); cy = skull(h)[0]
        top = v[:, 2] > z + 0.5 * (h['top'] - z)
        v[top, 1] -= 0.18 * hw * (v[top, 2] - z) / (h['top'] - z + 1e-6)               # the crown pulled forward over the brim
        return [(merge([(v, d[1], d[2], d[3]), visor(h, z, g, 0.42 * hw, 58, 0.30, 0.95 * hw)]), 'acc_flatcap.tga')]

def facial(h, kind, name):
    """Facial hair: the head mesh's faces in the region, pushed out, the border feathered (strand alpha by the
    distance from the border, in v)."""
    V, N, I, nose, hw = h['V'], h['N'], h['I'], h['nose'], h['hw']
    nx, ny, nz = nose; S = hw / 0.0375
    def region(p):
        x, y, z = p; depth = (y - ny) / S; zz = (z - nz) / S; ax = abs(x) / S
        lips = ax < 0.011 and -0.025 < zz < -0.0165 and depth < 0.02
        if kind == 'moustache':
            return ax < 0.019 and -0.017 < zz < -0.004 and depth < 0.022
        if kind == 'goatee':
            if lips: return False
            if ax < 0.019 and -0.017 < zz < -0.004 and depth < 0.022: return True       # the moustache
            return ax < 0.016 and zz < -0.017 and depth < 0.035 and zz > -0.05
        # beard and stubble: the jaw, chin and moustache; sideburns
        if depth > 0.07: return False
        if lips: return False
        if zz > -0.004: return zz < 0.024 and 0.046 < depth < 0.07 and ax > 0.027
        if zz > -0.016 and depth < 0.038 and ax > 0.019: return False
        return True
    inr = np.array([region(p) for p in V])
    faces = [f for f in I if inr[f].sum() >= 2]
    if not faces: return None
    used = sorted({int(v) for f in faces for v in f}); remap = {v: k for k, v in enumerate(used)}
    F = np.array([[remap[int(v)] for v in f] for f in faces])
    P0 = V[used]; N0 = N[used]; n = len(P0)
    # distance from the border along the surface (Dijkstra on the edges)
    import heapq
    edges = {}
    for f in F:
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            key = (min(a, b), max(a, b)); edges[key] = edges.get(key, 0) + 1
    adj = [[] for _ in range(n)]
    border = set()
    for (a, b), c in edges.items():
        d = float(np.linalg.norm(P0[a] - P0[b])); adj[a].append((b, d)); adj[b].append((a, d))
        if c == 1: border |= {a, b}
    dist = np.full(n, 1e9); pq = [(0.0, v) for v in border]
    for v in border: dist[v] = 0.0
    heapq.heapify(pq)
    while pq:
        dd, v = heapq.heappop(pq)
        if dd > dist[v]: continue
        for w, l in adj[v]:
            if dd + l < dist[w]: dist[w] = dd + l; heapq.heappush(pq, (dd + l, w))
    feather = 0.008 * S
    k = np.clip(dist / feather, 0, 1)
    low = np.clip((nz - 0.016 * S) - P0[:, 2], 0, None)
    push = {'stubble': 0.0008 * S + 0 * k, 'moustache': (0.0012 + 0.003 * k) * S, 'goatee': (0.0012 + 0.004 * k) * S,
            'beard': (0.0012 + 0.0035 * k) * S + 0.06 * low * k}[kind]
    P = P0 + N0 * np.asarray(push)[:, None] if np.ndim(push) else P0 + N0 * push
    if kind == 'beard': P[:, 2] -= 0.10 * low * k
    rep = 6
    UV = np.c_[0.5 + np.arctan2(P[:, 0], P[:, 1] - ny) / (2 * math.pi) * rep, 0.02 + 0.96 * k]
    tex = f'{name}~stubble.tga' if kind == 'stubble' else f'{name}~hair.tga'
    return [((P, N0, UV, F), tex)]

# ---------------------------------------------------------------- textures
def hair_mask(a):
    """recolor_hair.py hair_mask (the head map's hair, above the face; the face, ears and neck keep their skin)."""
    h, w, _ = a.shape
    f = a[int(0.22 * h):int(0.42 * h), int(0.40 * w):int(0.60 * w)].reshape(-1, 3)
    skin = np.median(f, axis=0)
    d = np.sqrt(((a - skin) ** 2).sum(axis=2)); lum = a.mean(axis=2)
    m = (d > 38) | (lum < skin.mean() * 0.62)
    yy, xx = np.mgrid[0:h, 0:w]
    # (PEDS-FACES: down to the map's foot, not its upper half: long hair is painted below; the skin test keeps the neck)
    m &= (yy < 0.95 * h) & ~(((xx - 0.5 * w) / (0.19 * w)) ** 2 + ((yy - 0.36 * h) / (0.22 * h)) ** 2 < 1.0)
    img = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.GaussianBlur(3))
    return np.asarray(img).astype(np.float32) / 255.0, skin

def strands(rgb, density=1.9, n=128, seed=7, dots=False):
    rng = np.random.default_rng(seed)
    vv = np.linspace(0, 1, n)[:, None][::-1]                                         # TGA rows top-down; v up
    if dots: alpha = (rng.random((n, n)) < 0.55 * np.clip(0.5 + vv * 1.5, 0, 1)).astype(np.float32)
    else: alpha = ((rng.random(n)[None, :] + rng.random((n, n)) * 0.25) < vv * density).astype(np.float32)
    st = np.clip(1 + 0.18 * (np.repeat(rng.normal(0, 1, (1, n)), n, 0) * 0.6 + rng.normal(0, 1, (n, n)) * 0.4), 0.7, 1.3)
    a = np.zeros((n, n, 4), np.float32)
    for c in range(3): a[..., c] = np.clip(rgb[c] * st, 0, 255)
    a[..., 3] = alpha * 255
    return a.astype(np.uint8)

def flat(rgb, n=32, noise=0.06, seed=3, knit=False):
    rng = np.random.default_rng(seed); t = np.clip(1 + noise * rng.normal(0, 1, (n, n)), 0.8, 1.2)
    if knit: t *= 0.92 + 0.08 * np.sin(np.arange(n) * 1.6)[None, :]
    a = np.zeros((n, n, 4), np.uint8)
    for c in range(3): a[..., c] = np.clip(rgb[c] * t, 0, 255)
    a[..., 3] = 255; return a

def recolour_head(a, m, target):
    lum = a.mean(axis=2, keepdims=True); hm = (lum * m[..., None]).sum() / max((m > 0.5).sum(), 1)
    new = np.asarray(target, float)[None, None, :] * (1 + 0.45 * (lum / max(hm, 1.0) - 1))   # the own strands' contrast, softened
    return a * (1 - m[..., None]) + np.clip(new, 0, 255) * m[..., None]

def grey_head(a, m, own, seed):
    rng = np.random.default_rng(seed); lum = a.mean(axis=2, keepdims=True)
    hm = (lum * m[..., None]).sum() / max((m > 0.5).sum(), 1)
    h, w = m.shape; xx = np.mgrid[0:h, 0:w][1]
    temples = np.clip(np.abs(xx - 0.5 * w) / (0.5 * w), 0, 1)[..., None]        # the sides of the map: the temples
    salt = np.clip(0.30 + 0.45 * temples + 0.2 * rng.random((h, w, 1)), 0, 1)
    grey = np.array([158, 156, 152])[None, None, :] * (lum / max(hm, 1.0)) ** 0.6
    mixed = a * (1 - salt) + np.clip(grey, 0, 255) * salt
    return a * (1 - m[..., None]) + mixed * m[..., None]

def recolour_cards(c, target):
    out = c.copy().astype(np.float32); on = c[..., 3] > 8
    lum = c[..., :3].mean(axis=2); hm = lum[on].mean() if on.any() else 1
    for k in range(3): out[..., k][on] = np.clip(target[k] * (1 + 0.45 * (lum[on] / max(hm, 1) - 1)), 0, 255)
    return out.astype(np.uint8)

def small(a, n):
    return np.asarray(Image.fromarray(a.astype(np.uint8), 'RGBA').resize((n, n), Image.LANCZOS))

# ---------------------------------------------------------------- main
def build(M, out, name, male, report):
    h = head(M, name); made = []
    def put(kind, parts):
        if not parts: return
        ms = []
        for (V, N, UV, I), tex in parts:
            v, n = to_head(h, V, N); ms.append((v, n, UV, np.asarray(I), tex))
        write_rigid(os.path.join(out, f'{name}~{kind}.mesh'), ms); made.append(kind)
    for k in EYE: put(k, eyewear(h, k))
    if name not in HOODED and name not in UPDO:   # (HOODED: the hood, the afros)
        for k in (HEAD_M if male else HEAD_F): put(k, headwear(h, k))
    if male and name not in BEARDED:
        for k in FACIAL: put(k, facial(h, k, name))
    # hair colour: the own colour, the variants, the facial hair textures in each
    a = read_tga(M + h['head_tex']).astype(np.float32)
    m, skin = hair_mask(a[..., :3])
    own = (a[..., :3] * m[..., None]).sum((0, 1)) / max(m.sum(), 1)
    dark_skin = skin.mean() < 120 or name in DARK
    pool = ['black', 'dark brown'] if dark_skin else ['black', 'dark brown', 'light brown', 'auburn'] + (['blonde'] if own.mean() > 70 else [])
    # (blonde only over hair that is not dark already: a dark map turned blonde reads as dyed)
    rng = np.random.default_rng(sum(name.encode()))
    if own.mean() > 90: pool = [c for c in pool if c in ('auburn', 'blonde', 'light brown')]   # light hair: the mask misses
    # strands close to the skin's colour, so a dark variant would streak; only near shades
    far = [c for c in pool if np.linalg.norm(np.array(HAIR[c]) - own) > 55]
    picks = [] if name in BALD else (list(rng.choice(far, size=min(2, len(far)), replace=False)) if far else [])
    cards = read_tga(M + h['op_tex']) if h['op_tex'] else None
    facial_rgb = lambda c: tuple(int(x * 0.85) for x in c)
    write_tga(strands(facial_rgb(own)), os.path.join(out, f'{name}~hair.tga'))
    shadow = lambda c: tuple(int(0.62 * skin[k] * 0.78 + 0.38 * c[k] * 0.85) for k in range(3))   # a five o'clock shadow: skin darkened toward the hair
    write_tga(strands(shadow(own), density=3.2, seed=11), os.path.join(out, f'{name}~stubble.tga'))
    variants = []
    for i, c in enumerate(picks + ([] if name in NO_GREY else ['grey']), 1):
        tag = f'~hc{i}'
        if c == 'grey':
            ha = grey_head(a[..., :3], m, own, i); col = (150, 148, 144)
        else:
            ha = recolour_head(a[..., :3], m, HAIR[c]); col = HAIR[c]
        write_tga(np.dstack([ha, a[..., 3:]]).clip(0, 255).astype(np.uint8), os.path.join(out, h['head_tex'][:-4] + tag + '.tga'))
        if cards is not None:
            write_tga(small(recolour_cards(cards, col), 256), os.path.join(out, h['op_tex'][:-4] + tag + '.tga'))
        write_tga(strands(facial_rgb(col)), os.path.join(out, f'{name}~hair{tag}.tga'))
        write_tga(strands(shadow(col), density=3.2, seed=11), os.path.join(out, f'{name}~stubble{tag}.tga'))
        variants.append(c)
    report[name] = dict(accessories=made, hair=variants, own_hair=[round(x) for x in own], dark_skin=bool(dark_skin))

def shared_textures(out):
    write_tga(flat((176, 178, 184), noise=0.03), os.path.join(out, 'acc_glasses_metal.tga'))
    write_tga(flat((30, 30, 34), noise=0.03), os.path.join(out, 'acc_glasses_dark.tga'))
    write_tga(flat((22, 24, 28), noise=0.01), os.path.join(out, 'acc_lens_dark.tga'))
    clear = np.zeros((4, 4, 4), np.uint8); write_tga(clear, os.path.join(out, 'acc_clear.tga'))   # headwear: no hair cards
    for kind, cols in CAP_COLOURS.items():
        write_tga(flat(cols[0], knit=kind == 'beanie'), os.path.join(out, f'acc_{kind}.tga'))
        for k, c in enumerate(cols): write_tga(flat(c, knit=kind == 'beanie', seed=5 + k), os.path.join(out, f'acc_{kind}~c{k}.tga'))

if __name__ == '__main__':
    args = sys.argv[1:]; man = None; only = None
    if '--manifest' in args: i = args.index('--manifest'); man = args[i + 1]; del args[i:i + 2]
    if '--only' in args: i = args.index('--only'); only = set(args[i + 1].split(',')); del args[i:i + 2]
    M, out = args[0].rstrip('/') + '/', args[1]; os.makedirs(out, exist_ok=True)
    shared_textures(out); report = {}
    for name in MEN + WOMEN:
        if only and name not in only: continue
        build(M, out, name, name in MEN, report); print(name, report[name])
    json.dump(report, open(os.path.join(out, 'faces_report.json'), 'w'), indent=1)
    if man:
        mm = json.load(open(man))
        have = {e['name'] for e in mm['models']}
        for name, r in report.items():
            for k in r['accessories']:
                n = f'{name}~{k}'
                if n not in have: mm['models'].append({'name': n, 'accessory_of': name})
        open(man, 'w').write(json.dumps(mm, indent=1))
