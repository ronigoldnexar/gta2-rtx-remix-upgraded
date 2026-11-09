#!/usr/bin/env python3
"""QB-37 water probe, Downtown harbour (the basin x 209-232, y 241-252, quays at
level 1, water at level 0). From the roof at (203.5, 237.5), height 4, west of the
basin: turn (small steps, read back from the log's face= word) until he faces the
basin, then first-person frames (a burst for the waves' movement) and third-person
frames from the same spot."""
import math, re, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, say, hold, shot

FACE = re.compile(r"view: player x=\S+ y=\S+ z=\S+ face=(-?[\d.]+),(-?[\d.]+)")
def face():
    m = None
    for m in FACE.finditer(Q.log_text(20000)): pass
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)

def turn_to(tx, ty, label):
    n = math.hypot(tx, ty); tx, ty = tx / n, ty / n
    for k in range(48):
        time.sleep(0.7)
        f = face()
        if f[0] * tx + f[1] * ty > 0.96: break
        hold("Left", 0.08)
    say(f"MARK {label}: face {f[0]:.2f},{f[1]:.2f} after {k} steps")

Q.start("qb37_water")
T.warp(203.5, 237.5, 5, why="roof west of the harbour")
Q.set_view("first", settle=3.0)
turn_to(1.0, 0.55, "east-south-east over the basin")
for i in range(6): shot(f"f1_{i:02d}"); time.sleep(0.4)
turn_to(0.55, 1.0, "south-south-east")
shot("f1_sse")
Q.set_view("third", settle=2.5)
shot("f3_sse")
turn_to(1.0, 0.55, "east-south-east (third)")
time.sleep(1.5)
for i in range(4): shot(f"f3_{i:02d}"); time.sleep(0.5)
turn_to(1.0, -0.2, "east, down at the channel and its quays (third)")
time.sleep(1.5)
for i in range(3): shot(f"c3_{i:02d}"); time.sleep(0.5)
time.sleep(6.0)   # a frame-times line with the basin in view
A.finish()
