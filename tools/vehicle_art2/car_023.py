#!/usr/bin/env python3
"""023 Hot Dog Van (VEHICLE-ART-27): the catalog's 1950s hot-dog van read from the GTA2 sprite nose down
(assets-src/cars/sprites_x4/023_hot_dog_van_default.png, body 44 x 86 px: 3.44 x 6.72 m, axles +26 / -26 px). The
sprite is 027's van (the same cab, box, hatch columns and footprint) in one orange, with a giant hot dog lying along
the roof instead of the cone: two golden bun halves either side of a brown sausage that runs from the box's tail
over the cab's roof, a mustard zigzag down its top. So the body is 027's kit van (VEHICLE-ART-15/16, car_027.py)
re-coloured (orange cab and box, a brown belt band, slatted awnings in the sprite's tan and brown, HOT DOGS boards)
with the hot dog instead of the cone. 23 is a livery (identity.cpp Livery: drawn untinted): its colours are its own.
The hot-dog dummies 24 / 25 / 26 / 85 draw this mesh (manifest cars.by_model). It replaces the image-to-3D shell
(stretched awning stripes over a lumpy box; its swung door crossed the first-person exit view: qaexp59).
Metres, +z nose, 1 block = 5 m."""
import math
import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "023_hot_dog_van"
SPRITE = (200, 110, 40)
PAINT = (235.0, 235.0, 235.0)
BODY = (206, 112, 40)          # the van's one orange (cab and box)
CREAM = BODY
TAN = BODY
ORANGE = (96, 48, 20)           # the belt band and the awning's dark slats: the sprite's brown
SLAT = (214, 176, 112)          # the awning's light slats: the sprite's tan
BUN = (226, 152, 58)
SAUSAGE = (148, 66, 36)
MUSTARD = (246, 192, 24)
LEN = 86 / 64 * 5.0               # 6.72 m
HALF_W = 44 / 64 * 5.0 / 2        # 1.72 m
ZF, ZR = 28 / 64 * 5.0, -24 / 64 * 5.0     # +2.19 / -1.875 (027's: the catalog's +26 / -26 px would put the rear wheels under the hatch)
R_TYRE, W_TYRE = 0.44, 0.28
R_REAR, W_REAR = 0.46, 0.44
X_WHEEL, X_REAR = 1.15, 1.25
R_ARCH = 0.54
R_ARCH_R = R_REAR + 0.10              # the box's rear arches (VEHICLE-ART-28)
ZC = 0.90                          # cab back (inside the box's front wall)
ZBF = 1.00                         # box front wall
BOX_HW = 1.66
BOX_BOT, BOX_TOP = 0.82, 2.55
SV = 2.6
AWN = 0.40                         # awning reach (VEHICLE-ART-16: 0.55 stood far proud of the footprint)


def build():
    car = Car(NAME)
    car.preview_tint = None
    zn = LEN / 2 - 0.10
    zt = -LEN / 2 + 0.06

    # ---- cab + bonnet: 058's loft, a rounded 1950s pickup front with pontoon wings
    BOT = 0.70
    belt0 = spline([(ZC, 1.50), (1.9, 1.50), (2.3, 1.46), (3.0, 1.40), (zn, 1.30)])
    top0 = spline([(ZC, 2.10), (1.15, 2.17), (1.42, 2.15), (1.58, 2.06), (1.80, 1.62), (2.0, 1.58), (2.8, 1.52), (zn, 1.42)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.30 * np.exp(-((z - ZF) / 0.62) ** 2)
        return np.interp(z, [ZC, 1.62, 1.95, 2.9, zn], [1.18, 1.18, 0.98, 0.90, 0.80]) + swell
    tumble0 = spline([(ZC, 0.10), (1.4, 0.12), (1.8, 0.0), (zn, 0.0)])
    def arch(z):
        dz = np.abs(z - ZF)
        y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
        return np.where(dz < R_ARCH, y, 0)
    def ends(z, nose=0.25):
        dn = np.clip((z - (zn - nose)) / nose, 0, 1)
        dc = np.clip(((ZC + 0.06) - z) / 0.06, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dc ** 2, 0, 1))
    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * (0.85 + 0.15 * f) - inset
        belt = belt0(z)
        fh = 0.80 + 0.20 * f
        top = belt + (top0(z) - belt) * fh - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08)
        bot = belt - (belt - bot) * fh + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z)
        xl = hw * sepow(c, 0.35)
        yl = belt - (belt - bot) * sepow(s, 0.45)
        H = top - belt
        t = np.clip((v - 0.5) / 0.3, 0, 1) * 0.95
        xs = hw * (1 - t ** 6) ** (1 / 6) - tb * t
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** 6) ** (1 / 6) - tb * 0.95
        xr = X0 * (1 - w)
        yr = belt + H * (0.90 + 0.10 * (1 - (1 - w) ** 2.2) ** 0.45)
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
    side = win([(1.70, 0.56), (1.05, 0.56), (1.05, 0.77), (1.56, 0.77)], 0.05)
    # split screen: two panes either side of a centre bar (v = 1 is the centre line)
    screen = win([(1.76, 0.81), (1.76, 0.975), (1.60, 0.975), (1.60, 0.81)], 0.03)
    glass = sdf_union(side, screen)
    seal = lambda u, v: glass(u, v) - 0.014
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, ZC, zn, 0.0, 1.0, 60, 30, mirror=True,
                regions=[("glass", glass), ("interior_dark", seal), ("underbody", under)],
                default="paint_cab", uvfn=lambda u, v: ((u - ZC) / (zn - ZC), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, 1.76, 1.60, 1.70, 1.05], vkeys=[0.56, 0.77, 0.81, 0.975])
    car.cap(body, zn, 0.0, 1.0, 24, "paint_cab", regions=[("underbody", lambda r, v: np.asarray(v) - 0.14)])
    car.surface(lambda u, v: body(u, v, inset=0.06), ZC + 0.12, 1.75, 0.45, 1.0, 16, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for s_ in (1, -1):
        def liner(u, v, s_=s_):
            a = np.asarray(u, float); x = np.asarray(v, float)
            return s_ * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), ZF + (R_ARCH - 0.01) * np.cos(a)
        car.surface(liner, 0.05, math.pi - 0.05, 0.70, 1.45, 16, 2, default="underbody", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    # grille, bumper, lamps
    car.box("grille", (-0.55, 0.78, zn - 0.02), (0.55, 1.20, zn + 0.04))
    for yb in (0.78, 0.99, 1.20):
        car.sweep(lambda u, yb=yb: np.stack([(u - 0.5) * 1.16, yb + 0 * u, zn + 0.04 + 0 * u], 1), 0.020, 12, 8, "chrome")
    car.sweep(lambda u: np.stack([(u - 0.5) * 2 * 1.30, 0.62 + 0 * u, zn + 0.10 - 0.06 * ((u - 0.5) * 2) ** 2], 1), 0.09, 24, 10,
              "chrome", squash=(0.55, 1.0))
    for s_ in (1, -1):
        c = np.array([s_ * 0.92, 1.06, zn - 0.05])
        car.revolve([(0.12, -0.10), (0.125, 0.012), (0.11, 0.030)], c, (0, 0, 1), 22, default="chrome", uv_mode="disc")
        car.revolve([(0.11, 0.026), (0.072, 0.044), (0.0, 0.050)], c, (0, 0, 1), 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.040, 0.0), (0.040, 0.02), (0.0, 0.03)], (s_ * 0.66, 0.90, zn + 0.02), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        car.box("chrome", (s_ * 1.20 - 0.012, 1.40, 1.25), (s_ * 1.20 + 0.012, 1.43, 1.38))
        car.sweep(lambda u, s_=s_: np.stack([s_ * (1.15 + 0.25 * u), 1.85 + 0 * u, 1.62 + 0 * u], 1), 0.016, 4, 6, "chrome")
        car.box("chrome", (s_ * 1.42 - 0.04, 1.72, 1.60), (s_ * 1.42 + 0.04, 2.00, 1.64))
    car.box("chrome", (-0.012, 1.80, 1.62), (0.012, 2.10, 1.80))         # the split screen's centre bar
    # interior: bench + dash + wheel
    car.box("seat", (-1.05, 1.10, 1.02), (1.05, 1.28, 1.40))
    car.box("seat", (-1.05, 1.26, 0.96), (1.05, 1.90, 1.06))
    car.box("interior_dark", (-1.10, 1.50, 1.62), (1.10, 1.66, 1.74))
    car.revolve([(0.22, -0.012), (0.22, 0.012)], (-0.52, 1.62, 1.50), (0, 0.6, -1), 18, default="interior_dark", uv_mode="disc")

    # ---- the box: a rounded cream box, a serving hatch with a counter and a striped awning each side, a tan belt band
    def rear_arch(z):
        dz = np.abs(np.asarray(z, float) - ZR)
        return np.where(dz < R_ARCH_R, R_REAR + np.sqrt(np.clip(R_ARCH_R ** 2 - np.minimum(dz, R_ARCH_R) ** 2, 0, None)), 0.0)
    za0 = ZR - math.sqrt(R_ARCH_R ** 2 - (BOX_BOT - R_REAR) ** 2)   # where the arch meets the floor
    za1 = 2 * ZR - za0
    def box_body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        rr = 0.14                                           # corner radius (section)
        er = np.clip(np.minimum(z - zt, ZBF - z) / 0.12, 0, 1)
        hw = (BOX_HW - inset) * (0.97 + 0.03 * np.sqrt(1 - (1 - er) ** 2))
        lo, hi = BOX_BOT + inset, BOX_TOP - inset
        # the half section from the floor's centre line (v 0) round to the roof's (v 1): floor (0..0.16), lower corner
        # (0.16..0.24), side wall (0.24..0.76), upper corner (0.76..0.84), roof (0.84..1)
        cb = (v > 0.16) & (v < 0.24); ct = (v > 0.76) & (v < 0.84)
        ab = np.clip((v - 0.16) / 0.08, 0, 1) * math.pi / 2; at = np.clip((v - 0.76) / 0.08, 0, 1) * math.pi / 2
        x = np.where(v <= 0.16, (hw - rr) * np.clip(v / 0.16, 0, 1), np.where(v < 0.84, hw + 0 * v, (hw - rr) * (1 - np.clip((v - 0.84) / 0.16, 0, 1))))
        y = np.where(v <= 0.16, lo + 0 * v, np.where(v < 0.84, lo + rr + (hi - lo - 2 * rr) * np.clip((v - 0.24) / 0.52, 0, 1), hi + 0 * v))
        x = np.where(cb, hw - rr + rr * np.sin(ab), x); y = np.where(cb, lo + rr - rr * np.cos(ab), y)
        x = np.where(ct, hw - rr + rr * np.cos(at), x); y = np.where(ct, hi - rr + rr * np.sin(at), y)
        # VEHICLE-ART-28 qav108: a rear wheel arch in the box. The floor (0.82) sat 0.10 inside the rear tyres' circle
        # (top 0.92): the renderer's wheel split took 136 box faces and spun them with the wheels (body-coloured shards
        # over and under the tyre). The floor and the wall's bottom are lifted round the tyre (radius + 0.10); the wall
        # above keeps its heights (the hatch and the band are drawn in v)
        y = np.maximum(y, rear_arch(z) + inset)
        return x, y, z
    # v -> height on the side: y = lo + rr + (hi - lo - 2rr) (v - 0.24) / 0.52
    vy = lambda y: 0.24 + 0.52 * (y - BOX_BOT - 0.14) / (BOX_TOP - BOX_BOT - 0.28)
    HZ0, HZ1, HY0, HY1 = -1.55, 0.25, 1.30, 1.95      # the serving hatch
    hatch = lambda u, v: np.maximum(np.maximum(HZ0 - np.asarray(u), np.asarray(u) - HZ1), np.maximum(vy(HY0) - np.asarray(v), np.asarray(v) - vy(HY1)))
    hatch_frame = lambda u, v: hatch(u, v) - 0.04
    band = lambda u, v: np.abs(np.asarray(v) - vy(1.20)) - 0.035
    car.surface(box_body, zt, ZBF, 0.0, 1.0, 96, 40, mirror=True,
                regions=[("glass_hatch", hatch), ("chrome", hatch_frame), ("underbody", lambda u, v: np.asarray(v) - 0.155 + 0 * np.asarray(u))],
                default="paint_box", uvfn=lambda u, v: ((u - zt) / (ZBF - zt), v),
                ukeys=[HZ0, HZ1, HZ0 - 0.04, HZ1 + 0.04, za0, za1] + list(ZR + R_ARCH_R * np.sin(np.linspace(-1.2, 1.2, 25))), vkeys=[vy(HY0), vy(HY1), vy(HY0 - 0.04), vy(HY1 + 0.04), 0.16, 0.24, 0.76, 0.84,
                                                                vy(1.20) - 0.035, vy(1.20) + 0.035])
    car.cap(box_body, zt, 0.0, 1.0, 30, "paint_box")
    car.cap(box_body, ZBF, 0.0, 1.0, 30, "paint_box")
    # behind the hatch glass: a lit cream interior wall and a counter
    for s_ in (1, -1):
        x0, x1 = sorted((s_ * (BOX_HW - 0.45), s_ * (BOX_HW - 0.42)))
        car.box("hatch_wall", (x0, HY0 - 0.05, HZ0), (x1, HY1, HZ1))
        x0, x1 = sorted((s_ * (BOX_HW - 0.40), s_ * (BOX_HW + 0.12)))
        car.box("chrome", (x0, HY0 - 0.06, HZ0 + 0.05), (x1, HY0 - 0.01, HZ1 - 0.05))
        # awning: a striped canopy sloping out over the hatch, held by two struts
        def awn(u, v, s_=s_):
            z = HZ0 - 0.10 + (HZ1 - HZ0 + 0.20) * np.asarray(u, float)
            t = np.asarray(v, float)
            x = s_ * (BOX_HW + 0.02 + AWN * t)
            y = HY1 + 0.20 - 0.28 * t - 0.04 * np.sin(math.pi * t)
            return x, y, z
        car.surface(awn, 0.0, 1.0, 0.0, 1.0, 24, 6, default="awning", flip=s_ < 0,
                    uvfn=lambda u, v: (np.asarray(u) * 1.0, np.asarray(v)))
        car.sweep(lambda u, s_=s_: np.stack([s_ * (BOX_HW + 0.02 + AWN * u), HY1 + 0.20 - 0.28 * u - 0.30 + 0.30 * u, HZ0 - 0.08 + 0 * u], 1),
                  0.014, 4, 6, "chrome")
        car.sweep(lambda u, s_=s_: np.stack([s_ * (BOX_HW + 0.02 + AWN * u), HY1 + 0.20 - 0.28 * u - 0.30 + 0.30 * u, HZ1 + 0.08 + 0 * u], 1),
                  0.014, 4, 6, "chrome")
        # ICE CREAM board above the awning (a box face: reads unmirrored from outside on both sides)
        x0, x1 = sorted((s_ * BOX_HW, s_ * (BOX_HW + 0.025)))
        car.box("sign", (x0, 2.16, -1.55), (x1, 2.48, 0.25), uv_rect=(0.0, 0.0, 0.5, 1.0) if s_ > 0 else (0.5, 0.0, 1.0, 1.0))
    # rear: double doors (dark shut lines in the texture), lamps, bumper, plate
    for s_ in (1, -1):
        car.revolve([(0.06, -0.02), (0.06, 0.02), (0.0, 0.03)], (s_ * 1.40, 1.05, zt - 0.01), (0, 0, -1), 12, default="lamp_tail", uv_mode="disc")
        car.box("chrome", (s_ * 0.14 - 0.012, 1.45, zt - 0.03), (s_ * 0.14 + 0.012, 1.60, zt))
    car.sweep(lambda u: np.stack([(u - 0.5) * 2.9, 0.66 + 0 * u, zt - 0.06 + 0 * u], 1), 0.07, 20, 8, "chrome", squash=(0.5, 1.0))
    car.box("paint_box", (-0.20, 0.80, zt - 0.02), (0.20, 0.94, zt))
    # chassis under the box (VEHICLE-ART-28 qav108: the rails reach the floor and the rear bumper, axles on springs
    # under them, a fuel tank on the right rail; the shared floor pan is not hung under the vans: underpan.SKIP. Its
    # parts hung under the rails as a floating box between the axles. Nothing outboard of |x| 0.68 inside a tyre's circle)
    for s_ in (1, -1):
        car.box("underbody", (s_ * 0.55 - 0.07, 0.58, zt - 0.04), (s_ * 0.55 + 0.07, BOX_BOT + 0.005, 2.9))
        for zc, r in ((ZF, R_TYRE), (ZR, R_REAR)):          # leaf springs from the axle up to the rail
            car.box("underbody", (s_ * 0.55 - 0.06, r + 0.02, zc - 0.42), (s_ * 0.55 + 0.06, 0.60, zc + 0.42))
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.32, R_REAR + 0 * u, ZR + 0 * u], 1), 0.055, 6, 10, "underbody", up=(0, 0, 1))
    car.box("underbody", (-0.20, R_REAR - 0.13, ZR - 0.16), (0.20, R_REAR + 0.13, ZR + 0.14))     # the differential
    car.box("underbody", (-0.60, R_TYRE - 0.04, ZF - 0.05), (0.60, R_TYRE + 0.06, ZF + 0.05))      # the front beam
    car.sweep(lambda u: np.stack([0 * u, 0.50 + 0 * u, ZR + 0.14 + (ZF - 0.60 - ZR - 0.14) * u], 1), 0.04, 6, 8, "underbody",
              up=(0, 1, 0))                                                                        # the propshaft
    car.sweep(lambda u: np.stack([0.84 + 0 * u, 0.66 + 0 * u, -0.95 + 0.80 * u], 1), 0.17, 6, 14, "underbody",
              up=(0, 1, 0), squash=(1.3, 0.9))                                                     # the fuel tank

    # ---- the hot dog: two bun halves either side of the sausage, lying along the roof from the box's tail over the
    # cab's roof (the sprite's 3-65 px), a mustard zigzag down the sausage's top
    def loaf(cx, cy, a, b, z0, z1, flat=0.0):
        """a long rounded loaf along z: section ellipse a x b, ends rounded over 0.45 m; flat: the inner side
        pressed flat against the sausage (the bun's cut face)"""
        def fn(u, v):
            t = np.asarray(u, float); th = np.asarray(v, float)
            z = z0 + (z1 - z0) * t
            e = np.clip(np.minimum(z - z0, z1 - z) / 0.45, 0, 1)
            env = np.sqrt(np.clip(1 - (1 - e) ** 2, 0, 1)) * 0.92 + 0.08 * (e > 0)
            c, s_ = np.cos(th), np.sin(th)
            x = a * env * np.sign(c) * np.abs(c) ** 0.8
            if flat:
                x = np.where(np.sign(c) == -np.sign(cx), x * (1 - flat), x)
            y = b * env * np.sign(s_) * np.abs(s_) ** 0.9
            return cx + x, cy + np.maximum(y, -b * 0.55), z
        return fn
    HD0, HD1 = -3.05, 1.05
    for s_ in (1, -1):
        car.surface(loaf(s_ * 0.56, BOX_TOP + 0.30, 0.46, 0.34, HD0 + 0.10, HD1 - 0.10, flat=0.5), 0.0, 1.0, 0.0, 2 * math.pi, 60, 28,
                    default="bun", uvfn=lambda u, v: (np.asarray(v) / (2 * math.pi), np.asarray(u)), flip=s_ < 0)
    sausage = loaf(0.0, BOX_TOP + 0.42, 0.33, 0.30, HD0 - 0.15, HD1 + 0.30)
    car.surface(sausage, 0.0, 1.0, 0.0, 2 * math.pi, 70, 24, default="sausage",
                uvfn=lambda u, v: (np.asarray(v) / (2 * math.pi), np.asarray(u)))
    def mustard(u):
        t = np.asarray(u, float)
        z = HD0 + 0.25 + (HD1 - HD0 - 0.15) * t
        x = 0.17 * np.sin(t * 4.5 * 2 * math.pi)
        y = BOX_TOP + 0.42 + 0.30 * np.sqrt(np.clip(1 - (x / 0.33) ** 2, 0, 1)) + 0.012
        return np.stack([x, y, z], 1)
    car.sweep(mustard, 0.045, 160, 8, "mustard", squash=(1.0, 0.55))

    # wheels
    st = dict(rim_r=0.58, rim_mat="paint_wheel", cap_mat="chrome", whitewall=1.0, cap_dome=0.12)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, st)
    for nm, zc, xw in (("wheel_rl", ZR, -X_REAR), ("wheel_rr", ZR, X_REAR)):
        add_wheel(car, nm, (xw, R_REAR, zc), R_REAR, W_REAR, 1 if xw > 0 else -1, st)

    Uc = lambda z: (z - ZC) / (zn - ZC)
    car.materials["paint_cab"] = tex_paint(BODY, 256, lines_u=[(Uc(1.74), 0.30, 0.56), (Uc(1.02), 0.30, 0.56), (Uc(1.82), 0.56, 0.98)],
                                           ao_v=[(0.18, 0.36, 0.30)], seed=27)
    Ub = lambda z: (z - zt) / (ZBF - zt)
    car.materials["paint_box"] = tex_paint(BODY, 512, lines_u=[(Ub(zt + 0.02), 0.25, 0.75)], lines_v=[(0.16, 0.0, 1.0), (0.84, 0.0, 1.0)],
                                           seed=28)
    # the orange belt band painted into the box picture (was its own material)
    pb = np.asarray(car.materials["paint_box"]).copy()
    r0, r1 = int((vy(1.20) - 0.035) * 512), int(math.ceil((vy(1.20) + 0.035) * 512))
    pb[r0:r1] = (pb[r0:r1].astype(float) / np.array(CREAM, float) * np.array(ORANGE, float)).clip(0, 255).astype(np.uint8)
    car.materials["paint_box"] = Image.fromarray(pb)
    car.materials["paint_wheel"] = tex_flat((226, 222, 210), 16)
    car.materials["hatch_wall"] = tex_hatch_wall()
    car.materials["awning"] = tex_stripes(64)
    # a box's x face maps image columns to height and rows to length (row 0 at the tail): the +x board reads
    # front to tail (rows falling), up = columns rising; the -x board is that turned half round
    # both boards in one 256 x 512 picture: +x in the left half, -x (turned half round) in the right
    sr = ImageOps.mirror(tex_sign((512, 128)).transpose(Image.ROTATE_90))
    sign = Image.new("RGB", (256, 512))
    sign.paste(sr, (0, 0)); sign.paste(sr.transpose(Image.ROTATE_180), (128, 0))
    car.materials["sign"] = sign
    car.materials["bun"] = tex_bun(128)
    car.materials["sausage"] = tex_sausage(64)
    car.materials["mustard"] = tex_flat(MUSTARD)
    car.materials["glass_hatch"] = tex_glass(64, tint=(60, 70, 76), alpha=110)
    car.materials["glass"] = tex_glass(128, tint=(34, 42, 50), alpha=190)
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(128, bars=7)
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((14, 14, 14))
    car.materials["seat"] = tex_leather((120, 60, 50), 64)
    car.materials["lamp_head"] = tex_lamp("head", 64)
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread(128, grooves=5)
    car.materials["tyre_side"] = tex_tyre_side()
    car.materials["whitewall"] = tex_flat((226, 224, 218))
    bake_ao(car, body, ZC, zn, 0.0, 1.0, "paint_cab")
    bake_ao(car, box_body, zt, ZBF, 0.0, 1.0, "paint_box")
    return car


def tex_stripes(size=128, n=8):
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    s = (np.floor(xx * n) % 2) == 0
    rgb = np.where(s[..., None], np.array((176, 40, 30), float), np.array(SLAT, float))
    rgb *= (0.92 + 0.08 * (1 - yy))[..., None]
    return Image.fromarray(rgb.clip(0, 255).astype(np.uint8))


def tex_sign(size=(512, 128)):
    im = Image.new("RGB", size, (240, 214, 120))
    d = ImageDraw.Draw(im)
    d.rectangle([3, 3, size[0] - 4, size[1] - 4], outline=(96, 48, 20), width=6)
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    f = ImageFont.truetype(p, int(size[1] * 0.66)) if os.path.exists(p) else ImageFont.load_default()
    t = "HOT DOGS"
    w = d.textlength(t, font=f); b = d.textbbox((0, 0), t, font=f)
    d.text(((size[0] - w) / 2, (size[1] - (b[3] - b[1])) / 2 - b[1]), t, fill=(160, 52, 40), font=f)
    return im


def tex_bun(size=128):
    """the bun: golden crust (u round the loaf, v along it), lighter at the cut face, faint crumb noise"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    crust = 0.80 + 0.20 * np.cos(xx * 2 * math.pi - 0.4) ** 2
    rgb = np.array(BUN, float)[None, None] * (crust * (0.94 + 0.12 * noise(size, size, 10, 23)))[..., None]
    return Image.fromarray(rgb.clip(0, 255).astype(np.uint8))


def tex_sausage(size=64):
    """the sausage: glossy reddish brown with a darker grilled band every so often along it"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    band = 0.88 + 0.12 * (np.abs(((yy * 7) % 1.0) - 0.5) > 0.08)
    rgb = np.array(SAUSAGE, float)[None, None] * (band * (0.96 + 0.08 * noise(size, size, 6, 85)))[..., None]
    return Image.fromarray(rgb.clip(0, 255).astype(np.uint8))



def tex_hatch_wall(size=256):
    """VEHICLE-ART-28: the wall behind the serving hatch, seen through the glass: a cream tiled wall, a steel
    splashback with a shelf, a dark serving slot. A box's x face maps rows to length and columns to height."""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)      # yy along the box (rows), xx up the wall (columns)
    rgb = np.empty((size, size, 3)); rgb[:] = (226, 214, 188)
    tile = ((np.abs((xx * 10) % 1 - 0.5) > 0.47) | (np.abs((yy * 18) % 1 - 0.5) > 0.47))
    rgb[tile] = (182, 170, 150)
    steel = xx < 0.38
    rgb[steel] = (150, 156, 160)
    rgb[steel & (np.abs((yy * 6) % 1 - 0.5) > 0.48)] = (110, 114, 118)
    rgb[np.abs(xx - 0.38) < 0.012] = (70, 72, 74)
    shelf = np.abs(xx - 0.70) < 0.018
    rgb[shelf] = (120, 92, 60)
    for k in range(5):                                  # jars on the shelf
        c = (k + 0.5) / 5
        jar = (np.abs(yy - c) < 0.035) & (xx > 0.718) & (xx < 0.80)
        rgb[jar] = ((200, 60, 40), (240, 190, 40), (120, 150, 60), (200, 60, 40), (240, 190, 40))[k]
    return Image.fromarray(rgb.clip(0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va27/p023.png", LEN)
