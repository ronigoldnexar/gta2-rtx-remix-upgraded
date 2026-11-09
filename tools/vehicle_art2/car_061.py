#!/usr/bin/env python3
"""061 Train FB (VEHICLE-ART-7): a flat wagon read from the GTA2 sprite: a dark plank deck between deep rust-brown
side sills with stake pockets and short stanchions, an end bulkhead with a lamp at each end, two bogies,
buffers. A livery (identity.cpp). Metres, +z nose, 1 block = 5 m."""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa
from rail_kit import *  # noqa

NAME = "061_train_fb"
LEN = 10.0
PAINT = (110, 62, 40)        # the sprite's rust-brown sills and bulkheads
DECK = 1.30


def build():
    car = Car(NAME)
    z0, z1 = -BODY_HALF, BODY_HALF
    hw = 1.55
    car.box("deck", (-hw + 0.12, DECK - 0.06, z0 + 0.10), (hw - 0.12, DECK, z1 - 0.10))
    for side in (1, -1):
        car.box("body", (side * hw - (0.14 if side > 0 else 0), DECK - 0.50, z0), (side * hw + (0.0 if side > 0 else 0.14), DECK + 0.10, z1))     # side sill
        for z in np.linspace(z0 + 0.6, z1 - 0.6, 9):
            car.box("frame_dark", (side * (hw + 0.02) - 0.05, DECK - 0.30, z - 0.06), (side * (hw + 0.02) + 0.05, DECK + 0.06, z + 0.06))   # pocket
            car.box("steel_post", (side * (hw - 0.07) - 0.04, DECK + 0.10, z - 0.04), (side * (hw - 0.07) + 0.04, DECK + 0.62, z + 0.04))  # stanchion
    for zend, s in ((z0, -1), (z1, 1)):
        zi = zend - s * 0.10
        car.box("body", (-hw, DECK - 0.50, min(zend, zi)), (hw, DECK + 0.10, max(zend, zi)))          # headstock
        car.box("body", (-hw + 0.05, DECK, min(zi, zi - s * 0.10)), (hw - 0.05, DECK + 1.20, max(zi, zi - s * 0.10)))   # bulkhead
        for x in (-1.0, -0.33, 0.33, 1.0):
            car.box("frame_dark", (x - 0.05, DECK, min(zi, zi - s * 0.18)), (x + 0.05, DECK + 1.20, max(zi, zi - s * 0.18)))   # bulkhead posts
        car.box("frame_dark", (-hw + 0.05, DECK + 1.15, min(zi, zi - s * 0.18)), (hw - 0.05, DECK + 1.24, max(zi, zi - s * 0.18)))
        car.revolve([(0.09, 0.0), (0.09, 0.04), (0.0, 0.06)], (0, DECK + 1.0, zend), (0, 0, s), 14,
                    default="lamp_head" if s > 0 else "lamp_tail", uv_mode="disc")
        buffers(car, zend, s, y=1.0)
    # centre sill and brake gear under the deck
    car.box("frame_dark", (-0.30, DECK - 0.60, z0 + 0.3), (0.30, DECK - 0.06, z1 - 0.3))
    car.box("frame_dark", (-0.9, DECK - 0.75, -0.6), (0.9, DECK - 0.45, 0.6))
    bogie(car, 2.55, markers=[("wheel_fl", "wheel_fr"), ("_a", "_b")])
    bogie(car, -2.55, markers=[("_c", "_d"), ("wheel_rl", "wheel_rr")])
    car.markers = [m for m in car.markers if not m[0].startswith("_")]
    bounds_markers(car)
    common_materials(car)
    car.materials["body"] = tex_grime(PAINT, 256, seed=61, streak=0.10)
    car.materials["deck"] = tex_planks(256, 12, (78, 60, 44), seed=61)
    car.materials["steel_post"] = tex_grime((70, 50, 38), 32, seed=62)
    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va7/p061.png", LEN)
