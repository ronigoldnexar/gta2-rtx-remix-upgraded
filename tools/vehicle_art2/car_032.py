#!/usr/bin/env python3
"""032 Stretch Limousine (VEHICLE-ART-27): the catalog's late-1940s American stretched limousine read from the GTA2
sprite nose down (assets-src/cars/sprites_x4/032_stretch_limousine_default.png, body 32 x 111 px: 2.50 x 8.67 m;
axles +39 / -27 px; doors at 40 and 76 px): the 050 B-Type's late-1940s four-door (VEHICLE-ART-7, car_050.py: the
rounded bonnet with the chrome centre strip, the arched chrome grille with its centre bar, front wings swelling
round the wheels with the lamps in them, a long rounded roof) drawn out along its length (stretch.py): the
windscreen, the B pillar, the back light, both wheel zones and the bumpers keep their size; the rear door window
behind the front bench is drawn out (x6), a short section of bonnet ahead of the front wheels and of boot behind the rear wheels
lengthen the overhangs, and the long windows are split into three bays a side with pillars between (the sprite's
three roof panels over the long cabin). One paint all over (every remap recolours the sprite's body and roof
alike). It replaces the image-to-3D shell (a 1955 Cadillac-like limousine with flat facets). Metres, +z nose."""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import car_050 as base  # noqa
import stretch  # noqa

NAME = "032_stretch_limousine"
PAINT = base.PAINT
SPRITE = (190, 130, 90)
LEN = 111 / 64 * 5.0            # 8.67 m
HALF_W = 32 / 64 * 5.0 / 2      # 1.25 m
SX = HALF_W / base.HALF_W
# 050 stations: tail rigid, boot stretch, rear wheel zone + back light + quarter rigid, the rear door glass behind the
# front bench stretched (a stretch limousine is cut there), front bench + B pillar + front door + windscreen + front
# wheel rigid, bonnet stretch, nose rigid
ZS = [-2.5, -2.25, -2.02, -0.85, -0.32, 2.12, 2.25, 2.5]
GROW = {1: 1.45, 3: 3.0, 5: 0.53}     # segment index -> its new length (others rigid; 3 takes the rounding)


def knots():
    rigid = sum(ZS[i + 1] - ZS[i] for i in range(len(ZS) - 1) if i not in GROW)
    g = dict(GROW); g[3] += LEN - rigid - sum(g.values())     # the rear door glass takes the rounding
    zd = [-LEN / 2]
    for i in range(len(ZS) - 1):
        zd.append(zd[-1] + g.get(i, ZS[i + 1] - ZS[i]))
    zd = np.array(zd)
    assert abs(zd[-1] - LEN / 2) < 1e-6, zd[-1]
    return np.array(ZS), zd


def build():
    car = base.build()
    car.name = NAME
    zs, zd = knots()
    stretch.warp(car, zs, zd, SX)
    m = lambda z: float(np.interp(z, zs, zd))
    # the long rear window becomes three bays with pillars between
    a0, a1 = m(-0.94), m(-0.10)          # the rear door glass (050 side2)
    w = 0.09
    stretch.pillars(car, [(a0 + (a1 - a0) * k / 3 - w / 2, a0 + (a1 - a0) * k / 3 + w / 2) for k in (1, 2)])
    return car


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va27/p032.png", LEN)
