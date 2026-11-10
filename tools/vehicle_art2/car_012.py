#!/usr/bin/env python3
"""012 Cop Car (VEHICLE-ART-15): an early-1950s police cruiser (the catalog's 'Ford Mainline / Chevy Bel Air
black-and-white') read from the GTA2 sprite (nose down, as 008/036/040/057 read it; x4 sprite assets-src/cars/sprites_x4/012_cop_car_default.png):
a long bonnet with a centre crease (the sprite's two ribbed panels) ending in a dark grille notch, a raked screen,
a long roof carrying a light bar (a red and a blue dome either side of a grey siren block), a short boot; white roof,
bonnet and boot centres over navy flanks and wings (the sprite's navy wing tips and sides).
The doors are a white panel on the blue flank carrying a gold shield (front door) and POLICE (rear door), each side
its own texture so the lettering reads the right way round from outside on both sides. It replaces the image-to-3D
shell (a green-grey roof, a door of white and blue pixel blotches, a mottled bonnet: prmx 'police car door and flank
livery chunky green-white pixel smear').
012 is a livery (identity.cpp Livery): its paint is drawn untinted, so the colours here are the car's own.
Metres, +z nose, 1 block = 5 m (catalog body 0.5 x 0.984 blocks: 2.5 x 4.92 m; axles +-17 px of 64, stretched a
little to a 2.85 m wheelbase so the car does not read as a short-wheelbase cart)."""
import math
import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "012_cop_car"
SPRITE = (184, 197, 228)         # catalog default remap paint (previews only)
PAINT = (235.0, 235.0, 235.0)    # manifest paint_rgb (a livery: not used for a tint)
WHITE = (236, 238, 241)
NAVY = (26, 46, 128)
GOLD = (214, 172, 62)
LEN = 0.984 * 5.0
HALF_W = 0.5 * 5.0 / 2           # 1.25 m
ZF, ZR = 1.45, -1.40             # axles
R_TYRE, W_TYRE = 0.36, 0.24
X_WHEEL = 1.02
R_ARCH = 0.42
BOT = 0.29
SV = 2.6
D0, D1 = -0.94, 1.00             # the white door panel along z (rear arch .. front arch)
DV0, DV1 = 0.20, 0.5              # ... and in v (rocker .. the belt; the lower side crowds its top 15 cm into v 0.496..0.5)
V_BELT = 0.512                   # the belt moulding: v 0.5 .. 0.512 on the upper side (~2 cm)
ZSB, ZBB = 1.18, -1.55            # screen base, back-light base
V_TOP = 0.84                     # bonnet / boot: white inside v > V_TOP (|x| < ~0.75 m), navy shoulders outside
BAR_Z = -0.25                    # light bar centre (car_bodies.cpp DrawBeacons: along -0.05 x length)


def build():
    car = Car(NAME)
    car.preview_tint = None
    zn, zt = LEN / 2, -LEN / 2

    belt0 = spline([(zt, 0.95), (-2.0, 0.98), (-1.5, 0.98), (1.5, 0.96), (2.2, 0.92), (zn, 0.84)])
    top0 = spline([(zt, 0.98), (-2.25, 1.04), (-1.85, 1.07), (-1.55, 1.10), (-1.20, 1.50), (-1.00, 1.59), (0.60, 1.61),
                   (0.80, 1.56), (ZSB, 1.14), (1.50, 1.11), (2.10, 1.05), (2.32, 1.00), (zn, 0.88)])
    hw0 = spline([(zt, 1.14), (-2.1, 1.23), (-1.4, 1.25), (1.5, 1.25), (2.1, 1.23), (zn, 1.16)])
    tumble0 = spline([(zt, 0.0), (ZBB, 0.0), (-1.20, 0.19), (0.80, 0.19), (1.16, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    def ends(z, nose=0.36, tail=0.30):
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
        tb = tumble0(z) * hw / 1.25
        xl = hw * (0.93 + 0.07 * sepow(c, 1.2))
        xl = np.where(s > 0.92, hw * (0.93 + 0.07 * sepow(c, 1.2)) * sepow(c, 0.08), xl)
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
    side1 = win([(1.10, 0.535), (0.03, 0.535), (0.03, 0.78), (0.76, 0.78)], 0.03)
    side2 = win([(-0.07, 0.535), (-0.95, 0.535), (-0.95, 0.78), (-0.07, 0.78)], 0.03)
    side3 = win([(-1.04, 0.535), (-1.42, 0.535), (-1.07, 0.77), (-1.04, 0.77)], 0.025)
    screen = win([(1.14, 0.80), (1.14, 1.03), (0.83, 1.03), (0.83, 0.80)], 0.03)
    backl = win([(-1.03, 0.80), (-1.03, 1.03), (-1.50, 1.03), (-1.50, 0.80)], 0.04)
    glass = sdf_union(side1, side2, side3, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.014
    belt_chrome = lambda u, v: np.maximum(np.maximum(0.5 - np.asarray(v), np.asarray(v) - V_BELT), np.abs(np.asarray(u)) - 2.30)
    under = lambda u, v: np.maximum(np.asarray(v) - 0.30, body(u, v)[1] - (BOT + 0.12))
    # the door panel is cut out of the shell and laid back as its own pieces (below)
    door_cut = lambda u, v: np.maximum(np.maximum(D0 - np.asarray(u), np.asarray(u) - D1), np.maximum(DV0 - np.asarray(v), np.asarray(v) - DV1))
    # white: the glasshouse's sides above the belt, and the bonnet / boot tops inside the navy wing shoulders
    house = lambda u, v: np.maximum(0.5 - np.asarray(v, float), np.maximum(np.asarray(u) - ZSB, ZBB - np.asarray(u)))
    top_white = sdf_union(house, lambda u, v: V_TOP - np.asarray(v, float))
    car.surface(body, zt, zn, 0.0, 1.0, 72, 30, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chrome", belt_chrome), ("__cut", door_cut), ("underbody", under),
                         ("paint_top", top_white)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, 1.14, 0.83, -1.03, -1.50, 1.10, 0.03, -0.07, -0.95,
                       -1.04, -1.42, D0, D1, -2.30, 2.30, ZSB, ZBB],
                vkeys=[0.535, 0.78, 0.80, 0.50, V_BELT, DV0, DV1, V_TOP])
    del car.parts["__cut"]

    # door pieces: t follows the height (v crowds the side's height into its last few hundredths)
    vk = np.concatenate([np.linspace(DV0, 0.40, 5), 0.5 - (0.5 - 0.40) * np.linspace(1, 0, 16) ** 3.3])
    vk = np.clip(vk, DV0, DV1)
    zm = 0.5 * (D0 + D1)
    y_lo = float(body(np.array([zm]), np.array([DV0]))[1][0]); y_hi = float(body(np.array([zm]), np.array([DV1]))[1][0])
    def t_of(u, v):
        return np.clip((body(u, v)[1] - y_lo) / (y_hi - y_lo), 0, 1)
    def flip_x(fn):
        def g(u, v):
            x, y, z = fn(u, v)
            return -x, y, z
        return g
    for side, mat in ((1, "paint_door_r"), (-1, "paint_door_l")):
        # +x: seen from outside the nose is to the viewer's left, so s runs nose -> tail; -x: tail -> nose
        uvf = (lambda u, v: ((D1 - u) / (D1 - D0), t_of(u, v))) if side > 0 else (lambda u, v: ((u - D0) / (D1 - D0), t_of(u, v)))
        car.surface(body if side > 0 else flip_x(body), D0, D1, DV0, DV1, 40, 4, default=mat, uvfn=uvf,
                    flip=side < 0, ukeys=[-0.02, 0.0, 0.02], vkeys=list(vk))
    door_h = y_hi - y_lo

    car.cap(body, zt, 0.0, 1.0, 20, "paint_body", regions=[("underbody", lambda u, v: np.asarray(v) - 0.12)])
    car.cap(body, zn, 0.0, 1.0, 20, "paint_body", regions=[("underbody", lambda u, v: np.asarray(v) - 0.12)])
    car.surface(lambda u, v: body(u, v, inset=0.06), -1.50, 1.16, 0.30, 1.0, 22, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, zc=zc, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.66, 1.24, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # light bar: a dark base across the roof, a grey siren block in the middle, a red dome on -x and a blue one on +x
    # (DrawBeacons puts the red glow at -0.22 x width, the blue at +0.22 x width, along -0.05 x length)
    roof_y = float(top0(np.array([BAR_Z]))[0])
    car.box("trim_dark", (-0.66, roof_y - 0.02, BAR_Z - 0.13), (0.66, roof_y + 0.05, BAR_Z + 0.13))
    car.box("chrome", (-0.70, roof_y + 0.05, BAR_Z - 0.15), (0.70, roof_y + 0.07, BAR_Z + 0.15))
    car.box("siren", (-0.13, roof_y + 0.07, BAR_Z - 0.11), (0.13, roof_y + 0.19, BAR_Z + 0.11))
    for sx, mat in ((-0.50, "beacon_red"), (0.50, "beacon_blue")):
        prof = [(0.13, 0.0)] + [(0.13 * math.cos(a) + 1e-4, 0.03 + 0.12 * math.sin(a)) for a in np.linspace(0, math.pi / 2, 7)]
        car.revolve(prof, (sx, roof_y + 0.07, BAR_Z), (0, 1, 0), 22, default=mat, uv_mode="disc", up=(0, 0, 1))
        car.revolve([(0.14, -0.01), (0.14, 0.02), (0.13, 0.025)], (sx, roof_y + 0.07, BAR_Z), (0, 1, 0), 22, default="chrome",
                    uv_mode="disc", up=(0, 0, 1))
    # a spotlight on the driver's A-pillar (left: -x)
    car.sweep(lambda u: np.stack([-1.08 + 0.02 * u, 1.10 + 0.06 * u, 1.10 - 0.05 * u], 1), 0.016, 4, 6, "chrome")
    car.revolve([(0.0, -0.09), (0.06, -0.08), (0.07, 0.0), (0.072, 0.02)], (-1.06, 1.19, 1.06), (0, 0, 1), 16, default="chrome", uv_mode="disc")
    car.revolve([(0.072, 0.02), (0.0, 0.026)], (-1.06, 1.19, 1.06), (0, 0, 1), 16, default="lamp_head", uv_mode="disc")

    # front: round lamps in the wing tips, a bar grille with a centre bullet, parking lamps under the lamps
    # VEHICLE-ART-18: the grille was a flat box face with painted bars and a 20 cm chrome blob in the middle. Now a
    # dark recess (the seal black) behind real bars: five thin chrome bars, chrome side posts, the centre bar
    # and a slim pointed spinner (the 1951 Ford's), so the mouth has depth and the bars catch the sky
    car.box("seal", (-0.78, 0.50, zn - 0.12), (0.78, 0.76, zn + 0.005))
    for yb in np.linspace(0.535, 0.725, 5):
        car.sweep(lambda u, yb=yb: np.stack([(u - 0.5) * 1.50, yb + 0 * u, zn + 0.024 - 0.015 * ((u - 0.5) * 2) ** 2], 1), 0.009, 16, 6, "chrome",
                  squash=(1.0, 0.7))
    for side in (1, -1):
        car.sweep(lambda u, side=side: np.stack([side * 0.775 + 0 * u, 0.49 + 0.28 * u, zn + 0.0 + 0 * u], 1), 0.020, 6, 8, "chrome")
    for yb in (0.49, 0.77):
        car.sweep(lambda u, yb=yb: np.stack([(u - 0.5) * 1.62, yb + 0 * u, zn + 0.01 - 0.05 * ((u - 0.5) * 2) ** 2], 1), 0.022, 16, 8, "chrome")
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.50, 0.63 + 0 * u, zn + 0.03 - 0.05 * ((u - 0.5) * 2) ** 2], 1), 0.030, 16, 8, "chrome",
              squash=(1.0, 0.55))
    car.revolve([(0.062, -0.01), (0.064, 0.02), (0.045, 0.07), (0.016, 0.115), (0.0, 0.122)], (0, 0.63, zn + 0.02), (0, 0, 1), 20, default="chrome", uv_mode="disc")
    for side in (1, -1):
        c = np.array([side * 0.93, 0.71, zn + 0.005])     # proud of the nose panel (zn), outside the grille
        ax = (side * 0.06, 0.02, 1)
        car.revolve([(0.12, -0.10), (0.118, 0.0), (0.108, 0.020)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.108, 0.016), (0.078, 0.030), (0.0, 0.036)], c, ax, 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.045, 0.0), (0.045, 0.02), (0.0, 0.03)], (side * 0.93, 0.52, zn + 0.0), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
    car.sweep(lambda u: np.stack([0 * u, 0.98 + 0.03 * np.sin(math.pi * u), zn - 0.10 - 0.26 * u], 1), 0.016, 8, 6, "chrome")
    # bumpers
    def wrap(zc, sign, y):
        def path(u):
            t = (u - 0.5) * 2
            x = t * 1.22
            e = np.clip(np.abs(t) - 0.82, 0, None) / 0.18
            z = zc - sign * (0.06 * t ** 2 + 0.16 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(wrap(zn + 0.06, 1, 0.40), 0.085, 30, 10, "chrome", squash=(0.55, 1.0))
    car.sweep(wrap(zt - 0.05, -1, 0.42), 0.080, 30, 10, "chrome", squash=(0.55, 1.0))
    for side in (1, -1):
        car.sweep(lambda u, x=side * 0.40: np.stack([x + 0 * u, 0.32 + 0.30 * u, zn + 0.12 - 0.05 * u], 1), 0.045, 6, 8, "chrome")
    # tail: round lamps in the wing ends, a dark plate notch with a plate, the boot lid's centre crease
    for side in (1, -1):
        for yl in (0.80, 0.62):                       # twin round lamps in the tail panel (tail lamp over a reverse/stop lamp)
            c = (side * 0.84, yl, zt - 0.005)
            car.revolve([(0.085, -0.06), (0.085, 0.0), (0.078, 0.015)], c, (0, 0, -1), 18, default="chrome", uv_mode="disc")
            car.revolve([(0.078, 0.012), (0.055, 0.024), (0.0, 0.03)], c, (0, 0, -1), 18,
                        default="lamp_tail" if yl > 0.7 else "lamp_head", uv_mode="disc")
    # a chrome strip across the boot lid's trailing edge and a lock
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.30, 0.93 + 0 * u, zt + 0.01 + 0.02 * (1 - ((u - 0.5) * 2) ** 2)], 1), 0.014, 16, 6, "chrome")
    car.revolve([(0.03, 0.0), (0.03, 0.01), (0.0, 0.016)], (0, 0.86, zt - 0.002), (0, 0, -1), 12, default="chrome", uv_mode="disc")
    car.box("trim_dark", (-0.24, 0.52, zt - 0.005), (0.24, 0.72, zt + 0.04))
    car.box("plate", (-0.20, 0.55, zt - 0.012), (0.20, 0.69, zt + 0.0))
    # the bonnet's centre crease (the sprite's split bonnet)
    car.sweep(lambda u: np.stack([0 * u, top0(1.26 + 0.98 * u) - 0.004, 1.26 + 0.98 * u], 1), 0.014, 12, 6, "paint_top",
              squash=(1.0, 0.6))
    # door handles, mirror
    for side in (1, -1):
        for zh in (0.12, -0.80):
            car.box("chrome", (side * 1.245 - 0.012, 0.92, zh), (side * 1.245 + 0.012, 0.95, zh + 0.15))
    car.sweep(lambda u: np.stack([-1.14 - 0.13 * u, 1.04 + 0.05 * u, 1.05 + 0 * u], 1), 0.014, 4, 6, "chrome")
    car.revolve([(0.06, 0.0), (0.06, 0.02), (0.0, 0.03)], (-1.29, 1.11, 1.05), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: bench seats, a dash and wheel, a radio box on the dash
    car.box("seat", (-0.98, 0.53, 0.05), (0.98, 0.70, 0.62))
    car.box("seat", (-0.98, 0.68, -0.08), (0.98, 1.26, 0.06))
    car.box("seat", (-0.98, 0.53, -1.00), (0.98, 0.70, -0.48))
    car.box("seat", (-0.98, 0.68, -1.12), (0.98, 1.24, -1.00))
    car.box("interior_dark", (-1.05, 0.83, 1.12), (1.05, 1.05, 1.27))
    car.box("trim_dark", (0.05, 0.86, 1.00), (0.40, 0.98, 1.12))
    car.revolve([(0.19, -0.012), (0.19, 0.012)], (-0.43, 1.05, 0.86), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.58, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.10)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / LEN
    gaps_low = [(U(D1), 0.10, DV0), (U(-0.02), 0.10, DV0), (U(D0), 0.10, DV0)]
    car.materials["paint_body"] = tex_paint(NAVY, 512, lines_u=gaps_low, ao_v=[(0.18, 0.36, 0.30)], seed=120)
    gaps_top = [(U(ZSB + 0.03), 0.5, 1.0), (U(ZBB - 0.04), 0.5, 1.0)]
    car.materials["paint_top"] = tex_paint(WHITE, 512, lines_u=gaps_top, seed=121)
    car.materials["paint_door_r"] = tex_door(D1 - D0, door_h, flip=False)
    car.materials["paint_door_l"] = tex_door(D1 - D0, door_h, flip=True)
    car.materials["paint_wheel"] = tex_paint((34, 36, 44), 64, seed=122)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((10, 10, 10))
    car.materials["trim_dark"] = tex_flat((24, 24, 27))
    car.materials["siren"] = tex_siren()
    car.materials["plate"] = tex_plate()
    car.materials["seat"] = tex_leather((70, 66, 62))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["beacon_red"] = tex_dome((225, 30, 22))
    car.materials["beacon_blue"] = tex_dome((30, 70, 230))
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_top")
    # the door textures: s along z (reversed on +x), t by height: invert t at the panel's middle for the AO lookup
    vs = DV1 - (DV1 - DV0) * np.linspace(1, 0, 600) ** 4
    ts = t_of(np.full_like(vs, zm), vs)
    def door_uv(sgn):
        def f(S, T):
            Z = D1 - S * (D1 - D0) if sgn > 0 else D0 + S * (D1 - D0)
            return Z, np.interp(T, ts, vs)
        return f
    bake_ao(car, body, D0, D1, DV0, DV1, "paint_door_r", uv=door_uv(1))
    bake_ao(car, body, D0, D1, DV0, DV1, "paint_door_l", uv=door_uv(-1))
    return car


def _font(px):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, px)
    return ImageFont.load_default()


def tex_door(length, height, flip, out=(512, 256)):
    """the white door panel (both doors), drawn as seen from outside: not flip (the +x side, nose to the viewer's
    left) puts the front door at column 0; flip (the -x side) puts the rear door there. Row 0 = the belt (turned to
    t = 0 at the rocker at the end). A gold shield with a navy star on the front door, POLICE in navy on the rear
    door, the door gaps and a navy pinstripe along the panel's top and bottom edges."""
    ppm = 600                                        # pixels per metre while drawing
    W, H = int(length * ppm), int(height * ppm)
    a = np.ones((H, W, 3)) * np.array(WHITE, float)
    n = noise(H, W, 6, 131) * 0.5 + noise(H, W, 40, 132) * 0.5
    a *= (0.975 + 0.05 * n)[..., None]
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    gap = (60, 62, 70)
    front_w = int((D1 - (-0.02)) * ppm)               # the front door's width (gap at z = -0.02)
    x_mid = front_w if not flip else W - front_w
    for x in (1, x_mid, W - 2):
        d.line([(x, 0), (x, H)], fill=gap, width=3)
    d.rectangle([0, 0, W, int(0.012 * ppm)], fill=NAVY)
    d.rectangle([0, H - int(0.012 * ppm), W, H], fill=NAVY)
    fx0, fx1 = (0, x_mid) if not flip else (x_mid, W)   # the front door's columns
    rx0, rx1 = (x_mid, W) if not flip else (0, x_mid)   # the rear door's columns
    # front door: the shield
    cx, cy = (fx0 + fx1) // 2, int(H * 0.47)
    sh = int(0.30 * ppm); sw = int(0.24 * ppm)
    def shield(w, h):
        pts = []
        for k in range(5):                            # scalloped top edge
            x = cx - w / 2 + w * k / 4
            pts.append((x, cy - h / 2 + (0 if k % 2 == 0 else h * 0.07)))
        pts += [(cx + w / 2, cy - h * 0.05), (cx + w * 0.30, cy + h * 0.30), (cx, cy + h / 2), (cx - w * 0.30, cy + h * 0.30),
                (cx - w / 2, cy - h * 0.05)]
        return pts
    d.polygon(shield(sw + 12, sh + 14), fill=NAVY)
    d.polygon(shield(sw, sh), fill=GOLD)
    d.polygon(shield(sw - 22, sh - 26), fill=(238, 205, 104))
    r1, r2 = sw * 0.26, sw * 0.105
    star = [(cx + (r1 if k % 2 == 0 else r2) * math.sin(k * math.pi / 5), cy + 8 - (r1 if k % 2 == 0 else r2) * math.cos(k * math.pi / 5))
            for k in range(10)]
    d.polygon(star, fill=NAVY)
    f_small = _font(int(0.036 * ppm))
    bw = d.textlength("CITY", font=f_small)
    d.text((cx - bw / 2, cy - sh * 0.36), "CITY", fill=NAVY, font=f_small)
    # rear door: POLICE
    t = "POLICE"
    px = int(0.15 * ppm)
    f = _font(px)
    room = (rx1 - rx0) * 0.84
    if d.textlength(t, font=f) > room:
        f = _font(int(px * room / d.textlength(t, font=f)))
    bw = d.textlength(t, font=f)
    box = d.textbbox((0, 0), t, font=f)
    th = box[3] - box[1]
    d.text(((rx0 + rx1) / 2 - bw / 2, H * 0.47 - th / 2 - box[1]), t, fill=NAVY, font=f)
    im = im.filter(ImageFilter.GaussianBlur(0.7))
    return ImageOps.flip(im.resize(out, Image.LANCZOS))   # t = 0 at the rocker


def tex_dome(rgb, size=64):
    """a beacon dome by day: a saturated fresnel lens, brighter at the crown, ribbed"""
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0) * 2 - 1
    r = np.hypot(xx, yy)
    rib = 0.88 + 0.12 * (0.5 + 0.5 * np.cos(np.arctan2(yy, xx) * 18))
    b = (0.70 + 0.45 * (1 - r)) * rib
    rgb_ = np.array(rgb, float)[None, None] * b[..., None]
    rgb_ += np.exp(-(((xx + 0.3) ** 2 + (yy + 0.3) ** 2) / 0.03))[..., None] * 90
    return Image.fromarray(np.clip(rgb_, 0, 255).astype(np.uint8))


def tex_siren(size=64):
    """the siren block: grey cast metal with a dark slotted grille on its faces"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    slot = (np.abs(((yy * 6) % 1.0) - 0.5) < 0.18) & (xx > 0.12) & (xx < 0.88) & (yy > 0.15) & (yy < 0.85)
    v = np.where(slot, 40, 150 + 20 * (1 - yy))
    return Image.fromarray(np.dstack([v, v, v * 1.02]).clip(0, 255).astype(np.uint8))


def tex_plate(size=(128, 48)):
    im = Image.new("RGB", size, (232, 226, 196))
    d = ImageDraw.Draw(im)
    d.rectangle([1, 1, size[0] - 2, size[1] - 2], outline=(30, 30, 40), width=2)
    f = _font(26)
    t = "PD 012"
    w = d.textlength(t, font=f)
    d.text(((size[0] - w) / 2, 8), t, fill=(26, 46, 128), font=f)
    return ImageOps.flip(im)        # the box's -z face reads its picture upside down


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va15/p012.png", LEN)
