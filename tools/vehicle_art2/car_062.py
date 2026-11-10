#!/usr/bin/env python3
"""062 Trance-Am (VEHICLE-ART-16): the catalog's late-1960s Trans Am / Firebird muscle coupe read from the GTA2 sprite
(nose down in the export, body 28 x 64 px): a long flat bonnet with a raised shaker scoop and the bird emblem on it,
a chrome beak nose (the sprite's chrome V) between two dark grille openings with round lamps, a raked screen, a long roof
running into a wide wrap-round back light (the sprite's dark band at the tail), a short deck ending in a duck-tail
spoiler, coke-bottle hips over the rear wheels, slotted dark wheels. Painted (neutral 235 tinted to the identity
record; the roof is body hue: audit item 8). It replaces the image-to-3D shell (a dark lumpy body with a sprite-coloured
roof). Derived from car_046.py's loft.
Metres, +z nose, 1 block = 5 m (catalog body 28 x 64 px = 2.19 x 5.0 m; axles +18 / -19 px)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "062_trance_am"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (190, 128, 74)
LEN = 64 / 64 * 5.0              # 5.0 m
HALF_W = 28 / 64 * 5.0 / 2         # 1.09 m
ZF, ZR = 18 / 64 * 5.0, -19 / 64 * 5.0         # +1.41 / -1.48 (CARI)
R_TYRE, W_TYRE = 0.33, 0.24
X_WHEEL = 0.86
R_ARCH = 0.38
BOT = 0.30
SHEAR = 0.0


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2 - 0.10, -LEN / 2 + 0.10

    belt0 = spline([(zt, 0.74), (-1.9, 0.78), (-1.3, 0.79), (0.0, 0.77), (1.2, 0.76), (1.9, 0.74), (zn, 0.66)])
    # centre line: the tail, the small roof set back, the windscreen, the long low bonnet down to the grille
    # a Kamm tail, the fastback falling from the roof, the roof, the raked windscreen, the long bonnet to the grille
    # a boat-tail deck, the fastback falling in one line from the small roof, a raked screen, the long low bonnet
    # a short deck to the spoiler, a wide back light falling from the long roof, a raked screen, the long flat bonnet
    top0 = spline([(zt, 0.86), (-2.20, 0.90), (-1.95, 0.89), (-1.40, 0.95), (-0.95, 1.20), (-0.60, 1.27), (0.00, 1.28),
                   (0.18, 1.24), (0.62, 0.92), (1.10, 0.88), (1.80, 0.85), (2.20, 0.82), (zn, 0.76)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.05 * np.exp(-((z - ZF) / 0.65) ** 2) + 0.07 * np.exp(-((z - ZR) / 0.60) ** 2)
        base = np.interp(z, [zt, -2.0, -1.4, -0.6, 0.4, 1.8, zn], [0.98, 1.02, 1.05, 0.99, 1.00, 0.98, 0.86])
        return base + swell
    tumble0 = spline([(zt, 0.0), (-1.9, 0.0), (-1.3, 0.20), (-0.2, 0.24), (0.55, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    NOSE, TAILL = 0.30, 0.12
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
        crown = 0.04 * smoothstep(0.40, 1.20, z) * (1 - smoothstep(zn - 0.30, zn, z) * 0.5) + 0.06 * np.exp(-((z - ZR) / 0.55) ** 2)
        # a low power bulge down the bonnet's centre (the shaker scoop sits on it), and the duck-tail spoiler's lip
        scoop = 0.030 * np.exp(-((v - 1.0) / 0.10) ** 2) * smoothstep(0.70, 1.10, z) * (1 - smoothstep(2.10, 2.40, z))
        scoop = scoop + 0.07 * smoothstep(zt + 0.28, zt + 0.04, z) * smoothstep(0.82, 0.92, v)
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
    side1 = win([(0.52, 0.56), (-0.40, 0.56), (-0.40, 0.78), (0.20, 0.78)], 0.04)
    side2 = win([(-0.48, 0.56), (-1.10, 0.56), (-0.78, 0.77), (-0.48, 0.77)], 0.04)
    screen = win([(0.58, 0.80), (0.58, 1.03), (0.20, 1.03), (0.20, 0.80)], 0.035)
    # the wide wrap-round back light
    backl = win([(-0.88, 0.79), (-0.88, 1.03), (-1.42, 1.03), (-1.42, 0.82)], 0.05)
    glass = sdf_union(side1, side2, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.014
    # chrome: the bonnet's centre crease, a spear along the flank, the boot handle (the sprite's chrome at the tail)
    def crease(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.012, np.maximum(2.30 - u, u - zn + 0.02))
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
                regions=[("glass", glass), ("interior_dark", seal), ("chrome", crease), ("interior_dark", gills), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / (zn - zt), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, 0.58, 0.20, -0.88, -1.42, 0.52, -0.40, -0.48, -1.10, 2.30],
                vkeys=[0.56, 0.77, 0.78, 0.79, 0.80, 0.82, 0.39, 0.49, 0.99])
    # the nose: a cap over the open front, and on it the upright oval grille with vertical bars and a chrome surround
    car.cap(body, zn, 0.0, 1.0, 24, "paint_body", nr=4, regions=[("underbody", lambda r, v: np.asarray(v) - 0.12)])
    # the beak nose: a dark grille opening each side of the painted centre beak, each with a round lamp, chrome edged
    for side in (1, -1):
        x0, x1 = sorted((side * 0.14, side * 0.78))
        car.box("grille", (x0, 0.44, zn - 0.03), (x1, 0.66, zn + 0.012))
        car.sweep(lambda u, side=side: np.stack([side * (0.14 + 0.64 * u), 0.67 + 0 * u, zn + 0.016 + 0 * u], 1), 0.012, 8, 6, "chrome")
        car.sweep(lambda u, side=side: np.stack([side * (0.14 + 0.64 * u), 0.43 + 0 * u, zn + 0.016 + 0 * u], 1), 0.012, 8, 6, "chrome")
        car.sweep(lambda u, side=side: np.stack([side * 0.13 + 0 * u, 0.43 + 0.24 * u, zn + 0.020 + 0.03 * u], 1), 0.016, 6, 6, "chrome")
    car.surface(lambda u, v: body(u, v, inset=0.06), -1.40, 0.56, 0.30, 1.0, 24, 10, mirror=True, default="interior_dark",
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
        c = np.array([side * 0.58, 0.555, zn + 0.0])
        ax = (0.0, 0.0, 1.0)
        car.revolve([(0.080, -0.07), (0.084, 0.010), (0.074, 0.024)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.074, 0.020), (0.05, 0.032), (0.0, 0.036)], c, ax, 22, default="lamp_head", uv_mode="disc")
        # tail lamps: small teardrops on the rear wings
        # twin round tail lamps in the Kamm tail
        for xl in (0.45, 0.80):
            car.revolve([(0.075, -0.02), (0.075, 0.012), (0.0, 0.020)], (side * xl, 0.72, zt + 0.0), (0, 0, -1), 14,
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
        car.sweep(lambda u, side=side: np.stack([side * (0.0 + 0.92 * u), 0.38 + 0 * u, LEN / 2 - 0.08 - 0.16 * u ** 2], 1),
                  0.045, 16, 10, "chrome", squash=(0.45, 1.0))
    for side in (1, -1):
        car.sweep(lambda u, side=side: np.stack([side * (0.0 + 0.92 * u), 0.50 + 0 * u, -LEN / 2 + 0.06 + 0.14 * u ** 2], 1),
                  0.050, 16, 10, "chrome", squash=(0.45, 1.0))
    # the bonnet scoop: a low fairing on the centre line with a dark mouth
    # door handles, a mirror
    for side in (1, -1):
        for zh in (-0.05,):
            car.box("chrome", (side * 1.005 - 0.012, 0.80, zh - 0.20), (side * 1.005 + 0.012, 0.83, zh - 0.08))
    car.sweep(lambda u: np.stack([-0.90 - 0.10 * u, 0.90 + 0.05 * u, 0.55 + 0 * u], 1), 0.014, 4, 6, "chrome")
    car.revolve([(0.055, 0.0), (0.055, 0.02), (0.0, 0.03)], (-1.02, 0.97, 0.55), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # the shaker scoop: a dark box standing up through the bonnet's bulge with a forward-facing mouth, the bird on the bonnet
    yb = float(top0(np.array([1.30]))[0]) + 0.03
    car.box("interior_dark", (-0.20, yb - 0.04, 1.08), (0.20, yb + 0.10, 1.48))
    car.box("chrome", (-0.20, yb + 0.02, 1.48), (0.20, yb + 0.10, 1.49))
    # interior: bench seats, dash, steering wheel
    for xs in (-0.40, 0.40):
        car.box("seat", (xs - 0.24, 0.36, -0.45), (xs + 0.24, 0.48, 0.00))
        car.box("seat", (xs - 0.24, 0.44, -0.57), (xs + 0.24, 1.02, -0.45))
    car.box("seat", (-0.80, 0.36, -1.20), (0.80, 0.48, -0.85))
    car.box("interior_dark", (-0.90, 0.66, 0.36), (0.90, 0.84, 0.52))
    car.revolve([(0.18, -0.012), (0.18, 0.012)], (-0.40, 0.84, 0.24), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.70, rim_mat="interior_dark", cap_mat="chrome", whitewall=0.0, cap_dome=0.10)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / (zn - zt)
    # door shut lines, the bonnet's rear edge, the boot lid
    lines_u = [(U(0.55), 0.30, 0.56), (U(-0.44), 0.30, 0.56), (U(0.64), 0.62, 0.98), (U(-1.98), 0.80, 0.98)]
    pb = np.asarray(tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=62), float).copy()
    # the bonnet bird, painted dark into the paint picture (luminance only: the record's hue holds). Texel row = v,
    # column = u; near the centre line x ~ X0 (1 - (v - 0.8) / 0.2) with X0 ~ 0.92 m; the half bird is mirrored
    rows, cols = np.mgrid[0:512, 0:512] / 511.0
    zz = zt + cols * (zn - zt)
    xx = 0.92 * (1 - np.clip((rows - 0.8) / 0.2, 0, 1))
    zc = 1.95
    dz = zz - zc
    wing = (xx < 0.30) & (np.abs(dz) < 0.20 - 0.35 * xx) & (dz > -0.12 - 0.20 * xx)
    body_ = (xx < 0.045) & (np.abs(dz) < 0.21)
    head = (xx < 0.06) & (np.abs(dz - 0.20) < 0.05)
    bird = (wing | body_ | head) & (rows > 0.8)
    pb = np.where(bird[..., None], pb * 0.30, pb)
    car.materials["paint_body"] = Image.fromarray(pb.clip(0, 255).astype(np.uint8))
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
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va16/p062.png", LEN)
