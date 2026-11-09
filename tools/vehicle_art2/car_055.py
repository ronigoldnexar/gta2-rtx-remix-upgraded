#!/usr/bin/env python3
"""055 Tanker (VEHICLE-ART-7): a road tank semi-trailer pulled by the 063 truck cab, read from the GTA2 sprite:
an elliptical tank on a frame with two round filler domes (the sprite's), a walkway with handrails between
them, stainless end caps and girth bands, a rear tandem axle with dual wheels, landing legs and the kingpin
plate at the front (over the cab's fifth wheel: the game overlaps the two at the hitch). A painted trailer: the
tank is neutral paint, tinted to the sprite (identity.cpp). Metres, +z nose, 1 block = 5 m."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa
from rail_kit import *  # noqa

NAME = "055_tanker"
LEN = 10.0
PAINT = (235.0, 235.0, 235.0)
SPRITE = (152, 139, 115)
AXIS_Y, RX, RY = 2.35, 1.22, 1.02
TZ0, TZ1 = -4.85, 4.70


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE

    def ends(z):
        a = np.clip((z - (TZ1 - 0.45)) / 0.45, 0, 1); b = np.clip(((TZ0 + 0.45) - z) / 0.45, 0, 1)
        return np.sqrt(1 - a ** 2) * np.sqrt(1 - b ** 2)

    def tank(u, v):
        z = np.asarray(u, float); a = np.asarray(v, float)
        f = ends(z) ** 0.45
        return RX * f * np.cos(a), AXIS_Y + RY * f * np.sin(a), z
    bands = [-3.2, -1.6, 0.0, 1.6, 3.2]
    def band(u, v):
        z = np.asarray(u, float)
        return np.min(np.stack([np.abs(z - b) for b in bands]), 0) - 0.05
    def endcap(u, v):
        z = np.asarray(u, float)
        return np.minimum(z - (TZ0 + 0.30), (TZ1 - 0.30) - z)
    car.surface(tank, TZ0, TZ1, -math.pi / 2, math.pi / 2, 90, 30, mirror=True,
                regions=[("steel_bright", endcap), ("tank_band", band)], default="paint_body",
                uvfn=lambda u, v: ((u - TZ0) / (TZ1 - TZ0), (v + math.pi / 2) / math.pi), ukeys=[b + d for b in bands for d in (-0.05, 0.05)])
    # filler domes with hatches (sprite rows 40 / 105 of 128 px -> z +1.9 / -2.6), a walkway between and rails
    for zc in (1.9, -2.6):
        car.revolve([(0.42, 0.0), (0.42, 0.16), (0.38, 0.22), (0.0, 0.26)], (0, AXIS_Y + RY - 0.06, zc), (0, 1, 0), 26, default="steel_bright", uv_mode="disc")
        car.revolve([(0.30, 0.25), (0.30, 0.29), (0.0, 0.31)], (0, AXIS_Y + RY - 0.06, zc), (0, 1, 0), 20, default="hatch", uv_mode="disc")
    car.box("grating", (-0.32, AXIS_Y + RY + 0.02, -3.3), (0.32, AXIS_Y + RY + 0.06, 2.6))
    for side in (1, -1):
        for z in np.linspace(-3.2, 2.5, 7):
            car.box("steel_bright", (side * 0.34 - 0.015, AXIS_Y + RY + 0.04, z - 0.015), (side * 0.34 + 0.015, AXIS_Y + RY + 0.55, z + 0.015))
        car.sweep(lambda u, side=side: np.stack([side * 0.34 + 0 * u, AXIS_Y + RY + 0.55 + 0 * u, -3.2 + 5.7 * u], 1), 0.02, 12, 6, "steel_bright")
    # ladder at the back
    for side in (1, -1):
        car.box("steel_bright", (side * 0.22 - 0.015, 1.4, TZ0 - 0.08), (side * 0.22 + 0.015, AXIS_Y + RY, TZ0 - 0.05))
    for y in np.arange(1.5, AXIS_Y + RY, 0.30):
        car.box("steel_bright", (-0.22, y, TZ0 - 0.08), (0.22, y + 0.025, TZ0 - 0.05))
    # cradles, chassis, axles, legs, kingpin plate, side guards with a hose tray
    for zc in (-3.9, -0.8, 2.6, 4.3):
        car.box("frame_dark", (-1.0, 1.25, zc - 0.10), (1.0, AXIS_Y - RY * 0.55, zc + 0.10))
    trailer_chassis(car, -4.95, 4.80, y=1.45)
    car.box("frame_dark", (-0.9, 1.35, 3.6), (0.9, 1.45, 4.8))
    road_axle(car, -2.90, names=("wheel_fl", "wheel_fr"))
    road_axle(car, -4.05, names=("wheel_rl", "wheel_rr"))
    landing_legs(car, 2.4, top=1.30)
    for side in (1, -1):
        car.box("frame_dark", (side * 1.15 - 0.03, 0.65, -1.9), (side * 1.15 + 0.03, 0.95, 1.9))
        car.box("frame_dark", (side * 1.15 - 0.03, 1.12, -1.9), (side * 1.15 + 0.03, 1.20, 1.9))
    bounds_markers(car)
    common_materials(car)
    car.materials["paint_body"] = tex_paint(PAINT, 512, ao_v=None, seed=55)
    car.materials["tank_band"] = tex_flat((90, 88, 84))
    car.materials["hatch"] = tex_grime((70, 70, 72), 32, seed=55)
    car.materials["grating"] = tex_grating(128)
    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va7/p055.png", LEN)
