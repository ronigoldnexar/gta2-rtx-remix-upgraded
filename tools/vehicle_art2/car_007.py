#!/usr/bin/env python3
"""007 Box Truck (VEHICLE-ART-24): the catalog's late-1930s box van read from the GTA2 sprite nose down
(assets-src/cars/sprites_x4/007_box_truck_default.png; body 34 x 107 px = 2.66 x 8.36 m, 0.078 m per sprite px; axles
15 / 88 px from the nose): a narrow V-nosed bonnet with the sprite's chrome strip down its prow (0-25 px), pontoon
front wings flaring round the front wheels with the lamps in their noses, a rounded two-seat cab with a near-upright
screen (the dark band 23-25 px) and a ribbed roof (25-41 px), and behind it a tall box body (41-107 px) whose roof
carries the sprite's raised centre ridge and three cross frames, its flanks vertical ribs and a rub rail, its back
two doors with hinges and lock bars, on a dark chassis with twin rear tyres. One paint all over (the remaps recolour
the box and the cab alike). Built on 001's kit body for the cab (VEHICLE-ART-24). It replaces the image-to-3D shell
(a flat cardboard-textured box with a faint grid, no panel detail and no rear door hardware).
Metres, +z nose, 1 block = 5 m."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "007_box_truck"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (142, 109, 80)
PX = 5.0 / 64
LEN = 107 * PX                   # 8.36 m
HALF_W = 34 * PX / 2             # 1.33 m
ZNOSE = LEN / 2
ZF, ZR = ZNOSE - 15 * PX, ZNOSE - 88 * PX     # +3.01 / -2.69
R_TYRE, W_TYRE, W_REAR = 0.48, 0.24, 0.42
X_WHEEL, X_REAR = 1.00, 0.95
R_ARCH = 0.56                    # arch top 1.04: the wing's waist stays >= 0.08 above it (the wheel split, car_001)
BOT = 0.72
ZCAB = ZNOSE - 41 * PX           # +0.98: the cab's back wall, the box's front
BOX_HW, BOX_Y0, BOX_Y1 = 1.30, 1.02, 3.02
ZB0, ZB1 = -LEN / 2 + 0.04, ZCAB - 0.06


def face_out(part, k0, sign):
    """turn the chunks added to `part` since k0 so their mean normal points along sign * z (car_052's helper)"""
    for i in range(k0, len(part.n)):
        if np.sign(part.n[i][:, 2].mean()) != sign:
            part.n[i] = -part.n[i]
            part.f[i] = part.f[i][:, ::-1]


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = ZNOSE - 0.06, ZCAB

    belt0 = spline([(zt, 1.44), (1.6, 1.44), (2.15, 1.40), (2.55, 1.24), (2.9, 1.18), (3.5, 1.18), (3.85, 1.08), (zn, 0.90)])
    # the cab roof, the near-upright screen, the long bonnet level to the grille's head, the raked V prow
    top0 = spline([(zt, 2.40), (1.25, 2.50), (1.85, 2.50), (2.12, 2.44), (2.34, 1.72), (2.7, 1.66), (3.40, 1.62),
                   (3.72, 1.54), (4.0, 1.22), (zn, 0.98)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.31 * np.exp(-((z - 3.0) / 0.78) ** 4)
        base = np.interp(z, [zt, 2.2, 2.6, 3.6, 3.95, zn], [1.12, 1.12, 1.00, 1.00, 0.86, 0.50])
        return base + swell
    tumble0 = spline([(zt, 0.12), (2.0, 0.14), (2.35, 0.40), (3.0, 0.62), (3.7, 0.58), (zn, 0.14)])
    leanq = lambda z: np.interp(z, [2.1, 2.6, 3.9, zn], [1.0, 0.42, 0.42, 0.8])

    def arch(z):
        lift = np.zeros_like(z)
        dz = np.abs(z - ZF)
        y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
        return np.maximum(lift, np.where(dz < R_ARCH, y, 0))

    NOSE = 0.45
    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        fn = np.clip((zn - z) / NOSE, 0, 1)
        fn = 0.16 + 0.84 * (1 - (1 - fn) ** 3.2)
        # the cab's back corners round off a little in plan
        fb = 0.92 + 0.08 * np.sqrt(np.clip((z - zt) / 0.25, 0, 1))
        hw = hw0(z) * fn * fb - inset
        belt = belt0(z)
        top = top0(z) - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08) + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z) * np.minimum(hw, 1.10) / 1.20
        xl = hw * sepow(c, 0.30)
        yl = belt - (belt - bot) * sepow(s, 0.45)
        H = top - belt
        q = leanq(z)
        t = np.clip((v - 0.5) / 0.3, 0, 1) * 0.95
        xs = hw * (1 - t ** 5) ** (1 / 5) - tb * t ** q
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** 5) ** (1 / 5) - tb * 0.95 ** q
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
    side1 = win([(2.16, 0.56), (1.20, 0.56), (1.20, 0.77), (2.06, 0.77)], 0.05)    # the door glass
    screen = win([(2.33, 0.81), (2.33, 0.985), (2.13, 0.985), (2.13, 0.81)], 0.03)
    glass = sdf_union(side1, screen)
    seal = lambda u, v: glass(u, v) - 0.014
    G0, G1, GV0 = 3.72, zn, 0.90
    def crease(u, v):
        u = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 1.0) * SV - 0.012, np.maximum(2.36 - u, u - G0))
    def grille(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.maximum(G0 - u, u - G1), GV0 - v)
    under = lambda u, v: np.maximum(np.asarray(v) - 0.20, body(u, v)[1] - (BOT + 0.08))
    car.surface(body, zt, zn, 0.0, 1.0, 64, 34, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chrome", crease), ("grille_back", grille), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / (zn - zt), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, 2.33, 2.13, 2.16, 1.20, 2.36, G0], vkeys=[0.56, 0.77, 0.81, GV0])
    k0 = len(car.part("paint_body").n)
    car.cap(body, zt, 0.0, 1.0, 20, "paint_body")
    face_out(car.parts["paint_body"], k0, -1)
    car.surface(lambda u, v: body(u, v, inset=-0.008), G0, G1 - 0.01, GV0, 1.0, 16, 8, mirror=True, default="grille",
                uvfn=lambda u, v: ((u - G0) / (G1 - G0), (v - GV0) / (1.0 - GV0)))
    car.surface(lambda u, v: body(u, v, inset=0.06), zt + 0.02, 2.30, 0.30, 1.0, 16, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for side in (1, -1):
        def liner(u, v, side=side):
            a = np.asarray(u, float); x = np.asarray(v, float)
            return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), ZF + (R_ARCH - 0.01) * np.cos(a)
        car.surface(liner, 0.05, math.pi - 0.05, 0.62, 1.20, 16, 2, default="underbody", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # headlamps faired into the wing noses
    uu, vv = np.meshgrid(np.linspace(3.2, zn, 200), np.linspace(0.3, 0.7, 120))
    bx, by, bz = body(uu.ravel(), vv.ravel())
    k = np.argmin(np.abs(bx - 0.98) + np.abs(by - 1.10))
    LAMP = np.array([0.96, 1.10, bz[k] - 0.03])
    for side in (1, -1):
        c = LAMP * np.array([side, 1.0, 1.0])
        ax = (side * 0.25, 0.05, 1.0)
        car.revolve([(0.160, -0.17), (0.150, -0.03), (0.134, 0.005)], c, ax, 24, default="paint_wheel", uv_mode="disc")
        car.revolve([(0.134, -0.02), (0.130, 0.014), (0.114, 0.028)], c, ax, 24, default="chrome", uv_mode="disc")
        car.revolve([(0.114, 0.024), (0.084, 0.037), (0.0, 0.043)], c, ax, 24, default="lamp_head", uv_mode="disc")
    def prow(t):
        u = G0 + (zn - 0.004 - G0) * np.asarray(t, float)
        x, y, z = body(u, np.full_like(u, 1.0))
        return np.stack([0 * u, y + 0.010, z + 0.004], 1)
    car.sweep(prow, 0.028, 20, 10, "chrome", up=(0, 0, 1), squash=(0.6, 1.0))
    # front bumper: a chrome blade with over-riders
    def wrap(zc, y, half):
        def path(u):
            t = (u - 0.5) * 2
            e = np.clip(np.abs(t) - 0.80, 0, None) / 0.20
            return np.stack([t * half, np.full_like(t, y), zc - (0.08 * t ** 2 + 0.16 * e * e)], 1)
        return path
    car.sweep(wrap(ZNOSE - 0.04, 0.70, 1.12), 0.080, 30, 10, "chrome", squash=(0.45, 1.0))
    for side in (1, -1):
        car.sweep(lambda u, x=side * 0.44: np.stack([x + 0 * u, 0.62 + 0.24 * u, ZNOSE - 0.03 + 0 * u], 1), 0.038, 6, 8, "chrome")
    # door handles, the cab's step
    hx, hy, hz = body(np.array([1.30]), np.array([0.47]))
    hx, hy = float(hx[0]), float(hy[0])
    for side in (1, -1):
        car.box("chrome", (side * hx - 0.012, hy - 0.015, 1.24), (side * hx + 0.012, hy + 0.015, 1.38))
        car.box("trim_dark", (min(side * 0.80, side * 1.14), 0.56, 1.10), (max(side * 0.80, side * 1.14), 0.62, 2.20))
    # cab interior
    car.box("seat", (-0.96, 1.06, 1.06), (0.96, 1.24, 1.50))
    car.box("seat", (-0.96, 1.22, 0.98), (0.96, 1.86, 1.08))
    car.box("interior_dark", (-1.00, 1.42, 2.08), (1.00, 1.62, 2.26))
    car.revolve([(0.21, -0.014), (0.21, 0.014)], (-0.46, 1.66, 1.86), (0, 0.55, -1), 18, default="interior_dark", uv_mode="disc")

    # ---- the box body ------------------------------------------------------------------------------------------
    pb = car.part("paint_box"); kb = len(pb.n)
    car.box("paint_box", (-BOX_HW, BOX_Y0, ZB0), (BOX_HW, BOX_Y1, ZB1))
    # roof: the sprite's raised centre ridge, three cross frames, a drip edge round the roof
    car.box("paint_box", (-0.30, BOX_Y1, ZB0 + 0.20), (0.30, BOX_Y1 + 0.07, ZB1 - 0.20))
    for zf in (ZB0 + 1.30, ZB0 + 2.60, ZB0 + 3.90):
        car.box("paint_box", (-BOX_HW + 0.04, BOX_Y1, zf - 0.05), (BOX_HW - 0.04, BOX_Y1 + 0.04, zf + 0.05))
    for side in (1, -1):
        car.box("paint_box", (min(side * (BOX_HW - 0.04), side * (BOX_HW + 0.03)), BOX_Y1 - 0.08, ZB0 - 0.02),
                (max(side * (BOX_HW - 0.04), side * (BOX_HW + 0.03)), BOX_Y1 + 0.02, ZB1 + 0.02))
        # flank ribs (vertical stiffeners) and a rub rail
        for zr_ in np.linspace(ZB0 + 0.08, ZB1 - 0.08, 9):
            car.box("paint_box", (min(side * BOX_HW, side * (BOX_HW + 0.035)), BOX_Y0 + 0.02, zr_ - 0.035),
                    (max(side * BOX_HW, side * (BOX_HW + 0.035)), BOX_Y1 - 0.02, zr_ + 0.035))
        car.box("trim_dark", (min(side * BOX_HW, side * (BOX_HW + 0.05)), BOX_Y0 + 0.20, ZB0 + 0.02),
                (max(side * BOX_HW, side * (BOX_HW + 0.05)), BOX_Y0 + 0.30, ZB1 - 0.02))
        # sill rail under the box
        car.box("trim_dark", (min(side * (BOX_HW - 0.06), side * (BOX_HW + 0.02)), BOX_Y0 - 0.14, ZB0),
                (max(side * (BOX_HW - 0.06), side * (BOX_HW + 0.02)), BOX_Y0, ZB1))
        # amber marker lamps along the roof edge
        for zm in (ZB0 + 0.25, ZB1 - 0.25):
            car.box("lamp_amber", (min(side * BOX_HW, side * (BOX_HW + 0.04)), BOX_Y1 - 0.20, zm - 0.06),
                    (max(side * BOX_HW, side * (BOX_HW + 0.04)), BOX_Y1 - 0.12, zm + 0.06))
    # the back: two doors (a centre seam, hinges at the outer edges, two lock bars), tail lamps, a step bumper
    car.box("trim_dark", (-0.012, BOX_Y0 + 0.06, ZB0 - 0.012), (0.012, BOX_Y1 - 0.06, ZB0))
    for side in (1, -1):
        for yh in (BOX_Y0 + 0.30, BOX_Y0 + 1.00, BOX_Y1 - 0.30):
            car.box("chrome", (min(side * 1.16, side * 1.27), yh - 0.04, ZB0 - 0.03), (max(side * 1.16, side * 1.27), yh + 0.04, ZB0))
        car.sweep(lambda u, x=side * 0.30: np.stack([x + 0 * u, BOX_Y0 + 0.10 + (BOX_Y1 - BOX_Y0 - 0.20) * u, ZB0 - 0.05 + 0 * u], 1),
                  0.020, 8, 8, "chrome")
        car.box("chrome", (min(side * 0.24, side * 0.36), BOX_Y0 + 0.90, ZB0 - 0.07), (max(side * 0.24, side * 0.36), BOX_Y0 + 0.98, ZB0 - 0.02))
        car.box("lamp_tail", (min(side * 0.98, side * 1.18), 0.80, ZB0 - 0.06), (max(side * 0.98, side * 1.18), 0.92, ZB0 + 0.02))
        car.box("rubber", (min(side * 0.70, side * 1.10), 0.30, ZR - 0.70), (max(side * 0.70, side * 1.10), 0.80, ZR - 0.68))   # mudflaps
    car.box("trim_dark", (-1.20, 0.66, ZB0 - 0.16), (1.20, 0.80, ZB0 - 0.04))
    # the box's front wall sits just behind the cab: its face toward the cab is the box's own front face
    # chassis rails, the rear wheel boxes under the box floor
    for s_ in (1, -1):
        car.box("trim_dark", (s_ * 0.55 - 0.08, 0.58, ZB0 + 0.10), (s_ * 0.55 + 0.08, BOX_Y0 - 0.14, ZCAB + 0.60))
    car.box("underbody", (-BOX_HW + 0.06, BOX_Y0 - 0.16, ZB0 + 0.04), (BOX_HW - 0.06, BOX_Y0 - 0.12, ZB1 - 0.04))

    style = dict(rim_r=0.58, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.10)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)
    for nm, zc, xw in (("wheel_rl", ZR, -X_REAR), ("wheel_rr", ZR, X_REAR)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_REAR, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / (zn - zt)
    lines_u = [(U(2.20), 0.30, 0.55), (U(1.12), 0.30, 0.55), (U(2.36), 0.55, 0.98)]   # door shuts, the bonnet's rear edge
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=7)
    car.materials["paint_box"] = tex_paint(PAINT, 256, seed=71)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=72)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_vgrille(128, bars=6)
    car.materials["grille_back"] = tex_flat((14, 14, 15))
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((12, 12, 12))
    car.materials["trim_dark"] = tex_flat((26, 26, 28))
    car.materials["rubber"] = tex_flat((18, 18, 18))
    car.materials["seat"] = tex_leather((80, 62, 50))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
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
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va24/p007.png", LEN)
