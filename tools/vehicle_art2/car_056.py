#!/usr/bin/env python3
"""056 Taxi: a 1950s American four-door cab (Checker idiom) in the GTA2 sprite's livery: cab yellow,
a chequer strip down the roof with a TAXI sign box in the middle of it (the sprite's roof), a chequer
band along each side, a chrome grille between paired lamps, wraparound bumpers, whitewall tyres.
Metres, +z nose, 1 block = 5 m (catalog body 0.531 x 1.0 blocks: 2.66 x 5.0 m)."""
import math
import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "056_taxi"
YELLOW = (232, 158, 30)          # the sprite's cab yellow (median of its saturated texels, x4 sprite)
PAINT = YELLOW                   # a livery: the renderer does not tint it
LEN = 1.0 * 5.0
HALF_W = 0.531 * 5.0 / 2         # 1.33 m
ZF, ZR = 1.80, -1.25             # axles (CARI: 23 px forward, 16 px back)
R_TYRE, W_TYRE = 0.37, 0.25
X_WHEEL = 1.08
R_ARCH = 0.43
BOT = 0.30


def build():
    car = Car(NAME)
    zn, zt = LEN / 2, -LEN / 2

    belt0 = spline([(zt, 0.86), (-2.0, 1.00), (-1.0, 1.04), (0.8, 1.04), (1.6, 1.00), (2.3, 0.94), (zn, 0.86)])
    top0 = spline([(zt, 0.92), (-2.30, 1.10), (-1.95, 1.13), (-1.62, 1.16), (-1.30, 1.60), (-1.05, 1.75), (0.30, 1.78),
                   (0.60, 1.74), (1.02, 1.20), (1.30, 1.17), (2.1, 1.12), (2.4, 1.06), (zn, 0.96)])
    hw0 = spline([(zt, 1.16), (-2.2, 1.28), (-1.4, 1.33), (1.6, 1.33), (2.2, 1.28), (zn, 1.20)])
    tumble0 = spline([(zt, 0.0), (-1.6, 0.0), (-1.2, 0.22), (0.7, 0.22), (1.1, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    def ends(z, nose=0.14, tail=0.14):
        dn = np.clip((z - (zn - nose)) / nose, 0, 1)
        dt = np.clip(((zt + tail) - z) / tail, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dt ** 2, 0, 1))

    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * (0.88 + 0.12 * f) - inset
        belt = belt0(z)
        fh = 0.80 + 0.20 * f
        top = belt + (top0(z) - belt) * fh - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08)
        bot = belt - (belt - bot) * fh + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z) * hw / 1.33
        xl = hw * (0.93 + 0.07 * sepow(c, 1.2))                                     # near vertical flanks
        xl = np.where(s > 0.92, hw * (0.93 + 0.07 * sepow(c, 1.2)) * sepow(c, 0.08), xl)
        yl = belt - (belt - bot) * sepow(s, 0.30)
        # upper part: v 0.5..0.8 climbs the side (linear in height, so windows are placed by height),
        # v 0.8..1 crosses the roof from its rounded edge to the centre line
        H = top - belt
        t = np.clip((v - 0.5) / 0.3, 0, 1) * 0.95
        xs = hw * (1 - t ** 7) ** (1 / 7) - tb * t
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** 7) ** (1 / 7) - tb * 0.95
        xr = X0 * (1 - w)
        yr = belt + H * (0.95 + 0.05 * (1 - (1 - w) ** 4) ** 0.25)
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
    # v: 0.5 belt ... 1 roof centre; the side glass sits on the steep part (v < ~0.80)
    side1 = win([(0.92, 0.53), (0.06, 0.53), (0.06, 0.775), (0.50, 0.775)], 0.035)
    side2 = win([(-0.04, 0.53), (-0.92, 0.53), (-0.92, 0.775), (-0.04, 0.775)], 0.035)
    side3 = win([(-1.02, 0.53), (-1.40, 0.53), (-1.12, 0.775), (-1.02, 0.775)], 0.035)
    screen = win([(1.04, 0.80), (1.04, 1.03), (0.62, 1.03), (0.62, 0.80)], 0.03)
    backl = win([(-1.15, 0.80), (-1.15, 1.03), (-1.58, 1.03), (-1.58, 0.80)], 0.04)
    glass = sdf_union(side1, side2, side3, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.014
    # chequer band below the side windows, chequer strip down the roof (the sprite's)
    band = lambda u, v: np.maximum(np.abs(np.asarray(v) - 0.475) * SV - 0.055, np.abs(np.asarray(u) + 0.3) - 1.95)
    roofstrip = lambda u, v: np.maximum((1 - np.asarray(v)) * SV * 1.6 - 0.15, np.abs(np.asarray(u) + 0.25) - 0.82)
    belt_chrome = lambda u, v: np.maximum(np.abs(np.asarray(v) - 0.505) * SV - 0.014,
                                          np.maximum(np.abs(np.asarray(u) - 0.2) - 2.25, -np.where(arch(np.asarray(u, float)) > 0, -1.0, 1.0)))
    under = lambda u, v: np.maximum(np.asarray(v) - 0.30, body(u, v)[1] - (BOT + 0.12))
    car.surface(body, zt, zn, 0.0, 1.0, 64, 30, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chequer", band), ("chequer_roof", roofstrip),
                         ("chrome", belt_chrome), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, 1.04, 0.62, -1.15, -1.58],
                vkeys=[0.53, 0.775, 0.80, 0.42, 0.505])
    # the boot and nose panels: the end rings fanned shut (flat panels with the loft's rounded rims)
    car.cap(body, zt, 0.0, 1.0, 20, "paint_body", regions=[("underbody", lambda u, v: np.asarray(v) - 0.12)])
    car.cap(body, zn, 0.0, 1.0, 20, "paint_body", regions=[("underbody", lambda u, v: np.asarray(v) - 0.12)])
    # chequer UVs: the band repeats along the car; the surface UV (u = z / LEN) is scaled in the texture
    car.surface(lambda u, v: body(u, v, inset=0.06), -1.6, 1.05, 0.30, 1.0, 22, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    # wheel well liners
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, zc=zc, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.70, 1.30, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # front: a chrome grille between paired lamps, a bonnet ornament
    car.box("grille", (-0.62, 0.52, zn - 0.10), (0.62, 0.86, zn + 0.035))
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.30, 0.88 + 0 * u, zn + 0.035 - 0.04 * ((u - 0.5) * 2) ** 2], 1), 0.022, 16, 8, "chrome")
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.30, 0.50 + 0 * u, zn + 0.035 - 0.04 * ((u - 0.5) * 2) ** 2], 1), 0.022, 16, 8, "chrome")
    for side in (1, -1):
        for k, dx in enumerate((0.90, 1.12)):
            c = np.array([side * dx, 0.80, zn + 0.02 - 0.03 * k])
            car.revolve([(0.098, -0.04), (0.100, 0.010), (0.088, 0.024)], c, (side * 0.05, 0.05, 1), 20, default="chrome", uv_mode="disc")
            car.revolve([(0.088, 0.020), (0.06, 0.030), (0.0, 0.034)], c, (side * 0.05, 0.05, 1), 20, default="lamp_head", uv_mode="disc")
        car.revolve([(0.04, 0.0), (0.04, 0.02), (0.0, 0.028)], (side * 0.98, 0.56, zn - 0.02), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        # tail lamps: tall red lenses on the rear corners
        car.sweep(lambda u, side=side: np.stack([side * 1.12 + 0 * u, 0.66 + 0.30 * u, zt + 0.03 + 0 * u], 1), 0.065, 6, 10,
                  "lamp_tail", squash=(1.0, 0.45))
    # bumpers: heavy wraparound chrome with over-riders
    def wrap(zc, sign, y):
        def path(u):
            t = (u - 0.5) * 2
            x = t * 1.30
            z = zc - sign * (0.06 * t ** 2 + 0.30 * np.clip(np.abs(t) - 0.82, 0, None) / 0.18 * np.clip(np.abs(t) - 0.82, 0, None) / 0.18 * 0.6)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(wrap(zn + 0.06, 1, 0.44), 0.085, 30, 10, "chrome", squash=(0.55, 1.0))
    car.sweep(wrap(zt - 0.06, -1, 0.46), 0.085, 30, 10, "chrome", squash=(0.55, 1.0))
    for zc, sgn in ((zn + 0.10, 1), (zt - 0.10, -1)):
        for side in (1, -1):
            x = side * 0.42
            car.sweep(lambda u, x=x, zc=zc, sgn=sgn: np.stack([x + 0 * u, 0.36 + 0.34 * u, zc + 0 * u], 1), 0.04, 6, 8, "chrome")
    # roof sign: a box with TAXI on both faces, set across the chequer strip
    sz = -0.20
    car.box("sign_body", (-0.36, 1.78, sz - 0.14), (0.36, 1.81, sz + 0.14))
    car.box("sign", (-0.32, 1.81, sz - 0.11), (0.32, 2.01, sz + 0.11))
    car.box("sign_body", (-0.33, 2.01, sz - 0.12), (0.33, 2.03, sz + 0.12))
    # door handles, mirrors
    for side in (1, -1):
        for zh in (0.12, -0.80):
            car.box("chrome", (side * 1.325 - 0.012, 1.00, zh), (side * 1.325 + 0.012, 1.03, zh + 0.15))
    car.sweep(lambda u: np.stack([-1.20 - 0.14 * u, 1.10 + 0.05 * u, 1.0 + 0 * u], 1), 0.014, 4, 6, "chrome")
    car.revolve([(0.06, 0.0), (0.06, 0.02), (0.0, 0.03)], (-1.36, 1.17, 1.0), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: bench seats and a dash
    car.box("seat", (-1.02, 0.55, -0.15), (1.02, 0.72, 0.45))
    car.box("seat", (-1.02, 0.70, -0.25), (1.02, 1.30, -0.12))
    car.box("seat", (-1.02, 0.55, -1.10), (1.02, 0.72, -0.55))
    car.box("seat", (-1.02, 0.70, -1.22), (1.02, 1.28, -1.08))
    car.box("interior_dark", (-1.10, 0.85, 0.90), (1.10, 1.10, 1.05))

    style = dict(rim_r=0.56, rim_mat="wheel_paint_dark", cap_mat="chrome", whitewall=1.0, cap_dome=0.12)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    # textures
    U = lambda z: (z - zt) / LEN
    lines_u = [(U(0.98), 0.30, 0.50), (U(0.02), 0.30, 0.50), (U(-0.96), 0.30, 0.50), (U(1.10), 0.50, 1.0), (U(-1.70), 0.50, 1.0)]
    car.materials["paint_body"] = tex_paint(YELLOW, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=56)
    car.materials["chequer"] = tex_chequer(512, cells_u=60, cells_v=2, v0=0.475 - 0.055 / 2.6, v1=0.475 + 0.055 / 2.6)
    car.materials["chequer_roof"] = tex_chequer(512, cells_u=36, cells_v=3, v0=1 - 0.15 / 2.6 / 1.6, v1=1.0, mirror_v=True)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(128, bars=9)
    car.materials["underbody"] = tex_flat((28, 27, 26))
    car.materials["interior_dark"] = tex_flat((10, 10, 10))
    car.materials["seat"] = tex_leather((96, 70, 52))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    car.materials["whitewall"] = tex_flat((226, 224, 218))
    car.materials["wheel_paint_dark"] = tex_flat((60, 58, 56))
    car.materials["sign_body"] = tex_flat(YELLOW)
    car.materials["sign"] = tex_sign()
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    return car


def tex_chequer(size, cells_u, cells_v, v0, v1, mirror_v=False):
    """black and white checks in the band v0..v1 of the body's (u, v) map, cells_u across the car's length"""
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0)
    t = np.clip((yy - v0) / max(v1 - v0, 1e-6), 0, 0.999)
    if mirror_v:
        t = 1 - t
    cu = np.floor(xx * cells_u).astype(int); cv = np.floor(t * cells_v).astype(int)
    w = (cu + cv) % 2 == 0
    v = np.where(w, 236, 22).astype(np.uint8)
    rgb = np.dstack([v, v, v])
    im = Image.fromarray(rgb).filter(ImageFilter.GaussianBlur(0.5))
    return im


def tex_sign(size=256):
    im = Image.new("RGB", (size, size), (238, 232, 205))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(size * 0.30))
    except OSError:
        font = ImageFont.load_default()
    # the box maps its faces with corner UVs: the word on each face, centred
    txt = "TAXI"
    bb = d.textbbox((0, 0), txt, font=font)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((size - w) / 2 - bb[0], (size - h) / 2 - bb[1]), txt, fill=(30, 26, 22), font=font)
    d.rectangle([4, 4, size - 5, size - 5], outline=(30, 26, 22), width=6)
    return im.transpose(Image.FLIP_TOP_BOTTOM)


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va2/p056.png", LEN)
