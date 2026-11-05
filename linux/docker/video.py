#!/usr/bin/env python3
"""The demonstration: opening, menu, area 1 in the classic view, a walk to the
street by the map, then the live switch to third person and to first person,
walking along the pavement with the traffic beside."""
import math, os, subprocess, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import gmp

say = D.say
D.start()                                   # window, focus, intro, menu, level
s = D.wait_state(40)
if not s: sys.exit(1)
D.calibrate_turn()
level = int(s["z"]) - 1
blocks, columns = gmp.load("/tmp/wp/drive_c/Games/GTA2/data/wil.gmp")
say("classic view: walking to the street")
path = gmp.route(blocks, columns, int(s["x"]), int(s["y"]), level) or []
for cx, cy in D.straighten(path)[1:-1]:     # stop on the pavement, not in the road
    s = D.goto(cx + 0.5, cy + 0.5, tol=0.5, limit=20)
# Which way along the pavement has the longest clear run?
here = (int(s["x"]), int(s["y"]))
def run_len(dx):
    n = 0
    while gmp.ground(blocks, columns, here[0] + dx * (n + 1), here[1], level) in (2, 3) and n < 14: n += 1
    return n
east, west = run_len(1), run_len(-1)
dx = 1 if east >= west else -1
far = max(east, west)
say(f"pavement runs {far} cells to the {'east' if dx > 0 else 'west'}")
# Face along it in the classic view and walk a few steps.
s = D.goto(here[0] + 0.5 + dx * min(3, far), here[1] + 0.5, tol=0.5, limit=10)
D.tap("v"); say("V: third person"); time.sleep(1.0)
s = D.goto(here[0] + 0.5 + dx * far, here[1] + 0.5, tol=0.5, limit=16)
D.hold("Up", 1.0)
D.tap("v"); say("V: first person"); time.sleep(1.0)
# turn round and walk back the way we came
s = D.goto(here[0] + 0.5 - dx * min(2, far), here[1] + 0.5, tol=0.5, limit=20)
D.hold("Left", 0.35); D.hold("Up", 2.0); D.hold("Right", 0.35); D.hold("Up", 2.0)
D.tap("v"); say("V: classic"); time.sleep(1.0)
D.hold("Up", 2.0)
say("done")
