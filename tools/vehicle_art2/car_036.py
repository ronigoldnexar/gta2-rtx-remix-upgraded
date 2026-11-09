#!/usr/bin/env python3
"""036 Schmidt: a tandem two-seat bubble car (Messerschmitt KR200 idiom) read from the GTA2 sprite:
nose down in the sprite, a flat front deck with a chrome centre spine and two lamps, a long glass
canopy with a cross hoop between the seats and a spine, a pointed tail with two small fins.
Metres, +z nose, 1 block = 5 m (catalog body 0.375 x 0.828 blocks)."""
import math
import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "036_schmidt"
# The paint is a neutral 235 base: the renderer multiplies it by live paint / 235 (identity.cpp; the manifest's
# paint_rgb is 235 too), so every remap shows the sprite's own colour. SPRITE is the default remap, for previews.
PAINT = (235.0, 235.0, 235.0)
SPRITE = (117, 88, 77)
LEN = 0.828 * 5.0                # 4.14 m
HALF_W = 0.375 * 5.0 / 2         # 0.9375 m, the widest point (front wheel pods)
ZF, ZR = 1.40, -1.40             # axles (CARI wheel offsets +-18 px of 53)
R_TYRE, W_TYRE = 0.265, 0.165
X_FRONT, X_REAR = 0.775, 0.70
R_ARCH = 0.315
BELT = 0.74


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2, -LEN / 2

    hw0 = spline([(zt, 0.40), (-1.85, 0.64), (-1.45, 0.78), (-0.6, 0.80), (0.5, 0.80), (0.95, 0.84),
                  (1.40, 0.9375), (1.75, 0.88), (zn, 0.58)])
    top0 = spline([(zt, 0.60), (-1.85, 0.76), (-1.3, BELT), (1.0, BELT), (1.40, 0.72), (1.8, 0.64), (zn, 0.52)])
    mid0 = spline([(zt, 0.48), (-1.6, 0.56), (0.0, 0.56), (1.6, 0.54), (zn, 0.42)])
    bot0 = spline([(zt, 0.36), (-1.7, 0.21), (1.7, 0.21), (zn, 0.32)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            inside = dz < R_ARCH + 0.06
            # the arch edge rounded into the sill over 6 cm
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            y = np.where(dz > R_ARCH, R_TYRE + (R_ARCH + 0.06 - dz) / 0.06 * 0.0, y)
            lift = np.maximum(lift, np.where(inside, y, 0))
        return lift

    def ends(z):
        """the rounding of nose and tail: the section shrinks on an ellipse"""
        dn = np.clip((z - (zn - 0.30)) / 0.30, 0, 1)
        dt = np.clip(((zt + 0.26) - z) / 0.26, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dt ** 2, 0, 1))

    def tub(u, v):
        """u = z, v in 0..1: bottom centre -> right side -> top centre"""
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * f
        mid = mid0(z)
        top = mid + (top0(z) - mid) * f
        bot = np.maximum(bot0(z), arch(z))
        bot = np.minimum(bot, mid - 0.04)
        bot = mid - (mid - bot) * f
        th = -math.pi / 2 + math.pi * v
        c, s = np.cos(th), np.sin(th)
        # squarer at the sides than at top and bottom
        x = hw * sepow(c, 0.55)
        y = np.where(s >= 0, mid + (top - mid) * sepow(s, 0.85), mid + (mid - bot) * sepow(s, 0.70))
        return x, y, z

    # the canopy: a teardrop bubble on the belt
    cz0, cz1 = 1.06, -1.72
    cw = spline([(cz1, 0.0), (-1.55, 0.24), (-1.1, 0.46), (-0.4, 0.60), (0.2, 0.63), (0.65, 0.59), (0.92, 0.42), (cz0, 0.0)])
    ch = spline([(cz1, 0.0), (-1.55, 0.20), (-1.1, 0.46), (-0.4, 0.64), (0.15, 0.68), (0.65, 0.58), (0.92, 0.34), (cz0, 0.0)])

    def canopy_ends(z):
        a = np.clip((z - cz1) / 0.10, 0, 1); b = np.clip((cz0 - z) / 0.12, 0, 1)
        return np.sqrt(1 - (1 - a) ** 2) * np.sqrt(1 - (1 - b) ** 2)

    def canopy(u, v):
        z = np.asarray(u, float); phi = np.asarray(v, float)
        e = canopy_ends(z)
        w = cw(z) * e; h = ch(z) * e
        x = w * np.cos(phi)
        y = BELT - 0.005 + h * sepow(np.sin(phi), 0.9)
        return x, y, z

    # cockpit opening in the deck: inside the canopy's base outline (2 cm in)
    def opening(u, v):
        x, y, z = tub(u, v)
        e = canopy_ends(z)
        return np.where(v > 0.55, x - (cw(z) * e - 0.03), 1.0) + np.where(cw(z) * e < 0.06, 1.0, 0.0)

    # rub strip: a thin band round the widest point
    def rub(u, v):
        z = np.asarray(u, float)
        return np.abs(v - 0.5) * 3.0 - 0.012 + np.where((arch(z) > 0) | (z > 1.85) | (z < -1.85), 1.0, 0.0)

    def under(u, v):
        return v - 0.18

    # the bonnet spine (sprite: a chrome strip down the middle of the front deck)
    def spine(u, v):
        z = np.asarray(u, float)
        return np.maximum(np.abs(1 - v) * 3.0 - 0.018, np.maximum(1.02 - z, z - (zn - 0.12)))

    car.surface(tub, zt, zn, 0.0, 1.0, 64, 26, mirror=True,
                regions=[("_cut", opening), ("chrome", rub), ("chrome_spine", spine), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH])
    car.parts.pop("_cut", None)

    # canopy frame: base rim, a hoop over the windscreen, a hoop between the seats, a spine
    s_v = 0.62     # metres per radian, about
    def frame(u, v):
        z = np.asarray(u, float); phi = np.asarray(v, float)
        rim = phi * s_v - 0.035
        hoop1 = np.abs(z - 0.62) - 0.028
        hoop2 = np.abs(z + 0.10) - 0.040
        spine_ = np.maximum((math.pi / 2 - phi) * s_v - 0.020, np.maximum(z - 0.62, -1.40 - z))
        return np.minimum.reduce([rim, hoop1, hoop2, spine_])
    car.surface(canopy, cz1, cz0, 0.0, math.pi / 2, 44, 14, mirror=True,
                regions=[("paint_frame", frame), ("seal", lambda u, v: frame(u, v) - 0.010)],
                default="glass", uvfn=lambda u, v: ((u - cz1) / (cz0 - cz1), v / (math.pi / 2)),
                ukeys=[0.62 - 0.028, 0.62 + 0.028, -0.14, -0.06])

    # fins: upright blades on the tail's corners, tallest at the back
    for side in (1, -1):
        def fin(u, v, side=side):
            z = np.asarray(u, float); a = np.asarray(v, float)
            t = np.clip((-1.25 - z) / (-1.25 + 1.98), 0, 1)          # 0 forward, 1 at the back
            hgt = 0.15 * smoothstep(0.0, 0.9, t) * np.sqrt(np.clip(1 - ((t - 0.9) / 0.1).clip(0) ** 2, 0, 1))
            th = 0.018 * np.sqrt(np.clip(np.sin(t * math.pi), 0, 1)) + 0.002
            base = top0(z) - 0.04
            x = side * (0.60 + 0.03 * t) + th * np.cos(a)
            y = base + (hgt + 0.04) * (0.5 + 0.5 * np.sin(a))
            return x, y, z
        car.surface(fin, -1.98, -1.25, 0, 2 * math.pi, 16, 8, default="paint_body",
                    uvfn=lambda u, v: (0.5 + 0.0 * u, 0.5 + 0.0 * v))
        # tail lamp on the fin's back end
        car.revolve([(0.040, 0.0), (0.036, 0.016), (0.0, 0.020)], (side * 0.63, top0(np.array([-1.96]))[0] + 0.05, -1.97),
                    (0, 0, -1), 14, default="lamp_tail", uv_mode="disc")

    # headlamps: on the front deck's corners, set in chrome bezels, looking forward
    for side in (1, -1):
        c = np.array([side * 0.50, 0.645, 1.86])
        car.revolve([(0.088, -0.02), (0.090, 0.010), (0.080, 0.022)], c, (0, 0.12, 1), 20, default="chrome", uv_mode="disc")
        car.revolve([(0.078, 0.014), (0.05, 0.022), (0.0, 0.026)], c, (0, 0.12, 1), 20, default="lamp_head", uv_mode="disc")
        # amber indicator below
        car.revolve([(0.028, 0.0), (0.0, 0.012)], c + [side * -0.02, -0.12, 0.12], (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")

    # bumpers: chrome tubes following the nose and tail outlines
    def bumper(zc, width, bend, y):
        def path(u):
            x = (u - 0.5) * 2 * width
            z = zc - np.sign(zc) * bend * (x / width) ** 2
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(bumper(zn - 0.02, 0.62, 0.26, 0.38), 0.030, 22, 8, "chrome")
    car.sweep(bumper(zt + 0.03, 0.52, 0.26, 0.42), 0.030, 22, 8, "chrome")

    # wheel well liners: dark half shells over each wheel so no daylight shows through the arch
    for zc, xw in ((ZF, X_FRONT), (ZR, X_REAR)):
        for side in (1, -1):
            def liner(u, v, zc=zc, xw=xw, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.005) * np.sin(a), zc + (R_ARCH - 0.005) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, xw - 0.26, xw + 0.10, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # interior: floor, two tandem seats, a handlebar and a dash under the windscreen
    car.box("interior_dark", (-0.52, 0.30, -1.35), (0.52, 0.34, 0.95))
    for z0, z1 in ((0.05, 0.50), (-0.80, -0.30)):
        car.box("seat", (-0.30, 0.34, z0), (0.30, 0.52, z1))                  # cushion
        car.box("seat", (-0.30, 0.50, z0 - 0.10), (0.30, 1.00, z0 + 0.02))    # back
    car.box("interior_dark", (-0.46, 0.52, 0.70), (0.46, 0.71, 0.92))        # dash
    car.sweep(lambda u: np.stack([(u - 0.5) * 0.46, 0.92 + 0 * u, 0.62 - 0.05 * ((u - 0.5) * 2) ** 2], 1), 0.014, 12, 8, "chrome")
    car.sweep(lambda u: np.stack([0 * u, 0.70 + 0.22 * u, 0.80 - 0.18 * u], 1), 0.016, 6, 8, "interior_dark")

    # wheels
    style = dict(rim_r=0.60, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.16)
    for nm, zc, xw in (("wheel_fl", ZF, -X_FRONT), ("wheel_fr", ZF, X_FRONT), ("wheel_rl", ZR, -X_REAR), ("wheel_rr", ZR, X_REAR)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    # textures
    car.materials["paint_body"] = tex_paint(PAINT, 512, ao_v=[(0.18, 0.40, 0.35)], seed=36)
    car.materials["paint_frame"] = tex_paint(PAINT, 64, seed=37)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=38)
    car.materials["glass"] = tex_glass(256, tint=(60, 80, 96), alpha=105)
    car.materials["seal"] = tex_flat((22, 22, 24))
    car.materials["chrome"] = tex_chrome()
    # VEHICLE-ART-7: the spine lies flat on the deck, at the body map's v ~ 1, where the chrome band texture is its
    # dark ground reflection (a black stripe in the game): a flat strip of bright metal mirroring the sky instead
    car.materials["chrome_spine"] = tex_flat((222, 228, 236), 64)
    car.materials["underbody"] = tex_flat((30, 28, 27))
    car.materials["interior_dark"] = tex_flat((38, 34, 32))
    car.materials["seat"] = tex_leather((122, 38, 32))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    bake_ao(car, tub, zt, zn, 0.0, 1.0, "paint_body")
    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else f"/tmp/va2/p036.png", LEN)
