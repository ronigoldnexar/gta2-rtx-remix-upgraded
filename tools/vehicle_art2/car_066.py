#!/usr/bin/env python3
"""066 Transporter (VEHICLE-ART-7): a two-deck car-transporter semi-trailer pulled by the 063 truck cab, read from
the GTA2 sprite: an open skeletal frame of posts and side rails, a dark grated lower deck dropping between the
wheels, an upper deck on the posts, loading ramps folded at the back, a headboard at the front. A painted
trailer: the frame is neutral paint tinted to each remap (identity.cpp). Metres, +z nose, 1 block = 5 m."""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa
from rail_kit import *  # noqa

NAME = "066_transporter"
LEN = 10.0
PAINT = (235.0, 235.0, 235.0)
SPRITE = (90, 63, 50)
HW = 1.50
Z0, Z1 = -4.95, 4.75
LOW, UP = 1.15, 2.75


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    # decks between side channels. VEHICLE-ART-20 (qav27): wooden planks along the trailer, the sprite's brown deck
    # (they were dark steel grating, which drew a near-black slab with a faint grid against the classic's planks)
    car.box("deck_wood", (-HW + 0.10, LOW - 0.04, Z0 + 0.4), (HW - 0.10, LOW, 2.6))
    car.box("deck_wood", (-HW + 0.10, UP - 0.04, Z0 + 0.1), (HW - 0.10, UP, Z1 - 0.2))
    for side in (1, -1):
        x = side * HW
        for y in (LOW, UP):
            car.box("paint_frame", (min(x, x - side * 0.12), y - 0.20, Z0 if y == UP else Z0 + 0.3), (max(x, x - side * 0.12), y + 0.02, Z1 - 0.2 if y == UP else 2.7))
        # upper guard rail
        car.box("paint_frame", (min(x, x - side * 0.06), UP + 0.42, Z0 + 0.1), (max(x, x - side * 0.06), UP + 0.50, Z1 - 0.3))
        for z in np.linspace(Z0 + 0.15, Z1 - 0.35, 8):
            car.box("paint_frame", (min(x, x - side * 0.10), LOW - 0.20, z - 0.06), (max(x, x - side * 0.10), UP + 0.50, z + 0.06))
        # diagonals between the decks
        for za, zb in zip(np.linspace(Z0 + 0.15, Z1 - 0.35, 8)[:-1], np.linspace(Z0 + 0.15, Z1 - 0.35, 8)[1:]):
            a = np.array([x - side * 0.05, LOW + 0.05, za]); b = np.array([x - side * 0.05, UP - 0.22, zb])
            car.sweep(lambda u, a=a, b=b: a[None] + u[:, None] * (b - a)[None], 0.035, 3, 6, "paint_frame")
    # headboard at the front over the hitch, gooseneck deck to the kingpin
    car.box("paint_frame", (-HW, LOW, 2.6), (HW, UP + 0.50, 2.75))
    car.box("frame_dark", (-0.9, 1.30, 2.6), (0.9, 1.50, Z1))
    # folded ramps at the back
    for side in (1, -1):
        car.box("grating", (side * 0.85 - 0.30, LOW, Z0 - 0.02), (side * 0.85 + 0.30, UP - 0.25, Z0 + 0.06))
    trailer_chassis(car, Z0, 2.6, y=LOW - 0.20)
    road_axle(car, -2.95, names=("wheel_fl", "wheel_fr"), r=0.42)
    road_axle(car, -4.00, names=("wheel_rl", "wheel_rr"), r=0.42)
    landing_legs(car, 2.2, top=1.30)
    bounds_markers(car)
    common_materials(car)
    car.materials["paint_frame"] = tex_paint(PAINT, 64, seed=66)
    car.materials["grating"] = tex_grating(128, (60, 58, 56), cells=20)
    car.materials["deck_wood"] = tex_deck_planks()
    return car


def tex_deck_planks(size=256, planks=11, seed=66):
    """VEHICLE-ART-20: weathered brown planks running along the deck (u along the trailer, v across it), a dark gap
    between planks, grain and a few darker boards; colours from the classic sprite's deck (brown 120,84,52 lit)."""
    rng = np.random.default_rng(seed)
    vv, uu = np.mgrid[0:size, 0:size] / float(size)
    k = np.floor(vv * planks).astype(int)
    f = (vv * planks) % 1.0
    tone = rng.uniform(0.78, 1.12, planks)[k]
    off = rng.uniform(0, 50, planks)[k]
    grain = 0.5 + 0.5 * np.sin(uu * 90 + off + 3.0 * np.sin(uu * 7 + off) + f * 5)
    fine = rng.normal(0, 1, (size, size)) * 0.04
    v = (0.80 + 0.14 * grain + fine) * tone
    v = np.where((f < 0.07) | (f > 0.95), 0.30, v)          # the gap between boards
    v = np.where((f >= 0.07) & (f < 0.13), v * 0.85, v)      # a worn edge
    # butt joints: boards end at staggered places along the deck
    joint = (np.abs(((uu * 3.0 + rng.uniform(0, 1, planks)[k]) % 1.0) - 0.5) > 0.493)
    v = np.where(joint, 0.35, v)
    rgb = np.array([118.0, 82.0, 52.0])[None, None] * v[..., None]
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va7/p066.png", LEN)
