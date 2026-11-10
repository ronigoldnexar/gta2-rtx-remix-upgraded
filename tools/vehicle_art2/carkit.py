#!/usr/bin/env python3
"""carkit: clean parametric car bodies for the 3D views (VEHICLE-ART-2).

A car is a set of smooth parametric surfaces S(u, v) -> (x, y, z) (metres, +y up, +z the
nose, x across). Each surface is triangulated on a regular (u, v) grid and its triangles
are cut exactly along material regions given as signed distance functions in (u, v)
space (window glass, rubber seals, pillars, panel inserts), so a window edge is a smooth
curve on the shell and never a texel staircase. Normals come from the surface's own
derivatives (smooth shading everywhere, no faceting). Wheels are surfaces of revolution
(tyre with sidewall bulge and tread, rim, hubcap) placed at marker nodes wheel_fl/fr/rl/rr,
which the renderer's wheel split uses (dll/src/car_bodies.cpp BuildWheelSplit).

Textures are generated here (paint with panel gaps and occlusion, glass with sky
reflection, chrome, tyre tread, lamp lenses, upholstery): no third-party or game art.
The paint texture's base colour is the sprite's default paint (catalog paint_rgb), so the
renderer's tint (live paint / default paint) gives each remap its sprite colour.

Output: a .glb that tools/import_assets.py turns into the game's .mesh + .tga files.
Materials named "paint_*" become "_paint" textures (tinted); "*_glass" textures are drawn
blended and last by the renderer (model_store.cpp); "_chrome" / "_rubber" get their own
specular there.
"""
import io
import json
import math
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# ---------------------------------------------------------------------------------------
# Geometry accumulation
# ---------------------------------------------------------------------------------------


class Part:
    """vertices / normals / uvs / triangles of one material"""

    def __init__(self):
        self.p, self.n, self.t, self.f = [], [], [], []
        self.count = 0

    def add(self, p, n, t, f):
        p = np.asarray(p, np.float64); n = np.asarray(n, np.float64); t = np.asarray(t, np.float64)
        f = np.asarray(f, np.int64)
        if len(f) == 0:
            return
        # keep only the vertices the triangles use
        used = np.unique(f)
        remap = -np.ones(len(p), np.int64); remap[used] = np.arange(len(used))
        self.p.append(p[used]); self.n.append(n[used]); self.t.append(t[used])
        self.f.append(remap[f] + self.count)
        self.count += len(used)

    def arrays(self):
        if not self.p:
            return None
        p = np.concatenate(self.p); n = np.concatenate(self.n); t = np.concatenate(self.t); f = np.concatenate(self.f)
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        n = n / np.maximum(ln, 1e-9)
        return p, n, t, f


class Car:
    def __init__(self, name):
        self.name = name
        self.parts = {}          # material -> Part
        self.markers = []        # (name, xyz)
        self.materials = {}      # material -> PIL image
        self.materials["chrome_disc"] = tex_chrome_disc()
        self.preview_tint = None # the sprite's default paint over the neutral paint (previews only)

    def part(self, mat):
        if mat not in self.parts:
            self.parts[mat] = Part()
        return self.parts[mat]

    def marker(self, name, xyz):
        self.markers.append((name, [float(c) for c in xyz]))

    # -----------------------------------------------------------------------------------
    def surface(self, fn, u0, u1, v0, v1, nu, nv, regions=(), default="paint_body", uvfn=None, flip=False,
                xform=None, mirror=False, closed_u=False, ukeys=(), vkeys=()):
        """fn(u, v) -> (x, y, z) arrays; regions: [(material, sdf(u, v)), ...] in priority order
        (negative = inside); uvfn(u, v) -> (s, t) texture coordinates (default: normalised u, v).
        ukeys / vkeys: extra grid lines (exact region edges). mirror: also emit the x-mirrored copy."""
        us = np.unique(np.concatenate([np.linspace(u0, u1, nu + 1), np.asarray(ukeys, float)]))
        vs = np.unique(np.concatenate([np.linspace(v0, v1, nv + 1), np.asarray(vkeys, float)]))
        us = us[(us >= u0 - 1e-12) & (us <= u1 + 1e-12)]
        vs = vs[(vs >= v0 - 1e-12) & (vs <= v1 + 1e-12)]
        U, V = np.meshgrid(us, vs, indexing="ij")
        pu = np.stack([U.ravel(), V.ravel()], 1)
        a = len(us); b = len(vs)
        tris = []
        for i in range(a - 1):
            for j in range(b - 1):
                k00 = i * b + j; k10 = (i + 1) * b + j; k01 = i * b + j + 1; k11 = (i + 1) * b + j + 1
                tris.append((k00, k10, k11)); tris.append((k00, k11, k01))
        # triangles as explicit param-space corner lists
        T = [[pu[t[0]], pu[t[1]], pu[t[2]]] for t in tris]
        assigned = []          # (material, [3 param points])
        rest = T
        for mat, sdf in regions:
            nxt = []
            for tri in rest:
                inside, outside = clip_tri(tri, sdf)
                for t in inside:
                    assigned.append((mat, t))
                nxt += outside
            rest = nxt
        for t in rest:
            assigned.append((default, t))
        # group per material and evaluate
        bymat = {}
        for mat, t in assigned:
            bymat.setdefault(mat, []).append(t)
        span = (u1 - u0, v1 - v0)
        for mat, ts in bymat.items():
            P = np.array(ts).reshape(-1, 2)
            # merge identical param points (shared vertices: smooth, crack free)
            key = np.round(P / np.array([max(span[0], 1e-9), max(span[1], 1e-9)]) * 1e7).astype(np.int64)
            _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
            Q = P[first]
            F = inv.reshape(-1, 3)
            xyz, nrm = eval_surface(fn, Q[:, 0], Q[:, 1], span)
            if closed_u:
                pass
            if flip:
                nrm = -nrm
                F = F[:, ::-1]
            if uvfn is not None:
                s, t = uvfn(Q[:, 0], Q[:, 1])
            else:
                s = (Q[:, 0] - u0) / (u1 - u0); t = (Q[:, 1] - v0) / (v1 - v0)
            uv = np.stack([s, t], 1)
            # drop degenerate triangles
            e1 = xyz[F[:, 1]] - xyz[F[:, 0]]; e2 = xyz[F[:, 2]] - xyz[F[:, 0]]
            area = np.linalg.norm(np.cross(e1, e2), axis=1)
            F = F[area > 1e-10]
            for m in ([False, True] if mirror else [False]):
                p = xyz.copy(); n = nrm.copy(); f = F
                if xform is not None:
                    p, n = xform(p, n)
                if m:
                    p[:, 0] *= -1; n[:, 0] *= -1; f = F[:, ::-1]
                self.part(mat).add(p, n, uv, f)

    # -----------------------------------------------------------------------------------
    def revolve(self, profile, centre, axis, nseg, mat_of=None, default="rubber", uv_mode="tyre", up=(0, 1, 0)):
        """A surface of revolution about `axis` (a vector; +-x for a wheel) through `centre`:
        profile = list of (r, d) points, d along the axis, the material of each profile segment
        from mat_of(k) (default `default`). uv_mode "tyre": u around, v along the profile;
        "disc": planar projection onto the disc."""
        if np.isscalar(axis):
            axis = (float(axis), 0.0, 0.0)
        ax = np.array(axis, float); ax /= np.linalg.norm(ax)
        upv = np.array(up, float)
        if abs(upv @ ax) > 0.9:
            upv = np.array([0.0, 0.0, 1.0]) if abs(ax[2]) < 0.9 else np.array([0.0, 1.0, 0.0])
        e1 = upv - (upv @ ax) * ax; e1 /= np.linalg.norm(e1)
        e2 = np.cross(ax, e1)
        c = np.array(centre, float)
        prof = np.asarray(profile, float)
        m = len(prof)
        ang = np.linspace(0, 2 * math.pi, nseg + 1)
        rmax = max(prof[:, 0].max(), 1e-6)
        for k in range(m - 1):
            mat = mat_of(k) if mat_of else default
            if mat == "chrome" and uv_mode == "disc":
                mat = "chrome_disc"     # a radial reflection: the band texture across a disc reads as a half moon
            P, N, Tc, F = [], [], [], []
            for kk in (0, 1):
                idx = k + kk
                r, d = prof[idx]
                nr, nd = profile_normal(prof, idx, k)
                for a in ang:
                    ca, sa = math.cos(a), math.sin(a)
                    radial = ca * e1 + sa * e2
                    P.append(c + d * ax + r * radial)
                    N.append(nd * ax + nr * radial)
                    if uv_mode == "tyre":
                        Tc.append((a / (2 * math.pi), idx / (m - 1)))
                    else:
                        rr = r / rmax
                        Tc.append((0.5 + 0.5 * rr * ca, 0.5 + 0.5 * rr * sa))
            L = len(ang)
            for i in range(nseg):
                F.append((i, L + i, L + i + 1)); F.append((i, L + i + 1, i + 1))
            self.part(mat).add(P, N, Tc, np.array(F))

    def sweep(self, path, radius, n_u, n_v, mat, up=(0, 1, 0), squash=(1.0, 1.0), caps=True):
        """a tube along path(u) (u in 0..1, returns (n,3)), radius(u) (or a number), elliptical
        section squashed by (horizontal, vertical); the ends closed with domes when caps"""
        u = np.linspace(0, 1, n_u + 1)
        rad = radius if callable(radius) else (lambda uu: np.full_like(uu, float(radius)))
        def fn(uu, vv):
            uu = np.asarray(uu, float); vv = np.asarray(vv, float)
            P = path(uu); h = 1e-4
            T = path(np.clip(uu + h, 0, 1)) - path(np.clip(uu - h, 0, 1))
            T = T / np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
            upv = np.repeat(np.array(up, float)[None, :], len(T), 0)
            par = np.abs((T * upv).sum(1)) > 0.95
            upv[par] = np.array([0.0, 0.0, 1.0]) if abs(up[2]) < 0.5 else np.array([1.0, 0.0, 0.0])
            B = np.cross(T, upv); B = B / np.maximum(np.linalg.norm(B, axis=1, keepdims=True), 1e-12)
            Nn = np.cross(B, T)
            r = rad(uu)
            if caps:
                end = np.minimum(uu, 1 - uu)
                r = r * np.sqrt(np.clip(1 - (np.clip(0.04 - end, 0, None) / 0.04) ** 2, 0, 1))
            ca, sa = np.cos(vv), np.sin(vv)
            Q = P + (B * (ca * squash[0])[:, None] + Nn * (sa * squash[1])[:, None]) * r[:, None]
            return Q[:, 0], Q[:, 1], Q[:, 2]
        self.surface(fn, 0, 1, 0, 2 * math.pi, n_u, n_v, default=mat)

    def cap(self, fn, u_end, v0, v1, nv, mat, mirror=True, nr=3, regions=(), uvfn=None):
        """close a loft's open end: the section ring fn(u_end, v) fanned to its centre (x = 0)"""
        vs = np.linspace(v0, v1, 64)
        x, y, z = fn(np.full_like(vs, u_end), vs)
        C = np.array([0.0, float(np.mean(y)), float(np.mean(z))])
        def capfn(r, v):
            r = np.asarray(r, float); v = np.asarray(v, float)
            px, py, pz = fn(np.full_like(v, u_end), v)
            if mirror:
                # VEHICLE-ART-14: a mirrored half ring must start and end on the centre line; a section whose end
                # point sits off it (car_010: sepow(cos(pi/2), 0.08) = 0.05) left a wedge open between the two
                # fans, a black crack up the tail panel
                px = np.where((v <= v0 + 1e-9) | (v >= v1 - 1e-9), 0.0, px)
            return C[0] + r * (px - C[0]), C[1] + r * (py - C[1]), C[2] + r * (pz - C[2])
        if regions:
            # VEHICLE-ART-14: a region given by the ring parameter (v < 0.14: the bottom of the section) took every
            # fan triangle down to the centre, a dark chevron up the tail/nose panel (050, 051, 056); it now takes only
            # the fan's outer band (r > 0.8), a strip along the panel's bottom edge
            regions = [(nm, (lambda r, v, f=f: np.maximum(f(r, v), 0.8 - np.asarray(r, float)))) for nm, f in regions]
            nr = max(nr, 5)
        self.surface(capfn, 0.0, 1.0, v0, v1, nr, nv, default=mat, mirror=mirror, regions=regions,
                     uvfn=uvfn or (lambda r, v: (0.5 + 0 * r, 0.5 + 0 * v)))

    def box(self, mat, lo, hi, uv_scale=1.0):
        lo = np.array(lo, float); hi = np.array(hi, float)
        P, N, T, F = [], [], [], []
        faces = [((0, 1, 2), 0, 1), ((0, 1, 2), 0, -1)]
        for axis in range(3):
            for sgn in (-1, 1):
                o = [(axis + 1) % 3, (axis + 2) % 3]
                base = len(P)
                for c in ((0, 0), (1, 0), (1, 1), (0, 1)):
                    q = np.where(np.arange(3) == axis, hi if sgn > 0 else lo, 0.0)
                    q = q.copy()
                    q[axis] = (hi if sgn > 0 else lo)[axis]
                    q[o[0]] = (lo, hi)[c[0]][o[0]]; q[o[1]] = (lo, hi)[c[1]][o[1]]
                    P.append(q); nn = [0, 0, 0]; nn[axis] = sgn; N.append(nn)
                    # faces looking down an axis read their picture unmirrored from outside
                    T.append((1 - c[0], c[1]) if (sgn < 0) != (axis == 1) else c)
                if sgn > 0:
                    F += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
                else:
                    F += [(base, base + 2, base + 1), (base, base + 3, base + 2)]
        self.part(mat).add(P, N, T, F)

    def squash_xz(self, s):
        """scale everything built so far by s across and along (heights kept): a body modelled on
        the sprite's footprint at 5 m a block becomes one at the street's 4 m a block (a person is
        0.45 block) with real heights. Parts added afterwards (wheels, lamps) are in final units."""
        for part in self.parts.values():
            for i in range(len(part.p)):
                part.p[i] = part.p[i] * np.array([s, 1.0, s])
                n = part.n[i] / np.array([s, 1.0, s])
                part.n[i] = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        self.markers = [(n, [p[0] * s, p[1], p[2] * s]) for n, p in self.markers]

    def stats(self):
        v = sum(p.count for p in self.parts.values())
        f = sum(sum(len(x) for x in p.f) for p in self.parts.values())
        return v, f


def profile_normal(prof, idx, seg):
    """outward normal (nr, nx) of a revolve profile at point idx, averaged over its segments"""
    def segn(k):
        r0, x0 = prof[k]; r1, x1 = prof[k + 1]
        dr, dx = r1 - r0, x1 - x0
        # profile runs inner->outer around the tyre; outward = rotate (dr, dx) by -90 deg
        nr, nx = dx, -dr
        l = math.hypot(nr, nx) or 1.0
        return nr / l, nx / l
    ks = [k for k in (idx - 1, idx) if 0 <= k < len(prof) - 1]
    # a sharp corner (> 50 deg between segments) keeps the segment's own normal
    if len(ks) == 2:
        a = segn(ks[0]); b = segn(ks[1])
        if a[0] * b[0] + a[1] * b[1] < 0.64:
            return segn(seg)
        nr, nx = a[0] + b[0], a[1] + b[1]
        l = math.hypot(nr, nx) or 1.0
        return nr / l, nx / l
    return segn(ks[0])


def eval_surface(fn, u, v, span):
    xyz = np.stack(fn(u, v), 1)
    hu = 1e-4 * max(span[0], 1e-6); hv = 1e-4 * max(span[1], 1e-6)
    du = (np.stack(fn(u + hu, v), 1) - np.stack(fn(u - hu, v), 1))
    dv = (np.stack(fn(u, v + hv), 1) - np.stack(fn(u, v - hv), 1))
    n = np.cross(du, dv)
    ln = np.linalg.norm(n, axis=1)
    bad = ln < 1e-12
    if bad.any():
        # a pole (a section shrunk to a point): take the derivative a little inside
        for sgn in (1, -1):
            uu = u[bad] + sgn * 5e-3 * span[0]
            du2 = np.stack(fn(uu + hu, v[bad]), 1) - np.stack(fn(uu - hu, v[bad]), 1)
            dv2 = np.stack(fn(uu, v[bad] + hv), 1) - np.stack(fn(uu, v[bad] - hv), 1)
            n2 = np.cross(du2, dv2)
            ok = np.linalg.norm(n2, axis=1) > 1e-12
            idx = np.where(bad)[0][ok]
            n[idx] = n2[ok]
            bad[idx] = False
            if not bad.any():
                break
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    return xyz, n


def clip_tri(tri, sdf):
    """split a param-space triangle by sdf = 0: (inside pieces, outside pieces)"""
    P = np.array(tri)
    d = np.array(sdf(P[:, 0], P[:, 1]), float).reshape(3)
    if (d < 0).all():
        return [tri], []
    if (d >= 0).all():
        return [], [tri]
    poly_in, poly_out = [], []
    for k in range(3):
        a, b = P[k], P[(k + 1) % 3]
        da, db = d[k], d[(k + 1) % 3]
        (poly_in if da < 0 else poly_out).append(a)
        if (da < 0) != (db < 0):
            t = da / (da - db)
            # refine the crossing on the true sdf (bisection), not the linear guess
            lo, hi = 0.0, 1.0
            neg_at_lo = da < 0
            for _ in range(18):
                mid = 0.5 * (lo + hi)
                q = a + (b - a) * mid
                dm = float(np.array(sdf(np.array([q[0]]), np.array([q[1]]))).reshape(-1)[0])
                if (dm < 0) == neg_at_lo:
                    lo = mid
                else:
                    hi = mid
            t = 0.5 * (lo + hi)
            q = a + (b - a) * t
            poly_in.append(q); poly_out.append(q)
    fan = lambda poly: [[poly[0], poly[i], poly[i + 1]] for i in range(1, len(poly) - 1)]
    return fan(poly_in), fan(poly_out)


# ---------------------------------------------------------------------------------------
# Shape helpers
# ---------------------------------------------------------------------------------------


def smoothstep(a, b, x):
    t = np.clip((np.asarray(x, float) - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def spline(keys):
    """monotone cubic (PCHIP) through (x, y) keys; returns f(x) (clamped at the ends)"""
    xs = np.array([k[0] for k in keys], float); ys = np.array([k[1] for k in keys], float)
    h = np.diff(xs); dl = np.diff(ys) / h
    m = np.zeros_like(ys)
    for i in range(1, len(xs) - 1):
        if dl[i - 1] * dl[i] > 0:
            w1 = 2 * h[i] + h[i - 1]; w2 = h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / dl[i - 1] + w2 / dl[i])
    m[0] = dl[0]; m[-1] = dl[-1]

    def f(x):
        x = np.clip(np.asarray(x, float), xs[0], xs[-1])
        i = np.clip(np.searchsorted(xs, x) - 1, 0, len(xs) - 2)
        t = (x - xs[i]) / h[i]
        h00 = 2 * t ** 3 - 3 * t ** 2 + 1; h10 = t ** 3 - 2 * t ** 2 + t
        h01 = -2 * t ** 3 + 3 * t ** 2; h11 = t ** 3 - t ** 2
        return h00 * ys[i] + h10 * h[i] * m[i] + h01 * ys[i + 1] + h11 * h[i] * m[i + 1]
    return f


def sepow(c, e):
    return np.sign(c) * np.abs(c) ** e


def rrect_sdf(cu, cv, hu, hv, r, su=1.0, sv=1.0):
    """rounded rectangle in (u, v) param space, u and v scaled by su / sv to make it isotropic"""
    def f(u, v):
        qx = np.abs((np.asarray(u) - cu) * su) - (hu * su - r)
        qy = np.abs((np.asarray(v) - cv) * sv) - (hv * sv - r)
        return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r
    return f


def poly_sdf(pts, su=1.0, sv=1.0):
    """signed distance to a convex or concave polygon in scaled (u, v) space (negative inside)"""
    P = np.array(pts, float) * [su, sv]

    def f(u, v):
        x = np.asarray(u, float) * su; y = np.asarray(v, float) * sv
        d = np.full(x.shape, 1e9); s = np.ones(x.shape)
        n = len(P)
        for i in range(n):
            a = P[i]; b = P[(i + 1) % n]
            e = b - a; w0 = x - a[0]; w1 = y - a[1]
            t = np.clip((w0 * e[0] + w1 * e[1]) / (e @ e), 0, 1)
            dx = w0 - e[0] * t; dy = w1 - e[1] * t
            d = np.minimum(d, dx * dx + dy * dy)
            c1 = y >= a[1]; c2 = y < b[1]; c3 = e[0] * w1 > e[1] * w0
            flip = (c1 & c2 & c3) | (~c1 & ~c2 & ~c3)
            s = np.where(flip, -s, s)
        return s * np.sqrt(d)
    return f


def sdf_union(*fs):
    return lambda u, v: np.minimum.reduce([f(u, v) for f in fs])


def sdf_shrink(f, w):
    return lambda u, v: f(u, v) + w


def sdf_band(f, w):
    """the outline band of width w just inside the shape f (a seal or frame)"""
    return lambda u, v: np.maximum(f(u, v), -(f(u, v) + w))


# ---------------------------------------------------------------------------------------
# Wheels
# ---------------------------------------------------------------------------------------


def add_wheel(car, name, centre, radius, width, side, style):
    """tyre + rim + hubcap at centre (metres); side +1 = right (x > 0); style keys:
    rim_r (fraction of radius), rim_mat, cap_mat, whitewall (fraction or 0), cap_dome, spokes"""
    r = radius; w = width
    rim_r = style.get("rim_r", 0.62) * r
    ww = style.get("whitewall", 0.0)
    # tyre profile (r, x outward), from the inner bead round the tread to the outer bead
    prof = [
        (rim_r * 1.02, -0.42 * w),
        (0.80 * r, -0.50 * w),
        (0.93 * r, -0.50 * w),
        (0.985 * r, -0.44 * w),
        (r, -0.30 * w),
        (r, 0.30 * w),
        (0.985 * r, 0.44 * w),
        (0.93 * r, 0.50 * w),
        (0.80 * r, 0.50 * w),
        (rim_r * 1.02, 0.42 * w),
    ]
    def tyre_mat(k):
        if 3 <= k <= 5:
            return "tyre_tread"
        if ww and k in (7, 8):
            return "whitewall"
        return "tyre_side"
    car.revolve(prof, centre, (side, 0, 0), 30, mat_of=tyre_mat)
    # rim: a dished steel/painted wheel, then the hubcap dome
    rim = [
        (rim_r * 1.02, 0.42 * w),
        (rim_r * 0.98, 0.36 * w),
        (rim_r * 0.80, 0.30 * w),
        (rim_r * 0.72, 0.34 * w),
    ]
    car.revolve(rim, centre, (side, 0, 0), 24, default=style.get("rim_mat", "chrome"), uv_mode="disc")
    cap_r = rim_r * 0.72
    dome = style.get("cap_dome", 0.10) * r
    cap = [(cap_r, 0.34 * w)]
    for k in range(1, 7):
        a = k / 6 * math.pi / 2
        cap.append((cap_r * math.cos(a) + 1e-4, 0.34 * w + dome * math.sin(a)))
    car.revolve(cap, centre, (side, 0, 0), 24, default=style.get("cap_mat", "chrome"), uv_mode="disc")
    # inner face: a dark disc so the wheel is never see-through from the inside
    inner = [(rim_r * 1.02, -0.42 * w), (0.001, -0.30 * w)]
    car.revolve(inner, centre, (side, 0, 0), 20, default="underbody", uv_mode="disc")
    car.marker(name, centre)


# ---------------------------------------------------------------------------------------
# Textures
# ---------------------------------------------------------------------------------------


def noise(h, w, scale, seed):
    rng = np.random.default_rng(seed)
    g = rng.random((max(2, h // scale + 2), max(2, w // scale + 2)))
    im = Image.fromarray((g * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    return np.asarray(im, float) / 255.0


def tex_paint(rgb, size=512, lines_u=(), lines_v=(), ao_v=None, seed=1, handles=()):
    """the paint: base colour rgb with a faint orange-peel noise, panel gaps (dark lines at
    normalised u or v) and occlusion along v (ao_v: list of (v0, v1, depth))"""
    base = np.array(rgb, float)
    a = np.ones((size, size, 3)) * base
    n = noise(size, size, 6, seed) * 0.5 + noise(size, size, 40, seed + 1) * 0.5
    a *= (0.975 + 0.05 * n)[..., None]
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    dark = tuple(int(c * 0.28) for c in rgb)
    for (u, v0, v1) in lines_u:
        x = int(u * size)
        d.line([(x, int(v0 * size)), (x, int(v1 * size))], fill=dark, width=2)
    for (v, u0, u1) in lines_v:
        y = int(v * size)
        d.line([(int(u0 * size), y), (int(u1 * size), y)], fill=dark, width=2)
    for (u, v, wd, ht) in handles:
        x, y = int(u * size), int(v * size)
        d.rounded_rectangle([x - wd * size / 2, y - ht * size / 2, x + wd * size / 2, y + ht * size / 2],
                            radius=2, fill=(205, 205, 210))
    im = im.filter(ImageFilter.GaussianBlur(0.6))
    a = np.asarray(im, float)
    if ao_v:
        vv = np.linspace(0, 1, size)[None, :, None] * np.ones((size, 1, 1))
        vv = np.linspace(0, 1, size)[:, None, None] * np.ones((1, size, 1))
        f = np.ones_like(vv)
        for (v0, v1, depth) in ao_v:
            f *= 1 - depth * smoothstep(v1, v0, vv) if v0 > v1 else 1 - depth * (1 - smoothstep(v0, v1, vv))
        a *= f
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def tex_glass(size=256, tint=(70, 92, 110), alpha=150, interior=None):
    """window glass: a dark tint with a sky gradient and two soft diagonal reflection streaks;
    alpha < 255 (the renderer blends it). t (rows) runs along the surface's v parameter."""
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0)
    base = np.array(tint, float)[None, None, :] * (0.75 + 0.45 * (1 - yy))[..., None]
    streak = np.exp(-((xx * 0.8 + yy * 0.6 - 0.45) / 0.07) ** 2) * 0.55 + np.exp(-((xx * 0.8 + yy * 0.6 - 0.72) / 0.035) ** 2) * 0.35
    rgb = base + streak[..., None] * np.array([200, 215, 230])
    a = np.full((size, size), float(alpha)) + streak * 70
    out = np.dstack([np.clip(rgb, 0, 255), np.clip(a, 0, 255)]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def tex_flat(rgb, size=16, alpha=255):
    a = np.ones((size, size, 4)) * (list(rgb) + [alpha])
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def tex_underbody(size=64, seed=29):
    """VEHICLE-ART-13: the shared underside / wheel-well / chassis paint of every kit car: road-grimed dark grey
    (was a flat 28,27,26 per car: a car seen from below or on its roof read as a black slab, pass 195)"""
    rng = np.random.default_rng(seed)
    n = rng.normal(0, 1, (size // 8, size // 8)).astype(np.float32)
    big = np.asarray(Image.fromarray(((n - n.min()) / (np.ptp(n) + 1e-6) * 255).astype(np.uint8)).resize((size, size), Image.BICUBIC), np.float32) / 255 - 0.5
    fine = rng.normal(0, 1, (size, size)).astype(np.float32)
    b = 66.0 + 14.0 * big + 3.0 * fine
    rgb = np.stack([b * 1.0, b * 0.97, b * 0.93], -1)
    a = np.full((size, size, 1), 255.0, np.float32)
    return Image.fromarray(np.clip(np.concatenate([rgb, a], -1), 0, 255).astype(np.uint8), "RGBA")


def tex_chrome(size=128):
    """bright metal: a horizon-like band (sky over a dark ground reflection) along v"""
    yy = np.linspace(0, 1, size)[:, None] * np.ones((1, size))
    sky = np.array([210, 222, 235.0]); ground = np.array([70, 66, 62.0]); horizon = np.array([250, 250, 248.0])
    t = yy[..., None]
    rgb = np.where(t < 0.45, sky * (1 - t / 0.45) + horizon * (t / 0.45),
                   np.where(t < 0.52, horizon * (1 - (t - 0.45) / 0.07) + ground * ((t - 0.45) / 0.07), ground + (t - 0.52) * 60))
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def tex_chrome_disc(size=128):
    """bright metal seen face on (hub caps, lamp bezels): concentric rings of sky and dark ground, a glint"""
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0) * 2 - 1
    r = np.hypot(xx, yy)
    band = 0.5 + 0.5 * np.cos(r * 9.0)
    v = 95 + 130 * band - 40 * (r > 0.92)
    glint = np.exp(-(((xx + 0.35) ** 2 + (yy + 0.40) ** 2) / 0.02)) * 90
    rgb = np.dstack([v + glint, v + glint + 4, v + glint + 10])
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def tex_tread(size=256, grooves=4):
    """tread: u around the tyre, v across it (0..1 over the tread segments)"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    base = 34 + 6 * noise(size, size, 8, 7)
    # circumferential grooves and transverse sipes
    g = np.zeros((size, size))
    for k in range(grooves):
        c = (k + 0.5) / grooves
        g += np.exp(-((yy - c) / 0.018) ** 2)
    sipe = (np.abs(((xx * 96) % 1.0) - 0.5) < 0.09) & (np.abs(((yy * grooves) % 1.0) - 0.5) < 0.38)
    v = base - 20 * np.clip(g, 0, 1) - 12 * sipe
    v = np.clip(v, 8, 255)
    return Image.fromarray(np.dstack([v, v, v * 1.02]).astype(np.uint8))


def tex_tyre_side(size=128):
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    v = 36 + 8 * noise(size, size, 16, 3) - 6 * np.exp(-((yy - 0.5) / 0.05) ** 2)
    return Image.fromarray(np.dstack([v, v, v]).astype(np.uint8))


def tex_lamp(kind, size=64):
    if kind == "head":
        size = max(size, 128)     # the prism cells need the texels
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0) * 2 - 1
    r = np.hypot(xx, yy)
    if kind == "head":
        # VEHICLE-ART-7: a 1950s sealed beam seen by day (as tools/vehicle_art/m063_truck_cab.py
        # sealed_beam_shader): a silvered reflector bright round the bulb behind clear prism glass (a grid
        # of lens cells), the bulb's dark shield with a chrome cap, a dark seal at the rim. The old fluted
        # grey-blue lens over a dark bowl read as a dark dome in the game's light.
        b = 0.50 + 0.42 * np.exp(-((r - 0.52) / 0.24) ** 2) + 0.10 * np.clip(-yy, 0, 1)
        cell = 0.17
        gx = np.abs(((xx / cell) % 1.0) - 0.5) > 0.40
        gy = np.abs(((yy / cell) % 1.0) - 0.5) > 0.40
        b = np.where((gx | gy) & (r < 0.86), b * 0.74, b)
        b = np.where(r < 0.11, 0.30, b)
        b = np.where((r >= 0.11) & (r < 0.16), 0.98, b)
        b = np.where(r > 0.90, 0.16, b)
        rgb = b[..., None] * np.array([0.90, 0.92, 0.95]) * 255
        rgb[..., 0] += 10 * np.exp(-((r - 0.30) / 0.10) ** 2)
        rgb += np.exp(-(((xx + 0.35) ** 2 + (yy + 0.40) ** 2) / 0.012))[..., None] * 60
    elif kind == "tail":
        rgb = np.dstack([170 - 50 * r, 18 + 0 * r, 22 + 0 * r]) * (0.85 + 0.15 * (0.5 + 0.5 * np.cos(r * 22)))[..., None]
        rgb += np.exp(-(((xx + 0.3) ** 2 + (yy + 0.35) ** 2) / 0.05))[..., None] * 70
    else:  # amber
        rgb = np.dstack([235 - 40 * r, 140 - 30 * r, 30 + 0 * r])
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def tex_leather(rgb, size=128, seams=6):
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    n = noise(size, size, 3, 11)
    a = np.array(rgb, float)[None, None] * (0.85 + 0.15 * n)[..., None]
    pleat = 0.5 + 0.5 * np.cos(xx * seams * 2 * math.pi)
    a *= (0.8 + 0.2 * pleat)[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def tex_grille(size=128, bars=10, rgb=(30, 30, 32)):
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    bar = np.abs(((yy * bars) % 1.0) - 0.5) < 0.22
    v = np.where(bar, 200, 26)
    a = np.dstack([v, v, v * 1.03]).astype(np.uint8)
    return Image.fromarray(a)


# ---------------------------------------------------------------------------------------
# glTF binary writer
# ---------------------------------------------------------------------------------------


def write_glb(car, path, scale=1.0, order=None):
    """materials in `order` first (the glass last, so the renderer blends it over the rest)"""
    mats = [m for m in (order or []) if m in car.parts] + [m for m in car.parts if m not in (order or [])]
    mats = [m for m in mats if car.parts[m].arrays() is not None]
    glass = [m for m in mats if "glass" in m]
    mats = [m for m in mats if m not in glass] + glass
    buf = bytearray()
    views, accessors, meshes, nodes, materials, images, textures = [], [], [], [], [], [], []

    def add_view(data, target=None):
        while len(buf) % 4:
            buf.append(0)
        off = len(buf); buf.extend(data)
        v = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target:
            v["target"] = target
        views.append(v)
        return len(views) - 1

    for mi, m in enumerate(mats):
        p, n, t, f = car.parts[m].arrays()
        p = (p * scale).astype(np.float32); n = n.astype(np.float32); t = t.astype(np.float32)
        f = f.astype(np.uint32)
        a_p = len(accessors); accessors.append({"bufferView": add_view(p.tobytes(), 34962), "componentType": 5126, "count": len(p),
                                                "type": "VEC3", "min": p.min(0).tolist(), "max": p.max(0).tolist()})
        a_n = len(accessors); accessors.append({"bufferView": add_view(n.tobytes(), 34962), "componentType": 5126, "count": len(n), "type": "VEC3"})
        a_t = len(accessors); accessors.append({"bufferView": add_view(t.tobytes(), 34962), "componentType": 5126, "count": len(t), "type": "VEC2"})
        a_f = len(accessors); accessors.append({"bufferView": add_view(f.ravel().tobytes(), 34963), "componentType": 5125, "count": f.size, "type": "SCALAR"})
        img = car.materials.get(m)
        if img is None:
            raise SystemExit(f"{car.name}: material {m} has no texture")
        bio = io.BytesIO(); img.save(bio, "PNG")
        images.append({"bufferView": add_view(bio.getvalue()), "mimeType": "image/png"})
        textures.append({"source": len(images) - 1})
        materials.append({"name": m, "pbrMetallicRoughness": {"baseColorTexture": {"index": len(textures) - 1},
                                                             "metallicFactor": 0.0, "roughnessFactor": 0.5}})
        meshes.append({"name": m, "primitives": [{"attributes": {"POSITION": a_p, "NORMAL": a_n, "TEXCOORD_0": a_t},
                                                  "indices": a_f, "material": mi}]})
        nodes.append({"name": m[:31], "mesh": mi})
    for name, xyz in car.markers:
        nodes.append({"name": name, "translation": [c * scale for c in xyz]})
    gl = {"asset": {"version": "2.0", "generator": "carkit (VEHICLE-ART-2)"}, "scene": 0,
          "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes, "materials": materials,
          "textures": textures, "images": images, "accessors": accessors, "bufferViews": views,
          "buffers": [{"byteLength": len(buf)}]}
    js = json.dumps(gl).encode()
    while len(js) % 4:
        js += b" "
    while len(buf) % 4:
        buf.append(0)
    out = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + 8 + len(buf))
    out += struct.pack("<I", len(js)) + b"JSON" + js + struct.pack("<I", len(buf)) + b"BIN\x00" + bytes(buf)
    open(path, "wb").write(out)
    return mats


# ---------------------------------------------------------------------------------------
# Ambient occlusion baked into a surface's texture
# ---------------------------------------------------------------------------------------


def bake_ao(car, fn, u0, u1, v0, v1, mat, size=160, rays=48, reach=0.9, strength=0.75, uv=None, gamma=1.0):
    """darken car.materials[mat] by the sky each texel of the surface fn sees, ray cast against the
    whole car (open3d). The texture's (s, t) must map linearly to (u, v): s = (u - u0)/(u1 - u0),
    t = (v - v0)/(v1 - v0) (uv: an (s,t)->(u,v) override). The less occluded side of the surface is
    taken as the outside, so the normal's sign does not matter."""
    import open3d as o3d
    P, F = [], []
    off = 0
    for m, part in car.parts.items():
        arr = part.arrays()
        if arr is None or "glass" in m:
            continue
        p, n, t, f = arr
        P.append(p); F.append(f + off); off += len(p)
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.core.Tensor(np.concatenate(P).astype(np.float32)), o3d.core.Tensor(np.concatenate(F).astype(np.uint32)))
    s = (np.arange(size) + 0.5) / size
    S, T = np.meshgrid(s, s, indexing="xy")          # rows = t, columns = s
    if uv is None:
        U = u0 + S * (u1 - u0); V = v0 + T * (v1 - v0)
    else:
        U, V = uv(S, T)
    xyz, nrm = eval_surface(fn, U.ravel(), V.ravel(), (u1 - u0, v1 - v0))
    rng = np.random.default_rng(5)
    # cosine-weighted directions about +z, rotated onto each normal
    a = rng.random(rays); b = rng.random(rays)
    r = np.sqrt(a); th = 2 * math.pi * b
    local = np.stack([r * np.cos(th), r * np.sin(th), np.sqrt(1 - a)], 1)
    best = None
    for sgn in (1.0, -1.0):
        n = nrm * sgn
        t1 = np.cross(n, np.where(np.abs(n[:, :1]) < 0.9, [[1, 0, 0]], [[0, 1, 0]]))
        t1 /= np.maximum(np.linalg.norm(t1, axis=1, keepdims=True), 1e-9)
        t2 = np.cross(n, t1)
        D = local[None, :, 0:1] * t1[:, None] + local[None, :, 1:2] * t2[:, None] + local[None, :, 2:3] * n[:, None]
        O = np.repeat(xyz[:, None] + n[:, None] * 0.004, rays, 1)
        R = np.concatenate([O.reshape(-1, 3), D.reshape(-1, 3)], 1).astype(np.float32)
        hit = scene.cast_rays(o3d.core.Tensor(R))["t_hit"].numpy().reshape(-1, rays)
        occ = (hit < reach).mean(1)
        best = occ if best is None else np.minimum(best, occ)
    ao = 1 - strength * best.reshape(size, size) ** gamma
    im = car.materials[mat]
    aoim = Image.fromarray((np.clip(ao, 0, 1) * 255).astype(np.uint8)).resize(im.size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.2))
    A = np.asarray(aoim, float)[..., None] / 255.0
    arr = np.asarray(im.convert("RGBA"), float)
    arr[..., :3] *= A
    car.materials[mat] = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA" if im.mode == "RGBA" else "RGBA").convert(im.mode)
    return ao
