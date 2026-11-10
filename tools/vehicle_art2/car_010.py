#!/usr/bin/env python3
"""010 Bulwark (VEHICLE-ART-12): a late-1950s American four-door read from the GTA2 sprite (front up in the
export; x4 sheet out/vr_review/sheet_007_014.png): a short bonnet between hooded wing tips (the sprite's bright
corner lamps, a wide chrome grille and a heavy bumper with two guards), a long glasshouse (the sprite's light roof
runs from row 7 to row 46 of 64, its dark outline the side glass), a wrap-around back light, a short dark deck between
two fins that end in tall tail lamps and a centre emblem. It replaces the image-to-3D shell (a 1950s convertible with a
glass box for a cabin, flat bonnet planes and mustard blotches).
Metres, +z nose, 1 block = 5 m (catalog body 0.531 x 1.0 blocks: 2.66 x 5.0 m; axles +21 / -19 px of 64)."""
import math
import os
import sys
import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "010_bulwark"
SPRITE = (209, 164, 116)         # catalog default remap paint
PAINT = (235.0, 235.0, 235.0)    # neutral: the identity record tints it
LEN = 1.0 * 5.0
HALF_W = 0.531 * 5.0 / 2         # 1.33 m
ZF, ZR = 1.64, -1.48             # axles (CARI: 21 px forward, 19 px back)
R_TYRE, W_TYRE = 0.37, 0.25
X_WHEEL = 1.08
R_ARCH = 0.43
BOT = 0.30


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2, -LEN / 2

    # belt: level along the doors, kicking up at the tail into the fin line
    belt0 = spline([(zt, 1.02), (-2.2, 1.06), (-1.7, 1.02), (-1.0, 0.98), (0.8, 0.98), (1.6, 0.97), (2.2, 0.93), (zn, 0.84)])
    # roof: deck, back light, a long flat roof, a raked wrap-around screen, the short bonnet
    top0 = spline([(zt, 1.04), (-2.25, 1.08), (-1.85, 1.10), (-1.62, 1.13), (-1.30, 1.55), (-1.05, 1.66), (0.40, 1.68),
                   (0.80, 1.63), (1.30, 1.15), (1.55, 1.11), (2.1, 1.07), (2.35, 1.02), (zn, 0.90)])
    hw0 = spline([(zt, 1.20), (-2.2, 1.30), (-1.4, 1.33), (1.6, 1.33), (2.2, 1.31), (zn, 1.24)])
    tumble0 = spline([(zt, 0.0), (-1.62, 0.0), (-1.30, 0.20), (0.80, 0.20), (1.25, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    def ends(z, nose=0.38, tail=0.30):
        dn = np.clip((z - (zn - nose)) / nose, 0, 1)
        dt = np.clip(((zt + tail) - z) / tail, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dt ** 2, 0, 1))

    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * (0.88 + 0.12 * f) - inset
        belt = belt0(z)
        fh = 0.80 + 0.20 * f
        top = belt + (top0(z) - belt) * fh - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08)
        bot = belt - (belt - bot) * fh + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z) * hw / 1.33
        xl = hw * (0.93 + 0.07 * sepow(c, 1.2))
        xl = np.where(s > 0.92, hw * (0.93 + 0.07 * sepow(c, 1.2)) * sepow(c, 0.08), xl)
        yl = belt - (belt - bot) * sepow(s, 0.30)
        H = top - belt
        t = np.clip((v - 0.5) / 0.3, 0, 1) * 0.95
        # the deck and bonnet (low H) round off softly; the glasshouse keeps a firm shoulder
        ex = 7.0
        xs = hw * (1 - t ** ex) ** (1 / ex) - tb * t
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** ex) ** (1 / ex) - tb * 0.95
        xr = X0 * (1 - w)
        yr = belt + H * (0.95 + 0.05 * (1 - (1 - w) ** 4) ** 0.25)
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
    # side glass: front door, rear door, a rear quarter light (a hardtop: thin pillars)
    side1 = win([(1.20, 0.535), (0.20, 0.535), (0.20, 0.78), (0.82, 0.78)], 0.03)
    side2 = win([(0.10, 0.535), (-0.95, 0.535), (-0.95, 0.78), (0.10, 0.78)], 0.03)
    side3 = win([(-1.05, 0.535), (-1.50, 0.535), (-1.22, 0.78), (-1.05, 0.78)], 0.03)
    screen = win([(1.24, 0.80), (1.24, 1.03), (0.84, 1.03), (0.84, 0.80)], 0.03)
    backl = win([(-1.10, 0.80), (-1.10, 1.03), (-1.58, 1.03), (-1.58, 0.80)], 0.04)
    glass = sdf_union(side1, side2, side3, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.014
    # chrome: the belt moulding, a side spear from the front wheel back to the fin (dipping over the rear door), the
    # drip rail over the doors
    def spear(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        vc = 0.40 + 0.04 * np.clip((u - 0.2) / 1.2, 0, 1)
        clear = np.minimum(np.abs(u - ZF), np.abs(u - ZR)) - (R_ARCH + 0.04)
        return np.maximum(np.maximum(np.abs(v - vc) * SV - 0.012, np.abs(u + 0.1) - 1.85), -clear)
    belt_chrome = lambda u, v: np.maximum(np.abs(np.asarray(v) - 0.51) * SV - 0.011, np.abs(np.asarray(u) + 0.15) - 1.45)
    under = lambda u, v: np.maximum(np.asarray(v) - 0.30, body(u, v)[1] - (BOT + 0.12))
    car.surface(body, zt, zn, 0.0, 1.0, 72, 30, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chrome", sdf_union(spear, belt_chrome)), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, 1.24, 0.84, -1.10, -1.58, 1.20, 0.20, 0.10, -0.95, -1.05, -1.50],
                vkeys=[0.535, 0.78, 0.80, 0.51, 0.40, 0.44])
    car.cap(body, zt, 0.0, 1.0, 20, "paint_body")
    car.cap(body, zn, 0.0, 1.0, 20, "paint_body", regions=[("underbody", lambda u, v: np.asarray(v) - 0.12)])
    car.surface(lambda u, v: body(u, v, inset=0.06), -1.6, 1.25, 0.30, 1.0, 22, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, zc=zc, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.70, 1.30, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # fins: a blade on each rear wing rising from the rear door to the tail, a tall tail lamp in its end
    for side in (1, -1):
        # the fin: a blade on the rear wing's shoulder, growing from the rear door to the tail lamp
        def fin(u, side=side):
            u = np.asarray(u, float)
            z = -0.95 + (zt + 0.06 + 0.95) * u
            x = side * (hw0(z) * (0.88 + 0.12 * ends(z)) - 0.10 - 0.02 * u)
            y = belt0(z) - 0.01 + 0.26 * np.clip(u, 0, 1) ** 1.5
            return np.stack([x, y, z], 1)
        car.sweep(fin, lambda u: 0.04 + 0.07 * np.clip(np.asarray(u, float), 0, 1) ** 1.2, 24, 10, "paint_fin", squash=(0.40, 1.0))
        car.sweep(lambda u, side=side: np.stack([side * 1.12 + 0 * u, 0.64 + 0.64 * u, zt + 0.06 + 0.03 * u], 1), 0.075, 8, 10,
                  "lamp_tail", squash=(1.0, 0.40))
    # deck emblem (the sprite's bright centre spot)
    car.revolve([(0.07, 0.0), (0.07, 0.015), (0.0, 0.03)], (0, 0.92, zt + 0.02), (0, 0.25, -1), 16, default="chrome", uv_mode="disc")

    # front: hooded lamps in the wing tips, a wide oval grille between them, a bonnet ornament
    def grille_path(u):
        t = (np.asarray(u, float) - 0.5) * 2
        return np.stack([t * 0.80, 0.66 + 0 * t, zn + 0.01 - 0.10 * t ** 2], 1)
    car.box("grille", (-0.80, 0.52, zn - 0.12), (0.80, 0.80, zn + 0.005))
    for yb in (0.50, 0.82):
        car.sweep(lambda u, yb=yb: np.stack([(u - 0.5) * 1.70, yb + 0 * u, zn + 0.01 - 0.06 * ((u - 0.5) * 2) ** 2], 1), 0.024, 16, 8, "chrome")
    for side in (1, -1):
        car.sweep(lambda u, side=side: np.stack([side * 0.85 + 0 * u, 0.50 + 0.32 * u, zn - 0.06 + 0 * u], 1), 0.024, 6, 8, "chrome")
        c = np.array([side * 1.07, 0.80, zn - 0.03])
        ax = (side * 0.10, 0.02, 1)
        car.revolve([(0.125, -0.10), (0.122, 0.0), (0.112, 0.020)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.112, 0.016), (0.08, 0.030), (0.0, 0.036)], c, ax, 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.04, 0.0), (0.04, 0.02), (0.0, 0.028)], (side * 1.02, 0.56, zn - 0.04), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
    car.sweep(lambda u: np.stack([0 * u, 0.95 + 0.04 * np.sin(math.pi * u), zn - 0.12 - 0.30 * u], 1), 0.018, 8, 6, "chrome")
    # bumpers: heavy wraparound chrome, two guards (the sprite's) in front
    def wrap(zc, sign, y):
        def path(u):
            t = (u - 0.5) * 2
            x = t * 1.30
            e = np.clip(np.abs(t) - 0.82, 0, None) / 0.18
            z = zc - sign * (0.06 * t ** 2 + 0.18 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(wrap(zn + 0.06, 1, 0.42), 0.09, 30, 10, "chrome", squash=(0.55, 1.0))
    car.sweep(wrap(zt - 0.05, -1, 0.44), 0.085, 30, 10, "chrome", squash=(0.55, 1.0))
    for side in (1, -1):
        x = side * 0.48
        car.sweep(lambda u, x=x: np.stack([x + 0 * u, 0.34 + 0.40 * u, zn + 0.13 - 0.06 * u], 1), 0.05, 6, 8, "chrome")
    # door handles, mirror
    for side in (1, -1):
        for zh in (0.25, -0.75):
            car.box("chrome", (side * 1.325 - 0.012, 1.00, zh), (side * 1.325 + 0.012, 1.03, zh + 0.15))
    car.sweep(lambda u: np.stack([-1.20 - 0.14 * u, 1.08 + 0.05 * u, 1.10 + 0 * u], 1), 0.014, 4, 6, "chrome")
    car.revolve([(0.06, 0.0), (0.06, 0.02), (0.0, 0.03)], (-1.36, 1.15, 1.10), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: bench seats and a dash
    car.box("seat", (-1.02, 0.55, 0.05), (1.02, 0.72, 0.62))
    car.box("seat", (-1.02, 0.70, -0.08), (1.02, 1.30, 0.06))
    car.box("seat", (-1.02, 0.55, -1.05), (1.02, 0.72, -0.50))
    car.box("seat", (-1.02, 0.70, -1.18), (1.02, 1.28, -1.04))
    car.box("interior_dark", (-1.10, 0.85, 1.10), (1.10, 1.08, 1.25))
    car.revolve([(0.20, -0.012), (0.20, 0.012)], (-0.45, 1.08, 0.85), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.56, rim_mat="paint_wheel", cap_mat="chrome", whitewall=1.0, cap_dome=0.12)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / LEN
    lines_u = [(U(1.22), 0.30, 0.50), (U(0.15), 0.30, 0.50), (U(-0.98), 0.30, 0.50), (U(1.30), 0.50, 1.0), (U(-1.66), 0.50, 1.0)]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=10)
    car.materials["paint_fin"] = tex_paint(PAINT, 64, seed=11)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=12)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_eggcrate()
    car.materials["underbody"] = tex_flat((28, 27, 26))
    car.materials["interior_dark"] = tex_flat((10, 10, 10))
    car.materials["seat"] = tex_leather((120, 92, 70))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    car.materials["whitewall"] = tex_flat((226, 224, 218))
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    return car


def tex_eggcrate(size=128, nx=12, ny=4):
    """a satin chrome egg-crate (the late-1950s grille), shaded cells"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    fx = (xx * nx) % 1.0; fy = (yy * ny) % 1.0
    web = (fx < 0.18) | (fy < 0.22)
    v = np.where(web, 150 + 50 * (1 - fy), 30 + 25 * fy)
    return Image.fromarray(np.dstack([v, v * 0.99, v * 0.97]).clip(0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va12/p010.png", LEN)
