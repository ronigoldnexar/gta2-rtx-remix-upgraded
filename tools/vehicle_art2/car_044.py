#!/usr/bin/env python3
"""044 Arachnid (VEHICLE-ART-18): the catalog's small Italian spider (Alfa Romeo Duetto idiom) read from the GTA2 sprite
(nose down in assets-src/cars/sprites_x4/044_arachnid_default.png): a long bonnet with two creases running back from a
central shield grille, round lamps under clear covers in the wing tips, a big oval open cockpit (the sprite's dark oval
from the windscreen at 25 px from the nose to 48 px) with two black bucket seats, the folded black hood behind them, a
long tapering boat tail with small lamps; slim split bumpers. Painted (neutral 235, tinted to the identity record).
It replaces the image-to-3D shell whose seat backs were single thin quads standing as flat black slabs (pmw1) and
whose bonnet drew a black void from the seat (qav10). The cockpit is part of the body surface: the top sinks into a
tub inside the oval, so every wall has thickness and an outward normal (no free-standing planes).
Metres, +z nose, 1 block = 5 m (catalog body 0.5 x 0.969 blocks: 2.5 x 4.84 m; axles +20 / -19 px of 62)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "044_arachnid"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (126, 85, 75)
LEN = 0.969 * 5.0               # 4.84 m
HALF_W = 0.5 * 5.0 / 2           # 1.25 m over the wings
ZF, ZR = 1.50, -1.45             # axles (CARI: 20 px forward, 19 back of 62)
R_TYRE, W_TYRE = 0.32, 0.21
X_WHEEL = 0.92
R_ARCH = 0.38
BOT = 0.30
SHEAR = 0.0
ZC, HZ, HV = -0.42, 0.92, 0.17      # the cockpit oval: centre and half length along z, half width in v (from v = 1)
ZS = 0.56                        # the windscreen base
FLOOR = 0.40


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2 - 0.08, -LEN / 2 + 0.08

    belt0 = spline([(zt, 0.64), (-1.9, 0.72), (-1.2, 0.76), (0.0, 0.77), (1.2, 0.76), (1.9, 0.70), (zn, 0.56)])
    # no roof: the deck line, highest at the cowl and the rear wings, falling to the boat tail and the nose
    top0 = spline([(zt, 0.70), (-2.0, 0.80), (-1.45, 0.86), (-0.40, 0.87), (ZS, 0.88), (1.20, 0.85), (1.90, 0.77), (zn, 0.62)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.07 * np.exp(-((z - ZF) / 0.60) ** 2) + 0.09 * np.exp(-((z - ZR) / 0.60) ** 2)
        base = np.interp(z, [zt, -2.0, -1.4, 1.1, 1.8, zn], [0.70, 0.96, 1.08, 1.08, 1.00, 0.72])
        return base + swell

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    NOSE, TAILL = 0.42, 0.40
    def plan(z):
        fn = np.clip((zn - z) / NOSE, 0, 1)
        fn = np.sqrt(np.clip(1 - (1 - fn) ** 2, 0, 1))
        ft = np.clip((z - zt) / TAILL, 0, 1)
        ft = np.sqrt(np.clip(1 - (1 - ft) ** 2, 0, 1))
        return fn, ft

    def oval(z, v):
        """the cockpit opening in (z, v): < 1 inside"""
        return ((np.asarray(z, float) - ZC) / HZ) ** 2 + ((1.0 - np.asarray(v, float)) / HV) ** 2

    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        fn, ft = plan(z)
        hw = hw0(z) * (0.55 + 0.45 * fn) * (0.45 + 0.55 * ft) - inset
        belt = belt0(z)
        fh = (0.75 + 0.25 * ft) * (0.55 + 0.45 * fn)
        top = belt + (top0(z) - belt) * fh - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08)
        bot = belt - (belt - bot) * (0.55 + 0.45 * fn) + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        xl = hw * sepow(c, 0.40)
        yl = belt - (belt - bot) * sepow(s, 0.55)
        H = top - belt
        t = np.clip((v - 0.5) / 0.3, 0, 1) * 0.95
        xs = hw * (1 - t ** 4) ** (1 / 4)
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** 4) ** (1 / 4)
        xr = X0 * (1 - w)
        yr = belt + H * (0.95 + 0.05 * (1 - (1 - w) ** 2.2) ** 0.45)
        xu = np.where(v < 0.8, xs, xr)
        yu = np.where(v < 0.8, ys, yr)
        # wing crowns either side of the bonnet and over the rear wheels; two bonnet creases (the sprite's)
        crown = 0.06 * smoothstep(0.50, 1.30, z) * (1 - smoothstep(zn - 0.30, zn, z) * 0.5) + 0.05 * np.exp(-((z - ZR) / 0.55) ** 2)
        creases = 0.012 * np.exp(-((v - 0.93) / 0.012) ** 2) * smoothstep(ZS + 0.1, ZS + 0.4, z)
        yu = yu + (crown * np.exp(-((v - 0.66) / 0.08) ** 2) + creases) * (v > 0.5)
        # the cockpit: inside the oval the deck sinks into a tub (a steep inner wall, then the floor), so the opening is
        # real geometry with thickness, not a painted patch
        e = oval(z, v)
        d = smoothstep(1.0, 0.78, e) * (v > 0.5)
        yu = yu - d * (yu - FLOOR)
        x = np.where(lo, xl, xu); y = np.where(lo, yl, yu)
        return x, y, z

    def cockpit(u, v):
        return oval(u, v) - 0.97
    rim = lambda u, v: np.abs(oval(u, v) - 1.06) - 0.09
    # chrome: a thin spear along the flank (the side cove's edge), the shield grille's surround is geometry
    def spear(u, v):
        u = np.asarray(u, float)
        clear = np.minimum(np.abs(u - ZF), np.abs(u - ZR)) - (R_ARCH + 0.03)
        return np.maximum(np.maximum(np.abs(np.asarray(v) - 0.47) * 2.6 - 0.010, np.maximum(u - (ZF - R_ARCH - 0.05), -1.0 - u)), -clear)
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 84, 40, mirror=True,
                regions=[("interior_dark", cockpit), ("trim_dark", rim), ("chrome", spear), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / (zn - zt), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, ZC - HZ, ZC + HZ],
                vkeys=[0.47, 0.80, 1.0 - HV, 1.0 - HV * 0.9, 1.0 - HV * 0.8, 1.0 - HV * 0.6])
    car.cap(body, zn, 0.0, 1.0, 24, "paint_body", nr=4, regions=[("underbody", lambda r, v: np.asarray(v) - 0.12)])
    car.cap(body, zt, 0.0, 1.0, 24, "paint_body", nr=4, regions=[("underbody", lambda r, v: np.asarray(v) - 0.12)])
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, side=side, zc=zc):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.62, 1.12, 16, 2, default="underbody", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # the front: the shield grille on the nose (a chrome shield over black bars), two slim side grilles, round lamps
    # under clear covers in the wing tips, amber lamps under them
    yg = 0.46
    def shield(rr, a):
        rr = np.asarray(rr, float); a = np.asarray(a, float)
        sx = 0.12 * np.sin(a); sy = np.where(np.cos(a) > 0, 0.13 * np.cos(a), 0.17 * np.cos(a))
        return rr * sx, yg - rr * sy, zn + 0.02 + 0.02 * (1 - rr ** 2)
    car.surface(shield, 0.0, 1.0, 0.0, 2 * math.pi, 5, 28, default="grille",
                uvfn=lambda rr, a: (0.5 + 0.5 * rr * np.sin(a), 0.5 - 0.5 * rr * np.cos(a)))
    car.sweep(lambda u: np.stack([0.12 * np.sin(u * 2 * math.pi), yg - np.where(np.cos(u * 2 * math.pi) > 0, 0.13, 0.17) * np.cos(u * 2 * math.pi),
                                  zn + 0.022 + 0 * u], 1), 0.014, 40, 8, "chrome", caps=False)
    for side in (1, -1):
        car.box("grille", (side * 0.17 if side > 0 else -0.52, 0.38, zn - 0.08), (0.52 if side > 0 else -0.17, 0.44, zn - 0.025))
        c = np.array([side * 0.62, 0.59, zn - 0.075])
        ax = (side * 0.30, 0.10, 1.0)
        car.revolve([(0.090, -0.07), (0.094, 0.008), (0.084, 0.022)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.084, 0.018), (0.056, 0.030), (0.0, 0.034)], c, ax, 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.035, 0.0), (0.035, 0.015), (0.0, 0.022)], (side * 0.62, 0.44, zn - 0.07), (side * 0.3, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        # tail lamps: small lenses at the tail's corners
        car.revolve([(0.050, -0.03), (0.052, 0.006), (0.046, 0.016)], (side * 0.21, 0.60, zt - 0.004), (side * 0.15, 0.05, -1), 14,
                    default="chrome", uv_mode="disc")
        car.revolve([(0.046, 0.012), (0.0, 0.024)], (side * 0.21, 0.60, zt - 0.004), (side * 0.15, 0.05, -1), 14,
                    default="lamp_tail", uv_mode="disc")
    # bumpers: slim split blades at the nose (either side of the shield), one blade round the tail
    for side in (1, -1):
        car.sweep(lambda u, side=side: np.stack([side * (0.18 + 0.58 * u), 0.33 + 0 * u, zn + 0.02 - 0.30 * u ** 2], 1),
                  0.035, 16, 10, "chrome", squash=(0.45, 1.0))
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.30, 0.40 + 0 * u, zt - 0.02 + 0.30 * ((u - 0.5) * 2) ** 2], 1), 0.035, 24, 10,
              "chrome", squash=(0.45, 1.0))

    # the windscreen: raked glass in a chrome frame on the cowl
    ZT, YB, YT = ZS - 0.26, 0.86, 1.14
    WX = 0.66
    def screen(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        x = (u - 0.5) * 2 * WX * (1 - 0.06 * v)
        bend = 0.08 * ((u - 0.5) * 2) ** 2
        return x, YB + (YT - YB) * v, ZS + (ZT - ZS) * v - bend
    car.surface(screen, 0.0, 1.0, 0.0, 1.0, 12, 3, default="glass", uvfn=lambda u, v: (u, v))
    for vv in (0.0, 1.0):
        car.sweep(lambda u, vv=vv: np.stack(screen(u, np.full_like(u, vv)), 1), 0.016, 16, 8, "chrome")
    for uu in (0.0, 1.0):
        car.sweep(lambda v, uu=uu: np.stack(screen(np.full_like(v, uu), v), 1), 0.016, 6, 8, "chrome")
    # the folded hood: a black bundle on the deck behind the seats, at the oval's back edge
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.30, 0.80 + 0 * u, ZC - HZ + 0.12 + 0.05 * ((u - 0.5) * 2) ** 2], 1), 0.11, 18, 12, "hood",
              squash=(1.0, 0.60))

    # interior: two bucket seats with real thickness (cushion, back, side bolsters), a dash with two dials, the wheel
    for xs in (-0.36, 0.36):
        car.box("seat", (xs - 0.23, FLOOR, -0.70), (xs + 0.23, FLOOR + 0.12, -0.22))
        car.box("seat", (xs - 0.23, FLOOR + 0.08, -0.86), (xs + 0.23, 0.98, -0.72))
        for sb in (-1, 1):
            car.box("seat", (xs + sb * 0.23 - 0.04, FLOOR + 0.10, -0.84), (xs + sb * 0.23 + 0.04, 0.90, -0.66))
    car.box("interior_dark", (-0.72, 0.62, ZS - 0.22), (0.72, 0.84, ZS - 0.04))
    for xd in (-0.48, -0.30):
        car.revolve([(0.055, 0.0), (0.055, 0.01), (0.0, 0.012)], (xd, 0.76, ZS - 0.225), (0, 0.2, -1), 14, default="chrome", uv_mode="disc")
    wc = np.array([-0.36, 0.80, ZS - 0.42])
    car.sweep(lambda u: wc[None, :] + np.stack([0.19 * np.cos(2 * math.pi * u), 0.19 * np.sin(2 * math.pi * u) * 0.9,
                                                0.19 * np.sin(2 * math.pi * u) * 0.42], 1), 0.014, 32, 8, "trim_dark", caps=False)
    car.revolve([(0.05, -0.01), (0.05, 0.01), (0.0, 0.02)], wc, (0, 0.42, -1), 12, default="chrome", uv_mode="disc")
    car.sweep(lambda u: np.stack([wc[0] + 0 * u, wc[1] - 0.20 * u, wc[2] + 0.35 * u], 1), 0.02, 6, 8, "trim_dark")
    # door shut lines are in the paint; door handles, a mirror on the driver's wing
    for side in (1, -1):
        car.box("chrome", (side * 1.04 - 0.012, 0.70, -0.05), (side * 1.04 + 0.012, 0.73, 0.07))
    car.sweep(lambda u: np.stack([-0.78 - 0.08 * u, 0.86 + 0.06 * u, 1.05 + 0 * u], 1), 0.014, 4, 6, "chrome")
    car.revolve([(0.050, 0.0), (0.050, 0.02), (0.0, 0.03)], (-0.88, 0.94, 1.05), (0, 0, -1), 14, default="chrome", uv_mode="disc")

    style = dict(rim_r=0.70, rim_mat="chrome", cap_mat="chrome", whitewall=0.0, cap_dome=0.22)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / (zn - zt)
    lines_u = [(U(ZS - 0.05), 0.30, 0.79), (U(-0.80), 0.30, 0.79)]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=44)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=150)
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_vgrille()
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((22, 21, 20))
    car.materials["trim_dark"] = tex_flat((14, 14, 15))
    car.materials["seat"] = tex_leather((34, 31, 30))
    car.materials["hood"] = tex_leather((26, 25, 25), seams=10)
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    return car


def tex_vgrille(size=128, bars=14):
    """an egg-crate of chrome bars on black, a chrome surround (the cap's uv: s across, t up)"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    bar = (np.abs(((xx * bars) % 1.0) - 0.5) < 0.16) | (np.abs(((yy * 5) % 1.0) - 0.5) < 0.12)
    v = np.where(bar, 170 + 30 * (1 - yy), 20)
    edge = (yy < 0.05) | (yy > 0.95)
    v = np.where(edge, 215, v)
    return Image.fromarray(np.dstack([v, v, v * 1.03]).clip(0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va18/p044.png", LEN)
