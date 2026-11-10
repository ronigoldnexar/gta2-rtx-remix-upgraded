#!/usr/bin/env python3
"""082 Jagular XK (VEHICLE-ART-9): a Jaguar XK120 fixed-head coupe read from the GTA2 sprite and the catalog: a long
low bonnet sunk between two wing crowns that run from the headlamps back to the doors, an upright oval grille with
vertical bars, a small rounded cabin set well back with dark glass, the tail falling in one curve to the bumper,
slim chrome blade bumpers with over-riders. It replaces the image-to-3D shell (a rear
window of irregular dark shape with a baked streak, jagged bumper edges, spiked hubs).
Metres, +z nose (the shipped model's orientation), 1 block = 5 m (catalog body 0.5 x 1.0 blocks: 2.5 x 5.0 m)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "082_jagular_xk"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (139, 87, 45)
LEN = 1.0 * 5.0                 # 5.0 m
HALF_W = 0.5 * 5.0 / 2           # 1.25 m over the wings
ZF, ZR = 1.30, -1.30             # axles (CARI: 18 px forward and back, less the overhang the bumpers take)
R_TYRE, W_TYRE = 0.34, 0.20
X_WHEEL = 0.96
R_ARCH = 0.41
BOT = 0.30
SHEAR = 0.0


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2 - 0.10, -LEN / 2 + 0.10

    belt0 = spline([(zt, 0.62), (-2.0, 0.76), (-1.4, 0.82), (0.0, 0.84), (1.2, 0.82), (2.0, 0.74), (zn, 0.62)])
    # centre line: the tail, the small roof set back, the windscreen, the long low bonnet down to the grille
    top0 = spline([(zt, 0.64), (-2.15, 0.78), (-1.80, 0.92), (-1.40, 1.10), (-1.00, 1.27), (-0.55, 1.35), (-0.15, 1.34),
                   (0.10, 1.27), (0.42, 0.97), (0.90, 0.92), (1.50, 0.89), (2.00, 0.83), (zn, 0.74)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.12 * np.exp(-((z - ZF) / 0.70) ** 2) + 0.12 * np.exp(-((z - ZR) / 0.70) ** 2)
        base = np.interp(z, [zt, -2.1, -1.5, 1.2, 1.9, zn], [0.70, 0.98, 1.08, 1.08, 0.98, 0.72])
        return base + swell
    tumble0 = spline([(zt, 0.0), (-1.5, 0.0), (-1.0, 0.26), (0.12, 0.28), (0.45, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    NOSE, TAILL = 0.40, 0.50
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
        fh = (0.15 + 0.85 * ft) * (0.55 + 0.45 * fn)
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
        crown = 0.14 * smoothstep(0.20, 0.90, z) * (1 - smoothstep(zn - 0.30, zn, z) * 0.5) + 0.07 * np.exp(-((z - ZR) / 0.55) ** 2)
        yu = yu + crown * np.exp(-((v - 0.60) / 0.075) ** 2) * (v > 0.5) - inset * 0
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
    side1 = win([(0.10, 0.56), (-0.92, 0.56), (-0.72, 0.77), (0.10, 0.77)], 0.06)
    screen = win([(0.40, 0.82), (0.40, 0.985), (0.14, 0.985), (0.14, 0.82)], 0.035)
    backl = win([(-1.00, 0.85), (-1.00, 0.99), (-1.38, 0.99), (-1.38, 0.85)], 0.06)
    glass = sdf_union(side1, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.014
    # chrome: the bonnet's centre crease, a spear along the flank, the boot handle (the sprite's chrome at the tail)
    def crease(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.012, np.maximum(1.02 - u, u - zn + 0.02))
    def spear(u, v):
        u = np.asarray(u, float)
        clear = np.abs(u - ZF) - (R_ARCH + 0.02)
        return np.maximum(np.maximum(np.abs(np.asarray(v) - 0.505) * SV - 0.012, np.maximum(u - 2.05, -1.95 - u)), -clear)
    def handle(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.05, np.abs(u - (zt + 0.42)) - 0.12)
    trim = handle
    G0, G1, GV0, GV1 = zn - 0.13, zn, 0.30, 0.52
    def grille(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.maximum(G0 - u, u - G1), np.maximum(GV0 - v, v - GV1))
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 80, 34, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chrome", trim), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / (zn - zt), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, 0.40, 0.14, -1.00, -1.38, 0.10, zn - 0.13],
                vkeys=[0.56, 0.77, 0.82, 0.30, 0.52])
    # the nose: a cap over the open front, and on it the upright oval grille with vertical bars and a chrome surround
    car.cap(body, zn, 0.0, 1.0, 24, "paint_body", nr=4, regions=[("underbody", lambda r, v: np.asarray(v) - 0.12)])
    GX, GY, GC = 0.19, 0.11, 0.565
    def oval(rr, a, dz=0.0):
        rr = np.asarray(rr, float); a = np.asarray(a, float)
        return GX * rr * np.sin(a), GC - GY * rr * np.cos(a), zn + 0.006 + dz + 0.025 * (1 - rr ** 2)
    car.surface(oval, 0.0, 1.0, 0.0, 2 * math.pi, 6, 32, default="grille",
                uvfn=lambda rr, a: (0.5 + 0.5 * rr * np.sin(a), 0.5 - 0.5 * rr * np.cos(a)))
    car.sweep(lambda u: np.stack([GX * np.sin(u * 2 * math.pi), GC - GY * np.cos(u * 2 * math.pi), zn + 0.008 + 0 * u], 1),
              0.016, 40, 8, "chrome", caps=False)
    car.surface(lambda u, v: body(u, v, inset=0.06), -1.45, 0.45, 0.30, 1.0, 24, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    # front wheel well liners
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, side=side, zc=zc):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.60, 1.20, 16, 2, default="underbody", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    for side in (1, -1):
        # headlamps faired into the wing noses, raked back with the prow
        c = np.array([side * 0.66, 0.68, 2.30])
        ax = (side * 0.15, 0.05, 1.0)
        car.revolve([(0.098, -0.07), (0.102, 0.010), (0.090, 0.026)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.090, 0.022), (0.06, 0.036), (0.0, 0.041)], c, ax, 22, default="lamp_head", uv_mode="disc")
        # tail lamps: small teardrops on the rear wings
        car.sweep(lambda u, side=side: np.stack([side * 0.86 + 0 * u, 0.62 + 0.14 * u, zt + 0.22 - 0.05 * u], 1), 0.045, 6, 10,
                  "lamp_tail", squash=(1.0, 0.6))
    # bumpers: chrome blades wrapping round the corners with over-riders
    def wrap(zc, sign, y, half):
        def path(u):
            t = (u - 0.5) * 2
            x = t * half
            e = np.clip(np.abs(t) - 0.80, 0, None) / 0.20
            z = zc - sign * (0.10 * t ** 2 + 0.20 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(wrap(LEN / 2 - 0.06, 1, 0.38, 0.98), 0.055, 30, 10, "chrome", squash=(0.45, 1.0))
    car.sweep(wrap(-LEN / 2 + 0.06, -1, 0.40, 0.96), 0.055, 30, 10, "chrome", squash=(0.45, 1.0))
    for zc, y0 in ((LEN / 2 - 0.05, 0.32), (-LEN / 2 + 0.08, 0.34)):
        for side in (1, -1):
            car.sweep(lambda u, x=side * 0.40, zc=zc, y0=y0: np.stack([x + 0 * u, y0 + 0.24 * u, zc + 0 * u], 1), 0.036, 6, 8, "chrome")
    # door handles, a mirror
    for side in (1, -1):
        for zh in (-0.10,):
            car.box("chrome", (side * 1.09 - 0.012, 0.84, zh), (side * 1.09 + 0.012, 0.87, zh + 0.13))
    car.sweep(lambda u: np.stack([-0.78 - 0.10 * u, 0.92 + 0.05 * u, 1.10 + 0 * u], 1), 0.014, 4, 6, "chrome")
    car.revolve([(0.055, 0.0), (0.055, 0.02), (0.0, 0.03)], (-0.90, 0.99, 1.10), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: bench seats, dash, steering wheel
    for xs in (-0.40, 0.40):
        car.box("seat", (xs - 0.24, 0.42, -0.50), (xs + 0.24, 0.56, -0.05))
        car.box("seat", (xs - 0.24, 0.52, -0.62), (xs + 0.24, 1.06, -0.50))
    car.box("interior_dark", (-0.92, 0.70, 0.28), (0.92, 0.88, 0.44))
    car.revolve([(0.19, -0.012), (0.19, 0.012)], (-0.40, 0.88, 0.18), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.62, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.16)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / (zn - zt)
    lines_u = [(U(0.36), 0.30, 0.56), (U(-0.98), 0.30, 0.56), (U(0.50), 0.66, 0.98), (U(-1.50), 0.70, 0.98)]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=82)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=83)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_vgrille()
    car.materials["grille_back"] = tex_flat((14, 14, 15))
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((12, 12, 12))
    car.materials["seat"] = tex_leather((96, 70, 56))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    car.materials["whitewall"] = tex_flat((226, 224, 218))
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    return car


def tex_vgrille(size=128, bars=14):
    """vertical chrome bars on black, a chrome surround (the cap's uv: s across, t up)"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    bar = np.abs(((xx * bars) % 1.0) - 0.5) < 0.20
    v = np.where(bar, 190 + 30 * (1 - yy), 22)
    edge = (yy < 0.05) | (yy > 0.95)
    v = np.where(edge, 215, v)
    return Image.fromarray(np.dstack([v, v, v * 1.03]).clip(0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va9/p082.png", LEN)
