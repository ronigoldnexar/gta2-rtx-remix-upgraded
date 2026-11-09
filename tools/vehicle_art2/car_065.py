#!/usr/bin/env python3
"""065 Container (VEHICLE-ART-7): a container semi-trailer pulled by the 063 truck cab, read from the GTA2 sprite:
a ribbed steel box van whose sides carry an outside frame of posts and X braces (the sprite's), corner
castings, a roof spine, rear doors with locking bars, a skeletal chassis with a rear tandem axle, landing legs
at the front (the cab's fifth wheel sits under it: the game overlaps the two at the hitch). A painted trailer:
neutral paint tinted to each remap (identity.cpp). Metres, +z nose, 1 block = 5 m."""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa
from rail_kit import *  # noqa

NAME = "065_container"
LEN = 10.0
PAINT = (235.0, 235.0, 235.0)
SPRITE = (138, 105, 80)
HW, FLOOR, TOP = 1.55, 1.50, 3.65
Z0, Z1 = -4.95, 4.75


def brace(car, a, b, w=0.06, mat="paint_frame", side=1):
    """a flat strap from a to b on the plane x = a[0] (the side face)"""
    a = np.array(a, float); b = np.array(b, float)
    d = b - a; L = np.linalg.norm(d[1:]); t = d / max(L, 1e-9)
    n = np.array([0.0, -t[2], t[1]]) * w / 2
    def fn(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        p = a[None] + u[:, None] * d[None] + ((v - 0.5) * 2)[:, None] * n[None]
        return p[:, 0] + side * 0.0, p[:, 1], p[:, 2]
    car.surface(fn, 0, 1, 0, 1, 2, 1, default=mat, flip=side < 0)


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    # the box: ribbed sides and roof in paint, the front wall and the doors
    car.box("paint_box", (-HW + 0.03, FLOOR, Z0 + 0.05), (HW - 0.03, TOP, Z1 - 0.05))
    # outside frame on each side: top and bottom rails, posts every 1.6 m, X braces between (the sprite's pattern)
    zs = np.linspace(Z0 + 0.1, Z1 - 0.1, 7)
    for side in (1, -1):
        x = side * (HW + 0.02)
        car.box("paint_frame", (min(x, x - side * 0.06), TOP - 0.14, Z0), (max(x, x - side * 0.06), TOP + 0.02, Z1))
        car.box("paint_frame", (min(x, x - side * 0.06), FLOOR - 0.10, Z0), (max(x, x - side * 0.06), FLOOR + 0.10, Z1))
        for z in zs:
            car.box("paint_frame", (min(x, x - side * 0.06), FLOOR, z - 0.06), (max(x, x - side * 0.06), TOP, z + 0.06))
        for za, zb in zip(zs[:-1], zs[1:]):
            brace(car, (x + side * 0.005, FLOOR + 0.10, za), (x + side * 0.005, TOP - 0.14, zb), side=side)
            brace(car, (x + side * 0.005, TOP - 0.14, za), (x + side * 0.005, FLOOR + 0.10, zb), side=side)
    # roof spine and corner castings
    car.box("paint_frame", (-0.10, TOP, Z0 + 0.1), (0.10, TOP + 0.06, Z1 - 0.1))
    for x in (-HW, HW):
        for y in (FLOOR - 0.10, TOP - 0.14):
            for z in (Z0, Z1 - 0.18):
                car.box("frame_dark", (x - 0.09, y, z), (x + 0.09, y + 0.16, z + 0.18))
    # rear doors: two leaves, hinges, four locking bars with handles
    car.box("frame_dark", (-0.012, FLOOR + 0.05, Z0 + 0.03), (0.012, TOP - 0.05, Z0 + 0.06))
    for x in (-1.05, -0.45, 0.45, 1.05):
        car.sweep(lambda u, x=x: np.stack([x + 0 * u, FLOOR + 0.08 + (TOP - FLOOR - 0.16) * u, Z0 + 0.01 + 0 * u], 1), 0.025, 8, 6, "steel_bright")
        car.box("steel_bright", (x - 0.02, FLOOR + 0.95, Z0 - 0.02), (x + 0.16, FLOOR + 1.00, Z0 + 0.02))
    trailer_chassis(car, Z0, Z1, y=FLOOR - 0.10)
    road_axle(car, -2.95, names=("wheel_fl", "wheel_fr"))
    road_axle(car, -4.10, names=("wheel_rl", "wheel_rr"))
    landing_legs(car, 2.4, top=FLOOR - 0.35)
    car.box("frame_dark", (-0.9, FLOOR - 0.25, 3.6), (0.9, FLOOR - 0.12, Z1))
    bounds_markers(car)
    common_materials(car)
    car.materials["paint_box"] = tex_corrugated(PAINT, 256, ribs=40, seed=65)
    car.materials["paint_frame"] = tex_paint(PAINT, 64, seed=66)
    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va7/p065.png", LEN)
