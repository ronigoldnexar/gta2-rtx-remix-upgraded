#!/usr/bin/env python3
"""008 Bug: a 1950s Beetle read from the GTA2 sprite (nose down in the sprite: a domed body, a
chrome strip and handle down the front lid, separate fenders with the lamps in them, running
boards, blade bumpers, a small rear window over a louvred engine lid). Metres, +z nose,
1 block = 5 m (catalog body 0.469 x 0.812 blocks: 2.34 x 4.06 m; the sprite is wider than a real
Beetle and the model keeps the sprite's footprint)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "008_bug"
PAINT = (235.0, 235.0, 235.0)    # neutral base, tinted by live paint / 235 (see car_036.py)
SPRITE = (179, 137, 105)         # the default remap (catalog), for previews
LEN = 0.8125 * 5.0               # 4.06 m
HALF_W = 0.469 * 5.0 / 2         # 1.17 m over the fenders
ZF, ZR = 1.17, -0.86             # axles (CARI: 15 px forward, 11 px back of the centre)
R_TYRE, W_TYRE = 0.33, 0.21
X_WHEEL = 0.95
R_ARCH = 0.385
BOT = 0.30


def manifest_paint(name, fallback):
    import json
    p = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "models", "manifest.json")
    try:
        for e in json.load(open(p))["models"]:
            if e["name"] == name and e.get("paint_rgb"):
                return tuple(e["paint_rgb"])
    except (OSError, ValueError, KeyError):
        pass
    return fallback


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2, -LEN / 2

    # centre line top: front lid, windscreen, dome roof, rear window, engine lid
    top0 = spline([(zt, 0.66), (-1.90, 0.82), (-1.55, 0.98), (-1.15, 1.20), (-0.80, 1.47), (-0.40, 1.62), (0.05, 1.66),
                   (0.40, 1.60), (0.62, 1.44), (0.86, 1.04), (1.25, 0.95), (1.65, 0.84), (1.92, 0.70), (zn, 0.62)])
    belt0 = spline([(zt, 0.66), (-1.6, 0.86), (-1.0, 0.98), (0.6, 0.98), (1.2, 0.86), (1.8, 0.72), (zn, 0.62)])
    hw0 = spline([(zt, 0.40), (-1.80, 0.64), (-1.25, 0.76), (0.70, 0.78), (1.35, 0.68), (1.80, 0.54), (zn, 0.40)])
    bot0 = spline([(zt, 0.46), (-1.75, BOT), (1.75, BOT), (zn, 0.44)])

    def ends(z, nose=0.22, tail=0.22):
        dn = np.clip((z - (zn - nose)) / nose, 0, 1)
        dt = np.clip(((zt + tail) - z) / tail, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dt ** 2, 0, 1))

    def body(u, v, inset=0.0):
        """u = z; v in 0..1: bottom centre -> belt (v = 0.5) -> roof centre"""
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * f - inset
        belt = belt0(z)
        top = belt + (top0(z) - belt) * f - inset
        bot = belt - (belt - bot0(z)) * f + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)       # 0 at the belt, pi/2 at bottom / top centre
        c, s = np.cos(a), np.sin(a)
        x = np.where(lo, hw * (0.86 + 0.14 * sepow(c, 1.4)), hw * sepow(c, 0.78))
        y = np.where(lo, belt - (belt - bot) * sepow(s, 0.55), belt + (top - belt) * sepow(s, 0.92))
        return x, y, z

    # windows in (z, v) parameter space (v 0.5 = belt, 1 = roof centre); su/sv make it about metric
    SU, SV = 1.0, 2.4
    def win(poly, r):
        p = np.array(poly, float)
        c = p.mean(0)
        d = p - c
        shrink = p - d / np.linalg.norm(d * [SU, SV], axis=1, keepdims=True) * r / np.array([SU, SV]) * 1.0
        f = poly_sdf(shrink, SU, SV)
        return lambda u, v: f(u, v) - r
    side_front = win([(0.70, 0.585), (-0.16, 0.585), (-0.16, 0.835), (0.30, 0.835)], 0.05)
    side_rear = win([(-0.26, 0.585), (-0.98, 0.585), (-0.70, 0.835), (-0.26, 0.835)], 0.06)
    screen = win([(0.84, 0.60), (0.84, 1.02), (0.48, 1.02), (0.48, 0.87)], 0.05)
    screen = (lambda f: (lambda u, v: np.maximum(f(u, v), 0.885 - np.asarray(v) - np.clip((0.86 - np.asarray(u)) * 0.0, 0, 1))))(screen)
    rear = win([(-0.86, 0.90), (-0.86, 1.02), (-1.12, 1.02), (-1.12, 0.90)], 0.07)
    glass = sdf_union(side_front, side_rear, screen, rear)
    seal = lambda u, v: glass(u, v) - 0.012
    # the windscreen is cut where it would reach under the cowl
    def lid_strip(u, v):
        z = np.asarray(u, float)
        return np.maximum(np.abs(1 - np.asarray(v)) * 2.4 - 0.016, np.maximum(1.0 - z, z - 1.95))
    def under(u, v):
        x, y, z = body(u, v)
        return np.maximum(np.asarray(v) - 0.30, y - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 56, 28, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chrome", lid_strip), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[0.84, 0.48, -0.16, -0.26, -0.86, -1.12], vkeys=[0.585, 0.835, 0.87, 0.90])
    # the cabin's inside: a dark shell a few cm in, so the glass shows a cabin, not the paint's back
    car.surface(lambda u, v: body(u, v, inset=0.05), -1.15, 0.85, 0.25, 1.0, 24, 12, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # fenders: pontoons over each wheel, open underneath on the arch
    def fender(zc, z0, z1, x0, a_max, top_y, round_front, round_back, sweep_back, sweep_front):
        """a pontoon over the wheel at zc from z0 (back) to z1 (front); its ends round off
        (round_*) or sweep down into the running board (sweep_*)"""
        def fn(u, v):
            z = np.asarray(u, float); phi = np.asarray(v, float)
            tb = np.clip((z - z0) / round_back, 0, 1) if round_back > 0 else np.ones_like(z)
            tf = np.clip((z1 - z) / round_front, 0, 1) if round_front > 0 else np.ones_like(z)
            e = np.sqrt(1 - (1 - tb) ** 2) * np.sqrt(1 - (1 - tf) ** 2)
            # sweep: toward that end the crown drops to the board and the section flattens
            sb = smoothstep(z0 + sweep_back, z0, z) if sweep_back > 0 else np.zeros_like(z)
            sf = smoothstep(z1 - sweep_front, z1, z) if sweep_front > 0 else np.zeros_like(z)
            sw = np.maximum(sb, sf)
            dz = z - zc
            yc = np.where(np.abs(dz) < R_ARCH, R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - dz ** 2, 0, None)), R_TYRE)
            yc = np.maximum(yc, BOT + 0.06)
            yc = yc * (1 - sw) + (BOT + 0.06) * sw
            crown = top_y - 0.10 * np.clip(np.abs(dz) / 0.9, 0, 1) ** 2
            ytop = yc + (crown - yc) * e
            ytop = ytop * (1 - sw) + (BOT + 0.10) * sw
            a = a_max * (0.80 + 0.20 * np.clip(1 - (dz / 0.9) ** 2, 0, 1)) * np.maximum(e, 0.0)
            a = a * (1 - 0.15 * sw)
            b = np.maximum(ytop - yc, 1e-4)
            x = x0 + a * sepow(np.cos(phi), 0.8)
            y = yc + b * sepow(np.sin(phi), 0.9)
            return x, y, z
        return fn
    ff = fender(ZF, 0.20, zn - 0.05, X_WHEEL - 0.02, 0.24, 0.84, 0.24, 0.0, 0.55, 0.0)
    fr = fender(ZR, -1.98, 0.00, X_WHEEL - 0.02, 0.24, 0.90, 0.0, 0.28, 0.0, 0.55)
    fenders = (("paint_fender_f", ff, 0.20, zn - 0.05), ("paint_fender_r", fr, -1.98, 0.00))
    for mname, fn, z0, z1 in fenders:
        car.surface(fn, z0, z1, 0.0, math.pi, 30, 12, mirror=True, default=mname,
                    uvfn=lambda u, v, z0=z0, z1=z1: ((u - z0) / (z1 - z0), v / math.pi))
    # running boards between the fenders
    for side in (1, -1):
        car.box("running_board_rubber", (min(side * 0.74, side * 1.07), BOT + 0.02, -0.20), (max(side * 0.74, side * 1.07), BOT + 0.08, 0.40))
    # wheel well liners
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, zc=zc, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.62, 1.10, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # headlamps in the front fenders, tail lamps on the rear fenders
    for side in (1, -1):
        c = np.array([side * (X_WHEEL - 0.03), 0.72, 1.86])
        ax = (side * 0.10, 0.12, 1.0)
        car.revolve([(0.115, -0.03), (0.118, 0.012), (0.105, 0.028)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.104, 0.024), (0.07, 0.045), (0.0, 0.052)], c, ax, 22, default="lamp_head", uv_mode="disc")
        t = np.array([side * (X_WHEEL - 0.02), 0.78, -1.68])
        car.revolve([(0.05, -0.02), (0.052, 0.02), (0.0, 0.035)], t, (0, 0.35, -1.0), 14, default="lamp_tail", uv_mode="disc")
        car.revolve([(0.02, 0.0), (0.0, 0.012)], c + [side * -0.18, -0.10, 0.08], (0, 0, 1), 10, default="lamp_amber", uv_mode="disc")

    # blade bumpers with over-riders
    def blade(zc, sign):
        def path(u):
            x = (u - 0.5) * 2 * 0.98
            z = zc - sign * 0.20 * (x / 0.98) ** 2
            return np.stack([x, np.full_like(x, 0.47), z], 1)
        return path
    car.sweep(blade(zn + 0.04, 1), 0.065, 22, 8, "chrome", squash=(0.35, 1.0))
    car.sweep(blade(zt - 0.04, -1), 0.065, 22, 8, "chrome", squash=(0.35, 1.0))
    for zc, sgn in ((zn + 0.03, 1), (zt - 0.03, -1)):
        for side in (1, -1):
            x = side * 0.48
            car.sweep(lambda u, x=x, zc=zc, sgn=sgn: np.stack([x + 0 * u, 0.40 + 0.20 * u, zc - sgn * 0.11 - sgn * 0.02 * u], 1),
                      0.024, 6, 8, "chrome")
    # front lid handle
    car.box("chrome", (-0.035, 0.66, 1.93), (0.035, 0.70, 1.99))
    # door handles
    for side in (1, -1):
        car.box("chrome", (side * 0.805 - 0.012, 1.00, 0.18), (side * 0.805 + 0.012, 1.025, 0.30))
    # mirror on the driver's door
    car.sweep(lambda u: np.stack([-0.80 - 0.10 * u, 1.10 + 0.04 * u, 0.62 + 0 * u], 1), 0.012, 4, 6, "chrome")
    car.revolve([(0.045, 0.0), (0.045, 0.02), (0.0, 0.03)], (-0.92, 1.15, 0.62), (0, 0, -1), 14, default="chrome", uv_mode="disc")

    # interior: seats, dash, steering wheel
    for xs in (-0.38, 0.38):
        car.box("seat", (xs - 0.24, 0.48, 0.0), (xs + 0.24, 0.62, 0.50))
        car.box("seat", (xs - 0.24, 0.58, -0.08), (xs + 0.24, 1.18, 0.04))
    car.box("seat", (-0.66, 0.48, -0.80), (0.66, 0.62, -0.40))
    car.box("seat", (-0.66, 0.58, -0.92), (0.66, 1.14, -0.80))
    car.box("interior_dark", (-0.72, 0.80, 0.72), (0.72, 1.00, 0.90))
    car.revolve([(0.17, -0.01), (0.17, 0.01), (0.15, 0.01), (0.15, -0.01), (0.17, -0.01)], (-0.38, 1.05, 0.62),
                (0, 0.45, -1.0), 20, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.58, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.14)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    # paint: door gaps, front lid and engine lid outlines, engine louvres (u = z normalised, v as the body)
    U = lambda z: (z - zt) / LEN
    lines_u = [(U(0.70), 0.36, 0.585), (U(-0.20), 0.36, 0.585), (U(1.88), 0.78, 1.0), (U(-1.18), 0.70, 1.0)]
    lines_v = []
    img = tex_paint(PAINT, 512, lines_u=lines_u, lines_v=lines_v, ao_v=[(0.16, 0.34, 0.30)], seed=8)
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    dark = tuple(int(c * 0.30) for c in PAINT)
    for k in range(8):
        y = int((0.80 + k * 0.022) * 512)
        d.line([(int(U(-1.45) * 512), y), (int(U(-1.30) * 512), y)], fill=dark, width=2)
    car.materials["paint_body"] = img
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=81)
    for mname, fn, z0, z1 in fenders:
        car.materials[mname] = tex_paint(PAINT, 256, seed=82)
    # occlusion: the body under the fenders and roof edge, the fenders' insides, the sills
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    for mname, fn, z0, z1 in fenders:
        bake_ao(car, fn, z0, z1, 0.0, math.pi, mname, size=96)
    car.materials["glass"] = tex_glass(256, tint=(58, 74, 88), alpha=120)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["underbody"] = tex_flat((28, 27, 26))
    car.materials["running_board_rubber"] = tex_flat((34, 33, 32))
    car.materials["interior_dark"] = tex_flat((44, 40, 36))
    car.materials["seat"] = tex_leather((150, 128, 100))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va2/p008.png", LEN)
