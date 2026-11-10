#!/usr/bin/env python3
"""046 Stinger (VEHICLE-ART-16): the catalog's 1963 Corvette Sting Ray coupe read from the GTA2 sprite (nose down in the
export, body 30 x 62 px): a long low bonnet narrowing to a pointed prow with a centre bulge (the sprite's V), wing
creases, a short raked screen, a small roof whose centre spine runs down the fastback and splits the rear window in two
(the sprite's two small rear panes), a short boat-tail deck with two round lamps each side, gill vents behind the front
wheels, split chrome bumperettes, a dark low grille under the prow, faired lamps at the wing tips. Painted (neutral 235,
tinted to the identity record: the sprite's lighter roof is the body hue, audit item 8). It replaces the image-to-3D
shell (a dark lumpy body with a sprite-coloured roof). Based on car_053.py's fastback loft.
Metres, +z nose, 1 block = 5 m (catalog body 30 x 62 px = 2.34 x 4.84 m; axles +20 / -22 px)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "046_stinger"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (184, 120, 72)
LEN = 0.969 * 5.0               # 4.84 m
HALF_W = 0.469 * 5.0 / 2         # 1.17 m over the wings
ZF, ZR = 20 / 64 * 5.0, -22 / 64 * 5.0 + 0.10      # +1.56 / -1.62 (CARI; the rear pulled in for the boat tail)
R_TYRE, W_TYRE = 0.31, 0.22
X_WHEEL = 0.92
R_ARCH = 0.38
BOT = 0.30
SHEAR = 0.0


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2 - 0.10, -LEN / 2 + 0.10

    belt0 = spline([(zt, 0.62), (-1.9, 0.70), (-1.3, 0.73), (0.0, 0.73), (1.2, 0.72), (1.9, 0.66), (zn, 0.52)])
    # centre line: the tail, the small roof set back, the windscreen, the long low bonnet down to the grille
    # a Kamm tail, the fastback falling from the roof, the roof, the raked windscreen, the long bonnet to the grille
    # a boat-tail deck, the fastback falling in one line from the small roof, a raked screen, the long low bonnet
    top0 = spline([(zt, 0.66), (-2.05, 0.76), (-1.70, 0.86), (-1.30, 0.98), (-0.85, 1.10), (-0.45, 1.18), (-0.15, 1.19),
                   (0.08, 1.13), (0.52, 0.84), (1.00, 0.80), (1.60, 0.76), (2.05, 0.68), (zn, 0.56)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.08 * np.exp(-((z - ZF) / 0.65) ** 2) + 0.10 * np.exp(-((z - ZR) / 0.65) ** 2)
        base = np.interp(z, [zt, -2.0, -1.4, 1.1, 1.8, zn], [0.80, 0.98, 1.05, 1.05, 0.96, 0.66])
        return base + swell
    tumble0 = spline([(zt, 0.0), (-2.1, 0.0), (-1.4, 0.26), (-0.1, 0.30), (0.50, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    NOSE, TAILL = 0.60, 0.30
    def plan(z):
        """plan multipliers: the prow narrows to a rounded vertical edge (a V in plan), the tail closes in a teardrop"""
        fn = np.clip((zn - z) / NOSE, 0, 1)
        fn = np.sqrt(np.clip(1 - (1 - fn) ** 2, 0, 1))
        ft = np.clip((z - zt) / TAILL, 0, 1)
        ft = np.sqrt(np.clip(1 - (1 - ft) ** 2, 0, 1))
        return fn, ft

    def shear(z, y):
        """the shark nose: toward the prow the body's upper part is pushed forward"""
        w = smoothstep(zn - 1.0, zn, z)
        return SHEAR * w * np.clip((y - 0.40) / 0.60, 0, 1) ** 1.2

    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        fn, ft = plan(z)
        hw = hw0(z) * (0.55 + 0.45 * fn) * ft - inset
        belt = belt0(z)
        # the tail's height closes with it (a teardrop); the prow keeps its height (a knife edge)
        fh = (0.70 + 0.30 * ft) * (0.55 + 0.45 * fn)
        top = belt + (top0(z) - belt) * fh - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08)
        bot = belt - (belt - bot) * fh + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z) * np.minimum(hw, 1.10) / 1.20
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
        # the wing crowns: the front wings stand above the bonnet from the lamps back to the doors, the rear wings
        # swell over the spats; the bonnet between them is the valley
        crown = 0.07 * smoothstep(0.40, 1.20, z) * (1 - smoothstep(zn - 0.30, zn, z) * 0.5) + 0.06 * np.exp(-((z - ZR) / 0.55) ** 2)
        # the bonnet's low central scoop: a bulge on the centre line rising toward its open mouth
        # the bonnet's centre bulge (the sprite's V) and the roof spine running down the fastback to the tail
        scoop = 0.045 * np.exp(-((v - 1.0) / 0.07) ** 2) * smoothstep(0.60, 1.10, z) * (1 - smoothstep(1.90, 2.25, z))
        scoop = scoop + 0.022 * np.exp(-((v - 1.0) / 0.018) ** 2) * smoothstep(-0.40, -0.70, z) * (1 - smoothstep(-2.10, -2.30, z))
        yu = yu + (crown * np.exp(-((v - 0.60) / 0.075) ** 2) + scoop) * (v > 0.5) - inset * 0
        x = np.where(lo, xl, xu); y = np.where(lo, yl, yu)
        return x, y, z + shear(z, y)

    SU, SV = 1.0, 2.6
    def win(poly, r):
        p = np.array(poly, float)
        c = p.mean(0)
        d = p - c
        shrink = p - d / np.linalg.norm(d * [SU, SV], axis=1, keepdims=True) * r / np.array([SU, SV])
        f = poly_sdf(shrink, SU, SV)
        return lambda u, v: f(u, v) - r
    side1 = win([(0.44, 0.56), (-0.62, 0.56), (-0.48, 0.77), (0.14, 0.77)], 0.05)
    side2 = win([(-0.70, 0.56), (-1.08, 0.56), (-0.58, 0.76)], 0.03)
    screen = win([(0.50, 0.80), (0.50, 0.99), (0.10, 0.99), (0.10, 0.80)], 0.035)
    # the split rear window: one pane each side of the spine (v 0.965 .. 1 stays paint: the bar)
    backl = win([(-0.66, 0.86), (-0.66, 0.955), (-1.42, 0.955), (-1.42, 0.88)], 0.04)
    glass = sdf_union(side1, side2, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.014
    # chrome: the bonnet's centre crease, a spear along the flank, the boot handle (the sprite's chrome at the tail)
    def crease(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.012, np.maximum(0.62 - u, u - zn + 0.02))
    def spear(u, v):
        u = np.asarray(u, float)
        clear = np.abs(u - ZF) - (R_ARCH + 0.02)
        return np.maximum(np.maximum(np.abs(np.asarray(v) - 0.505) * SV - 0.012, np.maximum(u - 2.05, -1.95 - u)), -clear)
    def handle(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.05, np.abs(u - (zt + 0.20)) - 0.10)
    def gills(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        d = None
        for k in range(3):
            zc = ZF - R_ARCH - 0.12 - 0.11 * k
            s = np.maximum((np.abs(u - zc) - 0.022) * SV, np.abs(v - 0.44) - 0.05)
            d = s if d is None else np.minimum(d, s)
        return d
    def louvres(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        d = None
        for k in range(5):
            zc = 0.62 + 0.09 * k
            s = np.maximum(np.abs(u - zc) - 0.018, np.abs(np.abs(v - 1.0) * SV - 0.10) - 0.07)
            d = s if d is None else np.minimum(d, s)
        return d
    def mouth(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.abs(u - 1.555) - 0.05, np.abs(v - 1.0) * SV - 0.075)
    trim = handle
    G0, G1, GV0, GV1 = zn - 0.13, zn, 0.30, 0.52
    def grille(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.maximum(G0 - u, u - G1), np.maximum(GV0 - v, v - GV1))
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 80, 34, mirror=True,
                regions=[("glass", glass), ("interior_dark", seal), ("interior_dark", gills), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / (zn - zt), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, 0.50, 0.10, -0.66, -1.42, 0.44, -0.62, -0.70, -1.08],
                vkeys=[0.56, 0.77, 0.80, 0.86, 0.88, 0.955, 0.965, 0.39, 0.49, 0.99])
    # the nose: a cap over the open front, and on it the upright oval grille with vertical bars and a chrome surround
    car.cap(body, zn, 0.0, 1.0, 24, "paint_body", nr=4, regions=[("underbody", lambda r, v: np.asarray(v) - 0.12)])
    GX, GY, GC = 0.46, 0.060, 0.36
    def oval(rr, a, dz=0.0):
        rr = np.asarray(rr, float); a = np.asarray(a, float)
        return GX * rr * np.sin(a), GC - GY * rr * np.cos(a), zn + 0.006 + dz + 0.025 * (1 - rr ** 2)
    car.surface(oval, 0.0, 1.0, 0.0, 2 * math.pi, 6, 32, default="grille",
                uvfn=lambda rr, a: (0.5 + 0.5 * rr * np.sin(a), 0.5 - 0.5 * rr * np.cos(a)))
    car.sweep(lambda u: np.stack([GX * np.sin(u * 2 * math.pi), GC - GY * np.cos(u * 2 * math.pi), zn + 0.008 + 0 * u], 1),
              0.016, 40, 8, "chrome", caps=False)
    car.surface(lambda u, v: body(u, v, inset=0.06), -1.50, 0.48, 0.30, 1.0, 24, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    # front wheel well liners
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, side=side, zc=zc):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.60, 1.00, 16, 2, default="underbody", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    for side in (1, -1):
        # headlamps faired into the wing noses, raked back with the prow
        c = np.array([side * 0.56, 0.58, 2.12])
        ax = (side * 0.25, 0.10, 1.0)
        car.revolve([(0.080, -0.07), (0.084, 0.010), (0.074, 0.024)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.074, 0.020), (0.05, 0.032), (0.0, 0.036)], c, ax, 22, default="lamp_head", uv_mode="disc")
        # tail lamps: small teardrops on the rear wings
        # twin round tail lamps in the Kamm tail
        for xl in (0.40, 0.62):
            car.revolve([(0.055, -0.02), (0.055, 0.015), (0.0, 0.025)], (side * xl, 0.60, zt + 0.06), (0, 0, -1), 14,
                        default="lamp_tail", uv_mode="disc")
    # bumpers: chrome blades wrapping round the corners with over-riders
    def wrap(zc, sign, y, half):
        def path(u):
            t = (u - 0.5) * 2
            x = t * half
            e = np.clip(np.abs(t) - 0.80, 0, None) / 0.20
            z = zc - sign * (0.10 * t ** 2 + 0.20 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    # slim split bumpers each side of the grille, a full blade at the tail
    for side in (1, -1):
        car.sweep(lambda u, side=side: np.stack([side * (0.38 + 0.50 * u), 0.34 + 0 * u, LEN / 2 - 0.08 - 0.22 * u ** 2], 1),
                  0.040, 16, 10, "chrome", squash=(0.45, 1.0))
    for side in (1, -1):
        car.sweep(lambda u, side=side: np.stack([side * (0.16 + 0.62 * u), 0.40 + 0 * u, -LEN / 2 + 0.10 + 0.20 * u ** 2], 1),
                  0.036, 16, 10, "chrome", squash=(0.45, 1.0))
    # the bonnet scoop: a low fairing on the centre line with a dark mouth
    # door handles, a mirror
    for side in (1, -1):
        for zh in (-0.05,):
            car.box("chrome", (side * 1.055 - 0.012, 0.72, zh), (side * 1.055 + 0.012, 0.75, zh + 0.12))
    car.sweep(lambda u: np.stack([-0.80 - 0.10 * u, 0.84 + 0.05 * u, 0.48 + 0 * u], 1), 0.014, 4, 6, "chrome")
    car.revolve([(0.055, 0.0), (0.055, 0.02), (0.0, 0.03)], (-0.92, 0.91, 0.48), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: bench seats, dash, steering wheel
    for xs in (-0.40, 0.40):
        car.box("seat", (xs - 0.24, 0.30, -0.55), (xs + 0.24, 0.42, -0.10))
        car.box("seat", (xs - 0.24, 0.38, -0.67), (xs + 0.24, 0.94, -0.55))
    car.box("interior_dark", (-0.90, 0.60, 0.28), (0.90, 0.78, 0.44))
    car.revolve([(0.18, -0.012), (0.18, 0.012)], (-0.40, 0.78, 0.16), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.66, rim_mat="chrome", cap_mat="chrome", whitewall=0.0, cap_dome=0.16)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / (zn - zt)
    # door shut lines, the bonnet's rear edge, the boot lid
    lines_u = [(U(0.46), 0.30, 0.56), (U(-0.66), 0.30, 0.56), (U(0.56), 0.62, 0.98), (U(-1.95), 0.70, 0.98)]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=46)
    car.materials["glass"] = tex_glass(128, tint=(30, 38, 46), alpha=195)
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_vgrille(64, bars=10)
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((14, 14, 15))
    car.materials["seat"] = tex_leather((110, 40, 34), 64)
    car.materials["lamp_head"] = tex_lamp("head", 64)
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["tyre_tread"] = tex_tread(128)
    car.materials["tyre_side"] = tex_tyre_side()
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    return car


def tex_vgrille(size=128, bars=14):
    """an egg-crate of chrome bars on black, a chrome surround (the cap's uv: s across, t up)"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    bar = (np.abs(((xx * bars) % 1.0) - 0.5) < 0.16) | (np.abs(((yy * 5) % 1.0) - 0.5) < 0.12)
    v = np.where(bar, 170 + 30 * (1 - yy), 20)
    edge = (yy < 0.05) | (yy > 0.95)
    v = np.where(edge, 215, v)
    return Image.fromarray(np.dstack([v, v, v * 1.03]).clip(0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va16/p046.png", LEN)
