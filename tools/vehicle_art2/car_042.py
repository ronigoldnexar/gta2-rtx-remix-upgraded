#!/usr/bin/env python3
"""042 A-Type (VEHICLE-ART-10, audit item 6): the catalog's 1930s streamlined gangster sedan (Cord 810 idiom, the Loonies'
A-Type) read from the GTA2 sprite (front down in the export): a coffin nose wrapped in horizontal chrome louvres
round its sides, a long bonnet with a chrome centre strip (the sprite's), headlamps set flush in the pontoon wing
fronts, a four-door cabin under a long roof falling into a fastback, teardrop tail with small lamps, wrap bumpers,
whitewalls. Painted (neutral, tinted to the identity record). It replaces the image-to-3D shell (crumpled wings,
VEHICLE-ART-8's chrome lamps on melted wings). Built on the 018 Shark's body code without its forward lean.
Metres, +z nose, 1 block = 5 m (catalog body 0.438 x 1.0 blocks: 2.19 x 5.0 m)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "042_a_type"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (150, 92, 58)
LEN = 1.0 * 5.0                 # 5.0 m
HALF_W = 0.438 * 5.0 / 2         # 1.10 m over the wings
ZF, ZR = 1.40, -1.56             # axles (CARI: 17 px forward, 20 back)
R_TYRE, W_TYRE = 0.36, 0.23
X_WHEEL = 0.86
R_ARCH = 0.43
BOT = 0.30
LAMP_X, LAMP_Y, LAMP_Z = 0.72, 0.80, 2.07
HANDLE_X = 0.955
SHEAR = 0.0


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2 - SHEAR - 0.06, -LEN / 2 + 0.07

    belt0 = spline([(zt, 0.72), (-2.0, 0.88), (-1.4, 0.95), (-0.4, 0.96), (0.9, 0.96), (1.6, 0.94), (2.0, 0.90), (zn, 0.82)])
    # roof: a teardrop tail, the long fastback, the roof, the windscreen, the bonnet running out to the prow
    top0 = spline([(zt, 0.74), (-2.25, 0.86), (-1.95, 1.00), (-1.55, 1.18), (-1.05, 1.40), (-0.50, 1.53), (0.10, 1.57),
                   (0.52, 1.53), (0.76, 1.42), (1.04, 1.10), (1.40, 1.06), (1.90, 1.02), (2.20, 0.98), (zn, 0.90)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.16 * np.exp(-((z - ZF) / 0.62) ** 2) + 0.13 * np.exp(-((z - ZR) / 0.70) ** 2)
        base = np.interp(z, [zt, -2.1, -1.5, 1.2, 1.8, zn], [0.62, 0.86, 0.94, 0.94, 0.84, 0.56])
        return base + swell
    tumble0 = spline([(zt, 0.0), (-1.6, 0.0), (-1.0, 0.20), (0.75, 0.22), (1.04, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    NOSE, TAILL = 0.70, 0.55
    def plan(z):
        """plan multipliers: the prow narrows to a rounded vertical edge (a V in plan), the tail closes in a teardrop"""
        fn = np.clip((zn - z) / NOSE, 0, 1)
        fn = 0.38 + 0.62 * (1 - (1 - fn) ** 2.2)
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
        hw = hw0(z) * fn * ft - inset
        belt = belt0(z)
        # the tail's height closes with it (a teardrop); the prow keeps its height (a knife edge)
        fh = 0.15 + 0.85 * ft
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
    side1 = win([(0.92, 0.54), (0.05, 0.54), (0.05, 0.76), (0.66, 0.76)], 0.06)
    side2 = win([(-0.05, 0.54), (-0.95, 0.54), (-0.75, 0.76), (-0.05, 0.76)], 0.07)
    screen = win([(1.02, 0.81), (1.02, 0.985), (0.76, 0.985), (0.76, 0.81)], 0.035)
    backl = win([(-1.05, 0.84), (-1.05, 0.99), (-1.55, 0.99), (-1.55, 0.84)], 0.06)
    glass = sdf_union(side1, side2, screen, backl)
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
    trim = sdf_union(crease, handle)
    # the coffin nose: horizontal louvres wrapping its sides from the prow back over the front wheels' leading edge
    G0, G1, GV0, GV1 = zn - 0.55, zn, 0.26, 0.48
    def grille(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.maximum(G0 - u, u - G1), np.maximum(GV0 - v, v - GV1))
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 80, 34, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chrome", trim), ("grille_back", grille), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / (zn - zt), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, 1.02, 0.76, -1.05, -1.55, 1.02, zn - 0.62],
                vkeys=[0.54, 0.76, 0.81, 0.26, 0.48])
    # the grille itself: its own patch a few mm proud of the dark back, with its own uv (vertical bars)
    car.surface(lambda u, v: body(u, v, inset=-0.008), G0, G1 - 0.01, GV0, GV1, 12, 10, mirror=True, default="grille",
                uvfn=lambda u, v: ((u - G0) / (G1 - G0), (v - GV0) / (GV1 - GV0)))
    car.surface(lambda u, v: body(u, v, inset=0.06), -1.55, 1.04, 0.30, 1.0, 24, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    # front wheel well liners
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, side=side, zc=zc):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.50, 1.02, 16, 2, default="underbody", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    for side in (1, -1):
        # headlamps faired into the wing noses, raked back with the prow
        c = np.array([side * LAMP_X, LAMP_Y, LAMP_Z])
        ax = (side * 0.30, 0.05, 1.0)
        car.revolve([(0.112, -0.10), (0.116, 0.010), (0.104, 0.028)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.104, 0.024), (0.07, 0.040), (0.0, 0.045)], c, ax, 22, default="lamp_head", uv_mode="disc")
        # tail lamps: small teardrops on the rear wings
        car.sweep(lambda u, side=side: np.stack([side * 0.80 + 0 * u, 0.68 + 0.16 * u, zt + 0.30 - 0.05 * u], 1), 0.045, 6, 10,
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
    car.sweep(wrap(LEN / 2 - 0.08, 1, 0.38, 0.92), 0.060, 30, 10, "chrome", squash=(0.45, 1.0))
    car.sweep(wrap(-LEN / 2 + 0.06, -1, 0.40, 0.90), 0.060, 30, 10, "chrome", squash=(0.45, 1.0))
    for zc, y0 in ((LEN / 2 - 0.08, 0.33), (-LEN / 2 + 0.08, 0.35)):
        for side in (1, -1):
            car.sweep(lambda u, x=side * 0.40, zc=zc, y0=y0: np.stack([x + 0 * u, y0 + 0.24 * u, zc + 0 * u], 1), 0.036, 6, 8, "chrome")
    # door handles, a mirror
    for side in (1, -1):
        for zh in (0.20, -0.70):
            car.box("chrome", (side * HANDLE_X - 0.012, 0.91, zh), (side * HANDLE_X + 0.012, 0.94, zh + 0.13))
    car.sweep(lambda u: np.stack([-0.90 - 0.14 * u, 1.02 + 0.05 * u, 0.98 + 0 * u], 1), 0.014, 4, 6, "chrome")
    car.revolve([(0.055, 0.0), (0.055, 0.02), (0.0, 0.03)], (-1.06, 1.09, 0.98), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: bench seats, dash, steering wheel
    car.box("seat", (-0.76, 0.50, -0.05), (0.76, 0.66, 0.50))
    car.box("seat", (-0.76, 0.64, -0.17), (0.76, 1.18, -0.03))
    car.box("seat", (-0.76, 0.50, -1.10), (0.76, 0.66, -0.60))
    car.box("seat", (-0.76, 0.64, -1.22), (0.76, 1.08, -1.08))
    car.box("interior_dark", (-0.84, 0.80, 0.82), (0.84, 1.00, 1.00))
    car.revolve([(0.18, -0.012), (0.18, 0.012)], (-0.38, 0.99, 0.66), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.58, rim_mat="paint_wheel", cap_mat="chrome", whitewall=1.0, cap_dome=0.12)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / (zn - zt)
    lines_u = [(U(0.98), 0.30, 0.52), (U(0.0), 0.30, 0.52), (U(-0.98), 0.30, 0.52), (U(1.10), 0.52, 0.98)]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=42)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=43)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_louvres()
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


def tex_louvres(size=128, bars=9):
    """horizontal chrome louvres on black (the patch's t runs up the nose side)"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    bar = np.abs(((yy * bars) % 1.0) - 0.5) < 0.18
    v = np.where(bar, 120 + 50 * (((yy * bars) % 1.0)), 34)
    return Image.fromarray(np.dstack([v, v, v * 1.03]).clip(0, 255).astype(np.uint8))


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
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va10/p042.png", LEN)
