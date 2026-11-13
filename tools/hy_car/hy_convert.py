#!/usr/bin/env python3
"""CARS-V3: a Hunyuan3D 2.1 car shell (one painted mesh, wheels and lamps fused in) -> a game car model with the
parts the renderer's car features use.

    gen3d/venv/bin/python tools/hy_car/hy_convert.py <out dir> 0 12 51 ... [--src /mnt/gta2/out/carhy]
        [--spec tools/hy_car/specs.json] [--preview]

Per car (docs/car-3d-pipeline.md, "CARS-V3"):
  1. orientation: the shell turned so its nose is +z (specs.json "nose": "+z"|"-z", as the generator left it);
  2. clean: loose bits under 200 faces dropped; decimated with its UVs kept (pymeshlab quadric with texture) to the
     face budget (20 000 for a remapped car, whose shell is drawn twice: paint and the rest; 28 000 for a livery);
  3. smooth normals: angle-weighted, welded across the UV seams, kept apart over a 60 degree crease;
  4. wheels: each wheel's circle fitted on an orthographic side render of the shell (a dark tyre disc touching the
     road, see fit_wheel); the fused tyre and hub cut out of the shell; a clean wheel (carkit.add_wheel) put in its
     place in the shell's own style (whitewall, chrome / steel / body-colour rim, hubcap, from the shell's texels);
     marker nodes wheel_fl/fr/rl/rr; a dark arch liner along the arch's own outline and an inner wall close the well;
  5. lamps: lens meshes (lamp_head / lamp_tail textures: car_bodies.cpp LensSpotsFor, the Remix emissive) on the
     shell's own head and tail lamps, found on end renders; the sprite's lamp deltas (6, 5) where none is found;
  6. specials from specs.json: a roof light bar from the sprite's siren deltas (cop car), a roof sign (taxis),
     texture recolours;
  7. a GLB whose shell material keeps its picture (the importer's paint_split pair for a remapped car, re-split
     by tools/car_paint_resplit.py after the import) and whose parts carry surface-named textures.
Then tools/import_assets.py, car_paint_resplit.py, car_mesh_orient.py fix and vehicle_art/underpan.py, as build.py does.
"""
import argparse, json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(TOOLS, 'vehicle_art2'), os.path.join(TOOLS, 'vehicle_art'), TOOLS]
import trimesh  # noqa
import carkit as K  # noqa
import hyrender as HR  # noqa
from gta2sty import Style  # noqa

ASRC = os.path.expanduser('~/gta2-linux/assets-src')
CAT = json.load(open(os.path.join(ASRC, 'cars', 'catalog.json')))['cars']
STY = os.path.expanduser('~/gta2-linux/game/data/wil.sty')
# car_bodies.cpp LiveryModel: painted in a fixed livery, never tinted
LIVERY = {4, 11, 12, 17, 22, 23, 24, 25, 26, 27, 34, 51, 52, 54, 56, 59, 60, 61, 67, 84, 85, 86}
# wheels left in the shell (tracks, bogies, trailer axles: nothing to spin or steer)
STATIC_WHEELS = {6, 54, 55, 59, 60, 61, 65, 66}
# Budget (the 32-bit game; the fleet before CARS-V3 averaged 0.9 MB of mesh and 2.6 MB of textures a car): a remapped
# car's shell is drawn twice (paint and rest, the same geometry) and its paint picture stays in system memory (soft
# paint mask), so it gets fewer faces and smaller pictures than a livery's single shell.
FACES_SPLIT, FACES_LIVERY = int(os.environ.get('HY_FACES_SPLIT', 12000)), int(os.environ.get('HY_FACES_LIVERY', 20000))
TEX_SPLIT, TEX_LIVERY = int(os.environ.get('HY_TEX_SPLIT', 512)), int(os.environ.get('HY_TEX_LIVERY', 1024))


def car(m):
    return next(e for e in CAT if e['model'] == m)


def lum(rgb):
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def sat(rgb):
    return rgb.max(-1) - rgb.min(-1)


# ---------------------------------------------------------------------------------------------------------------
# load, orient, clean, decimate, normals
# ---------------------------------------------------------------------------------------------------------------

def load(m, src):
    g = list(trimesh.load(f'{src}/{m:03d}.glb').geometry.values())[0]
    V = np.asarray(g.vertices, np.float64); F = np.asarray(g.faces, np.int64); UV = np.asarray(g.visual.uv, np.float64)
    tex = g.visual.material.baseColorTexture.convert('RGB')
    mr = None
    w = f'{src}/work/{m:03d}/final_work.glb'
    if os.path.exists(w):
        gw = list(trimesh.load(w).geometry.values())[0]
        if len(gw.vertices) == len(V) and np.allclose(np.asarray(gw.visual.uv), UV, atol=1e-6):
            t = getattr(gw.visual.material, 'metallicRoughnessTexture', None)
            if t is not None: mr = t.convert('RGB')
    return V, F, UV, tex, mr


def turn(V):
    V = V.copy(); V[:, 0] *= -1; V[:, 2] *= -1
    return V


def weld_key(V, q=1e-5):
    k = np.round(V / q).astype(np.int64)
    _, inv = np.unique(k, axis=0, return_inverse=True)
    return inv.ravel()


def drop_bits(V, F, UV, min_faces=200):
    pid = weld_key(V)
    edges = np.concatenate([pid[F[:, [0, 1]]], pid[F[:, [1, 2]]], pid[F[:, [2, 0]]]])
    lab = trimesh.graph.connected_component_labels(edges, node_count=pid.max() + 1)
    fl = lab[pid[F[:, 0]]]
    cnt = np.bincount(fl)
    keep = cnt[fl] >= min_faces
    return F[keep], int((~keep).sum())


def decimate(V, F, UV, target):
    import pymeshlab
    if len(F) <= target:
        return V, F, UV
    ms = pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(vertex_matrix=V, face_matrix=F.astype(np.int32), v_tex_coords_matrix=UV))
    ms.compute_texcoord_transfer_vertex_to_wedge()
    ms.meshing_merge_close_vertices(threshold=pymeshlab.PercentageValue(0.001))
    ms.meshing_decimation_quadric_edge_collapse_with_texture(targetfacenum=int(target), qualitythr=0.5, extratcoordw=1.0,
                                                             preserveboundary=True, optimalplacement=True, preservenormal=True)
    c = ms.current_mesh()
    P = c.vertex_matrix(); Fc = c.face_matrix().astype(np.int64); W = c.wedge_tex_coord_matrix().reshape(-1, 3, 2)
    # split per (position, uv): the game format has one uv per vertex
    corner_p = Fc.ravel(); corner_uv = W.reshape(-1, 2)
    key = np.concatenate([corner_p[:, None].astype(np.float64), np.round(corner_uv * 1e6)], 1)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return P[corner_p[first]], inv.reshape(-1, 3), corner_uv[first]


def smooth_normals(V, F, crease_deg=60.0):
    """per corner: the angle-weighted mean of the incident faces' normals (welded by position) within the crease;
    vertices are split where corners of one vertex disagree. Returns V, F, UV-index map, N."""
    pid = weld_key(V)
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    fn = np.cross(b - a, c - a); fl = np.linalg.norm(fn, axis=1); fn = fn / np.maximum(fl, 1e-12)[:, None]

    def ang(p, q, r):
        u = q - p; v = r - p
        cu = (u * v).sum(1) / np.maximum(np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1), 1e-12)
        return np.arccos(np.clip(cu, -1, 1))
    angs = np.stack([ang(a, b, c), ang(b, c, a), ang(c, a, b)], 1)
    cos_c = math.cos(math.radians(crease_deg))
    nc = len(F) * 3
    cp = pid[F].ravel(); cf = np.repeat(np.arange(len(F)), 3); cw = angs.ravel()
    order = np.argsort(cp, kind='stable')
    cps = cp[order]
    starts = np.flatnonzero(np.r_[True, cps[1:] != cps[:-1]]); ends = np.r_[starts[1:], len(cps)]
    cn = np.zeros((nc, 3))
    for s, e in zip(starts, ends):
        idx = order[s:e]; faces = cf[idx]; nf = fn[faces]; w = cw[idx][:, None]
        dots = nf @ nf.T
        acc = (dots >= cos_c).astype(np.float64) @ (nf * w)
        cn[idx] = acc / np.maximum(np.linalg.norm(acc, axis=1), 1e-12)[:, None]
    return cn.reshape(-1, 3, 3)


def expand(V, F, UV, CN):
    """one vertex per distinct (vertex, normal) corner"""
    cv = F.ravel(); n = CN.reshape(-1, 3)
    key = np.concatenate([cv[:, None].astype(np.float64), np.round(n * 1e4)], 1)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return V[cv[first]], inv.reshape(-1, 3), UV[cv[first]], n[first]


def tex_at(img_arr, uv):
    H, W = img_arr.shape[:2]
    x = np.clip((uv[..., 0] % 1.0) * W, 0, W - 1).astype(int); y = np.clip((1 - uv[..., 1] % 1.0) * H, 0, H - 1).astype(int)
    return img_arr[y, x]


# ---------------------------------------------------------------------------------------------------------------
# wheels
# ---------------------------------------------------------------------------------------------------------------

def side_render(shell, view):
    return HR.render([shell], view, res=0.002)


def fit_wheel(R, zc0, zsign, window=0.2, dthr=0.10):
    """the tyre circle near the axle hint zc0 (model z) on a side render: a dark, unsaturated disc on the outer face
    touching the road, with a lighter rim inside it and no dark tyre just outside it. -> (score, r, zc, outer depth)"""
    u0, u1, v0, v1 = R['extent']; res = R['res']; H, W = R['alpha'].shape
    alb = R['albedo']; L = lum(alb); S = sat(alb)
    near = R['alpha'] & (R['depth'] < dthr)
    tyre = near & (L < 0.16) & (S < 0.10)
    U = u0 + (np.arange(W) + 0.5) * res; Vv = v1 - (np.arange(H) + 0.5) * res
    ground = v0 + 0.01

    def score(zc, r):
        uc = zsign * zc
        ci = np.where(np.abs(U - uc) < 1.3 * r)[0]; ri = np.where(Vv < 2.4 * r + ground)[0]
        if len(ci) == 0 or len(ri) == 0: return -9.0
        uu, vv = np.meshgrid(U[ci], Vv[ri]); T = tyre[np.ix_(ri, ci)]; N = near[np.ix_(ri, ci)]
        d = np.hypot(uu - uc, vv - (ground + r))
        low = vv < ground + 1.2 * r
        band = (d > 0.80 * r) & (d < 0.97 * r) & low
        out = (d > 1.04 * r) & (d < 1.22 * r) & (vv < ground + 0.8 * r) & (vv > ground + 0.004)
        inner = d < 0.75 * r; rim = (d > 0.40 * r) & (d < 0.66 * r)
        if band.sum() < 10 or out.sum() < 5 or rim.sum() < 5: return -9.0
        return float(T[band].mean() - T[out].mean() + 0.3 * N[inner].mean() - 0.3 * (1 - N[band].mean()) + 0.5 * (1 - T[rim].mean()))
    best = (-9.0, 0.0, 0.0)
    for r in np.arange(0.035, 0.17, 0.004):
        for zc in np.arange(zc0 - window, zc0 + window, 0.004):
            s = score(zc, r)
            if s > best[0]: best = (s, r, zc)
    _, r0, z0 = best
    for r in np.arange(r0 - 0.004, r0 + 0.0045, 0.001):
        for zc in np.arange(z0 - 0.004, z0 + 0.0045, 0.001):
            s = score(zc, r)
            if s > best[0]: best = (s, r, zc)
    sc, r, zc = best
    # the tyre's outer face: the depth of its tyre texels (from the side the render looks from)
    uc = zsign * zc
    uu, vv = np.meshgrid(U, Vv); d = np.hypot(uu - uc, vv - (ground + r))
    m = tyre & (d > 0.7 * r) & (d < 0.97 * r)
    dep = float(np.percentile(R['depth'][m], 10)) if m.sum() > 20 else 0.02
    return sc, r, zc, dep


def arch_profile(R, zc, r, zsign, ground_pad=0.01, dthr=0.10):
    """for angles over the wheel (0 = toward +z ... 180 = toward -z, through the top), the distance from the axle at
    which the body's outer side (near, not tyre) begins: the arch's own outline. NaN where none within 1.9 r."""
    u0, u1, v0, v1 = R['extent']; res = R['res']; H, W = R['alpha'].shape
    alb = R['albedo']; L = lum(alb); S = sat(alb)
    near = R['alpha'] & (R['depth'] < dthr)
    tyre = near & (L < 0.16) & (S < 0.10)
    body = near & ~tyre
    yc = v0 + ground_pad + r
    angs = np.radians(np.arange(-25, 206, 5))
    out = []
    for a in angs:
        hit = np.nan
        for k in np.arange(0.9, 1.9, 0.01):
            z = zc + math.cos(a) * k * r; y = yc + math.sin(a) * k * r
            i = int((v1 - y) / res); j = int((zsign * z - u0) / res)
            if not (0 <= i < H and 0 <= j < W): break
            # three body texels in a row: the arch edge
            ok = True
            for kk in (0.0, 0.01, 0.02):
                z2 = zc + math.cos(a) * (k + kk) * r; y2 = yc + math.sin(a) * (k + kk) * r
                i2 = int((v1 - y2) / res); j2 = int((zsign * z2 - u0) / res)
                if not (0 <= i2 < H and 0 <= j2 < W and body[i2, j2]): ok = False; break
            if ok:
                hit = k * r; break
        out.append(hit)
    return np.degrees(angs), np.array(out)


def wheel_style(R, zc, r, zsign, paint_rgb, ground_pad=0.01):
    """the shell's wheel look: whitewall ring, rim colour and kind, hubcap colour (sampled on the side render)"""
    u0, u1, v0, v1 = R['extent']; res = R['res']; H, W = R['alpha'].shape
    U = u0 + (np.arange(W) + 0.5) * res; Vv = v1 - (np.arange(H) + 0.5) * res
    uu, vv = np.meshgrid(U, Vv); d = np.hypot(uu - zsign * zc, vv - (v0 + ground_pad + r))
    ok = R['alpha'] & (R['depth'] < 0.12)
    alb = R['albedo']

    def ring(a, b):
        m = ok & (d >= a * r) & (d < b * r) & (vv < v0 + ground_pad + 1.25 * r)
        return alb[m] if m.sum() > 10 else np.zeros((1, 3))
    ww = ring(0.66, 0.84); rim = ring(0.36, 0.62); cap = ring(0.0, 0.32)
    style = {}
    wwl = float(np.median(lum(ww))); wws = float(np.median(sat(ww)))
    style['whitewall'] = 0.0
    if wwl > 0.55 and wws < 0.18:
        style['whitewall'] = 1.0
    rimc = np.median(rim, 0); capc = np.median(cap, 0)

    def kind(c):
        l, s = float(lum(c)), float(sat(c))
        if s > 0.16:
            pr = np.array(paint_rgb, float) / 255
            ph = np.arctan2(math.sqrt(3) * (pr[1] - pr[2]), 2 * pr[0] - pr[1] - pr[2])
            ch = np.arctan2(math.sqrt(3) * (c[1] - c[2]), 2 * c[0] - c[1] - c[2])
            if abs((ch - ph + np.pi) % (2 * np.pi) - np.pi) < 0.45: return 'paint'
            return 'colour'
        if l > 0.50: return 'chrome'
        return 'steel'
    style['rim'] = kind(rimc); style['rim_rgb'] = [float(v) for v in rimc]
    style['cap'] = kind(capc); style['cap_rgb'] = [float(v) for v in capc]
    return style


def wheel_face(R, zc, r, zsign, ground_pad=0.01, size=128, sector=(210.0, 330.0)):
    """the shell's own wheel face as a disc texture: the lower third of the wheel as the side render shows it (never
    under the fender), in polar coordinates, repeated three times round the disc, so the new wheel wears the
    generated hubcap, rim, whitewall and tyre wall and its turning shows. Also the radial profile (32 bins, median
    colour) for the paint band test."""
    u0, u1, v0, v1 = R['extent']; res = R['res']; H, W = R['alpha'].shape
    alb = R['albedo']
    yy, xx = np.mgrid[0:size, 0:size]
    du = (xx + 0.5) / size * 2 - 1; dv = (yy + 0.5) / size * 2 - 1
    rho = np.clip(np.hypot(du, dv), 0, 1.0)
    th = np.degrees(np.arctan2(dv, du)) % 360.0
    span = sector[1] - sector[0]
    ths = np.radians(sector[0] + (th % span))
    uc = zsign * zc; yc = v0 + ground_pad + r
    u = uc + np.cos(ths) * rho * r * 0.995; v = yc + np.sin(ths) * rho * r * 0.995
    j = np.clip(((u - u0) / res).astype(int), 0, W - 1); i = np.clip(((v1 - v) / res).astype(int), 0, H - 1)
    face = alb[i, j]
    # hubcaps and wheel faces are round: the generated face carries baked light (a highlight on one side) that a
    # tiled sector turns into a triangle; the face is the sector's radial average, with five dark lug nuts so its
    # turning shows
    nb = 160
    rb = np.minimum((rho * nb).astype(int), nb - 1)
    avg = np.zeros((nb, 3)); have = np.zeros(nb, bool)
    for b in range(nb):
        mm = rb == b
        if mm.any(): avg[b] = np.median(face[mm], 0); have[b] = True
    xs = (np.arange(nb) + 0.5) / nb
    for c in range(3):
        avg[:, c] = np.interp(xs, xs[have], avg[have, c])
    face = np.stack([np.interp(rho, xs, avg[:, c]) for c in range(3)], -1)
    lug_r = 0.26; lug = np.zeros_like(rho)
    for k in range(5):
        a = 2 * math.pi * k / 5
        lug = np.maximum(lug, np.exp(-(((du - lug_r * math.cos(a)) ** 2 + (dv - lug_r * math.sin(a)) ** 2) / (2 * 0.035 ** 2))))
    face = face * (1 - 0.55 * lug[..., None])
    # radial profile from the same sector
    prof = np.zeros((32, 3))
    for b in range(32):
        rr = (b + 0.5) / 32
        ts = np.radians(np.linspace(sector[0], sector[1], 40))
        uu = uc + np.cos(ts) * rr * r; vv = yc + np.sin(ts) * rr * r
        jj = np.clip(((uu - u0) / res).astype(int), 0, W - 1); ii = np.clip(((v1 - vv) / res).astype(int), 0, H - 1)
        prof[b] = np.median(alb[ii, jj], 0)
    return face, prof


def paint_band(prof, paint_rgb):
    """the radial range (fractions of r) where the wheel face is body paint (a body-colour rim): None when there is none"""
    pr = np.array(paint_rgb, float) / 255
    hue = lambda c: np.degrees(np.arctan2(math.sqrt(3) * (c[..., 1] - c[..., 2]), 2 * c[..., 0] - c[..., 1] - c[..., 2]))
    dh = np.abs((hue(prof) - hue(pr) + 180) % 360 - 180)
    m = (dh < 28) & (sat(prof) > 0.12) & (prof.max(-1) > 0.18)
    if m.sum() < 3: return None
    idx = np.flatnonzero(m)
    # the longest run
    runs = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
    run = max(runs, key=len)
    if len(run) < 3: return None
    return (run[0] / 32.0, (run[-1] + 1) / 32.0)


def build_wheel(kc, nm, wh, face_mat, band):
    """a period wheel: tyre with a rounded shoulder and tread, the face a shallow dish under the sampled face texture
    (a body-colour band, when there is one, as its own ring under the neutral paint_wheel), a dark inner disc.
    Profile (radius, offset along the axle outward) in fractions of r and of the width w."""
    r, w, s = wh['r'], wh['width'], wh['side']
    cx = s * (wh['outer'] - 0.5 * w)
    face = [(0.0, 0.40), (0.10, 0.40), (0.20, 0.385), (0.32, 0.345), (0.46, 0.31), (0.58, 0.32), (0.66, 0.37),
            (0.72, 0.43), (0.80, 0.48), (0.88, 0.50), (0.94, 0.49), (0.985, 0.44), (1.0, 0.32)]
    if band is not None:
        pts = sorted(set([p[0] for p in face] + [round(band[0], 4), round(band[1], 4)]))
        face = [(q, float(np.interp(q, [p[0] for p in face], [p[1] for p in face]))) for q in pts]
    prof = [(a * r, b * w) for a, b in face]
    def mat_face(k):
        a = 0.5 * (face[k][0] + face[k + 1][0])
        if band is not None and band[0] <= a <= band[1]: return 'paint_wheel'
        return face_mat
    kc.revolve(prof, (cx, r, wh['zc']), (s, 0, 0), 28, mat_of=mat_face, uv_mode='disc')
    kc.revolve([(r, 0.32 * w), (r * 1.0, -0.32 * w)], (cx, r, wh['zc']), (s, 0, 0), 32, default='tyre_tread', uv_mode='tyre')
    kc.revolve([(r, -0.32 * w), (0.985 * r, -0.44 * w), (0.92 * r, -0.50 * w), (0.62 * r, -0.46 * w)], (cx, r, wh['zc']), (s, 0, 0), 28,
               default='tyre_side', uv_mode='tyre')
    kc.revolve([(0.62 * r, -0.46 * w), (0.001, -0.40 * w)], (cx, r, wh['zc']), (s, 0, 0), 20, default='hubback', uv_mode='disc')
    kc.marker(nm, (cx, r, wh['zc']))


# ---------------------------------------------------------------------------------------------------------------
# lamps from end renders
# ---------------------------------------------------------------------------------------------------------------

def find_lamps(shell, view, kind, hw, height, prior_x=None):
    """bright (head) or red (tail) compact islands on an end render, one a side: [(x, y, z, radius)] model frame"""
    from scipy import ndimage
    R = HR.render([shell], view, res=0.0015)
    u0, u1, v0, v1 = R['extent']; res = R['res']; H, W = R['alpha'].shape
    alb = R['albedo']; L = lum(alb); S = sat(alb)
    dmin = np.min(R['depth'][R['alpha']])
    front = R["alpha"] & (R["depth"] < dmin + 0.18)
    U = u0 + (np.arange(W) + 0.5) * res; Vv = v1 - (np.arange(H) + 0.5) * res
    uu, vv = np.meshgrid(U, Vv)
    band = (vv > 0.06 * height) & (vv < 0.80 * height) & (np.abs(uu) > 0.12 * hw)
    if kind == 'head':
        m = front & band & (L > 0.50) & (S < 0.32)
    else:
        r, g, b = alb[..., 0], alb[..., 1], alb[..., 2]
        m = front & band & (r > 0.28) & (r > 1.5 * g) & (r > 1.4 * b)
    m = ndimage.binary_opening(m, iterations=1)
    lab, n = ndimage.label(m)
    sign = 1.0 if view == 'front' else -1.0     # model z of the face the view sees
    best = {}
    (ia, sa), _, _ = HR.AXES[view]
    for k in range(1, n + 1):
        cm = lab == k; area = cm.sum() * res * res
        if area < (0.006 ** 2) * math.pi or area > (0.06 ** 2) * math.pi: continue
        ys, xs = np.nonzero(cm)
        u = float(U[xs].mean()); v = float(Vv[ys].mean()); dep = float(np.median(R['depth'][cm]))
        x = sa * u   # image-right axis is x (sign sa)
        ext = (U[xs].max() - U[xs].min(), Vv[ys].max() - Vv[ys].min())
        roundness = min(ext) / max(max(ext), 1e-6)
        if roundness < 0.35: continue
        z = (shell.vertices[:, 2].max() + 0.01 - dep) if sign > 0 else (shell.vertices[:, 2].min() - 0.01 + dep)
        side = 1 if x > 0 else -1
        if abs(x) < 0.35 * hw: continue
        if prior_x is not None and abs(abs(x) - abs(prior_x)) > 0.35 * hw: continue
        w8 = 1.0 if prior_x is None else 1.0 / (1.0 + 20.0 * abs(abs(x) - abs(prior_x)))
        cand = (area * roundness * w8, (x, v, z, math.sqrt(area / math.pi)))
        if side not in best or cand[0] > best[side][0]: best[side] = cand
    return [best[s][1] for s in sorted(best)]


def ray_hits(shell, o, d):
    """all hits of the ray o + t d (t > 0) on the shell's triangles (Moller-Trumbore, numpy): points"""
    tri = shell.vertices[shell.faces]
    e1 = tri[:, 1] - tri[:, 0]; e2 = tri[:, 2] - tri[:, 0]
    p = np.cross(d, e2); det = (e1 * p).sum(1)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    s = o - tri[:, 0]; u = (s * p).sum(1) * inv
    q = np.cross(s, e1); v = (q * d).sum(1) * inv; t = (e2 * q).sum(1) * inv
    hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0)
    return o + t[hit, None] * d


def surface_z_at(shell, x, y, end):
    """the shell's outermost z at (x, y) toward +z (end=+1) or -z: a ray cast"""
    loc = ray_hits(shell, np.array([x, y, end * 10.0]), np.array([0.0, 0.0, -float(end)]))
    if len(loc) == 0: return None
    return float(loc[np.argmax(end * loc[:, 2])][2])


def lamp_lens(car_, mat, x, y, z, r, end):
    """a shallow lens dome facing +z (end=+1) or -z, its rim on the surface"""
    prof = [(r, 0.0)] + [(r * math.cos(t) + 1e-5, 0.22 * r * math.sin(t)) for t in np.linspace(0.15, math.pi / 2, 6)]
    car_.revolve(prof, (x, y, z - end * 0.002), (0, 0, end), 20, default=mat, uv_mode='disc')


# ---------------------------------------------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------------------------------------------

def arch_parts(car_, wheel, side, angs, prof, hw):
    """the well: a liner surface along the arch outline (plus a hair) from the inner wall to just inside the body's
    side, and the inner wall (a fan over the same outline down to the road)"""
    zc, r, xo, xw = wheel['zc'], wheel['r'], wheel['outer'], wheel['wall']
    yc = r
    a = np.radians(angs)
    rad = np.where(np.isfinite(prof), prof, np.nan)
    # fill gaps from the neighbours; clamp
    if np.isnan(rad).all(): rad[:] = 1.12 * r
    idx = np.arange(len(rad)); good = np.isfinite(rad)
    rad = np.interp(idx, idx[good], rad[good])
    rad = np.clip(rad + 0.004, 1.03 * r, 1.45 * r)
    sel = (angs >= -2) & (angs <= 182)
    a = a[sel]; rad = rad[sel]
    # keep the liner above the road
    pts = np.stack([zc + np.cos(a) * rad, np.maximum(yc + np.sin(a) * rad, 0.004)], 1)
    x_in = side * xw; x_out = side * (xo - 0.004)
    P, Tc, Fc = [], [], []
    n = len(pts)
    for i, (z, y) in enumerate(pts):
        P.append((x_in, y, z)); P.append((x_out, y, z)); Tc.append((i / (n - 1), 0)); Tc.append((i / (n - 1), 1))
    for i in range(n - 1):
        k = 2 * i
        Fc.append((k, k + 1, k + 3)); Fc.append((k, k + 3, k + 2))
    P = np.array(P); Fc = np.array(Fc)
    # normals toward the axle (the liner is seen from the wheel)
    Nn = np.zeros_like(P)
    for i, (z, y) in enumerate(pts):
        v = np.array([0.0, yc - y, zc - z]); v /= max(np.linalg.norm(v), 1e-9)
        Nn[2 * i] = v; Nn[2 * i + 1] = v
    car_.part('underbody').add(P, Nn, np.array(Tc), Fc)
    car_.part('underbody').add(P, -Nn, np.array(Tc), Fc[:, ::-1])
    # inner wall: a fan from the axle's foot over the outline
    C = np.array([[x_in, 0.004, zc]])
    W = np.concatenate([C, np.stack([np.full(n, x_in), pts[:, 1], pts[:, 0]], 1)])
    Fw = np.array([(0, i + 1, i + 2) for i in range(n - 1)])
    Nw = np.tile([[side * 1.0, 0, 0]], (len(W), 1))
    Tw = np.stack([0.5 + (W[:, 2] - zc) / (4 * r), W[:, 1] / (4 * r)], 1)
    car_.part('underbody').add(W, Nw, Tw, Fw)
    car_.part('underbody').add(W, -Nw, Tw, Fw[:, ::-1])


def cut_wheel(V, F, UV, img, wheel, side):
    """faces of the fused tyre and hub: wholly inside 0.97 r of the axle (outboard of the inner wall), or wholly
    inside 1.08 r and textured as tyre (dark, grey)"""
    zc, r = wheel['zc'], wheel['r']
    sx = side * V[:, 0]
    d = np.hypot(V[:, 1] - r, V[:, 2] - zc)
    out_ok = sx > wheel['wall'] - 0.002
    in1 = (d < 0.97 * r) & out_ok; in2 = (d < 1.10 * r) & out_ok
    c = tex_at(img, UV[F].mean(1))
    dark = (lum(c) < 0.20) & (sat(c) < 0.14)
    kill = in1[F].all(1) | (in2[F].all(1) & dark)
    return kill


# ---------------------------------------------------------------------------------------------------------------
# main build
# ---------------------------------------------------------------------------------------------------------------

def build(m, spec, src, log):
    e = car(m)
    V, F, UV, tex, mr = load(m, src)
    if spec.get('nose', '+z') == '-z':
        V = turn(V)
    F, dropped = drop_bits(V, F, UV)
    livery = m in LIVERY
    target = spec.get('faces', FACES_LIVERY if livery else FACES_SPLIT)
    V, F, UV = decimate(V, F, UV, target)
    img = np.asarray(tex).astype(np.float64) / 255.0
    paint_rgb = e['remaps'][0]['paint_rgb']
    log(f'{m:03d}: {len(F)} faces after clean ({dropped} dropped) and decimation, nose {spec.get("nose", "+z")}')
    hw = float(np.abs(V[:, 0]).max()); height = float(V[:, 1].max()); L = float(V[:, 2].max() - V[:, 2].min())

    # texture edits (recolours) before anything samples the picture
    img0 = img
    for rc in spec.get('recolour', []):
        img = recolour(img, rc)

    shell = trimesh.Trimesh(V, F, process=False)
    shell.visual = trimesh.visual.TextureVisuals(uv=UV, image=Image.fromarray((img * 255).astype(np.uint8)))

    name = spec['name']
    kc = K.Car(name)
    wheels = []
    kill = np.zeros(len(F), bool)
    if m not in STATIC_WHEELS:
        k = L / e['body_blocks'][1]
        hints = spec.get('axles') or [e['wheels_px']['front_offset'] / 64 * k, e['wheels_px']['rear_offset'] / 64 * k]
        renders = {+1: side_render(shell, 'side+'), -1: side_render(shell, 'side-')}
        fine = {+1: HR.render([shell], 'side+', res=0.0007), -1: HR.render([shell], 'side-', res=0.0007)}
        for ai, zh in enumerate(hints):
            fits = {}
            for side, R in renders.items():
                fits[side] = fit_wheel(R, zh, 1 if side > 0 else -1, window=spec.get('axle_window', 0.2))
            r = float(np.mean([f[1] for f in fits.values()])); zc = float(np.mean([f[2] for f in fits.values()]))
            for side, R in renders.items():
                sc, _, _, dep = fits[side]
                outer = float(hw + 0.01 - dep)
                width = float(spec.get('tyre_width', 0.62)) * r
                wh = dict(zc=zc, r=r, outer=outer, width=width, side=side, score=sc,
                          front=zc > 0, wall=outer - max(1.0 * r, width + 0.03))
                angs, prof = arch_profile(R, zc, r, 1 if side > 0 else -1)
                wh['arch'] = [None if not np.isfinite(p) else round(float(p / r), 3) for p in prof]
                st = wheel_style(R, zc, r, 1 if side > 0 else -1, paint_rgb)
                st.update(spec.get('wheel_style', {}))
                wh['style'] = st
                fimg, fprof = wheel_face(fine[side], zc, r, 1 if side > 0 else -1)
                wh['band'] = None if livery else paint_band(fprof, paint_rgb)
                wh['face_mat'] = f'hubface_{ai}{"r" if side > 0 else "l"}'
                kc.materials[wh['face_mat']] = Image.fromarray((np.clip(fimg, 0, 1) * 255).astype(np.uint8))
                wheels.append(wh)
                kill |= cut_wheel(V, F, UV, img, wh, side)
                arch_parts(kc, wh, side, angs, prof, hw)
            log(f'  axle {ai}: hint {zh:+.3f} -> zc {zc:+.3f} r {r:.3f} (scores {fits[1][0]:.2f} / {fits[-1][0]:.2f}), '
                f'style {wheels[-1]["style"]["rim"]}/{wheels[-1]["style"]["cap"]} whitewall {wheels[-1]["style"]["whitewall"]:.0f}')
        log(f'  wheels: {int(kill.sum())} shell faces cut out')

    # lamps
    sty = Style(STY); spr = e['sprite_index']; sw, sh = sty.sprite_size(spr)
    kx = 2 * hw / (e['body_px'][0] / 64.0); kz = L / (e['body_px'][1] / 64.0)
    lamps = {'head': [], 'tail': []}
    for kind, dl, view in (('head', 6, 'front'), ('tail', 5, 'rear')):
        px = sty.delta_pixels(spr, dl)
        prior = (-(np.mean([p[0] for p in px]) + 0.5 - sw / 2) / 64 * kx) if px else None
        try:
            lamps[kind] = find_lamps(shell, view, kind, hw, height, prior)
        except Exception as ex:  # noqa
            log(f'  {kind} lamps: search failed ({ex})')

    def delta_xz(dl, mirror=False):
        px = sty.delta_pixels(spr, dl)
        if not px: return None
        xs = np.array([p[0] for p in px], float); ys = np.array([p[1] for p in px], float)
        if mirror: xs = sw - 1 - xs
        return (-(xs.mean() + 0.5 - sw / 2) / 64 * kx, (ys.mean() + 0.5 - sh / 2) / 64 * kz,
                (xs.max() - xs.min() + 1) / 64 * kx, (ys.max() - ys.min() + 1) / 64 * kz)
    for kind, dl, end in (('head', 6, 1), ('tail', 5, -1)):
        found = lamps[kind]
        if len(found) < 2:
            # LensSpotsFor wants both sides; a guessed lens on the wrong panel is worse than the renderer's own spot
            log(f'  {kind} lamps: {len(found)} found on the shell: no lenses (the renderer places the glow)')
            lamps[kind] = []
            continue
        log(f'  {kind} lamps: {len(found)} found on the shell')
        for (x, y, z, rr) in found:
            rr = float(np.clip(rr * 1.05, 0.010, 0.045))
            zs = surface_z_at(shell, x, y, end)
            lamp_lens(kc, 'lamp_' + kind, x, y, (zs if zs is not None else z), rr, end)
        lamps[kind] = found

    # specials
    if spec.get('lightbar'):
        kill |= lightbar(kc, V, F, UV, img0, spec['lightbar'], sty, spr, sw, sh, kx, kz, log)
    if spec.get('roof_sign'):
        roof_sign(kc, shell, spec['roof_sign'], sty, spr, sw, sh, kx, kz, e, log)

    # the shell
    keepF = F[~kill]
    CN = smooth_normals(V, keepF)
    Vx, Fx, UVx, Nx = expand(V, keepF, UV, CN)
    # trimesh hands glTF texture coordinates back flipped (v up); carkit writes them as glTF has them (v down)
    kc.part('shell').add(Vx, Nx, np.stack([UVx[:, 0], 1.0 - UVx[:, 1]], 1), Fx)
    tsz = spec.get('texture', TEX_LIVERY if livery else TEX_SPLIT)
    kc.materials['shell'] = Image.fromarray((img * 255).astype(np.uint8)).resize((tsz, tsz), Image.LANCZOS)
    if mr is not None:
        kc.mr = mr.resize((tsz, tsz), Image.LANCZOS)

    # wheels (after the shell: their parts are their own)
    for wh in wheels:
        nm = ('wheel_f' if wh['front'] else 'wheel_r') + ('r' if wh['side'] > 0 else 'l')
        build_wheel(kc, nm, wh, wh['face_mat'], wh['band'])
    set_materials(kc, wheels, paint_rgb, livery)
    return kc, dict(model=m, name=name, faces=int(len(keepF)), wheels=[{k: v for k, v in w.items()} for w in wheels],
                    lamps={k: [list(map(float, l)) for l in v] for k, v in lamps.items()}, livery=livery, mr=mr is not None)


def recolour(img, rc):
    """{"from": [r,g,b], "to": [r,g,b], "hue_tol": deg, "sat_min": s}: texels of the source hue mapped to the target
    colour, their shading kept (luminance ratio to the source's median)"""
    src = np.array(rc['from'], float) / 255; dst = np.array(rc['to'], float) / 255
    H = lambda c: np.degrees(np.arctan2(math.sqrt(3) * (c[..., 1] - c[..., 2]), 2 * c[..., 0] - c[..., 1] - c[..., 2]))
    dh = np.abs((H(img) - H(src) + 180) % 360 - 180)
    m = (dh < rc.get('hue_tol', 25)) & (sat(img) > rc.get('sat_min', 0.08))
    if rc.get('lum_max') is not None: m &= lum(img) < rc['lum_max']
    l = lum(img)[..., None]; ls = float(np.median(lum(img)[m])) if m.any() else float(lum(src))
    out = img.copy()
    out[m] = np.clip((dst[None] * (l[m] / max(ls, 1e-3)) ** rc.get('gamma', 1.0)), 0, 1)
    mm = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))
    a = np.asarray(mm).astype(float)[..., None] / 255
    return img * (1 - a) + out * a


def lightbar(kc, V, F, UV, img, spec, sty, spr, sw, sh, kx, kz, log):
    """the cop car's roof lamps, rebuilt: the generated domes (saturated blue / red texels standing above the roof)
    pressed into the roof and painted over, then a slim dark base, a grey siren block on the centre line and two
    domes along each side as the sprite shows them (its siren deltas: the blue pair on +x, the red pair on -x for the
    cop car; spec "+x"/"-x"), placed where the generator put its lamps (the roof's own lamp spot)"""
    top = V[:, 1] > 0.75 * V[:, 1].max()
    c = tex_at(img, UV)
    r_, g_, b_ = c[:, 0], c[:, 1], c[:, 2]
    blobc = ((b_ > r_ + 0.18) & (b_ > g_ + 0.10)) | ((r_ > g_ + 0.25) & (r_ > b_ + 0.15))
    blob = top & blobc
    if blob.sum() < 20:
        log('  lightbar: no generated lamps found on the roof'); return np.zeros(len(F), bool)
    bx = V[blob, 0]; bz = V[blob, 2]
    x0, x1 = np.percentile(bx, 2), np.percentile(bx, 98); z0, z1 = np.percentile(bz, 2), np.percentile(bz, 98)
    cxm, czm = 0.5 * (x0 + x1), 0.5 * (z0 + z1)
    hx, hz = 0.5 * (x1 - x0), 0.5 * (z1 - z0)
    ring = top & ~blobc & (np.abs(V[:, 0] - cxm) < hx + 0.09) & (np.abs(V[:, 2] - czm) < hz + 0.09) & \
        ~((np.abs(V[:, 0] - cxm) < hx + 0.015) & (np.abs(V[:, 2] - czm) < hz + 0.015))
    roof = float(np.median(V[ring, 1])) if ring.sum() > 10 else float(np.percentile(V[top, 1], 50))
    press = (np.abs(V[:, 0] - cxm) < hx + 0.035) & (np.abs(V[:, 2] - czm) < hz + 0.035) & (V[:, 1] > roof - 0.006)
    # pressed onto the roof's own surface (the ring's height near each vertex) and given the clean roof's texels
    rv = np.flatnonzero(ring)
    from scipy.spatial import cKDTree
    tr = cKDTree(V[rv][:, [0, 2]])
    pv = np.flatnonzero(press)
    _, nn = tr.query(V[pv][:, [0, 2]], k=6)
    V[pv, 1] = np.median(V[rv[nn], 1], 1)
    _, n1 = tr.query(V[pv][:, [0, 2]], k=1)
    UV[pv] = UV[rv[n1]]
    base_h = spec.get('base_h', 0.006)
    # the siren block on the centre line
    _, ns = tr.query([[cxm, czm]], k=8); ys_ = float(np.median(V[rv[ns[0]], 1]))
    kc.box('siren', (cxm - 0.018, ys_ - 0.004, czm - 0.6 * hz), (cxm + 0.018, ys_ + 0.024, czm + 0.6 * hz))
    kc.materials['siren'] = K.tex_flat((120, 122, 126))
    # two domes a side, along the car
    rd = min(0.034, 0.45 * min(hx, hz)) * spec.get('dome_scale', 1.0)
    for side in (-1, 1):
        col = spec.get('+x' if side > 0 else '-x', 'blue' if side > 0 else 'red')
        mat = 'beacon_blue' if col == 'blue' else 'beacon_red'
        x = cxm + side * (hx - rd * 0.6)
        for zz in (czm - 0.5 * hz, czm + 0.5 * hz):
            _, nd = tr.query([[x, zz]], k=8); roof = float(np.median(V[rv[nd[0]], 1]))
            prof = [(rd, 0.0)] + [(rd * math.cos(t) + 1e-5, 0.85 * rd * math.sin(t)) for t in np.linspace(0.12, math.pi / 2, 8)]
            kc.revolve(prof, (x, roof + base_h, zz), (0, 1, 0), 24, default=mat, uv_mode='disc')
            # a dark chrome-rimmed plinth under each dome
            kc.revolve([(rd * 1.18, -0.004), (rd * 1.18, base_h), (rd * 0.9, base_h + 0.001)], (x, roof, zz), (0, 1, 0), 24,
                       default='lightbar_base', uv_mode='disc')
        kc.materials['lightbar_base'] = K.tex_flat((30, 30, 32))
        kc.materials[mat] = tex_dome((225, 30, 22) if mat == 'beacon_red' else (30, 70, 230))
    log(f'  lightbar: on the generated lamps x {x0:.3f}..{x1:.3f} z {z0:.3f}..{z1:.3f}, roof {roof:.3f}, dome r {rd:.3f}, {int(press.sum())} shell vertices pressed')
    return np.zeros(len(F), bool)


def tex_dome(rgb, size=64):
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0) * 2 - 1
    r = np.hypot(xx, yy)
    rib = 0.88 + 0.12 * (0.5 + 0.5 * np.cos(np.arctan2(yy, xx) * 18))
    b = (0.70 + 0.45 * (1 - r)) * rib
    c = np.array(rgb, float)[None, None] * b[..., None]
    c += np.exp(-(((xx + 0.3) ** 2 + (yy + 0.3) ** 2) / 0.03))[..., None] * 90
    return Image.fromarray(np.clip(c, 0, 255).astype(np.uint8))


def roof_sign(kc, shell, spec, sty, spr, sw, sh, kx, kz, e, log):
    """a taxi's roof sign as the sprite shows it: a box across the roof at the sprite's sign (spec "rect": [x0, y0,
    x1, y1] in sprite pixels), its front and back faces a lit "TAXI" panel ("sign": the Remix layer makes it glow),
    a dark top and frame as the sprite's sign seen from above"""
    x0p, y0p, x1p, y1p = spec['rect']
    xa = -(x0p - sw / 2) / 64 * kx; xb = -(x1p - sw / 2) / 64 * kx
    za = (y0p - sh / 2) / 64 * kz; zb = (y1p - sh / 2) / 64 * kz
    xlo, xhi = min(xa, xb), max(xa, xb); zlo, zhi = min(za, zb), max(za, zb)
    zs = np.linspace(zlo, zhi, 5); xs = np.linspace(xlo, xhi, 5)
    ys = []
    for x in xs:
        for z in zs:
            loc = ray_hits(shell, np.array([x, 5.0, z]), np.array([0, -1.0, 0]))
            if len(loc): ys.append(loc[:, 1].max())
    roof_lo = float(min(ys)); roof_hi = float(max(ys))
    h = spec.get('height', 0.045)
    base = roof_lo - 0.004; topy = roof_hi + h
    kc.box('sign_body', (xlo, base, zlo), (xhi, topy, zhi))
    kc.materials['sign_body'] = K.tex_flat(tuple(spec.get('body_rgb', (34, 30, 26))))
    panel = sign_panel(spec.get('text', 'TAXI'), spec.get('panel_rgb', (246, 226, 168)))
    kc.materials['sign'] = panel
    inset = 0.006
    for zf, end in ((zhi + 0.0012, 1), (zlo - 0.0012, -1)):
        # seen from outside: left of the panel at -x for the +z face seen from the front (x to the viewer's right
        # is -x), so u runs with -x on the front face and with +x on the back face
        y0, y1 = roof_hi + 0.004, topy - 0.004
        P = np.array([[xhi - inset, y0, zf], [xlo + inset, y0, zf], [xlo + inset, y1, zf], [xhi - inset, y1, zf]])
        if end > 0:
            T = np.array([[1, 1], [0, 1], [0, 0], [1, 0]], float); f = np.array([[0, 1, 2], [0, 2, 3]])
        else:
            T = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], float); f = np.array([[0, 2, 1], [0, 3, 2]])
        kc.part('sign').add(P, np.tile([[0, 0, float(end)]], (4, 1)), T, f)
    log(f'  roof sign: x {xlo:.3f}..{xhi:.3f} z {zlo:.3f}..{zhi:.3f}, roof {roof_lo:.3f}..{roof_hi:.3f}, top {topy:.3f}')


def sign_panel(text, rgb, size=(256, 80)):
    from PIL import ImageFont
    im = Image.new('RGB', size, tuple(rgb)); d = ImageDraw.Draw(im)
    font = None
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',):
        if os.path.exists(p): font = ImageFont.truetype(p, 52)
    font = font or ImageFont.load_default()
    w = d.textlength(text, font=font)
    d.text(((size[0] - w) / 2, 10), text, fill=(28, 24, 20), font=font)
    return im


def set_materials(kc, wheels, paint_rgb, livery):
    kc.materials['lamp_head'] = K.tex_lamp('head')
    kc.materials['lamp_tail'] = K.tex_lamp('tail')
    kc.materials['tyre_tread'] = K.tex_tread()
    kc.materials['tyre_side'] = K.tex_tyre_side()
    kc.materials['whitewall'] = K.tex_flat((228, 226, 218))
    kc.materials['underbody'] = K.tex_underbody()
    kc.materials['hubback'] = K.tex_flat((22, 22, 24))
    # a body-colour rim: neutral, the shell's paint level (the tint gives it the car's colour)
    kc.materials['paint_wheel'] = K.tex_flat((200, 200, 200))


def write(kc, out_src, name, info, livery):
    os.makedirs(os.path.join(out_src, name), exist_ok=True)
    order = ['shell']
    mats = write_glb(kc, os.path.join(out_src, name + '.glb'), order)
    tex = {}
    for mt in mats:
        if mt == 'shell': continue
        p = os.path.join(out_src, name, f'{mt}.png'); kc.materials[mt].save(p); tex[mt] = f'cars/models_hy/{name}/{mt}.png'
    kc.materials['shell'].save(os.path.join(out_src, name, 'shell.png'))
    if getattr(kc, 'mr', None) is not None:
        kc.mr.save(os.path.join(out_src, name, 'shell_mr.png'))
    e = car(info['model'])
    entry = {'name': name, 'glb': f'cars/models_hy/{name}.glb', 'scale': 1.0,
             'paint_rgb': [float(c) for c in e['remaps'][0]['paint_rgb']] if not livery else [235.0, 235.0, 235.0],
             'texture_max': int(kc.materials['shell'].size[0]), 'material_textures': tex, 'wheel_parts': True,
             'generator': 'tools/hy_car/hy_convert.py (Hunyuan3D 2.1 shell, Tencent Hunyuan 3D 2.1 Community License)'}
    if not livery:
        entry['paint_split'] = True
    return entry


EMISSIVE = {'sign': [1.0, 0.88, 0.62]}   # lit by night and day (a taxi's roof sign); the lamps glow by the renderer's lights


def write_glb(car_, path, order):
    """carkit.write_glb, then the emissive parts given an emissiveFactor (tools/remix_model_pbr.py makes them glow under
    Remix). Node names must not start with "wheel_": the renderer takes such nodes as wheel markers."""
    import struct
    for m in car_.parts:
        assert not m.startswith('wheel_'), m
    mats = K.write_glb(car_, path, scale=1.0, order=order)
    b = open(path, 'rb').read()
    jl = struct.unpack('<I', b[12:16])[0]; js = json.loads(b[20:20 + jl]); rest = b[20 + jl:]
    for mt in js.get('materials', []):
        if mt.get('name') in EMISSIVE: mt['emissiveFactor'] = EMISSIVE[mt['name']]
    j = json.dumps(js).encode()
    while len(j) % 4: j += b' '
    out = b'glTF' + struct.pack('<II', 2, 12 + 8 + len(j) + len(rest)) + struct.pack('<I', len(j)) + b'JSON' + j + rest
    open(path, 'wb').write(out)
    return mats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out'); ap.add_argument('models', nargs='+')
    ap.add_argument('--src', default='/mnt/gta2/out/carhy')
    ap.add_argument('--spec', default=os.path.join(HERE, 'specs.json'))
    ap.add_argument('--no-import', action='store_true')
    a = ap.parse_args()
    specs = json.load(open(a.spec))
    out = os.path.abspath(a.out); src_root = os.path.join(out, 'src'); out_src = os.path.join(src_root, 'cars', 'models_hy')
    models_dir = os.path.join(out, 'models')
    os.makedirs(out_src, exist_ok=True); os.makedirs(models_dir, exist_ok=True)
    logf = open(os.path.join(out, 'convert.log'), 'a')

    def log(s):
        print(s, flush=True); logf.write(s + '\n'); logf.flush()
    entries = []; infos = {}
    for ms in a.models:
        m = int(ms); spec = specs[f'{m:03d}']
        kc, info = build(m, spec, a.src, log)
        entries.append(write(kc, out_src, spec['name'], info, info['livery']))
        infos[spec['name']] = info
        v, f = kc.stats(); log(f'  -> {spec["name"]}: {v} vertices, {f} triangles in {len(kc.parts)} parts')
    json.dump({'models': entries}, open(os.path.join(src_root, 'manifest.json'), 'w'), indent=1)
    json.dump(infos, open(os.path.join(out, 'info.json'), 'w'), indent=1)
    if a.no_import:
        return
    py = sys.executable
    subprocess.check_call([py, os.path.join(TOOLS, 'import_assets.py'), os.path.join(src_root, 'manifest.json'), models_dir])
    split = [e['name'] for e in entries if e.get('paint_split')]
    if split:
        subprocess.check_call([py, os.path.join(TOOLS, 'car_paint_resplit.py'), models_dir, '--only', ','.join(n[:3] for n in split)])
    # the generator's shells face outward and the parts here are built facing the right way (the liners and the
    # wheel discs on both sides), so car_mesh_orient only checks (its patch rule would turn one copy of a two-sided
    # liner round onto the other)
    import car_mesh_orient, underpan
    car_mesh_orient.check(models_dir, [e['name'] for e in entries])
    for e in entries:
        if e['name'][:3] not in underpan.SKIP:
            underpan.apply(models_dir, models_dir, e['name'])


if __name__ == '__main__':
    main()
