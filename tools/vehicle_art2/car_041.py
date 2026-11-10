#!/usr/bin/env python3
"""041 Pickup (VEHICLE-ART-21, qav50): the catalog's late-1940s / early-1950s American half-ton pickup (Ford F-1 /
Chevrolet Advance-Design idiom) read from the GTA2 sprite nose down: a long bonnet over the front wheels between
pontoon wings that carry the headlamps, a wide bar grille, a rounded two-seat cab (the sprite's light roof 18-33 px
from the nose) with a near-upright split-free windscreen and a small rear light, and behind it a stepside bed: the
sprite's dark plank floor with light stake pockets along both painted sides, a tailgate, rounded rear fenders outside
the bed sides and running boards between the wings. Painted (neutral base, tinted to the identity record's paint).
Built on VEHICLE-ART-9's 058 Tow Truck cab recipe. It replaces the image-to-3D shell (torn black pixel-stepped
patches baked on its bonnet, wing and door, a dark flat cab glass, a dented grille).
Metres, +z nose, 1 block = 5 m (catalog body 34 x 64 px = 0.531 x 1.0 blocks: 2.66 x 5.0 m; axles +18 / -19 px)."""
import math
import os
import sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "041_pickup"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (122, 94, 76)
LEN = 1.0 * 5.0                  # 5.0 m
HALF_W = 0.531 * 5.0 / 2         # 1.33 m
ZF, ZR = 1.41, -1.48             # axles (CARI: 18 px forward, 19 px back)
R_TYRE, W_TYRE = 0.38, 0.24
X_WHEEL, X_REAR = 0.96, 0.98
R_ARCH = 0.47
BOT = 0.50
ZC = -0.10                       # the cab's back wall (the sprite's roof ends 33 px from the nose)
DECK = 0.80                      # the bed floor
BED_X = 1.10                     # the bed sides' inner face
BED_H = 0.50


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn = LEN / 2 - 0.10
    zt = -LEN / 2 + 0.06

    belt0 = spline([(ZC, 1.22), (0.6, 1.23), (1.1, 1.21), (1.8, 1.16), (2.2, 1.10), (zn, 1.02)])
    top0 = spline([(ZC, 1.86), (0.10, 1.93), (0.45, 1.96), (0.78, 1.92), (0.96, 1.80), (1.12, 1.36), (1.50, 1.32),
                   (2.00, 1.26), (2.25, 1.20), (zn, 1.08)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.26 * np.exp(-((z - ZF) / 0.62) ** 2)
        base = np.interp(z, [ZC, 0.9, 1.2, 2.2, zn], [1.04, 1.04, 0.90, 0.80, 0.70])
        return base + swell
    tumble0 = spline([(ZC, 0.10), (0.8, 0.12), (1.05, 0.0), (zn, 0.0)])

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

    SU, SV = 1.0, 2.6
    def win(poly, r):
        p = np.array(poly, float)
        c = p.mean(0)
        d = p - c
        shrink = p - d / np.linalg.norm(d * [SU, SV], axis=1, keepdims=True) * r / np.array([SU, SV])
        f = poly_sdf(shrink, SU, SV)
        return lambda u, v: f(u, v) - r
    side = win([(0.90, 0.56), (0.02, 0.56), (0.02, 0.77), (0.78, 0.77)], 0.05)
    screen = win([(1.10, 0.81), (1.10, 0.985), (0.94, 0.985), (0.94, 0.81)], 0.03)
    glass = sdf_union(side, screen)
    seal = lambda u, v: glass(u, v) - 0.014
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    car.surface(body, ZC, zn, 0.0, 1.0, 64, 30, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - ZC) / (zn - ZC), v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, 1.10, 0.94, 0.90, 0.02], vkeys=[0.56, 0.77, 0.81])
    # the cab's back wall with its small rear light, and the nose
    car.cap(body, ZC, 0.0, 1.0, 24, "paint_body",
            regions=[("glass", lambda r, v: np.maximum(np.abs(np.asarray(v) - 0.84) * 6 - 0.6, np.asarray(r) - 0.62)),
                     ("underbody", lambda r, v: np.asarray(v) - 0.14)])
    car.cap(body, zn, 0.0, 1.0, 24, "paint_body", regions=[("underbody", lambda r, v: np.asarray(v) - 0.14)])
    car.surface(lambda u, v: body(u, v, inset=0.06), -0.04, 1.08, 0.45, 1.0, 20, 10, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    for s_ in (1, -1):
        def liner(u, v, s_=s_):
            a = np.asarray(u, float); x = np.asarray(v, float)
            return s_ * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), ZF + (R_ARCH - 0.01) * np.cos(a)
        car.surface(liner, 0.05, math.pi - 0.05, 0.55, 1.20, 16, 2, default="underbody", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # grille: a wide bar grille in a chrome surround low in the nose, a heavy chrome bumper
    car.box("grille", (-0.46, 0.64, zn + 0.00), (0.46, 0.98, zn + 0.05))
    for yb in (0.64, 0.98):
        car.sweep(lambda u, yb=yb: np.stack([(u - 0.5) * 0.96, yb + 0 * u, zn + 0.05 + 0 * u], 1), 0.020, 12, 8, "chrome")
    for xs_ in (-0.47, 0.47):
        car.sweep(lambda u, xs_=xs_: np.stack([xs_ + 0 * u, 0.64 + 0.34 * u, zn + 0.05 + 0 * u], 1), 0.020, 8, 8, "chrome")
    car.sweep(lambda u: np.stack([(u - 0.5) * 2 * 1.22, 0.52 + 0 * u, zn + 0.12 - 0.05 * ((u - 0.5) * 2) ** 2], 1), 0.085, 24, 10,
              "chrome", squash=(0.55, 1.0))
    # headlamps faired into the wing noses: found on the body at x 0.62, y 1.00
    uu, vv = np.meshgrid(np.linspace(1.9, zn, 160), np.linspace(0.3, 0.75, 100))
    bx, by, bz = body(uu.ravel(), vv.ravel())
    k = np.argmin(np.abs(bx - 0.62) + np.abs(by - 1.00))
    LAMP = np.array([0.62, 1.00, bz[k] - 0.04])
    for s_ in (1, -1):
        c = LAMP * np.array([s_, 1.0, 1.0])
        car.revolve([(0.125, -0.10), (0.128, 0.012), (0.112, 0.030)], c, (0, 0, 1), 22, default="chrome", uv_mode="disc")
        car.revolve([(0.112, 0.026), (0.072, 0.044), (0.0, 0.050)], c, (0, 0, 1), 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.035, 0.0), (0.035, 0.02), (0.0, 0.03)], (s_ * 0.36, 0.58, zn + 0.06), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        # mirror on an arm, a door handle on the door's face
        car.sweep(lambda u, s_=s_: np.stack([s_ * (1.02 + 0.20 * u), 1.50 + 0 * u, 0.92 + 0 * u], 1), 0.014, 4, 6, "chrome")
        car.box("chrome", (s_ * 1.22 - 0.035, 1.40, 0.90), (s_ * 1.22 + 0.035, 1.64, 0.94))
    hx, hy, hz = body(np.array([0.20]), np.array([0.60]))
    for s_ in (1, -1):
        car.box("chrome", (s_ * float(hx[0]) - 0.012, 1.30, 0.08), (s_ * float(hx[0]) + 0.012, 1.33, 0.21))

    # chassis, running boards and the stepside bed
    for s_ in (1, -1):
        car.box("frame", (s_ * 0.45 - 0.06, BOT - 0.10, zt + 0.10), (s_ * 0.45 + 0.06, BOT + 0.08, 2.20))
        car.box("frame", (s_ * 0.92, BOT - 0.02, ZR + 0.52), (s_ * 1.14, BOT + 0.03, ZF - 0.50))   # running board
    car.box("deck_wood", (-BED_X, DECK - 0.06, zt + 0.10), (BED_X, DECK, ZC - 0.10))
    car.box("underbody", (-BED_X, BOT - 0.02, zt + 0.10), (BED_X, DECK - 0.06, ZC - 0.10))
    for s_ in (1, -1):
        # bed side: a painted wall with a rolled top rail, stake pockets (the sprite's light dots)
        x0, x1 = (BED_X, BED_X + 0.07) if s_ > 0 else (-BED_X - 0.07, -BED_X)
        car.box("paint_bed", (x0, DECK - 0.06, zt + 0.10), (x1, DECK + BED_H, ZC - 0.10))
        car.sweep(lambda u, s_=s_: np.stack([s_ * (BED_X + 0.035) + 0 * u, DECK + BED_H + 0.02 + 0 * u, zt + 0.10 + (ZC - 0.20 - zt) * u], 1),
                  0.035, 16, 8, "paint_bed")
        for zp in (ZC - 0.25, -1.00, -1.95, zt + 0.25):
            car.box("chrome", (s_ * (BED_X + 0.035) - 0.03, DECK + BED_H + 0.04, zp - 0.04), (s_ * (BED_X + 0.035) + 0.03, DECK + BED_H + 0.06, zp + 0.04))
        # rear wheel tub: a rounded half tube bent over the rear tyre, its ends above the bed side's foot (a full
        # fender hung below the side as a thin bright arc, run qa_va21z2)
        RF, XF, WF = R_TYRE + 0.07, X_REAR, 0.17
        def fender(a, b, s_=s_):
            a = np.asarray(a, float); b = np.asarray(b, float)
            rad = RF + 0.10 * np.sin(b)
            return s_ * (XF + WF * np.cos(b)), R_TYRE + rad * np.sin(a), ZR + 1.25 * rad * np.cos(a)
        car.surface(fender, 0.85, math.pi - 0.85, 0.0, math.pi, 22, 12, default="paint_bed",
                    uvfn=lambda u, v: (u / math.pi, v / math.pi))
    # front board and tailgate
    car.box("paint_bed", (-BED_X - 0.07, DECK - 0.06, ZC - 0.17), (BED_X + 0.07, DECK + BED_H, ZC - 0.10))
    car.box("paint_bed", (-BED_X - 0.07, DECK - 0.06, zt + 0.04), (BED_X + 0.07, DECK + BED_H - 0.02, zt + 0.10))
    car.sweep(lambda u: np.stack([(u - 0.5) * 2 * 1.05, DECK + BED_H - 0.10 + 0 * u, zt + 0.035 + 0 * u], 1), 0.012, 12, 6, "chrome")
    # rear bumper and tail lamps on the bed's corners
    car.sweep(lambda u: np.stack([(u - 0.5) * 2.30, 0.56 + 0 * u, zt - 0.02 + 0 * u], 1), 0.06, 16, 8, "chrome", squash=(0.6, 1.0))
    for s_ in (1, -1):
        car.revolve([(0.055, -0.02), (0.055, 0.02), (0.0, 0.035)], (s_ * (BED_X + 0.035), DECK + 0.22, zt + 0.03), (0, 0, -1), 12,
                    default="lamp_tail", uv_mode="disc")

    # interior: a bench seat, the dash, a steering wheel
    car.box("seat", (-0.88, 0.86, 0.02), (0.88, 1.00, 0.50))
    car.box("seat", (-0.88, 0.98, -0.06), (0.88, 1.56, 0.06))
    car.box("interior_dark", (-0.98, 1.16, 0.86), (0.98, 1.32, 1.02))
    car.revolve([(0.20, -0.012), (0.20, 0.012)], (-0.45, 1.34, 0.70), (0, 0.6, -1), 18, default="interior_dark", uv_mode="disc")

    st = dict(rim_r=0.58, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.10)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_REAR), ("wheel_rr", ZR, X_REAR)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, st)

    U = lambda z: (z - ZC) / (zn - ZC)
    lines_u = [(U(0.92), 0.30, 0.56), (U(0.00), 0.30, 0.56), (U(1.14), 0.56, 0.98)]   # door shuts, the bonnet's rear edge
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.18, 0.36, 0.30)], seed=41)
    car.materials["paint_bed"] = tex_paint(PAINT, 256, seed=42)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=43)
    car.materials["glass"] = tex_glass(256, tint=(34, 42, 50), alpha=180)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(128, bars=6)
    car.materials["underbody"] = tex_underbody()
    car.materials["frame"] = tex_flat((30, 30, 32))
    car.materials["deck_wood"] = tex_planks()
    car.materials["interior_dark"] = tex_flat((14, 14, 14))
    car.materials["seat"] = tex_leather((80, 66, 54))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread(grooves=5)
    car.materials["tyre_side"] = tex_tyre_side()
    bake_ao(car, body, ZC, zn, 0.0, 1.0, "paint_body")
    return car


def tex_planks(size=256, planks=9):
    """the bed floor: dark weathered planks along the bed (the sprite's dark slats), dark gaps, steel skid strips"""
    xx, yy = np.mgrid[0:size, 0:size] / float(size)   # planks along the bed (the sprite's slats)
    rng = np.random.default_rng(41)
    tone = rng.uniform(0.80, 1.10, planks)
    idx = np.minimum((xx * planks).astype(int), planks - 1)
    f = (xx * planks) % 1.0
    grain = 0.06 * np.sin(yy * 90 + idx * 3.1) + 0.04 * np.sin(yy * 23 + idx)
    base = np.array([70.0, 56.0, 44.0])
    v = (tone[idx] + grain)[..., None] * base
    gap = (f < 0.06) | (f > 0.94)
    v = np.where(gap[..., None], np.array([18.0, 16.0, 15.0]), v)
    skid = (np.abs(f - 0.5) < 0.05) & (idx % 3 == 1)
    v = np.where(skid[..., None], np.array([92.0, 92.0, 94.0]), v)
    return Image.fromarray(v.clip(0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va21/p041.png", LEN)
