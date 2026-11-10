#!/usr/bin/env python3
"""035 Benson (VEHICLE-ART-22, qav55 "shredded see-through shell"): the catalog's 1950s Mercedes-Benz Ponton /
300 'Adenauer' sedan, narrow and tall, read from the GTA2 sprite nose down (assets-src/cars/sprites_x4/
035_benson_default.png, body 32 x 64 px): a long bonnet with a centre ridge down to a tall upright chrome-framed
grille (the sprite's bright nose) with low horizontal side grilles, slab pontoon flanks with only a faint swell
round the wheels, round lamps in the wing fronts, an upright dignified four-door greenhouse (the sprite's dark
windscreen 25 px and back light 49 px from the nose) under the sprite's pale roof, a short rounded boot, small
upright tail lamps, heavy chrome bumpers, whitewalls. Built on VEHICLE-ART-7's 050 B-Type surface recipe.
It replaces the image-to-3D shell (alpha-torn panels hanging as black shards, no glass found by car_glass, so a
seated car drew the 40 % FIX-SEATED band: the ghost canopy with the driver showing through).
Metres, +z nose, 1 block = 5 m (catalog body 0.5 x 1.0 blocks: 2.5 x 5.0 m; axles +19 / -15 px)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "035_benson"
# A painted car: the neutral base is multiplied by live paint / own paint (identity.cpp), so every remap shows the
# sprite's colour. SPRITE is the default remap, for previews.
PAINT = (235.0, 235.0, 235.0)
SPRITE = (161, 126, 105)
LEN = 1.0 * 5.0
HALF_W = 0.5 * 5.0 / 2           # 1.25 m over the wings
ZF, ZR = 1.48, -1.17             # axles (CARI: 19 px forward, 15 px back of 64)
R_TYRE, W_TYRE = 0.36, 0.22
X_WHEEL = 0.96
R_ARCH = 0.43
BOT = 0.30


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2 - 0.15, -LEN / 2 + 0.12   # the body inside the bumpers: bumper to bumper is the sprite's 5.0 m

    belt0 = spline([(zt, 0.86), (-2.2, 0.95), (-1.6, 0.99), (-0.6, 1.00), (0.6, 1.00), (1.6, 0.99), (2.2, 0.95), (zn, 0.86)])
    # roof: a short rounded boot, an upright back light, a tall flat roof, an upright windscreen, the long bonnet
    top0 = spline([(zt, 0.90), (-2.30, 1.02), (-2.00, 1.08), (-1.62, 1.11), (-1.40, 1.16), (-1.22, 1.50), (-0.95, 1.70),
                   (-0.2, 1.75), (0.30, 1.73), (0.50, 1.64), (0.68, 1.22), (1.00, 1.17), (1.70, 1.12), (2.25, 1.04), (zn, 0.93)])
    # plan width: slab pontoon flanks 1.18, only a faint swell round the wheels
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.07 * np.exp(-((z - ZF) / 0.70) ** 2) + 0.07 * np.exp(-((z - ZR) / 0.62) ** 2)
        base = np.interp(z, [zt, -2.2, -1.6, 1.6, 2.2, zn], [0.98, 1.10, 1.16, 1.16, 1.12, 1.02])
        return base + swell
    # the tall greenhouse tucks in only a little (upright)
    tumble0 = spline([(zt, 0.0), (-1.45, 0.0), (-1.20, 0.17), (0.50, 0.17), (0.70, 0.0), (zn, 0.0)])

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
        tb = tumble0(z) * np.minimum(hw, 1.14) / 1.20
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
    side1 = win([(0.62, 0.54), (-0.22, 0.54), (-0.22, 0.765), (0.46, 0.765)], 0.05)    # front door glass
    side2 = win([(-0.34, 0.54), (-1.00, 0.54), (-1.00, 0.765), (-0.34, 0.765)], 0.05)  # rear door glass
    side3 = win([(-1.08, 0.55), (-1.28, 0.55), (-1.14, 0.75), (-1.08, 0.755)], 0.04)  # quarter light
    # split windscreen (two flat panes either side of a centre bar, the 1940s look) and a three-piece back light
    screen = win([(0.66, 0.81), (0.66, 1.04), (0.52, 1.04), (0.52, 0.81)], 0.03)   # one piece across the centre
    backl = win([(-1.24, 0.82), (-1.24, 1.04), (-1.38, 1.04), (-1.38, 0.82)], 0.03)
    glass = sdf_union(side1, side2, side3, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.014
    # a chrome spear along the flank at the belt, broken over the wheel openings
    def spear(u, v):
        u = np.asarray(u, float)
        clear = np.minimum(np.abs(u - ZF), np.abs(u - ZR)) - (R_ARCH + 0.02)
        return np.maximum(np.maximum(np.abs(np.asarray(v) - 0.505) * SV - 0.013, np.abs(u - 0.0) - 2.20), -clear)
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 72, 32, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chrome", spear), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, 0.66, 0.52, -1.24, -1.38],
                vkeys=[0.54, 0.765, 0.81, 0.505])
    car.cap(body, zt, 0.0, 1.0, 20, "paint_body", regions=[("underbody", lambda u, v: np.asarray(v) - 0.14)])
    car.cap(body, zn, 0.0, 1.0, 20, "paint_body", regions=[("underbody", lambda u, v: np.asarray(v) - 0.14)])
    # the cabin's dark inside (seen through the glass)
    car.surface(lambda u, v: body(u, v, inset=0.06), -1.40, 0.68, 0.30, 1.0, 22, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    # wheel well liners
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, zc=zc, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.60, 1.06, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # the wing front at the lamp's place, found on the body (the nose rounds back toward the corners)
    uu, vv = np.meshgrid(np.linspace(zn - 0.5, zn, 160), np.linspace(0.3, 0.7, 120))
    bx, by, bz = body(uu.ravel(), vv.ravel())
    k = np.argmin(np.abs(bx - 0.80) + np.abs(by - 0.80))
    LZ = float(bz[k])
    k2 = np.argmin(np.abs(bx - 0.50) + np.abs(by - 0.56))
    GZ = float(bz[k2])
    # front: the Ponton's tall upright grille in a heavy chrome frame (the sprite's bright nose), its top a
    # rounded arch standing a little proud of the bonnet's nose, and low horizontal grilles either side of it
    GX, GY0, GY1 = 0.24, 0.48, 0.94
    car.box("grille", (-GX, GY0, zn - 0.08), (GX, GY1, zn + 0.05))
    def gframe(u):
        a = (np.asarray(u, float) * 2 - 1) * math.pi / 2       # -pi/2 .. pi/2 up one side, over the top, down
        x = GX * np.sin(a) * 1.04
        y = np.where(np.abs(a) > 1.2, GY1 - 0.06 - (np.abs(a) - 1.2) / (math.pi / 2 - 1.2) * (GY1 - 0.06 - GY0), GY1 - 0.06 + 0.06 * np.cos(a / 1.2 * math.pi / 2))
        return np.stack([x, y, np.full_like(x, zn + 0.055)], 1)
    car.sweep(gframe, 0.026, 40, 8, "chrome", squash=(0.8, 1.0))
    car.sweep(lambda u: np.stack([(u - 0.5) * 2 * GX * 1.04, GY0 + 0 * u, zn + 0.055 + 0 * u], 1), 0.024, 10, 8, "chrome")
    car.sweep(lambda u: np.stack([0 * u, GY0 + (GY1 - GY0) * u, zn + 0.06 + 0 * u], 1), 0.014, 8, 6, "chrome")   # the centre bar
    for side in (1, -1):
        car.box("grille", (min(side * 0.30, side * 0.66), 0.50, GZ - 0.10), (max(side * 0.30, side * 0.66), 0.62, GZ + 0.012))
        car.sweep(lambda u, side=side: np.stack([side * (0.30 + 0.36 * u), 0.625 + 0 * u, GZ + 0.015 - 0.0 * u], 1), 0.014, 10, 6, "chrome")
    # the three-pointed star on a short stalk at the head of the bonnet
    car.sweep(lambda u: np.stack([0 * u, GY1 + 0.005 + 0.07 * u, zn - 0.03 + 0 * u], 1), 0.010, 6, 6, "chrome")
    car.revolve([(0.040, -0.004), (0.040, 0.004)], (0.0, GY1 + 0.11, zn - 0.03), (0, 0, 1), 16, default="chrome", uv_mode="disc")
    for side in (1, -1):
        # sealed-beam headlamps in the front of each wing, in a chrome bezel, looking forward
        c = np.array([side * 0.80, 0.80, LZ - 0.01])
        car.revolve([(0.112, -0.06), (0.114, 0.012), (0.100, 0.030)], c, (side * 0.06, 0.04, 1), 22, default="chrome", uv_mode="disc")
        car.revolve([(0.100, 0.026), (0.07, 0.038), (0.0, 0.044)], c, (side * 0.06, 0.04, 1), 22, default="lamp_head", uv_mode="disc")
        # parking lamp under it, amber
        car.revolve([(0.040, 0.0), (0.040, 0.02), (0.0, 0.028)], (side * 0.84, 0.60, LZ - 0.02), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        # tail lamps: upright red lenses on the rear wings
        car.sweep(lambda u, side=side: np.stack([side * 0.86 + 0 * u, 0.62 + 0.22 * u, zt + 0.10 + 0 * u], 1), 0.055, 6, 10,
                  "lamp_tail", squash=(1.0, 0.5))
    # bumpers: heavy chrome bars wrapping round the corners, with over-riders
    def wrap(zc, sign, y):
        def path(u):
            t = (u - 0.5) * 2
            x = t * 1.16
            e = np.clip(np.abs(t) - 0.80, 0, None) / 0.20
            z = zc - sign * (0.08 * t ** 2 + 0.22 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(wrap(zn + 0.07, 1, 0.40), 0.085, 30, 10, "chrome", squash=(0.55, 1.0))
    car.sweep(wrap(zt - 0.03, -1, 0.42), 0.085, 30, 10, "chrome", squash=(0.55, 1.0))
    for zc, sgn, y0 in ((zn + 0.10, 1, 0.34), (zt - 0.10, -1, 0.36)):
        for side in (1, -1):
            x = side * 0.42
            car.sweep(lambda u, x=x, zc=zc, y0=y0: np.stack([x + 0 * u, y0 + 0.30 * u, zc + 0 * u], 1), 0.042, 6, 8, "chrome")
    # door handles (on the flank under the belt), a mirror
    hxh = float(body(np.array([-0.40]), np.array([0.47]))[0][0])
    for side in (1, -1):
        for zh in (-0.12, -0.92):
            car.box("chrome", (side * hxh - 0.012, 0.95, zh), (side * hxh + 0.012, 0.98, zh + 0.14))
    car.sweep(lambda u: np.stack([-1.08 - 0.14 * u, 1.06 + 0.05 * u, 0.66 + 0 * u], 1), 0.014, 4, 6, "chrome")
    car.revolve([(0.06, 0.0), (0.06, 0.02), (0.0, 0.03)], (-1.24, 1.13, 0.66), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: bench seats, a dash, a steering wheel
    car.box("seat", (-0.92, 0.52, -0.30), (0.92, 0.70, 0.22))
    car.box("seat", (-0.92, 0.68, -0.40), (0.92, 1.24, -0.26))
    car.box("seat", (-0.92, 0.52, -1.12), (0.92, 0.70, -0.66))
    car.box("seat", (-0.92, 0.68, -1.22), (0.92, 1.20, -1.08))
    car.box("interior_dark", (-0.98, 0.82, 0.44), (0.98, 1.06, 0.62))
    car.revolve([(0.20, -0.012), (0.20, 0.012)], (-0.44, 1.04, 0.28), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.56, rim_mat="paint_wheel", cap_mat="chrome", whitewall=1.0, cap_dome=0.14)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    # textures
    U = lambda z: (z - zt) / LEN
    lines_u = [(U(0.68), 0.30, 0.50), (U(-0.28), 0.30, 0.50), (U(-1.04), 0.30, 0.50), (U(0.74), 0.50, 0.98), (U(-1.58), 0.50, 0.98)]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=35)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=36)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(128, bars=12)
    car.materials["underbody"] = tex_underbody()
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
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va22/p035.png", LEN)
