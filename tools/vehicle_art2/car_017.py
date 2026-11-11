#!/usr/bin/env python3
"""017 Fire Truck (VEHICLE-ART-23, qav56 "black/white shards and a torn hose bed hanging off the rear"): the
catalog's 1950s American pumper read from the GTA2 sprite nose down (assets-src/cars/sprites_x4/
017_fire_truck_default.png, 58 x 124 px, body 40 x 123 px; x4 row r -> z = (r - 248) x 0.0195 m): the nose
(rows 430-490) and a rounded closed cab (rows 345-430) on VEHICLE-ART-9's 058 cab recipe re-proportioned to those
stations, its pale roof carrying the sprite's two red beacons (the orange-red squares in the pale frame); behind the
cab the pump section (rows 250-345) with the round hose reel on top (the sprite's ringed disc) and the pump panels
with gauges on both flanks; a lamp bar across the bed's front (rows 220-245); the bed (rows 10-220): red lockers
down both sides (shutter seams, chrome handles, amber markers: the sprite's notched red flanks and orange dots), the
hose bed between them with folded canvas hose, and two ladders racked on top (the sprite's long white bars); a
tailboard with grab rails and tail lamps at the rear. Fire-engine red with a pale cab roof; 17 is a livery model
(identity.cpp), so these are its colours in every mode. It replaces the image-to-3D shell (unshaded black/white
shards standing past the tail, a bed of interleaved sliver planes).
Metres, +z nose, 1 block = 5 m (catalog body 0.625 x 1.922 blocks: 3.13 x 9.61 m)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "017_fire_truck"
RED = (150.0, 28.0, 22.0)
PAINT = RED
SPRITE = None
LEN = 1.922 * 5.0                 # 9.61 m
HALF_W = 0.625 * 5.0 / 2          # 1.56 m
# the 058 cab is built in its own frame (cab back -0.40, nose 2.94) and mapped onto this truck's stations
ZC58, ZN58 = -0.40, 6.17 / 2 - 0.14     # 058's own cab back and nose
ZC = 1.86                         # the cab's back wall here (sprite row ~345)
S = (LEN / 2 - 0.14 - ZC) / (6.17 / 2 - 0.14 - ZC58)
ZF = 1.72                         # 058 frame (under the bonnet's rear: the sprite shows no wheels)
ZR = -3.05                        # rear axle (CARI -41 px from the centre, pulled in ahead of the tailboard)
R_TYRE, W_TYRE = 0.50, 0.32
R_REAR, W_REAR = 0.50, 0.60
X_WHEEL, X_REAR = 1.12, 1.06
R_ARCH = 0.55
R_ARCH_R = 0.64
BOT = 0.62
ZT = -LEN / 2 + 0.06              # body tail (the tailboard reaches the bumper line)
ZB0 = 0.30                        # the bed's front (behind it the lamp bar, then the pump section to the cab)
LOCK_X0, LOCK_X1 = 0.86, 1.52     # lockers' inner / outer faces
LOCK_TOP = 2.02
HOSE_Y = 1.62                     # the hose bed's floor
LADDER_Y = 2.16


def z_of(z58):
    return ZC + (np.asarray(z58, float) - ZC58) * S


def map_part(car, first):
    """map every vertex added since `first` (per material counts) from the 058 frame to this truck's z"""
    for m, part in car.parts.items():
        k0 = first.get(m, 0)
        for i in range(k0, len(part.p)):
            p = part.p[i].copy(); n = part.n[i].copy()
            p[:, 2] = z_of(p[:, 2])
            n[:, 2] = n[:, 2] / S
            part.p[i] = p; part.n[i] = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def build():
    car = Car(NAME)
    zn = ZN58
    first = {m: len(p.p) for m, p in car.parts.items()}
    marks0 = len(car.markers)
    belt0 = spline([(ZC58, 1.55), (0.6, 1.56), (1.1, 1.52), (2.0, 1.46), (2.7, 1.38), (zn, 1.26)])
    top0 = spline([(ZC58, 2.32), (-0.2, 2.40), (0.30, 2.44), (0.62, 2.40), (0.80, 2.28), (1.05, 1.72), (1.40, 1.66),
                   (2.2, 1.60), (2.7, 1.52), (zn, 1.36)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.30 * np.exp(-((z - ZF) / 0.75) ** 2)
        base = np.interp(z, [ZC58, 0.9, 1.3, 2.6, zn], [1.20, 1.20, 1.04, 0.96, 0.84])
        return base + swell
    tumble0 = spline([(ZC58, 0.12), (0.6, 0.14), (1.0, 0.0), (zn, 0.0)])

    def arch(z):
        dz = np.abs(z - ZF)
        y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
        return np.where(dz < R_ARCH, y, 0)

    def ends(z, nose=0.25):
        dn = np.clip((z - (zn - nose)) / nose, 0, 1)
        dc = np.clip(((ZC58 + 0.06) - z) / 0.06, 0, 1)
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

    SU, SV = 1.0, 2.6
    def win(poly, r):
        p = np.array(poly, float)
        c = p.mean(0)
        d = p - c
        shrink = p - d / np.linalg.norm(d * [SU, SV], axis=1, keepdims=True) * r / np.array([SU, SV])
        f = poly_sdf(shrink, SU, SV)
        return lambda u, v: f(u, v) - r
    side = win([(0.74, 0.56), (-0.20, 0.56), (-0.20, 0.77), (0.60, 0.77)], 0.05)
    screen = win([(0.98, 0.81), (0.98, 0.985), (0.80, 0.985), (0.80, 0.81)], 0.03)
    glass = sdf_union(side, screen)
    seal = lambda u, v: glass(u, v) - 0.014
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, ZC58, zn, 0.0, 1.0, 64, 30, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("underbody", under),
                     ("roof_pale", lambda u, v: np.maximum(0.86 - np.asarray(v), np.asarray(u) - 0.78))],
                default="paint_body", uvfn=lambda u, v: ((u - ZC58) / (zn - ZC58), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, 0.98, 0.80, 0.78, 0.74, -0.20], vkeys=[0.56, 0.77, 0.81, 0.86])
    # the cab's back wall with its small rear window, and the nose
    # VEHICLE-ART-23: the 058 recipe's cab-back fan faced into the cab (mean normal +0.99 z); turned to face back
    kb = {m: len(p.p) for m, p in car.parts.items()}
    car.cap(body, ZC58, 0.0, 1.0, 24, "paint_body",
            regions=[("glass", lambda r, v: np.maximum(np.abs(np.asarray(v) - 0.84) * 6 - 0.6, np.asarray(r) - 0.75)),
                     ("underbody", lambda r, v: np.asarray(v) - 0.14)])
    for m, k0 in kb.items():
        face_out(car.parts[m], k0, -1)
    kb = {m: len(p.p) for m, p in car.parts.items()}
    car.cap(body, zn, 0.0, 1.0, 24, "paint_body", regions=[("underbody", lambda r, v: np.asarray(v) - 0.14)])
    for m, k0 in kb.items():
        face_out(car.parts[m], k0, +1)
    car.surface(lambda u, v: body(u, v, inset=0.06), -0.34, 1.0, 0.45, 1.0, 20, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for s_ in (1, -1):
        def liner(u, v, s_=s_):
            a = np.asarray(u, float); x = np.asarray(v, float)
            return s_ * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), ZF + (R_ARCH - 0.01) * np.cos(a)
        car.surface(liner, 0.05, math.pi - 0.05, 0.70, 1.40, 16, 2, default="underbody", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # grille: chrome bars across the nose under the bonnet, a heavy chrome bumper
    car.box("grille", (-0.62, 0.86, zn + 0.00), (0.62, 1.30, zn + 0.05))
    for yb in (0.86, 1.30):
        car.sweep(lambda u, yb=yb: np.stack([(u - 0.5) * 1.30, yb + 0 * u, zn + 0.05 + 0 * u], 1), 0.022, 12, 8, "chrome")
    car.sweep(lambda u: np.stack([(u - 0.5) * 2 * 1.40, 0.70 + 0 * u, zn + 0.10 - 0.05 * ((u - 0.5) * 2) ** 2], 1), 0.10, 24, 10,
              "chrome", squash=(0.55, 1.0))
    for s_ in (1, -1):
        c = np.array([s_ * 0.86, 1.10, zn + 0.01])
        car.revolve([(0.125, -0.10), (0.130, 0.012), (0.115, 0.030)], c, (0, 0, 1), 22, default="chrome", uv_mode="disc")
        car.revolve([(0.115, 0.026), (0.075, 0.044), (0.0, 0.050)], c, (0, 0, 1), 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.040, 0.0), (0.040, 0.02), (0.0, 0.03)], (s_ * 0.80, 1.00, zn + 0.02), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        # roof beacons (the sprite's two domes) on a bar
        car.revolve([(0.15, 0.0), (0.15, 0.08), (0.12, 0.19), (0.0, 0.23)], (s_ * 0.50, 2.47, 0.30), (0, 1, 0), 18,
                    default="lamp_beacon", uv_mode="disc")
        # mirrors on arms
        car.sweep(lambda u, s_=s_: np.stack([s_ * (1.18 + 0.22 * u), 1.75 + 0 * u, 0.80 + 0 * u], 1), 0.016, 4, 6, "chrome")
        car.box("chrome", (s_ * 1.40 - 0.04, 1.62, 0.78), (s_ * 1.40 + 0.04, 1.92, 0.82))
        car.box("chrome", (s_ * 1.215 - 0.012, 1.60, 0.30), (s_ * 1.215 + 0.012, 1.63, 0.44))
    car.box("trim_dark", (-0.70, 2.43, 0.22), (0.70, 2.48, 0.38))


    # the cab's interior (058 frame): a bench, the dash, a wheel
    car.box("seat", (-1.00, 1.02, -0.30), (1.00, 1.20, 0.25))
    car.box("seat", (-1.00, 1.18, -0.38), (1.00, 1.80, -0.26))
    car.box("interior_dark", (-1.08, 1.30, 0.70), (1.08, 1.50, 0.90))
    car.revolve([(0.22, -0.012), (0.22, 0.012)], (-0.50, 1.52, 0.52), (0, 0.6, -1), 18, default="interior_dark", uv_mode="disc")
    map_part(car, first)
    cab_body = lambda u, v: (lambda p: (p[0], p[1], z_of(p[2])))(body(u, v))

    # ---- the pump section between the cab and the bed: the hose reel on top, pump panels on the flanks ----------
    rbox(car, "paint_red", -1.30, 1.30, BOT, 1.58, ZB0 - 0.02, ZC - 0.02, 0.08)
    zr0 = 0.5 * (ZB0 + ZC)
    for s_ in (1, -1):
        x = s_ * 1.31
        car.box("chrome", (min(x, x + s_ * 0.02), 0.78, ZB0 + 0.20), (max(x, x + s_ * 0.02), 1.46, ZC - 0.22))
        for k, zg in enumerate((zr0 - 0.35, zr0, zr0 + 0.35)):
            car.revolve([(0.075, 0.0), (0.075, 0.02), (0.0, 0.03)], (x + s_ * 0.02, 1.30, zg), (s_, 0, 0), 16,
                        default="gauge", uv_mode="disc")
        for zg in (zr0 - 0.30, zr0 + 0.30):
            car.revolve([(0.10, 0.0), (0.10, 0.08), (0.07, 0.10), (0.0, 0.11)], (x + s_ * 0.02, 0.98, zg), (s_, 0, 0), 16,
                        default="chrome", uv_mode="disc")
        # the running board / step under the pump panel
        car.box("tread", (min(s_ * 1.20, s_ * 1.46), 0.56, ZB0 + 0.05), (max(s_ * 1.20, s_ * 1.46), 0.62, ZC - 0.05))
    # the hose reel (the sprite's ringed disc): a drum of red hose between chrome flanges, a dark hub
    c = (0.0, 1.58, zr0)
    car.revolve([(0.10, 0.0), (0.10, 0.36)], c, (0, 1, 0), 20, default="trim_dark", uv_mode="disc")
    car.revolve([(0.44, 0.02), (0.44, 0.05)], c, (0, 1, 0), 32, default="chrome", uv_mode="disc")
    car.revolve([(0.44, 0.02), (0.0, 0.02)], c, (0, 1, 0), 32, default="chrome", uv_mode="disc")
    car.revolve([(0.37, 0.05), (0.38, 0.12), (0.38, 0.26), (0.37, 0.33)], c, (0, 1, 0), 32, default="hose", uv_mode="tyre")
    car.revolve([(0.44, 0.33), (0.44, 0.36), (0.30, 0.36)], c, (0, 1, 0), 32, default="chrome", uv_mode="disc")
    car.revolve([(0.30, 0.355), (0.0, 0.355)], c, (0, 1, 0), 24, default="trim_dark", uv_mode="disc")

    # ---- the lamp bar across the bed's front (the sprite's row of lamps) -----------------------------------------
    car.box("trim_dark", (-1.48, 1.98, ZB0 - 0.24), (1.48, 2.08, ZB0 - 0.02))
    for x in (-1.30, 1.30):
        car.box("lamp_amber", (x - 0.13, 2.08, ZB0 - 0.22), (x + 0.13, 2.20, ZB0 - 0.04))
    for x in (-0.70, -0.25, 0.25, 0.70):
        car.box("lamp_clear", (x - 0.12, 2.08, ZB0 - 0.20), (x + 0.12, 2.16, ZB0 - 0.06))
    for s_ in (1, -1):
        car.box("trim_dark", (s_ * 1.40 - 0.05, LOCK_TOP - 0.02, ZB0 - 0.20), (s_ * 1.40 + 0.05, 1.98, ZB0 - 0.06))

    # ---- the bed: lockers down both sides around the rear wheel, the hose bed, two ladders on top --------------
    za, zb = ZR - R_ARCH_R - 0.06, ZR + R_ARCH_R + 0.06
    for s_ in (1, -1):
        x0, x1 = sorted((s_ * LOCK_X0, s_ * LOCK_X1))
        rbox(car, "paint_locker", x0, x1, BOT, LOCK_TOP, zb, ZB0 - 0.26, 0.06, uv_len=ZB0 - 0.26 - ZT)
        rbox(car, "paint_locker", x0, x1, BOT, LOCK_TOP, ZT, za, 0.06, uv_len=ZB0 - 0.26 - ZT)
        rbox(car, "paint_locker", x0, x1, 2 * R_REAR + 0.14, LOCK_TOP, za, zb, 0.06, uv_len=ZB0 - 0.26 - ZT)
        # the rear wheel's fender lip and liner
        def lip(u, s_=s_):
            a = np.asarray(u, float) * math.pi
            return np.stack([s_ * (LOCK_X1 + 0.02) + 0 * a, R_REAR + 0.02 + R_ARCH_R * np.sin(a), ZR + R_ARCH_R * np.cos(a)], 1)
        car.sweep(lip, 0.035, 20, 6, "chrome", caps=True)
        def liner(u, v, s_=s_):
            a = np.asarray(u, float); x = np.asarray(v, float)
            return s_ * x, R_REAR + 0.02 + (R_ARCH_R - 0.01) * np.sin(a), ZR + (R_ARCH_R - 0.01) * np.cos(a)
        car.surface(liner, 0.05, math.pi - 0.05, LOCK_X0, LOCK_X1, 16, 2, default="underbody",
                    uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
        # locker handles, amber side markers fore and aft, a grab rail along the top edge
        xo = s_ * (LOCK_X1 + 0.005)
        for zh in (ZB0 - 0.75, -1.30, -2.00, ZT + 0.45):
            car.box("chrome", (min(xo, xo + s_ * 0.03), 1.32, zh - 0.09), (max(xo, xo + s_ * 0.03), 1.37, zh + 0.09))
        for zm in (ZB0 - 0.40, ZT + 0.18):
            car.box("lamp_amber", (min(xo, xo + s_ * 0.03), LOCK_TOP - 0.20, zm - 0.07), (max(xo, xo + s_ * 0.03), LOCK_TOP - 0.10, zm + 0.07))
        car.sweep(lambda u, s_=s_: np.stack([s_ * (LOCK_X1 + 0.05) + 0 * u, LOCK_TOP - 0.06 + 0 * u,
                                             ZT + 0.25 + (ZB0 - 0.55 - ZT) * u], 1), 0.022, 24, 6, "chrome")
        # rear: a tail lamp and an amber above it on each locker's back, a vertical grab rail
        xm = s_ * 0.5 * (LOCK_X0 + LOCK_X1)
        car.revolve([(0.10, 0.0), (0.10, 0.03), (0.0, 0.05)], (xm, 1.00, ZT - 0.005), (0, 0, -1), 18, default="lamp_tail", uv_mode="disc")
        car.revolve([(0.06, 0.0), (0.06, 0.025), (0.0, 0.04)], (xm, 1.28, ZT - 0.005), (0, 0, -1), 14, default="lamp_amber", uv_mode="disc")
        car.sweep(lambda u, s_=s_: np.stack([s_ * (LOCK_X0 + 0.10) + 0 * u, 1.15 + 0.70 * u, ZT - 0.08 + 0 * u], 1), 0.022, 8, 6, "chrome")
    # the hose bed: a floor and the folded canvas hose between the lockers, a dark divider at its front
    car.box("trim_dark", (-LOCK_X0, HOSE_Y - 0.06, ZT + 0.02), (LOCK_X0, HOSE_Y, ZB0 - 0.26))
    car.box("hose_canvas", (-LOCK_X0 + 0.02, HOSE_Y, ZT + 0.06), (LOCK_X0 - 0.02, LOCK_TOP - 0.08, ZB0 - 0.30))
    car.box("paint_red", (-LOCK_X0, BOT, ZT + 0.02), (LOCK_X0, HOSE_Y - 0.06, ZT + 0.10))
    car.box("paint_red", (-LOCK_X0, HOSE_Y - 0.06, ZB0 - 0.30), (LOCK_X0, LOCK_TOP, ZB0 - 0.24))
    # ladder rack: three dark cross brackets on the lockers, two aluminium ladders lying on them
    for zb_ in (ZT + 0.40, -2.10, ZB0 - 0.45):
        car.box("trim_dark", (-LOCK_X1 + 0.06, LOCK_TOP, zb_ - 0.06), (LOCK_X1 - 0.06, LADDER_Y - 0.06, zb_ + 0.06))
    for xc in (-0.46, 0.46):
        for xr in (xc - 0.27, xc + 0.27):
            car.box("ladder", (xr - 0.035, LADDER_Y - 0.06, ZT + 0.05), (xr + 0.035, LADDER_Y + 0.05, ZB0 - 0.30))
        for zr_ in np.arange(ZT + 0.25, ZB0 - 0.35, 0.32):
            car.box("ladder", (xc - 0.24, LADDER_Y - 0.03, zr_ - 0.025), (xc + 0.24, LADDER_Y + 0.02, zr_ + 0.025))
    # the tailboard: a diamond-plate step across the back, the bumper under it, the plate
    car.box("tread", (-1.50, 0.52, ZT - 0.20), (1.50, 0.62, ZT + 0.12))
    car.box("trim_dark", (-1.50, 0.40, ZT - 0.22), (1.50, 0.52, ZT + 0.05))
    car.box("plate", (-0.24, 0.66, ZT - 0.012), (0.24, 0.80, ZT - 0.002))

    # chassis
    for s_ in (1, -1):
        car.box("trim_dark", (s_ * 0.50 - 0.07, BOT - 0.10, ZT + 0.10), (s_ * 0.50 + 0.07, BOT + 0.10, ZC + 1.0))
    car.box("underbody", (-1.25, BOT - 0.02, ZT + 0.12), (1.25, BOT + 0.01, ZB0))

    st = dict(rim_r=0.58, rim_mat="paint_red", cap_mat="chrome", whitewall=0.0, cap_dome=0.10)
    zf = float(z_of(ZF))
    for nm, zc, xw in (("wheel_fl", zf, -X_WHEEL), ("wheel_fr", zf, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, st)
    for nm, zc, xw in (("wheel_rl", ZR, -X_REAR), ("wheel_rr", ZR, X_REAR)):
        add_wheel(car, nm, (xw, R_REAR, zc), R_REAR, W_REAR, 1 if xw > 0 else -1, st)

    # ---- textures --------------------------------------------------------------------------------------------
    U = lambda z: (z - ZC58) / (zn - ZC58)
    lines_u = [(U(0.76), 0.30, 0.56), (U(-0.24), 0.30, 0.56), (U(1.06), 0.56, 0.98)]
    car.materials["paint_body"] = tex_paint(RED, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=171)
    L = ZB0 - 0.26 - ZT
    seams = [((zs - ZT) / L, 0.0, 1.0) for zs in (-0.40, -1.60, -2.35, ZR - 0.75, ZR + 0.75, -4.05)]
    car.materials["paint_locker"] = tex_paint(RED, 256, lines_u=seams, seed=172)
    car.materials["paint_red"] = tex_paint(RED, 128, seed=173)
    car.materials["roof_pale"] = tex_paint((226, 220, 208), 128, seed=174)
    car.materials["glass"] = tex_glass(256, tint=(40, 50, 58), alpha=150)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(128, bars=9)
    car.materials["underbody"] = tex_underbody()
    car.materials["trim_dark"] = tex_flat((30, 30, 32))
    car.materials["tread"] = tex_grille(64, bars=8)
    car.materials["gauge"] = tex_chrome_disc(64)
    car.materials["hose"] = tex_tread(128, grooves=6)
    car.materials["hose_canvas"] = canvas()
    car.materials["ladder"] = tex_paint((214, 214, 206), 32, seed=175)
    car.materials["plate"] = tex_flat((214, 204, 160))
    car.materials["interior_dark"] = tex_flat((40, 38, 36))
    car.materials["seat"] = tex_leather((70, 60, 52))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["lamp_clear"] = tex_flat((236, 236, 226))
    car.materials["lamp_beacon"] = tex_lamp("tail")
    car.materials["tyre_tread"] = tex_tread(grooves=6)
    car.materials["tyre_side"] = tex_tyre_side()
    bake_ao(car, cab_body, ZC58, zn, 0.0, 1.0, "paint_body")
    return car


def face_out(part, k0, sign):
    """turn the chunks added to `part` since k0 so their mean normal points along sign * z (and flip the winding)"""
    for i in range(k0, len(part.n)):
        if np.sign(part.n[i][:, 2].mean()) != sign:
            part.n[i] = -part.n[i]
            part.f[i] = part.f[i][:, ::-1]


def rr_ring(v, hx, hy, r):
    """a rounded rectangle's outline by arc length, v 0..1 anticlockwise from the bottom centre"""
    v = np.asarray(v, float)
    sx, sy = hx - r, hy - r
    segs = [sx, math.pi * r / 2, 2 * sy, math.pi * r / 2, 2 * sx, math.pi * r / 2, 2 * sy, math.pi * r / 2, sx]
    tot = sum(segs); s = (v % 1.0) * tot
    x = np.zeros_like(s); y = np.zeros_like(s)
    acc = 0.0
    pieces = []
    for k, L in enumerate(segs):
        t = np.clip((s - acc) / L, 0, 1) if L > 0 else 0 * s
        m = (s >= acc) & (s <= acc + L + 1e-12)
        if k == 0: px, py = t * sx, -hy + 0 * t
        elif k == 1: a = -math.pi / 2 + t * math.pi / 2; px, py = sx + r * np.cos(a), -sy + r * np.sin(a)
        elif k == 2: px, py = hx + 0 * t, -sy + t * 2 * sy
        elif k == 3: a = t * math.pi / 2; px, py = sx + r * np.cos(a), sy + r * np.sin(a)
        elif k == 4: px, py = sx - t * 2 * sx, hy + 0 * t
        elif k == 5: a = math.pi / 2 + t * math.pi / 2; px, py = -sx + r * np.cos(a), sy + r * np.sin(a)
        elif k == 6: px, py = -hx + 0 * t, sy - t * 2 * sy
        elif k == 7: a = math.pi + t * math.pi / 2; px, py = -sx + r * np.cos(a), -sy + r * np.sin(a)
        else: px, py = -sx + t * sx, -hy + 0 * t
        x = np.where(m, px, x); y = np.where(m, py, y)
        acc += L
    return x, y


def rbox(car, mat, x0, x1, y0, y1, z0, z1, r, uv_len=None):
    """a box with rounded long edges (a loft along z of a rounded rectangle), its ends closed by fans"""
    cx, cy, hx, hy = 0.5 * (x0 + x1), 0.5 * (y0 + y1), 0.5 * (x1 - x0), 0.5 * (y1 - y0)
    def fn(u, v):
        x, y = rr_ring(v, hx, hy, r)
        return cx + x, cy + y, np.asarray(u, float) + 0 * x
    L = uv_len or (z1 - z0)
    car.surface(fn, z0, z1, 0.0, 1.0, max(4, int((z1 - z0) / 0.25)), 40, default=mat,
                uvfn=lambda u, v: ((np.asarray(u) - z0) / L, np.asarray(v)))
    # flat end plates (a fan cap's normals shaded an X across the locker backs)
    car.box(mat, (x0 + 0.002, y0 + 0.002, z0), (x1 - 0.002, y1 - 0.002, z0 + 0.003), uv_rect=(0.02, 0.02, 0.06, 0.06))
    car.box(mat, (x0 + 0.002, y0 + 0.002, z1 - 0.003), (x1 - 0.002, y1 - 0.002, z1), uv_rect=(0.02, 0.02, 0.06, 0.06))


def canvas(size=128):
    """folded hose seen from above and behind: pale canvas in bands with dark fold lines"""
    yy = np.linspace(0, 1, size)[:, None] * np.ones((1, size))
    fold = np.abs(((yy * 9) % 1.0) - 0.5)
    v = 196 - 70 * np.exp(-((fold - 0.5) / 0.06) ** 2) + 8 * noise(size, size, 4, 9)
    from PIL import Image
    return Image.fromarray(np.clip(np.dstack([v, v * 0.96, v * 0.84]), 0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va23/p017.png", LEN)
