#!/usr/bin/env python3
"""057 T-Rex (VEHICLE-ART-10): the catalog's 1955-57 Ford Thunderbird hardtop read from the GTA2 sprite (front down in
the export): a long low flat-sided two-seater with a straight belt line, a bonnet scoop on the centre line, hooded
headlamps at the wing tips over a wide oval egg-crate grille and a heavy chrome bumper with two guards, a wrap-around
windscreen with chrome pillars, the sprite's dark hardtop (a black roof with a porthole in each rear quarter and a
small upright back light), a short rear deck between two small fins ending in round tail lamps, a chrome spear down
the flank, wrap-around rear bumper. Painted (neutral, tinted to the identity record); the hardtop is a fixed dark
gloss (the sprite's roof is dark in every remap). It replaces the image-to-3D shell (VEHICLE-ART-8/9: geo_paint
painted its chrome and lost the dark roof). Metres, +z nose, 1 block = 5 m (catalog body 0.469 x 1.0 blocks:
2.34 x 5.0 m)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "057_t_rex"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (180, 118, 70)
LEN = 1.0 * 5.0                 # 5.0 m
HALF_W = 0.469 * 5.0 / 2         # 1.17 m over the wings
ZF, ZR = 1.48, -1.36             # axles (CARI: 20 px forward, 18 back, less the bumpers)
R_TYRE, W_TYRE = 0.33, 0.22
X_WHEEL = 0.92
R_ARCH = 0.40
BOT = 0.30
SHEAR = 0.0


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2 - 0.10, -LEN / 2 + 0.10

    belt0 = spline([(zt, 0.80), (-1.9, 0.84), (-1.3, 0.85), (0.0, 0.85), (1.2, 0.85), (1.9, 0.84), (zn, 0.78)])
    # centre line: the rear deck, the hardtop's upright back light, the flat hardtop, the wrap windscreen, the bonnet
    top0 = spline([(zt, 0.86), (-1.90, 0.92), (-1.32, 0.94), (-1.22, 1.06), (-1.10, 1.30), (-0.90, 1.36), (-0.10, 1.37),
                   (0.20, 1.34), (0.62, 0.99), (0.90, 0.97), (1.60, 0.95), (2.10, 0.90), (zn, 0.82)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.02 * np.exp(-((z - ZF) / 0.65) ** 2) + 0.02 * np.exp(-((z - ZR) / 0.65) ** 2)
        base = np.interp(z, [zt, -2.2, -1.4, 1.1, 2.0, zn], [1.00, 1.08, 1.12, 1.12, 1.08, 0.96])
        return base + swell
    tumble0 = spline([(zt, 0.0), (-1.35, 0.0), (-1.05, 0.22), (0.10, 0.24), (0.62, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    NOSE, TAILL = 0.30, 0.16
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
        fh = (0.80 + 0.20 * ft) * (0.75 + 0.25 * fn)
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
        # the small fins: the rear wing tops rise toward the tail
        crown = 0.08 * smoothstep(-1.2, zt + 0.10, z) + 0.02 * smoothstep(0.6, 1.4, z)
        # the bonnet's low central scoop: a bulge on the centre line rising toward its open mouth
        scoop = 0.06 * np.exp(-((v - 1.0) / 0.05) ** 2) * smoothstep(0.85, 1.55, z) * (1 - smoothstep(1.60, 1.72, z))
        yu = yu + (crown * np.exp(-((v - 0.58) / 0.06) ** 2) + scoop) * (v > 0.5) - inset * 0
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
    side1 = win([(0.52, 0.57), (-0.50, 0.57), (-0.50, 0.78), (0.30, 0.78)], 0.05)
    screen = win([(0.60, 0.80), (0.60, 0.985), (0.24, 0.985), (0.24, 0.80)], 0.03)
    backl = win([(-1.08, 0.84), (-1.08, 0.97), (-1.24, 0.97), (-1.24, 0.84)], 0.03)
    def porthole(u, v):
        return np.hypot(np.asarray(u, float) + 0.80, (np.asarray(v, float) - 0.68) * SV) - 0.12
    glass = sdf_union(side1, screen, backl, porthole)
    # the hardtop: everything above the belt between the windscreen header and the deck, round the glass
    def hardtop(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum.reduce([-1.27 - u, u - 0.27, 0.575 - v])
    def pillars(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum.reduce([0.24 - u, u - 0.64, 0.575 - v])
    def ring(u, v):
        return np.abs(porthole(u, v) + 0.012) - 0.018
    seal = lambda u, v: glass(u, v) - 0.014
    # chrome: the bonnet's centre crease, a spear along the flank, the boot handle (the sprite's chrome at the tail)
    def crease(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.012, np.maximum(1.02 - u, u - zn + 0.02))
    def spear(u, v):
        u = np.asarray(u, float)
        clear = np.abs(u - ZF) - (R_ARCH + 0.02)
        return np.maximum(np.maximum(np.abs(np.asarray(v) - 0.505) * SV - 0.014, np.maximum(u - 1.00, -2.20 - u)), -clear)
    def handle(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.05, np.abs(u - (zt + 0.20)) - 0.10)
    def mouth(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.abs(u - 1.665) - 0.05, np.abs(v - 1.0) * SV - 0.075)
    trim = sdf_union(handle, spear)
    G0, G1, GV0, GV1 = zn - 0.13, zn, 0.30, 0.52
    def grille(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.maximum(G0 - u, u - G1), np.maximum(GV0 - v, v - GV1))
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 80, 34, mirror=True,
                regions=[("glass", glass), ("chrome", ring), ("seal", seal), ("chrome", pillars), ("hardtop", hardtop), ("chrome", trim),
                         ("vent", mouth), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / (zn - zt), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, 0.60, 0.24, 0.52, -0.50, -1.08, -1.24, -1.27, 0.27, 0.64, -0.80],
                vkeys=[0.57, 0.575, 0.78, 0.80, 0.84, 0.97, 0.985, 0.505, 0.68])
    # the nose: a cap over the open front, and on it the upright oval grille with vertical bars and a chrome surround
    car.cap(body, zn, 0.0, 1.0, 24, "paint_body", nr=4, regions=[("underbody", lambda r, v: np.asarray(v) - 0.12)])
    GX, GY, GC = 0.52, 0.11, 0.56
    def oval(rr, a, dz=0.0):
        rr = np.asarray(rr, float); a = np.asarray(a, float)
        return GX * rr * np.sin(a), GC - GY * rr * np.cos(a), zn + 0.006 + dz + 0.025 * (1 - rr ** 2)
    car.surface(oval, 0.0, 1.0, 0.0, 2 * math.pi, 6, 32, default="grille",
                uvfn=lambda rr, a: (0.5 + 0.5 * rr * np.sin(a), 0.5 - 0.5 * rr * np.cos(a)))
    car.sweep(lambda u: np.stack([GX * np.sin(u * 2 * math.pi), GC - GY * np.cos(u * 2 * math.pi), zn + 0.008 + 0 * u], 1),
              0.016, 40, 8, "chrome", caps=False)
    car.surface(lambda u, v: body(u, v, inset=0.06), -1.26, 0.62, 0.30, 1.0, 24, 10, mirror=True, default="interior_dark",
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
        c = np.array([side * 0.78, 0.70, zn - 0.02])
        ax = (side * 0.10, 0.0, 1.0)
        # the hood over the lamp: a peak of the wing
        car.revolve([(0.135, -0.20), (0.135, -0.02), (0.112, 0.02)], c, ax, 22, default="paint_body", uv_mode="disc")
        car.revolve([(0.106, -0.02), (0.110, 0.020), (0.096, 0.036)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.096, 0.032), (0.06, 0.046), (0.0, 0.051)], c, ax, 22, default="lamp_head", uv_mode="disc")
        # tail lamps: small teardrops on the rear wings
        # round tail lamps at the fin ends, a chrome ring round each
        tl = (side * 0.80, 0.80, zt - 0.005)
        car.revolve([(0.11, -0.03), (0.115, 0.012), (0.10, 0.028)], tl, (0, 0, -1), 18, default="chrome", uv_mode="disc")
        car.revolve([(0.10, 0.024), (0.06, 0.040), (0.0, 0.046)], tl, (0, 0, -1), 18, default="lamp_tail", uv_mode="disc")
    # bumpers: chrome blades wrapping round the corners with over-riders
    def wrap(zc, sign, y, half):
        def path(u):
            t = (u - 0.5) * 2
            x = t * half
            e = np.clip(np.abs(t) - 0.80, 0, None) / 0.20
            z = zc - sign * (0.10 * t ** 2 + 0.20 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    # heavy wrap-around bumpers, two guards at the front, exhaust ports at the rear
    car.sweep(wrap(LEN / 2 - 0.06, 1, 0.42, 1.06), 0.075, 30, 10, "chrome", squash=(0.50, 1.0))
    car.sweep(wrap(-LEN / 2 + 0.06, -1, 0.46, 1.04), 0.070, 30, 10, "chrome", squash=(0.50, 1.0))
    for side in (1, -1):
        car.sweep(lambda u, x=side * 0.36: np.stack([x + 0 * u, 0.36 + 0.40 * u, LEN / 2 - 0.02 - 0.06 * u], 1), 0.045, 6, 8, "chrome")
        car.revolve([(0.05, 0.0), (0.05, 0.02), (0.0, 0.02)], (side * 0.62, 0.46, -LEN / 2 + 0.005), (0, 0, -1), 12, default="vent", uv_mode="disc")
    # the bonnet scoop: a low fairing on the centre line with a dark mouth
    # door handles, a mirror
    for side in (1, -1):
        for zh in (-0.05,):
            car.box("chrome", (side * 1.13 - 0.012, 0.84, zh), (side * 1.13 + 0.012, 0.87, zh + 0.12))
    car.sweep(lambda u: np.stack([-0.86 - 0.10 * u, 0.96 + 0.05 * u, 0.62 + 0 * u], 1), 0.014, 4, 6, "chrome")
    car.revolve([(0.055, 0.0), (0.055, 0.02), (0.0, 0.03)], (-0.98, 1.03, 0.62), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: bench seats, dash, steering wheel
    for xs in (-0.40, 0.40):
        car.box("seat", (xs - 0.26, 0.38, -0.55), (xs + 0.26, 0.52, -0.10))
        car.box("seat", (xs - 0.26, 0.48, -0.67), (xs + 0.26, 1.04, -0.55))
    car.box("interior_dark", (-0.95, 0.74, 0.40), (0.95, 0.92, 0.58))
    car.revolve([(0.20, -0.012), (0.20, 0.012)], (-0.42, 0.92, 0.28), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.62, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.22, cap_dome=0.14)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / (zn - zt)
    lines_u = [(U(0.56), 0.30, 0.565), (U(-0.62), 0.30, 0.565), (U(0.70), 0.66, 0.98), (U(-1.32), 0.70, 0.98)]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=57)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=58)
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
    car.materials["vent"] = tex_flat((16, 16, 17))
    car.materials["hardtop"] = tex_paint((26, 28, 32), 256, seed=59)
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
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va10/p057.png", LEN)
