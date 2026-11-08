#!/usr/bin/env python3
"""ACTIONS-3D probe 4, Downtown: other people's deaths and the player's own falls.
Flamethrower on the plaza crowd (burning, burnt), the rocket launcher at the kerb
crowd (blown), a car along the pavement (run over), walking off the roof at
164,117 (level 5 down to 1: a fall from a height), walking into the pool at
210-213,138-143 (drowning). Frames every 0.2-0.25 s around each event; the log's
'ped anim: down ... lying clip N' lines say which death pose each body got."""
import os, re, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

def strip(label, secs, every=0.25):
    t0 = time.time(); n = 0
    while time.time() - t0 < secs:
        shot(f"{label}_{n:02d}"); n += 1; time.sleep(every)

def select(name):
    for i in range(8):
        if A.weapon_name() == name: return True
        tap("z", 0.2); time.sleep(0.6)
    return A.weapon_name() == name

s = Q.start("a3_mayhem")
# (run with nav_map=0: tank controls, so drive_lib.goto steers)
# 1. weapons for the crowd
A.collect(19.5, 35.5, 4, "flamethrower")
A.collect(154.5, 129.5, 2, "rocket_launcher")
T.warp(159.5, 139.5, 2, why="plaza crowd")
Q.set_view("third", settle=1.0)
say("MARK flame", select("flamethrower"))
for k in range(4):
    A.fire(f"m_flame{k}", secs=1.0, every=0.25)
    hold("Up", 0.3)
    strip(f"m_burn{k}", 2.0)
    hold("Left", 0.3)
T.warp(164.5, 147.6, 2, why="kerb crowd")
Q.set_view("third", settle=1.0)
say("MARK rocket", select("rocket_launcher"))
for k in range(3):
    A.fire(f"m_rocket{k}", secs=0.3, every=0.15)
    strip(f"m_blown{k}", 1.8, every=0.15)
    hold("Left", 0.4)
# 2. a fall from a height: off the roof at 164,117 (level 5) to the street (level 1)
T.warp(164.5, 118.5, 6, why="roof")
Q.set_view("third", settle=1.0)
say("MARK roof walk")
D.goto(164.5, 115.0, tol=0.3, limit=12)
strip("m_fall", 3.0, every=0.15)
time.sleep(4.0)
# 3. the water: from the shore at 211,137 into the pool
T.warp(211.5, 137.3, 2, why="pool shore")
Q.set_view("third", settle=1.0)
say("MARK water")
D.goto(211.5, 140.5, tol=0.3, limit=12)
strip("m_water", 5.0, every=0.2)
A.finish()
