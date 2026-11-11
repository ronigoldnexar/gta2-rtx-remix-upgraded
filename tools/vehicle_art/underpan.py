#!/usr/bin/env python3
"""VEHICLE-ART-13: one shared floor pan for every car body (generated shells, carkit v1, vehicle_art2 kit).

Every car's underside was near-black texels (the kit's flat 28,27,26 `underbody`, the image-to-3D shells' random
projection), so a car seen from below or lying on its roof read as a black slab (DEFECT-TRIAGE pass 195, pm33).
This adds one extra draw group, `<name>_underpan.tga` (the same shared texture for every car), hung just under the
body's own floor: a stamped dark-grey pan with a transmission tunnel and cross members, two frame rails, the sump and
gearbox, a propshaft, a front cross-member, a rear axle tube with its differential, the exhaust with a silencer, and
a fuel tank. Nothing else in the .mesh changes.

Wheel split safety (dll/src/car_bodies.cpp BuildWheelSplit): a face goes to a wheel when all its corners lie
within the wheel's disc (y-z, ~1.06 r) AND outboard of xin (>= 0.25 x half width for marker wheels, >= 0.35 x for
shells). Near each axle the pan narrows to 0.20 x half width (the wheel wells), so no face of it can ever be taken.

    gen3d/venv/bin/python tools/vehicle_art/underpan.py <in_models_dir> <out_models_dir> NNN [NNN ...] | --all
    (reads <in>/<name>.mesh, writes <out>/<name>.mesh and <out>/<name>_underpan.tga; never writes in place: the
    models dirs are hard-linked into stages, copy the results with cp --remove-destination)
    --check: print each car's floor height / axles / pan size without writing.
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import mesh_io  # noqa

NODE = "underpan"
WHEELS = json.load(open(os.path.join(HERE, "underpan_wheels.json")))
# not road cars: the tank (tracks), rail stock and trailers (bogies / chassis of their own: rail_kit.py), the wrecks
# (a burnt-out shell's underside is black by design); 063 Truck Cab has an authored ladder chassis with its tanks
# VEHICLE-ART-24: kit bodies whose floor narrows to an egg at the ends (028): their pan follows the body's own outline
# at floor level like the shell bodies' does, not the kit's fixed 0.80 rectangle (that stood ~0.3 m out past 028's tail
# as a hard-edged dark slab, out/va24_a4 rear34). 029 has the same shape but is not rebuilt here.
FOLLOW = {"028", "083", "047", "048"}   # VEHICLE-ART-25: 083/047/048 pinched nose and tail
# (007, VEHICLE-ART-24: an open high truck chassis like 063; its pan measured a 0.16 m floor and hung as a slab)
SKIP = {"063", "007", "006", "054", "055", "059", "060", "061", "065", "066", "023", "027"} | {f"{n:03d}" for n in range(72, 82)}

# ------------------------------------------------------------------------------------------------------------------
# The shared texture: a 256 px atlas, four regions (u0, v0, u1, v1 in image space, v down)
# ------------------------------------------------------------------------------------------------------------------
R_PAN = (0.0, 0.0, 0.5, 1.0)       # the floor pan, planar (x across, z along: v = nose at the top)
R_DARK = (0.5, 0.0, 1.0, 0.5)      # cast iron / oily steel: sump, gearbox, diff, rails, axle
R_RUST = (0.5, 0.5, 0.75, 1.0)     # exhaust: heat-browned steel
R_TANK = (0.75, 0.5, 1.0, 0.75)    # fuel tank: painted steel, a little lighter
R_GRIME = (0.75, 0.75, 1.0, 1.0)   # VEHICLE-ART-14: road grime over the shell's own downward faces (the cover)


PAN_BASE = 64.0   # VEHICLE-ART-14: was 92 (ART-13): darker grime-grey, the stamping still reads


def texture(size=256, seed=13):
    rng = np.random.default_rng(seed)
    S = size
    img = np.zeros((S, S, 3), np.float32)

    def noise(h, w, scale, amp):
        n = rng.normal(0, 1, (max(2, h // scale), max(2, w // scale))).astype(np.float32)
        im = Image.fromarray(((n - n.min()) / (np.ptp(n) + 1e-6) * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        return (np.asarray(im, np.float32) / 255 - 0.5) * 2 * amp

    def region(r):
        return int(r[1] * S), int(r[3] * S), int(r[0] * S), int(r[2] * S)

    # pan: galvanised-dark grey (a real underside under road grime), lit from below it must still read grey
    y0, y1, x0, x1 = region(R_PAN)
    h, w = y1 - y0, x1 - x0
    base = np.full((h, w), PAN_BASE, np.float32) + noise(h, w, 16, 7) + noise(h, w, 3, 4)
    xs = (np.arange(w) + 0.5) / w             # 0..1 across (0.5 = the centre line)
    vs = (np.arange(h) + 0.5) / h             # 0 nose .. 1 tail
    X, V = np.meshgrid(xs, vs)
    # transmission tunnel: a darker band down the middle with soft stamped shoulders
    d = np.abs(X - 0.5)
    base -= 16 * np.clip((0.085 - d) / 0.03, 0, 1)
    base += 10 * np.exp(-((d - 0.095) / 0.010) ** 2)          # the bright shoulder edge
    # stamped ribs across the floor halves (stiffening swages), every ~1/9 of the length, outside the tunnel
    rib = np.exp(-(((V * 9.0) % 1.0 - 0.5) / 0.05) ** 2) * (d > 0.12) * (d < 0.44)
    base += 9 * rib
    base -= 7 * np.exp(-((((V * 9.0) + 0.12) % 1.0 - 0.5) / 0.05) ** 2) * (d > 0.12) * (d < 0.44)
    # cross members: two dark bars (under the seats) and a lighter seam at the edges
    for vc in (0.42, 0.62):
        base -= 18 * np.clip((0.018 - np.abs(V - vc)) / 0.006, 0, 1)
    base += 8 * np.exp(-((d - 0.47) / 0.012) ** 2)
    # road grime: darker towards the wheels (front and rear) and the edges
    base -= 10 * (np.exp(-((V - 0.10) / 0.12) ** 2) + np.exp(-((V - 0.90) / 0.12) ** 2)) * (d > 0.25)
    base -= 8 * np.clip((d - 0.40) / 0.08, 0, 1)                # grime builds up towards the sills
    pan = np.stack([base * 0.98, base * 0.97, base * 0.95], -1)
    img[y0:y1, x0:x1] = pan

    y0, y1, x0, x1 = region(R_DARK)
    h, w = y1 - y0, x1 - x0
    b = np.full((h, w), 46.0, np.float32) + noise(h, w, 8, 7) + noise(h, w, 2, 4)
    img[y0:y1, x0:x1] = np.stack([b, b * 0.98, b * 0.95], -1)

    y0, y1, x0, x1 = region(R_RUST)
    h, w = y1 - y0, x1 - x0
    b = np.full((h, w), 64.0, np.float32) + noise(h, w, 6, 9) + noise(h, w, 2, 5)
    img[y0:y1, x0:x1] = np.stack([b * 1.12, b * 0.92, b * 0.78], -1)

    y0, y1, x0, x1 = region(R_TANK)
    h, w = y1 - y0, x1 - x0
    b = np.full((h, w), 70.0, np.float32) + noise(h, w, 10, 5)
    yy = np.arange(h)[:, None] / h
    b -= 22 * ((np.abs(yy - 0.3) < 0.05) | (np.abs(yy - 0.7) < 0.05))   # the two straps
    img[y0:y1, x0:x1] = np.stack([b, b, b * 0.98], -1)

    # VEHICLE-ART-14: the cover's grime: a slightly warm, mottled dark grey (road dirt over underseal), no structure
    # (it is mapped planar over every downward face of the shell: arches, sills, bumpers, the overhangs)
    y0, y1, x0, x1 = region(R_GRIME)
    h, w = y1 - y0, x1 - x0
    b = np.full((h, w), 50.0, np.float32) + noise(h, w, 12, 7) + noise(h, w, 3, 5)
    img[y0:y1, x0:x1] = np.stack([b * 1.04, b * 1.0, b * 0.93], -1)
    a = np.full((S, S, 1), 255, np.float32)
    return Image.fromarray(np.concatenate([np.clip(img, 0, 255), a], -1).astype(np.uint8), "RGBA")


# ------------------------------------------------------------------------------------------------------------------
# Geometry (model units: the body spans z -0.5..0.5; +y up, +z nose). Triangles counter-clockwise seen from the
# side their normal points to (the .mesh convention).
# ------------------------------------------------------------------------------------------------------------------
class Acc:
    def __init__(self):
        self.v, self.f = [], []

    def add(self, P, N, UV, F):
        base = sum(len(x) for x in self.v)
        P = np.asarray(P, np.float64); N = np.asarray(N, np.float64); F = np.asarray(F, np.int64)
        # orient every triangle so its winding agrees with its vertex normals
        c = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
        flip = (c * N[F].mean(1)).sum(1) < 0
        F[flip] = F[flip][:, ::-1]
        self.v.append(np.concatenate([P, N, np.asarray(UV, np.float64)], 1))
        self.f.append(F + base)

    def arrays(self):
        return np.concatenate(self.v).astype(np.float32), np.concatenate(self.f).astype(np.uint32).ravel()


def _uv(region, s, t):
    return np.stack([region[0] + (region[2] - region[0]) * np.clip(s, 0, 1), region[1] + (region[3] - region[1]) * np.clip(t, 0, 1)], -1)


def box(acc, lo, hi, region, bevel=0.15):
    """an axis-aligned box with chamfered vertical edges (flat faces: a cast or pressed part)"""
    lo = np.asarray(lo, float); hi = np.asarray(hi, float)
    c = (lo + hi) / 2; e = (hi - lo) / 2
    k = bevel * min(e[0], e[2])
    # an octagon in plan (x, z), extruded in y
    oc = np.array([[e[0] - k, e[2]], [e[0], e[2] - k], [e[0], -e[2] + k], [e[0] - k, -e[2]],
                   [-e[0] + k, -e[2]], [-e[0], -e[2] + k], [-e[0], e[2] - k], [-e[0] + k, e[2]]])
    n = len(oc)
    for i in range(n):                                    # sides
        a, b = oc[i], oc[(i + 1) % n]
        nn = np.array([b[1] - a[1], 0, -(b[0] - a[0])])
        if np.linalg.norm(nn) < 1e-9:
            continue
        nn /= np.linalg.norm(nn)
        if np.dot(nn, [(a[0] + b[0]) / 2, 0, (a[1] + b[1]) / 2]) < 0: nn = -nn
        P = [[c[0] + a[0], lo[1], c[2] + a[1]], [c[0] + b[0], lo[1], c[2] + b[1]], [c[0] + b[0], hi[1], c[2] + b[1]], [c[0] + a[0], hi[1], c[2] + a[1]]]
        UV = _uv(region, np.array([i, i + 1, i + 1, i]) / n, np.array([0, 0, 1, 1]) * 0.6)
        acc.add(P, [nn] * 4, UV, [[0, 1, 2], [0, 2, 3]])
    for y, sgn in ((lo[1], -1), (hi[1], 1)):              # bottom (and top: seen when the car lies on its roof? no:
        P = [[c[0] + p[0], y, c[2] + p[1]] for p in oc]  # the top is inside the body; kept for a closed solid)
        UV = _uv(region, (oc[:, 0] / (2 * e[0]) + 0.5), (oc[:, 1] / (2 * e[2]) + 0.5))
        acc.add(P, [[0, sgn, 0]] * n, UV, [[0, i, i + 1] for i in range(1, n - 1)])


def tube(acc, a, b, r, region, seg=10, caps=True):
    """a cylinder from a to b (smooth normals)"""
    a = np.asarray(a, float); b = np.asarray(b, float)
    ax = b - a; L = np.linalg.norm(ax); ax /= L
    t1 = np.cross(ax, [0, 1, 0] if abs(ax[1]) < 0.9 else [1, 0, 0]); t1 /= np.linalg.norm(t1)
    t2 = np.cross(ax, t1)
    ang = np.linspace(0, 2 * math.pi, seg + 1)
    ring = np.array([math.cos(q) * t1 + math.sin(q) * t2 for q in ang])
    P = np.concatenate([a + r * ring, b + r * ring]); N = np.concatenate([ring, ring])
    UV = np.concatenate([_uv(region, ang / (2 * math.pi), np.zeros_like(ang)), _uv(region, ang / (2 * math.pi), np.ones_like(ang) * min(1.0, L / (8 * r)))])
    m = seg + 1
    F = [[i, i + 1, m + i + 1] for i in range(seg)] + [[i, m + i + 1, m + i] for i in range(seg)]
    acc.add(P, N, UV, F)
    if caps:
        for o, s in ((a, -1), (b, 1)):
            Pc = np.concatenate([[o], o + r * ring[:-1]]); Nc = [ax * s] * (seg + 1)
            UVc = _uv(region, 0.5 + 0.4 * np.concatenate([[0], np.cos(ang[:-1])]), 0.5 + 0.4 * np.concatenate([[0], np.sin(ang[:-1])]))
            acc.add(Pc, Nc, UVc, [[0, 1 + i, 1 + (i + 1) % seg] for i in range(seg)])


def blob(acc, c, rx, ry, rz, region, nu=12, nv=7):
    """an ellipsoid (the differential's housing)"""
    c = np.asarray(c, float)
    us = np.linspace(0, 2 * math.pi, nu + 1); vs = np.linspace(-math.pi / 2, math.pi / 2, nv + 1)
    U, V = np.meshgrid(us, vs, indexing="ij")
    d = np.stack([np.cos(V) * np.cos(U), np.sin(V), np.cos(V) * np.sin(U)], -1).reshape(-1, 3)
    P = c + d * [rx, ry, rz]
    N = d / np.array([rx, ry, rz]); N /= np.linalg.norm(N, axis=1, keepdims=True)
    UV = _uv(region, (U / (2 * math.pi)).ravel(), ((V + math.pi / 2) / math.pi).ravel())
    b = nv + 1
    F = []
    for i in range(nu):
        for j in range(nv):
            k = i * b + j
            F += [[k, k + b, k + b + 1], [k, k + b + 1, k + 1]]
    acc.add(P, N, UV, F)


# ------------------------------------------------------------------------------------------------------------------
def measure(m, name=""):
    """the body's floor and wheels, from the shipped mesh"""
    W = mesh_io.world(m)
    P = np.concatenate([w[2] for w in W]); N = np.concatenate([w[3] for w in W])
    lo, hi = P.min(0), P.max(0)
    halfw = max(abs(lo[0]), abs(hi[0]))
    zmin, zmax = lo[2], hi[2]
    marks = [(n["name"], np.asarray(n["t"], float)) for n in m["nodes"] if n["name"].startswith("wheel_") and n["mesh"] < 0]
    wheels = []
    if marks:
        for _, c in marks:
            r = max(0.03, c[1])
            wheels.append(dict(x=c[0], z=c[2], r=r, rr=1.06 * r, y=c[1], xin=max(0.25 * halfw, abs(c[0]) - 1.2 * r)))
        axles = sorted({round(w["z"], 4) for w in wheels}, reverse=True)
    else:
        # the renderer's shell guess: road contact near each end; radius up to 0.13 (taken at its maximum)
        miny = lo[1]
        low = P[P[:, 1] < miny + 0.015]
        axles = []
        for sgn in (1, -1):
            q = low[(sgn * low[:, 2]) > 0.08]
            axles.append(float(q[:, 2].mean()) if len(q) >= 3 else sgn * 0.3)
        # the radius: the renderer's own (its 'wheel split of' log line, car units = model units x the body's
        # length in blocks; underpan_wheels.json), else its maximum 0.13 (+4 %)
        r = 0.135
        known = WHEELS.get(name)
        if known and known["shell"] and abs(known["zf"] - known["zr"]) > 0.05:
            lb = (known["zf"] - known["zr"]) / max(axles[0] - axles[1], 1e-3)
            if 0.6 < lb < 3.5:
                r = 1.04 * known["r"] / lb
        for z in axles:
            wheels.append(dict(z=z, r=r, rr=0.98 * r, y=miny + r, xin=0.35 * halfw))
    zf, zr = max(axles), min(axles)
    # the floor: per cell of a grid over the band between the axles, the lowest point of the body (any normal: the
    # shells' normals are not reliable); the median of the centre cells, or of the sill cells if that is lower (the
    # kits with separate wings have no floor panel, only sills: 008, 040)
    def cells(xa, xb):
        sel = (np.abs(P[:, 0]) >= xa * halfw) & (np.abs(P[:, 0]) < xb * halfw) & (P[:, 2] < zf - 0.06) & (P[:, 2] > zr + 0.06)
        Q = P[sel]
        if len(Q) < 20:
            return None
        ix = np.clip(((np.abs(Q[:, 0]) / halfw - xa) / (xb - xa) * 4).astype(int), 0, 3) * np.sign(Q[:, 0]).astype(int)
        iz = np.clip(((Q[:, 2] - zr) / max(zf - zr, 1e-3) * 16).astype(int), 0, 15)
        c = {}
        for key, yv in zip(ix * 16 + iz, Q[:, 1]):
            c[key] = min(c.get(key, 9.0), yv)
        return float(np.percentile(list(c.values()), 15))
    # (15th percentile of the cells: the shells' floors are not flat). Never more than 0.02 under the side band's
    # bottom (0.75-1.0 x half width): lower, the pan would hang in view under the sills from the side
    centre, sill, side = cells(0.0, 0.5), cells(0.5, 0.92), cells(0.75, 1.0)
    cands = [v for v in (centre, sill) if v is not None]
    floor = min(cands) if cands else 0.06
    if side is not None and side - 0.02 < floor + 0.06:   # (a side band far above the floor is no skirt: 023's)
        floor = max(floor, side - 0.02)
    # the body's length at floor level (where its underside is within 4 cm of the floor)
    near = (np.abs(P[:, 0]) < 0.8 * halfw) & (P[:, 1] < floor + 0.04)
    z0 = float(np.percentile(P[near, 2], 1)) if near.sum() > 20 else zr - 0.12
    z1 = float(np.percentile(P[near, 2], 99)) if near.sum() > 20 else zf + 0.12
    # VEHICLE-ART-14: the body's half width at floor level along z (the pan follows it out to the sills): per bin,
    # the widest point within 6 cm over the floor; empty bins take their neighbours'
    nb = 48
    zb = np.linspace(zmin, zmax, nb + 1)
    lowp = P[P[:, 1] < floor + 0.06]
    ob = np.zeros(nb)
    for i in range(nb):
        q = lowp[(lowp[:, 2] >= zb[i]) & (lowp[:, 2] < zb[i + 1])]
        ob[i] = np.percentile(np.abs(q[:, 0]), 98) if len(q) >= 4 else np.nan
    ok = ~np.isnan(ob)
    ob = np.interp(np.arange(nb), np.flatnonzero(ok), ob[ok]) if ok.any() else np.full(nb, 0.8 * halfw)
    return dict(halfw=float(halfw), floor=floor, zf=zf, zr=zr, z0=max(z0, zmin + 0.02), z1=min(z1, zmax - 0.02),
                follow=name[:3] in FOLLOW,
                wheels=wheels, marker=bool(marks), lo=lo, hi=hi,
                outline=(0.5 * (zb[1:] + zb[:-1]), ob))


def build(meas):
    acc = Acc()
    hw, zf, zr = meas["halfw"], meas["zf"], meas["zr"]
    min_r = min(w["r"] for w in meas["wheels"])
    # the pan sits 3 mm under the floor, never lower than 0.03 (~15 cm)
    # (VEHICLE-ART-14: 6 mm, was 3: the cover's copies of the body's own floor faces sit 1.2 mm under them, and a
    # gap of under 2 mm z-fought with the pan as dark combs; 4.8 mm is more than the 3 mm body-to-pan gap that never did)
    # The kit bodies (marker wheels) keep 3 mm: their authored chassis boxes sit just under the floor, and parts
    # lowered with a 6 mm pan met them as combs (out/va14_up_a4 004 rear axle); their cover skips floor-level faces.
    y = max(meas["floor"] - (0.003 if meas["marker"] else 0.006), 0.030)
    z0, z1 = meas["z0"], meas["z1"]
    if meas.get("follow"):
        z0, z1 = z0 + 0.03, z1 - 0.03   # the egg ends: the body's own underside closes them (VEHICLE-ART-24)
    # scale: a part's size in model units per metre (the body's width is ~2.1 m on every car)
    k = (2 * hw) / 2.1

    def well(z):
        """1 inside a wheel well's z span, 0 clear of it"""
        out = 0.0
        for w in meas["wheels"]:
            dz = abs(z - w["z"])
            span = w["rr"] + 0.02
            out = max(out, float(np.clip((span + 0.03 - dz) / 0.03, 0, 1)))
        return out
    wide, narrow = 0.80 * hw, 0.20 * hw
    # the pan: a (x, z) grid, half width narrowing at the wheel wells.
    # VEHICLE-ART-14: between and beyond the wells it reaches the sills (0.96 x the body's own half width at floor
    # level, never past 0.97 x the half width), not a fixed 0.80: the shell's underside no longer shows beside it
    oz, ob = meas["outline"]
    nz = 64; nx = 12
    zs = np.linspace(z0, z1, nz + 1)
    wides = np.clip(0.96 * np.interp(zs, oz, ob), wide, 0.95 * hw)
    if meas["marker"] and meas.get("follow"):
        wides = np.clip(0.92 * np.interp(zs, oz, ob), narrow, wide)
    elif meas["marker"]:
        # the kit bodies keep ART-13's pan (0.80, curled lip): wider, it met their floor structure as sawteeth
        # (out/va14_up_a5..a9 004); their own sills are authored paint, not projected texels
        wides = np.full_like(zs, wide)
    halfs = np.array([wd + (narrow - wd) * well(z) for wd, z in zip(wides, zs)])
    P, N, UV = [], [], []
    for i, z in enumerate(zs):
        for j in range(nx + 1):
            s = j / nx * 2 - 1
            x = s * halfs[i]
            # (VEHICLE-ART-14: flat, no curled lip: out at the sills a lip rising 2 cm crossed the body's own floor
            # panels 3 mm above the pan at a grazing angle and read as sawteeth, out/va14_up_a6 004)
            if meas["marker"]:
                lip = 0.02 * k * max(0.0, (abs(s) - 0.85) / 0.15) ** 2
                endlip = 0.02 * k * max(0.0, 1 - min(z - z0, z1 - z) / (0.03)) if min(z - z0, z1 - z) < 0.03 else 0.0
            else:
                lip = 0.0
                endlip = 0.0
            P.append([x, y + lip + endlip, z]); N.append([0, -1, 0])
            # planar UV: across = the pan's own half width so the tunnel stays at the centre, along = the body
            UV.append([R_PAN[0] + (R_PAN[2] - R_PAN[0]) * np.clip(0.5 + x / (2 * wides[i]), 0, 1), R_PAN[1] + (R_PAN[3] - R_PAN[1]) * (z1 - z) / (z1 - z0)])
    F = []
    for i in range(nz):
        for j in range(nx):
            a = i * (nx + 1) + j; b = a + nx + 1
            F += [[a, b, b + 1], [a, b + 1, a + 1]]
    acc.add(P, N, UV, F)

    def under(h):
        # hung h metres under the pan, squeezed on a low car so nothing reaches the road
        return y - min(h * k, 0.6 * (y - 0.008) * h / 0.16)

    # frame rails, only between the wells (where the pan is wide); not on the kit bodies: their authored rails sit
    # at the same height (004: 0.8 mm apart), a z-fight that the darker atlas made read as sawteeth (out/va14_up_a11)
    for sx in (() if meas["marker"] else (-1, 1)):
        x = sx * 0.50 * hw
        za, zb = zr + max(w["rr"] for w in meas["wheels"]) + 0.05, zf - max(w["rr"] for w in meas["wheels"]) - 0.05
        if zb - za > 0.06:
            box(acc, (x - 0.035 * k, under(0.09), za), (x + 0.035 * k, y + 0.001, zb), R_DARK, bevel=0.0)
    xc = narrow - 0.01                                    # the widest a part may be near an axle
    # engine sump and gearbox behind the front axle line
    sump_w = min(0.24 * k, xc)
    box(acc, (-sump_w, under(0.13), zf - 0.30 * k), (sump_w, y + 0.001, zf + 0.20 * k), R_DARK)
    gb_w = min(0.13 * k, xc)
    box(acc, (-gb_w, under(0.10), zf - 0.95 * k), (gb_w, y + 0.001, zf - 0.30 * k), R_DARK)
    # front cross-member under the sump, across to the wells
    box(acc, (-xc, under(0.16), zf - 0.06 * k), (xc, under(0.11), zf + 0.04 * k), R_DARK, bevel=0.0)
    # propshaft to the rear axle
    ya = under(0.09)
    tube(acc, (0, under(0.06), zf - 0.95 * k), (0, ya, zr + 0.12 * k), 0.035 * k, R_DARK, seg=8)
    # rear axle tube (inside the wells' inboard limit) and the differential
    tube(acc, (-xc, ya, zr), (xc, ya, zr), 0.045 * k, R_DARK, seg=10)
    blob(acc, (0, ya, zr + 0.03 * k), 0.16 * k, 0.12 * k, 0.15 * k, R_DARK)
    # VEHICLE-ART-14: suspension: a lower arm each side at every axle, from beside the tunnel out into the well
    # (one face spans the whole length, so its inboard end keeps every face off the wheel split), and a coil/damper
    # stub over it; the rear also gets a trailing link forward to the floor
    # (shells only: the kit bodies carry authored chassis boxes at the axles, and arms through them z-fought as combs)
    for w in ([] if meas["marker"] else meas["wheels"]):
        sx = 1 if w.get("x", 1) >= 0 else -1
        for side in ((-1, 1) if not meas["marker"] else (sx,)):
            xa, xb = side * 0.16 * hw, side * min(0.80 * hw, w["xin"] + 0.6 * w["r"])
            ya = under(0.10)
            tube(acc, (xa, ya, w["z"] - 0.10 * k), (xb, ya, w["z"]), 0.032 * k, R_DARK, seg=8, caps=False)
            tube(acc, (xa, ya, w["z"] + 0.10 * k), (xb, ya, w["z"]), 0.032 * k, R_DARK, seg=8, caps=False)
            if w["z"] < 0:
                tube(acc, (xa * 0.9, under(0.05), w["z"] + 0.55 * k), (xb * 0.95, ya, w["z"]), 0.028 * k, R_DARK, seg=8, caps=False)
    # exhaust: from the engine down the right of the tunnel, a silencer ahead of the rear axle, a tail past it
    xe = min(0.32 * k, 0.55 * hw)
    ye = under(0.06)
    zs0, zs1 = zr + 0.45 * k + 0.12, zr + 0.45 * k + 0.12 + 0.75 * k
    zs1 = min(zs1, zf - 1.0 * k)
    path = [(0.10 * k, ye, zf - 0.35 * k), (xe, ye, zf - 0.70 * k)]
    if zs1 - zs0 > 0.1 * k:
        path += [(xe, ye, zs1)]
        tube(acc, path[0], path[1], 0.03 * k, R_RUST, seg=8)
        tube(acc, path[1], path[2], 0.03 * k, R_RUST, seg=8, caps=False)
        tube(acc, (xe, under(0.07), zs1), (xe, under(0.07), zs0), 0.10 * k, R_RUST, seg=12)   # the silencer
        tail0 = (min(xe, xc), ye, zs0)
    else:
        tube(acc, path[0], path[1], 0.03 * k, R_RUST, seg=8)
        tail0 = (min(xe, xc), ye, zf - 0.70 * k)
    tail1 = (min(xe, xc), ye, z0 + 0.04)
    tube(acc, tail0, tail1, 0.028 * k, R_RUST, seg=8)
    # fuel tank behind the rear axle (a car's), on the left
    tz1 = zr - max(w["rr"] for w in meas["wheels"]) - 0.02
    tz0 = max(z0 + 0.03, tz1 - 0.45 * k)
    if tz1 - tz0 > 0.06:
        box(acc, (-0.55 * hw, under(0.11), tz0), (0.30 * hw * 0 + 0.10 * hw, y + 0.001, tz1), R_TANK)
    else:
        # no overhang: the tank goes ahead of the axle, left of the tunnel
        za = zr + max(w["rr"] for w in meas["wheels"]) + 0.03
        box(acc, (-0.55 * hw, under(0.11), za), (-0.14 * hw, y + 0.001, za + 0.40 * k), R_TANK)
    return acc.arrays(), y, (zs, halfs)


# texture names of the body's own parts the cover leaves alone (tyres and wheels, glass, the cabin, the kit's own
# grey underbody and wells)
COVER_SKIP = ("_glass", "underbody", "underpan", "tyre", "tire", "wheel", "whitewall", "hub", "rim", "seat", "interior",
              "dash", "cabin", "lamp", "lens")


def cover(m, meas, y_pan, pan_rows, offset=0.0012, down=0.72, well_r=2.0):
    """VEHICLE-ART-14: every downward-facing face of the body's lower half, copied a hair outside itself and mapped
    to the grime region, so the image-to-3D shells' projected texels (black voids, sprite smears) no longer show
    round the pan: the wheel arches, the sills, the bumpers' undersides and the overhangs past the pan. Faces the pan
    already hides, and faces near a wheel disc (tyres; the renderer's wheel split must take none of the cover), are
    left out."""
    zs, halfs = pan_rows
    hw = meas["halfw"]
    top = meas["lo"][1] + 0.5 * (meas["hi"][1] - meas["lo"][1])
    zmin, zmax = meas["lo"][2], meas["hi"][2]
    Ps, Ns, UVs = [], [], []
    for (n, me, P, N, UV, F) in mesh_io.world(m):
        t = me["tex"].lower()
        if n["name"].startswith("wheel") or any(k in t for k in COVER_SKIP):
            continue
        if meas["marker"] and "paint_" not in t:
            # a kit body's chassis parts (bars, frame, leaf channels, chrome) are authored: only its painted
            # panels' undersides get grime (half-covered bar strips read as sawteeth, out/va14_up_a5 004)
            continue
        A, B, C = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
        g = np.cross(B - A, C - A)
        L = np.linalg.norm(g, axis=1)
        okL = L > 1e-10
        g[okL] /= L[okL, None]
        tri = P[F]                                            # (k, 3, 3)
        sel = okL & (g[:, 1] < -down) & (tri[..., 1].max(1) < top)
        if not meas["marker"]:
            # a shell's wheel well is a noisy cavity: half its faces lean sideways and kept their black texels
            # between the covered ones (shards). Inside the body's flank (not the arch lip) round each wheel,
            # every face that leans down at all is covered
            tx, ty, tz = np.abs(tri[..., 0]).mean(1), tri[..., 1].mean(1), tri[..., 2].mean(1)
            for w in meas["wheels"]:
                dd = (ty - w["y"]) ** 2 + (tz - w["z"]) ** 2
                # (0.72 x, -0.35: wider or flatter took flank paint by the arches on narrow shells, out/va14_up_a7 002)
                well = (dd < (well_r * w["r"]) ** 2) & (tx < 0.72 * hw) & (tx > 0.30 * hw)
                sel |= okL & well & (g[:, 1] < -0.35)
        # hidden behind the pan already (inside its footprint and close over it)
        zc = tri[..., 2]
        ph = np.interp(zc, zs, halfs)
        inside = ((np.abs(tri[..., 0]) < ph - 0.004) & (zc > zs[0]) & (zc < zs[-1]) & (tri[..., 1] < y_pan + 0.05)).all(1)
        sel &= ~inside
        if meas["marker"]:
            sel &= tri[..., 1].min(1) > y_pan + 0.012
        for w in meas["wheels"]:
            dy = tri[..., 1] - w["y"]; dz = tri[..., 2] - w["z"]
            # the tyre: the face's centre inside the disc (a hair over it) and outboard; the arch round it is covered
            cy, cz, cx = dy.mean(1), dz.mean(1), np.abs(tri[..., 0]).mean(1)
            near = ((cy * cy + cz * cz) < (1.03 * w["rr"]) ** 2) & (cx > 0.75 * w["xin"])
            if meas["marker"]:
                # the kit bodies have authored grey wells (_underbody): their painted arch lips face down too, and a
                # grime copy of them reads as dark teeth round the arch from a low eye
                # (and the well drums: strips of them passed the facing test in turn and read as combs)
                near |= np.abs(cz) < 1.8 * w["rr"]
            sel &= ~near
        if not sel.any():
            continue
        q = tri[sel] + g[sel][:, None, :] * offset
        Ps.append(q.reshape(-1, 3))
        Ns.append(np.repeat(g[sel], 3, axis=0))
        u = np.clip(q[..., 0] / (2 * hw) + 0.5, 0, 1).reshape(-1)
        v = np.clip((zmax - q[..., 2]) / max(zmax - zmin, 1e-6), 0, 1).reshape(-1)
        UVs.append(_uv(R_GRIME, u, v))
    if not Ps:
        return None
    P = np.concatenate(Ps); N = np.concatenate(Ns); UV = np.concatenate(UVs)
    F = np.arange(len(P)).reshape(-1, 3)
    return P, N, UV, F


def wheel_hits(V, idx, meas):
    """faces of the pan that the renderer's wheel split would take (must be 0)"""
    P = V[:, :3]; F = idx.reshape(-1, 3)
    hits = 0
    for w in meas["wheels"]:
        q = P[F]
        dy = q[..., 1] - w["y"]; dz = q[..., 2] - w["z"]
        inside = ((dy * dy + dz * dz) < w["rr"] ** 2).all(1)
        out = (np.abs(q[..., 0]) > w["xin"]).all(1)
        hits += int((inside & out).sum())
    return hits


def apply(src_dir, dst_dir, name, check=False):
    import import_assets
    m = mesh_io.read(os.path.join(src_dir, name + ".mesh"))
    if any(n["name"] == NODE for n in m["nodes"]):
        # re-run: drop the old pan first
        old = [n["mesh"] for n in m["nodes"] if n["name"] == NODE][0]
        m["nodes"] = [n for n in m["nodes"] if n["name"] != NODE]
        for n in m["nodes"]:
            if n["mesh"] > old: n["mesh"] -= 1
        del m["meshes"][old]
    meas = measure(m, name)
    (V, idx), y, rows = build(meas)
    # the kit bodies (marker wheels) get no cover: their undersides are authored, and every cover rule tried
    # (a0..a8) left sawteeth on some kit part; only the darker atlas changes for them
    cv = None if meas["marker"] else cover(m, meas, y, rows)
    ncov = 0
    if cv is not None:
        P, N, UV, F = cv
        ncov = len(F)
        V = np.concatenate([V, np.concatenate([P, N, UV], 1).astype(np.float32)])
        idx = np.concatenate([idx, (F.ravel() + (len(V) - len(P))).astype(np.uint32)])
    hits = wheel_hits(V, idx, meas)
    info = f"{name}: floor {meas['floor']:.3f} pan y {y:.3f} z {meas['z0']:.2f}..{meas['z1']:.2f} axles {meas['zf']:.2f}/{meas['zr']:.2f} " \
           f"({'markers' if meas['marker'] else 'shell'}) half width {meas['halfw']:.3f}: {len(idx) // 3} triangles ({ncov} cover), wheel-split hits {hits}"
    print(info)
    if hits:
        raise SystemExit(f"{name}: the pan would be taken by the wheel split")
    if check:
        return
    tex = f"{name}_underpan.tga"
    m["meshes"].append(dict(tex=tex, skin=-1, v=V, idx=idx))
    m["nodes"].append(dict(name=NODE, parent=-1, t=(0.0, 0.0, 0.0), r=(0.0, 0.0, 0.0, 1.0), s=(1.0, 1.0, 1.0), mesh=len(m["meshes"]) - 1))
    out = os.path.join(dst_dir, name + ".mesh")
    if os.path.exists(out): os.unlink(out)
    mesh_io.write(m, out)
    t = os.path.join(dst_dir, tex)
    if os.path.exists(t): os.unlink(t)
    import_assets.write_tga(texture(), t)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src, dst = args[0], args[1]
    check = "--check" in sys.argv
    if "--all" in sys.argv:
        names = sorted(f[:-5] for f in os.listdir(src) if f.endswith(".mesh") and f[:3].isdigit() and f[:3] not in SKIP)
    else:
        names = sorted(f[:-5] for f in os.listdir(src) if f.endswith(".mesh") and f[:3] in args[2:])
    os.makedirs(dst, exist_ok=True)
    for n in names:
        apply(src, dst, n, check)


if __name__ == "__main__":
    main()
