#!/usr/bin/env python3
"""014 Eddy (VEHICLE-ART-16): the catalog's 1958 Edsel-style sedan ('tall, plain, the everyday car') read from the GTA2
sprite nose down (assets-src/cars/sprites_x4/014_eddy_default.png, body 30 x 62 px): a short flat bonnet, a wrap-around
screen at the sprite's window line 18 px, a long flat roof to an upright back light at 47 px, a long deck between two
modest fins, two long doors with a rear quarter light (the sprite's one door a side), the Edsel's vertical horse-collar
grille between low side grilles and quad lamps, horizontal tail lamps under the fins, heavy chrome bumpers. The roof is
the body's paint a shade lighter (the sprite's lighter roof: luminance only, so the identity record's hue holds:
audit item 8, the shell painted the sprite's roof colour over every remap). Neutral 235 paint tinted by the record.
084 Special Agent Car draws this mesh too (manifest by_model 84 -> 014_eddy). It replaces the image-to-3D shell
(blotched paint, torn wings, a smeared roof).
Metres, +z nose, 1 block = 5 m (catalog body 30 x 62 px = 2.34 x 4.84 m; axles +24 / -17 px)."""
import math
import os
import sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "014_eddy"
SPRITE = (150, 170, 40)            # the sprite's default green-yellow (previews only)
PAINT = (235.0, 235.0, 235.0)    # neutral: the identity record tints it
LEN = 62 / 64 * 5.0              # 4.84 m
HALF_W = 30 / 64 * 5.0 / 2       # 1.17 m
ZF, ZR = 24 / 64 * 5.0, -17 / 64 * 5.0     # +1.875 / -1.33
R_TYRE, W_TYRE = 0.35, 0.22
X_WHEEL = 0.95
R_ARCH = 0.42
BOT = 0.30
SV = 2.6
ZSB, ZBB = 1.12, -1.36           # screen base, back-light base
ZST, ZBT = 0.66, -0.98           # screen top, back-light top
V_BELT = 0.512


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2, -LEN / 2

    # a straight high belt, a flat long deck and a flat bonnet (the sprite's plain three-box), an upright back light
    belt0 = spline([(zt, 0.97), (-1.8, 0.99), (-0.6, 0.99), (1.2, 0.98), (2.0, 0.96), (zn, 0.90)])
    top0 = spline([(zt, 1.03), (zt + 0.25, 1.07), (ZBB, 1.09), (-1.20, 1.36), (ZBT, 1.50), (-0.80, 1.545), (0.30, 1.55),
                   (ZST, 1.52), (ZSB, 1.10), (1.40, 1.08), (2.10, 1.05), (zn - 0.08, 1.01), (zn, 0.94)])
    hw0 = spline([(zt, 1.10), (-1.9, 1.15), (-1.2, 1.17), (1.4, 1.17), (2.0, 1.15), (zn, 1.10)])
    tumble0 = spline([(zt, 0.0), (ZBB, 0.0), (ZBT - 0.08, 0.14), (ZST + 0.02, 0.14), (ZSB - 0.04, 0.0), (zn, 0.0)])

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
    # a long door's glass and a rear quarter light (two doors: the sprite's one door a side); a wrap-around screen;
    # an upright back light wrapping a little round the corners
    side1 = win([(1.04, 0.535), (-0.10, 0.535), (-0.10, 0.78), (0.62, 0.78)], 0.03)
    side3 = win([(-0.18, 0.535), (-1.22, 0.535), (-0.94, 0.78), (-0.18, 0.78)], 0.03)
    screen = win([(ZSB - 0.04, 0.70), (ZSB - 0.04, 1.03), (ZST + 0.03, 1.03), (ZST + 0.03, 0.78)], 0.03)
    backl = win([(ZBT - 0.03, 0.76), (ZBT - 0.03, 1.03), (ZBB + 0.04, 1.03), (ZBB + 0.04, 0.73)], 0.03)
    glass = sdf_union(side1, side3, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.014
    # a chrome side spear from the front wheel's arch back to the tail (the shipped 013's, a period touch)
    def spear(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        clear = np.minimum(np.abs(u - ZF), np.abs(u - ZR)) - (R_ARCH + 0.04)
        return np.maximum(np.maximum(np.abs(v - 0.40) * SV - 0.010, np.abs(u + 0.10) - 1.80), -clear)
    belt_chrome = lambda u, v: np.maximum(np.maximum(0.5 - np.asarray(v), np.asarray(v) - V_BELT), np.abs(np.asarray(u) + 0.1) - 2.0)
    under = lambda u, v: np.maximum(np.asarray(v) - 0.30, body(u, v)[1] - (BOT + 0.12))
    car.surface(body, zt, zn, 0.0, 1.0, 72, 30, mirror=True,
                regions=[("glass", glass), ("interior_dark", seal), ("chrome", sdf_union(belt_chrome, spear)), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, ZSB, ZST, ZBB, ZBT, 1.04, -0.10, -0.18, -1.22, -1.9, 1.7],
                vkeys=[0.535, 0.70, 0.73, 0.76, 0.78, 0.80, 0.86, 0.50, V_BELT, 0.40 - 0.010 / SV, 0.40 + 0.010 / SV])
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

    # a hood ornament at the bonnet's leading edge
    car.sweep(lambda u: np.stack([0 * u, top0(zn - 0.30 + 0.18 * u) + 0.01 + 0.03 * u, zn - 0.30 + 0.18 * u], 1), 0.016, 6, 6, "chrome",
              squash=(0.6, 1.0))
    # fins: modest blades on the rear wings' shoulders from the quarter light back to the tail; under each a horizontal
    # 'gull-wing' tail lamp along the tail panel (the Edsel's), a reversing lamp inboard
    for side in (1, -1):
        def fin(u, side=side):
            u = np.asarray(u, float)
            z = -1.05 + (zt + 0.04 + 1.05) * u
            x = side * (hw0(z) * (0.90 + 0.10 * ends(z)) - 0.05)
            y = belt0(z) + 0.01 + 0.06 * np.clip(u, 0, 1) ** 1.4
            return np.stack([x, y, z], 1)
        car.sweep(fin, lambda u: 0.035 + 0.03 * np.clip(np.asarray(u, float), 0, 1) ** 0.5, 20, 10, "paint_wheel", squash=(0.50, 1.0))
        x0, x1 = sorted((side * 0.30, side * 1.00))
        car.box("chrome", (x0 - 0.01, 0.80, zt - 0.012), (x1 + 0.01, 0.92, zt + 0.03))
        car.box("lamp_tail", (x0, 0.815, zt - 0.020), (x1, 0.905, zt + 0.02))
        car.revolve([(0.035, 0.0), (0.035, 0.012), (0.0, 0.018)], (side * 0.62, 0.66, zt - 0.005), (0, 0, -1), 12, default="lamp_head",
                    uv_mode="disc")
    # tail: the plate in a dark recess, the boot lock
    car.box("interior_dark", (-0.22, 0.52, zt - 0.004), (0.22, 0.70, zt + 0.04))
    car.box("plate", (-0.19, 0.545, zt - 0.010), (0.19, 0.675, zt + 0.0))
    car.revolve([(0.025, 0.0), (0.025, 0.01), (0.0, 0.014)], (0, 0.82, zt - 0.002), (0, 0, -1), 12, default="chrome", uv_mode="disc")

    # front: the vertical horse-collar grille in a chrome oval ring, a low horizontal grille each side, quad lamps
    car.box("grille", (-0.13, 0.46, zn - 0.06), (0.13, 0.88, zn + 0.004))
    car.sweep(lambda u: np.stack([0.155 * np.sin(2 * math.pi * u), 0.67 + 0.235 * np.cos(2 * math.pi * u), zn + 0.012 + 0 * u], 1),
              0.024, 40, 8, "chrome", caps=False)
    for side in (1, -1):
        x0, x1 = sorted((side * 0.22, side * 0.82))
        car.box("grille", (x0, 0.55, zn - 0.06), (x1, 0.66, zn + 0.004))
        car.sweep(lambda u, side=side: np.stack([side * (0.22 + 0.60 * u), 0.67 + 0 * u, zn + 0.008 + 0 * u], 1), 0.012, 8, 6, "chrome")
        car.sweep(lambda u, side=side: np.stack([side * (0.22 + 0.60 * u), 0.54 + 0 * u, zn + 0.008 + 0 * u], 1), 0.010, 8, 6, "chrome")
        for xl, r in ((0.98, 0.085), (0.80, 0.080)):
            c = np.array([side * xl, 0.78, zn - 0.01])
            ax = (side * 0.05, 0.02, 1)
            car.revolve([(r + 0.014, -0.08), (r + 0.012, 0.0), (r, 0.016)], c, ax, 22, default="chrome", uv_mode="disc")
            car.revolve([(r, 0.012), (r * 0.72, 0.024), (0.0, 0.029)], c, ax, 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.04, 0.0), (0.04, 0.016), (0.0, 0.022)], (side * 0.90, 0.60, zn - 0.01), (0, 0, 1), 12, default="lamp_amber",
                    uv_mode="disc")
    # bumpers: slim wraparound chrome blades
    def wrap(zc, sign, y):
        def path(u):
            t = (u - 0.5) * 2
            x = t * 1.10
            e = np.clip(np.abs(t) - 0.84, 0, None) / 0.16
            z = zc - sign * (0.04 * t ** 2 + 0.14 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(wrap(zn + 0.05, 1, 0.40), 0.085, 30, 10, "chrome", squash=(0.45, 1.0))
    car.sweep(wrap(zt - 0.04, -1, 0.44), 0.080, 30, 10, "chrome", squash=(0.45, 1.0))
    for side in (1, -1):
        car.sweep(lambda u, x=side * 0.36: np.stack([x + 0 * u, 0.33 + 0.18 * u, zn + 0.09 - 0.03 * u], 1), 0.035, 6, 8, "chrome")
    # door handles, mirror
    for side in (1, -1):
        car.box("chrome", (side * 1.165 - 0.012, 0.92, -0.09), (side * 1.165 + 0.012, 0.95, 0.05))
    car.sweep(lambda u: np.stack([-1.08 - 0.12 * u, 1.04 + 0.04 * u, 0.98 + 0 * u], 1), 0.013, 4, 6, "chrome")
    car.revolve([(0.055, 0.0), (0.055, 0.02), (0.0, 0.028)], (-1.21, 1.09, 0.98), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: front buckets, a rear bench, a dash and wheel
    car.box("seat", (-0.90, 0.50, -0.05), (0.90, 0.66, 0.45))
    car.box("seat", (-0.90, 0.64, -0.16), (0.90, 1.16, -0.04))
    car.box("seat", (-0.88, 0.50, -1.02), (0.88, 0.66, -0.58))
    car.box("seat", (-0.88, 0.64, -1.14), (0.88, 1.10, -1.02))
    car.box("interior_dark", (-0.98, 0.80, 0.80), (0.98, 1.00, 0.94))
    car.revolve([(0.19, -0.012), (0.19, 0.012)], (-0.45, 1.00, 0.64), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.60, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.12)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / LEN
    lines_u = [(U(1.06), 0.16, 0.50), (U(-0.14), 0.16, 0.50), (U(ZSB + 0.03), 0.50, 1.0), (U(ZBB - 0.04), 0.50, 1.0),
               (U(-2.20), 0.45, 0.80)]
    lines_v = [(0.80, U(-2.20), U(ZBB - 0.04)), (0.86, U(ZSB + 0.03), U(2.30))]
    pb = tex_paint(PAINT, 512, lines_u=lines_u, lines_v=lines_v, ao_v=[(0.18, 0.36, 0.30)], seed=14)
    # the roof a shade lighter than the body (the sprite's lighter roof, luminance only: the record's hue holds)
    a = np.asarray(pb, float).copy()
    rows = np.arange(512)[:, None] / 511.0; cols = np.arange(512)[None, :] / 511.0
    roof = ((rows > 0.93) & (cols > U(ZBT + 0.02)) & (cols < U(ZST - 0.02)))
    a = np.where(roof[..., None], np.minimum(a * 1.07, 255), a)
    car.materials["paint_body"] = Image.fromarray(a.astype(np.uint8))
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=15)
    car.materials["glass"] = tex_glass(128, tint=(30, 38, 46), alpha=195)
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(64, bars=6, rgb=(30, 30, 32))
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((16, 16, 18))
    car.materials["interior_liner"] = tex_flat((117, 110, 97))
    car.materials["plate"] = tex_plate()
    car.materials["seat"] = tex_leather((150, 140, 120), 64)
    car.materials["lamp_head"] = tex_lamp("head", 64)
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread(128)
    car.materials["tyre_side"] = tex_tyre_side()
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    return car


def tex_plate(size=(128, 48)):
    from PIL import ImageDraw, ImageFont, ImageOps
    im = Image.new("RGB", size, (226, 222, 205))
    d = ImageDraw.Draw(im)
    d.rectangle([1, 1, size[0] - 2, size[1] - 2], outline=(30, 30, 40), width=2)
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    f = ImageFont.truetype(p, 24) if os.path.exists(p) else ImageFont.load_default()
    t = "ED 014"
    w = d.textlength(t, font=f)
    d.text(((size[0] - w) / 2, 9), t, fill=(30, 30, 40), font=f)
    return ImageOps.flip(im)        # the box's -z face reads its picture upside down


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va16/p014.png", LEN)
