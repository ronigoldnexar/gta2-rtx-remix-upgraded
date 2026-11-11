#!/usr/bin/env python3
"""048 Meteor (VEHICLE-ART-25): 047's body (tools/vehicle_art2/car_047.py) with the sprite's exposed engine on the rear
deck and a chrome blower through the bonnet (sprite 42 differs from 41 only there)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import car_047

NAME = "048_meteor"
SPRITE = car_047.SPRITE
PAINT = car_047.PAINT
LEN = car_047.LEN


def build():
    return car_047.build(1, NAME)


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va25/p048.png", LEN)
