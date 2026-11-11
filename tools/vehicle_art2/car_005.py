#!/usr/bin/env python3
"""005 Beamer (VEHICLE-ART-24): the catalog's mid-1950s two-seat roadster with its hardtop up, read from the GTA2
sprite nose down (x4 rows, 0.078 m per sprite px): a full-width envelope body (32 px) with a domed bonnet over 27 px
(the sprite's centre highlight) and round headlamps in the wing tops' front corners (the bright discs 7-11 px from
the nose, 11 px off the centre line), a wide low grille with a chrome centre (the nose's bright bar), a raked screen
(27-31 px), the dark fabric hardtop over the cabin (the sprite's grey-blue dome from 31 to 53 px: the same grey in
every remap, so it is not paint), a small back light at its tail, a short rounded boot between the rear wings'
crowns (55-58 px), chrome bumpers, whitewalls.
Built on 001's kit body (VEHICLE-ART-24, itself on 070's). It replaces the image-to-3D shell, which drew near-black
from every ground pose and white from above (its paint mask split along the shell's lumps).
Metres, +z nose, 1 block = 5 m (catalog body 32 x 64 px = 0.5 x 1.0 blocks: 2.5 x 5.0 m; axles +18 / -19 px)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "005_beamer"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (127, 98, 82)
LEN = 1.0 * 5.0
HALF_W = 0.5 * 5.0 / 2           # 1.25 m
ZF, ZR = 1.40, -1.48             # axles (catalog +18 / -19 px)
R_TYRE, W_TYRE = 0.33, 0.20
X_WHEEL = 0.98
R_ARCH = 0.39                    # arch top 0.72: the waist stays >= 0.08 above it (wheel split, see car_001)
BOT = 0.28


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2 - 0.06, -LEN / 2 + 0.07

    # the waist: one level line round the envelope body, a touch up over the rear wings' crowns, down at the ends
    belt0 = spline([(zt, 0.62), (-2.15, 0.76), (-1.85, 0.84), (-1.2, 0.82), (0.0, 0.81), (1.0, 0.81), (1.9, 0.80),
                    (2.25, 0.72), (zn, 0.58)])
    # roof line: the rounded boot, the hardtop's small back light, its dome, the raked screen, the domed bonnet
    # falling to the low nose
    top0 = spline([(zt, 0.66), (-2.15, 0.84), (-1.92, 0.92), (-1.75, 1.06), (-1.45, 1.26), (-1.00, 1.33), (-0.40, 1.34),
                   (0.06, 1.30), (0.40, 0.98), (0.80, 0.96), (1.50, 0.92), (2.05, 0.84), (zn, 0.66)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.05 * np.exp(-((z - ZF) / 0.60) ** 4) + 0.06 * np.exp(-((z - ZR) / 0.60) ** 4)
        base = np.interp(z, [zt, -2.1, -1.7, 1.7, 2.2, zn], [0.70, 1.08, 1.19, 1.19, 1.08, 0.70])
        return base + swell
    # the upper body: a gentle shoulder round the bonnet, the hardtop's tumble home over the doors
    tumble0 = spline([(zt, 0.05), (-1.95, 0.20), (-1.6, 0.42), (-0.2, 0.44), (0.30, 0.30), (1.0, 0.24), (2.0, 0.24),
                      (zn, 0.12)])
    leanq = lambda z: np.interp(z, [-1.6, -0.2, 0.4, zn], [1.0, 1.0, 0.7, 0.7])

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
    side1 = win([(0.34, 0.54), (-0.86, 0.54), (-0.86, 0.77), (0.06, 0.77)], 0.06)     # the door glass
    side2 = win([(-0.96, 0.54), (-1.56, 0.54), (-1.30, 0.75), (-0.96, 0.75)], 0.07)   # the hardtop's quarter light
    screen = win([(0.39, 0.81), (0.39, 0.985), (0.10, 0.985), (0.10, 0.81)], 0.035)
    backl = win([(-1.62, 0.86), (-1.62, 0.99), (-1.86, 0.99), (-1.86, 0.86)], 0.05)
    glass = sdf_union(side1, side2, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.014
    # the hardtop: everything above the waist from the screen's head to the back light's foot (not paint: the sprite's
    # grey dome is the same in every remap)
    def hardtop(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.maximum(u - 0.10, -1.88 - u), 0.53 - v)
    G0, G1 = zn - 0.10, zn
    GV0, GV1 = 0.24, 0.52
    # chrome: a spine on the bonnet's dome, the boot handle, a belt moulding along the flank
    def crease(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.010, np.maximum(0.50 - u, u - (zn - 0.30)))
    def handle(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.05, np.abs(u - (zt + 0.40)) - 0.12)
    def moulding(u, v):
        u = np.asarray(u, float)
        clear = np.minimum(np.abs(u - ZF), np.abs(u - ZR)) - (R_ARCH + 0.03)
        return np.maximum(np.maximum(np.abs(np.asarray(v) - 0.40) * SV - 0.010, np.maximum(u - 2.10, -2.0 - u)), -clear)
    trim = sdf_union(crease, handle, moulding)
    def grille(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.maximum(G0 - u, u - G1), np.maximum(GV0 - v, v - GV1))
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 84, 34, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("rubber_top", hardtop), ("chrome", trim), ("grille_back", grille),
                         ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / (zn - zt), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, 0.39, 0.10, -1.62, -1.86, -1.88, G0],
                vkeys=[0.54, 0.77, 0.81, 0.30, GV0, GV1, 0.53])
    # the grille: its own patch a few mm proud of the dark back (horizontal bars)
    car.surface(lambda u, v: body(u, v, inset=-0.008), G0, G1 - 0.01, GV0, GV1, 12, 10, mirror=True, default="grille",
                uvfn=lambda u, v: ((u - G0) / (G1 - G0), (v - GV0) / (GV1 - GV0)))
    car.surface(lambda u, v: body(u, v, inset=0.06), -1.86, 0.40, 0.30, 1.0, 24, 10, mirror=True, default="interior_dark",
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
    k = np.argmin(np.abs(bx - 0.86) + np.abs(by - 0.70))
    LAMP = np.array([0.86, 0.70, bz[k] - 0.03])
    for side in (1, -1):
        c = LAMP * np.array([side, 1.0, 1.0])
        ax = (side * 0.18, 0.10, 1.0)
        car.revolve([(0.140, -0.16), (0.132, -0.03), (0.118, 0.005)], c, ax, 24, default="paint_wheel", uv_mode="disc")
        car.revolve([(0.118, -0.02), (0.114, 0.014), (0.100, 0.027)], c, ax, 24, default="chrome", uv_mode="disc")
        car.revolve([(0.100, 0.023), (0.074, 0.035), (0.0, 0.041)], c, ax, 24, default="lamp_head", uv_mode="disc")
        tx, ty, tz = body(np.array([zt + 0.22]), np.array([0.30]))
        car.sweep(lambda u, side=side, tx=float(tx[0]), tz=float(tz[0]): np.stack([side * (tx - 0.01) + 0 * u, 0.58 + 0.12 * u, tz - 0.03 * u], 1),
                  0.040, 6, 10, "lamp_tail", squash=(1.0, 0.6))
    # the sprite's bright centre bar: a chrome bar across the grille's middle
    gx, gy, gz = body(np.array([zn - 0.02]), np.array([0.38]))
    car.sweep(lambda u, y=float(gy[0]), z=float(gz[0]): np.stack([(u - 0.5) * 0.9, y + 0 * u, z + 0.02 - 0.10 * ((u - 0.5) * 2) ** 2], 1),
              0.018, 16, 8, "chrome")
    # bumpers: chrome blades wrapping round the corners with over-riders
    def wrap(zc, sign, y, half):
        def path(u):
            t = (u - 0.5) * 2
            x = t * half
            e = np.clip(np.abs(t) - 0.80, 0, None) / 0.20
            z = zc - sign * (0.10 * t ** 2 + 0.20 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(wrap(LEN / 2 - 0.06, 1, 0.36, 1.06), 0.070, 30, 10, "chrome", squash=(0.45, 1.0))
    car.sweep(wrap(-LEN / 2 + 0.05, -1, 0.38, 1.02), 0.070, 30, 10, "chrome", squash=(0.45, 1.0))
    for zc, y0 in ((LEN / 2 - 0.06, 0.31), (-LEN / 2 + 0.07, 0.33)):
        for side in (1, -1):
            car.sweep(lambda u, x=side * 0.42, zc=zc, y0=y0: np.stack([x + 0 * u, y0 + 0.22 * u, zc + 0 * u], 1), 0.034, 6, 8, "chrome")
    # door handles at the door's rear edge, on the body's face under the belt
    hx, hy, hz = body(np.array([-0.76]), np.array([0.47]))
    hx, hy = float(hx[0]), float(hy[0])
    for side in (1, -1):
        car.box("chrome", (side * hx - 0.012, hy - 0.015, -0.82), (side * hx + 0.012, hy + 0.015, -0.69))
    # interior: the coupe's bench, dash, steering wheel
    for sx in (1, -1):   # two buckets
        car.box("seat", (sx * 0.10, 0.48, -0.86), (sx * 0.72, 0.64, -0.40))
        car.box("seat", (sx * 0.10, 0.62, -1.00), (sx * 0.72, 1.08, -0.86))
    car.box("interior_dark", (-0.10, 0.40, -0.90), (0.10, 0.62, 0.30))   # the tunnel
    car.box("interior_dark", (-0.86, 0.72, 0.18), (0.86, 0.92, 0.38))    # the dash
    car.box("interior_dark", (-0.90, 0.60, -1.60), (0.90, 0.90, -1.05))  # the parcel shelf
    car.revolve([(0.18, -0.012), (0.18, 0.012)], (-0.40, 0.92, 0.06), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.58, rim_mat="paint_wheel", cap_mat="chrome", whitewall=1.0, cap_dome=0.12)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / (zn - zt)
    lines_u = [(U(0.42), 0.30, 0.53), (U(-0.90), 0.30, 0.53), (U(0.46), 0.53, 0.98), (U(-1.96), 0.56, 0.98)]   # door shuts, bonnet and boot edges
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=5)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=6)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_vgrille(128, bars=7)
    car.materials["rubber_top"] = tex_leather((58, 60, 70), seams=4)
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
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va24/p005.png", LEN)
