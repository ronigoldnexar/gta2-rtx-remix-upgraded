#!/usr/bin/env python3
"""033 Sports Limousine (VEHICLE-ART-27): the catalog's late-1930s streamlined limousine read from the GTA2 sprite
nose down (assets-src/cars/sprites_x4/033_sports_limousine_default.png, body 32 x 109 px: 2.50 x 8.52 m; axles
+35 / -35 px; doors at 36 and 52 px): a long pointed bonnet with a chrome centre strip between pontoon front wings,
a long cabin with its roof in two panels, the back light over the rear wheels and a tapering tail. The 070 Z-Type's
late-1930s streamliner (VEHICLE-ART-21, car_070.py: the V prow with its chrome strip ending in the arrow ornament,
the faired lamps, the fastback) drawn out along its length (stretch.py): the prow, the windscreen, both wheel zones,
the rear quarter and back light and the bumpers keep their size; the nose ahead of the front wheels, the bonnet
behind them, the door glass behind the front bench and the tail lengthen, and the long door window is split into four
bays a side with pillars between. One paint all over. It replaces the image-to-3D shell (a 1960s Continental-like sedan:
the wrong era for the sprite's streamliner). Metres, +z nose."""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import car_070 as base  # noqa
import stretch  # noqa

NAME = "033_sports_limousine"
PAINT = base.PAINT
SPRITE = (190, 120, 80)
LEN = 109 / 64 * 5.0            # 8.52 m
HALF_W = 32 / 64 * 5.0 / 2      # 1.25 m
SX = HALF_W / base.HALF_W
# 070 stations: tail rigid, tail stretch, rear wheel zone + back light + quarter rigid, the door glass behind the front
# bench stretched, front bench + A pillar + windscreen rigid, bonnet stretch, front wheel zone rigid, nose stretch,
# prow rigid
ZS = [-2.5, -2.30, -1.95, -0.48, -0.36, 0.65, 1.30, 2.24, 2.32, 2.5]
GROW = {1: 0.78, 3: 2.4, 5: 1.08, 7: 0.92}


def knots():
    rigid = sum(ZS[i + 1] - ZS[i] for i in range(len(ZS) - 1) if i not in GROW)
    g = dict(GROW); g[3] += LEN - rigid - sum(g.values())
    zd = [-LEN / 2]
    for i in range(len(ZS) - 1):
        zd.append(zd[-1] + g.get(i, ZS[i + 1] - ZS[i]))
    return np.array(ZS), np.array(zd)


def build():
    car = base.build()
    car.name = NAME
    zs, zd = knots()
    stretch.warp(car, zs, zd, SX)
    m = lambda z: float(np.interp(z, zs, zd))
    a0, a1 = m(-0.48), m(-0.36)          # the stretched part of the door glass (070 side1) behind the front bench
    w = 0.09
    stretch.pillars(car, [(a0 + (a1 - a0) * k / 3 - w / 2, a0 + (a1 - a0) * k / 3 + w / 2) for k in (1, 2, 3)])
    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va27/p033.png", LEN)
