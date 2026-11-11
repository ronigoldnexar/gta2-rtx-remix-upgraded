#!/usr/bin/env python3
"""031 Jefferson (VEHICLE-ART-27): the catalog's late-1930s streamlined coupe read from the GTA2 sprite nose down
(assets-src/cars/sprites_x4/031_jefferson_default.png, body 26 x 61 px: 2.03 x 4.77 m; axles +18 / -18 px): a long
bonnet with a raised centre spine between pontoon front wings (the sprite's dark valleys), five louvres on each side of
the bonnet before the cowl (20-31 px from the nose), a small arched grille low in the prow with lamps faired into the
wing noses, a long painted dome roof (the sprite's oval 31-53 px, recoloured by every remap: paint) ringed by glass,
a sloping back light and a short tail between swelling rear wings with lamps on their tips.
Built on VEHICLE-ART-24's 001 Wellard recipe: 001's profiles (waist, roof line, plan width, tumble) are evaluated at a
remapped station (the roof drawn out x1.24, the bonnet shortened), the width scaled to the narrower sprite, while the
wheel arches stay round in the 031 frame. It replaces the image-to-3D shell (an E-Type-like open roadster: the wrong
car for the sprite's closed dome coupe). Painted (neutral base, tinted to the identity paint).
Metres, +z nose, 1 block = 5 m."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa
from car_001 import tex_vgrille  # noqa

NAME = "031_jefferson"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (170, 120, 80)
LEN = 61 / 64 * 5.0              # 4.77 m
HALF_W = 26 / 64 * 5.0 / 2       # 1.016 m
WS = 0.87                        # width against 001's
ZF, ZR = 18 / 64 * 5.0, -18 / 64 * 5.0   # axles +1.41 / -1.41
R_TYRE, W_TYRE = 0.33, 0.18
X_WHEEL = 0.79
R_ARCH = 0.39
BOT = 0.30
LEN01 = 5.0
# station map 031 -> 001: tail, back light foot, the roof's front end, the screen's foot, front axle, nose
Z31 = [-LEN / 2 + 0.07, -1.83, -0.45, -0.04, ZF, LEN / 2 - 0.06]
Z01 = [-LEN01 / 2 + 0.07, -2.06, -0.95, -0.48, 1.48, LEN01 / 2 - 0.06]
m = lambda z: np.interp(np.asarray(z, float), Z31, Z01)
mi = lambda z: float(np.interp(z, Z01, Z31))


def tex_louvre(size=128, slots=30):
    """louvres across the bonnet side: dark slots with a lit lip (u along the car; used through the body's uv)"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    f = (xx * slots) % 1.0
    slot = (f > 0.30) & (f < 0.78)
    v = np.where(slot, 40 + 40 * (f - 0.30), 228)
    v = np.where((f > 0.78) & (f < 0.90), 250, v)
    return Image.fromarray(np.dstack([v, v, v]).clip(0, 255).astype(np.uint8))


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2 - 0.06, -LEN / 2 + 0.07
    zn1, zt1 = LEN01 / 2 - 0.06, -LEN01 / 2 + 0.07   # 001's frame, where its profiles are written

    # the waist: low over the front wings (their tops), highest along the doors, falling into the tail
    belt0 = spline([(zt1, 0.66), (-2.2, 0.80), (-1.8, 0.88), (-1.2, 0.92), (-0.4, 0.93), (-0.05, 0.90), (0.45, 0.84),
                    (1.00, 0.83), (1.90, 0.83), (2.20, 0.76), (zn1, 0.60)])
    # roof line: a short tail, the sloping back light, the short coupe roof, the windscreen, the long bonnet running
    # level to the grille's head, the raked grille down to the prow
    top0 = spline([(zt1, 0.70), (-2.25, 0.86), (-2.05, 1.00), (-1.80, 1.22), (-1.60, 1.37), (-1.30, 1.46), (-0.95, 1.47),
                   (-0.74, 1.42), (-0.48, 1.10), (-0.20, 1.07), (0.60, 1.06), (1.30, 1.04), (1.66, 0.99), (2.10, 0.80),
                   (zn1, 0.62)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.21 * np.exp(-((z - 1.36) / 0.86) ** 4) + 0.21 * np.exp(-((z - ZR) / 0.64) ** 4)
        base = np.interp(z, [zt1, -2.2, -1.8, 0.2, 1.6, 2.1, zn1], [0.55, 0.84, 0.96, 0.96, 0.92, 0.80, 0.42])
        return base + swell
    # the upper body leans in: a narrow bonnet between the wing tops, the coupe's glasshouse over the doors
    tumble0 = spline([(zt1, 0.0), (-2.0, 0.10), (-1.7, 0.26), (-0.50, 0.26), (-0.30, 0.32), (0.50, 0.46), (1.40, 0.52),
                      (2.00, 0.40), (zn1, 0.10)])
    # the lean's curve: linear over the doors, a quick roll-in over the front wings (their crown, then the bonnet's
    # steep side rising to the narrow bonnet top: the sprite's dark valleys)
    leanq = lambda z: np.interp(z, [-0.4, 0.5, 2.1, zn1], [1.0, 0.42, 0.42, 0.8])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    NOSE, TAILL = 0.50, 0.55
    def plan(z):
        fn = np.clip((zn - z) / NOSE, 0, 1)
        fn = 0.14 + 0.86 * (1 - (1 - fn) ** 3.2)
        ft = np.clip((z - zt) / TAILL, 0, 1)
        ft = np.sqrt(np.clip(1 - (1 - ft) ** 2, 0, 1))
        return fn, ft

    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        fn, ft = plan(z)
        z1 = m(z)
        hw = hw0(z1) * WS * fn * ft - inset
        belt = belt0(z1)
        fh = 0.15 + 0.85 * ft
        top = belt + (top0(z1) - belt) * fh - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08)
        bot = belt - (belt - bot) * fh + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z1) * WS * np.minimum(hw, 1.10 * WS) / (1.20 * WS)
        xl = hw * sepow(c, 0.42)
        yl = belt - (belt - bot) * sepow(s, 0.55)
        H = top - belt
        t = np.clip((v - 0.5) / 0.3, 0, 1) * 0.95
        q = leanq(z1)
        xs = hw * (1 - t ** 5) ** (1 / 5) - tb * t ** q
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** 5) ** (1 / 5) - tb * 0.95 ** q
        xr = X0 * (1 - w)
        yr = belt + H * (0.90 + 0.10 * (1 - (1 - w) ** 2.2) ** 0.45)
        xu = np.where(v < 0.8, xs, xr)
        yu = np.where(v < 0.8, ys, yr)
        x = np.where(lo, xl, xu); y = np.where(lo, yl, yu)
        return x, y, z

    SU, SV = 1.0, 2.6
    def win(poly, r):
        p = np.array(poly, float)
        c = p.mean(0)
        d = p - c
        shrink = p - d / np.linalg.norm(d * [SU, SV], axis=1, keepdims=True) * r / np.array([SU, SV])
        f = poly_sdf(shrink, SU, SV)
        return lambda u, v: f(u, v) - r
    side1 = win([(-0.50, 0.54), (-1.28, 0.54), (-1.28, 0.76), (-0.76, 0.76)], 0.06)    # the door glass
    side2 = win([(-1.38, 0.54), (-1.88, 0.54), (-1.62, 0.76), (-1.38, 0.76)], 0.07)    # the rear quarter light
    screen = win([(-0.47, 0.81), (-0.47, 0.985), (-0.73, 0.985), (-0.73, 0.81)], 0.035)
    backl = win([(-1.80, 0.88), (-1.80, 0.985), (-2.02, 0.985), (-2.02, 0.88)], 0.05)
    glass1 = sdf_union(side1, side2, screen, backl)
    glass = lambda u, v: glass1(m(u), v)
    seal = lambda u, v: glass(u, v) - 0.014
    G0, G1, GV0 = 1.96, zn, 0.86   # the small arched mouth low in the prow (1-6 px from the nose)
    # chrome: the sprite's spine down the bonnet's centre (to the grille's head), the boot handle
    def crease(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.020, np.maximum(-0.02 - u, u - G0))
    def handle(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.05, np.abs(u - (zt + 0.40)) - 0.12)
    trim = sdf_union(crease, handle)
    # five louvres on each side of the bonnet before the cowl (the sprite's dark slots 20-31 px from the nose)
    LV0, LV1 = 0.805, 0.86
    def louvre(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.maximum(0.05 - u, u - 0.80), np.maximum(LV0 - v, v - LV1))
    def grille(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.maximum(G0 - u, u - G1), GV0 - v)
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 84, 34, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chrome", trim), ("grille_back", grille), ("paint_louvre", louvre), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / (zn - zt), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH] + [mi(k) for k in (-0.47, -0.73, -1.72, -2.06, -0.50, -1.28, -1.38, -1.88)] + [-0.02, G0, 0.05, 0.80],
                vkeys=[0.54, 0.76, 0.81, 0.30, GV0, LV0, LV1])
    # the waterfall grille: its own patch a few mm proud of the dark back, bars running fore and aft down the rake
    car.surface(lambda u, v: body(u, v, inset=-0.008), G0, G1 - 0.01, GV0, 1.0, 16, 8, mirror=True, default="grille",
                uvfn=lambda u, v: ((u - G0) / (G1 - G0), (v - GV0) / (1.0 - GV0)))
    car.surface(lambda u, v: body(u, v, inset=0.06), mi(-2.06), mi(-0.40), 0.30, 1.0, 24, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, side=side, zc=zc):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.46, 0.92, 16, 2, default="underbody", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # headlamps faired into the wing noses: the bucket half sunk where the wing face passes x 0.74 at y 0.78
    uu, vv = np.meshgrid(np.linspace(1.5, zn, 200), np.linspace(0.3, 0.7, 120))
    bx, by, bz = body(uu.ravel(), vv.ravel())
    k = np.argmin(np.abs(bx - 0.66) + np.abs(by - 0.74))
    LAMP = np.array([0.64, 0.74, bz[k] - 0.03])
    for side in (1, -1):
        c = LAMP * np.array([side, 1.0, 1.0])
        ax = (side * 0.30, 0.06, 1.0)
        car.revolve([(0.120, -0.16), (0.114, -0.03), (0.102, 0.005)], c, ax, 24, default="paint_wheel", uv_mode="disc")
        car.revolve([(0.102, -0.02), (0.098, 0.014), (0.086, 0.027)], c, ax, 24, default="chrome", uv_mode="disc")
        car.revolve([(0.086, 0.023), (0.064, 0.035), (0.0, 0.041)], c, ax, 24, default="lamp_head", uv_mode="disc")
        tx, ty, tz = body(np.array([zt + 0.30]), np.array([0.34]))
        car.sweep(lambda u, side=side, tx=float(tx[0]), tz=float(tz[0]): np.stack([side * (tx - 0.01) + 0 * u, 0.62 + 0.15 * u, tz - 0.04 * u], 1),
                  0.040, 6, 10, "lamp_tail", squash=(1.0, 0.6))
    # the grille's chrome surround: a strip along the prow's centre line from the grille's head to its foot
    def prow(t):
        u = G0 + (zn - 0.004 - G0) * np.asarray(t, float)
        x, y, z = body(u, np.full_like(u, 1.0))
        return np.stack([0 * u, y + 0.010, z + 0.004], 1)
    car.sweep(prow, 0.026, 20, 10, "chrome", up=(0, 0, 1), squash=(0.6, 1.0))
    # bumpers: chrome blades wrapping round the corners with over-riders
    def wrap(zc, sign, y, half):
        def path(u):
            t = (u - 0.5) * 2
            x = t * half
            e = np.clip(np.abs(t) - 0.80, 0, None) / 0.20
            z = zc - sign * (0.10 * t ** 2 + 0.20 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(wrap(LEN / 2 - 0.08, 1, 0.38, 0.86), 0.060, 30, 10, "chrome", squash=(0.45, 1.0))
    car.sweep(wrap(-LEN / 2 + 0.05, -1, 0.40, 0.82), 0.060, 30, 10, "chrome", squash=(0.45, 1.0))
    for zc, y0 in ((LEN / 2 - 0.06, 0.31), (-LEN / 2 + 0.07, 0.33)):
        for side in (1, -1):
            car.sweep(lambda u, x=side * 0.30, zc=zc, y0=y0: np.stack([x + 0 * u, y0 + 0.22 * u, zc + 0 * u], 1), 0.034, 6, 8, "chrome")
    # door handles at the door's rear edge, on the body's face under the belt
    hx, hy, hz = body(np.array([-0.80]), np.array([0.47]))
    hx, hy = float(hx[0]), float(hy[0])
    for side in (1, -1):
        car.box("chrome", (side * hx - 0.012, hy - 0.015, -0.86), (side * hx + 0.012, hy + 0.015, -0.73))
    # the mascot at the grille's head (the sprite's bright spot at 13 px)
    ax_, ay_, az_ = body(np.array([G0 - 0.04]), np.array([1.0]))
    car.sweep(lambda u, y=float(ay_[0]), z=float(az_[0]): np.stack([0 * u, y + 0.01 + 0.06 * u, z - 0.22 * u], 1), 0.020, 8, 8, "chrome",
              squash=(0.5, 1.0))
    # interior: the coupe's bench, dash, steering wheel
    car.box("seat", (-0.62, 0.52, -1.10), (0.62, 0.70, -0.66))
    car.box("seat", (-0.62, 0.68, -1.24), (0.62, 1.12, -1.10))
    car.box("interior_dark", (-0.70, 0.80, -0.24), (0.70, 1.00, -0.06))
    car.revolve([(0.17, -0.012), (0.17, 0.012)], (-0.32, 0.96, -0.36), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.58, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.14)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / (zn - zt)
    lines_u = [(U(mi(-0.44)), 0.30, 0.52), (U(mi(-1.32)), 0.30, 0.52), (U(-0.02), 0.52, 0.98)]   # door shuts, the bonnet's rear edge
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=31)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=2)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_vgrille(128, bars=6)
    car.materials["grille_back"] = tex_flat((14, 14, 15))
    car.materials["paint_louvre"] = tex_louvre()
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((12, 12, 12))
    car.materials["seat"] = tex_leather((96, 70, 56))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    car.materials["whitewall"] = tex_flat((226, 224, 218))
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va27/p031.png", LEN)
