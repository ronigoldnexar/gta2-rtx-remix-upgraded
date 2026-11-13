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
     by tools/car_paint_resplit.py after the import over the body's whole hue family, its broad shading half
     flattened: a two-tone generated body takes the remap colour as the sprite does) and whose parts carry
     surface-named textures. Remix prims: tools/hy_car/remix_prims.sh.
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


def fit_wheel(R, zc0, zsign, window=0.2, dthr=0.10, tyre_lum=0.16, tyre_sat=0.10):
    """the tyre circle near the axle hint zc0 (model z) on a side render: a dark, unsaturated disc on the outer face
    touching the road, with a lighter rim inside it and no dark tyre just outside it. -> (score, r, zc, outer depth)"""
    u0, u1, v0, v1 = R['extent']; res = R['res']; H, W = R['alpha'].shape
    alb = R['albedo']; L = lum(alb); S = sat(alb)
    near = R['alpha'] & (R['depth'] < dthr)
    tyre = near & (L < tyre_lum) & (S < tyre_sat)   # specs "tyre_lum"/"tyre_sat" for a generator's brown tyres (016)
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


HUB = 0.64   # the rim's edge, fraction of the tyre radius: the wheel face texture covers the hub disc inside it


def wheel_face(R, zc, r, zsign, ground_pad=0.01, size=128, sector=(210.0, 330.0), rmax=HUB):
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
    u = uc + np.cos(ths) * rho * r * rmax; v = yc + np.sin(ths) * rho * r * rmax
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
    m[int(0.74 * len(m)):] = False   # the tyre wall is never paint (016's brown tyres share the body's hue)
    if m.sum() < 3: return None
    idx = np.flatnonzero(m)
    # every run of paint bins (a painted hub centre and a painted rim ring are separate rings; 007): [(lo, hi), ...]
    runs = [rn for rn in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1) if len(rn) >= 2]
    if not runs or max(len(rn) for rn in runs) < 3: return None
    # a run from near the centre is the whole cap (its middle often reads off-hue under a baked highlight)
    return [(0.0 if rn[0] < 8 else rn[0] / 32.0, (rn[-1] + 1) / 32.0) for rn in runs]


def build_wheel(kc, nm, wh, face_mat, band):
    """a period wheel, sized as the shell's own: a tyre with a rounded, bulging sidewall and a tread, a whitewall a
    third of the sidewall wide where the shell's wheel had one, a rim dished in from the bead and a domed hubcap
    that wears the shell's own hub (the sampled face, made round, with lug nuts). A body-colour band on the hub
    (band, fractions of r) is its own ring under the neutral paint_wheel. Profiles: (radius, offset along the axle
    outward), fractions of r and of the width w."""
    r, w, s = wh['r'], wh['width'], wh['side']
    cx = s * (wh['outer'] - 0.5 * w)
    c = (cx, r, wh['zc']); ax = (s, 0, 0)
    ww = wh['style'].get('whitewall', 0) > 0.5
    # outer sidewall from the tread shoulder down to the bead, bulging out mid-wall
    side = [(1.0, 0.33), (0.985, 0.43), (0.95, 0.49), (0.88, 0.52), (0.80, 0.52), (0.72, 0.49), (0.67, 0.45), (HUB, 0.42)]
    if ww:   # the whitewall: 0.71..0.82 of r (a third of the 0.64..1.0 sidewall)
        pts = sorted(set([p[0] for p in side] + [0.71, 0.82]), reverse=True)
        side = [(q, float(np.interp(q, [p[0] for p in side][::-1], [p[1] for p in side][::-1]))) for q in pts]
    kc.revolve([(a * r, b * w) for a, b in side], c, ax, 32,
               mat_of=lambda k: 'whitewall' if ww and 0.71 <= 0.5 * (side[k][0] + side[k + 1][0]) <= 0.82 else 'tyre_side', uv_mode='tyre')
    kc.revolve([(r, 0.33 * w), (1.0 * r, -0.33 * w)], c, ax, 32, default='tyre_tread', uv_mode='tyre')
    kc.revolve([(r, -0.33 * w), (0.985 * r, -0.43 * w), (0.92 * r, -0.50 * w), (0.80 * r, -0.51 * w), (HUB * r, -0.44 * w)], c, ax, 28,
               default='tyre_side', uv_mode='tyre')
    # rim and hubcap: the rim dishes in from the bead, the cap domes out to the tyre's face
    hub = [(HUB, 0.42), (0.60, 0.34), (0.52, 0.29), (0.46, 0.31), (0.40, 0.38), (0.30, 0.44), (0.18, 0.475), (0.06, 0.49), (0.0, 0.49)]
    if band is not None:
        pts = sorted(set([p[0] for p in hub] + [round(min(q, HUB), 4) for bd in band for q in bd]), reverse=True)
        hub = [(q, float(np.interp(q, [p[0] for p in hub][::-1], [p[1] for p in hub][::-1]))) for q in pts]
    def mat_hub(k):
        a = 0.5 * (hub[k][0] + hub[k + 1][0])
        if band is not None and any(lo <= a <= hi for lo, hi in band): return 'paint_wheel'
        return face_mat
    kc.revolve([(a * r, b * w) for a, b in hub], c, ax, 28, mat_of=mat_hub, uv_mode='disc')
    kc.revolve([(HUB * r, -0.44 * w), (0.001, -0.38 * w)], c, ax, 20, default='hubback', uv_mode='disc')
    kc.marker(nm, c)


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
    front = R["alpha"] & (R["depth"] < dmin + 0.30)   # a truck's lamps sit in the fenders well behind its bumper
    U = u0 + (np.arange(W) + 0.5) * res; Vv = v1 - (np.arange(H) + 0.5) * res
    uu, vv = np.meshgrid(U, Vv)
    # head lamps sit at the fenders' height: not the bumper's chrome bullets or fog lamps (051 took a bumper bullet)
    band = (vv > (0.18 if kind == 'head' else 0.06) * height) & (vv < 0.80 * height) & (np.abs(uu) > 0.12 * hw)
    if kind == 'head':
        m = front & band & (L > 0.45) & (S < 0.45)   # sealed beams are often cream (007)
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
    # the arch outline found on a render is noisy (texel steps, a lip's shadow): a running median then a mean, and
    # a little outside it, so the liner's edge sits behind the fender's own lip and never shows as teeth
    from scipy.ndimage import median_filter, uniform_filter1d
    rad = uniform_filter1d(median_filter(rad, size=7, mode='nearest'), size=5, mode='nearest')
    rad = np.clip(rad + 0.010, 1.06 * r, 1.45 * r)
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
    # fanned from the axle (not the road): nothing of the wall hangs below the axle, where it showed as dark spikes
    # under a low car (007, 012) and is not needed (the well is open below)
    C = np.array([[x_in, yc, zc]])
    W = np.concatenate([C, np.stack([np.full(n, x_in), pts[:, 1], pts[:, 0]], 1)])
    Fw = np.array([(0, i + 1, i + 2) for i in range(n - 1)])
    Nw = np.tile([[side * 1.0, 0, 0]], (len(W), 1))
    Tw = np.stack([0.5 + (W[:, 2] - zc) / (4 * r), W[:, 1] / (4 * r)], 1)
    car_.part('underbody').add(W, Nw, Tw, Fw)
    car_.part('underbody').add(W, -Nw, Tw, Fw[:, ::-1])


def cut_wheel(V, F, UV, img, wheel, side, paint_rgb=None):
    """faces of the fused tyre and hub: wholly inside 0.97 r of the axle (outboard of the inner wall), or wholly
    inside 1.10 r and textured as tyre (dark, grey). Not the body's own skin over the wheel: a fender skirt or lip in
    the body's colour on the outer face (at or outboard of the tyre's face) stays, as the generator shaped it, and the
    new wheel turns behind it (cutting those away showed whole wheels that read 25-30 % too big)."""
    zc, r = wheel['zc'], wheel['r']
    sx = side * V[:, 0]
    d = np.hypot(V[:, 1] - r, V[:, 2] - zc)
    out_ok = sx > wheel['wall'] - 0.002
    in1 = (d < 0.97 * r) & out_ok; in2 = (d < 1.10 * r) & out_ok
    c = tex_at(img, UV[F].mean(1))
    dark = (lum(c) < 0.20) & (sat(c) < 0.14)
    kill = in1[F].all(1) | (in2[F].all(1) & dark)
    if paint_rgb is not None:
        pr = np.array(paint_rgb, float) / 255
        hue = lambda q: np.degrees(np.arctan2(math.sqrt(3) * (q[..., 1] - q[..., 2]), 2 * q[..., 0] - q[..., 1] - q[..., 2]))
        body = (sat(c) > 0.15) & (np.abs((hue(c) - hue(pr) + 180) % 360 - 180) < 40) & ~dark
        # a skirt hangs over the wheel's rim, never over its middle: a body-coloured hub (007) is still cut
        skin = ((side * V[F][:, :, 0]).min(1) > wheel['outer'] - 0.006) & (d[F].min(1) > 0.75 * r)
        kill &= ~(body & skin)
    return kill


# ---------------------------------------------------------------------------------------------------------------
# main build
# ---------------------------------------------------------------------------------------------------------------

def build(m, spec, src, log):
    e = car(m)
    V, F, UV, tex, mr = load(m, spec.get('src', src))   # specs "src": a re-picked generation (fix-list cars)
    if spec.get('nose', '+z') == '-z':
        V = turn(V)
    if 'keep_z' in spec:
        # specs "keep_z": [lo, hi] fractions of the length (nose +z = 1) to keep - a trailer generated with its tractor
        # (066) loses the cab; what is left is stretched back to the sprite's length
        z0, z1 = V[:, 2].min(), V[:, 2].max(); lo, hi = [z0 + q * (z1 - z0) for q in spec['keep_z']]
        keep = ((V[F][:, :, 2] >= lo) & (V[F][:, :, 2] <= hi)).all(1)
        F = F[keep]
        V = V.copy(); V[:, 2] = z0 + (np.clip(V[:, 2], lo, hi) - lo) / (hi - lo) * (z1 - z0)
    F, dropped = drop_bits(V, F, UV)
    livery = m in LIVERY
    target = spec.get('faces', FACES_LIVERY if livery else FACES_SPLIT)
    V, F, UV = decimate(V, F, UV, target)
    img = np.asarray(tex).astype(np.float64) / 255.0
    paint_rgb = e['remaps'][0]['paint_rgb']
    log(f'{m:03d}: {len(F)} faces after clean ({dropped} dropped) and decimation, nose {spec.get("nose", "+z")}')
    hw = float(np.abs(V[:, 0]).max()); height = float(V[:, 1].max()); L = float(V[:, 2].max() - V[:, 2].min())

    # texture edits (recolours) before anything samples the picture
    if spec.get('smooth_chrome', True):
        smooth_chrome(V, F, UV, img, log)
    img0 = img
    for rc in spec.get('recolour', []):
        img = recolour(img, rc)

    shell = trimesh.Trimesh(V, F, process=False)
    shell.visual = trimesh.visual.TextureVisuals(uv=UV, image=Image.fromarray((img * 255).astype(np.uint8)))

    name = spec['name']
    kc = K.Car(name)
    wheels = []
    kill = np.zeros(len(F), bool)
    if m not in STATIC_WHEELS and not spec.get('static_wheels'):   # 036: the body hides its wheels to the ground
        k = L / e['body_blocks'][1]
        hints = spec.get('axles') or [e['wheels_px']['front_offset'] / 64 * k, e['wheels_px']['rear_offset'] / 64 * k]
        renders = {+1: side_render(shell, 'side+'), -1: side_render(shell, 'side-')}
        fine = {+1: HR.render([shell], 'side+', res=0.0007), -1: HR.render([shell], 'side-', res=0.0007)}
        for ai, zh in enumerate(hints):
            fits = {}
            for side, R in renders.items():
                fits[side] = fit_wheel(R, zh, 1 if side > 0 else -1, window=spec.get('axle_window', max(0.2, 0.25 * L)),   # a bus's CARI axles sit far from its generated wheels
                                      
                                       tyre_lum=spec.get('tyre_lum', 0.16), tyre_sat=spec.get('tyre_sat', 0.10))
            r = float(np.mean([f[1] for f in fits.values()])); zc = float(np.mean([f[2] for f in fits.values()]))
            fix = (spec.get('wheel_fix') or [None] * len(hints))[ai]
            if fix:
                # specs "wheel_fix": [[zc, r] or null per axle], read off the shell's side grid where the fit takes a hub
                # (045), a skirt (031) or a bus's arch (011) for the wheel
                log(f'  axle {ai}: fit zc {zc:+.3f} r {r:.3f} overridden by the spec: zc {fix[0]:+.3f} r {fix[1]:.3f}')
                zc, r = float(fix[0]), float(fix[1])
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
                if st.get('whitewall', 0) > 0.5:
                    # a whitewall car wears chrome caps; a generated hub that reads as a dark hole (000) gets a
                    # chrome dome (bright centre, darker toward the rim) with its lug nuts kept
                    n_ = fimg.shape[0]; yy_, xx_ = np.mgrid[0:n_, 0:n_]
                    rho_ = np.hypot((xx_ + 0.5) / n_ * 2 - 1, (yy_ + 0.5) / n_ * 2 - 1)
                    mid = rho_ < 0.75
                    if True:   # every whitewall car: the generated hubs read as dark holes (000) or target rings (070)
                        base = np.clip(0.86 - 0.30 * rho_, 0.5, 0.9)[..., None] * np.array([1.0, 1.0, 1.02])
                        ring = (np.abs(rho_ - 0.62) < 0.03)[..., None]
                        cap = np.where(ring, 0.45, base)
                        lugd = lum(fimg) / np.maximum(np.median(lum(fimg[mid])), 1e-3)
                        cap = cap * np.clip(lugd, 0.45, 1.0)[..., None] ** 0.5
                        fimg = np.where(mid[..., None], cap, fimg)
                wh['band'] = None if livery else paint_band(fprof, paint_rgb)
                wh['face_mat'] = f'hubface_{ai}{"r" if side > 0 else "l"}'
                kc.materials[wh['face_mat']] = Image.fromarray((np.clip(fimg, 0, 1) * 255).astype(np.uint8))
                wheels.append(wh)
                kill |= cut_wheel(V, F, UV, img, wh, side, spec.get('body_rgb', paint_rgb))
                arch_parts(kc, wh, side, angs, prof, hw)
            log(f'  axle {ai}: hint {zh:+.3f} -> zc {zc:+.3f} r {r:.3f} (scores {fits[1][0]:.2f} / {fits[-1][0]:.2f}), '
                f'style {wheels[-1]["style"]["rim"]}/{wheels[-1]["style"]["cap"]} whitewall {wheels[-1]["style"]["whitewall"]:.0f} band {wheels[-1]["band"]}')
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
        if spec.get(kind + '_lamp'):
            # specs "head_lamp"/"tail_lamp": [x, y, radius] where the search takes the wrong part (051's dark-eyed
            # headlamps lose to its bumper's chrome bullets); mirrored to the other side
            x, y, rr = spec[kind + '_lamp']
            lamps[kind] = [(x, y, 0.0, rr), (-x, y, 0.0, rr)]
        found = lamps[kind]
        if len(found) == 1:
            # the car is symmetric: the other side's lamp mirrors the one found (a chrome bezel or a shadow hid it)
            x, y, z, rr = found[0]
            zs = surface_z_at(shell, -x, y, end)
            if zs is not None and abs(zs - z) < 0.03:
                found.append((-x, y, zs, rr))
                log(f'  {kind} lamps: one found, the other mirrored')
        if len(found) < 2:
            # LensSpotsFor wants both sides; a guessed lens on the wrong panel is worse than the renderer's own spot
            log(f'  {kind} lamps: {len(found)} found on the shell: no lenses (the renderer places the glow)')
            lamps[kind] = []
            continue
        log(f'  {kind} lamps: {len(found)} found on the shell')
        for (x, y, z, rr) in found:
            rr = float(np.clip(rr * 0.95, 0.010, 0.030))
            zs = surface_z_at(shell, x, y, end)
            lamp_lens(kc, 'lamp_' + kind, x, y, (zs if zs is not None else z), rr, end)
        lamps[kind] = found

    # specials
    if spec.get('lightbar'):
        kill |= lightbar(kc, V, F, UV, img0, spec['lightbar'], sty, spr, sw, sh, kx, kz, log, paint_img=img)
    if spec.get('roof_sign'):
        roof_sign(kc, shell, spec['roof_sign'], sty, spr, sw, sh, kx, kz, e, log)
    if 'roof_gun' in spec:
        roof_gun(kc, shell, spec['roof_gun'], log)

    # the shell
    keepF = F[~kill]
    CN = smooth_normals(V, keepF)
    Vx, Fx, UVx, Nx = expand(V, keepF, UV, CN)
    # trimesh hands glTF texture coordinates back flipped (v up); carkit writes them as glTF has them (v down)
    kc.part('shell').add(Vx, Nx, np.stack([UVx[:, 0], 1.0 - UVx[:, 1]], 1), Fx)
    tsz = spec.get('texture', TEX_LIVERY if livery else TEX_SPLIT)
    kc.paint_force = None
    if not livery and spec.get('flank_paint', True):
        kc.paint_force = flank_paint_mask(V, keepF, UV, img, tsz, e, sty, spr, sw, sh, kx, kz, log)
    kc.materials['shell'] = Image.fromarray((img * 255).astype(np.uint8)).resize((tsz, tsz), Image.LANCZOS)
    if mr is not None:
        kc.mr = mr.resize((tsz, tsz), Image.LANCZOS)
    if spec.get('decals'):
        kc.materials['shell'] = apply_decals(kc.materials['shell'], V, keepF, UV, spec['decals'], log)

    # wheels (after the shell: their parts are their own)
    for wh in wheels:
        nm = ('wheel_f' if wh['front'] else 'wheel_r') + ('r' if wh['side'] > 0 else 'l')
        build_wheel(kc, nm, wh, wh['face_mat'], wh['band'])
    set_materials(kc, wheels, paint_rgb, livery)
    return kc, dict(model=m, name=name, faces=int(len(keepF)), wheels=[{k: v for k, v in w.items()} for w in wheels],
                    lamps={k: [list(map(float, l)) for l in v] for k, v in lamps.items()}, livery=livery, mr=mr is not None)


def decal_image(d, px_per_block=1600):
    """an RGBA decal: "text" (bold sans, the colour, a thin outline) or "badge" (a gold six-point star shield)"""
    from PIL import ImageFont
    w = int((d['z'][1] - d['z'][0]) * px_per_block); h = int((d['y'][1] - d['y'][0]) * px_per_block)
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    rgb = tuple(d.get('rgb', (24, 36, 110)))
    if d['kind'] == 'text':
        fs = h
        for fp in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',):
            if os.path.exists(fp):
                while fs > 6:
                    font = ImageFont.truetype(fp, fs)
                    if dr.textlength(d['text'], font=font) <= w * 0.96: break
                    fs -= 2
        bb = dr.textbbox((0, 0), d['text'], font=font)
        x = (w - (bb[2] - bb[0])) / 2 - bb[0]; y = (h - (bb[3] - bb[1])) / 2 - bb[1]
        dr.text((x, y), d['text'], font=font, fill=rgb + (255,))
    else:   # a shield with a star
        cx, cy = w / 2, h / 2; R = min(w, h) * 0.46
        shield = [(cx - R * 0.8, cy - R * 0.9), (cx + R * 0.8, cy - R * 0.9), (cx + R * 0.8, cy + R * 0.1), (cx, cy + R), (cx - R * 0.8, cy + R * 0.1)]
        dr.polygon(shield, fill=(212, 170, 60, 255), outline=rgb + (255,))
        star = []
        for k in range(10):
            a = -math.pi / 2 + k * math.pi / 5; rr = R * (0.5 if k % 2 == 0 else 0.22)
            star.append((cx + rr * math.cos(a), cy - R * 0.15 + rr * math.sin(a)))
        dr.polygon(star, fill=rgb + (255,))
    return im


def apply_decals(shell_img, V, F, UV, decals, log):
    """decals painted into the shell's texture where the body's side faces carry them: each texel's surface point
    (its triangle rasterised in UV space) inside a decal's z/y rectangle on that side takes the decal's colour,
    read so the text runs nose-ward on the right side and tail-ward on the left (as seen from beside the car)"""
    import texmap
    size = shell_img.size[0]
    pos, nrm, valid = texmap.texel_maps(V, F, UV, size)
    out = np.asarray(shell_img.convert('RGB')).astype(np.float32)
    hw = np.abs(V[:, 0]).max(); n_all = 0
    for d in decals:
        im = np.asarray(decal_image(d)).astype(np.float32) / 255; dh, dw = im.shape[:2]
        for side in d.get('sides', [1, -1]):
            m = valid & (side * nrm[..., 0] > 0.4) & (side * pos[..., 0] > 0.5 * hw)
            z, y = pos[..., 2], pos[..., 1]
            m &= (z >= d['z'][0]) & (z <= d['z'][1]) & (y >= d['y'][0]) & (y <= d['y'][1])
            u = (z - d['z'][0]) / (d['z'][1] - d['z'][0])
            if side > 0: u = 1 - u      # from the car's right side the nose is to the viewer's right... the text runs that way
            v = (d['y'][1] - y) / (d['y'][1] - d['y'][0])
            j = np.clip((u * dw).astype(int), 0, dw - 1); i = np.clip((v * dh).astype(int), 0, dh - 1)
            a = im[i, j, 3] * m
            out = out * (1 - a[..., None]) + im[i, j, :3] * 255 * a[..., None]
            n_all += int((a > 0.5).sum())
    log(f'  decals: {len(decals)} painted, {n_all} texels')
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def flank_paint_mask(V, F, UV, img, size, e, sty, spr, sw, sh, kx, kz, log):
    """the game recolours a remapped car's whole body; a generated body is often two-tone below the belt (000's navy
    flanks under maroon). The texels of the body's side panels (facing sideways, between the sills and the belt)
    that the sprite paints in body colour along that stretch of the car go to the paint half whatever their hue
    (not black trim, chrome, lamps or glass). -> mask (size, size) bool, image rows as the texture's."""
    import texmap
    pos, nrm, valid = texmap.texel_maps(V, F, UV, size)
    H = V[:, 1].max(); hw = np.abs(V[:, 0]).max()
    c = np.asarray(Image.fromarray((img * 255).astype(np.uint8)).resize((size, size), Image.BILINEAR)).astype(np.float64) / 255
    L = lum(c); S = sat(c)
    # the belt: the lowest glass-like (dark blue-grey) texel band on the sides, else 0.55 of the height
    belt = 0.55 * H
    sidef = valid & (np.abs(nrm[..., 0]) > 0.55) & (np.abs(nrm[..., 1]) < 0.6)
    panel = sidef & (pos[..., 1] > 0.06 * H) & (pos[..., 1] < belt) & (np.abs(pos[..., 0]) > 0.6 * hw)
    # not chrome (bright, grey); a dark navy flank (000) is near black, so darkness alone does not exclude a texel
    ok = panel & ~((L > 0.55) & (S < 0.14))
    # the sprite: is the body's outer edge body colour at this z (its remap palette's paint)?
    sp = Image.open(os.path.join(ASRC, 'cars', e['remaps'][0]['file_x4'])).convert('RGBA'); s4 = sp.width / sw
    a = np.asarray(sp).astype(np.float64) / 255
    pr = np.array(e['remaps'][0]['paint_rgb'], float) / 255
    hue = lambda q: np.degrees(np.arctan2(math.sqrt(3) * (q[..., 1] - q[..., 2]), 2 * q[..., 0] - q[..., 1] - q[..., 2]))
    rows = {}
    for row in range(a.shape[0]):
        al = a[row, :, 3] > 0.5
        if al.sum() < 4: rows[row] = False; continue
        # the outer quarter of the body on each side (past the 1-texel outline): sides seen from above
        xs = np.flatnonzero(al); q = max(2, len(xs) // 4)
        edge = np.concatenate([a[row, xs[1:1 + q], :3], a[row, xs[-1 - q:-1], :3]])
        dh = np.abs((hue(edge) - hue(pr) + 180) % 360 - 180)
        rows[row] = bool(((dh < 35) & (sat(edge) > 0.12)).mean() > 0.3)
    zrow = ((pos[..., 2] / kz) * 64 + sh / 2) * s4   # model z -> sprite row (x4); nose +z = the sprite's bottom
    ri = np.clip(zrow.astype(int), 0, a.shape[0] - 1)
    body_row = np.vectorize(lambda r: rows.get(int(r), False))(ri)
    m = ok & body_row
    # whole panels, not a mosaic: close the gaps the texel raster and stray highlights leave
    from scipy import ndimage
    m = ndimage.binary_closing(m, iterations=3) & ndimage.binary_dilation(panel, iterations=2) & ~((L > 0.55) & (S < 0.14))
    log(f'  flank paint: {int(m.sum())} texels of the side panels below the belt take the remap ({int(panel.sum())} panel texels, {int(ok.sum())} not trim, body rows {np.mean(list(rows.values())):.2f}, panel z->rows {ri[panel].min() if panel.any() else 0}-{ri[panel].max() if panel.any() else 0} of {a.shape[0]})')
    return m


def smooth_chrome(V, F, UV, img, log, iters=24, lam=0.5, mu=-0.53):
    """the generator's bumpers and grilles come out lumpy ("melted" chrome) and their texture is speckled with
    near-white blobs: Taubin smoothing (volume-keeping) on the bright-metal vertices at the car's ends below the belt,
    welded across the UV seams, and a median clean-up of the chrome texels' luminance outliers"""
    from scipy import ndimage
    H = V[:, 1].max(); zl, zh = V[:, 2].min(), V[:, 2].max(); Lz = zh - zl
    c = tex_at(img, UV)
    pid = weld_key(V)
    n = pid.max() + 1
    P = np.zeros((n, 3)); np.add.at(P, pid, V); cnt = np.bincount(pid, minlength=n)[:, None]; P /= np.maximum(cnt, 1)
    chrome_v = (lum(c) > 0.50) & (sat(c) < 0.14) & (V[:, 1] < 0.55 * H) & ((V[:, 2] < zl + 0.22 * Lz) | (V[:, 2] > zh - 0.22 * Lz))
    sel = np.zeros(n, bool); sel[pid[chrome_v]] = True
    # grow by one ring so the smoothing reaches the lumps' feet (068's wavy grille is the generator's, not this)
    E = np.concatenate([pid[F[:, [0, 1]]], pid[F[:, [1, 2]]], pid[F[:, [2, 0]]]])
    E = np.concatenate([E, E[:, ::-1]])
    grow = np.zeros(n, bool); grow[E[sel[E[:, 0]], 1]] = True; sel |= grow
    deg = np.bincount(E[:, 0], minlength=n)[:, None]
    for it in range(iters):
        for f in (lam, mu):
            nb = np.zeros((n, 3)); np.add.at(nb, E[:, 0], P[E[:, 1]])
            L = nb / np.maximum(deg, 1) - P
            P[sel] += f * L[sel]
    V[:] = P[pid]
    # texture: chrome texels whose luminance stands out of their neighbourhood's median take the median
    L = lum(img); S = sat(img)
    m = (L > 0.45) & (S < 0.14)
    # only the bumpers' and grilles' texels (the ends below the belt, as the vertices above): white paint elsewhere
    # (012's doors, 027) keeps its detail
    import texmap
    pos, _, valid = texmap.texel_maps(V, F, UV, img.shape[0])
    if pos.shape[:2] == m.shape:
        m &= valid & (pos[..., 1] < 0.55 * H) & ((pos[..., 2] < zl + 0.22 * Lz) | (pos[..., 2] > zh - 0.22 * Lz))
    med = ndimage.median_filter(np.where(m, L, np.nan_to_num(L)), size=7)
    # near-white blobs on a chrome surface only (a grille's bright bars over dark gaps have a dark median: kept)
    spk = m & (L - med > 0.16) & (med > 0.50)
    img[spk] = img[spk] * (med[spk] / np.maximum(L[spk], 1e-3))[:, None]
    # then the chrome's blotches (baked reflections read as snow patches in game, 000/012): its luminance is the
    # chrome-only gaussian average (sigma 2.5 texels) blended 3:1 over its own, colour kept
    L = lum(img); mm = m.astype(np.float64)
    avg = ndimage.gaussian_filter(L * mm, 2.5) / np.maximum(ndimage.gaussian_filter(mm, 2.5), 1e-3)
    Ln = np.where(m, 0.75 * avg + 0.25 * L, L)
    img[m] = np.clip(img[m] * (Ln[m] / np.maximum(L[m], 1e-3))[:, None], 0, 1)
    log(f'  chrome: {int(sel.sum())} vertices smoothed, {int(spk.sum())} speckle texels cleaned')


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


def lightbar(kc, V, F, UV, img, spec, sty, spr, sw, sh, kx, kz, log, paint_img=None):
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
    # the pressed faces' texels painted the clean roof's colour (the ring's median texel), so no trace of the
    # generated domes' dark base shows round the new ones
    pim = img if paint_img is None else paint_img
    roof_rgb = np.median(tex_at(pim, UV[rv]), 0)
    pf = np.isin(F, pv).any(1)
    H_, W_ = pim.shape[:2]
    mimg = Image.new('L', (W_, H_), 0); dr_ = ImageDraw.Draw(mimg)
    for tri in UV[F[pf]]:
        dr_.polygon([(float(u % 1.0) * W_, (1.0 - float(v % 1.0)) * H_) for u, v in tri], fill=255)
    mm = np.asarray(mimg.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1.5))).astype(np.float64)[..., None] / 255.0
    pim[...] = pim * (1 - mm) + roof_rgb[None, None, :] * mm
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


def roof_gun(kc, shell, spec, log):
    """the armed Land Roamer's roof machine gun (022): the game draws it as a sprite of its own with its own heading,
    which the renderer turns the model's turret by (TurretSplitFor cuts it off above the roof). A pedestal ring on
    the roof, a receiver with an ammunition box and a barrel with a cooling jacket, its muzzle toward the nose (+z).
    spec: {"z": fraction of the length from the tail to the pivot (default: the middle of the highest roof),
    "scale": 1.0}. Gunmetal, untinted (not paint)."""
    lo, hi = shell.bounds; Lz = hi[2] - lo[2]
    zs = np.linspace(lo[2] + 0.1 * Lz, hi[2] - 0.1 * Lz, 41); ys = []
    for z in zs:
        loc = ray_hits(shell, np.array([0.0, 5.0, z]), np.array([0, -1.0, 0]))
        ys.append(loc[:, 1].max() if len(loc) else -1.0)
    ys = np.array(ys)
    if 'z' in spec:
        zc = lo[2] + float(spec['z']) * Lz
    else:
        top = zs[ys > ys.max() - 0.012]; zc = float(0.5 * (top.min() + top.max()))
    yr = float(np.interp(zc, zs, ys)); k = float(spec.get('scale', 1.0))
    c = np.array([0.0, yr, zc])
    # pedestal: a short ring standing on the roof, then a post
    kc.revolve([(0.050 * k, -0.004), (0.050 * k, 0.012 * k), (0.040 * k, 0.016 * k), (0.016 * k, 0.016 * k),
                (0.014 * k, 0.040 * k), (0.0, 0.040 * k)], tuple(c), (0, 1, 0), 20, default='gun', uv_mode='disc')
    y0 = yr + 0.040 * k
    kc.box('gun', (-0.018 * k, y0, zc - 0.045 * k), (0.018 * k, y0 + 0.034 * k, zc + 0.040 * k))          # receiver
    kc.box('gun_ammo', (0.018 * k, y0 - 0.004 * k, zc - 0.022 * k), (0.046 * k, y0 + 0.026 * k, zc + 0.016 * k))  # ammo box
    kc.box('gun', (-0.006 * k, y0 + 0.034 * k, zc - 0.030 * k), (0.006 * k, y0 + 0.046 * k, zc - 0.008 * k))  # sight
    yb = y0 + 0.020 * k
    # barrel: cooling jacket then the bare barrel and a muzzle ring, along +z
    kc.revolve([(0.0, 0.0), (0.013 * k, 0.0), (0.013 * k, 0.110 * k), (0.007 * k, 0.112 * k), (0.007 * k, 0.190 * k),
                (0.010 * k, 0.192 * k), (0.010 * k, 0.205 * k), (0.0, 0.205 * k)], (0.0, yb, zc + 0.040 * k), (0, 0, 1), 16,
               default='gun', uv_mode='disc')
    # spade grips at the back
    kc.box('gun', (-0.016 * k, yb - 0.010 * k, zc - 0.062 * k), (-0.010 * k, yb + 0.012 * k, zc - 0.045 * k))
    kc.box('gun', (0.010 * k, yb - 0.010 * k, zc - 0.062 * k), (0.016 * k, yb + 0.012 * k, zc - 0.045 * k))
    kc.materials['gun'] = K.tex_flat((52, 56, 50))
    kc.materials['gun_ammo'] = K.tex_flat((70, 78, 48))
    top = y0 + 0.046 * k
    log(f'  roof gun: pivot z {zc:+.3f} on the roof at y {yr:.3f}, top {top:.3f} (roof/top {yr / top:.3f}; '
        f'the shell top {hi[1]:.3f})')


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
    # the top: the sprite's own sign pixels (x4), image rows along z, the sprite's right on the car's -x
    sp = Image.open(os.path.join(ASRC, 'cars', e['remaps'][0]['file_x4'])).convert('RGB')
    s4 = sp.width / sw
    kc.materials['sign_top'] = sp.crop((int(x0p * s4), int(y0p * s4), int(x1p * s4), int(y1p * s4))).resize((128, 128), Image.LANCZOS)
    ty = topy + 0.0008
    P = np.array([[xhi, ty, zlo], [xlo, ty, zlo], [xlo, ty, zhi], [xhi, ty, zhi]])
    T = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)
    kc.part('sign_top').add(P, np.tile([[0, 1.0, 0]], (4, 1)), T, np.array([[0, 2, 1], [0, 3, 2]]))
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


def tex_lens(kind, size=128):
    """a lamp lens seen face on: a hot core (the bulb behind clear glass), a prism lens of fine cells, a bright reflector
    lip and a dark bezel at the rim; also the emission pattern under Remix (EMISSIVE)"""
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0) * 2 - 1
    r = np.hypot(xx, yy)
    cell = 0.16
    grid = ((np.abs(((xx / cell) % 1.0) - 0.5) > 0.42) | (np.abs(((yy / cell) % 1.0) - 0.5) > 0.42)) & (r > 0.32) & (r < 0.84)
    if kind == 'head':
        core, lens, lip, rim = np.array([255, 246, 222.]), np.array([118, 120, 118.]), np.array([200, 200, 196.]), np.array([34, 34, 38.])
    else:
        core, lens, lip, rim = np.array([255, 80, 60.]), np.array([120, 14, 12.]), np.array([170, 40, 32.]), np.array([30, 8, 8.])
    # the core falls off over the inner third (the bulb's hot spot through clear glass), the prism lens stays well under
    # it, a bright reflector lip and a wide dark bezel close it: the lens reads as glass over a bulb, not a flat disc
    t = np.clip((r - 0.10) / 0.28, 0, 1)[..., None] ** 0.8
    c = core * (1 - t) + lens * t
    c = np.where(grid[..., None], c * 0.78, c)
    c = np.where(((r > 0.80) & (r < 0.86))[..., None], lip, c)
    c = np.where((r >= 0.86)[..., None], rim, c)
    c += np.exp(-(((xx + 0.35) ** 2 + (yy + 0.40) ** 2) / 0.010))[..., None] * 50   # a glint
    return Image.fromarray(np.clip(c, 0, 255).astype(np.uint8))


def set_materials(kc, wheels, paint_rgb, livery):
    kc.materials['lamp_head'] = tex_lens('head')
    kc.materials['lamp_tail'] = tex_lens('tail')
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
    if getattr(kc, 'paint_force', None) is not None:
        Image.fromarray((kc.paint_force * 255).astype(np.uint8)).save(os.path.join(out_src, name, 'paint_force.png'))
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


# Remix emission (tools/remix_model_pbr.py): factor, strength. The strength is the gain and the texture's own pattern is
# the emission, so a lens shows a hot core, a dimmer prism lens and a dark rim (defect prxr1: flat white discs), at a
# gain near 1 (the night exposure; [devtools] remix_day_emissive_percent dims every emitter by day).
EMISSIVE = {'sign': ([1.0, 0.88, 0.62], 1.2), 'lamp_head': ([1.0, 0.94, 0.82], 0.35), 'lamp_tail': ([1.0, 0.30, 0.22], 0.8)}


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
        if mt.get('name') in EMISSIVE:
            f, st = EMISSIVE[mt['name']]
            mt['emissiveFactor'] = f
            mt.setdefault('extensions', {})['KHR_materials_emissive_strength'] = {'emissiveStrength': st}
            js.setdefault('extensionsUsed', [])
            if 'KHR_materials_emissive_strength' not in js['extensionsUsed']: js['extensionsUsed'].append('KHR_materials_emissive_strength')
    j = json.dumps(js).encode()
    while len(j) % 4: j += b' '
    out = b'glTF' + struct.pack('<II', 2, 12 + 8 + len(j) + len(rest)) + struct.pack('<I', len(j)) + b'JSON' + j + rest
    open(path, 'wb').write(out)
    return mats


def apply_paint_force(models_dir, name, mask_png, log, level=None):
    """the flank texels (flank_paint_mask) moved into the paint half, neutral: their fine detail over the paint
    half's own level, so the remap colours them as the rest of the body"""
    if not os.path.exists(mask_png): return
    from car_paint_resplit import write_tga as wt
    from scipy import ndimage
    pp = os.path.join(models_dir, name + '_0_paint.tga'); rp = os.path.join(models_dir, name + '_0.tga')
    P = np.asarray(Image.open(pp).convert('RGBA')).astype(np.float32); R = np.asarray(Image.open(rp).convert('RGBA')).astype(np.float32)
    m = np.asarray(Image.open(mask_png).resize((P.shape[1], P.shape[0]), Image.NEAREST)) > 127
    m &= P[..., 3] < 128            # not already paint
    if not m.any(): return
    pm = P[..., 3] >= 128
    lev = level or float(np.median(P[pm][:, 0])) if pm.any() else 180.0
    Lr = R[..., :3].mean(-1)
    low = ndimage.gaussian_filter(np.where(m, Lr, 0), 4) / np.maximum(ndimage.gaussian_filter(m.astype(np.float32), 4), 1e-3)
    detail = np.clip(Lr / np.maximum(low, 4.0), 0.6, 1.4)
    g = np.clip(lev * detail, 0, 255)
    for k in range(3): P[..., k] = np.where(m, g, P[..., k])
    P[..., 3] = np.where(m, 255, P[..., 3]); R[..., 3] = np.where(m, 0, R[..., 3])
    wt(P, pp); wt(R, rp)
    log(f'  flank paint: {int(m.sum())} texels moved into {name}_0_paint.tga at level {lev:.0f}')


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
    # the paint: every texel of the body's hue family (a generated body is often two-tone: 000's dark maroon flanks
    # under a cream roof; the game's remap recolours the whole body), neutralised, its broad shading half flattened
    for e in entries:
        if not e.get('paint_split'): continue
        extra = specs[e['name'][:3]].get('resplit', ['--hue-tol', '42', '--min-sat', '0.12', '--flatten', '0.5'])
        subprocess.check_call([py, os.path.join(TOOLS, 'car_paint_resplit.py'), models_dir, '--only', e['name'][:3]] + list(extra))
        apply_paint_force(models_dir, e['name'], os.path.join(out_src, e['name'], 'paint_force.png'), log)
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
