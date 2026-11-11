#!/usr/bin/env python3
"""001 Wellard (VEHICLE-ART-24): the catalog's late-1930s two-door coupe read from the GTA2 sprite nose down
(x4 rows, 0.078 m per sprite px): a very long bonnet (the windscreen's dark band 38-40 px from the nose) with a
chrome spine down its centre, pontoon front wings standing proud of the bonnet with dark valleys between (the
sprite's dark lines from 5 to 22 px), a raked chrome waterfall grille on the prow (the sprite's chrome bars 1-13 px
from the nose), headlamps faired into the wing noses, a short cabin (the roof's highlight 40-53 px), a sloping
back light (53-58 px) and a short tail between swelling rear wings (51-61 px), chrome bumpers, whitewalls.
Built on VEHICLE-ART-21's 070 Z-Type kit body (the same surface recipe; 070 itself is on 018's).
It replaces the image-to-3D shell (a 1955 Thunderbird-like coupe with a dark lettering ghost on the door).
Metres, +z nose, 1 block = 5 m (catalog body 30 x 64 px = 0.469 x 1.0 blocks: 2.34 x 5.0 m; axles +19 / -22 px)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "001_wellard"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (149, 113, 94)
LEN = 1.0 * 5.0                 # 5.0 m
HALF_W = 0.469 * 5.0 / 2         # 1.17 m over the wings
ZF, ZR = 1.48, -1.72             # axles (catalog +19 / -22 px)
R_TYRE, W_TYRE = 0.34, 0.20
X_WHEEL = 0.90
R_ARCH = 0.40   # arch top 0.74: the wing's waist must stay 0.08 above it (a capped arch dipped into the tyre top
                 # and the renderer's wheel split steered those wing faces: a paint shard under the front wheel, va24_a1)
BOT = 0.30
SHEAR = 0.0


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2 - 0.06, -LEN / 2 + 0.07

    # the waist: low over the front wings (their tops), highest along the doors, falling into the tail
    belt0 = spline([(zt, 0.66), (-2.2, 0.80), (-1.8, 0.88), (-1.2, 0.92), (-0.4, 0.93), (-0.05, 0.90), (0.45, 0.84),
                    (1.00, 0.83), (1.90, 0.83), (2.20, 0.76), (zn, 0.60)])
    # roof line: a short tail, the sloping back light, the short coupe roof, the windscreen, the long bonnet running
    # level to the grille's head, the raked grille down to the prow
    top0 = spline([(zt, 0.70), (-2.25, 0.86), (-2.05, 1.00), (-1.80, 1.22), (-1.60, 1.37), (-1.30, 1.46), (-0.95, 1.47),
                   (-0.74, 1.42), (-0.48, 1.10), (-0.20, 1.07), (0.60, 1.06), (1.30, 1.04), (1.66, 0.99), (2.10, 0.80),
                   (zn, 0.62)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.21 * np.exp(-((z - 1.36) / 0.86) ** 4) + 0.21 * np.exp(-((z - ZR) / 0.64) ** 4)
        base = np.interp(z, [zt, -2.2, -1.8, 0.2, 1.6, 2.1, zn], [0.55, 0.84, 0.96, 0.96, 0.92, 0.80, 0.42])
        return base + swell
    # the upper body leans in: a narrow bonnet between the wing tops, the coupe's glasshouse over the doors
    tumble0 = spline([(zt, 0.0), (-2.0, 0.10), (-1.7, 0.26), (-0.50, 0.26), (-0.30, 0.32), (0.50, 0.46), (1.40, 0.52),
                      (2.00, 0.40), (zn, 0.10)])
    # the lean's curve: linear over the doors, a quick roll-in over the front wings (their crown, then the bonnet's
    # steep side rising to the narrow bonnet top: the sprite's dark valleys)
    leanq = lambda z: np.interp(z, [-0.4, 0.5, 2.1, zn], [1.0, 0.42, 0.42, 0.8])

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
        hw = hw0(z) * fn * ft - inset
        belt = belt0(z)
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
        q = leanq(z)
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
    backl = win([(-1.72, 0.84), (-1.72, 0.99), (-2.06, 0.99), (-2.06, 0.84)], 0.06)
    glass = sdf_union(side1, side2, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.014
    G0, G1, GV0 = 1.64, zn, 0.90
    # chrome: the sprite's spine down the bonnet's centre (to the grille's head), the boot handle
    def crease(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.012, np.maximum(-0.32 - u, u - G0))
    def handle(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.05, np.abs(u - (zt + 0.40)) - 0.12)
    trim = sdf_union(crease, handle)
    def grille(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.maximum(G0 - u, u - G1), GV0 - v)
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 84, 34, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chrome", trim), ("grille_back", grille), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / (zn - zt), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, -0.47, -0.73, -1.72, -2.06, -0.32, G0],
                vkeys=[0.54, 0.76, 0.81, 0.30, GV0])
    # the waterfall grille: its own patch a few mm proud of the dark back, bars running fore and aft down the rake
    car.surface(lambda u, v: body(u, v, inset=-0.008), G0, G1 - 0.01, GV0, 1.0, 16, 8, mirror=True, default="grille",
                uvfn=lambda u, v: ((u - G0) / (G1 - G0), (v - GV0) / (1.0 - GV0)))
    car.surface(lambda u, v: body(u, v, inset=0.06), -2.06, -0.40, 0.30, 1.0, 24, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, side=side, zc=zc):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.52, 1.06, 16, 2, default="underbody", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # headlamps faired into the wing noses: the bucket half sunk where the wing face passes x 0.74 at y 0.78
    uu, vv = np.meshgrid(np.linspace(1.6, zn, 200), np.linspace(0.3, 0.7, 120))
    bx, by, bz = body(uu.ravel(), vv.ravel())
    k = np.argmin(np.abs(bx - 0.76) + np.abs(by - 0.78))
    LAMP = np.array([0.74, 0.78, bz[k] - 0.03])
    for side in (1, -1):
        c = LAMP * np.array([side, 1.0, 1.0])
        ax = (side * 0.30, 0.06, 1.0)
        car.revolve([(0.140, -0.16), (0.132, -0.03), (0.118, 0.005)], c, ax, 24, default="paint_wheel", uv_mode="disc")
        car.revolve([(0.118, -0.02), (0.114, 0.014), (0.100, 0.027)], c, ax, 24, default="chrome", uv_mode="disc")
        car.revolve([(0.100, 0.023), (0.074, 0.035), (0.0, 0.041)], c, ax, 24, default="lamp_head", uv_mode="disc")
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
    car.sweep(wrap(LEN / 2 - 0.08, 1, 0.38, 0.98), 0.070, 30, 10, "chrome", squash=(0.45, 1.0))
    car.sweep(wrap(-LEN / 2 + 0.05, -1, 0.40, 0.94), 0.070, 30, 10, "chrome", squash=(0.45, 1.0))
    for zc, y0 in ((LEN / 2 - 0.06, 0.31), (-LEN / 2 + 0.07, 0.33)):
        for side in (1, -1):
            car.sweep(lambda u, x=side * 0.36, zc=zc, y0=y0: np.stack([x + 0 * u, y0 + 0.22 * u, zc + 0 * u], 1), 0.034, 6, 8, "chrome")
    # door handles at the door's rear edge, on the body's face under the belt
    hx, hy, hz = body(np.array([-1.20]), np.array([0.47]))
    hx, hy = float(hx[0]), float(hy[0])
    for side in (1, -1):
        car.box("chrome", (side * hx - 0.012, hy - 0.015, -1.26), (side * hx + 0.012, hy + 0.015, -1.13))
    # the mascot at the grille's head (the sprite's bright spot at 13 px)
    ax_, ay_, az_ = body(np.array([G0 - 0.04]), np.array([1.0]))
    car.sweep(lambda u, y=float(ay_[0]), z=float(az_[0]): np.stack([0 * u, y + 0.01 + 0.06 * u, z - 0.22 * u], 1), 0.020, 8, 8, "chrome",
              squash=(0.5, 1.0))
    # interior: the coupe's bench, dash, steering wheel
    car.box("seat", (-0.74, 0.52, -1.42), (0.74, 0.70, -0.98))
    car.box("seat", (-0.74, 0.68, -1.56), (0.74, 1.16, -1.42))
    car.box("interior_dark", (-0.80, 0.82, -0.66), (0.80, 1.04, -0.46))
    car.revolve([(0.18, -0.012), (0.18, 0.012)], (-0.38, 1.00, -0.76), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.58, rim_mat="paint_wheel", cap_mat="chrome", whitewall=1.0, cap_dome=0.12)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / (zn - zt)
    lines_u = [(U(-0.44), 0.30, 0.52), (U(-1.32), 0.30, 0.52), (U(-0.32), 0.52, 0.98)]   # door shuts, the bonnet's rear edge
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=1)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=2)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_vgrille(128, bars=6)
    car.materials["grille_back"] = tex_flat((14, 14, 15))
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

def tex_vgrille(size=128, bars=9):
    """VEHICLE-ART-12: the Sharknose's horizontal bars wrapping the prow (t = up the patch), satin chrome on a dark
    back, shaded per bar (lit top edge, dark underside), a thin surround; was 14 stark black/white vertical bars"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    f = (yy * bars) % 1.0
    bar = f < 0.58
    shade = np.where(bar, 118 + 62 * (1 - f / 0.58), 34 + 10 * f)
    edge = (yy < 0.045) | (yy > 0.955) | (xx < 0.03)
    v = np.where(edge, 168, shade)
    return Image.fromarray(np.dstack([v, v * 0.99, v * 0.97]).clip(0, 255).astype(np.uint8))


def tex_wgrille(size=128, bars=13):
    """the Z-Type's waterfall grille: narrow vertical chrome bars (across the patch) on a dark back, each lit on one
    edge, a thin bright surround"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    f = (xx * bars) % 1.0
    bar = f < 0.52
    shade = np.where(bar, 112 + 70 * (1 - f / 0.52), 30 + 10 * f)
    edge = (yy < 0.04) | (yy > 0.96) | (xx > 0.97)
    v = np.where(edge, 172, shade)
    return Image.fromarray(np.dstack([v, v * 0.99, v * 0.97]).clip(0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va24/p001.png", LEN)
