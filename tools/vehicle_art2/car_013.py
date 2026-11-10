#!/usr/bin/env python3
"""013 Minx (VEHICLE-ART-15, audit item: the third most-seen car to the kit standard of 010/053/058): the catalog's
early-1960s compact two-door (Dodge Dart / Hillman Minx), read from the GTA2 sprite nose down
(assets-src/cars/sprites_x4/013_minx_default.png, body 30 x 58 px): a long bonnet with a raised centre panel (the
sprite's two lines from the screen to the nose), a wrap-around screen, a big dark glasshouse under a black vinyl roof
(the sprite's dark grey roof area), one long door, a large rear quarter light and a wide back light, a short boot
between two small fins ending in round tail lamps (the sprite's bright rear corners), a full-width bar grille between
single round lamps.
It replaces the carkit-v1 body (tools/vehicle_art/m013_minx.py: shader-painted panel lines, a cut box cabin). The
cabin liner keeps 1b59d00's light grey-beige with its normals leaning up, so the cabin reads through the glass.
Neutral 235 paint: the identity record tints it (car_paint_sprite_palette). Metres, +z nose, 1 block = 5 m (catalog
body 30 x 58 px = 2.34 x 4.53 m; axles +17 / -15 px)."""
import math
import os
import sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "013_minx"
SPRITE = (133, 98, 80)           # catalog default remap paint (previews only)
PAINT = (235.0, 235.0, 235.0)    # neutral: the identity record tints it
LEN = 58 / 64 * 5.0              # 4.53 m
HALF_W = 30 / 64 * 5.0 / 2       # 1.17 m
ZF, ZR = 17 / 64 * 5.0, -15 / 64 * 5.0     # +1.33 / -1.17
R_TYRE, W_TYRE = 0.35, 0.23
X_WHEEL = 0.95
R_ARCH = 0.42
BOT = 0.29
SV = 2.6
ZSB, ZBB = 0.80, -1.38           # screen base, back-light base
ZST, ZBT = 0.40, -1.00           # screen top, back-light top
V_BELT = 0.512


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2, -LEN / 2

    belt0 = spline([(zt, 0.95), (-1.9, 0.98), (-1.2, 0.97), (1.2, 0.95), (2.0, 0.92), (zn, 0.85)])
    top0 = spline([(zt, 1.01), (-2.05, 1.06), (-1.70, 1.09), (ZBB, 1.11), (-1.12, 1.52), (ZBT, 1.58), (-0.80, 1.61), (0.20, 1.62),
                   (ZST, 1.58), (ZSB, 1.13), (1.20, 1.10), (2.00, 1.04), (zn - 0.08, 0.98), (zn, 0.91)])
    hw0 = spline([(zt, 1.08), (-1.9, 1.15), (-1.2, 1.17), (1.4, 1.17), (2.0, 1.14), (zn, 1.06)])
    tumble0 = spline([(zt, 0.0), (ZBB, 0.0), (ZBT - 0.05, 0.17), (ZST + 0.02, 0.17), (ZSB - 0.04, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    def ends(z, nose=0.32, tail=0.28):
        dn = np.clip((z - (zn - nose)) / nose, 0, 1)
        dt = np.clip(((zt + tail) - z) / tail, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dt ** 2, 0, 1))

    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * (0.90 + 0.10 * f) - inset
        belt = belt0(z)
        fh = 0.82 + 0.18 * f
        top = belt + (top0(z) - belt) * fh - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08)
        bot = belt - (belt - bot) * fh + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z) * hw / 1.17
        xl = hw * (0.94 + 0.06 * sepow(c, 1.2))
        xl = np.where(s > 0.92, hw * (0.94 + 0.06 * sepow(c, 1.2)) * sepow(c, 0.08), xl)
        yl = belt - (belt - bot) * sepow(s, 0.30)
        H = top - belt
        t = np.clip((v - 0.5) / 0.3, 0, 1) * 0.95
        ex = 7.0
        xs = hw * (1 - t ** ex) ** (1 / ex) - tb * t
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** ex) ** (1 / ex) - tb * 0.95
        xr = X0 * (1 - w)
        yr = belt + H * (0.95 + 0.05 * (1 - (1 - w) ** 4) ** 0.25)
        xu = np.where(v < 0.8, xs, xr)
        yu = np.where(v < 0.8, ys, yr)
        return np.where(lo, xl, xu), np.where(lo, yl, yu), z

    SU = 1.0
    def win(poly, r):
        p = np.array(poly, float)
        c = p.mean(0)
        d = p - c
        shrink = p - d / np.linalg.norm(d * [SU, SV], axis=1, keepdims=True) * r / np.array([SU, SV])
        f = poly_sdf(shrink, SU, SV)
        return lambda u, v: f(u, v) - r
    # one long door's glass, a large rear quarter light (the sprite's big dark glasshouse), a wrap-around screen and back light
    side1 = win([(0.74, 0.535), (-0.38, 0.535), (-0.38, 0.78), (0.42, 0.78)], 0.03)
    side2 = win([(-0.47, 0.535), (-1.30, 0.535), (-0.98, 0.78), (-0.47, 0.78)], 0.03)
    screen = win([(ZSB - 0.04, 0.70), (ZSB - 0.04, 1.03), (ZST + 0.03, 1.03), (ZST + 0.03, 0.78)], 0.03)
    backl = win([(ZBT - 0.03, 0.78), (ZBT - 0.03, 1.03), (ZBB + 0.03, 1.03), (ZBB + 0.03, 0.72)], 0.04)
    glass = sdf_union(side1, side2, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.014
    # black vinyl roof: the roof panel between the screen and back light tops, down to the drip rail
    vinyl = lambda u, v: np.maximum(np.maximum(np.asarray(u) - ZST, ZBT - np.asarray(u)), 0.795 - np.asarray(v, float))
    # a chrome side spear from the front wheel's arch back to the tail (the shipped 013's, a period touch)
    def spear(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        clear = np.minimum(np.abs(u - ZF), np.abs(u - ZR)) - (R_ARCH + 0.04)
        return np.maximum(np.maximum(np.abs(v - 0.40) * SV - 0.010, np.abs(u + 0.25) - 1.85), -clear)
    belt_chrome = lambda u, v: np.maximum(np.maximum(0.5 - np.asarray(v), np.asarray(v) - V_BELT), np.abs(np.asarray(u) + 0.1) - 2.0)
    under = lambda u, v: np.maximum(np.asarray(v) - 0.30, body(u, v)[1] - (BOT + 0.12))
    car.surface(body, zt, zn, 0.0, 1.0, 72, 30, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("vinyl", vinyl), ("chrome", sdf_union(belt_chrome, spear)), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, ZSB, ZST, ZBB, ZBT, 0.74, -0.38, -0.47, -1.30, -2.1, 1.9],
                vkeys=[0.535, 0.70, 0.72, 0.78, 0.795, 0.80, 0.50, V_BELT, 0.40 - 0.010 / SV, 0.40 + 0.010 / SV])
    car.cap(body, zt, 0.0, 1.0, 20, "paint_body", regions=[("underbody", lambda u, v: np.asarray(v) - 0.12)])
    car.cap(body, zn, 0.0, 1.0, 20, "paint_body", regions=[("underbody", lambda u, v: np.asarray(v) - 0.12)])
    # the cabin liner (1b59d00's light grey-beige, normals leaning up: it reads through the glass)
    car.surface(lambda u, v: body(u, v, inset=0.06), ZBB + 0.05, ZSB - 0.05, 0.30, 1.0, 22, 10, mirror=True, default="interior_liner",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    lp = car.parts["interior_liner"]
    lp.n = [(-np.asarray(n) + np.array([0.0, 2.5, 0.0])) for n in lp.n]
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, zc=zc, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.62, 1.15, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # the bonnet's raised centre panel: two low ribs from the screen base to the nose (the sprite's two lines)
    for sx in (-0.40, 0.40):
        def rib(u, sx=sx):
            z = ZSB + 0.08 + (zn - 0.14 - ZSB - 0.08) * np.asarray(u, float)
            x, y, _ = body(z, np.full_like(z, 0.8 + 0.2 * (1 - abs(sx) / 0.86)))
            return np.stack([np.sign(sx) * np.abs(sx) + 0 * z, y + 0.004, z], 1)
        car.sweep(rib, 0.016, 16, 6, "paint_trim", squash=(1.0, 0.5))
    # fins: low blades on the rear wings' shoulders from the door's end to the tail, ending in a round tail lamp
    for side in (1, -1):
        def fin(u, side=side):
            u = np.asarray(u, float)
            z = -1.35 + (zt + 0.05 + 1.35) * u
            x = side * (hw0(z) * (0.90 + 0.10 * ends(z)) - 0.06)
            y = belt0(z) + 0.01 + 0.07 * np.clip(u, 0, 1) ** 1.3
            return np.stack([x, y, z], 1)
        car.sweep(fin, lambda u: 0.04 + 0.035 * np.clip(np.asarray(u, float), 0, 1) ** 0.5, 20, 10, "paint_trim", squash=(0.50, 1.0))
        c = (side * (hw0(np.array([zt + 0.05]))[0] * 0.90 - 0.06), float(belt0(np.array([zt + 0.05]))[0]) + 0.08, zt + 0.04)
        car.revolve([(0.075, -0.05), (0.075, 0.0), (0.068, 0.014)], c, (0, 0, -1), 18, default="chrome", uv_mode="disc")
        car.revolve([(0.068, 0.010), (0.045, 0.022), (0.0, 0.028)], c, (0, 0, -1), 18, default="lamp_tail", uv_mode="disc")
        car.revolve([(0.04, 0.0), (0.04, 0.015), (0.0, 0.02)], (side * 0.70, 0.62, zt - 0.005), (0, 0, -1), 12, default="lamp_head",
                    uv_mode="disc")
    # tail: the plate in a dark recess, the boot lock
    car.box("trim_dark", (-0.22, 0.52, zt - 0.004), (0.22, 0.70, zt + 0.04))
    car.box("plate", (-0.19, 0.545, zt - 0.010), (0.19, 0.675, zt + 0.0))
    car.revolve([(0.025, 0.0), (0.025, 0.01), (0.0, 0.014)], (0, 0.82, zt - 0.002), (0, 0, -1), 12, default="chrome", uv_mode="disc")

    # front: a full-width bar grille between single round lamps
    car.box("grille", (-0.70, 0.50, zn - 0.10), (0.70, 0.72, zn + 0.004))
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.44, 0.735 + 0 * u, zn + 0.008 - 0.04 * ((u - 0.5) * 2) ** 2], 1), 0.018, 16, 8, "chrome")
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.44, 0.49 + 0 * u, zn + 0.008 - 0.04 * ((u - 0.5) * 2) ** 2], 1), 0.016, 16, 8, "chrome")
    for side in (1, -1):
        c = np.array([side * 0.86, 0.66, zn + 0.0])
        ax = (side * 0.05, 0.02, 1)
        car.revolve([(0.105, -0.09), (0.103, 0.0), (0.094, 0.018)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.094, 0.014), (0.068, 0.027), (0.0, 0.032)], c, ax, 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.035, 0.0), (0.035, 0.016), (0.0, 0.022)], (side * 0.86, 0.48, zn - 0.01), (0, 0, 1), 12, default="lamp_amber",
                    uv_mode="disc")
    # bumpers: slim wraparound chrome blades
    def wrap(zc, sign, y):
        def path(u):
            t = (u - 0.5) * 2
            x = t * 1.12
            e = np.clip(np.abs(t) - 0.84, 0, None) / 0.16
            z = zc - sign * (0.04 * t ** 2 + 0.14 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(wrap(zn + 0.05, 1, 0.40), 0.065, 30, 10, "chrome", squash=(0.45, 1.0))
    car.sweep(wrap(zt - 0.04, -1, 0.42), 0.062, 30, 10, "chrome", squash=(0.45, 1.0))
    for side in (1, -1):
        car.sweep(lambda u, x=side * 0.36: np.stack([x + 0 * u, 0.33 + 0.18 * u, zn + 0.09 - 0.03 * u], 1), 0.035, 6, 8, "chrome")
    # door handle, mirror, drip-rail chrome over the vinyl edge
    for side in (1, -1):
        car.box("chrome", (side * 1.165 - 0.012, 0.91, -0.30), (side * 1.165 + 0.012, 0.94, -0.16))
    car.sweep(lambda u: np.stack([-1.06 - 0.12 * u, 1.03 + 0.04 * u, 0.70 + 0 * u], 1), 0.013, 4, 6, "chrome")
    car.revolve([(0.055, 0.0), (0.055, 0.02), (0.0, 0.028)], (-1.19, 1.08, 0.70), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: front buckets, a rear bench, a dash and wheel
    for sx in (-0.45, 0.45):
        car.box("seat", (sx - 0.30, 0.50, -0.05), (sx + 0.30, 0.66, 0.42))
        car.box("seat", (sx - 0.28, 0.64, -0.16), (sx + 0.28, 1.18, -0.04))
    car.box("seat", (-0.92, 0.50, -1.10), (0.92, 0.66, -0.62))
    car.box("seat", (-0.92, 0.64, -1.22), (0.92, 1.12, -1.10))
    car.box("interior_dark", (-1.00, 0.78, 0.66), (1.00, 0.98, 0.80))
    car.revolve([(0.18, -0.012), (0.18, 0.012)], (-0.45, 0.98, 0.52), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.58, rim_mat="paint_wheel", cap_mat="chrome", whitewall=1.0, cap_dome=0.12)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / LEN
    lines_u = [(U(0.76), 0.16, 0.50), (U(-0.42), 0.16, 0.50), (U(ZSB + 0.03), 0.50, 1.0), (U(ZBB - 0.04), 0.50, 1.0)]
    lines_v = [(0.86, U(-2.15), U(ZBB - 0.04)), (0.86, U(ZSB + 0.03), U(2.18))]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, lines_v=lines_v, ao_v=[(0.18, 0.36, 0.30)], seed=13)
    car.materials["paint_trim"] = tex_paint(PAINT, 64, seed=14)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=15)
    car.materials["vinyl"] = tex_vinyl()
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(128, bars=9, rgb=(30, 30, 32))
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((14, 14, 14))
    car.materials["interior_liner"] = tex_flat((117, 110, 97))
    car.materials["trim_dark"] = tex_flat((24, 24, 27))
    car.materials["plate"] = tex_plate()
    car.materials["seat"] = tex_leather((96, 70, 56))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    car.materials["whitewall"] = tex_flat((226, 224, 218))
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    return car


def tex_vinyl(size=128):
    """a black vinyl roof: a fine leather grain and faint seams along the car"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    n = noise(size, size, 2, 41) * 0.6 + noise(size, size, 9, 42) * 0.4
    v = 20 + 10 * n
    v = np.where(np.abs(((yy * 3) % 1.0) - 0.5) > 0.48, v * 0.6, v)
    return Image.fromarray(np.dstack([v, v, v * 1.05]).clip(0, 255).astype(np.uint8))


def tex_plate(size=(128, 48)):
    from PIL import ImageDraw, ImageFont, ImageOps
    im = Image.new("RGB", size, (226, 222, 205))
    d = ImageDraw.Draw(im)
    d.rectangle([1, 1, size[0] - 2, size[1] - 2], outline=(30, 30, 40), width=2)
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    f = ImageFont.truetype(p, 24) if os.path.exists(p) else ImageFont.load_default()
    t = "MX 613"
    w = d.textlength(t, font=f)
    d.text(((size[0] - w) / 2, 9), t, fill=(30, 30, 40), font=f)
    return ImageOps.flip(im)        # the box's -z face reads its picture upside down


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va15/p013.png", LEN)
