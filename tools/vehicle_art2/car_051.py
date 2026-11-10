#!/usr/bin/env python3
"""051 Taxi Xpress (VEHICLE-ART-8, vr-taxi-051-residue): the 050 B-Type's body in the sprite's cab livery (the catalog:
"Checker cab livery on the B-Type": yellow, a chequer belt along each side, a chequer strip down the roof with a sign box
on it, a thin dark pin line down the bonnet and boot, a waterfall grille). It replaces the image-to-3D shell, whose
TRELLIS bake kept door "QR" ghosts, dark spots by the bonnet stripe and a C-pillar stub after VEHICLE-ART-6's repaint.
The 050's description follows.
050 B-Type (VEHICLE-ART-7): a late-1940s American four-door sedan (1948 Plymouth / Checker idiom) read from the
GTA2 sprite: a long rounded roof from the windscreen to a sloping back, front wings that swell round the wheels
and carry the lamps, a rounded bonnet down to a chrome grille with a centre bar (the sprite's chrome nose),
rear wings swelling round the back wheels, heavy chrome bumpers, whitewall tyres. It replaces the image-to-3D
shell, whose bonnet and wings were a crumpled mosaic (vr-generated-bodies-hard-facets).
Metres, +z nose, 1 block = 5 m (catalog body 0.562 x 1.0 blocks: 2.81 x 5.0 m)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa
from PIL import Image
from car_056 import tex_chequer, tex_sign

NAME = "051_taxi_xpress"
# A painted car: the neutral base is multiplied by live paint / own paint (identity.cpp), so every remap shows the
# sprite's colour. SPRITE is the default remap, for previews.
YELLOW = (236, 160, 40)         # the sprite's cab yellow (catalog paint_rgb 240,161,57; a livery: drawn untinted)
PAINT = YELLOW
SPRITE = (255, 255, 255)        # preview: the livery is the colour
LEN = 1.0 * 5.0
HALF_W = 0.562 * 5.0 / 2         # 1.405 m over the wings
ZF, ZR = 1.62, -1.52             # axles (CARI: 21 px forward, 20 px back of 64)
R_TYRE, W_TYRE = 0.37, 0.24
X_WHEEL = 1.07
R_ARCH = 0.44
BOT = 0.30


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2, -LEN / 2

    belt0 = spline([(zt, 0.80), (-2.2, 0.92), (-1.6, 0.99), (-0.6, 1.00), (0.9, 1.00), (1.6, 0.98), (2.15, 0.92), (zn, 0.80)])
    # roof: boot deck, a long sloping back, the roof, the windscreen, the bonnet falling to the nose
    top0 = spline([(zt, 0.84), (-2.35, 0.98), (-2.05, 1.05), (-1.75, 1.12), (-1.25, 1.42), (-0.80, 1.60), (-0.2, 1.66),
                   (0.45, 1.64), (0.75, 1.52), (1.02, 1.16), (1.35, 1.11), (1.90, 1.06), (2.25, 0.98), (zn, 0.84)])
    # plan width: the doors 1.30, the wings swell to 1.405 round each wheel (the 1940s fender line)
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.20 * np.exp(-((z - ZF) / 0.70) ** 2) + 0.19 * np.exp(-((z - ZR) / 0.62) ** 2)
        base = np.interp(z, [zt, -2.2, -1.6, 1.6, 2.2, zn], [1.04, 1.16, 1.20, 1.20, 1.18, 1.10])
        return base + swell
    # the greenhouse tucks in from the flanks (tumblehome)
    tumble0 = spline([(zt, 0.0), (-1.9, 0.0), (-1.3, 0.26), (0.75, 0.26), (1.05, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    def ends(z, nose=0.20, tail=0.22):
        dn = np.clip((z - (zn - nose)) / nose, 0, 1)
        dt = np.clip(((zt + tail) - z) / tail, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dt ** 2, 0, 1))

    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * (0.90 + 0.10 * f) - inset
        belt = belt0(z)
        fh = 0.78 + 0.22 * f
        top = belt + (top0(z) - belt) * fh - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08)
        bot = belt - (belt - bot) * fh + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z) * np.minimum(hw, 1.22) / 1.30
        # rounder flanks than the 1950s cab: the lower body curves under (pontoon)
        xl = hw * sepow(c, 0.42)
        yl = belt - (belt - bot) * sepow(s, 0.55)
        H = top - belt
        t = np.clip((v - 0.5) / 0.3, 0, 1) * 0.95
        xs = hw * (1 - t ** 5) ** (1 / 5) - tb * t
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** 5) ** (1 / 5) - tb * 0.95
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
    side1 = win([(0.86, 0.54), (0.10, 0.54), (0.10, 0.755), (0.54, 0.755)], 0.06)
    side2 = win([(-0.10, 0.54), (-0.94, 0.54), (-0.94, 0.755), (-0.10, 0.755)], 0.06)
    side3 = win([(-1.12, 0.55), (-1.42, 0.55), (-1.20, 0.74), (-1.12, 0.745)], 0.05)
    # split windscreen (two flat panes either side of a centre bar, the 1940s look) and a three-piece back light
    screen = win([(0.98, 0.81), (0.98, 0.985), (0.66, 0.985), (0.66, 0.81)], 0.035)
    backl = win([(-1.12, 0.82), (-1.12, 0.99), (-1.62, 0.99), (-1.62, 0.82)], 0.05)
    glass = sdf_union(side1, side2, side3, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.014
    # the livery: a two-row chequer belt under the chrome spear, clear of the wheel openings; a three-cell chequer strip
    # down the roof from the back light to the windscreen (the sprite's); a dark pin line down the bonnet and the boot
    def band(u, v):
        u = np.asarray(u, float)
        clear = np.minimum(np.abs(u - ZF), np.abs(u - ZR)) - (R_ARCH + 0.05)
        return np.maximum(np.maximum(np.abs(np.asarray(v) - 0.455) * SV - 0.055, np.abs(u + 0.05) - 2.0), -clear)
    roofstrip = lambda u, v: np.maximum((1 - np.asarray(v)) * SV * 1.6 - 0.15, np.abs(np.asarray(u) + 0.23) - 0.87)
    pin = lambda u, v: np.maximum((1 - np.asarray(v)) * SV * 1.6 - 0.022, -(np.abs(np.asarray(u) + 0.23) - 0.90))
    # a chrome spear along the flank at the belt, broken over the wheel openings
    def spear(u, v):
        u = np.asarray(u, float)
        clear = np.minimum(np.abs(u - ZF), np.abs(u - ZR)) - (R_ARCH + 0.02)
        return np.maximum(np.maximum(np.abs(np.asarray(v) - 0.505) * SV - 0.013, np.abs(u - 0.0) - 2.20), -clear)
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 72, 32, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chequer", band), ("chequer_roof", roofstrip), ("pin", pin),
                         ("chrome", spear), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, 0.98, 0.66, -1.12, -1.62],
                vkeys=[0.54, 0.755, 0.81, 0.505, 0.434, 0.476])
    car.cap(body, zt, 0.0, 1.0, 20, "paint_body", regions=[("underbody", lambda u, v: np.asarray(v) - 0.14)])
    car.cap(body, zn, 0.0, 1.0, 20, "paint_body", regions=[("underbody", lambda u, v: np.asarray(v) - 0.14)])
    # the cabin's dark inside (seen through the glass)
    car.surface(lambda u, v: body(u, v, inset=0.06), -1.75, 1.0, 0.30, 1.0, 22, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    # the windscreen's centre bar
    zs0, zs1 = 0.69, 0.95
    ys = lambda z: top0(np.array([z]))[0] + 0.004
    car.sweep(lambda u: np.stack([0 * u, ys(zs0) + (ys(zs1) - ys(zs0)) * u - 0.006, zs0 + (zs1 - zs0) * u], 1), 0.018, 6, 8, "chrome")
    # wheel well liners
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, zc=zc, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.62, 1.30, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # front: a horizontal-bar grille low in the nose with the sprite's chrome centre bar over it
    car.box("grille", (-0.56, 0.50, zn - 0.10), (0.56, 0.78, zn + 0.03))
    # roof sign: a long flat box across the chequer strip (the sprite's dark sign with light slats), TAXI on each face
    sz, top_y = -0.30, top0(np.array([-0.30]))[0]
    car.box("sign_body", (-0.42, top_y - 0.02, sz - 0.36), (0.42, top_y + 0.03, sz + 0.36))
    car.box("sign", (-0.38, top_y + 0.03, sz - 0.32), (0.38, top_y + 0.20, sz + 0.32))
    car.box("sign_top", (-0.39, top_y + 0.20, sz - 0.33), (0.39, top_y + 0.22, sz + 0.33))
    for yb in (0.50, 0.785):
        car.sweep(lambda u, yb=yb: np.stack([(u - 0.5) * 1.16, yb + 0 * u, zn + 0.03 - 0.03 * ((u - 0.5) * 2) ** 2], 1), 0.020, 16, 8, "chrome")
    car.sweep(lambda u: np.stack([0 * u, 0.50 + 0.40 * u, zn + 0.045 - 0.12 * u ** 2], 1), 0.026, 10, 8, "chrome", squash=(0.7, 1.0))
    # bonnet ornament: a chrome spear down the bonnet's centre from the nose
    car.sweep(lambda u: np.stack([0 * u, top0(np.array([2.30 - 0.55 * u]))[0] * (1 + 0 * u) + 0.012, 2.30 - 0.55 * u], 1),
              0.014, 10, 8, "chrome", squash=(1.0, 0.7))
    for side in (1, -1):
        # sealed-beam headlamps in the front of each wing, in a chrome bezel, looking forward
        c = np.array([side * 0.82, 0.78, zn - 0.035])
        car.revolve([(0.112, -0.06), (0.114, 0.012), (0.100, 0.030)], c, (side * 0.06, 0.04, 1), 22, default="chrome", uv_mode="disc")
        car.revolve([(0.100, 0.026), (0.07, 0.038), (0.0, 0.044)], c, (side * 0.06, 0.04, 1), 22, default="lamp_head", uv_mode="disc")
        # parking lamp under it, amber
        car.revolve([(0.040, 0.0), (0.040, 0.02), (0.0, 0.028)], (side * 0.80, 0.56, zn + 0.0), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        # tail lamps: upright red lenses on the rear wings
        car.sweep(lambda u, side=side: np.stack([side * 1.12 + 0 * u, 0.66 + 0.24 * u, zt + 0.16 + 0 * u], 1), 0.060, 6, 10,
                  "lamp_tail", squash=(1.0, 0.5))
    # bumpers: heavy chrome bars wrapping round the corners, with over-riders
    def wrap(zc, sign, y):
        def path(u):
            t = (u - 0.5) * 2
            x = t * 1.28
            e = np.clip(np.abs(t) - 0.80, 0, None) / 0.20
            z = zc - sign * (0.08 * t ** 2 + 0.22 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(wrap(zn + 0.05, 1, 0.42), 0.09, 30, 10, "chrome", squash=(0.55, 1.0))
    car.sweep(wrap(zt - 0.05, -1, 0.44), 0.09, 30, 10, "chrome", squash=(0.55, 1.0))
    for zc, sgn, y0 in ((zn + 0.10, 1, 0.34), (zt - 0.10, -1, 0.36)):
        for side in (1, -1):
            x = side * 0.46
            car.sweep(lambda u, x=x, zc=zc, y0=y0: np.stack([x + 0 * u, y0 + 0.30 * u, zc + 0 * u], 1), 0.042, 6, 8, "chrome")
    # door handles, a mirror
    for side in (1, -1):
        for zh in (0.10, -0.86):
            car.box("chrome", (side * 1.30 - 0.012, 0.95, zh), (side * 1.30 + 0.012, 0.98, zh + 0.14))
    car.sweep(lambda u: np.stack([-1.18 - 0.14 * u, 1.06 + 0.05 * u, 0.95 + 0 * u], 1), 0.014, 4, 6, "chrome")
    car.revolve([(0.06, 0.0), (0.06, 0.02), (0.0, 0.03)], (-1.34, 1.13, 0.95), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: bench seats, a dash, a steering wheel
    car.box("seat", (-1.00, 0.52, -0.20), (1.00, 0.70, 0.40))
    car.box("seat", (-1.00, 0.68, -0.30), (1.00, 1.24, -0.16))
    car.box("seat", (-1.00, 0.52, -1.20), (1.00, 0.70, -0.62))
    car.box("seat", (-1.00, 0.68, -1.32), (1.00, 1.20, -1.18))
    car.box("interior_dark", (-1.08, 0.82, 0.78), (1.08, 1.06, 0.98))
    car.revolve([(0.20, -0.012), (0.20, 0.012)], (-0.48, 1.04, 0.62), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.56, rim_mat="paint_wheel", cap_mat="chrome", whitewall=1.0, cap_dome=0.14)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    # textures
    U = lambda z: (z - zt) / LEN
    lines_u = [(U(0.96), 0.30, 0.50), (U(-0.02), 0.30, 0.50), (U(-1.02), 0.30, 0.50), (U(1.06), 0.50, 0.98), (U(-1.80), 0.50, 0.98)]
    car.materials["paint_body"] = tex_paint(YELLOW, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=51)
    car.materials["chequer"] = tex_chequer(512, cells_u=60, cells_v=2, v0=0.455 - 0.055 / 2.6, v1=0.455 + 0.055 / 2.6)
    car.materials["chequer_roof"] = tex_chequer(512, cells_u=34, cells_v=3, v0=1 - 0.15 / 2.6 / 1.6, v1=1.0, mirror_v=True)
    car.materials["pin"] = tex_flat((28, 34, 70))
    car.materials["sign_body"] = tex_flat((40, 40, 44))
    car.materials["sign"] = tex_sign()
    car.materials["sign_top"] = tex_flat((38, 38, 42))
    car.materials["paint_wheel"] = tex_flat((60, 58, 56))
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(128, bars=8).transpose(Image.ROTATE_90)   # waterfall: vertical bars
    car.materials["underbody"] = tex_flat((28, 27, 26))
    car.materials["interior_dark"] = tex_flat((12, 12, 12))
    car.materials["seat"] = tex_leather((92, 62, 50))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    car.materials["whitewall"] = tex_flat((226, 224, 218))
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va2/p051.png", LEN)
