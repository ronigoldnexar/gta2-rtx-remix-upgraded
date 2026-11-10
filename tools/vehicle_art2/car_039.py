#!/usr/bin/env python3
"""039 Morton (VEHICLE-ART-10, audit item 6): the catalog's Morgan Plus 4 idiom read from the GTA2 sprite (front down in
the export): a narrow tub with a long bonnet whose sides carry rows of louvres (the sprite's), an upright chrome
waterfall grille, separate wings - long front wings sweeping back and down into running boards, round rear wings -
headlamps on stalks between the grille and the wings, a two-seat open cockpit (the sprite's dark cockpit) behind a
small upright windscreen, the folded hood behind the seats, a rounded tail carrying the spare wheel. Painted
(neutral, tinted to the identity record). It replaces the image-to-3D shell (crumpled wings; VEHICLE-ART-8's chrome
lamps sat on melted wings). Metres, +z nose, 1 block = 5 m (catalog body 0.5 x 0.906 blocks: 2.5 x 4.53 m)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "039_morton"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (150, 96, 60)
LEN = 0.906 * 5.0                # 4.53 m
ZF, ZR = 1.32, -1.30             # axles (CARI: 18 px forward, 17 back, less the overhangs)
R_TYRE, W_TYRE = 0.36, 0.20
X_WHEEL = 1.02
R_ARCH = 0.42
BOT = 0.36
ZS = 0.30                        # the windscreen
ZC0, ZC1 = -1.25, 0.28           # the cockpit opening


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2 - 0.10, -LEN / 2 + 0.18

    # the tub: bonnet (narrow, tall at the cowl), cockpit sides, rounded tail
    top0 = spline([(zt, 0.66), (-1.95, 0.84), (-1.55, 0.92), (-0.4, 0.94), (ZS, 0.98), (1.0, 0.95), (1.8, 0.92), (zn, 0.88)])
    hw0 = spline([(zt, 0.30), (-1.95, 0.52), (-1.5, 0.57), (-0.2, 0.58), (ZS, 0.56), (1.2, 0.46), (1.9, 0.42), (zn, 0.40)])
    bot0 = spline([(zt, 0.56), (-1.8, BOT), (1.8, BOT), (zn, 0.46)])

    def ends(z, nose=0.10, tail=0.35):
        dn = np.clip((z - (zn - nose)) / nose, 0, 1)
        dt = np.clip(((zt + tail) - z) / tail, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dt ** 2, 0, 1))

    def body(u, v, inset=0.0):
        """u = z; v: bottom centre (0) -> side -> top centre (1); a rounded box section"""
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * (0.35 + 0.65 * f) - inset
        top = bot0(z) + (top0(z) - bot0(z)) * (0.30 + 0.70 * f) - inset
        bot = bot0(z) + inset
        mid = 0.5 * (top + bot); hh = 0.5 * (top - bot)
        a = (v - 0.5) * math.pi
        c, s = np.cos(a), np.sin(a)
        x = hw * sepow(c, 0.30)
        y = mid + hh * sepow(s, 0.30)
        # the bonnet's centre hinge ridge
        y = y + 0.02 * np.exp(-((v - 1.0) / 0.04) ** 2) * (z > ZS)
        return x, y, z

    SV = 2.0
    def cockpit(u, v):
        z = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum.reduce([ZC0 - z, z - ZC1, 0.86 - v])
    rim = lambda u, v: np.abs(cockpit(u, v) + 0.03) - 0.03
    def louvres(u, v):
        z = np.asarray(u, float); v = np.asarray(v, float)
        d = None
        for k in range(9):
            zc = 0.78 + 0.12 * k
            s_ = np.maximum(np.abs(z - zc) - 0.018, np.abs(v - 0.70) - 0.07)
            d = s_ if d is None else np.minimum(d, s_)
        return d
    under = lambda u, v: np.asarray(v) - 0.12
    car.surface(body, zt, zn, 0.0, 1.0, 64, 30, mirror=True,
                regions=[("interior_dark", cockpit), ("trim_dark", rim), ("vent", louvres), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / (zn - zt), v),
                ukeys=[ZC0, ZC1] + [0.78 + 0.12 * k + d for k in range(9) for d in (-0.018, 0.018)],
                vkeys=[0.86, 0.63, 0.77])
    car.cap(body, zn, 0.0, 1.0, 30, "paint_body", nr=4)
    # the cockpit well: a dark floor and walls under the opening
    car.box("interior_dark", (-0.52, BOT + 0.02, ZC0), (0.52, BOT + 0.06, ZC1))

    # wings: long front wings sweeping into running boards, round rear wings (the 008 Bug's fender, slimmer)
    def fender(zc, z0, z1, x0, a_max, top_y, round_front, round_back, sweep_back, sweep_front):
        def fn(u, v):
            z = np.asarray(u, float); phi = np.asarray(v, float)
            tb = np.clip((z - z0) / round_back, 0, 1) if round_back > 0 else np.ones_like(z)
            tf = np.clip((z1 - z) / round_front, 0, 1) if round_front > 0 else np.ones_like(z)
            e = np.sqrt(1 - (1 - tb) ** 2) * np.sqrt(1 - (1 - tf) ** 2)
            sb = smoothstep(z0 + sweep_back, z0, z) if sweep_back > 0 else np.zeros_like(z)
            sf = smoothstep(z1 - sweep_front, z1, z) if sweep_front > 0 else np.zeros_like(z)
            sw = np.maximum(sb, sf)
            dz = z - zc
            yc = np.where(np.abs(dz) < R_ARCH, R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - dz ** 2, 0, None)), R_TYRE)
            yc = np.maximum(yc, BOT + 0.02)
            yc = yc * (1 - sw) + (BOT + 0.02) * sw
            crown = top_y - 0.10 * np.clip(np.abs(dz) / 0.9, 0, 1) ** 2
            ytop = yc + (crown - yc) * e
            ytop = ytop * (1 - sw) + (BOT + 0.07) * sw
            a = a_max * (0.80 + 0.20 * np.clip(1 - (dz / 0.9) ** 2, 0, 1)) * np.maximum(e, 0.0)
            b = np.maximum(ytop - yc, 1e-4)
            x = x0 + a * sepow(np.cos(phi), 0.8)
            y = yc + b * sepow(np.sin(phi), 0.9)
            return x, y, z
        return fn
    ff = fender(ZF, -0.35, zn - 0.02, X_WHEEL - 0.02, 0.17, 0.88, 0.30, 0.0, 0.90, 0.0)
    fr = fender(ZR, -2.02, -0.42, X_WHEEL - 0.02, 0.17, 0.86, 0.0, 0.30, 0.0, 0.40)
    fenders = (("paint_wing_f", ff, -0.35, zn - 0.02), ("paint_wing_r", fr, -2.02, -0.42))
    for mname, fn, z0, z1 in fenders:
        car.surface(fn, z0, z1, 0.0, math.pi, 34, 12, mirror=True, default=mname,
                    uvfn=lambda u, v, z0=z0, z1=z1: ((u - z0) / (z1 - z0), v / math.pi))
        car.surface(fn, z0, z1, 0.0, math.pi, 34, 4, mirror=True, default="underbody", flip=True,
                    uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for side in (1, -1):
        car.box("running_board_rubber", (min(side * 0.56, side * 1.12), BOT + 0.02, -0.45), (max(side * 0.56, side * 1.12), BOT + 0.06, -0.30))
        # wing stays from the tub to the wings
        car.box("frame", (min(side * 0.40, side * 0.57), 0.76, ZF - 0.03), (max(side * 0.40, side * 0.57), 0.80, ZF + 0.03))

    # grille: an upright chrome waterfall shell at the nose
    car.box("grille", (-0.24, 0.52, zn + 0.00), (0.24, 0.90, zn + 0.05))
    # the shell: an inverted U, across the top and down both sides
    def shell(u):
        t = (u - 0.5) * 2
        x = 0.26 * np.clip(t * 1.5, -1, 1)
        y = 0.92 - 0.40 * np.clip((np.abs(t) - 2 / 3) * 3, 0, 1)
        return np.stack([x, y, zn + 0.05 + 0 * u], 1)
    car.sweep(shell, 0.025, 40, 8, "chrome", caps=False)
    # headlamps on stalks between the grille and the wings, a light bar between them
    for side in (1, -1):
        c = np.array([side * 0.62, 0.88, zn - 0.10])
        car.revolve([(0.11, -0.12), (0.12, -0.04), (0.125, 0.012), (0.110, 0.030)], c, (0, 0, 1), 22, default="chrome", uv_mode="disc")
        car.revolve([(0.110, 0.026), (0.07, 0.042), (0.0, 0.048)], c, (0, 0, 1), 22, default="lamp_head", uv_mode="disc")
        car.sweep(lambda u, side=side: np.stack([side * 0.62 + 0 * u, 0.70 + 0.07 * u, zn - 0.16 + 0 * u], 1), 0.022, 4, 6, "chrome")
        # tail lamps on the rear wings
        car.revolve([(0.05, -0.02), (0.052, 0.02), (0.0, 0.035)], (side * 1.02, 0.80, -1.92), (0, 0.3, -1.0), 14, default="lamp_tail", uv_mode="disc")
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.20, 0.76 + 0 * u, zn - 0.16 + 0 * u], 1), 0.020, 10, 6, "chrome")
    # slim bumpers
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.70, 0.42 + 0 * u, zn + 0.12 - 0.10 * ((u - 0.5) * 2) ** 2], 1), 0.040, 20, 8,
              "chrome", squash=(0.45, 1.0))
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.50, 0.46 + 0 * u, zt - 0.06 + 0.10 * ((u - 0.5) * 2) ** 2], 1), 0.040, 20, 8,
              "chrome", squash=(0.45, 1.0))
    # windscreen: an upright chrome frame with glass, the folded hood behind the seats
    car.box("chrome", (-0.62, 0.96, ZS - 0.03), (0.62, 1.00, ZS + 0.01))
    car.box("chrome", (-0.62, 1.34, ZS - 0.05), (0.62, 1.37, ZS - 0.01))
    for side in (1, -1):
        car.box("chrome", (side * 0.62 - 0.02, 0.96, ZS - 0.05), (side * 0.62 + 0.02, 1.37, ZS + 0.01))
    car.box("glass", (-0.60, 1.00, ZS - 0.035), (0.60, 1.34, ZS - 0.025))
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.22, 0.98 + 0 * u, -1.32 + 0 * u], 1), 0.13, 16, 12, "hood", squash=(1.0, 0.75))
    # spare wheel on the tail
    sc = np.array([0.0, 0.70, zt - 0.10])
    car.revolve([(0.19, -0.08), (0.28, -0.08), (0.30, 0.0), (0.28, 0.08), (0.19, 0.08)], sc, (0, 0.25, -1), 24, default="tyre_side", uv_mode="disc")
    car.revolve([(0.19, 0.08), (0.10, 0.09), (0.0, 0.12)], sc, (0, 0.25, -1), 20, default="chrome", uv_mode="disc")

    # interior: two seats, dash, steering wheel
    for xs in (-0.30, 0.30):
        car.box("seat", (xs - 0.24, BOT + 0.06, -0.80), (xs + 0.24, BOT + 0.20, -0.30))
        car.box("seat", (xs - 0.24, BOT + 0.16, -0.92), (xs + 0.24, 0.98, -0.80))
    car.box("interior_dark", (-0.60, 0.78, ZS - 0.12), (0.60, 0.94, ZS - 0.02))
    car.revolve([(0.17, -0.012), (0.17, 0.012)], (-0.30, 0.94, -0.02), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.66, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.18)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / (zn - zt)
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=[(U(ZS + 0.06), 0.30, 1.0)], lines_v=[(0.98, U(ZS + 0.1), 1.0)], seed=39)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=40)
    for mname, fn, z0, z1 in fenders:
        car.materials[mname] = tex_paint(PAINT, 256, seed=41)
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    for mname, fn, z0, z1 in fenders:
        bake_ao(car, fn, z0, z1, 0.0, math.pi, mname, size=96)
    car.materials["glass"] = tex_glass(256, tint=(58, 74, 88), alpha=110)
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(128, bars=12, rgb=(30, 30, 32))
    car.materials["underbody"] = tex_underbody()
    car.materials["frame"] = tex_flat((30, 30, 32))
    car.materials["trim_dark"] = tex_flat((26, 24, 22))
    car.materials["vent"] = tex_flat((18, 18, 18))
    car.materials["hood"] = tex_leather((34, 32, 30), seams=10)
    car.materials["running_board_rubber"] = tex_flat((34, 33, 32))
    car.materials["interior_dark"] = tex_flat((30, 26, 22))
    car.materials["seat"] = tex_leather((120, 72, 46))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va10/p039.png", LEN)
