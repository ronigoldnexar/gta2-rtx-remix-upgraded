#!/usr/bin/env python3
"""070 Z-Type (VEHICLE-ART-21, qav50): the catalog's late-1930s streamlined coupe (Lincoln-Zephyr / Cord era) read
from the GTA2 sprite nose down: a long bonnet with the sprite's chrome centre strip ending in an arrow ornament at
the nose, an upright narrow waterfall grille between pontoon wings that swell round the front wheels with the lamps
faired into their noses, a short two-door glasshouse (the sprite's dark windscreen band 29 px from the nose), and a
long teardrop fastback with a small rear light on the slope (the sprite's thin blue band 12 px from the tail), rear
wings swelling round the rear wheels, whitewalls. Built on VEHICLE-ART-9's 018 Shark kit body (same surface recipe).
It replaces the image-to-3D shell (lumpy wings and bonnet, no glass found by car_glass, so a seated car drew the
40 % FIX-SEATED band: a translucent grey canopy with the interior and the driver ghosting through it).
Metres, +z nose, 1 block = 5 m (catalog body 34 x 64 px = 0.531 x 1.0 blocks: 2.66 x 5.0 m; axles +24 / -18 px)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "070_z_type"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (179, 137, 108)
LEN = 1.0 * 5.0                 # 5.0 m
HALF_W = 0.531 * 5.0 / 2         # 1.33 m over the wings
ZF, ZR = 1.78, -1.40             # axles (CARI +24 / -18 px; the front a touch back so the wing closes ahead of it)
R_TYRE, W_TYRE = 0.36, 0.22
X_WHEEL = 1.00
R_ARCH = 0.43
BOT = 0.30
SHEAR = 0.0                      # the Z-Type's grille stands upright (the Shark's leaned forward)


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2 - SHEAR - 0.06, -LEN / 2 + 0.07

    belt0 = spline([(zt, 0.72), (-2.0, 0.88), (-1.4, 0.96), (-0.4, 0.98), (0.9, 0.99), (1.6, 0.97), (2.0, 0.93), (zn, 0.88)])
    # roof: a teardrop tail, the long fastback, the roof, the windscreen, the bonnet running out to the prow
    top0 = spline([(zt, 0.76), (-2.15, 0.93), (-1.75, 1.13), (-1.25, 1.34), (-0.70, 1.50), (-0.20, 1.56), (0.12, 1.54),
                   (0.30, 1.48), (0.62, 1.14), (1.20, 1.10), (1.80, 1.06), (2.20, 1.02), (zn, 0.98)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.28 * np.exp(-((z - ZF) / 0.62) ** 2) + 0.27 * np.exp(-((z - ZR) / 0.72) ** 2)
        base = np.interp(z, [zt, -2.1, -1.5, 1.0, 1.8, zn], [0.62, 0.90, 1.00, 1.01, 0.86, 0.58])
        return base + swell
    tumble0 = spline([(zt, 0.0), (-1.7, 0.0), (-1.2, 0.24), (0.40, 0.26), (0.68, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    NOSE, TAILL = 0.50, 0.60   # VEHICLE-ART-12: was 0.75 (the wing tucked in over the front tyre, its liner showed as a black chin)
    def plan(z):
        """plan multipliers: the prow narrows to a rounded vertical edge (a V in plan), the tail closes in a teardrop"""
        fn = np.clip((zn - z) / NOSE, 0, 1)
        fn = 0.10 + 0.90 * (1 - (1 - fn) ** 3.2)
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
    side1 = win([(0.52, 0.54), (-0.50, 0.54), (-0.50, 0.76), (0.28, 0.76)], 0.06)     # the door glass behind the A-pillar
    side2 = win([(-0.64, 0.54), (-1.32, 0.54), (-1.02, 0.76), (-0.64, 0.76)], 0.08)   # the rear quarter light
    screen = win([(0.60, 0.81), (0.60, 0.985), (0.32, 0.985), (0.32, 0.81)], 0.035)
    backl = win([(-1.12, 0.84), (-1.12, 0.99), (-1.58, 0.99), (-1.58, 0.84)], 0.06)
    glass = sdf_union(side1, side2, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.014
    # chrome: the bonnet's centre crease, a spear along the flank, the boot handle (the sprite's chrome at the tail)
    def crease(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.012, np.maximum(0.70 - u, u - zn + 0.02))
    def spear(u, v):
        u = np.asarray(u, float)
        clear = np.abs(u - ZF) - (R_ARCH + 0.02)
        return np.maximum(np.maximum(np.abs(np.asarray(v) - 0.505) * SV - 0.012, np.maximum(u - 2.05, -1.95 - u)), -clear)
    def handle(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.05, np.abs(u - (zt + 0.42)) - 0.12)
    trim = sdf_union(crease, handle)
    G0, G1, GV0, GV1 = zn - 0.10, zn, 0.30, 0.58   # the V prow's flanks only (VEHICLE-ART-12: was zn-0.40, 0.18..0.56, over the wing faces)
    def grille(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.maximum(G0 - u, u - G1), np.maximum(GV0 - v, v - GV1))
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 80, 34, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chrome", trim), ("grille_back", grille), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / (zn - zt), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, 0.60, 0.32, -1.12, -1.58, 0.70, zn - 0.10],
                vkeys=[0.54, 0.76, 0.81, 0.30, 0.58])
    # the grille itself: its own patch a few mm proud of the dark back, with its own uv (vertical bars)
    car.surface(lambda u, v: body(u, v, inset=-0.008), G0, G1 - 0.01, GV0, GV1, 12, 10, mirror=True, default="grille",
                uvfn=lambda u, v: ((u - G0) / (G1 - G0), (v - GV0) / (GV1 - GV0)))
    car.surface(lambda u, v: body(u, v, inset=0.06), -1.58, 0.62, 0.30, 1.0, 24, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    # front wheel well liners
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, side=side, zc=zc):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.60, 1.20, 16, 2, default="underbody", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # the lamp sits half sunk where the wing face passes x 0.80 at y 0.86
    uu, vv = np.meshgrid(np.linspace(1.6, zn, 200), np.linspace(0.3, 0.7, 120))
    bx, by, bz = body(uu.ravel(), vv.ravel())
    k = np.argmin(np.abs(bx - 0.84) + np.abs(by - 0.84) - 0.0 * bz)
    LAMP = np.array([0.80, 0.86, bz[k] - 0.03])
    for side in (1, -1):
        # headlamps faired into the wing faces beside the prow (VEHICLE-ART-12: they sat 0.1 m ahead of the wing,
        # floating on the grille): the bucket half sunk in the wing at x 0.80 (wing face z ~1.96), a paint fairing ring
        c = LAMP * np.array([side, 1.0, 1.0])
        ax = (side * 0.38, 0.06, 1.0)
        car.revolve([(0.150, -0.17), (0.142, -0.03), (0.126, 0.005)], c, ax, 24, default="paint_wheel", uv_mode="disc")
        car.revolve([(0.126, -0.02), (0.122, 0.014), (0.108, 0.027)], c, ax, 24, default="chrome", uv_mode="disc")
        car.revolve([(0.108, 0.023), (0.08, 0.037), (0.0, 0.043)], c, ax, 24, default="lamp_head", uv_mode="disc")
        # tail lamps: small teardrops on the rear wings
        # (the wing face found on the body at the lamp's height, so the lamp sits on it, not in the air)
        tx, ty, tz = body(np.array([zt + 0.34]), np.array([0.34]))
        car.sweep(lambda u, side=side, tx=float(tx[0]), tz=float(tz[0]): np.stack([side * (tx - 0.01) + 0 * u, 0.66 + 0.16 * u, tz - 0.04 * u], 1),
                  0.042, 6, 10, "lamp_tail", squash=(1.0, 0.6))
    # the sprite's chrome prow: a vertical chrome strip along the knife edge (it also closes the open tip of the body)
    def prow(t):
        v = 0.17 + 0.78 * np.asarray(t, float)
        x, y, z = body(np.full_like(v, zn - 0.004), v)
        return np.stack([0 * v, y, z + 0.012], 1)
    car.sweep(prow, 0.042, 24, 12, "chrome", up=(0, 0, 1), squash=(1.0, 0.75))
    # bumpers: chrome blades wrapping round the corners with over-riders
    def wrap(zc, sign, y, half):
        def path(u):
            t = (u - 0.5) * 2
            x = t * half
            e = np.clip(np.abs(t) - 0.80, 0, None) / 0.20
            z = zc - sign * (0.10 * t ** 2 + 0.20 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(wrap(LEN / 2 - 0.10, 1, 0.40, 1.08), 0.075, 30, 10, "chrome", squash=(0.45, 1.0))
    car.sweep(wrap(-LEN / 2 + 0.06, -1, 0.42, 1.04), 0.075, 30, 10, "chrome", squash=(0.45, 1.0))
    for zc, y0 in ((LEN / 2 - 0.08, 0.33), (-LEN / 2 + 0.08, 0.35)):
        for side in (1, -1):
            car.sweep(lambda u, x=side * 0.40, zc=zc, y0=y0: np.stack([x + 0 * u, y0 + 0.24 * u, zc + 0 * u], 1), 0.036, 6, 8, "chrome")
    # door handles (one door a side, on the body's face under the belt)
    hx, hy, hz = body(np.array([-0.40]), np.array([0.47]))
    hx = float(hx[0])
    for side in (1, -1):
        car.box("chrome", (side * hx - 0.012, 0.90, -0.46), (side * hx + 0.012, 0.93, -0.33))
    # the sprite's arrow ornament at the head of the bonnet's chrome strip
    ax_, ay_, az_ = body(np.array([zn - 0.22]), np.array([1.0]))
    car.sweep(lambda u, y=float(ay_[0]), z=float(az_[0]): np.stack([0 * u, y + 0.01 + 0.07 * u, z - 0.30 * u], 1), 0.022, 8, 8, "chrome",
              squash=(0.5, 1.0))
    # interior: bench seats, dash, steering wheel
    car.box("seat", (-0.84, 0.52, -0.22), (0.84, 0.70, 0.28))
    car.box("seat", (-0.84, 0.68, -0.34), (0.84, 1.18, -0.20))
    car.box("seat", (-0.80, 0.52, -1.12), (0.80, 0.70, -0.70))
    car.box("seat", (-0.80, 0.68, -1.24), (0.80, 1.06, -1.10))
    car.box("interior_dark", (-0.96, 0.82, 0.44), (0.96, 1.04, 0.62))
    car.revolve([(0.19, -0.012), (0.19, 0.012)], (-0.42, 1.01, 0.30), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.58, rim_mat="paint_wheel", cap_mat="chrome", whitewall=1.0, cap_dome=0.12)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / (zn - zt)
    lines_u = [(U(0.56), 0.30, 0.52), (U(-0.58), 0.30, 0.52), (U(0.70), 0.52, 0.98)]   # door shuts, the bonnet's rear edge
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=70)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=71)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_wgrille()
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
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va21/p070.png", LEN)
