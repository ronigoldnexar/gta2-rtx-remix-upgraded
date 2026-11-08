#!/usr/bin/env python3
"""ACTIONS-3D probe 8, Downtown: the player's own fall and drowning. Off the
roof at 160,141 (level 6, no parapet on its north side) down to the plaza at
level 2: falling from a height; then the developer warp to 225.0,241.5 (beside
the parked tank), which leaves him in the water: drowning. Frames every 0.15 s;
the player's frame/state words in the log (state 8 sub 0x13 falling, 0x14 water).
Run with nav_map=0 (tank controls: drive_lib.goto steers)."""
import os, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

def strip(label, secs, every=0.15):
    t0 = time.time(); n = 0
    while time.time() - t0 < secs:
        shot(f"{label}_{n:02d}"); n += 1; time.sleep(every)

s = Q.start("a3_falls")
for attempt in range(2):
    s = T.warp(160.5, 141.6, 7, why="roof edge 160,141")
    say("on the roof:", Q.words(s), "z", s["z"])
    Q.set_view("third", settle=1.0)
    say("MARK roof walk", attempt)
    D.goto(160.5, 139.6, tol=0.3, limit=10)
    strip(f"f_fall{attempt}", 2.5)
    s = D.wait_state(); say("after:", Q.words(s), "z", s["z"])
    if s["z"] < 4: break
time.sleep(3.0)
say("MARK water")
T.warp(225.0, 241.5, 2, why="water by the tank")
Q.set_view("third", settle=0.2)
strip("f_water", 4.0)
Q.set_view("first", settle=0.2)
strip("f_water_fp", 1.5)
time.sleep(5.0)
A.finish()
