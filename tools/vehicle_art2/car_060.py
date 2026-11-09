#!/usr/bin/env python3
"""060 Train Cab (VEHICLE-ART-7): the elevated railway's power car read from the GTA2 sprite: a tan carriage body
with a streamlined rounded nose (two-pane windscreen, a headlamp, a pilot skirt) at the nose end (+z, the
sprite's lower end), a silver roof hood with louvres and a radiator grille over the cab, the crew doors near
the back (CARI door row 111 of 128), a gangway at the back where the coaches couple. A livery (identity.cpp).
Metres, +z nose, 1 block = 5 m."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa
from rail_kit import *  # noqa
import car_059 as coach

NAME = "060_train_cab"
LEN = 10.0
PAINT = (181, 161, 145)
SILVER = (196, 198, 200)


def build():
    car = Car(NAME)
    z0, z1 = -BODY_HALF, HALF_LEN - 0.05
    zs = z1 - 1.6           # where the nose starts to round

    def nose(z):
        t = np.clip((np.asarray(z, float) - zs) / (z1 - zs), 0, 1)
        return np.sqrt(np.clip(1 - t ** 2.2, 0.0, 1)) * 0.75 + 0.25 * (1 - t), 1 - 0.30 * t ** 1.6

    # body: the coach shell with the nose taper; only the crew doors at the back, a short window band behind the cab
    # the windscreen: two panes cut on the nose's own shell where it rounds over (shell v 0.56..0.80: the top of
    # the side, the cant and the roof's edge), split by a centre post; the panes stop 0.25 m short of the tip
    def screen(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        a = np.maximum(np.maximum(zs + 0.30 - u, u - (z1 - 0.32)), np.maximum(0.55 - v, v - 0.86))
        return np.maximum(a, 0.035 - np.abs(v - 0.985) * 0 - (1.0 - v)) * 3.0
    coach.coach_body(car, z0, z1, doors=(-3.15,), nose=nose, seed=60, window_band=(2.10, 2.62), end_round=0.10,
                     extra_regions=[("glass_cab", screen), ("seal", lambda u, v: screen(u, v) - 0.05)], win_z1=zs)
    # silver roof hood: a long low box with louvres, a radiator grille block at the back of the hood
    car.box("hood_silver", (-0.62, coach.CROWN - 0.04, -2.6), (0.62, coach.CROWN + 0.16, zs - 0.4))
    car.box("vent", (-0.56, coach.CROWN + 0.16, -2.2), (0.56, coach.CROWN + 0.17, -0.6))
    car.box("vent", (-0.56, coach.CROWN + 0.16, 0.2), (0.56, coach.CROWN + 0.17, 1.6))
    for side in (1, -1):
        car.box("vent", (side * 1.585 - 0.01, 1.55, -1.9), (side * 1.585 + 0.01, 2.40, -0.4))    # side louvres
    # headlamp in the nose and two marker lamps; a pilot skirt below the nose
    car.revolve([(0.20, -0.04), (0.20, 0.04), (0.17, 0.07)], (0, 1.55, z1 - 0.12), (0, -0.1, 1), 22, default="steel_bright", uv_mode="disc")
    car.revolve([(0.17, 0.06), (0.10, 0.09), (0.0, 0.10)], (0, 1.55, z1 - 0.12), (0, -0.1, 1), 22, default="lamp_head", uv_mode="disc")
    for side in (1, -1):
        car.revolve([(0.07, 0.0), (0.07, 0.03), (0.0, 0.04)], (side * 0.55, 1.30, z1 - 0.10), (0, 0, 1), 12, default="lamp_head", uv_mode="disc")
    def pilot(u, v):
        x = (np.asarray(u, float) - 0.5) * 2.6
        h = np.asarray(v, float)
        z = HALF_LEN - 0.02 - 0.55 * (x / 1.3) ** 2 - 0.35 * (1 - h)
        return x, 0.18 + 0.82 * h, z
    car.surface(pilot, 0.0, 1.0, 0.0, 1.0, 20, 4, default="frame_dark")
    car.surface(pilot, 0.0, 1.0, 0.0, 1.0, 20, 4, default="frame_dark", flip=True)
    # back end: gangway door, bellows, buffers
    car.box("door_dark", (-0.42, coach.FLOOR + 0.02, z0 - 0.012), (0.42, 2.92, z0 + 0.012))
    car.box("bellows", (-0.50, coach.FLOOR + 0.05, z0 - 0.05), (0.50, 2.95, z0))
    buffers(car, z0, -1, y=1.0)
    car.box("underbody", (-coach.HW + 0.10, coach.FLOOR - 0.34, z0 + 0.2), (coach.HW - 0.10, coach.FLOOR - 0.10, z1 - 0.6))
    car.box("frame_dark", (-1.10, coach.FLOOR - 0.80, -1.3), (1.10, coach.FLOOR - 0.34, 1.0))   # fuel tank / traction gear
    bogie(car, 2.55, markers=[("wheel_fl", "wheel_fr"), ("_a", "_b")])
    bogie(car, -2.55, markers=[("_c", "_d"), ("wheel_rl", "wheel_rr")])
    car.markers = [m for m in car.markers if not m[0].startswith("_")]
    bounds_markers(car)

    common_materials(car)
    car.materials["body"] = tex_grime(PAINT, 256, seed=60, streak=0.06)
    car.materials["roof"] = tex_grime(SILVER, 256, seed=61, streak=0.05)
    car.materials["roof_panel"] = tex_grime((214, 214, 212), 128, seed=62, streak=0.03)
    car.materials["hood_silver"] = tex_grime(SILVER, 128, seed=63, streak=0.04)
    car.materials["band_dark"] = tex_flat((58, 50, 44))
    car.materials["door_dark"] = tex_grime((130, 112, 96), 64, seed=64, streak=0.04)
    car.materials["glass"] = tex_glass(256, tint=(30, 38, 46), alpha=200)
    car.materials["glass_cab"] = tex_glass(128, tint=(24, 30, 38), alpha=235)
    car.materials["seal"] = tex_flat((24, 22, 22))
    car.materials["interior_dark"] = tex_flat((16, 15, 14))
    car.materials["bellows"] = tex_corrugated((58, 54, 50), 64, ribs=8, along_u=False)
    car.materials["vent"] = tex_louvres(128, 14, (170, 168, 164))
    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va7/p060.png", LEN)
