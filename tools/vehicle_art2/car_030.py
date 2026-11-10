#!/usr/bin/env python3
"""030 Land Roamer (VEHICLE-ART-22, qav51 "bonnet peppered with black stair-stepped holes"): the catalog's Land Rover
Series I / Willys idiom in army olive, read from the GTA2 sprite nose down (assets-src/cars/sprites_x4/
030_land_roamer_default.png, body 26 x 47 px): a short square body of flat panels: a flat bonnet carrying the sprite's
white star, flat-topped front wings with square wheel openings and the headlamps in their front panels, a mesh grille
panel between them, an upright split windscreen in a frame (the sprite's light bar and dark band 24 px from the nose),
and behind it a canvas tilt over the cab and the rear tub (the sprite's darker ribbed olive), side screens with the
cabin behind them, square rear wheel openings, a spare wheel on the tail, black steel bumpers, big off-road tyres.
Painted (neutral base, tinted to the identity record's paint); the canvas is its own fixed darker olive.
It replaces the image-to-3D shell (its atlas baked cut-out texels into the bonnet: black holes, an olive wedge).
Metres, +z nose, 1 block = 5 m (catalog body 0.406 x 0.734 blocks: 2.03 x 3.67 m; axles +15 / -11 px)."""
import math
import os
import sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "030_land_roamer"
PAINT = (235.0, 235.0, 235.0)
SPRITE = (53, 65, 39)
CANVAS = (62, 72, 46)            # the tilt's own olive drab (the sprite's ribbed rear, darker than the bonnet)
LEN = 47 / 64 * 5.0              # 3.67 m
HALF_W = 26 / 64 * 5.0 / 2       # 1.016 m
ZF, ZR = 15 / 64 * 5.0, -11 / 64 * 5.0    # axles +1.17 / -0.86
R_TYRE, W_TYRE = 0.40, 0.28
X_WHEEL = 0.80
W = 1.00                         # the body sides
OPEN = 0.47                      # half length of a wheel opening
YW = 0.86                        # the wing / tub line over the wheels
ZS = -0.06                       # the windscreen
YB = 1.04                        # the body top (the belt)


def tube(z0, z1, wx, y0, y1, r):
    """a rounded-rectangle section along z, half of it (v 0 at the side's foot .. 1 on the centre line, mirrored):
    a flat side, a corner of radius r, a flat top"""
    side = (y1 - r) - y0
    arc = 0.5 * math.pi * r
    top = wx - r
    tot = side + arc + top
    def fn(u, v):
        z = np.asarray(u, float); s = np.asarray(v, float) * tot
        a = np.clip((s - side) / r, 0, 0.5 * math.pi)
        x = np.where(s < side, wx, np.where(s < side + arc, wx - r + r * np.cos(a), wx - r - (s - side - arc)))
        y = np.where(s < side, y0 + s, np.where(s < side + arc, y1 - r + r * np.sin(a), y1))
        x = np.maximum(x, 0.0)
        return x, y, z
    return fn, side / tot, (side + arc) / tot


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2, -LEN / 2
    zf = zn - 0.06               # the body's front (the bumper ahead of it)
    zb = zt + 0.27               # the body's tail (the spare wheel on it reaches the sprite's tail)

    # ---- the chassis and the floor
    car.box("underbody", (-0.62, 0.30, zt + 0.10), (0.62, 0.48, zn - 0.10))

    # ---- front: the bonnet between the wings, the grille panel, the wings with square openings
    car.box("paint_body", (-0.56, 0.62, ZS), (0.56, YB + 0.02, zf - 0.03))
    car.box("grille", (-0.50, 0.50, zf - 0.05), (0.50, YB - 0.04, zf - 0.015))
    car.box("paint_body", (-0.56, 0.48, zf - 0.04), (0.56, 0.52, zf - 0.01))                 # the grille panel's sill
    for s_ in (1, -1):
        lo, hi = min(s_ * 0.56, s_ * W), max(s_ * 0.56, s_ * W)
        car.box("paint_body", (lo, YW, ZS), (hi, YB, zf))                                        # the flat wing top
        car.box("paint_body", (lo, 0.50, ZF + OPEN), (hi, YW, zf))                               # ahead of the opening
        car.box("paint_body", (lo, 0.50, ZS), (hi, YW, ZF - OPEN))                               # behind it (the door's foot)
        car.box("underbody", (lo + 0.02, YW - 0.02, ZF - OPEN), (hi - 0.02, YW, ZF + OPEN))       # the opening's roof
        car.box("underbody", (min(s_ * 0.56, s_ * 0.60), 0.45, ZF - OPEN), (max(s_ * 0.56, s_ * 0.60), YW, ZF + OPEN))  # its inner wall

    # ---- the tub (cab and rear body) under the tilt, square rear openings
    car.box("paint_body", (-W, YW, zb), (W, YB, ZS))
    car.box("paint_body", (-W, 0.48, ZR + OPEN), (W, YW, ZS))
    car.box("paint_body", (-W, 0.48, zb), (W, YW, ZR - OPEN))
    for s_ in (1, -1):
        lo, hi = min(s_ * 0.56, s_ * W), max(s_ * 0.56, s_ * W)
        car.box("underbody", (lo + 0.02, YW - 0.02, ZR - OPEN), (hi - 0.02, YW, ZR + OPEN))
        car.box("underbody", (min(s_ * 0.56, s_ * 0.60), 0.45, ZR - OPEN), (max(s_ * 0.56, s_ * 0.60), YW, ZR + OPEN))
        # the door: shut lines and a handle
        for zl in (ZS - 0.04, -0.92):
            car.box("seal", (min(s_ * W, s_ * (W + 0.006)), 0.52, zl - 0.006), (max(s_ * W, s_ * (W + 0.006)), YB, zl + 0.006))
        car.box("chrome", (min(s_ * W, s_ * (W + 0.02)), 0.92, -0.86), (max(s_ * W, s_ * (W + 0.02)), 0.95, -0.74))
    car.box("underbody", (-0.56, 0.48, ZR - OPEN), (0.56, YW, ZR + OPEN))   # between the rear openings (no see-through)

    # ---- the windscreen: a frame with two flat panes, upright
    car.box("paint_body", (-W + 0.02, YB, ZS - 0.06), (W - 0.02, YB + 0.06, ZS))
    car.box("paint_body", (-W + 0.02, 1.62, ZS - 0.06), (W - 0.02, 1.68, ZS))
    for x0, x1 in ((-W + 0.02, -W + 0.08), (W - 0.08, W - 0.02), (-0.03, 0.03)):
        car.box("paint_body", (x0, YB, ZS - 0.06), (x1, 1.68, ZS))
    for x0, x1 in ((-W + 0.08, -0.03), (0.03, W - 0.08)):
        car.box("glass", (x0, YB + 0.06, ZS - 0.035), (x1, 1.62, ZS - 0.025))
    # ---- the canvas tilt over the cab and the tub: a rounded box from the windscreen to the tail
    tz0, tz1 = zb + 0.02, ZS - 0.06
    fn, v_side, v_top = tube(tz0, tz1, W - 0.01, YB - 0.02, 1.86, 0.16)
    def side_screen(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        # the cab's side screens (the door tops): u along z, v up the side
        du = np.abs(u - (-0.47)) - 0.36
        dv = np.abs(v - 0.5 * (0.13 + 0.40) * v_side / 0.5) - 0.5 * (0.40 - 0.13) * v_side / 0.5
        return np.maximum(du, dv * 2.0)
    def ribs(u, v):
        u = np.asarray(u, float)
        d = np.min(np.abs(u[..., None] - np.array([-0.98, -1.42])), axis=-1)
        return np.maximum(d - 0.015, np.asarray(v) - 2.0)
    car.surface(fn, tz0, tz1, 0.0, 1.0, 30, 24, mirror=True, regions=[("glass", side_screen), ("canvas_seam", ribs)], default="canvas",
                uvfn=lambda u, v: ((u - tz0) / (tz1 - tz0), np.asarray(v)), ukeys=[-0.83, -0.11, -0.98, -1.42],
                vkeys=[0.13 * v_side / 0.5, 0.40 * v_side / 0.5, v_side, v_top])
    car.cap(fn, tz0, 0.0, 1.0, 24, "canvas")                       # the rear flap
    car.box("canvas", (-W + 0.01, 1.68, tz1), (W - 0.01, 1.86, ZS))  # over the windscreen frame
    # the cabin's dark inside (behind the side screens and the windscreen)
    fi, _, _ = tube(tz0, tz1, W - 0.08, YB - 0.02, 1.78, 0.12)
    car.surface(fi, -1.00, tz1, 0.0, 1.0, 12, 10, mirror=True, default="interior_dark", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    car.box("interior_dark", (-W + 0.08, YB - 0.02, -1.02), (W - 0.08, 1.78, -0.98))   # the cab's back wall
    # seats, dash, steering wheel
    car.box("seat", (-0.86, 0.62, -0.72), (-0.12, 0.76, -0.30))
    car.box("seat", (0.12, 0.62, -0.72), (0.86, 0.76, -0.30))
    car.box("seat", (-0.86, 0.74, -0.80), (-0.12, 1.22, -0.70))
    car.box("seat", (0.12, 0.74, -0.80), (0.86, 1.22, -0.70))
    car.box("interior_dark", (-0.94, 0.90, -0.30), (0.94, YB, ZS - 0.06))
    car.revolve([(0.19, -0.012), (0.19, 0.012)], (-0.48, 1.12, -0.30), (0, 0.55, -1), 18, default="interior_dark", uv_mode="disc")

    # ---- lamps: round headlamps in the wing front panels, side lamps beside them, tail lamps on the corners
    for s_ in (1, -1):
        c = (s_ * 0.78, 0.70, zf)
        car.revolve([(0.115, -0.01), (0.115, 0.018), (0.100, 0.030)], c, (0, 0, 1), 22, default="chrome", uv_mode="disc")
        car.revolve([(0.100, 0.026), (0.07, 0.038), (0.0, 0.044)], c, (0, 0, 1), 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.035, 0.0), (0.035, 0.018), (0.0, 0.026)], (s_ * 0.78, 0.92, zf), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        car.box("lamp_tail", (min(s_ * 0.78, s_ * 0.92), 0.66, zb - 0.02), (max(s_ * 0.78, s_ * 0.92), 0.76, zb))
    # ---- bumpers: black steel channel at both ends, with towing eyes
    car.box("steel", (-W, 0.38, zf), (W, 0.54, zn))
    car.box("steel", (-W, 0.40, zt + 0.05), (W, 0.54, zb))
    for s_ in (1, -1):
        car.box("steel", (s_ * 0.40 - 0.05, 0.30, zf - 0.02), (s_ * 0.40 + 0.05, 0.38, zn - 0.02))
    # the spare: a tyre on a painted rim facing the tail, on the flap below the tilt
    r, w, c = 0.32, 0.20, (0.0, 0.92, zb - 0.11)
    prof = [(0.56 * r, -0.42 * w), (0.80 * r, -0.50 * w), (0.93 * r, -0.50 * w), (0.985 * r, -0.44 * w), (r, -0.30 * w), (r, 0.30 * w),
            (0.985 * r, 0.44 * w), (0.93 * r, 0.50 * w), (0.80 * r, 0.50 * w), (0.56 * r, 0.42 * w)]
    car.revolve(prof, c, (0, 0, -1), 26, mat_of=lambda k: "tyre_tread" if 3 <= k <= 5 else "tyre_side")
    car.revolve([(0.56 * r, 0.42 * w), (0.40 * r, 0.32 * w), (0.0, 0.36 * w)], c, (0, 0, -1), 20, default="paint_wheel", uv_mode="disc")
    car.revolve([(0.56 * r, -0.42 * w), (0.0, -0.30 * w)], c, (0, 0, -1), 16, default="underbody", uv_mode="disc")
    # ---- the white star on the bonnet (the sprite's), a flat five-point star a hair above the paint
    rr = np.array([0.26 if k % 2 == 0 else 0.105 for k in range(10)])
    ang = np.array([math.pi / 2 + k * math.pi / 5 for k in range(10)])
    sx = rr * np.cos(ang); sz = rr * np.sin(ang)
    zc = 0.80; yc = YB + 0.02 + 0.003
    P = [(0.0, yc, zc)] + [(float(sx[k]), yc, zc + float(sz[k])) for k in range(10)]
    N = [(0, 1, 0)] * 11
    T = [(0.5, 0.5)] * 11
    F = [(0, 1 + (k + 1) % 10, 1 + k) for k in range(10)]
    car.part("star").add(P, N, T, F)
    # a ring round the star (the army roundel's outline)
    a = np.linspace(0, 2 * math.pi, 41)[:-1]
    P2, F2 = [], []
    for k, t in enumerate(a):
        for rad in (0.30, 0.325):
            P2.append((rad * math.cos(t), yc, zc + rad * math.sin(t)))
    for k in range(40):
        i0, i1, j0, j1 = 2 * k, 2 * k + 1, 2 * ((k + 1) % 40), 2 * ((k + 1) % 40) + 1
        F2 += [(i0, j0, i1), (i1, j0, j1)]
    car.part("star").add(P2, [(0, 1, 0)] * len(P2), [(0.5, 0.5)] * len(P2), F2)

    style = dict(rim_r=0.55, rim_mat="paint_wheel", cap_mat="underbody", whitewall=0.0, cap_dome=0.06)
    for nm, zc_, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc_), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    car.materials["paint_body"] = tex_paint(PAINT, 128, seed=30)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=31)
    car.materials["canvas"] = tex_canvas(CANVAS)
    car.materials["canvas_seam"] = tex_flat(tuple(int(c * 0.55) for c in CANVAS))
    car.materials["glass"] = tex_glass(128, tint=(30, 38, 46), alpha=195)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["steel"] = tex_flat((28, 29, 27))
    car.materials["grille"] = tex_mesh_grille()
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((12, 12, 12))
    car.materials["seat"] = tex_leather((58, 54, 44))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    car.materials["star"] = tex_flat((232, 230, 214))
    return car


def tex_canvas(rgb, size=128):
    """the tilt: a woven olive drab with soft vertical creases (u along the car) and a darker foot"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    n = noise(size, size, 3, 33) * 0.6 + noise(size, size, 24, 34) * 0.4
    crease = 0.06 * np.cos(xx * 2 * math.pi * 7) * np.exp(-((yy - 0.3) / 0.35) ** 2)
    f = 0.92 + 0.10 * n + crease - 0.10 * np.clip(0.12 - yy, 0, None) / 0.12
    a = np.array(rgb, float)[None, None, :] * f[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def tex_mesh_grille(size=128):
    """the Land Rover's square wire mesh in a painted frame (dark holes, lit wires)"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    wire = (np.abs(((xx * 16) % 1.0) - 0.5) > 0.36) | (np.abs(((yy * 14) % 1.0) - 0.5) > 0.36)
    v = np.where(wire, 70, 10)
    edge = (xx < 0.05) | (xx > 0.95) | (yy < 0.06) | (yy > 0.94)
    v = np.where(edge, 40, v)
    return Image.fromarray(np.dstack([v * 0.95, v, v * 0.85]).clip(0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va22/p030.png", LEN)
