#!/usr/bin/env python3
"""034 Medicar (VEHICLE-ART-18): a 1959 American ambulance (Cadillac / Miller-Meteor idiom) read from the GTA2 sprite
(nose down in assets-src/cars/sprites_x4/034_medicar_default.png): a long cream bonnet between maroon wing tops that
flare at the nose, a raked wrap-around screen at row 40 of 114 (from the nose), a long high cream roof carrying a grey
lamp rack with four red lamps behind the screen, the red star of life in the middle and two red lamps with two whip
aerials at the back; maroon flanks the whole length under a gold pinstripe; a square tail with two rear doors.
It replaces the image-to-3D shell (qaexp7: navy blotches over the glass, a torn roof cross, white jagged patches and
orange streaks in the window band: the sprite's colour classes smeared through a generated texture).
034 is a livery (identity.cpp Livery): drawn untinted, so the colours here are the car's own. The livery is painted
by where each texel lies on the body (cream above the belt, maroon below, the roof star where the roof is), not by
texture rows, so no colour crosses a panel edge.
Metres, +z nose, 1 block = 5 m (catalog body 0.5 x 1.484 blocks: 2.5 x 7.42 m; axles +30 / -24 px of 95 body px)."""
import math
import os
import sys
import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa
from car_010 import tex_eggcrate  # noqa

NAME = "034_medicar"
SPRITE = (168, 152, 126)         # catalog default remap paint (previews only)
PAINT = (235.0, 235.0, 235.0)    # manifest paint_rgb (a livery: not used for a tint)
CREAM = (222, 210, 174)
MAROON = (124, 30, 24)
GOLD = (196, 150, 64)
RED = (178, 30, 26)
LEN = 1.484 * 5.0                # 7.42 m
HALF_W = 0.5 * 5.0 / 2           # 1.25 m
PX = LEN / 95.0                  # metres per sprite body pixel
ZF, ZR = 30 * PX, -24 * PX       # axles: 2.34, -1.87
R_TYRE, W_TYRE = 0.38, 0.25
X_WHEEL = 1.02
R_ARCH = 0.45
BOT = 0.31
ZSB, ZST = 1.46, 1.10            # screen base, screen top
STAR_Z = -18 * PX                # the roof star's centre (sprite row 75 from the nose)
CAP_Y0, CAP_Y1 = 0.25, 2.05      # the end panels' height range (paint_end rows)


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

    belt0 = spline([(zt, 1.04), (-3.2, 1.05), (-1.0, 1.03), (1.4, 1.01), (2.6, 0.98), (3.3, 0.92), (zn, 0.84)])
    top0 = spline([(zt, 1.12), (-3.66, 1.70), (-3.52, 1.93), (-3.2, 1.98), (0.70, 1.98), (ZST - 0.10, 1.90), (ZST, 1.80),
                   (ZSB, 1.17), (1.80, 1.12), (2.60, 1.09), (3.30, 1.03), (zn, 0.92)])
    hw0 = spline([(zt, 1.20), (-3.3, 1.25), (2.8, 1.25), (3.4, 1.22), (zn, 1.13)])
    tumble0 = spline([(zt, 0.0), (-3.62, 0.06), (-3.4, 0.07), (ZST - 0.1, 0.07), (ZSB, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    def ends(z, nose=0.42, tail=0.16):
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
        ex = 9.0
        xs = hw * (1 - t ** ex) ** (1 / ex) - tb * t
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** ex) ** (1 / ex) - tb * 0.95
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
    # side glass: front door (slanted A-pillar), rear door, the compartment's two windows either side of the
    # cross panel; the screen wraps a little round the corners
    side1 = win([(ZSB - 0.06, 0.535), (0.55, 0.535), (0.55, 0.78), (ZST + 0.02, 0.78)], 0.03)
    side2 = win([(0.42, 0.535), (-0.50, 0.535), (-0.50, 0.78), (0.42, 0.78)], 0.03)
    side3 = win([(-0.66, 0.535), (-1.45, 0.535), (-1.45, 0.78), (-0.66, 0.78)], 0.03)
    side4 = win([(-2.62, 0.535), (-3.30, 0.535), (-3.30, 0.78), (-2.62, 0.78)], 0.03)
    screen = win([(ZSB, 0.79), (ZSB, 1.03), (ZST, 1.03), (ZST, 0.79)], 0.03)
    glass = sdf_union(side1, side2, side3, side4, screen)
    seal = lambda u, v: glass(u, v) - 0.014
    belt_chrome = lambda u, v: np.maximum(np.abs(np.asarray(v) - 0.512) * SV - 0.010, np.abs(np.asarray(u) + 0.10) - 3.45)
    drip = lambda u, v: np.maximum(np.abs(np.asarray(v) - 0.792) * SV - 0.008, np.maximum(np.asarray(u) - ZST, -3.45 - np.asarray(u)))
    under = lambda u, v: np.maximum(np.asarray(v) - 0.30, body(u, v)[1] - (BOT + 0.12))
    car.surface(body, zt, zn, 0.0, 1.0, 96, 32, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chrome", sdf_union(belt_chrome, drip)), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, ZSB, ZST, 0.55, 0.42, -0.50, -0.66, -1.45, -2.62, -3.30],
                vkeys=[0.535, 0.78, 0.79, 0.512, 0.792])
    # the end panels: a fan to the centre, so the atlas (mapped by u along the body) cannot colour them; they take a
    # strip coloured by height (maroon under the belt, the pinstripe, cream above), u fixed, t = height
    def cap_uv(u_end):
        def uv(r, v):
            _, y, _ = body(np.full_like(np.asarray(v, float), u_end), v)
            C = float(np.mean(body(np.full(64, u_end), np.linspace(0, 1, 64))[1]))
            yy = C + np.asarray(r, float) * (y - C)
            return 0.5 + 0 * yy, np.clip((yy - CAP_Y0) / (CAP_Y1 - CAP_Y0), 0.0, 1.0)
        return uv
    car.cap(body, zt, 0.0, 1.0, 24, "paint_end", uvfn=cap_uv(zt))
    car.cap(body, zn, 0.0, 1.0, 20, "paint_end", regions=[("underbody", lambda u, v: np.asarray(v) - 0.12)], uvfn=cap_uv(zn))
    car.surface(lambda u, v: body(u, v, inset=0.06), -3.45, ZSB - 0.05, 0.30, 1.0, 30, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, zc=zc, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.70, 1.20, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # the tail: two rear doors (a shut line down the middle, a window in each, chrome handles), tall tail lamps
    zb = zt + 0.004
    car.box("seal", (-0.012, 0.50, zb - 0.012), (0.012, 1.86, zb + 0.01))
    for side in (1, -1):
        x0, x1 = sorted((side * 0.12, side * 0.46))
        car.box("glass", (x0, 1.30, zb - 0.02), (x1, 1.74, zb - 0.006))
        car.box("chrome", (side * 0.08 - 0.03, 1.02, zb - 0.03), (side * 0.08 + 0.03, 1.05, zb - 0.005))
        car.sweep(lambda u, side=side: np.stack([side * 1.13 + 0 * u, 0.70 + 0.62 * u, zt + 0.07 + 0.0 * u], 1), 0.07, 8, 10,
                  "lamp_tail", squash=(0.55, 0.55))
    # rear bumper with a step
    def wrap(zc, sign, y, half=1.24):
        def path(u):
            t = (u - 0.5) * 2
            x = t * half
            e = np.clip(np.abs(t) - 0.84, 0, None) / 0.16
            z = zc - sign * (0.04 * t ** 2 + 0.16 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(wrap(zt - 0.06, -1, 0.46), 0.09, 30, 10, "chrome", squash=(0.60, 1.0))
    car.box("underbody", (-0.55, 0.40, zt - 0.20), (0.55, 0.45, zt - 0.02))

    # front: dual headlamps in each wing tip, a wide egg-crate grille, the bumper with two bullet guards
    car.box("grille", (-0.82, 0.50, zn - 0.12), (0.82, 0.78, zn + 0.005))
    for yb in (0.48, 0.80):
        car.sweep(lambda u, yb=yb: np.stack([(u - 0.5) * 1.72, yb + 0 * u, zn + 0.012 - 0.05 * ((u - 0.5) * 2) ** 2], 1), 0.022, 16, 8, "chrome")
    for side in (1, -1):
        car.sweep(lambda u, side=side: np.stack([side * 0.86 + 0 * u, 0.48 + 0.32 * u, zn - 0.04 + 0 * u], 1), 0.022, 6, 8, "chrome")
        for k, dx in enumerate((0.0, 0.22)):
            c = np.array([side * (0.93 - dx), 0.76, zn - 0.05 + 0.01 * k])
            ax = (side * 0.08, 0.02, 1)
            car.revolve([(0.095, -0.08), (0.094, 0.0), (0.085, 0.016)], c, ax, 20, default="chrome", uv_mode="disc")
            car.revolve([(0.085, 0.012), (0.06, 0.024), (0.0, 0.030)], c, ax, 20, default="lamp_head", uv_mode="disc")
        car.revolve([(0.045, 0.0), (0.045, 0.02), (0.0, 0.03)], (side * 1.00, 0.56, zn - 0.06), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        x = side * 0.46
        car.revolve([(0.07, -0.10), (0.07, 0.0), (0.05, 0.08), (0.0, 0.14)], (x, 0.46, zn + 0.10), (0, 0, 1), 16, default="chrome", uv_mode="disc")
    car.sweep(wrap(zn + 0.07, 1, 0.42, 1.22), 0.09, 30, 10, "chrome", squash=(0.55, 1.0))
    car.sweep(lambda u: np.stack([0 * u, 0.95 + 0.04 * np.sin(math.pi * u), zn - 0.14 - 0.36 * u], 1), 0.016, 8, 6, "chrome")

    # roof: the lamp rack behind the screen (grey bar, four red domes along its front edge, a chrome siren),
    # two red lamps and two whip aerials at the back
    roof = lambda z: float(top0(np.array([z]))[0])
    ry = roof(0.2)
    car.box("rack", (-0.80, ry - 0.02, -0.39), (0.80, ry + 0.08, 0.62))
    for xr in (-0.70, 0.70):
        car.sweep(lambda u, xr=xr: np.stack([xr + 0 * u, ry + 0.10 + 0 * u, -0.36 + 0.95 * u], 1), 0.016, 10, 6, "chrome")
    for zr in (-0.25, 0.05, 0.35):
        car.box("rack", (-0.70, ry + 0.08, zr - 0.03), (0.70, ry + 0.11, zr + 0.03))
    for x in (-0.62, -0.22, 0.22, 0.62):
        car.revolve([(0.075, 0.0), (0.074, 0.03), (0.055, 0.10), (0.0, 0.13)], (x, ry + 0.08, 0.50), (0, 1, 0), 18,
                    default="beacon_red", uv_mode="disc", up=(0, 0, 1))
    car.revolve([(0.0, -0.07), (0.07, -0.06), (0.075, 0.05), (0.0, 0.07)], (0, ry + 0.20, 0.10), (0, 0, 1), 16, default="chrome", uv_mode="disc")
    car.box("seal", (-0.03, ry + 0.08, 0.06), (0.03, ry + 0.14, 0.14))
    yr = roof(-2.9)
    for side in (1, -1):
        car.revolve([(0.065, 0.0), (0.064, 0.03), (0.045, 0.08), (0.0, 0.10)], (side * 0.55, yr - 0.005, -2.90), (0, 1, 0), 16,
                    default="beacon_red", uv_mode="disc", up=(0, 0, 1))
        car.revolve([(0.025, 0.0), (0.02, 0.03), (0.0, 0.04)], (side * 0.42, yr - 0.005, -2.62), (0, 1, 0), 10, default="chrome", uv_mode="disc", up=(0, 0, 1))
        car.sweep(lambda u, side=side: np.stack([side * 0.42 + 0 * u, yr + 0.03 + 0.10 * u - 0.04 * u * u, -2.62 + 0.95 * u], 1),
                  0.006, 10, 5, "seal", caps=False)

    # door handles, mirrors
    for side in (1, -1):
        for zh in (0.40, -0.62):
            car.box("chrome", (side * 1.255 - 0.012, 0.98, zh), (side * 1.255 + 0.012, 1.01, zh + 0.15))
        car.sweep(lambda u, side=side: np.stack([side * (1.20 + 0.16 * u), 1.10 + 0.05 * u, 1.30 + 0 * u], 1), 0.014, 4, 6, "chrome")
        car.revolve([(0.07, 0.0), (0.07, 0.02), (0.0, 0.03)], (side * 1.38, 1.17, 1.30), (0, 0, -1), 14, default="chrome", uv_mode="disc")

    # interior: the front bench, a dash, a partition, the cot (white sheet, red blanket) along the compartment
    car.box("seat", (-1.02, 0.55, 0.05), (1.02, 0.72, 0.62))
    car.box("seat", (-1.02, 0.70, -0.08), (1.02, 1.32, 0.06))
    car.box("interior_dark", (-1.10, 0.85, 1.25), (1.10, 1.08, 1.40))
    car.revolve([(0.20, -0.012), (0.20, 0.012)], (-0.45, 1.08, 1.00), (0, 0.45, -1), 18, default="interior_dark", uv_mode="disc")
    car.box("interior_dark", (-1.10, 1.32, -0.14), (1.10, 1.70, -0.10))
    car.box("sheet", (-0.70, 0.62, -3.20), (0.10, 0.80, -1.10))
    car.box("blanket", (-0.72, 0.80, -2.40), (0.12, 0.84, -1.20))
    car.box("sheet", (-0.66, 0.80, -3.12), (0.06, 0.88, -2.80))
    car.box("seat", (0.40, 0.55, -2.80), (1.02, 0.80, -1.40))

    style = dict(rim_r=0.56, rim_mat="paint_wheel", cap_mat="chrome", whitewall=1.0, cap_dome=0.12)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    car.materials["paint_body"] = tex_livery(body, belt0, top0, hw0, zt, LEN)
    car.materials["paint_wheel"] = tex_paint(CREAM, 64, seed=35)
    car.materials["paint_end"] = tex_end(belt0(np.array([zt]))[0] - 0.035)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_eggcrate()
    car.materials["rack"] = tex_flat((150, 152, 156), 16)
    car.materials["beacon_red"] = tex_flat((200, 30, 24), 16)
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((10, 10, 10))
    car.materials["seat"] = tex_leather((96, 80, 66))
    car.materials["sheet"] = tex_flat((214, 214, 208), 16)
    car.materials["blanket"] = tex_flat((150, 34, 30), 16)
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    car.materials["whitewall"] = tex_flat((226, 224, 218))
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    return car


def tex_livery(body, belt0, top0, hw0, zt, length, size=512):
    """the paint atlas coloured by where each texel lies on the body: cream above the belt, maroon below it (and on
    the front wing tops, flaring towards the nose as in the sprite), a gold pinstripe on the line, the red star of
    life on the roof and a red cross on each side's compartment panel; door shut lines"""
    s = (np.arange(size) + 0.5) / size
    S, T = np.meshgrid(s, s, indexing="xy")              # rows = t (v), columns = s (u)
    U = zt + S * length
    x, y, z = body(U, T)
    ax = np.abs(x)
    belt = belt0(z)
    col = np.ones(x.shape + (3,)) * np.array(CREAM, float)
    split = belt - 0.035
    maroon = y < split
    # the front wing tops: |x| beyond a line that widens from the screen base to the nose
    k = np.clip((z - ZSB) / (LEN / 2 - ZSB), 0, 1)
    maroon |= (z > ZSB - 0.2) & (ax > hw0(z) * (0.80 - 0.16 * k)) & (y < top0(z) + 0.02) & (T > 0.5)
    col[maroon] = MAROON
    gold = (np.abs(y - split) < 0.014) & (T < 0.52) & (z < LEN / 2 - 0.25) & (z > -LEN / 2 + 0.12)
    col[gold] = GOLD
    roof = (T > 0.80) & (z < ZST - 0.15)
    col[roof & star_of_life(x, z - STAR_Z)] = RED
    # the compartment's cream panel between its two windows: a red cross
    zc, yc = -2.04, belt0(np.array([-2.04]))[0] + 0.48
    cross = (T > 0.5) & (T < 0.8) & (((np.abs(z - zc) < 0.30) & (np.abs(y - yc) < 0.09)) | ((np.abs(z - zc) < 0.09) & (np.abs(y - yc) < 0.30)))
    col[cross] = RED
    # door shut lines (rear doors' centre line is geometry): front door, rear door, the side compartment door
    for zl in (ZSB - 0.02, 0.48, -0.56):
        line = (np.abs(z - zl) < 0.010) & (T > 0.25) & (T < 0.79)
        col[line] *= 0.30
    im = Image.fromarray(np.clip(col, 0, 255).astype(np.uint8))
    a = np.asarray(im.filter(ImageFilter.GaussianBlur(0.6)), float)
    n = noise(size, size, 6, 34) * 0.5 + noise(size, size, 40, 35) * 0.5
    a *= (0.985 + 0.03 * n)[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def tex_end(split, size=64):
    """the end panels' strip by height: maroon under the split, the gold pinstripe, cream above"""
    y = CAP_Y0 + (np.arange(size) + 0.5) / size * (CAP_Y1 - CAP_Y0)
    col = np.where((y < split)[:, None], np.array(MAROON, float), np.array(CREAM, float))
    col[np.abs(y - split) < 0.016] = GOLD
    a = np.repeat(col[:, None, :], size, 1)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va18/p034.png", LEN)
