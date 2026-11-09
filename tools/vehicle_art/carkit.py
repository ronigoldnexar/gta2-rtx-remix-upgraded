#!/usr/bin/env python3
"""carkit: authored, multi-material 3D vehicles for the street views (VEHICLE-ART-1).

The image-to-3D cars (SDXL + TRELLIS, docs/car-3d-pipeline.md) top out at a lumpy
5 000-face hull with one soft 512 px bake: melted lamps, smeared grilles, no glass,
no tread. A car built here is modelled part by part instead:

- panels are lofts of superellipse sections (`section`, `loft`), so a bonnet or a
  roof is one smooth surface with real normals and tight, slightly rounded edges;
- wheels, lamps, stacks and tanks are surfaces of revolution (`revolve`); rails,
  arms and pipes are tubes along a path (`tube`); small blocks are rounded boxes;
- every part names a material (paint, chrome, rubber, glass, lamp lenses, ...).

Texturing is world-space: each draw group (paint / rest / glass) is unwrapped with
xatlas and rasterised in UV space (nvdiffrast), every texel learns its 3D position,
normal and part, and the part's shader paints it there (tread, grille bars, panel
seams are functions of position, not of a UV layout). Ambient occlusion is ray cast
per texel against the whole car (open3d), so arches, seams and the underside darken
the way they would under a sky. Chrome and glass get a baked sky/ground reflection
(the plain renderer is fixed-function diffuse: without it chrome reads as grey
plastic); the paint gets only AO, the game lights it.

Output: a .glb in block units (x across, y up, nose +z, wheels on y = 0, footprint
centred), materials named for tools/import_assets.py ("paint" -> the `_paint`
texture the renderer tints with the car's live colour) and for
tools/remix_model_pbr.py (a metallic/roughness texture per texel, "glass" and lamp
names), plus a .json report. No game art is embedded.

Units while modelling: metres at METRES_PER_BLOCK = 3.8 (an adult is 0.46 block, see
dll/src/live_geometry.cpp kPedHeight), uniform, so wheels stay round.
"""
import json, math, os, struct, io
import numpy as np
from PIL import Image

METRES_PER_BLOCK = 3.8
# The paint texture is neutral light grey: the renderer multiplies it by the car's live
# sprite paint / paint_rgb (identity.cpp DeriveVehicle), and paint_rgb is 235 for every car
# model (model_store.cpp reads it from the import report, which has none) - write 235 in the
# manifest too, so the colour is the sprite's whether or not that lookup is ever fixed.
PAINT_NEUTRAL = (235, 235, 235)

# ---------------------------------------------------------------- geometry ----

class Part:
    """One piece of the car: vertices, triangles, smooth normals, a material."""
    def __init__(self, name, mat, V, F, N=None, tag=None):
        self.name, self.mat = name, mat
        self.V = np.asarray(V, np.float64)
        self.F = np.asarray(F, np.int64).reshape(-1, 3)
        self.N = face_normals_avg(self.V, self.F) if N is None else np.asarray(N, np.float64)
        self.tag = tag or {}

    def mirrored_x(self, name=None):
        V = self.V * [-1, 1, 1]
        N = self.N * [-1, 1, 1]
        return Part(name or self.name + "_m", self.mat, V, self.F[:, ::-1].copy(), N, dict(self.tag))

    def moved(self, d):
        return Part(self.name, self.mat, self.V + np.asarray(d, float), self.F, self.N, dict(self.tag))


def face_normals_avg(V, F):
    N = np.zeros_like(V)
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    n = np.linalg.norm(N, axis=1, keepdims=True)
    return N / np.maximum(n, 1e-12)


def grid_faces(S, R, closed=True, offset=0):
    """Quads between S rings of R points (ring-major), two triangles each, CCW seen from
    outside for rings that run counter-clockwise looking down +s."""
    F = []
    for s in range(S - 1):
        for r in range(R if closed else R - 1):
            a = offset + s * R + r
            b = offset + s * R + (r + 1) % R
            c = offset + (s + 1) * R + (r + 1) % R
            d = offset + (s + 1) * R + r
            F.append((a, c, b)); F.append((a, d, c))
    return np.array(F, np.int64)


def loft(name, mat, rings, cap0=False, cap1=False, closed=True, flip=False, tag=None):
    """rings: (S, R, 3). Smooth normals over the sheet; caps are flat fans with their own
    vertices (a hard edge where they meet the sheet)."""
    rings = np.asarray(rings, np.float64)
    S, R, _ = rings.shape
    V = rings.reshape(-1, 3)
    F = grid_faces(S, R, closed)
    # orientation: normals should point away from the ring centroid
    N = face_normals_avg(V, F)
    cen = rings.mean(axis=1, keepdims=True).repeat(R, 1).reshape(-1, 3)
    if np.mean(np.sum(N * (V - cen), axis=1)) < 0:
        F = F[:, ::-1]; N = -N
    if flip:
        F = F[:, ::-1]; N = -N
    parts_V, parts_F, parts_N = [V], [F], [N]
    base = len(V)
    for which, do in ((0, cap0), (S - 1, cap1)):
        if not do: continue
        ring = rings[which]
        c = ring.mean(axis=0)
        nrm = np.cross(ring[1] - ring[0], ring[R // 4] - ring[0]) if R > 4 else np.array([0, 0, 1.0])
        # outward: away from the neighbouring ring
        other = rings[1 if which == 0 else S - 2].mean(axis=0)
        nrm = nrm / max(np.linalg.norm(nrm), 1e-12)
        if np.dot(nrm, c - other) < 0: nrm = -nrm
        cv = np.vstack([ring, c[None]])
        cf = []
        for r in range(R):
            cf.append((base + r, base + (r + 1) % R, base + R))
        cf = np.array(cf)
        # wind so the triangle normal agrees with nrm
        t = cv[cf[0] - base]
        if np.dot(np.cross(t[1] - t[0], t[2] - t[0]), nrm) < 0: cf = cf[:, ::-1]
        parts_V.append(cv); parts_F.append(cf); parts_N.append(np.repeat(nrm[None], R + 1, 0))
        base += R + 1
    return Part(name, mat, np.vstack(parts_V), np.vstack(parts_F), np.vstack(parts_N), tag)


def sexp(t, n):
    return np.sign(t) * np.abs(t) ** (2.0 / n)


def section(R, yb, yt, wb, wt, n=4.0, x0=0.0, nb=None, crown=0.0, flat_bottom=False, start=-0.5 * math.pi):
    """A closed cross-section in the x-y plane: a superellipse from y = yb to yt whose
    half-width runs from wb (bottom) to wt (top) (tumblehome), squareness n (2 = ellipse,
    higher = boxier); nb: another squareness for the lower half; crown lifts the middle
    of the top by that much (a domed roof). Points run counter-clockwise seen from +z."""
    th = start + np.linspace(0, 2 * math.pi, R, endpoint=False)
    c, s = np.cos(th), np.sin(th)
    nn = np.where(s >= 0, n, nb if nb else n)
    u = np.sign(c) * np.abs(c) ** (2.0 / nn)
    v = np.sign(s) * np.abs(s) ** (2.0 / nn)
    if flat_bottom:
        v = np.where(s < 0, np.maximum(v, -1.0), v)
    f = (v + 1) * 0.5
    hw = wb + (wt - wb) * f
    x = x0 + u * hw
    y = yb + f * (yt - yb) + crown * np.clip(v, 0, 1) * (1 - u ** 2)
    return np.stack([x, y], axis=1)


def smooth_keys(keys, zs):
    """keys: list of (z, value or tuple). Monotone cubic (Fritsch-Carlson) per component at zs."""
    kz = np.array([k[0] for k in keys], float)
    kv = np.array([np.atleast_1d(k[1]) for k in keys], float)
    out = np.zeros((len(zs), kv.shape[1]))
    for j in range(kv.shape[1]):
        y = kv[:, j]
        h = np.diff(kz); d = np.diff(y) / h
        m = np.zeros_like(y)
        m[0], m[-1] = d[0], d[-1]
        for i in range(1, len(y) - 1):
            m[i] = 0 if d[i - 1] * d[i] <= 0 else 2.0 / (1.0 / d[i - 1] + 1.0 / d[i]) if (d[i - 1] != 0 and d[i] != 0) else 0
        for i, z in enumerate(zs):
            k = int(np.clip(np.searchsorted(kz, z) - 1, 0, len(kz) - 2))
            t = (z - kz[k]) / h[k]
            t = min(max(t, 0.0), 1.0)
            h00 = 2 * t ** 3 - 3 * t ** 2 + 1; h10 = t ** 3 - 2 * t ** 2 + t
            h01 = -2 * t ** 3 + 3 * t ** 2; h11 = t ** 3 - t ** 2
            out[i, j] = h00 * y[k] + h10 * h[k] * m[k] + h01 * y[k + 1] + h11 * h[k] * m[k + 1]
    return out


def body_loft(name, mat, keys, R=48, S=40, cap0=True, cap1=True, zs=None, round_ends=0.0, tag=None, axis="z", nb=None):
    """A panel lofted along z. keys: [(z, (yb, yt, wb, wt, n, crown, x0)) ...]. round_ends:
    a length over which the section closes in at both ends (a rounded nose/tail)."""
    z0, z1 = keys[0][0], keys[-1][0]
    if zs is None:
        t = np.linspace(0, 1, S)
        t = 0.5 - 0.5 * np.cos(np.pi * t)       # denser at the ends
        zs = z0 + (z1 - z0) * t
    P = smooth_keys(keys, zs)
    rings = []
    for z, p in zip(zs, P):
        yb, yt, wb, wt, n, crown, x0 = p
        sec = section(R, yb, yt, max(wb, 1e-4), max(wt, 1e-4), max(n, 2.0), x0=x0, crown=crown, nb=nb)
        rings.append(np.column_stack([sec[:, 0], sec[:, 1], np.full(R, z)]))
    rings = np.array(rings)
    if round_ends > 0:
        # pull the end rings toward their centres on a quarter circle
        for which, sgn in ((0, 1), (len(zs) - 1, -1)):
            pass
    return loft(name, mat, rings, cap0, cap1, tag=tag)


def revolve(name, mat, profile, center, axis, R=32, cap0=False, cap1=False, tag=None, phase=0.0):
    """profile: [(r, t)] along the axis (t from the centre point); a surface of revolution."""
    axis = np.asarray(axis, float); axis /= np.linalg.norm(axis)
    a = np.array([0, 1.0, 0]) if abs(axis[1]) < 0.9 else np.array([1.0, 0, 0])
    e1 = np.cross(axis, a); e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    th = phase + np.linspace(0, 2 * math.pi, R, endpoint=False)
    rings = []
    for r, t in profile:
        ring = np.asarray(center) + axis * t + r * (np.cos(th)[:, None] * e1 + np.sin(th)[:, None] * e2)
        rings.append(ring)
    return loft(name, mat, np.array(rings), cap0, cap1, tag=tag)


def tube(name, mat, path, radius, R=12, cap0=True, cap1=True, tag=None):
    """A round tube along a polyline (parallel-transported frames)."""
    P = np.asarray(path, float)
    rad = np.broadcast_to(np.asarray(radius, float), (len(P),))
    T = np.gradient(P, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
    a = np.array([0, 1.0, 0]) if abs(T[0][1]) < 0.9 else np.array([1.0, 0, 0])
    n = np.cross(T[0], a); n /= np.linalg.norm(n)
    rings = []
    th = np.linspace(0, 2 * math.pi, R, endpoint=False)
    for i in range(len(P)):
        if i > 0:
            n = n - T[i] * np.dot(n, T[i]); n /= np.linalg.norm(n)
        b = np.cross(T[i], n)
        rings.append(P[i] + rad[i] * (np.cos(th)[:, None] * n + np.sin(th)[:, None] * b))
    return loft(name, mat, np.array(rings), cap0, cap1, tag=tag)


def rbox(name, mat, lo, hi, r=0.02, R=24, n=8.0, tag=None, axis="z"):
    """A box from lo to hi with rounded edges (radius r), lofted along the given axis."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    ax = "xyz".index(axis)
    oth = [i for i in range(3) if i != ax]
    rings = []
    steps = [0.0, 0.38, 0.71, 0.92, 1.0]
    zs = []
    for s in steps: zs.append((lo[ax] + r * (1 - math.cos(s * math.pi / 2)), math.sin(s * math.pi / 2)))
    zs = zs + [(hi[ax] - r * (1 - math.cos(s * math.pi / 2)), math.sin(s * math.pi / 2)) for s in steps[::-1]]
    for z, k in zs:
        sh = r * (1 - k)
        a0 = 0.5 * (hi[oth[0]] - lo[oth[0]]) - sh
        a1 = 0.5 * (hi[oth[1]] - lo[oth[1]]) - sh
        c0 = 0.5 * (hi[oth[0]] + lo[oth[0]]); c1 = 0.5 * (hi[oth[1]] + lo[oth[1]])
        # superellipse whose squareness gives roughly an r corner
        m = max(min(a0, a1), 1e-4)
        ne = max(2.0, min(n * m / max(r, 1e-4) * 0.5, 40.0))
        th = np.linspace(0, 2 * math.pi, R, endpoint=False)
        u = sexp(np.cos(th), ne) * max(a0, 1e-4) + c0
        v = sexp(np.sin(th), ne) * max(a1, 1e-4) + c1
        ring = np.zeros((R, 3)); ring[:, ax] = z; ring[:, oth[0]] = u; ring[:, oth[1]] = v
        rings.append(ring)
    return loft(name, mat, np.array(rings), True, True, tag=tag)


def wheel(prefix, center, side, radius, width, rim_r, mats, R=40, dual=False, gap=0.02, hub="truck", tag=None, hub_out=0.10):
    """A tyre (rounded, with sidewall bulge and shoulder) and a rim/hub facing outward
    (side = +1 for the right, -1 for the left: the axis points out of the car)."""
    parts = []
    ax = np.array([side, 0, 0], float)
    w = width
    # tyre profile (r, t) from the inner sidewall round the tread to the outer sidewall
    ri = rim_r * 1.02
    prof = []
    for k in range(9):      # inner sidewall
        t = -w / 2 + (k / 8) ** 1.5 * 0.0
    sw = [(ri, -w * 0.42), (ri + 0.5 * (radius - ri), -w * 0.5),
          (radius - 0.03, -w * 0.47), (radius - 0.006, -w * 0.42), (radius, -w * 0.30),
          (radius, w * 0.30), (radius - 0.006, w * 0.42), (radius - 0.03, w * 0.47),
          (ri + 0.5 * (radius - ri), w * 0.5), (ri, w * 0.42)]
    tyre = revolve(prefix + "_tyre", mats["tyre"], sw, center, ax, R=R, tag=dict(tag or {}, center=list(center), axis=list(ax),
                                                                                    radius=radius, width=w, kind="tyre"))
    parts.append(tyre)
    # rim: a dished wheel seen from outside, the face at +w*0.42
    face = w * 0.40
    if hub == "truck":
        k = hub_out / 0.10
        rp = [(ri * 0.98, w * 0.30), (ri * 0.98, face), (ri * 0.88, face - 0.015),
              (ri * 0.50, face - 0.03), (ri * 0.42, face + 0.03 * k), (ri * 0.33, face + 0.075 * k),
              (ri * 0.16, face + 0.10 * k), (0.0001, face + 0.10 * k)]
    elif hub == "cap":       # car: painted steel wheel with a chrome dome hubcap
        rp = [(ri * 0.98, w * 0.30), (ri * 0.98, face), (ri * 0.92, face + 0.006), (ri * 0.86, face - 0.012),
              (ri * 0.78, face - 0.012), (ri * 0.72, face + 0.004), (ri * 0.66, face + 0.02), (ri * 0.55, face + 0.04),
              (ri * 0.38, face + 0.055), (ri * 0.18, face + 0.062), (0.0001, face + 0.064)]
    else:
        rp = [(ri * 0.98, w * 0.30), (ri * 0.98, face), (ri * 0.5, face - 0.02), (0.0001, face)]
    rim = revolve(prefix + "_rim", mats["rim"], rp, center, ax, R=R, tag=dict(tag or {}, center=list(center), axis=list(ax),
                                                                                   radius=ri, kind="rim", face=face, hub=hub))
    parts.append(rim)
    # the inner face: a dark disc so the wheel is closed seen from below
    inner = revolve(prefix + "_back", mats["under"], [(0.0001, -w * 0.40), (ri * 0.98, -w * 0.40)],
                    center, ax, R=max(10, R // 2))
    parts.append(inner)
    return parts


# ---------------------------------------------------------------- materials ---

class Mat:
    """A material: which draw group it lands in, PBR factors, and a shader that paints
    texels (pos, nrm, part tags) -> rgb in 0..1."""
    def __init__(self, name, group, rgb, rough=0.5, metal=0.0, emit=None, shader=None, ao=0.85, env=0.0, glbname=None):
        self.name, self.group = name, group
        self.rgb = np.asarray(rgb, float) / (255.0 if max(rgb) > 1.0 else 1.0)
        self.rough, self.metal, self.emit = rough, metal, emit
        self.shader = shader
        self.ao = ao          # how much the baked occlusion darkens it (0..1)
        self.env = env        # baked sky reflection strength (chrome, glass)
        self.glbname = glbname or name


def sky_env(nrm, view_up=-0.12):
    """What a shiny surface with normal nrm reflects for a viewer roughly level with the car,
    looking at it along the normal's horizontal direction from a little above: the reflected
    ray's height picks pale sky (up), a band of street and buildings at the horizon, and the
    dark road below; the transition at the horizon is sharp, as chrome shows it."""
    n = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    h = n * [1, 0, 1]
    hl = np.linalg.norm(h, axis=1, keepdims=True)
    h = np.where(hl > 0.05, h / np.maximum(hl, 1e-9), np.array([[0, 0, 1.0]]))
    v = h + np.array([[0, view_up, 0]]); v /= np.linalg.norm(v, axis=1, keepdims=True)
    r = 2 * np.sum(n * v, 1, keepdims=True) * n - v
    ry = r[:, 1:2]
    zen = np.array([0.50, 0.66, 0.92]); hor = np.array([0.93, 0.95, 0.97]); bld = np.array([0.42, 0.40, 0.38])
    road = np.array([0.10, 0.10, 0.10]); near = np.array([0.20, 0.19, 0.18])
    up = np.clip(ry, 0, 1)
    sky = hor + (zen - hor) * np.clip((up - 0.12) / 0.6, 0, 1)
    sky = np.where(ry < 0.10, bld + (hor - bld) * np.clip(ry / 0.10, 0, 1) ** 0.5, sky)
    dn = np.clip(-ry, 0, 1)
    gnd = road + (near - road) * np.clip(dn * 1.5, 0, 1)
    t = np.clip((ry + 0.015) / 0.03, 0, 1)
    return gnd * (1 - t) + sky * t


# ---------------------------------------------------------------- baking ------

def _rasterise_uv(uv, F, res, device):
    import torch, nvdiffrast.torch as dr
    glctx = dr.RasterizeCudaContext(device=device)
    pos = torch.tensor(np.column_stack([uv * 2 - 1, np.zeros(len(uv)), np.ones(len(uv))]), dtype=torch.float32, device=device)[None]
    tri = torch.tensor(F, dtype=torch.int32, device=device)
    rast, _ = dr.rasterize(glctx, pos, tri, resolution=[res, res])
    return rast[0].cpu().numpy()     # (res, res, 4): u, v, z, triangle id + 1


def bake_group(parts, res, all_parts, ao_rays=96, ao_dist=0.55, seed=1, device="cuda"):
    """Unwrap the parts of one draw group into one atlas and paint it.
    Returns (V, N, UV, F, face_part_index, rgb image, mr image (G rough, B metal), emissive mask)."""
    import xatlas
    V = np.vstack([p.V for p in parts]); N = np.vstack([p.N for p in parts])
    F = []; off = 0; fpart = []
    for i, p in enumerate(parts):
        F.append(p.F + off); off += len(p.V); fpart.append(np.full(len(p.F), i))
    F = np.vstack(F); fpart = np.concatenate(fpart)
    atlas = xatlas.Atlas()
    atlas.add_mesh(V.astype(np.float32), F.astype(np.uint32), N.astype(np.float32))
    po = xatlas.PackOptions(); po.resolution = res; po.padding = 4; po.bilinear = True; po.bruteForce = False
    co = xatlas.ChartOptions(); co.max_iterations = 2
    atlas.generate(co, po)
    vmap, Fi, UV = atlas[0]
    V2, N2 = V[vmap], N[vmap]
    Fi = Fi.astype(np.int64)
    # rasterise in UV space
    rast = _rasterise_uv(UV, Fi, res, device)
    tid = rast[..., 3].astype(np.int64) - 1
    cov = tid >= 0
    # nvdiffrast: the point is u * v0 + v * v1 + (1 - u - v) * v2
    b0, b1 = rast[..., 0], rast[..., 1]
    b2 = 1 - b0 - b1
    t = np.where(cov, tid, 0)
    tri = Fi[t]
    P = V2[tri[..., 0]] * b0[..., None] + V2[tri[..., 1]] * b1[..., None] + V2[tri[..., 2]] * b2[..., None]
    Nn = N2[tri[..., 0]] * b0[..., None] + N2[tri[..., 1]] * b1[..., None] + N2[tri[..., 2]] * b2[..., None]
    Nn /= np.maximum(np.linalg.norm(Nn, axis=-1, keepdims=True), 1e-9)
    pidx = np.where(cov, fpart[t], -1)
    # occlusion against the whole car
    ao = np.ones((res, res))
    idx = np.nonzero(cov)
    if ao_rays > 0:
        ao[idx] = ambient_occlusion(P[idx], Nn[idx], all_parts, ao_rays, ao_dist, seed)
        ao = masked_blur(ao, cov, 3)
    rgb = np.zeros((res, res, 3)); mr = np.zeros((res, res, 3)); em = np.zeros((res, res))
    for i, p in enumerate(parts):
        m = pidx == i
        if not m.any(): continue
        mat = p.mat
        pos, nrm = P[m], Nn[m]
        col = np.repeat(mat.rgb[None], len(pos), 0)
        rough = np.full(len(pos), mat.rough); metal = np.full(len(pos), mat.metal)
        if mat.shader is not None:
            out = mat.shader(pos, nrm, p, col.copy())
            if isinstance(out, tuple):
                col = out[0]
                if len(out) > 1 and out[1] is not None: rough = out[1]
                if len(out) > 2 and out[2] is not None: metal = out[2]
            else:
                col = out
        if mat.env > 0:
            col = col * (1 - mat.env) + sky_env(nrm) * (col / max(col.mean(), 1e-3)).clip(0, 1.4) * mat.env
        a = ao[m]
        col = col * (1 - mat.ao * (1 - a))[:, None]
        rgb[m] = col
        mr[m, 1] = rough; mr[m, 2] = metal
        if mat.emit is not None: em[m] = 1.0
    rgb, mr, em = dilate([rgb, mr, em[..., None]], cov, 10)
    return dict(V=V2, N=N2, UV=UV, F=Fi, fpart=fpart, rgb=rgb, mr=mr, em=em[..., 0], cov=cov)


_SCENE_CACHE = {}

def ambient_occlusion(P, Nn, all_parts, rays, dist, seed):
    import open3d as o3d
    key = id(all_parts)
    if key not in _SCENE_CACHE:
        Vs = np.vstack([p.V for p in all_parts]).astype(np.float32)
        Fs = []; off = 0
        for p in all_parts:
            Fs.append(p.F + off); off += len(p.V)
        Fs = np.vstack(Fs).astype(np.uint32)
        sc = o3d.t.geometry.RaycastingScene()
        sc.add_triangles(o3d.core.Tensor(Vs), o3d.core.Tensor(Fs))
        _SCENE_CACHE.clear(); _SCENE_CACHE[key] = sc
    sc = _SCENE_CACHE[key]
    rng = np.random.default_rng(seed)
    n = len(P)
    occ = np.zeros(n)
    # cosine-weighted hemisphere, tangent frames per texel
    a = np.where(np.abs(Nn[:, 1:2]) < 0.9, np.array([[0, 1, 0]]), np.array([[1, 0, 0]]))
    T = np.cross(Nn, a); T /= np.linalg.norm(T, axis=1, keepdims=True)
    B = np.cross(Nn, T)
    chunk = 400000 // max(1, rays) * 1
    for s in range(0, n, chunk):
        e = min(n, s + chunk)
        k = e - s
        u1 = rng.random((k, rays)); u2 = rng.random((k, rays))
        r = np.sqrt(u1); phi = 2 * math.pi * u2
        x = r * np.cos(phi); y = r * np.sin(phi); z = np.sqrt(1 - u1)
        D = (x[..., None] * T[s:e, None] + y[..., None] * B[s:e, None] + z[..., None] * Nn[s:e, None])
        O = np.repeat((P[s:e] + Nn[s:e] * 0.003)[:, None], rays, 1)
        rr = np.concatenate([O, D], axis=-1).reshape(-1, 6).astype(np.float32)
        hit = sc.cast_rays(o3d.core.Tensor(rr))["t_hit"].numpy().reshape(k, rays)
        w = np.clip(1 - hit / dist, 0, 1)                         # near hits occlude more
        w = np.where(np.isfinite(hit), w ** 0.5, 0)
        # rays heading for the ground below the car (y < 0) are occluded by the road
        ground = (D[..., 1] < 0) & ((-(P[s:e, None, 1] + 0.003) / np.minimum(D[..., 1], -1e-6)) < dist)
        w = np.maximum(w, ground * 0.5)
        occ[s:e] = w.mean(axis=1)
    return np.clip(1 - occ * 1.25, 0, 1)


def masked_blur(a, mask, r):
    """A small box blur over covered texels only (normalised), to take the noise out of the AO."""
    acc = np.zeros_like(a); w = np.zeros_like(a)
    m = mask.astype(float)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            acc += np.roll(np.roll(a * m, dy, 0), dx, 1); w += np.roll(np.roll(m, dy, 0), dx, 1)
    return np.where(mask, acc / np.maximum(w, 1e-9), a)


def dilate(imgs, mask, it):
    """Spread covered texels into the gutter so bilinear filtering and mips never pull in black."""
    m = mask.copy()
    out = [i.copy() for i in imgs]
    for _ in range(it):
        nb = np.zeros_like(m, dtype=np.float64); acc = [np.zeros_like(o) for o in out]
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            mm = np.roll(np.roll(m, dy, 0), dx, 1)
            nb += mm
            for a, o in zip(acc, out):
                a += np.roll(np.roll(o, dy, 0), dx, 1) * mm[..., None]
        grow = (~m) & (nb > 0)
        for a, o in zip(acc, out):
            o[grow] = a[grow] / nb[grow][:, None]
        m = m | grow
    # whatever is still empty: the mean colour
    for o, i in zip(out, imgs):
        if (~m).any(): o[~m] = o[m].mean(axis=0)
    return out


# ---------------------------------------------------------------- export ------

def to_png(arr):
    im = Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8))
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()


def write_glb(path, groups, scale):
    """groups: list of dicts {name, mats: [(Mat, face mask)], V, N, UV, F, images...}.
    One glTF mesh, one primitive per material, images shared per group."""
    bin_ = bytearray()
    def add(arr, target=None):
        nonlocal bin_
        while len(bin_) % 4: bin_ += b"\0"
        off = len(bin_); data = arr.tobytes(); bin_ += data
        bv = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target: bv["target"] = target
        g["bufferViews"].append(bv); return len(g["bufferViews"]) - 1
    g = {"asset": {"version": "2.0", "generator": "carkit (gta2dx9 VEHICLE-ART-1)"}, "scene": 0,
         "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "body"}], "meshes": [{"primitives": [], "name": "car"}],
         "materials": [], "textures": [], "images": [], "accessors": [], "bufferViews": [], "buffers": [],
         "samplers": [{"magFilter": 9729, "minFilter": 9987}]}
    def image(png):
        bv = add(np.frombuffer(png, np.uint8))
        g["images"].append({"bufferView": bv, "mimeType": "image/png"})
        g["textures"].append({"sampler": 0, "source": len(g["images"]) - 1})
        return len(g["textures"]) - 1
    for grp in groups:
        tex = image(to_png(grp["rgb"]))
        mrt = image(to_png(grp["mr"]))
        for mat, fmask in grp["mats"]:
            F = grp["F"][fmask]
            if len(F) == 0: continue
            used = np.unique(F); remap = -np.ones(len(grp["V"]), np.int64); remap[used] = np.arange(len(used))
            V = (grp["V"][used] * scale).astype(np.float32); N = grp["N"][used].astype(np.float32); UV = grp["UV"][used].astype(np.float32)
            idx = remap[F].astype(np.uint32).reshape(-1)
            acc_base = len(g["accessors"])
            bv = add(V, 34962); g["accessors"].append({"bufferView": bv, "componentType": 5126, "count": len(V), "type": "VEC3",
                                                       "min": V.min(0).tolist(), "max": V.max(0).tolist()})
            bv = add(N, 34962); g["accessors"].append({"bufferView": bv, "componentType": 5126, "count": len(N), "type": "VEC3"})
            bv = add(UV, 34962); g["accessors"].append({"bufferView": bv, "componentType": 5126, "count": len(UV), "type": "VEC2"})
            bv = add(idx, 34963)
            g["accessors"].append({"bufferView": bv, "componentType": 5125, "count": len(idx), "type": "SCALAR"})
            m = {"name": mat.glbname, "pbrMetallicRoughness": {"baseColorTexture": {"index": tex},
                 "metallicRoughnessTexture": {"index": mrt}, "metallicFactor": 1.0, "roughnessFactor": 1.0}}
            if mat.emit is not None: m["emissiveFactor"] = [float(c) for c in mat.emit]
            g["materials"].append(m)
            g["meshes"][0]["primitives"].append({"attributes": {"POSITION": acc_base, "NORMAL": acc_base + 1, "TEXCOORD_0": acc_base + 2},
                                                 "indices": len(g["accessors"]) - 1, "material": len(g["materials"]) - 1})
    while len(bin_) % 4: bin_ += b"\0"
    g["buffers"].append({"byteLength": len(bin_)})
    js = json.dumps(g, separators=(",", ":")).encode()
    while len(js) % 4: js += b" "
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A)); f.write(js)
        f.write(struct.pack("<II", len(bin_), 0x004E4942)); f.write(bin_)


def build(parts, out_glb, res=None, device="cuda", report=None):
    """Bake every draw group and write the glb (metres -> blocks)."""
    res = res or {"paint": 1024, "rest": 1024, "glass": 256}
    groups = []
    for gname in ("rest", "paint", "glass"):
        gp = [p for p in parts if p.mat.group == gname]
        if not gp: continue
        b = bake_group(gp, res[gname], parts, device=device)
        # one primitive per draw: the lamps (each its own emissive colour), and everything else
        # of the group in one (its metal/roughness is in the texture)
        def key(m): return m.glbname if (m.emit is not None or gname != "rest") else "trim"
        names = []
        for p in gp:
            if key(p.mat) not in names: names.append(key(p.mat))
        mats = []
        for nm in names:
            pi = [i for i, p in enumerate(gp) if key(p.mat) == nm]
            m0 = next(p.mat for p in gp if key(p.mat) == nm)
            if nm == "trim": m0 = Mat("trim", "rest", (0.5, 0.5, 0.5))
            mats.append((m0, np.isin(b["fpart"], pi)))
        b["mats"] = mats; b["name"] = gname
        groups.append(b)
    write_glb(out_glb, groups, 1.0 / METRES_PER_BLOCK)
    V = np.vstack([p.V for p in parts]) / METRES_PER_BLOCK
    rep = {"vertices": int(sum(len(b["V"]) for b in groups)), "faces": int(sum(len(b["F"]) for b in groups)),
           "bounds_blocks": [V.min(0).round(4).tolist(), V.max(0).round(4).tolist()],
           "groups": {b["name"]: {"vertices": len(b["V"]), "faces": len(b["F"])} for b in groups}}
    if report: rep.update(report)
    json.dump(rep, open(out_glb[:-4] + ".json", "w"), indent=1)
    for b in groups:
        Image.fromarray((np.clip(b["rgb"], 0, 1) * 255).astype(np.uint8)).save(out_glb[:-4] + f"_{b['name']}.png")
    return rep, groups


# ---------------------------------------------------------------- more shapes --

def transformed(p, M=None, t=(0, 0, 0), name=None):
    """A copy of part p under the 3x3 matrix M then the translation t."""
    M = np.eye(3) if M is None else np.asarray(M, float)
    V = p.V @ M.T + np.asarray(t, float)
    N = p.N @ np.linalg.inv(M)
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    F = p.F if np.linalg.det(M) > 0 else p.F[:, ::-1].copy()
    return Part(name or p.name, p.mat, V, F, N, dict(p.tag))


def rot(axis, deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    if axis == "x": return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "y": return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


SWAP_ZX = np.array([[0, 0, 1], [0, 1, 0], [1, 0, 0]], float)   # a loft built along z, laid along x


def box(name, mat, lo, hi, tag=None):
    """A sharp box, flat normals (24 vertices)."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    V, N, F = [], [], []
    for ax in range(3):
        for sgn in (-1, 1):
            n = np.zeros(3); n[ax] = sgn
            o = [i for i in range(3) if i != ax]
            q = []
            for a, b in ((0, 0), (1, 0), (1, 1), (0, 1)):
                p = np.zeros(3); p[ax] = hi[ax] if sgn > 0 else lo[ax]
                p[o[0]] = hi[o[0]] if a else lo[o[0]]; p[o[1]] = hi[o[1]] if b else lo[o[1]]
                q.append(p)
            base = len(V); V += q; N += [n] * 4
            f = [(base, base + 1, base + 2), (base, base + 2, base + 3)]
            t = np.array(q)
            if np.dot(np.cross(t[1] - t[0], t[2] - t[0]), n) < 0: f = [ff[::-1] for ff in f]
            F += f
    return Part(name, mat, np.array(V), np.array(F), np.array(N), tag)


def merge(name, mat, parts, tag=None):
    V, N, F = [], [], []; off = 0
    for p in parts:
        V.append(p.V); N.append(p.N); F.append(p.F + off); off += len(p.V)
    return Part(name, mat, np.vstack(V), np.vstack(F), np.vstack(N), tag)


def squircle_grid(nu, nv, n=6.0):
    """A (nv, nu, 2) grid on [-1, 1]^2 mapped into a superellipse disc (rounded rectangle)."""
    s = np.linspace(-1, 1, nu); t = np.linspace(-1, 1, nv)
    S, T = np.meshgrid(s, t)
    rinf = np.maximum(np.abs(S), np.abs(T))
    rn = (np.abs(S) ** n + np.abs(T) ** n) ** (1.0 / n)
    k = np.where(rn > 1e-9, rinf / np.maximum(rn, 1e-9), 1.0)
    return np.stack([S * k, T * k], axis=-1)


def _scene_of(parts):
    import open3d as o3d
    V = np.vstack([p.V for p in parts]).astype(np.float32)
    F = []; off = 0
    for p in parts:
        F.append(p.F + off); off += len(p.V)
    sc = o3d.t.geometry.RaycastingScene()
    sc.add_triangles(o3d.core.Tensor(V), o3d.core.Tensor(np.vstack(F).astype(np.uint32)))
    return sc


def conform(targets, pts, direction, offset=0.004):
    """Project points along `direction` onto the target parts (from 1 m behind); returns the
    hit points pushed `offset` out along the surface normal, and the normals."""
    import open3d as o3d
    sc = _scene_of(targets)
    d = np.asarray(direction, float); d /= np.linalg.norm(d)
    P = np.asarray(pts, float).reshape(-1, 3)
    O = P - d * 1.0
    rays = np.hstack([O, np.repeat(d[None], len(P), 0)]).astype(np.float32)
    r = sc.cast_rays(o3d.core.Tensor(rays))
    t = r["t_hit"].numpy(); n = r["primitive_normals"].numpy().astype(float)
    ok = np.isfinite(t)
    H = O + d * np.where(ok, t, 1.0)[:, None]
    n = np.where((np.sum(n * d, 1) > 0)[:, None], -n, n)
    return H + n * offset, n, ok


def window(name, mat, frame_mat, targets, centre, u, v, half_u, half_v, direction, n=6.0, nu=10, nv=8,
           offset=0.006, frame_r=0.014, frame=True, tag=None, inset=0.0):
    """A pane of glass that follows the body's surface (a conformed rounded rectangle) with a
    rubber/chrome rim around it. centre/u/v: the window's plane in world space; direction:
    the way to project onto the body (into the body)."""
    centre, u, v = (np.asarray(a, float) for a in (centre, u, v))
    g = squircle_grid(nu, nv, n)
    P = centre + g[..., 0:1] * u * half_u + g[..., 1:2] * v * half_v
    H, Nn, ok = conform(targets, P.reshape(-1, 3), direction, offset)
    H = H.reshape(nv, nu, 3); Nn = Nn.reshape(nv, nu, 3)
    if inset:
        H = H - Nn * inset
    V = H.reshape(-1, 3)
    F = grid_faces(nv, nu, closed=False)
    nrm = face_normals_avg(V, F)
    if np.mean(np.sum(nrm * Nn.reshape(-1, 3), 1)) < 0: F = F[:, ::-1]
    parts = [Part(name, mat, V, F, None, tag)]
    if frame:
        # the boundary loop, a little outside the pane
        ring = list(H[0, :]) + list(H[1:, -1]) + list(H[-1, -2::-1]) + list(H[-2:0:-1, 0])
        ringn = list(Nn[0, :]) + list(Nn[1:, -1]) + list(Nn[-1, -2::-1]) + list(Nn[-2:0:-1, 0])
        ring = np.array(ring); ringn = np.array(ringn)
        ring = ring + ringn * (frame_r * 0.2)
        ring = np.vstack([ring, ring[:1]])
        parts.append(tube(name + "_rim", frame_mat, ring, frame_r, R=6, cap0=False, cap1=False))
    return parts


def cut(part, keep_fn):
    """Window holes: drop a face only when keep_fn says False for all three of its vertices,
    so the hole never reaches past the region (the pane over it covers its ragged edge)."""
    kv = keep_fn(part.V)
    k = kv[part.F].any(axis=1)
    F = part.F[k]
    used = np.unique(F)
    remap = -np.ones(len(part.V), np.int64); remap[used] = np.arange(len(used))
    return Part(part.name, part.mat, part.V[used], remap[F], part.N[used], dict(part.tag))


def sweep(name, mat, path, sec_fn, lateral=(1, 0, 0), cap0=True, cap1=True, tag=None):
    """A section swept along a path, the section's first axis held along `lateral` (a fender
    over a wheel: the path an arc in the z-y plane, the section across x). sec_fn(i, t) ->
    (R, 2) points in (lateral, outward normal) coordinates."""
    P = np.asarray(path, float)
    T = np.gradient(P, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
    L = np.asarray(lateral, float); L /= np.linalg.norm(L)
    rings = []
    for i in range(len(P)):
        nrm = np.cross(T[i], L); nrm /= np.linalg.norm(nrm)
        s = sec_fn(i, i / (len(P) - 1))
        rings.append(P[i] + s[:, 0:1] * L + s[:, 1:2] * nrm)
    return loft(name, mat, np.array(rings), cap0, cap1, tag=tag)


# ------------------------------------------------- side-profile extrusion ----

def rounded_profile(spec, step=0.06):
    """A closed 2D outline (z, y), counter-clockwise seen from +x, resampled every `step`.
    spec items: ("p", z, y, r) a corner filleted with radius r; ("arc", cz, cy, R, a0, a1) an arc
    (degrees, a0 -> a1) inserted as is (a wheel arch)."""
    raw = []
    pts = []
    # first expand corners: a corner needs its neighbours, so collect the anchor points
    items = list(spec)
    anchors = []
    for it in items:
        if it[0] == "p": anchors.append(("p", np.array(it[1:3], float), it[3]))
        else:
            cz, cy, R, a0, a1 = it[1:]
            n = max(6, int(abs(math.radians(a1 - a0)) * R / step * 1.5))
            a = np.radians(np.linspace(a0, a1, n))
            anchors.append(("arc", np.stack([cz + R * np.cos(a), cy + R * np.sin(a)], 1), 0))
    def first(a): return a[1] if a[0] == "p" else a[1][0]
    def last(a): return a[1] if a[0] == "p" else a[1][-1]
    out = []
    K = len(anchors)
    for i, a in enumerate(anchors):
        if a[0] == "arc":
            out += list(a[1]); continue
        p, r = a[1], a[2]
        prv = last(anchors[i - 1]); nxt = first(anchors[(i + 1) % K])
        if r <= 0:
            out.append(p); continue
        d1 = p - prv; d1 /= np.linalg.norm(d1); d2 = nxt - p; d2 /= np.linalg.norm(d2)
        cosang = np.clip(np.dot(-d1, d2), -1, 1); ang = math.acos(cosang)
        if ang > math.pi - 1e-3:
            out.append(p); continue
        t = r / math.tan(ang / 2)
        s = p - d1 * t; e = p + d2 * t
        bis = (-d1 + d2); bis /= np.linalg.norm(bis)
        c = p + bis * (r / math.sin(ang / 2))
        a0 = math.atan2(s[1] - c[1], s[0] - c[0]); a1 = math.atan2(e[1] - c[1], e[0] - c[0])
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        n = max(3, int(abs(da) * r / step * 2) + 2)
        for k in range(n):
            aa = a0 + da * k / (n - 1)
            out.append(c + r * np.array([math.cos(aa), math.sin(aa)]))
    P = np.array(out)
    # resample by arc length
    seg = np.linalg.norm(np.diff(np.vstack([P, P[:1]]), axis=0), axis=1)
    keep = seg > 1e-6
    P = P[keep]; seg = seg[keep]
    cum = np.concatenate([[0], np.cumsum(seg)])
    total = cum[-1]
    n = max(16, int(total / step))
    s = np.linspace(0, total, n, endpoint=False)
    Q = np.vstack([P, P[:1]])
    z = np.interp(s, cum, Q[:, 0]); y = np.interp(s, cum, Q[:, 1])
    # keep the sharp anchor corners (r = 0) exactly
    R2 = np.stack([z, y], 1)
    area = 0.5 * np.sum(R2[:, 0] * np.roll(R2[:, 1], -1) - np.roll(R2[:, 0], -1) * R2[:, 1])
    if area < 0: R2 = R2[::-1]
    return R2


def offset2d(P, d):
    """Move a closed CCW outline inward by d along its normals."""
    t = np.roll(P, -1, 0) - np.roll(P, 1, 0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
    n_in = np.stack([-t[:, 1], t[:, 0]], 1)     # left of the direction of travel = inside for CCW
    return P + n_in * d


def _inside(poly, pts):
    x, y = pts[:, 0], pts[:, 1]
    ins = np.zeros(len(pts), bool)
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]; xj, yj = poly[j]
        c = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi)
        ins ^= c; j = i
    return ins


def fill_outline(poly, grid=0.12):
    """Triangulate a closed outline with interior points (Delaunay, outside triangles dropped).
    Returns (points (n,2), faces) where the first len(poly) points are the outline."""
    from scipy.spatial import Delaunay
    lo, hi = poly.min(0), poly.max(0)
    gz, gy = np.meshgrid(np.arange(lo[0] + grid / 2, hi[0], grid), np.arange(lo[1] + grid / 2, hi[1], grid))
    G = np.stack([gz.ravel(), gy.ravel()], 1)
    G = G[_inside(poly, G)]
    if len(G):
        # keep interior points away from the outline
        from scipy.spatial import cKDTree
        dd, _ = cKDTree(poly).query(G)
        G = G[dd > grid * 0.45]
    pts = np.vstack([poly, G])
    tri = Delaunay(pts).simplices
    cen = pts[tri].mean(axis=1)
    tri = tri[_inside(poly, cen)]
    return pts, tri


def extrude_profile(name, mat, prof, half_w, r=0.08, mid=5, zshift=None, xfun=None, grid=0.12, tag=None):
    """A body whose side view is `prof` (CCW (z, y) outline), as wide as 2 * half_w, with its
    long edges rounded by r: rings across x (the rounding steps and `mid` stations across the
    top), the two flat sides filled. zshift(x, z, y) -> dz bends the plan view (a bowed nose);
    xfun(y) -> the half width at a height (tumblehome)."""
    steps = [0.0, 0.30, 0.58, 0.82, 1.0]
    xs = []
    # from the right side (-x) across to the left (+x); each station: (sign, phi or None, u)
    stations = []
    for ph in steps[::-1]: stations.append((-1, ph))
    for u in np.linspace(-1, 1, mid + 2)[1:-1]: stations.append((0, u))
    for ph in steps: stations.append((1, ph))
    rings = []
    hw = (lambda y: np.full_like(y, half_w)) if xfun is None else xfun
    for sgn, v in stations:
        if sgn == 0:
            Q = prof.copy(); k = v
            x = k * (hw(Q[:, 1]) - r)
        else:
            phi = v * math.pi / 2
            d = r * (1 - math.cos(phi))
            Q = offset2d(prof, d)
            x = sgn * (hw(Q[:, 1]) - r + r * math.sin(phi))
        z = Q[:, 0] + (zshift(x, Q[:, 0], Q[:, 1]) if zshift else 0)
        rings.append(np.stack([x, Q[:, 1], z], 1))
    rings = np.array(rings)
    body = loft(name, mat, rings, False, False, tag=tag)
    parts = [body]
    # the flat sides: the fully inset outline filled
    side = offset2d(prof, r)
    pts, tri = fill_outline(side, grid)
    for sgn in (-1, 1):
        y = pts[:, 1]
        x = sgn * hw(y)
        z = pts[:, 0] + (zshift(x, pts[:, 0], y) if zshift else 0)
        V = np.stack([x, y, z], 1)
        F = tri.copy()
        fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
        if np.mean(fn[:, 0]) * sgn < 0: F = F[:, ::-1]
        # weld: the outline points coincide with the last rounding ring; give them the side normal
        N = np.zeros_like(V); N[:, 0] = sgn
        parts.append(Part(name + ("_l" if sgn > 0 else "_r"), mat, V, F, N, tag))
    return parts
