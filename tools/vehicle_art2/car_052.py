#!/usr/bin/env python3
"""052 SWAT Van (VEHICLE-ART-23, qav56 "roof a 2-3 px-per-texel blurry smear with a floating white pillar"): the
catalog's armoured SWAT truck read from the GTA2 sprite nose down (assets-src/cars/sprites_x4/052_swat_van_default.png,
64 x 98 px, body 40 x 83 px), on VEHICLE-ART-10's 004 armoured-van recipe: a short forward-control cab with a raked
windscreen, a rounded nose with a slotted grille between the lamps, a heavy bumper with a push bar; on the cab roof the
sprite's light bar (blue to the rear, red to the front, a clear centre); behind it a taller armoured box with
stiffener ribs, gun ports, a pale roof carrying the sprite's two navy stripes, two vent grilles and the blue/red
beacon pods at its rear corners, rear doors with armoured windows. Two-tone as the sprite (dark flanks under a pale
upper body and roof): navy below the belt, pale grey-blue above. 52 is a livery model (identity.cpp), so these are
its colours in every mode. It replaces the image-to-3D shell (the roof a blurred copy of the sprite with a stray
white fin down the middle). Metres, +z nose, 1 block = 5 m (catalog body 0.625 x 1.297 blocks: 3.13 x 6.48 m;
axles +30 / -25 px)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "052_swat_van"
PALE = (196.0, 208.0, 210.0)
NAVY = (32.0, 58.0, 110.0)     # the sprite's stripe blue (30,61,116)
PAINT = PALE
SPRITE = None
LEN = 1.297 * 5.0                 # 6.48 m
ZF, ZR = 2.22, -1.95              # axles (CARI: 30 px forward, 25 px back of 64 a block; front pulled in for the bumper)
R_TYRE, W_TYRE = 0.50, 0.34
R_REAR, W_REAR = 0.50, 0.48
X_WHEEL, X_REAR = 1.16, 1.12
R_ARCH = 0.62
ZT, ZB = -3.06, 0.45              # the box: tail, front wall (sprite rows 35-220 of 392)
ZC0, ZN = 0.35, 2.98              # the cab: back (inside the box), nose
BOX_HW, BOX_BOT, BOX_TOP = 1.44, 0.70, 3.05
CAB_HW, CAB_BOT, CAB_TOP, BELT = 1.38, 0.72, 2.60, 1.66
NAVY_TOP = 1.62                   # the dark flanks end at the belt
RIBS = (-2.60, -1.30, -0.05)
SLITS = (-1.95, -0.68)
VENTS = (-1.85,)

# section breakpoints along v (bottom centre 0 -> top centre 1)
VB = (0.0, 0.14, 0.22, 0.62, 0.72, 1.0)


def section(v, hw, bot, top, r_lo, r_hi, tumble=0.0, belt=None, crown=0.0):
    """a rounded-rectangle half section: bottom flat, lower corner, side, upper corner, roof"""
    v = np.asarray(v, float)
    hw = np.broadcast_to(hw, v.shape).astype(float); bot = np.broadcast_to(bot, v.shape).astype(float)
    top = np.broadcast_to(top, v.shape).astype(float)
    belt = bot + r_lo if belt is None else np.broadcast_to(belt, v.shape).astype(float)
    t0 = np.clip(v / VB[1], 0, 1)
    t1 = np.clip((v - VB[1]) / (VB[2] - VB[1]), 0, 1)
    t2 = np.clip((v - VB[2]) / (VB[3] - VB[2]), 0, 1)
    t3 = np.clip((v - VB[3]) / (VB[4] - VB[3]), 0, 1)
    t4 = np.clip((v - VB[4]) / (VB[5] - VB[4]), 0, 1)
    side_lo = bot + r_lo; side_hi = top - r_hi
    # side: x pulls in above the belt (tumblehome)
    ys = side_lo + t2 * (side_hi - side_lo)
    tb = tumble * np.clip((ys - belt) / np.maximum(side_hi - belt, 1e-6), 0, 1) ** 1.4
    hw_top = hw - tumble
    a1 = -math.pi / 2 + t1 * math.pi / 2
    a3 = t3 * math.pi / 2
    xs = [t0 * (hw - r_lo), hw - r_lo + r_lo * np.cos(a1), hw - tb, hw_top - r_hi + r_hi * np.cos(a3), (hw_top - r_hi) * (1 - t4)]
    ys_ = [bot + 0 * v, side_lo + r_lo * np.sin(a1), ys, side_hi + r_hi * np.sin(a3), top + crown * (1 - (1 - t4) ** 2)]
    seg = np.select([v < VB[1], v < VB[2], v < VB[3], v < VB[4]], [0, 1, 2, 3], 4)
    x = np.choose(seg, xs); y = np.choose(seg, ys_)
    return x, y


def arch_at(z, zc, r=R_ARCH, rt=R_TYRE):
    dz = np.abs(np.asarray(z, float) - zc)
    y = rt + np.sqrt(np.clip(r ** 2 - np.minimum(dz, r) ** 2, 0, None))
    return np.where(dz < r, y, 0)


def box_body(u, v):
    z = np.asarray(u, float)
    bot = np.maximum(BOX_BOT, arch_at(z, ZR))
    x, y = section(v, BOX_HW, bot, BOX_TOP, 0.06, 0.16, crown=0.03)
    return x, y, z


cab_top = spline([(ZC0, CAB_TOP), (1.0, CAB_TOP + 0.01), (1.48, CAB_TOP - 0.02), (1.62, CAB_TOP - 0.10),
                  (2.14, BELT - 0.02), (2.26, BELT - 0.07), (2.66, BELT - 0.20), (ZN, BELT - 0.30)])


def cab_hw(z):
    z = np.asarray(z, float)
    return np.interp(z, [ZC0, 1.5, 2.15, ZN - 0.25, ZN], [CAB_HW, CAB_HW, CAB_HW - 0.03, CAB_HW - 0.12, CAB_HW - 0.30])


def cab_body(u, v, inset=0.0):
    z = np.asarray(u, float)
    bot = np.maximum(CAB_BOT, arch_at(z, ZF))
    top = cab_top(z)
    belt = np.minimum(BELT, top - 0.05)
    x, y = section(v, cab_hw(z) - inset, bot + inset, top - inset, 0.06, 0.22, tumble=0.10, belt=belt, crown=0.04)
    return x, y, z


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE

    # ---- the armoured box -------------------------------------------------------------------------
    def box_slits(u, v):
        x, y, z = box_body(u, v)
        d = None
        for zs in SLITS:
            s = np.maximum(np.abs(z - zs) - 0.20, np.abs(y - 2.06) - 0.055)
            d = s if d is None else np.minimum(d, s)
        return np.maximum(d, np.maximum(VB[2] - np.asarray(v), np.asarray(v) - VB[3]))
    box_under = lambda u, v: np.asarray(v) - VB[1] * 0.98
    box_navy = lambda u, v: np.maximum(box_body(u, v)[1] - NAVY_TOP, VB[1] - np.asarray(v))
    # the sprite's two navy stripes along the roof (x 0.35..0.74), the white centre between them
    stripes = lambda u, v: np.maximum(np.abs(np.abs(box_body(u, v)[0]) - 0.545) - 0.195, VB[4] - np.asarray(v))
    vk = list(VB)
    car.surface(box_body, ZT, ZB, 0.0, 1.0, 60, 40, mirror=True,
                regions=[("slit", box_slits), ("underbody", box_under), ("paint_navy", box_navy), ("paint_navy", stripes)],
                default="paint_box", uvfn=lambda u, v: ((u - ZT) / (ZB - ZT), v),
                ukeys=[ZR - R_ARCH, ZR + R_ARCH] + [z + d for z in SLITS for d in (-0.2, 0.2)], vkeys=vk)
    # VEHICLE-ART-23: a fan cap's normals follow the ring's winding; the 004 recipe's tail cap faced into the box
    # (mean normal +0.9 z: the van's back drew near-black from behind), so each cap is turned to face away from it
    k0 = len(car.parts["paint_box"].p)
    car.cap(box_body, ZT, 0.0, 1.0, 40, "paint_box", nr=6)
    face_out(car.parts["paint_box"], k0, -1)
    k0 = len(car.parts["paint_box"].p)
    car.cap(box_body, ZB, 0.0, 1.0, 40, "paint_box", nr=6)
    face_out(car.parts["paint_box"], k0, +1)
    # stiffener ribs down each side, a clear marker lamp at the top of each (the sprite's white squares)
    for s_ in (1, -1):
        for z in RIBS:
            x0 = s_ * (BOX_HW - 0.02); x1 = s_ * (BOX_HW + 0.07)
            car.box("paint_navy", (min(x0, x1), 1.16, z - 0.10), (max(x0, x1), NAVY_TOP, z + 0.10))
            car.box("paint_rib", (min(x0, x1), NAVY_TOP, z - 0.10), (max(x0, x1), BOX_TOP - 0.18, z + 0.10))
            car.box("lamp_clear", (min(x1, x1 + s_ * 0.02), BOX_TOP - 0.40, z - 0.06), (max(x1, x1 + s_ * 0.02), BOX_TOP - 0.28, z + 0.06))
        # a rubbing strake along the bottom of the box and the cab
        car.box("trim_dark", (min(s_ * (BOX_HW - 0.02), s_ * (BOX_HW + 0.04)), 0.78, ZT + 0.05),
                (max(s_ * (BOX_HW - 0.02), s_ * (BOX_HW + 0.04)), 0.90, ZR - R_ARCH - 0.02))
        car.box("trim_dark", (min(s_ * (BOX_HW - 0.02), s_ * (BOX_HW + 0.04)), 0.78, ZR + R_ARCH + 0.02),
                (max(s_ * (BOX_HW - 0.02), s_ * (BOX_HW + 0.04)), 0.90, ZB))
    # the roof: two vent grilles between the rear beacon pods (sprite rows 80-130: blue to the rear, red ahead)
    for s_ in (1, -1):
        car.box("trim_dark", (s_ * 0.30 - 0.17, BOX_TOP + 0.02, -2.20), (s_ * 0.30 + 0.17, BOX_TOP + 0.08, -1.40))
        car.box("grille", (s_ * 0.30 - 0.14, BOX_TOP + 0.08, -2.17), (s_ * 0.30 + 0.14, BOX_TOP + 0.10, -1.43))
        beacon_pod(car, s_ * 0.86, BOX_TOP + 0.02, -1.78, 0.30, 0.86)
    # the rear doors' lower half navy like the flanks
    car.box("paint_navy", (-BOX_HW + 0.10, BOX_BOT + 0.08, ZT - 0.010), (BOX_HW - 0.10, NAVY_TOP, ZT + 0.02))
    # rear: two doors (a seam, hinges, a locking bar and handle), small armoured windows, lamps, a step bumper
    zr = ZT - 0.012
    car.box("trim_dark", (-0.012, 0.80, zr - 0.004), (0.012, BOX_TOP - 0.20, ZT + 0.01))
    for s_ in (1, -1):
        car.box("slit", (min(s_ * 0.28, s_ * 0.86), 2.02, zr - 0.006), (max(s_ * 0.28, s_ * 0.86), 2.40, ZT + 0.01))
        car.box("trim_dark", (min(s_ * 0.24, s_ * 0.90), 1.98, zr - 0.002), (max(s_ * 0.24, s_ * 0.90), 2.44, ZT + 0.01))
        for y in (1.10, 1.80, 2.50):
            car.box("chrome", (s_ * 1.30 - 0.03, y, zr - 0.04), (s_ * 1.30 + 0.03, y + 0.18, ZT + 0.01))
        car.revolve([(0.075, 0.0), (0.075, 0.03), (0.0, 0.045)], (s_ * 1.10, 1.02, zr), (0, 0, -1), 16, default="lamp_tail", uv_mode="disc")
        car.revolve([(0.050, 0.0), (0.050, 0.02), (0.0, 0.03)], (s_ * 1.10, 1.22, zr), (0, 0, -1), 12, default="lamp_amber", uv_mode="disc")
        car.revolve([(0.040, 0.0), (0.040, 0.02), (0.0, 0.03)], (s_ * 1.12, BOX_TOP - 0.10, zr), (0, 0, -1), 12, default="lamp_amber", uv_mode="disc")
    car.sweep(lambda u: np.stack([(u - 0.5) * 0.70, 1.62 + 0 * u, zr - 0.05 + 0 * u], 1), 0.025, 8, 6, "chrome")
    car.box("chrome", (-0.06, 1.55, zr - 0.07), (0.06, 1.69, zr - 0.02))
    car.box("trim_dark", (-1.38, 0.56, ZT - 0.06), (1.38, 0.78, ZT + 0.20))
    car.box("trim_dark", (-0.90, 0.50, ZT - 0.04), (0.90, 0.56, ZT + 0.30))
    car.box("plate", (-0.26, 0.86, zr - 0.02), (0.26, 1.02, zr))

    # ---- the cab --------------------------------------------------------------------------------------
    def cab_glass(u, v):
        x, y, z = cab_body(u, v)
        z = np.asarray(z, float); v = np.asarray(v, float)
        top = cab_top(z)
        # windscreen: the raked part of the roof between the pillars
        ws = np.maximum.reduce([BELT + 0.06 - y, z - 2.12, 1.64 - z, np.abs(x) - (cab_hw(z) - 0.30), VB[3] - 0.02 - v])
        # side windows: above the belt, behind the A pillar, ahead of the box
        za = 1.56 + (CAB_TOP - 0.06 - y) / (CAB_TOP - BELT) * 0.55 - 0.16
        sw = np.maximum.reduce([BELT + 0.08 - y, y - (top - 0.14), ZB + 0.16 - z, z - za, VB[2] - v, v - VB[3]])
        return np.minimum(ws, sw)
    seal = lambda u, v: cab_glass(u, v) - 0.03
    pale_roof = lambda u, v: np.maximum(VB[4] + 0.02 - np.asarray(v), np.asarray(u) - 1.48)
    cab_navy = lambda u, v: np.maximum(cab_body(u, v)[1] - NAVY_TOP, VB[1] - np.asarray(v))
    cab_under = lambda u, v: np.asarray(v) - VB[1] * 0.98
    car.surface(cab_body, ZC0, ZN, 0.0, 1.0, 56, 40, mirror=True,
                regions=[("glass", cab_glass), ("seal", seal), ("roof_panel", pale_roof), ("underbody", cab_under), ("paint_navy", cab_navy)],
                default="paint_body", uvfn=lambda u, v: ((u - ZC0) / (ZN - ZC0), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, 1.48, 1.64, 2.12, ZB + 0.16], vkeys=vk + [VB[4] + 0.02])
    k0 = len(car.parts["paint_body"].p)
    car.cap(cab_body, ZN, 0.0, 1.0, 40, "paint_body", nr=6)
    face_out(car.parts["paint_body"], k0, +1)
    car.surface(lambda u, v: cab_body(u, v, inset=0.06), ZB - 0.05, 2.10, 0.18, 1.0, 20, 14, mirror=True,
                default="interior_dark", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    # wheel-arch liners
    for zc in (ZF, ZR):
        for s_ in (1, -1):
            def liner(u, v, s_=s_, zc=zc):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return s_ * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.62, 1.40, 16, 2, default="underbody", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # nose: a grille of vertical bars between the lamps, a heavy bumper and a bull-bar
    car.box("grille", (-0.66, 0.86, ZN - 0.02), (0.66, 1.34, ZN + 0.03))
    car.box("trim_dark", (-0.70, 0.82, ZN - 0.03), (0.70, 0.86, ZN + 0.04))
    car.box("trim_dark", (-0.70, 1.34, ZN - 0.03), (0.70, 1.38, ZN + 0.04))
    car.box("trim_dark", (-1.36, 0.56, ZN - 0.04), (1.36, 0.80, ZN + 0.14))
    for s_ in (1, -1):
        c = np.array([s_ * 0.98, 1.12, ZN - 0.01])
        car.revolve([(0.15, -0.10), (0.155, 0.015), (0.14, 0.035)], c, (0, 0, 1), 22, default="chrome", uv_mode="disc")
        car.revolve([(0.14, 0.030), (0.09, 0.050), (0.0, 0.056)], c, (0, 0, 1), 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.045, 0.0), (0.045, 0.02), (0.0, 0.03)], (s_ * 0.98, 0.90, ZN + 0.01), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        # bull-bar uprights
        car.sweep(lambda u, s_=s_: np.stack([s_ * 0.56 + 0 * u, 0.66 + 0.80 * u, ZN + 0.20 + 0 * u], 1), 0.045, 8, 10, "trim_dark")
        # mirrors on arms off the cab corners
        car.sweep(lambda u, s_=s_: np.stack([s_ * (CAB_HW - 0.04 + 0.26 * u), 1.92 + 0 * u, 1.72 + 0 * u], 1), 0.018, 4, 6, "chrome")
        car.box("trim_dark", (s_ * (CAB_HW + 0.24) - 0.04, 1.78, 1.70), (s_ * (CAB_HW + 0.24) + 0.04, 2.14, 1.76))
        # step under the cab door
        car.box("trim_dark", (min(s_ * (CAB_HW - 0.10), s_ * (CAB_HW + 0.02)), 0.62, 0.70), (max(s_ * (CAB_HW - 0.10), s_ * (CAB_HW + 0.02)), 0.68, 1.30))
    # the light bar across the cab roof (sprite rows 232-262): a chrome base, blue lenses to the rear, red ahead,
    # a clear centre
    car.box("trim_dark", (-0.62, CAB_TOP + 0.02, 0.72), (0.62, CAB_TOP + 0.08, 1.30))
    car.box("lamp_clear", (-0.12, CAB_TOP + 0.08, 0.76), (0.12, CAB_TOP + 0.24, 1.26))
    for s_ in (1, -1):
        car.box("lamp_blue", (min(s_ * 0.13, s_ * 0.58), CAB_TOP + 0.08, 0.76), (max(s_ * 0.13, s_ * 0.58), CAB_TOP + 0.24, 1.01))
        car.box("lamp_red", (min(s_ * 0.13, s_ * 0.58), CAB_TOP + 0.08, 1.01), (max(s_ * 0.13, s_ * 0.58), CAB_TOP + 0.24, 1.26))
    for y in (0.98, 1.42):
        car.sweep(lambda u, y=y: np.stack([(u - 0.5) * 1.30, y + 0 * u, ZN + 0.20 + 0 * u], 1), 0.04, 10, 10, "trim_dark")
    car.box("plate", (-0.24, 0.62, ZN + 0.14), (0.24, 0.76, ZN + 0.15))

    # chassis
    for s_ in (1, -1):
        car.box("trim_dark", (s_ * 0.55 - 0.08, 0.40, ZT + 0.2), (s_ * 0.55 + 0.08, 0.66, ZN - 0.1))
    car.box("underbody", (-1.30, 0.40, ZT + 0.2), (1.30, 0.42, ZN - 0.2))

    # interior
    car.box("seat", (-1.08, 1.08, 0.48), (1.08, 1.26, 0.98))
    car.box("seat", (-1.08, 1.24, 0.42), (1.08, 1.92, 0.54))
    car.box("interior_dark", (-1.16, 1.40, 1.80), (1.16, 1.62, 2.05))
    car.revolve([(0.22, -0.012), (0.22, 0.012)], (-0.55, 1.66, 1.48), (0, 0.6, -1), 18, default="interior_dark", uv_mode="disc")

    st = dict(rim_r=0.56, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.10)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, st)
    for nm, zc, xw in (("wheel_rl", ZR, -X_REAR), ("wheel_rr", ZR, X_REAR)):
        add_wheel(car, nm, (xw, R_REAR, zc), R_REAR, W_REAR, 1 if xw > 0 else -1, st)

    # textures: panel seams on the box (bottom/top plate edges, rivet-free), cab door shut lines
    Ub = lambda z: (z - ZT) / (ZB - ZT)
    Uc = lambda z: (z - ZC0) / (ZN - ZC0)
    car.materials["paint_box"] = tex_paint(PAINT, 512, lines_v=[(0.30, 0.0, 1.0), (0.60, 0.0, 1.0)],
                                           lines_u=[(Ub(-2.50), 0.30, 0.60), (Ub(-0.55), 0.30, 0.60)], seed=41)
    car.materials["paint_rib"] = tex_paint(PAINT, 64, seed=42)
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=[(Uc(ZB + 0.12), 0.14, 0.70), (Uc(1.62), 0.14, 0.70)],
                                            handles=[(Uc(ZB + 0.30), 0.42, 0.03, 0.008)], seed=43)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=44)
    car.materials["roof_panel"] = tex_paint((222, 230, 234), 256, seed=45)
    car.materials["paint_navy"] = tex_paint(NAVY, 128, seed=47)
    car.materials["lamp_blue"] = lens((70, 120, 255))
    car.materials["lamp_red"] = lens((250, 64, 44))
    car.materials["glass"] = tex_glass(256, tint=(34, 42, 50), alpha=190)
    car.materials["slit"] = tex_flat((16, 18, 20))
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["trim_dark"] = tex_flat((30, 31, 32))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(128, bars=9)
    car.materials["underbody"] = tex_underbody()
    car.materials["plate"] = tex_flat((210, 200, 150))
    car.materials["lamp_clear"] = tex_flat((236, 236, 226))
    car.materials["interior_dark"] = tex_flat((14, 14, 14))
    car.materials["seat"] = tex_leather((62, 56, 50))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread(grooves=5)
    car.materials["tyre_side"] = tex_tyre_side()
    bake_ao(car, box_body, ZT, ZB, 0.0, 1.0, "paint_box")
    bake_ao(car, cab_body, ZC0, ZN, 0.0, 1.0, "paint_body")
    return car


def face_out(part, k0, sign):
    """turn the chunks added to `part` since k0 so their mean normal points along sign * z (and flip the winding)"""
    for i in range(k0, len(part.n)):
        if np.sign(part.n[i][:, 2].mean()) != sign:
            part.n[i] = -part.n[i]
            part.f[i] = part.f[i][:, ::-1]


def beacon_pod(car, x, y, z, w, l):
    """a rotating-beacon pod: a dark base, a blue lens to the rear and a red one ahead"""
    car.box("trim_dark", (x - w / 2, y, z - l / 2), (x + w / 2, y + 0.06, z + l / 2))
    car.box("lamp_blue", (x - w / 2 + 0.03, y + 0.06, z - l / 2 + 0.03), (x + w / 2 - 0.03, y + 0.22, z - 0.01))
    car.box("lamp_red", (x - w / 2 + 0.03, y + 0.06, z + 0.01), (x + w / 2 - 0.03, y + 0.22, z + l / 2 - 0.03))


def lens(rgb, size=32):
    """a coloured beacon lens: the colour with a pale hot band (the reflector seen through it)"""
    yy = np.linspace(0, 1, size)[:, None] * np.ones((1, size))
    hot = np.exp(-((yy - 0.45) / 0.18) ** 2)
    a = np.array(rgb, float)[None, None] * (0.75 + 0.25 * hot)[..., None] + hot[..., None] * 60
    from PIL import Image
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va23/p052.png", LEN)
