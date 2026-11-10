#!/usr/bin/env python3
"""069 U-Jerk Truck (VEHICLE-ART-15): the catalog's 1930s utility truck (Ford Model AA), read from the GTA2 sprite nose
down (assets-src/cars/sprites_x4/069_u_jerk_truck_default.png, body 32 x 56 px): a closed cab with a rounded roof (the
sprite's big tan roof), a narrow bonnet with side louvres to an upright chrome radiator shell, black wings sweeping into
running boards with the headlamps on stalks between the wings and the radiator (the sprite's chrome lamps at the nose
corners), and behind the cab a tall open-top slatted box with cross bows over it (the sprite's dark bed with its
ribs), its rails painted. Painted body (neutral 235, tinted by the identity record); wings, running boards, box slats
and bows are their own untinted materials. It replaces the image-to-3D shell (blotched box sides, a crumpled roof, an
empty window hole for a cab, balloon tyres).
Metres, +z nose, 1 block = 5 m (catalog body 32 x 56 px = 2.5 x 4.38 m; axles +15 / -13 px)."""
import math
import os
import sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "069_u_jerk_truck"
SPRITE = (162, 133, 102)
PAINT = (235.0, 235.0, 235.0)
LEN = 56 / 64 * 5.0               # 4.375 m
HALF_W = 32 / 64 * 5.0 / 2        # 1.25 m
ZF, ZR = 15 / 64 * 5.0, -13 / 64 * 5.0     # +1.17 / -1.02
R_TYRE, W_TYRE = 0.40, 0.17
R_REAR, W_REAR = 0.42, 0.24
X_WHEEL, X_REAR = 0.84, 0.88
R_ARCH = 0.48
BOT = 0.78                        # cab sill
ZC = -0.10                        # cab back wall
ZW = 0.90                         # windscreen base / cowl
ZRAD = 1.98                       # radiator shell front
DECK = 1.04                       # box floor
BOX_TOP = 1.92
BOX_HW = 1.18
ZB0, ZB1 = -2.16, -0.18           # box tail / front


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn = ZRAD

    # cab + bonnet: one loft (058's), the cab 0.92 m a side narrowing at the cowl to a 0.44 m bonnet
    belt0 = spline([(ZC, 1.36), (0.6, 1.36), (ZW, 1.34), (1.10, 1.30), (1.6, 1.29), (zn, 1.28)])
    top0 = spline([(ZC, 1.98), (0.05, 2.05), (0.50, 2.07), (0.70, 2.04), (ZW - 0.05, 1.92), (ZW + 0.06, 1.48), (1.20, 1.47),
                   (1.70, 1.46), (zn, 1.45)])
    def hw0(z):
        z = np.asarray(z, float)
        return np.interp(z, [ZC, ZW - 0.02, ZW + 0.14, zn], [0.92, 0.92, 0.45, 0.42])
    bot0 = lambda z: np.interp(np.asarray(z, float), [ZC, ZW, ZW + 0.12, zn], [BOT, BOT, 0.92, 0.92])
    tumble0 = spline([(ZC, 0.05), (0.6, 0.06), (ZW, 0.0), (zn, 0.0)])

    def ends(z, nose=0.08):
        dn = np.clip((z - (zn - nose)) / nose, 0, 1)
        dc = np.clip(((ZC + 0.05) - z) / 0.05, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dc ** 2, 0, 1))

    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * (0.92 + 0.08 * f) - inset
        belt = belt0(z)
        fh = 0.85 + 0.15 * f
        top = belt + (top0(z) - belt) * fh - inset
        bot = bot0(z)
        bot = belt - (belt - bot) * fh + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z)
        xl = hw * sepow(c, 0.25)
        yl = belt - (belt - bot) * sepow(s, 0.40)
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
    side = win([(0.80, 0.56), (0.05, 0.56), (0.05, 0.78), (0.74, 0.78)], 0.04)
    screen = win([(ZW + 0.03, 0.81), (ZW + 0.03, 0.99), (ZW - 0.09, 0.99), (ZW - 0.09, 0.81)], 0.02)
    glass = sdf_union(side, screen)
    seal = lambda u, v: glass(u, v) - 0.016
    # bonnet side louvres: a band of short vertical slots on each bonnet side
    def louvre(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        k = np.abs(((u - 1.20) / 0.07) % 1.0 - 0.5) * 0.07 - 0.012
        return np.maximum(np.maximum(k, np.abs(v - 0.40) * SV - 0.10), np.maximum(1.18 - u, u - 1.80))
    car.surface(body, ZC, zn, 0.0, 1.0, 70, 30, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("louvre", louvre)],
                default="paint_body", uvfn=lambda u, v: ((u - ZC) / (zn - ZC), v),
                ukeys=[ZW - 0.09, ZW + 0.03, 0.80, 0.74, 0.05, 1.18, 1.80] + list(1.20 + 0.07 * np.arange(9) + 0.035),
                vkeys=[0.56, 0.78, 0.81, 0.99, 0.40 - 0.10 / SV, 0.40 + 0.10 / SV])
    car.cap(body, ZC, 0.0, 1.0, 24, "paint_body",
            regions=[("glass", lambda r, v: np.maximum(np.abs(np.asarray(v) - 0.86) * 6 - 0.5, np.asarray(r) - 0.70))])
    car.cap(body, zn, 0.0, 1.0, 24, "paint_body")
    car.surface(lambda u, v: body(u, v, inset=0.05), ZC + 0.05, ZW - 0.04, 0.45, 1.0, 16, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    # cab floor under the seat (the sill opening must not show the road)
    car.box("underbody", (-0.88, BOT - 0.02, ZC), (0.88, BOT + 0.02, ZW))

    # radiator: an upright chrome shell round a dark honeycomb, a cap on top
    car.box("grille", (-0.36, 0.86, zn - 0.02), (0.36, 1.42, zn + 0.03))
    def shell(u):
        t = (u - 0.5) * 2
        x = 0.38 * np.clip(t * 1.6, -1, 1)
        y = 1.44 - 0.60 * np.clip((np.abs(t) - 1 / 1.6) * 1.6 / (1 - 1 / 1.6) / 1.6, 0, 1)
        return np.stack([x, y, zn + 0.035 + 0 * u], 1)
    car.sweep(shell, 0.03, 48, 8, "chrome", caps=False)
    car.sweep(lambda u: np.stack([(u - 0.5) * 0.76, 0.86 + 0 * u, zn + 0.035 + 0 * u], 1), 0.03, 10, 8, "chrome")
    car.revolve([(0.04, 0.0), (0.04, 0.05), (0.02, 0.07), (0.0, 0.075)], (0, 1.46, zn - 0.02), (0, 1, 0), 12, default="chrome", uv_mode="disc")

    # wings (039's fender: long fronts sweeping back into the running boards), short rear wings under the box
    def fender(zc, z0, z1, x0, a_max, top_y, round_front, round_back, sweep_back, sweep_front, r_t, foot):
        def fn(u, v):
            z = np.asarray(u, float); phi = np.asarray(v, float)
            tb = np.clip((z - z0) / round_back, 0, 1) if round_back > 0 else np.ones_like(z)
            tf = np.clip((z1 - z) / round_front, 0, 1) if round_front > 0 else np.ones_like(z)
            e = np.sqrt(1 - (1 - tb) ** 2) * np.sqrt(1 - (1 - tf) ** 2)
            sb = smoothstep(z0 + sweep_back, z0, z) if sweep_back > 0 else np.zeros_like(z)
            sf = smoothstep(z1 - sweep_front, z1, z) if sweep_front > 0 else np.zeros_like(z)
            sw = np.maximum(sb, sf)
            dz = z - zc
            yc = np.where(np.abs(dz) < R_ARCH, r_t + np.sqrt(np.clip(R_ARCH ** 2 - dz ** 2, 0, None)), r_t)
            yc = np.maximum(yc, foot)
            yc = yc * (1 - sw) + foot * sw
            crown = top_y - 0.10 * np.clip(np.abs(dz) / 0.9, 0, 1) ** 2
            ytop = yc + (crown - yc) * e
            ytop = ytop * (1 - sw) + (foot + 0.05) * sw
            a = a_max * (0.80 + 0.20 * np.clip(1 - (dz / 0.9) ** 2, 0, 1)) * np.maximum(e, 0.0)
            b = np.maximum(ytop - yc, 1e-4)
            x = x0 + a * sepow(np.cos(phi), 0.8)
            y = yc + b * sepow(np.sin(phi), 0.9)
            return x, y, z
        return fn
    RB = 0.56                     # running board height
    ff = fender(ZF, -0.05, zn + 0.06, X_WHEEL - 0.02, 0.17, 1.02, 0.25, 0.0, 0.80, 0.0, R_TYRE, RB)
    fr = fender(ZR, ZR - 0.62, -0.05, X_REAR - 0.02, 0.19, 0.96, 0.22, 0.0, 0.0, 0.40, R_REAR, RB)
    for fn, z0, z1 in ((ff, -0.05, zn + 0.06), (fr, ZR - 0.62, -0.05)):
        car.surface(fn, z0, z1, 0.0, math.pi, 34, 12, mirror=True, default="wing",
                    uvfn=lambda u, v, z0=z0, z1=z1: ((u - z0) / (z1 - z0), v / math.pi))
        car.surface(fn, z0, z1, 0.0, math.pi, 34, 4, mirror=True, default="underbody", flip=True,
                    uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for side in (1, -1):
        car.box("running_board_rubber", (min(side * 0.84, side * 1.04), RB + 0.03, -0.12), (max(side * 0.84, side * 1.04), RB + 0.07, 0.10))
        # splash apron between the running board and the cab / bonnet
        car.box("wing", (min(side * 0.60, side * 0.86), RB + 0.04, -0.10), (max(side * 0.60, side * 0.86), BOT + 0.01, ZW))
        car.box("wing", (min(side * 0.40, side * 0.62), 0.80, ZW), (max(side * 0.40, side * 0.62), 0.93, zn - 0.05))
        # headlamps on stalks between the radiator and the wings, a tie bar between them
        c = np.array([side * 0.62, 1.30, zn - 0.06])
        car.revolve([(0.10, -0.13), (0.12, -0.05), (0.125, 0.012), (0.110, 0.030)], c, (0, 0, 1), 22, default="chrome", uv_mode="disc")
        car.revolve([(0.110, 0.026), (0.07, 0.042), (0.0, 0.048)], c, (0, 0, 1), 22, default="lamp_head", uv_mode="disc")
        car.sweep(lambda u, side=side: np.stack([side * (0.62 - 0.10 * u) + 0 * u, 1.17 - 0.17 * u, zn - 0.12 + 0 * u], 1), 0.022, 4, 6, "chrome")
        # cowl lamp, door handle, mirror
        car.revolve([(0.035, 0.0), (0.035, 0.02), (0.0, 0.03)], (side * 0.56, 1.42, ZW + 0.06), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        car.box("chrome", (side * 0.925 - 0.012, 1.30, 0.25), (side * 0.925 + 0.012, 1.33, 0.38))
        car.sweep(lambda u, side=side: np.stack([side * (0.92 + 0.20 * u), 1.70 + 0 * u, ZW - 0.10 + 0 * u], 1), 0.014, 4, 6, "chrome")
        car.box("chrome", (side * 1.12 - 0.04, 1.60, ZW - 0.12), (side * 1.12 + 0.04, 1.80, ZW - 0.08))
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.24, 1.30 + 0 * u, zn - 0.10 + 0 * u], 1), 0.018, 10, 6, "chrome")
    # bumper: a double chrome blade on brackets
    for yb in (0.62, 0.73):
        car.sweep(lambda u, yb=yb: np.stack([(u - 0.5) * 1.84, yb + 0 * u, zn + 0.16 - 0.03 * ((u - 0.5) * 2) ** 2], 1), 0.042, 16, 8,
                  "chrome", squash=(0.40, 1.0), caps=False)
        for side in (1, -1):         # rounded blade ends
            car.revolve([(0.0, -0.017), (0.042, -0.017), (0.042, 0.017), (0.0, 0.017)], (side * 0.92, yb, zn + 0.13), (0, 0, 1), 12,
                        default="chrome", uv_mode="disc")
    for side in (1, -1):
        car.box("frame", (side * 0.50 - 0.04, 0.60, zn - 0.10), (side * 0.50 + 0.04, 0.75, zn + 0.14))

    # chassis
    for side in (1, -1):
        car.box("frame", (side * 0.50 - 0.06, 0.62, ZB0 + 0.05), (side * 0.50 + 0.06, 0.80, zn - 0.05))
    # the box: a floor, four slats a side between painted stakes and rails, a front board, a tailgate, cross bows
    car.box("wood", (-BOX_HW, DECK - 0.10, ZB0), (BOX_HW, DECK, ZB1))
    car.box("paint_rail", (-BOX_HW - 0.02, DECK - 0.16, ZB0 - 0.02), (BOX_HW + 0.02, DECK - 0.04, ZB1 + 0.02))
    n_slat = 4
    sh = (BOX_TOP - DECK - 0.10) / n_slat
    for side in (1, -1):
        x0, x1 = sorted((side * (BOX_HW - 0.05), side * BOX_HW))
        for k in range(n_slat):
            y0 = DECK + 0.04 + k * sh
            car.box("wood", (x0, y0, ZB0 + 0.04), (x1, y0 + sh * 0.72, ZB1 - 0.04))
        for zs in np.linspace(ZB0 + 0.04, ZB1 - 0.04, 5):
            xs0, xs1 = sorted((side * (BOX_HW - 0.07), side * (BOX_HW + 0.02)))
            car.box("paint_rail", (xs0, DECK - 0.04, zs - 0.045), (xs1, BOX_TOP, zs + 0.045))
        car.box("paint_rail", (min(side * (BOX_HW - 0.07), side * (BOX_HW + 0.03)), BOX_TOP - 0.06, ZB0),
                (max(side * (BOX_HW - 0.07), side * (BOX_HW + 0.03)), BOX_TOP + 0.02, ZB1))
    for zb, hi in ((ZB1, BOX_TOP), (ZB0, BOX_TOP - 0.25)):
        for k in range(n_slat if zb == ZB1 else n_slat - 1):
            y0 = DECK + 0.04 + k * sh
            car.box("wood", (-BOX_HW + 0.05, y0, zb - 0.025), (BOX_HW - 0.05, y0 + sh * 0.72, zb + 0.025))
        car.box("paint_rail", (-BOX_HW, hi - 0.06, zb - 0.04), (BOX_HW, hi + 0.02, zb + 0.04))
    # cross bows over the open top (the sprite's ribs), arched slightly
    for zb in np.linspace(ZB0 + 0.20, ZB1 - 0.20, 5):
        car.sweep(lambda u, zb=zb: np.stack([(u - 0.5) * 2 * (BOX_HW - 0.04), BOX_TOP + 0.04 + 0.10 * np.sin(math.pi * u), zb + 0 * u], 1),
                  0.025, 16, 6, "paint_rail", squash=(1.0, 0.7))
    # tail lamps and plate under the tailgate
    for side in (1, -1):
        car.revolve([(0.05, -0.02), (0.05, 0.02), (0.0, 0.03)], (side * 0.95, 0.88, ZB0 - 0.03), (0, 0, -1), 12, default="lamp_tail", uv_mode="disc")
    car.box("plate", (-0.17, 0.70, ZB0 - 0.03), (0.17, 0.83, ZB0 - 0.02))
    car.box("frame", (-0.20, 0.68, ZB0 - 0.02), (0.20, 0.85, ZB0 + 0.04))

    # interior: a bench, the dash, a big wheel on an upright column
    car.box("seat", (-0.84, 1.06, -0.05), (0.84, 1.22, 0.42))
    car.box("seat", (-0.84, 1.20, -0.10), (0.84, 1.80, 0.00))
    car.box("interior_dark", (-0.88, 1.36, ZW - 0.12), (0.88, 1.52, ZW - 0.02))
    car.revolve([(0.21, -0.012), (0.21, 0.012)], (-0.40, 1.50, 0.62), (0, 0.8, -1), 18, default="interior_dark", uv_mode="disc")
    car.sweep(lambda u: np.stack([-0.40 + 0 * u, 1.50 - 0.45 * u, 0.62 + 0.36 * u], 1), 0.02, 4, 6, "interior_dark")

    st = dict(rim_r=0.55, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.16)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, st)
    for nm, zc, xw in (("wheel_rl", ZR, -X_REAR), ("wheel_rr", ZR, X_REAR)):
        add_wheel(car, nm, (xw, R_REAR, zc), R_REAR, W_REAR, 1 if xw > 0 else -1, st)

    U = lambda z: (z - ZC) / (zn - ZC)
    lines_u = [(U(0.84), 0.20, 0.56), (U(0.02), 0.20, 0.56), (U(ZW + 0.10), 0.50, 1.0)]
    lines_v = [(0.93, U(ZW + 0.12), U(zn - 0.04))]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, lines_v=lines_v, ao_v=[(0.18, 0.36, 0.30)], seed=69)
    car.materials["paint_rail"] = tex_paint(PAINT, 128, seed=70)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=71)
    car.materials["wing"] = tex_paint((26, 25, 24), 128, seed=72)
    car.materials["louvre"] = tex_flat((18, 17, 16))
    car.materials["wood"] = tex_wood()
    car.materials["glass"] = tex_glass(256, tint=(34, 42, 50), alpha=170)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_honeycomb()
    car.materials["underbody"] = tex_underbody()
    car.materials["frame"] = tex_flat((28, 28, 30))
    car.materials["running_board_rubber"] = tex_flat((34, 33, 32))
    car.materials["plate"] = tex_flat((210, 200, 170))
    car.materials["interior_dark"] = tex_flat((16, 15, 14))
    car.materials["seat"] = tex_leather((58, 46, 38))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread(grooves=5)
    car.materials["tyre_side"] = tex_tyre_side()
    bake_ao(car, body, ZC, zn, 0.0, 1.0, "paint_body")
    return car


def tex_wood(size=128):
    """weathered dark plank: grain along the plank, a darker edge"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    n = noise(size, size, 3, 91) * 0.5 + noise(size, size, 16, 92) * 0.5
    grain = 0.5 + 0.5 * np.sin(yy * 60 + n * 6)
    v = 58 + 18 * grain + 10 * n
    v = np.where((xx < 0.04) | (xx > 0.96), v * 0.6, v)
    return Image.fromarray(np.dstack([v * 1.00, v * 0.80, v * 0.62]).clip(0, 255).astype(np.uint8))


def tex_honeycomb(size=128):
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    fx = (xx * 18) % 1.0; fy = (yy * 14 + 0.5 * (np.floor(xx * 18) % 2)) % 1.0
    web = (np.abs(fx - 0.5) > 0.36) | (np.abs(fy - 0.5) > 0.36)
    v = np.where(web, 120, 22)
    return Image.fromarray(np.dstack([v, v, v * 1.03]).clip(0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va15/p069.png", LEN)
