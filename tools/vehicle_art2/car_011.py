#!/usr/bin/env python3
"""011 Bus (VEHICLE-ART-23, qav56 "ragged dark-blue awning, black quad holes on the roof, smeared sides"): the
catalog's 1950s GM 'old look' transit bus read from the GTA2 sprite nose down (assets-src/cars/sprites_x4/
011_bus_default.png, 52 x 128 px, body 40 x 127 px): a long single-deck body with well-rounded roof edges and
rounded corners in plan; a cream body with the sprite's brown livery (the roof's centre strip carrying three
escape hatches and round vents, the letterboard band over the windows with marker lamps along it, a belt stripe
under the windows with a chrome moulding); a glazed window band with pillars and the cabin (seat rows, a liner)
behind it; a flat front with a split windscreen, a destination box over it, sealed-beam lamps, a small grille and
a black bumper (the sprite's dark curved nose bar and pale plate); passenger doors (front and centre) on the -x
side, the driver's window on the +x side; a flat rear with a small back light, the engine louvres, tail lamps and
the sprite's amber band at the roof's rear; single front tyres, twin rear tyres.

The bus is a livery model (identity.cpp Livery: its colours are its own art, the lit-livery gain uniform), so the
body is authored in the default sprite's colours, which is the remap traffic draws for ~80 % of the buses seen
(identity lines: paint 115,88,69 palettes 29-31); the remaps' blue / green / red / teal strips still show brown.
The body and its stripes are paint_* materials (the livery gain applies to them as to the shell's paint half).
Metres, +z nose, 1 block = 5 m (catalog body 0.625 x 1.984 blocks: 3.13 x 9.92 m)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "011_bus"
CREAM = (232.0, 222.0, 212.0)
BROWN = (120.0, 84.0, 61.0)
PAINT = CREAM
SPRITE = None
LEN = 1.984 * 5.0                 # 9.92 m bumper to bumper
ZBN, ZBT = 4.96, -4.96            # bumper faces
ZN, ZT = 4.82, -4.84              # body faces
HW = 1.52
RCF, RCT = 0.42, 0.50             # plan corner radii, front / tail
BOT, BELT, WTOP, TOP = 0.52, 1.74, 2.74, 3.26
CROWN = 0.07
R_LO, R_HI = 0.10, 0.40
ZF, ZR = 2.80, -2.34              # axles
R_TYRE, W_TYRE, W_REAR = 0.57, 0.36, 0.64
X_WHEEL, X_REAR = 1.20, 1.10
R_ARCH = 0.70
VB = (0.0, 0.12, 0.20, 0.72, 0.86, 1.0)

# passenger doors on the -x side (front, centre); pillar stations along the window band
DOOR_F = (ZN - 1.26, ZN - 0.46)
DOOR_C = (ZR + 0.95, ZR + 2.05)
WIN_Z0, WIN_Z1 = ZT + 0.62, ZN - 0.32
PILLAR = 0.13


def section(v, hw, bot, top):
    """rounded-rectangle half section, v 0 bottom centre -> 1 roof centre (VEHICLE-ART-10's 004 recipe)"""
    v = np.asarray(v, float)
    hw = np.broadcast_to(hw, v.shape).astype(float); bot = np.broadcast_to(bot, v.shape).astype(float)
    top = np.broadcast_to(top, v.shape).astype(float)
    t0 = np.clip(v / VB[1], 0, 1)
    t1 = np.clip((v - VB[1]) / (VB[2] - VB[1]), 0, 1)
    t2 = np.clip((v - VB[2]) / (VB[3] - VB[2]), 0, 1)
    t3 = np.clip((v - VB[3]) / (VB[4] - VB[3]), 0, 1)
    t4 = np.clip((v - VB[4]) / (VB[5] - VB[4]), 0, 1)
    side_lo = bot + R_LO; side_hi = top - R_HI
    a1 = -math.pi / 2 + t1 * math.pi / 2
    a3 = t3 * math.pi / 2
    # a slight tumblehome above the belt (the old look's sides lean in to the roof)
    ys = side_lo + t2 * (side_hi - side_lo)
    tb = 0.05 * np.clip((ys - BELT) / (side_hi - BELT), 0, 1) ** 1.3
    hwt = hw - 0.05
    xs = [t0 * (hw - R_LO), hw - R_LO + R_LO * np.cos(a1), hw - tb, hwt - R_HI + R_HI * np.cos(a3), (hwt - R_HI) * (1 - t4)]
    ys_ = [bot + 0 * v, side_lo + R_LO * np.sin(a1), ys, side_hi + R_HI * np.sin(a3), top + CROWN * (1 - (1 - t4) ** 2)]
    seg = np.select([v < VB[1], v < VB[2], v < VB[3], v < VB[4]], [0, 1, 2, 3], 4)
    return np.choose(seg, xs), np.choose(seg, ys_)


def arch_at(z, zc, r=R_ARCH, rt=R_TYRE):
    dz = np.abs(np.asarray(z, float) - zc)
    y = rt + 0.02 + np.sqrt(np.clip(r ** 2 - np.minimum(dz, r) ** 2, 0, None))
    return np.where(dz < r, y, 0)


def hw_at(z):
    """plan: full width with quarter-round corners at the nose and the tail"""
    z = np.asarray(z, float)
    df = np.clip(z - (ZN - RCF), 0, RCF); dt = np.clip((ZT + RCT) - z, 0, RCT)
    return np.where(df > 0, HW - RCF + np.sqrt(np.clip(RCF ** 2 - df ** 2, 0, None)),
                    np.where(dt > 0, HW - RCT + np.sqrt(np.clip(RCT ** 2 - dt ** 2, 0, None)), HW))


def body(u, v, inset=0.0):
    z = np.asarray(u, float)
    bot = np.maximum(BOT, np.maximum(arch_at(z, ZF), arch_at(z, ZR)))
    x, y = section(v, hw_at(z) - inset, bot + inset, TOP - inset)
    return x, y, z


def end_outline(zc):
    """the body's section at an end face: x half-width as a function of height"""
    vv = np.linspace(0, 1, 400)
    x, y = section(vv, float(hw_at(np.array([zc]))[0]), BOT, TOP)
    order = np.argsort(y, kind="stable")
    return y[order], x[order]


def build():
    car = Car(NAME)

    # ---- the body loft, built per side (the doors are on -x only) --------------------------------------
    def win_sdf(side):
        def f(u, v):
            x, y, z = body(u, v)
            z = np.asarray(z, float); v = np.asarray(v, float)
            band = np.maximum.reduce([BELT + 0.04 - y, y - WTOP, VB[2] - v, v - VB[3] - 0.02,
                                      WIN_Z0 - z, z - WIN_Z1])
            # pillars every bay (the sprite's window grid: 8 bays a side)
            bay = (WIN_Z1 - WIN_Z0) / 8.0
            ph = np.abs(((z - WIN_Z0) / bay) % 1.0 - 0.0)
            ph = np.minimum(ph, 1.0 - ph) * bay
            band = np.maximum(band, PILLAR / 2 - ph)
            if side < 0:
                for d0, d1 in (DOOR_F, DOOR_C):
                    mid, half = 0.5 * (d0 + d1), 0.5 * (d1 - d0)
                    # no window bay across a door: the door's own glass instead (two leaves, a centre seam, a rail)
                    band = np.maximum(band, half + 0.10 - np.abs(z - mid))
                    leaf = np.maximum.reduce([0.66 - y, y - WTOP, np.abs(z - mid) - (half - 0.06),
                                              0.03 - np.abs(z - mid), 0.05 - np.abs(y - 1.30)])
                    band = np.minimum(band, leaf)
            return band
        return f

    def door_frame(side):
        def f(u, v):
            x, y, z = body(u, v)
            z = np.asarray(z, float)
            d = None
            for d0, d1 in (DOOR_F, DOOR_C):
                s = np.maximum.reduce([0.60 - y, y - (WTOP + 0.04), d0 - z, z - d1])
                d = s if d is None else np.minimum(d, s)
            return d if side < 0 else d * 0 + 1.0
        return f

    def stripes(u, v):
        x, y, z = body(u, v)
        v = np.asarray(v, float)
        letter = np.maximum(np.abs(y - (WTOP + 0.17)) - 0.13, VB[2] - v)
        belt = np.maximum(np.abs(y - (BELT - 0.22)) - 0.11, VB[2] - v)
        roof = np.maximum(np.abs(x) - 0.46, VB[4] - v)
        return np.minimum.reduce([letter, belt, roof])

    def moulding(u, v):
        x, y, z = body(u, v)
        return np.maximum(np.abs(y - (BELT - 0.05)) - 0.025, VB[2] - np.asarray(v, float))

    under = lambda u, v: np.asarray(v) - VB[1] * 0.98
    ukeys = [ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, WIN_Z0, WIN_Z1, ZN - RCF, ZT + RCT]
    ukeys += list(np.linspace(WIN_Z0, WIN_Z1, 9))
    vkeys = list(VB)
    for side in (1, -1):
        g = win_sdf(side)
        seal = lambda u, v, g=g: g(u, v) - 0.035
        regions = [("glass", g), ("seal", seal)]
        if side < 0:
            df = door_frame(side)
            regions += [("seal", sdf_band(df, 0.018))]
            ukeys_s = ukeys + [d for p in (DOOR_F, DOOR_C) for d in p]
        else:
            ukeys_s = ukeys
        regions += [("chrome", moulding), ("paint_stripe", stripes), ("underbody", under)]
        fn = body if side > 0 else (lambda u, v: (lambda p: (-p[0], p[1], p[2]))(body(u, v)))
        if side > 0:
            car.surface(fn, ZT, ZN, 0.0, 1.0, 120, 48, regions=regions, default="paint_body",
                        uvfn=lambda u, v: ((u - ZT) / (ZN - ZT), v), ukeys=ukeys_s, vkeys=vkeys)
        else:
            rg = [(m, (lambda u, v, f=f: f(u, v))) for m, f in regions]
            car.surface(fn, ZT, ZN, 0.0, 1.0, 120, 48, regions=rg, default="paint_body", flip=True,
                        uvfn=lambda u, v: ((u - ZT) / (ZN - ZT), v), ukeys=ukeys_s, vkeys=vkeys)

    # ---- the end faces: planar panels cut to the section outline -------------------------------------------
    def face(zc, sign, regions, default):
        yo, xo = end_outline(zc)
        hwe = float(xo.max())
        def fn(u, v):
            u = np.asarray(u, float); v = np.asarray(v, float)
            return u, v, zc + 0 * u
        def outside(u, v):
            u = np.asarray(u, float); v = np.asarray(v, float)
            xs = np.interp(v, yo, xo)
            return -np.maximum.reduce([np.abs(u) - xs - 0.004, BOT - v, v - (TOP + CROWN) - 0.002])
        regs = [("__cut", outside)] + regions
        car.surface(fn, -hwe - 0.01, hwe + 0.01, BOT, TOP + CROWN + 0.01, 40, 40, regions=regs, default=default,
                    uvfn=lambda u, v: ((u + hwe) / (2 * hwe), (v - BOT) / (TOP + CROWN - BOT)), flip=sign < 0,
                    ukeys=[-hwe + 0.24, hwe - 0.24, -0.05, 0.05], vkeys=[BELT, WTOP, 1.60, 2.70, 2.82, 3.08])
        car.parts.pop("__cut", None)

    def rr(cx, cy, hx, hy, r):
        return lambda u, v: rrect_sdf(cx, cy, hx, hy, r)(np.asarray(u, float), np.asarray(v, float))

    # front: a split windscreen, the destination box over it
    hwf = float(hw_at(np.array([ZN]))[0])
    ws_l = rr(-0.5 * (hwf - 0.10), 2.16, 0.5 * (hwf - 0.22) - 0.04, 0.52, 0.08)
    ws_r = rr(0.5 * (hwf - 0.10), 2.16, 0.5 * (hwf - 0.22) - 0.04, 0.52, 0.08)
    screen = sdf_union(ws_l, ws_r)
    dest = rr(0.0, 2.95, 0.78, 0.11, 0.03)
    face(ZN, 1, [("glass", screen), ("seal", lambda u, v: screen(u, v) - 0.035), ("dest", dest),
                 ("seal", lambda u, v: dest(u, v) - 0.03),
                 ("paint_stripe", lambda u, v: np.abs(np.asarray(v) - (BELT - 0.22)) - 0.11),
                 ("chrome", lambda u, v: np.abs(np.asarray(v) - (BELT - 0.05)) - 0.025)], "paint_face")
    # rear: a small back light, the brown belt continued
    hwt = float(hw_at(np.array([ZT]))[0])
    back = rr(0.0, 2.40, 0.62, 0.30, 0.08)
    face(ZT, -1, [("glass", back), ("seal", lambda u, v: back(u, v) - 0.035),
                  ("paint_stripe", lambda u, v: np.abs(np.asarray(v) - (BELT - 0.22)) - 0.11),
                  ("chrome", lambda u, v: np.abs(np.asarray(v) - (BELT - 0.05)) - 0.025)], "paint_face")

    # ---- the cabin behind the glass -------------------------------------------------------------------------
    car.surface(lambda u, v: body(u, v, inset=0.09), ZT + 0.12, ZN - 0.12, 0.16, 1.0, 40, 16, mirror=True,
                default="interior_dark", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for zz in (ZT + 0.10, ZN - 0.10):
        car.box("interior_dark", (-HW + 0.28, BOT + 0.30, zz - 0.01), (HW - 0.28, TOP - 0.20, zz + 0.01))
    car.box("interior_dark", (-HW + 0.10, 1.00, ZT + 0.15), (HW - 0.10, 1.04, ZN - 0.15))     # the floor
    # double seats in rows down both sides (a bench across the back), the aisle between
    rows = np.arange(ZT + 1.80, ZN - 1.70, 0.82)
    for z in rows:
        for s_ in (1, -1):
            if s_ < 0 and (DOOR_C[0] - 0.25 < z < DOOR_C[1] + 0.10):
                continue
            x0, x1 = s_ * 0.36, s_ * (HW - 0.14)
            car.box("seat", (min(x0, x1), 1.04, z - 0.22), (max(x0, x1), 1.46, z + 0.22))
            car.box("seat", (min(x0, x1), 1.46, z - 0.24), (max(x0, x1), 2.02, z - 0.14))
    # the back bench sits ahead of the rounded rear corners (its ends showed through them)
    car.box("seat", (-HW + 0.42, 1.04, ZT + 0.62), (HW - 0.42, 1.46, ZT + 1.02))
    car.box("seat", (-HW + 0.42, 1.46, ZT + 0.56), (HW - 0.42, 2.02, ZT + 0.68))
    # the driver: seat, dash, a big flat wheel, on the +x side
    car.box("seat", (0.45, 1.04, ZN - 1.55), (1.15, 1.48, ZN - 1.05))
    car.box("seat", (0.45, 1.48, ZN - 1.60), (1.15, 2.10, ZN - 1.48))
    car.box("interior_dark", (-HW + 0.12, 1.20, ZN - 0.42), (HW - 0.12, 1.62, ZN - 0.14))
    car.revolve([(0.26, -0.015), (0.26, 0.015)], (0.80, 1.78, ZN - 0.70), (0, 0.85, -0.5), 20, default="trim_dark", uv_mode="disc")
    # grab poles at the doors
    for d0, d1 in (DOOR_F, DOOR_C):
        car.sweep(lambda u, z=d1 + 0.08: np.stack([-(HW - 0.32) + 0 * u, 1.04 + 1.90 * u, z + 0 * u], 1), 0.025, 6, 6, "chrome")

    # wheel-arch liners
    for zc in (ZF, ZR):
        for s_ in (1, -1):
            def liner(u, v, s_=s_, zc=zc):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return s_ * x, R_TYRE + 0.02 + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.62, HW - 0.04, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # ---- the nose ---------------------------------------------------------------------------------------------
    for s_ in (1, -1):
        c = np.array([s_ * (hwf - 0.36), 1.02, ZN])
        car.revolve([(0.17, -0.05), (0.175, 0.02), (0.16, 0.04)], c, (0, 0, 1), 24, default="chrome", uv_mode="disc")
        car.revolve([(0.16, 0.035), (0.10, 0.055), (0.0, 0.062)], c, (0, 0, 1), 24, default="lamp_head", uv_mode="disc")
        car.revolve([(0.065, -0.02), (0.065, 0.02), (0.0, 0.035)], (s_ * (hwf - 0.36), 1.36, ZN), (0, 0, 1), 14,
                    default="lamp_amber", uv_mode="disc")
        # roof-front marker lamps
        car.revolve([(0.05, -0.02), (0.05, 0.015), (0.0, 0.03)], (s_ * 0.30, 3.18, ZN - 0.01), (0, 0, 1), 12,
                    default="lamp_amber", uv_mode="disc")
        # mirrors on arms off the front corners
        car.sweep(lambda u, s_=s_: np.stack([s_ * (hwf + 0.02 + 0.30 * u), 2.30 + 0.10 * u, ZN - 0.18 + 0.10 * u], 1), 0.02, 4, 6, "chrome")
        car.box("trim_dark", (s_ * (hwf + 0.32) - 0.05, 2.06, ZN - 0.12), (s_ * (hwf + 0.32) + 0.05, 2.46, ZN - 0.04))
    car.box("grille", (-0.48, 0.70, ZN - 0.01), (0.48, 1.16, ZN + 0.025))
    car.box("chrome", (-0.52, 0.66, ZN - 0.01), (0.52, 0.70, ZN + 0.035))
    car.box("chrome", (-0.52, 1.16, ZN - 0.01), (0.52, 1.20, ZN + 0.035))
    # the black bumper with rounded ends (the sprite's dark curved bar), the pale plate
    car.sweep(lambda u: np.stack([(u - 0.5) * 2.0 * (hwf - 0.04), 0.56 + 0 * u,
                                  ZN + 0.08 - 0.06 * ((u - 0.5) * 2) ** 2], 1), 0.09, 24, 10, "trim_dark", squash=(0.8, 1.0))
    car.box("plate", (-0.26, 0.70, ZN + 0.10), (0.26, 0.84, ZN + 0.11))

    # ---- the tail ---------------------------------------------------------------------------------------------
    car.box("grille", (-0.95, 0.78, ZT - 0.02), (0.95, 1.46, ZT + 0.01))
    car.box("trim_dark", (-0.99, 0.74, ZT - 0.03), (0.99, 0.78, ZT + 0.01))
    car.box("trim_dark", (-0.99, 1.46, ZT - 0.03), (0.99, 1.50, ZT + 0.01))
    for s_ in (1, -1):
        car.revolve([(0.11, 0.0), (0.11, 0.03), (0.0, 0.05)], (s_ * (hwt - 0.26), 1.12, ZT), (0, 0, -1), 18,
                    default="lamp_tail", uv_mode="disc")
        car.revolve([(0.07, 0.0), (0.07, 0.025), (0.0, 0.04)], (s_ * (hwt - 0.26), 1.40, ZT), (0, 0, -1), 14,
                    default="lamp_amber", uv_mode="disc")
    # the sprite's amber band at the roof's rear: a marker lamp bar under the roof edge
    car.box("lamp_amber", (-0.55, 2.98, ZT - 0.03), (0.55, 3.08, ZT + 0.01))
    car.sweep(lambda u: np.stack([(u - 0.5) * 2.0 * (hwt - 0.04), 0.58 + 0 * u,
                                  ZT - 0.08 + 0.06 * ((u - 0.5) * 2) ** 2], 1), 0.09, 24, 10, "trim_dark", squash=(0.8, 1.0))
    car.box("plate", (-0.26, 1.54, ZT - 0.02), (0.26, 1.68, ZT - 0.01))

    # ---- the roof: three escape hatches on the brown strip, round vents between, marker lamps on the letterboard
    for z in (-2.46, -0.55, 1.05):
        car.box("hatch", (-0.34, TOP + CROWN - 0.01, z - 0.34), (0.34, TOP + CROWN + 0.05, z + 0.34))
        car.box("hatch_lid", (-0.30, TOP + CROWN + 0.05, z - 0.30), (0.30, TOP + CROWN + 0.08, z + 0.30))
    for z in (-3.30, -1.55, 0.25, 1.90, 3.20):
        c = (0.0, TOP + CROWN - 0.01, z)
        car.revolve([(0.17, -0.01), (0.17, 0.03), (0.155, 0.045)], c, (0, 1, 0), 24, default="trim_dark", uv_mode="disc")
        car.revolve([(0.155, 0.045), (0.12, 0.09), (0.06, 0.115), (0.0, 0.12)], c, (0, 1, 0), 24, default="hatch", uv_mode="disc")
    for s_ in (1, -1):
        for z in np.linspace(ZT + 0.9, ZN - 0.9, 5):
            x = s_ * (float(hw_at(np.array([z]))[0]) - 0.035)
            car.box("lamp_amber", (min(x, x + s_ * 0.03), WTOP + 0.22, z - 0.05), (max(x, x + s_ * 0.03), WTOP + 0.30, z + 0.05))
        # a rubbing strake along the skirt
        x0 = s_ * (HW - 0.01); x1 = s_ * (HW + 0.035)
        for a, b in ((ZT + 0.30, ZR - R_ARCH - 0.05), (ZR + R_ARCH + 0.05, ZF - R_ARCH - 0.05), (ZF + R_ARCH + 0.05, ZN - RCF)):
            car.box("trim_dark", (min(x0, x1), 0.70, a), (max(x0, x1), 0.80, b))

    # chassis
    for s_ in (1, -1):
        car.box("trim_dark", (s_ * 0.62 - 0.09, 0.40, ZT + 0.4), (s_ * 0.62 + 0.09, 0.62, ZN - 0.4))
    car.box("underbody", (-HW + 0.06, 0.48, ZT + 0.2), (HW - 0.06, 0.50, ZN - 0.2))

    st = dict(rim_r=0.58, rim_mat="trim_dark", cap_mat="chrome", whitewall=0.0, cap_dome=0.08)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, st)
    for nm, zc, xw in (("wheel_rl", ZR, -X_REAR), ("wheel_rr", ZR, X_REAR)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_REAR, 1 if xw > 0 else -1, st)

    # ---- textures -------------------------------------------------------------------------------------------
    U = lambda z: (z - ZT) / (ZN - ZT)
    # panel seams down the sides between the bays (below the belt), the skirt's top line
    seams = [(U(z), VB[1], VB[2] + 0.30) for z in np.linspace(WIN_Z0, WIN_Z1, 5)[1:-1]]
    car.materials["paint_body"] = tex_paint(CREAM, 512, lines_u=seams, lines_v=[(VB[2] + 0.06, 0.0, 1.0)], seed=111)
    # the end faces: their own unbaked cream (the side's occlusion picture is mapped along the body, not across a face)
    car.materials["paint_face"] = tex_paint(CREAM, 128, seed=115)
    car.materials["paint_stripe"] = tex_paint(BROWN, 128, seed=112)
    car.materials["hatch"] = tex_paint((196, 194, 188), 64, seed=114)
    car.materials["hatch_lid"] = tex_paint((70, 72, 74), 64, seed=116)     # the sprite's dark roof squares: smoked lids
    car.materials["glass"] = tex_glass(256, tint=(40, 50, 58), alpha=135)
    car.materials["seal"] = tex_flat((22, 22, 24))
    car.materials["trim_dark"] = tex_flat((30, 31, 32))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(128, bars=10)
    car.materials["underbody"] = tex_underbody()
    car.materials["plate"] = tex_flat((214, 204, 160))
    car.materials["dest"] = dest_sign()
    car.materials["interior_dark"] = tex_flat((44, 42, 40))
    car.materials["seat"] = tex_leather((120, 78, 56))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread(grooves=5)
    car.materials["tyre_side"] = tex_tyre_side()
    bake_ao(car, body, ZT, ZN, 0.0, 1.0, "paint_body", strength=0.55)
    return car


def dest_sign(size=128):
    """the destination box: a dark blind with a pale route panel (no lettering: no game art)"""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (size, size // 4 * 4), (24, 24, 26))
    d = ImageDraw.Draw(im)
    d.rectangle([size * 0.08, size * 0.30, size * 0.92, size * 0.70], fill=(214, 206, 170))
    for k in range(5):
        x = size * (0.16 + 0.15 * k)
        d.rectangle([x, size * 0.40, x + size * 0.09, size * 0.60], fill=(40, 38, 34))
    return im


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va23/p011.png", LEN)
