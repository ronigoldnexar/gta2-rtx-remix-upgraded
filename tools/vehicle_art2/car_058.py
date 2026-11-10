#!/usr/bin/env python3
"""058 Tow Truck (VEHICLE-ART-9): the catalog's 1950s wrecker read from the GTA2 sprite (front down in the sprite
export, +z here): a conventional cab with a rounded roof and two amber beacons, a bonnet between pontoon wings that
carry the headlamps, a chrome grille and bumper; behind the cab a flat bed with tool boxes along both sides, a winch,
an A-frame and the sprite's twin booms reaching back past the tail to a hook. Painted (neutral base, tinted to the
identity record's yellow). It replaces the image-to-3D shell (crumpled cab, white blotch on the bonnet).
Metres, +z nose, 1 block = 5 m (catalog body 0.625 x 1.234 blocks: 3.13 x 6.17 m)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "058_tow_truck"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (196, 150, 40)
LEN = 1.234 * 5.0                # 6.17 m
HALF_W = 0.625 * 5.0 / 2          # 1.56 m
ZF, ZR = 1.72, -1.48              # axles (CARI: 22 px forward, 19 px back)
R_TYRE, W_TYRE = 0.46, 0.30
R_REAR, W_REAR = 0.46, 0.52       # the rear pair: one wide (dual) tyre a side
X_WHEEL, X_REAR = 1.10, 1.02
R_ARCH = 0.55
BOT = 0.62
ZC = -0.40                        # the cab's back wall
DECK = 1.08


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn = LEN / 2 - 0.14
    zt = -LEN / 2 + 0.05

    belt0 = spline([(ZC, 1.55), (0.6, 1.56), (1.1, 1.52), (2.0, 1.46), (2.7, 1.38), (zn, 1.26)])
    top0 = spline([(ZC, 2.32), (-0.2, 2.40), (0.30, 2.44), (0.62, 2.40), (0.80, 2.28), (1.05, 1.72), (1.40, 1.66),
                   (2.2, 1.60), (2.7, 1.52), (zn, 1.36)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.30 * np.exp(-((z - ZF) / 0.75) ** 2)
        base = np.interp(z, [ZC, 0.9, 1.3, 2.6, zn], [1.20, 1.20, 1.04, 0.96, 0.84])
        return base + swell
    tumble0 = spline([(ZC, 0.12), (0.6, 0.14), (1.0, 0.0), (zn, 0.0)])

    def arch(z):
        dz = np.abs(z - ZF)
        y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
        return np.where(dz < R_ARCH, y, 0)

    def ends(z, nose=0.25):
        dn = np.clip((z - (zn - nose)) / nose, 0, 1)
        dc = np.clip(((ZC + 0.06) - z) / 0.06, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dc ** 2, 0, 1))

    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * (0.85 + 0.15 * f) - inset
        belt = belt0(z)
        fh = 0.80 + 0.20 * f
        top = belt + (top0(z) - belt) * fh - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08)
        bot = belt - (belt - bot) * fh + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z)
        xl = hw * sepow(c, 0.35)
        yl = belt - (belt - bot) * sepow(s, 0.45)
        H = top - belt
        t = np.clip((v - 0.5) / 0.3, 0, 1) * 0.95
        xs = hw * (1 - t ** 6) ** (1 / 6) - tb * t
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** 6) ** (1 / 6) - tb * 0.95
        xr = X0 * (1 - w)
        yr = belt + H * (0.90 + 0.10 * (1 - (1 - w) ** 2.2) ** 0.45)
        xu = np.where(v < 0.8, xs, xr)
        yu = np.where(v < 0.8, ys, yr)
        return np.where(lo, xl, xu), np.where(lo, yl, yu), z

    SU, SV = 1.0, 2.6
    def win(poly, r):
        p = np.array(poly, float)
        c = p.mean(0)
        d = p - c
        shrink = p - d / np.linalg.norm(d * [SU, SV], axis=1, keepdims=True) * r / np.array([SU, SV])
        f = poly_sdf(shrink, SU, SV)
        return lambda u, v: f(u, v) - r
    side = win([(0.74, 0.56), (-0.20, 0.56), (-0.20, 0.77), (0.60, 0.77)], 0.05)
    screen = win([(0.98, 0.81), (0.98, 0.985), (0.80, 0.985), (0.80, 0.81)], 0.03)
    glass = sdf_union(side, screen)
    seal = lambda u, v: glass(u, v) - 0.014
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, ZC, zn, 0.0, 1.0, 64, 30, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - ZC) / (zn - ZC), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, 0.98, 0.80, 0.74, -0.20], vkeys=[0.56, 0.77, 0.81])
    # the cab's back wall with its small rear window, and the nose
    car.cap(body, ZC, 0.0, 1.0, 24, "paint_body",
            regions=[("glass", lambda r, v: np.maximum(np.abs(np.asarray(v) - 0.84) * 6 - 0.6, np.asarray(r) - 0.75)),
                     ("underbody", lambda r, v: np.asarray(v) - 0.14)])
    car.cap(body, zn, 0.0, 1.0, 24, "paint_body", regions=[("underbody", lambda r, v: np.asarray(v) - 0.14)])
    car.surface(lambda u, v: body(u, v, inset=0.06), -0.34, 1.0, 0.45, 1.0, 20, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for s_ in (1, -1):
        def liner(u, v, s_=s_):
            a = np.asarray(u, float); x = np.asarray(v, float)
            return s_ * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), ZF + (R_ARCH - 0.01) * np.cos(a)
        car.surface(liner, 0.05, math.pi - 0.05, 0.70, 1.40, 16, 2, default="underbody", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # grille: chrome bars across the nose under the bonnet, a heavy chrome bumper
    car.box("grille", (-0.62, 0.86, zn + 0.00), (0.62, 1.30, zn + 0.05))
    for yb in (0.86, 1.30):
        car.sweep(lambda u, yb=yb: np.stack([(u - 0.5) * 1.30, yb + 0 * u, zn + 0.05 + 0 * u], 1), 0.022, 12, 8, "chrome")
    car.sweep(lambda u: np.stack([(u - 0.5) * 2 * 1.40, 0.70 + 0 * u, zn + 0.10 - 0.05 * ((u - 0.5) * 2) ** 2], 1), 0.10, 24, 10,
              "chrome", squash=(0.55, 1.0))
    for s_ in (1, -1):
        c = np.array([s_ * 0.86, 1.10, zn + 0.01])
        car.revolve([(0.125, -0.10), (0.130, 0.012), (0.115, 0.030)], c, (0, 0, 1), 22, default="chrome", uv_mode="disc")
        car.revolve([(0.115, 0.026), (0.075, 0.044), (0.0, 0.050)], c, (0, 0, 1), 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.040, 0.0), (0.040, 0.02), (0.0, 0.03)], (s_ * 0.80, 1.00, zn + 0.02), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        # roof beacons (the sprite's two domes) on a bar
        car.revolve([(0.10, 0.0), (0.10, 0.06), (0.08, 0.14), (0.0, 0.17)], (s_ * 0.55, 2.47, 0.20), (0, 1, 0), 18,
                    default="lamp_amber", uv_mode="disc")
        # mirrors on arms
        car.sweep(lambda u, s_=s_: np.stack([s_ * (1.18 + 0.22 * u), 1.75 + 0 * u, 0.80 + 0 * u], 1), 0.016, 4, 6, "chrome")
        car.box("chrome", (s_ * 1.40 - 0.04, 1.62, 0.78), (s_ * 1.40 + 0.04, 1.92, 0.82))
        car.box("chrome", (s_ * 1.215 - 0.012, 1.60, 0.30), (s_ * 1.215 + 0.012, 1.63, 0.44))
    car.box("tube", (-0.62, 2.43, 0.16), (0.62, 2.48, 0.24))

    # chassis and bed
    for s_ in (1, -1):
        car.box("frame", (s_ * 0.50 - 0.07, BOT - 0.08, -3.00), (s_ * 0.50 + 0.07, BOT + 0.12, 2.80))
    car.box("paint_bed", (-1.30, DECK - 0.10, zt + 0.15), (1.30, DECK, ZC - 0.08))
    for s_ in (1, -1):
        # tool boxes along the sides, ahead of and behind the rear wheel, a rear fender over it
        car.box("paint_bed", (s_ * 1.30 - (0.28 if s_ > 0 else 0), BOT + 0.02, ZR + 0.62), (s_ * 1.30 + (0.28 if s_ < 0 else 0), DECK + 0.30, ZC - 0.08))
        car.box("paint_bed", (s_ * 1.30 - (0.28 if s_ > 0 else 0), BOT + 0.02, zt + 0.15), (s_ * 1.30 + (0.28 if s_ < 0 else 0), DECK + 0.30, ZR - 0.62))
        car.box("paint_bed", (s_ * 1.30 - (0.32 if s_ > 0 else 0), DECK + 0.10, ZR - 0.62), (s_ * 1.30 + (0.32 if s_ < 0 else 0), DECK + 0.16, ZR + 0.62))
        for zh in (ZR + 0.95, ZR - 0.95):
            car.box("chrome", (s_ * 1.305 - 0.01, DECK + 0.05, zh - 0.06), (s_ * 1.305 + 0.01, DECK + 0.10, zh + 0.06))
        car.sweep(lambda u, s_=s_: np.stack([s_ * 1.31 + 0 * u, BOT + 0.10 + 0 * u, ZR + 0.62 + (ZC - 0.08 - ZR - 0.62) * u], 1),
                  0.014, 6, 6, "chrome")
    car.box("underbody", (-1.0, BOT + 0.02, zt + 0.15), (1.0, DECK - 0.10, zt + 0.25))
    car.sweep(lambda u: np.stack([(u - 0.5) * 2.5, 0.72 + 0 * u, zt + 0.10 + 0 * u], 1), 0.08, 16, 8, "tube", squash=(0.6, 1.0))
    for s_ in (1, -1):
        car.revolve([(0.05, -0.02), (0.05, 0.02), (0.0, 0.03)], (s_ * 1.10, 0.92, zt + 0.12), (0, 0, -1), 12, default="lamp_tail", uv_mode="disc")
    # winch drum behind the cab, A-frame, twin booms, cables and hook
    car.box("frame", (-0.55, DECK, ZC - 0.55), (0.55, DECK + 0.40, ZC - 0.15))
    car.revolve([(0.17, -0.50), (0.17, 0.50)], (0.0, DECK + 0.58, ZC - 0.36), (1, 0, 0), 18, default="spring", uv_mode="disc")
    apex = np.array([0.0, 2.80, -1.15])
    for s_ in (1, -1):
        foot = np.array([s_ * 1.05, DECK, ZC - 0.25])
        car.sweep(lambda u, foot=foot: foot[None, :] + (apex - foot)[None, :] * u[:, None], 0.065, 10, 10, "paint_boom")
        b0 = np.array([s_ * 0.32, DECK + 0.30, ZC - 0.65]); b1 = np.array([s_ * 0.32, 1.95, -3.12])
        car.sweep(lambda u, b0=b0, b1=b1: b0[None, :] + (b1 - b0)[None, :] * u[:, None], 0.085, 12, 4, "paint_boom", squash=(0.75, 1.0))
        car.sweep(lambda u, s_=s_: np.stack([s_ * 0.32 + 0 * u, 1.95 - 0.70 * u, -3.12 + 0 * u], 1), 0.03, 8, 6, "cable")
    tip = np.array([0.0, 2.80, -1.15]); end = np.array([0.0, 2.05, -3.05])
    car.sweep(lambda u: tip[None, :] + (end - tip)[None, :] * u[:, None], 0.020, 16, 6, "cable")
    car.sweep(lambda u: np.stack([0 * u, 2.05 - 0.75 * u, -3.05 + 0 * u], 1), 0.016, 10, 6, "cable")
    car.sweep(lambda u: np.stack([0.10 * np.sin(u * 4.2), 1.20 - 0.12 * (1 - np.cos(u * 4.2)), -3.05 + 0 * u], 1), 0.024, 18, 8, "chrome")
    car.sweep(lambda u: np.stack([(u - 0.5) * 0.90, 1.95 + 0 * u, -3.12 + 0 * u], 1), 0.05, 8, 8, "paint_boom")

    # interior
    car.box("seat", (-1.00, 1.02, -0.30), (1.00, 1.20, 0.25))
    car.box("seat", (-1.00, 1.18, -0.38), (1.00, 1.80, -0.26))
    car.box("interior_dark", (-1.08, 1.30, 0.70), (1.08, 1.50, 0.90))
    car.revolve([(0.22, -0.012), (0.22, 0.012)], (-0.50, 1.52, 0.52), (0, 0.6, -1), 18, default="interior_dark", uv_mode="disc")

    st = dict(rim_r=0.58, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.10)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, st)
    for nm, zc, xw in (("wheel_rl", ZR, -X_REAR), ("wheel_rr", ZR, X_REAR)):
        add_wheel(car, nm, (xw, R_REAR, zc), R_REAR, W_REAR, 1 if xw > 0 else -1, st)

    U = lambda z: (z - ZC) / (zn - ZC)
    lines_u = [(U(0.76), 0.30, 0.56), (U(-0.24), 0.30, 0.56), (U(1.06), 0.56, 0.98)]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=58)
    car.materials["paint_bed"] = tex_paint(PAINT, 256, seed=59)
    car.materials["paint_boom"] = tex_paint(PAINT, 128, seed=60)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=61)
    car.materials["glass"] = tex_glass(256, tint=(34, 42, 50), alpha=190)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(128, bars=9)
    car.materials["underbody"] = tex_underbody()
    car.materials["frame"] = tex_flat((30, 30, 32))
    car.materials["tube"] = tex_flat((26, 26, 28))
    car.materials["cable"] = tex_flat((40, 40, 42))
    car.materials["spring"] = tex_flat((60, 58, 56))
    car.materials["interior_dark"] = tex_flat((14, 14, 14))
    car.materials["seat"] = tex_leather((70, 60, 52))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread(grooves=6)
    car.materials["tyre_side"] = tex_tyre_side()
    bake_ao(car, body, ZC, zn, 0.0, 1.0, "paint_body")
    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va9/p058.png", LEN)
