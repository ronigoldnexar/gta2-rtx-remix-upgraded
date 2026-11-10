#!/usr/bin/env python3
"""086 Karma Bus (VEHICLE-ART-18): a 1950s conventional school bus (the catalog's 'Hare Krishna bus: school-bus body,
orange paint, yellow roof, flat hood') read from the GTA2 sprite (nose down in
assets-src/cars/sprites_x4/086_karma_bus_default.png): a short flat bonnet between the front wings, a near-upright split
windscreen at row 15 of 100 from the nose, a long box body with a row of side windows over black rub rails, a light
roof carrying the sprite's two dark roof hatches (raised hatch frames with smoked lights), a rear emergency door with
two windows, four round tail lamps.
It replaces the image-to-3D shell (qav7: the rear glass two ragged black cut-outs, black rectangular holes under the
emblem, the roof vents flat black slots: holes and dark blotches baked in a generated texture).
086 is a livery (identity.cpp Livery): drawn untinted, so the colours here are the bus's own; painted by where each
texel lies on the body, as 034.
Metres, +z nose, 1 block = 5 m (catalog body 0.594 x 1.562 blocks: 2.97 x 7.81 m; axles +39 / -23 px of 100)."""
import math
import os
import sys
import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa
from car_010 import tex_eggcrate  # noqa

NAME = "086_karma_bus"
SPRITE = (244, 161, 45)          # catalog default remap paint (previews only)
PAINT = (235.0, 235.0, 235.0)    # manifest paint_rgb (a livery: not used for a tint)
BODY = (236, 148, 36)
ROOF = (246, 196, 78)
BLACK = (24, 24, 26)
LEN = 1.562 * 5.0                # 7.81 m
HALF_W = 0.594 * 5.0 / 2         # 1.485 m
PX = LEN / 100.0                 # metres per sprite body pixel
ZF, ZR = 39 * PX, -23 * PX       # axles: 3.05, -1.80
R_TYRE, W_TYRE = 0.50, 0.30
X_WHEEL = 1.17
R_ARCH = 0.60
BOT = 0.52
ZSB, ZST = 2.78, 2.64            # screen base, screen top (sprite row 15 from the nose)
CAP_Y0, CAP_Y1 = 0.40, 3.00      # the end panels' height range (paint_end rows)
HATCHES = (0.43, -1.95)          # the sprite's two roof hatches (rows 40-49 and 70-80 from the nose)


def star_of_life(px, pz, r=0.62, w=0.15):
    """the six-armed star: three bars of half width w and half length r at 0, 60, 120 degrees"""
    inside = np.zeros_like(px, bool)
    for a in (0.0, math.pi / 3, 2 * math.pi / 3):
        c, s = math.cos(a), math.sin(a)
        along = px * s + pz * c
        across = px * c - pz * s
        inside |= (np.abs(along) < r) & (np.abs(across) < w)
    return inside


def build():
    car = Car(NAME)
    car.preview_tint = None
    zn, zt = LEN / 2, -LEN / 2

    belt0 = spline([(zt, 1.52), (2.60, 1.55), (2.90, 1.48), (3.50, 1.42), (zn, 1.30)])
    top0 = spline([(zt, 2.30), (-3.80, 2.74), (-3.62, 2.88), (-3.3, 2.92), (2.30, 2.92), (2.52, 2.86), (ZST, 2.70),
                   (ZSB, 1.60), (3.10, 1.56), (3.60, 1.50), (zn, 1.36)])
    hw0 = spline([(zt, 1.42), (-3.6, 1.485), (2.72, 1.485), (2.98, 1.30), (3.60, 1.27), (zn, 1.16)])
    tumble0 = spline([(zt, 0.0), (-3.7, 0.08), (2.5, 0.08), (ZSB, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    def ends(z, nose=0.30, tail=0.14):
        dn = np.clip((z - (zn - nose)) / nose, 0, 1)
        dt = np.clip(((zt + tail) - z) / tail, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dt ** 2, 0, 1))

    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * (0.90 + 0.10 * f) - inset
        belt = belt0(z)
        fh = 0.85 + 0.15 * f
        top = belt + (top0(z) - belt) * fh - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08)
        bot = belt - (belt - bot) * fh + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z) * hw / 1.485
        xl = hw * (0.96 + 0.04 * sepow(c, 1.2))
        xl = np.where(s > 0.95, hw * (0.96 + 0.04 * sepow(c, 1.2)) * sepow(c, 0.06), xl)
        yl = belt - (belt - bot) * sepow(s, 0.85)   # the side spread over the atlas rows (0.22 drew the rails one texel tall)
        H = top - belt
        t = np.clip((v - 0.5) / 0.3, 0, 1) * 0.95
        ex = 10.0
        xs = hw * (1 - t ** ex) ** (1 / ex) - tb * t
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** ex) ** (1 / ex) - tb * 0.95
        xr = X0 * (1 - w)
        yr = belt + H * (0.95 + 0.05 * (1 - (1 - w) ** 3) ** 0.3)
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
    WV0, WV1 = 0.545, 0.70
    panes = [win([(ZSB - 0.10, WV0), (2.05, WV0), (2.05, WV1), (ZST - 0.02, WV1)], 0.025)]     # the driver's / door window
    z0 = 1.85
    for k in range(7):
        a_, b_ = z0 - k * 0.80, z0 - k * 0.80 - 0.70
        panes.append(win([(a_, WV0), (b_, WV0), (b_, WV1), (a_, WV1)], 0.025))
    screen = win([(ZSB, 0.80), (ZSB, 1.03), (ZST, 1.03), (ZST, 0.80)], 0.02)
    glass = sdf_union(*panes, screen)
    seal = lambda u, v: glass(u, v) - 0.014
    under = lambda u, v: np.maximum(np.asarray(v) - 0.30, body(u, v)[1] - (BOT + 0.12))
    car.surface(body, zt, zn, 0.0, 1.0, 110, 34, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, ZSB, ZST, 2.05] +
                      [z0 - k * 0.80 for k in range(7)] + [z0 - k * 0.80 - 0.70 for k in range(7)],
                vkeys=[WV0, WV1, 0.80])
    def cap_uv(u_end):
        def uv(r, v):
            _, y, _ = body(np.full_like(np.asarray(v, float), u_end), v)
            C = float(np.mean(body(np.full(64, u_end), np.linspace(0, 1, 64))[1]))
            yy = C + np.asarray(r, float) * (y - C)
            return 0.5 + 0 * yy, np.clip((yy - CAP_Y0) / (CAP_Y1 - CAP_Y0), 0.0, 1.0)
        return uv
    car.cap(body, zt, 0.0, 1.0, 24, "paint_end", uvfn=cap_uv(zt))
    car.cap(body, zn, 0.0, 1.0, 20, "paint_end", regions=[("underbody", lambda u, v: np.asarray(v) - 0.12)], uvfn=cap_uv(zn))
    car.surface(lambda u, v: body(u, v, inset=0.06), -3.70, ZST + 0.05, 0.30, 1.0, 34, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, zc=zc, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.80, 1.42, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    # the windscreen's centre post
    car.sweep(lambda u: np.stack([0 * u, 1.62 + 1.06 * u, ZSB + 0.005 - 0.15 * u], 1), 0.025, 6, 8, "seal")

    # the tail: the emergency door (shut lines, two windows, a handle), four round tail lamps, a black bumper
    zb = zt + 0.004
    for xl in (-0.55, 0.55):
        car.box("seal", (xl - 0.012, 0.62, zb - 0.012), (xl + 0.012, 2.55, zb + 0.01))
    car.box("seal", (-0.55, 2.54, zb - 0.012), (0.55, 2.56, zb + 0.01))
    car.box("glass", (-0.48, 1.70, zb - 0.02), (-0.04, 2.45, zb - 0.006))
    car.box("glass", (0.04, 1.70, zb - 0.02), (0.48, 2.45, zb - 0.006))
    car.box("chrome", (0.30, 1.40, zb - 0.04), (0.46, 1.44, zb - 0.005))
    for side in (1, -1):
        for yl in (1.05, 2.62):
            car.revolve([(0.085, -0.03), (0.085, 0.012), (0.0, 0.024)], (side * 1.10, yl, zt + 0.02), (0, 0, -1), 16,
                        default="lamp_tail" if yl < 2 else "lamp_amber", uv_mode="disc")
    def bar(zc, y, half=1.40):
        return lambda u: np.stack([(u - 0.5) * 2 * half, y + 0 * u, zc + 0 * u], 1)
    car.sweep(bar(zt - 0.06, 0.62), 0.09, 20, 8, "bumper", squash=(0.60, 1.0))
    car.sweep(bar(zn + 0.08, 0.66, 1.30), 0.10, 20, 8, "bumper", squash=(0.60, 1.0))

    # front: a chrome-surround grille, round lamps on the wings, amber parking lamps, the four roof flashers
    car.box("grille", (-0.62, 0.80, zn - 0.10), (0.62, 1.32, zn + 0.004))
    for yb in (0.79, 1.33):
        car.sweep(bar(zn + 0.01, yb, 0.64), 0.022, 12, 8, "chrome")
    for side in (1, -1):
        car.sweep(lambda u, side=side: np.stack([side * 0.64 + 0 * u, 0.79 + 0.54 * u, zn + 0.01 + 0 * u], 1), 0.022, 6, 8, "chrome")
        c = np.array([side * 0.98, 1.20, zn - 0.02])
        car.revolve([(0.13, -0.10), (0.128, 0.0), (0.118, 0.020)], c, (side * 0.05, 0.02, 1), 22, default="chrome", uv_mode="disc")
        car.revolve([(0.118, 0.016), (0.085, 0.030), (0.0, 0.036)], c, (side * 0.05, 0.02, 1), 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.05, 0.0), (0.05, 0.02), (0.0, 0.03)], (side * 0.98, 0.92, zn - 0.02), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        for xf in (0.55, 1.15):
            car.revolve([(0.075, -0.03), (0.075, 0.015), (0.0, 0.026)], (side * xf, 2.72, ZST - 0.10), (0, 0.3, 1), 14,
                        default="lamp_amber" if xf > 1 else "lamp_tail", uv_mode="disc")

    # roof: the two hatches (raised frames in the roof colour, smoked lights), a rain gutter strip each side
    ytop = float(top0(np.array([0.0]))[0])
    for zh in HATCHES:
        car.box("hatch", (-0.30, ytop - 0.03, zh - 0.40), (0.30, ytop + 0.07, zh + 0.40))
        car.box("hatch_light", (-0.24, ytop + 0.07, zh - 0.33), (0.24, ytop + 0.085, zh + 0.33))
    # mirrors on stalks, the entrance door's shut lines are in the paint
    for side in (1, -1):
        car.sweep(lambda u, side=side: np.stack([side * (1.45 + 0.22 * u), 2.10 - 0.10 * u, ZSB - 0.02 + 0.10 * u], 1), 0.016, 6, 6, "chrome")
        car.box("seal", (side * 1.67 - 0.05, 1.85, ZSB + 0.03), (side * 1.67 + 0.05, 2.15, ZSB + 0.05))

    # interior: the driver's seat and wheel, rows of bench seats down both sides
    car.box("seat", (-1.10, 0.95, 2.10), (-0.55, 1.05, 2.55))
    car.box("seat", (-1.10, 1.00, 1.98), (-0.55, 1.62, 2.10))
    car.revolve([(0.24, -0.012), (0.24, 0.012)], (-0.82, 1.55, 2.62), (0, 0.6, -1), 18, default="interior_dark", uv_mode="disc")
    for k in range(7):
        zc = 1.50 - k * 0.80
        for side in (1, -1):
            x0, x1 = sorted((side * 0.30, side * 1.30))
            car.box("seat", (x0, 0.95, zc - 0.40), (x1, 1.08, zc))
            car.box("seat", (x0, 1.00, zc - 0.48), (x1, 1.62, zc - 0.40))

    style = dict(rim_r=0.60, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.10)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    car.materials["paint_body"] = tex_livery(body, belt0, top0, zt, LEN)
    car.materials["paint_end"] = tex_end(belt0(np.array([zt]))[0])
    car.materials["paint_wheel"] = tex_paint(BLACK, 64, seed=87)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_eggcrate()
    car.materials["bumper"] = tex_flat((26, 26, 28), 16)
    car.materials["hatch"] = tex_flat(ROOF, 16)
    car.materials["hatch_light"] = tex_flat((44, 52, 58), 16)
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((10, 10, 10))
    car.materials["seat"] = tex_leather((92, 58, 40))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    return car


def tex_livery(body, belt0, top0, zt, length, size=512):
    """the paint atlas coloured by where each texel lies on the bus: orange body, the light roof (from the drip line
    up), two black rub rails and a black belt rail under the windows, the entrance door's and the panel shut lines"""
    s = (np.arange(size) + 0.5) / size
    S, T = np.meshgrid(s, s, indexing="xy")
    U = zt + S * length
    x, y, z = body(U, T)
    col = np.ones(x.shape + (3,)) * np.array(BODY, float)
    roof = (T > 0.78) & (z < ZST - 0.05)
    col[roof] = ROOF
    side = (T < 0.5) & (z > zt + 0.10) & (z < ZSB - 0.10) & (np.abs(z - ZR) > R_ARCH + 0.04)
    for y0, y1 in ((0.86, 0.94), (1.16, 1.24)):
        col[side & (y > y0) & (y < y1)] = BLACK
    col[(T < 0.5) & (y > 1.46) & (z > zt + 0.10) & (z < ZSB)] = BLACK            # the belt rail under the windows
    # the entrance door (front right): two leaves' shut lines; panel seams every window pitch
    for zl in (ZSB - 0.12, 2.12, 2.48):
        col[(np.abs(z - zl) < 0.010) & (T < 0.80) & (x > 0)] *= 0.30
    for k in range(8):
        zl = 1.85 - k * 0.80 + 0.05
        col[(np.abs(z - zl) < 0.006) & (T < 0.5)] *= 0.55
    im = Image.fromarray(np.clip(col, 0, 255).astype(np.uint8))
    a = np.asarray(im.filter(ImageFilter.GaussianBlur(0.6)), float)
    n = noise(size, size, 6, 86) * 0.5 + noise(size, size, 40, 87) * 0.5
    a *= (0.985 + 0.03 * n)[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def tex_end(belt, size=64):
    """the end panels' strip by height: the orange body, the black rails at the side rails' heights, the light roof cap"""
    y = CAP_Y0 + (np.arange(size) + 0.5) / size * (CAP_Y1 - CAP_Y0)
    col = np.ones((size, 3)) * np.array(BODY, float)
    for y0, y1 in ((0.86, 0.94), (1.16, 1.24)):
        col[(y > y0) & (y < y1)] = BLACK
    col[y > 2.70] = ROOF
    a = np.repeat(col[:, None, :], size, 1)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va18/p086.png", LEN)
