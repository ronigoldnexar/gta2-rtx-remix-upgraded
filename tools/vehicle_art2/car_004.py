#!/usr/bin/env python3
"""004 G4 Bank Van (VEHICLE-ART-10, ptm1-bil): the catalog's 1950s armoured cash-in-transit truck read from the GTA2
sprite (front down in the sprite export, +z here): a short forward-control cab with a pale roof (the sprite's
pale panel ahead of the box), a raked windscreen over a short bonnet, a bull-bar on a heavy bumper; behind it a
tall armoured box with four stiffener ribs down each side (the sprite's notched flanks, a marker lamp on each),
gun slits between them, a pale roof plate carrying two round domed vents (the sprite's two white discs) and a pair
of rear doors with small armoured windows. The body is painted (neutral base, tinted to the identity record: dark
green on remap 36, blue on the default); the roof plate, the cab roof and the vents are a fixed pale grey, as in
both remaps of the sprite. It replaces the image-to-3D shell (dark untinted lower half, a mottled 'camo' roof and a
white rear slab: ptm1). Metres, +z nose, 1 block = 5 m (catalog body 0.625 x 1.234 blocks: 3.13 x 6.17 m)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "004_g4_bank_van"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (52, 82, 66)             # remap 36 (the bil bank van): dark green
LEN = 1.234 * 5.0                 # 6.17 m
ZF, ZR = 2.28, -1.40              # axles (CARI: 31 px forward, 17 px back of 64 a block; front pulled in for the bumper)
R_TYRE, W_TYRE = 0.50, 0.34
R_REAR, W_REAR = 0.50, 0.48
X_WHEEL, X_REAR = 1.16, 1.12
R_ARCH = 0.62
ZT, ZB = -3.02, 0.40              # the box: tail, front wall
ZC0, ZN = 0.28, 2.88              # the cab: back (inside the box), nose
BOX_HW, BOX_BOT, BOX_TOP = 1.42, 0.68, 2.95
CAB_HW, CAB_BOT, CAB_TOP, BELT = 1.32, 0.72, 2.55, 1.66
RIBS = (-2.19, -1.56, -0.94, -0.23)
SLITS = (-1.875, -1.25, -0.585)
VENTS = (-1.80, -0.62)

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


cab_top = spline([(ZC0, CAB_TOP), (1.0, CAB_TOP + 0.01), (1.62, CAB_TOP - 0.02), (1.78, CAB_TOP - 0.10),
                  (2.30, BELT - 0.02), (2.40, BELT - 0.06), (2.70, BELT - 0.16), (ZN, BELT - 0.24)])


def cab_hw(z):
    z = np.asarray(z, float)
    return np.interp(z, [ZC0, 1.6, 2.3, ZN - 0.10, ZN], [CAB_HW, CAB_HW, CAB_HW - 0.02, CAB_HW - 0.06, CAB_HW - 0.12])


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
    vk = list(VB)
    car.surface(box_body, ZT, ZB, 0.0, 1.0, 60, 40, mirror=True,
                regions=[("slit", box_slits), ("underbody", box_under)],
                default="paint_box", uvfn=lambda u, v: ((u - ZT) / (ZB - ZT), v),
                ukeys=[ZR - R_ARCH, ZR + R_ARCH] + [z + d for z in SLITS for d in (-0.2, 0.2)], vkeys=vk)
    car.cap(box_body, ZT, 0.0, 1.0, 40, "paint_box", nr=6)
    car.cap(box_body, ZB, 0.0, 1.0, 40, "paint_box", nr=6)
    # stiffener ribs down each side, a clear marker lamp at the top of each (the sprite's white squares)
    for s_ in (1, -1):
        for z in RIBS:
            x0 = s_ * (BOX_HW - 0.02); x1 = s_ * (BOX_HW + 0.07)
            car.box("paint_rib", (min(x0, x1), 1.16, z - 0.10), (max(x0, x1), BOX_TOP - 0.18, z + 0.10))
            car.box("lamp_clear", (min(x1, x1 + s_ * 0.02), BOX_TOP - 0.40, z - 0.06), (max(x1, x1 + s_ * 0.02), BOX_TOP - 0.28, z + 0.06))
        # a rubbing strake along the bottom of the box and the cab
        car.box("trim_dark", (min(s_ * (BOX_HW - 0.02), s_ * (BOX_HW + 0.04)), 0.78, ZT + 0.05),
                (max(s_ * (BOX_HW - 0.02), s_ * (BOX_HW + 0.04)), 0.90, ZR - R_ARCH - 0.02))
        car.box("trim_dark", (min(s_ * (BOX_HW - 0.02), s_ * (BOX_HW + 0.04)), 0.78, ZR + R_ARCH + 0.02),
                (max(s_ * (BOX_HW - 0.02), s_ * (BOX_HW + 0.04)), 0.90, ZB))
    # the pale roof plate with its two domed vents, a drip rail round it
    car.box("roof_panel", (-0.98, BOX_TOP + 0.005, ZT + 0.22), (0.98, BOX_TOP + 0.06, ZB - 0.12))
    for z in VENTS:
        c = (0.0, BOX_TOP + 0.06, z)
        car.revolve([(0.50, -0.01), (0.50, 0.04), (0.47, 0.06)], c, (0, 1, 0), 32, default="trim_dark", uv_mode="disc")
        car.revolve([(0.47, 0.06), (0.44, 0.12), (0.34, 0.19), (0.18, 0.225), (0.0, 0.235)], c, (0, 1, 0), 32,
                    default="vent", uv_mode="disc")
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
    car.box("frame", (-1.38, 0.56, ZT - 0.06), (1.38, 0.78, ZT + 0.20))
    car.box("trim_dark", (-0.90, 0.50, ZT - 0.04), (0.90, 0.56, ZT + 0.30))
    car.box("plate", (-0.26, 0.86, zr - 0.02), (0.26, 1.02, zr))

    # ---- the cab --------------------------------------------------------------------------------------
    def cab_glass(u, v):
        x, y, z = cab_body(u, v)
        z = np.asarray(z, float); v = np.asarray(v, float)
        top = cab_top(z)
        # windscreen: the raked part of the roof between the pillars
        ws = np.maximum.reduce([BELT + 0.06 - y, z - 2.27, 1.70 - z, np.abs(x) - (cab_hw(z) - 0.30), VB[3] - 0.02 - v])
        # side windows: above the belt, behind the A pillar, ahead of the box
        za = 1.68 + (CAB_TOP - 0.06 - y) / (CAB_TOP - BELT) * 0.55 - 0.16
        sw = np.maximum.reduce([BELT + 0.08 - y, y - (top - 0.14), ZB + 0.16 - z, z - za, VB[2] - v, v - VB[3]])
        return np.minimum(ws, sw)
    seal = lambda u, v: cab_glass(u, v) - 0.03
    pale_roof = lambda u, v: np.maximum(VB[4] + 0.02 - np.asarray(v), np.asarray(u) - 1.60)
    cab_under = lambda u, v: np.asarray(v) - VB[1] * 0.98
    car.surface(cab_body, ZC0, ZN, 0.0, 1.0, 56, 40, mirror=True,
                regions=[("glass", cab_glass), ("seal", seal), ("roof_panel", pale_roof), ("underbody", cab_under)],
                default="paint_body", uvfn=lambda u, v: ((u - ZC0) / (ZN - ZC0), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, 1.60, 1.70, 2.27, ZB + 0.16], vkeys=vk + [VB[4] + 0.02])
    car.cap(cab_body, ZN, 0.0, 1.0, 40, "paint_body", nr=6)
    car.surface(lambda u, v: cab_body(u, v, inset=0.06), ZB - 0.05, 2.25, 0.18, 1.0, 20, 14, mirror=True,
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
    car.box("frame", (-1.36, 0.56, ZN - 0.04), (1.36, 0.80, ZN + 0.14))
    for s_ in (1, -1):
        c = np.array([s_ * 0.98, 1.12, ZN - 0.01])
        car.revolve([(0.15, -0.10), (0.155, 0.015), (0.14, 0.035)], c, (0, 0, 1), 22, default="chrome", uv_mode="disc")
        car.revolve([(0.14, 0.030), (0.09, 0.050), (0.0, 0.056)], c, (0, 0, 1), 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.045, 0.0), (0.045, 0.02), (0.0, 0.03)], (s_ * 0.98, 0.90, ZN + 0.01), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        # bull-bar uprights
        car.sweep(lambda u, s_=s_: np.stack([s_ * 0.56 + 0 * u, 0.66 + 0.80 * u, ZN + 0.20 + 0 * u], 1), 0.045, 8, 10, "bar")
        # mirrors on arms off the cab corners
        car.sweep(lambda u, s_=s_: np.stack([s_ * (CAB_HW - 0.04 + 0.26 * u), 1.92 + 0 * u, 1.72 + 0 * u], 1), 0.018, 4, 6, "chrome")
        car.box("trim_dark", (s_ * (CAB_HW + 0.24) - 0.04, 1.78, 1.70), (s_ * (CAB_HW + 0.24) + 0.04, 2.14, 1.76))
        # cab roof marker lamps (the sprite's two small items between cab and box)
        car.revolve([(0.06, 0.0), (0.06, 0.04), (0.0, 0.08)], (s_ * 0.45, CAB_TOP + 0.03, 0.80), (0, 1, 0), 12, default="lamp_amber", uv_mode="disc")
        # step under the cab door
        car.box("trim_dark", (min(s_ * (CAB_HW - 0.10), s_ * (CAB_HW + 0.02)), 0.62, 0.70), (max(s_ * (CAB_HW - 0.10), s_ * (CAB_HW + 0.02)), 0.68, 1.30))
    for y in (0.98, 1.42):
        car.sweep(lambda u, y=y: np.stack([(u - 0.5) * 1.30, y + 0 * u, ZN + 0.20 + 0 * u], 1), 0.04, 10, 10, "bar")
    car.box("plate", (-0.24, 0.62, ZN + 0.14), (0.24, 0.76, ZN + 0.15))

    # chassis
    for s_ in (1, -1):
        car.box("frame", (s_ * 0.55 - 0.08, 0.40, ZT + 0.2), (s_ * 0.55 + 0.08, 0.66, ZN - 0.1))
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
    car.materials["roof_panel"] = tex_paint((214, 220, 218), 256, seed=45)
    car.materials["vent"] = tex_paint((226, 230, 228), 128, seed=46)
    car.materials["glass"] = tex_glass(256, tint=(34, 42, 50), alpha=190)
    car.materials["slit"] = tex_flat((16, 18, 20))
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["trim_dark"] = tex_flat((30, 31, 32))
    car.materials["bar"] = tex_flat((36, 37, 38))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(128, bars=9)
    car.materials["underbody"] = tex_flat((28, 27, 26))
    car.materials["frame"] = tex_flat((30, 30, 32))
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


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va10/p004.png", LEN)
