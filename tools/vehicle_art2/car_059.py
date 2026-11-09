#!/usr/bin/env python3
"""059 Train (VEHICLE-ART-7): a 1950s elevated-railway passenger coach read from the GTA2 sprite: a cream roof
with a light centre panel and louvred vents at both ends, tan sides with a dark window band, two pairs of
sliding doors each side (CARI door rows), end doors with a gangway, two bogies. A livery (identity.cpp: trains
are drawn in their own colours). Metres, +z nose, 1 block = 5 m; body 0.656 x 2 blocks (3.28 x 10 m) of which
the carriage is 7.9 m (rail_kit: coupled cars overlap by 0.41 block)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa
from rail_kit import *  # noqa

NAME = "059_train"
LEN = 10.0
PAINT = (163, 144, 123)       # the sprite's tan (catalog paint_rgb)
ROOF = (206, 200, 184)        # the sprite's cream roof
HW = 1.58                     # half width over the body sides
FLOOR = 1.10
CANT = 3.02                   # where the sides meet the roof
CROWN = 3.52
DOORS = (2.95, -2.95)         # door centres (CARI door rows 26 / 102 of 128 px)


def coach_body(car, z0, z1, doors, nose=None, seed=59, window_band=(2.02, 2.68), end_round=0.22, extra_regions=(), win_z1=None):
    """the carriage shell between z0 and z1: vertical sides, a rounded cant, an elliptical roof; the windows,
    doors and the roof's panels cut as regions. nose(z) -> (width, height) scale near a streamlined end."""
    def ends(z):
        a = np.clip((z - (z1 - end_round)) / end_round, 0, 1); b = np.clip(((z0 + end_round) - z) / end_round, 0, 1)
        return np.sqrt(1 - a ** 2) * np.sqrt(1 - b ** 2)

    def shell(u, v):
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = 0.94 + 0.06 * ends(z)
        sw, sh = (nose(z) if nose else (1.0, 1.0))
        hw = HW * f * sw
        # v 0..0.12 under the sole bar, 0.12..0.62 the side, 0.62..0.72 the cant, 0.72..1 the roof to the centre
        y_side = FLOOR - 0.10 + (CANT - FLOOR + 0.10) * np.clip((v - 0.12) / 0.50, 0, 1)
        x = np.where(v < 0.12, hw * (0.80 + 0.20 * v / 0.12), hw)
        y = np.where(v < 0.12, FLOOR - 0.10, y_side)
        a = np.clip((v - 0.62) / 0.38, 0, 1) * math.pi / 2
        rx = hw * np.cos(a) ** 0.55
        ry = CANT + (CROWN - CANT) * np.sin(a) ** 0.8
        x = np.where(v > 0.62, rx, x); y = np.where(v > 0.62, ry, y)
        y = FLOOR - 0.10 + (y - (FLOOR - 0.10)) * sh
        return x, y, z

    vb = lambda y: 0.12 + (y - (FLOOR - 0.10)) / (CANT - FLOOR + 0.10) * 0.50
    v0, v1 = vb(window_band[0]), vb(window_band[1])
    pitch = 0.98
    def windows(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        k = np.round(u / pitch) * pitch
        d = np.maximum(np.abs(u - k) - 0.36, np.abs(v - (v0 + v1) / 2) - (v1 - v0) / 2) - 0.0
        for dz in doors:
            d = np.maximum(d, -(np.abs(u - dz) - 0.75))
        d = np.maximum(d, -(np.minimum(u - (z0 + 0.45), ((win_z1 if win_z1 is not None else z1) - 0.45) - u)))
        return d * 3.0
    def door_glass(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        d = np.full_like(u, 9.0)
        for dz in doors:
            for s in (-1, 1):
                d = np.minimum(d, np.maximum(np.abs(u - (dz + s * 0.31)) - 0.20, np.abs(v - (v0 + v1) / 2 - 0.01) - (v1 - v0) / 2 - 0.01))
        return d * 3.0
    def door_panel(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        d = np.full_like(u, 9.0)
        for dz in doors:
            d = np.minimum(d, np.maximum(np.abs(u - dz) - 0.66, np.maximum(vb(FLOOR + 0.02) - v, v - vb(2.86))))
        return d * 3.0
    def band(u, v):
        v = np.asarray(v, float)
        return np.maximum((np.abs(v - (v0 + v1) / 2) - (v1 - v0) / 2 - 0.035) * 3.0,
                          (np.asarray(u, float) - ((win_z1 if win_z1 is not None else z1) - 0.30)) if win_z1 is not None else -1.0)
    def seal_(u, v):
        return np.minimum(windows(u, v), door_glass(u, v)) - 0.03
    roofpanel = lambda u, v: np.maximum(0.93 - np.asarray(v), np.abs(np.asarray(u) - (z0 + z1) / 2) - ((z1 - z0) / 2 - 1.2))
    roof = lambda u, v: 0.70 - np.asarray(v)
    under = lambda u, v: np.asarray(v) - 0.12
    car.surface(shell, z0, z1, 0.0, 1.0, 120, 34, mirror=True,
                regions=list(extra_regions) + [("glass", windows), ("glass", door_glass), ("seal", seal_), ("door_dark", door_panel),
                         ("band_dark", band), ("roof_panel", roofpanel), ("roof", roof), ("underbody", under)],
                default="body", uvfn=lambda u, v: ((u - z0) / (z1 - z0), v),
                vkeys=[0.12, 0.62, v0, v1, 0.70, 0.93])
    # the ends: flat panels (the loft's ring fanned shut)
    for zend, sign in ((z0, -1), (z1, 1)):
        car.cap(shell, zend, 0.0, 1.0, 34, "body", regions=[("roof", lambda r, v: 0.70 - np.asarray(v)), ("underbody", lambda r, v: np.asarray(v) - 0.12)])
    # the inside: dark, seen through the windows; seats as a row of dark backs
    car.box("interior_dark", (-HW + 0.06, FLOOR, z0 + 0.10), (HW - 0.06, CANT - 0.02, (win_z1 if win_z1 is not None else z1) - 0.10))
    return shell


def build():
    car = Car(NAME)
    z0, z1 = -BODY_HALF, BODY_HALF
    coach_body(car, z0, z1, DOORS)
    # end doors with a window, a gangway bellows at each end, handrails
    for zend, s in ((z0, -1), (z1, 1)):
        car.box("door_dark", (-0.42, FLOOR + 0.02, zend + s * 0.0 - 0.012), (0.42, 2.92, zend + s * 0.0 + 0.012))
        car.box("glass", (-0.30, 2.10, zend + s * 0.014 - 0.006), (0.30, 2.72, zend + s * 0.014 + 0.006))
        car.box("bellows", (-0.50, FLOOR + 0.05, min(zend, zend + s * 0.05)), (0.50, 2.95, max(zend, zend + s * 0.05)))
        for side in (1, -1):
            car.sweep(lambda u, side=side, zend=zend, s=s: np.stack([side * 0.95 + 0 * u, 1.35 + 1.4 * u, zend + s * 0.07 + 0 * u], 1), 0.02, 6, 6, "steel_bright")
            # marker lamps high on the end
            car.revolve([(0.06, 0.0), (0.06, 0.02), (0.0, 0.03)], (side * 1.22, 2.92, zend), (0, 0, s), 12, default="lamp_tail" if s < 0 else "lamp_head", uv_mode="disc")
        buffers(car, zend, s, y=1.0)
    # roof: louvred vents near each end (the sprite's), a rain strip along each cant
    for zc in (z0 + 0.75, z1 - 0.75):
        car.box("vent", (-0.36, CROWN - 0.02, zc - 0.32), (0.36, CROWN + 0.10, zc + 0.32))
    for side in (1, -1):
        car.sweep(lambda u, side=side: np.stack([side * (HW - 0.02) + 0 * u, CANT + 0.03 + 0 * u, z0 + 0.1 + (z1 - z0 - 0.2) * u], 1), 0.025, 20, 6, "roof")
    # underframe: sole bars, battery and air boxes between the bogies
    car.box("underbody", (-HW + 0.10, FLOOR - 0.34, z0 + 0.2), (HW - 0.10, FLOOR - 0.10, z1 - 0.2))
    for zc, w in ((-0.9, 1.0), (0.6, 0.8)):
        car.box("frame_dark", (-1.05, FLOOR - 0.72, zc - w / 2), (1.05, FLOOR - 0.34, zc + w / 2))
    bogie(car, 2.55, markers=[("wheel_fl", "wheel_fr"), ("_f2l", "_f2r")])
    bogie(car, -2.55, markers=[("_r2l", "_r2r"), ("wheel_rl", "wheel_rr")])
    car.markers = [m for m in car.markers if not m[0].startswith("_")]
    bounds_markers(car)

    common_materials(car)
    car.materials["body"] = tex_grime(PAINT, 256, seed=59, streak=0.06)
    car.materials["roof"] = tex_grime(ROOF, 256, seed=60, streak=0.05)
    car.materials["roof_panel"] = tex_grime((226, 222, 210), 128, seed=61, streak=0.03)
    car.materials["band_dark"] = tex_flat((58, 50, 44))
    car.materials["door_dark"] = tex_grime((118, 100, 84), 64, seed=62, streak=0.04)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=200)
    car.materials["seal"] = tex_flat((24, 22, 22))
    car.materials["interior_dark"] = tex_flat((16, 15, 14))
    car.materials["bellows"] = tex_corrugated((58, 54, 50), 64, ribs=8, along_u=False)
    car.materials["vent"] = tex_louvres(128, 10, (170, 166, 156))
    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va7/p059.png", LEN)
