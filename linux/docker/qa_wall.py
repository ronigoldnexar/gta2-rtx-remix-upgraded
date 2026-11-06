#!/usr/bin/env python3
"""(a) Walk into a wall and keep pushing, in third and first person; turn 360 on the spot in each."""
import sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D

s = Q.start("wall")
# The spawn plaza: the building wall is just north (smaller y) of the spawn point.
for view in ("third", "first"):
    Q.set_view(view)
    # face north: the wall; goto turns toward a point north of us
    s = D.wait_state()
    s = D.goto(s["x"], s["y"] - 6.0, tol=0.2, limit=4)  # ends against the wall (never reaches)
    shot(f"wall_{view}_arrive")
    for n in range(1, 4):
        hold("Up", 2.0); shot(f"wall_{view}_push{n}")
        say(f"push {n}: {Q.words(D.wait_state())}")
    # strafe along the wall while pushing: Up + Left briefly
    D.xdo("keydown", "Up"); hold("Left", 0.6); time.sleep(0.6); D.xdo("keyup", "Up"); shot(f"wall_{view}_slide")
    Q.turn_360(view, "wall")
    # back off and look at the wall from two steps
    hold("Down", 1.2); time.sleep(0.5); shot(f"wall_{view}_backoff")
Q.set_view("classic"); shot("wall_classic_end")
Q.report("wall")
say("done")
