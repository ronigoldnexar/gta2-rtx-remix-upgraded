#!/usr/bin/env python3
"""028 Dementia Limousine (VEHICLE-ART-24): the catalog's stretched bubble car read from the GTA2 sprite nose down
(assets-src/cars/sprites_x4/028_dementia_limousine_default.png, body 26 x 78 px: 2.03 x 6.09 m; axles +29 / -21 px):
the 029 Dementia's egg (VEHICLE-ART-22, car_029.py) with the front-opening door and its wraparound screen at the nose
(the sprite's dark band 10 px from the nose), drawn out into a limousine: the long pale roof dome over four glazed
bays a side with pillars between (the sprite's dark marks down both flanks), a small back light (66 px), a longer
engine tail, a full-width rear track. Built by evaluating 029's section at a remapped station: nose and tail zones
shift rigidly with the wheels, only the cabin between the wheels (x3.28) and the tail behind the rear arch (x1.9) are
drawn out, so the wheel arches keep their shape. It replaces the image-to-3D shell (a long tan Hudson-like sedan
with flat facets on the bonnet: the wrong car for the sprite). Painted (neutral base, tinted to the identity paint).
Metres, +z nose, 1 block = 5 m."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "028_dementia_limousine"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (229, 179, 124)
LEN = 78 / 64 * 5.0              # 6.09 m
HALF_W = 26 / 64 * 5.0 / 2       # 1.016 m
LEN29 = 44 / 64 * 5.0            # the 029 section the body is drawn from
ZF29, ZR29 = 11 / 64 * 5.0 + 0.10, -10 / 64 * 5.0
ZF, ZR = ZF29 + 1.305, ZR29 - 0.86   # axles +2.27 / -1.64 (catalog +29 / -21 px)
# station map 028 -> 029: (z028, z029) knots; the wheels' zones move rigidly
Z28 = [-LEN / 2 + 0.06, -2.01, -1.26, 1.855, LEN / 2 - 0.06]
Z29 = [-LEN29 / 2 + 0.06, -1.15, -0.40, 0.55, LEN29 / 2 - 0.06]
R_TYRE, W_TYRE = 0.27, 0.17
X_WHEEL, X_REAR = 0.80, 0.76   # a full-width rear track (the limousine is not the Isetta)
R_ARCH = 0.33
BOT = 0.26


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2 - 0.06, -LEN / 2 + 0.06   # the body inside the bumpers (028 frame)
    zn9, zt9 = LEN29 / 2 - 0.06, -LEN29 / 2 + 0.06   # 029's, for its section functions

    belt0 = spline([(zt9, 0.66), (-1.30, 0.86), (-0.6, 0.92), (0.4, 0.92), (1.10, 0.86), (1.50, 0.74), (zn9, 0.62)])
    # the egg: the engine tail, the back light, the long roof dome, the wraparound windscreen, the door's round nose
    top0 = spline([(zt9, 0.72), (-1.50, 1.02), (-1.20, 1.34), (-0.80, 1.55), (-0.20, 1.64), (0.30, 1.62), (0.62, 1.52),
                   (0.88, 1.32), (1.12, 1.04), (1.36, 0.90), (1.58, 0.78), (zn9, 0.64)])
    def hw0(z):
        z = np.asarray(z, float)
        return np.interp(z, [zt9, -1.30, -0.60, 0.20, 0.90, 1.40, zn], [0.60, 0.84, 0.94, 0.99, 0.98, 0.88, 0.66])
    # the bubble tucks in over the belt all round the cabin
    tumble0 = spline([(zt9, 0.0), (-1.45, 0.0), (-1.10, 0.16), (0.70, 0.18), (1.10, 0.06), (zn9, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF29, ZR29):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    def ends(z, nose=0.60, tail=0.60):
        dn = np.clip((z - (zn9 - nose)) / nose, 0, 1)
        dt = np.clip(((zt9 + tail) - z) / tail, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dt ** 2, 0, 1))

    def body9(z, v, inset=0.0):
        z = np.asarray(z, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * (0.25 + 0.75 * f) - inset
        belt = belt0(z)
        fh = 0.35 + 0.65 * f
        top = belt + (top0(z) - belt) * fh - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08)
        bot = belt - (belt - bot) * fh + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z) * np.minimum(hw, 0.96) / 1.00
        # rounder flanks than the 1950s cab: the lower body curves under (pontoon)
        xl = hw * sepow(c, 0.60)
        yl = belt - (belt - bot) * sepow(s, 0.55)
        H = top - belt
        t = np.clip((v - 0.5) / 0.3, 0, 1) * 0.95
        xs = hw * (1 - t ** 3) ** (1 / 3) - tb * t
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** 3) ** (1 / 3) - tb * 0.95
        xr = X0 * (1 - w)
        yr = belt + H * (0.90 + 0.10 * (1 - (1 - w) ** 2.2) ** 0.45)
        xu = np.where(v < 0.8, xs, xr)
        yu = np.where(v < 0.8, ys, yr)
        return np.where(lo, xl, xu), np.where(lo, yl, yu), z

    def body(u, v, inset=0.0):
        """the 028 body: 029's section at the mapped station, placed at the 028 station"""
        u = np.asarray(u, float)
        x, y, _ = body9(np.interp(u, Z28, Z29), v, inset)
        return x, y, u

    SU, SV = 1.0, 2.6
    def win(poly, r):
        p = np.array(poly, float)
        c = p.mean(0)
        d = p - c
        shrink = p - d / np.linalg.norm(d * [SU, SV], axis=1, keepdims=True) * r / np.array([SU, SV])
        f = poly_sdf(shrink, SU, SV)
        return lambda u, v: f(u, v) - r
    # the bubble's glass: a wide wraparound windscreen in the door, bubble side windows, a small back light
    # four bays a side with pillars between (the sprite's dark marks down the flanks)
    bays = [win([(a, 0.58), (b, 0.58), (b + 0.04, 0.73), (a - 0.04, 0.73)], 0.07)
            for a, b in ((1.82, 0.98), (0.86, 0.02), (-0.10, -0.94), (-1.06, -1.72))]
    screen = win([(2.465, 0.62), (2.465, 1.05), (2.105, 1.05), (2.005, 0.79), (2.045, 0.62)], 0.06)
    backl = win([(-1.92, 0.83), (-1.92, 1.05), (-2.30, 1.05), (-2.30, 0.83)], 0.05)
    glass = sdf_union(*bays, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.016
    # the door's shut line round the nose, a thin rub strip round the waist
    def door(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.abs(u - 2.005) - 0.006, np.maximum(v - 0.80, 0.30 - v))
    def rub(u, v):
        u = np.asarray(u, float)
        clear = np.minimum(np.abs(u - ZF), np.abs(u - ZR)) - (R_ARCH + 0.02)
        return np.maximum(np.maximum(np.abs(np.asarray(v) - 0.47) * SV - 0.012, np.abs(u - 0.10) - 2.55), -clear)
    under = lambda u, v: np.maximum(np.asarray(v) - 0.24, body(u, v)[1] - (BOT + 0.08))
    car.surface(body, zt, zn, 0.0, 1.0, 120, 34, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("seal_door", door), ("chrome", rub), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, 2.465, 2.005, -1.92, -2.30] + [k for ab in ((1.82, 0.98), (0.86, 0.02), (-0.10, -0.94), (-1.06, -1.72)) for k in ab],
                vkeys=[0.58, 0.62, 0.73, 0.79, 0.83, 0.47])
    car.cap(body, zt, 0.0, 1.0, 20, "paint_body", regions=[("underbody", lambda u, v: np.asarray(v) - 0.14)])
    car.cap(body, zn, 0.0, 1.0, 20, "paint_body", regions=[("underbody", lambda u, v: np.asarray(v) - 0.14)])
    car.parts["seal"] = car.parts.get("seal") or Part()
    if "seal_door" in car.parts:
        p = car.parts.pop("seal_door")
        for k in range(len(p.p)):
            car.part("seal").add(p.p[k], p.n[k], p.t[k], p.f[k] - (p.f[k].min() if len(p.f[k]) else 0))
    # the cabin's dark inside (seen through the glass)
    car.surface(lambda u, v: body(u, v, inset=0.06), -2.30, 2.40, 0.30, 1.0, 40, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    # wheel well liners (the rear pair close together: the Isetta's narrow rear track)
    for zc, xw in ((ZF, X_WHEEL), (ZR, X_REAR)):
        for side in (1, -1):
            def liner(u, v, zc=zc, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, xw - 0.16, 0.84 * float(hw0(np.interp(np.array([zc]), Z28, Z29))[0]), 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    U = lambda z: (z - zt) / LEN
    lines_u = [(U(-2.41), 0.50, 0.98)]   # the engine lid's edge
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=28)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=280)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((12, 12, 12))
    car.materials["seat"] = tex_leather((120, 46, 38))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    # the occlusion is baked before the lamps and bumpers go on (their pods made dark smudges on the nose)
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    # lamps on short pods at the nose's sides
    uu, vv = np.meshgrid(np.linspace(zn - 0.8, zn, 160), np.linspace(0.3, 0.7, 120))
    bx, by, bz = body(uu.ravel(), vv.ravel())
    def front_z(x, y):
        k = np.argmin(np.abs(bx - x) + np.abs(by - y))
        return float(bz[k])
    for side in (1, -1):
        lz = front_z(0.74, 0.70)
        c = np.array([side * 0.74, 0.70, lz + 0.02])
        ax = (side * 0.25, 0.0, 1.0)
        car.revolve([(0.10, -0.10), (0.098, -0.01), (0.090, 0.012)], c, ax, 22, default="paint_wheel", uv_mode="disc")
        car.revolve([(0.090, 0.008), (0.088, 0.020), (0.078, 0.030)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.078, 0.026), (0.05, 0.036), (0.0, 0.040)], c, ax, 22, default="lamp_head", uv_mode="disc")
        az = front_z(0.62, 0.50)
        car.revolve([(0.032, 0.0), (0.032, 0.016), (0.0, 0.022)], (side * 0.62, 0.50, az + 0.01), (side * 0.3, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        # tail lamps: small round lenses on the tail's shoulders
        tx, ty, tz = body(np.array([zt + 0.22]), np.array([0.53]))
        car.revolve([(0.045, 0.0), (0.042, 0.016), (0.0, 0.022)], (side * (float(tx[0]) - 0.02), 0.78, float(tz[0]) - 0.02), (side * 0.4, 0, -1), 14,
                    default="lamp_tail", uv_mode="disc")
    # bumpers: thin chrome bars at both ends
    def bar(zc, sign, half, y):
        def path(u):
            t = (u - 0.5) * 2
            return np.stack([t * half, np.full_like(t, y), zc - sign * 0.20 * t ** 2], 1)
        return path
    car.sweep(bar(zn + 0.02, 1, 0.66, 0.38), 0.030, 20, 8, "chrome")
    car.sweep(bar(zt - 0.02, -1, 0.58, 0.42), 0.030, 20, 8, "chrome")
    # interior: one bench across the back of the cabin, the steering column on the door, a parcel shelf
    car.box("seat", (-0.74, 0.50, 1.05), (0.74, 0.66, 1.45))      # the driver's bench behind the door
    car.box("seat", (-0.74, 0.64, 0.93), (0.74, 1.12, 1.05))
    car.box("interior_dark", (-0.80, 0.66, 0.70), (0.80, 1.06, 0.84))   # the division
    car.box("seat", (-0.74, 0.50, -1.30), (0.74, 0.66, -0.70))    # the rear bench, facing forward
    car.box("seat", (-0.74, 0.64, -1.44), (0.74, 1.18, -1.30))
    car.box("seat", (-0.70, 0.50, -0.30), (0.70, 0.62, 0.10))     # the occasional seats
    car.box("interior_dark", (-0.80, 0.30, -2.00), (0.80, 0.34, 2.10))
    car.revolve([(0.17, -0.012), (0.17, 0.012)], (-0.18, 0.98, 1.72), (0, 0.6, -1), 18, default="interior_dark", uv_mode="disc")
    car.sweep(lambda u: np.stack([-0.18 + 0 * u, 0.98 - 0.30 * u, 1.72 + 0.30 * u], 1), 0.016, 6, 8, "interior_dark")

    style = dict(rim_r=0.60, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.16)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_REAR), ("wheel_rr", ZR, X_REAR)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va24/p028.png", LEN)
