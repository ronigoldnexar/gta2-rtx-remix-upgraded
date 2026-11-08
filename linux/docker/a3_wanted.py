#!/usr/bin/env python3
"""ACTIONS-3D probe 6, Downtown: the police. The machine gun into the plaza
crowd and the traffic until the wanted level climbs, with the police manager's
and the player object's changed words logged (GTA2DX9_LOG_POLICE=1) to find the
field the level is made from; then hold still and let the police come: frames
every 0.3 s, turning now and then, third person then first."""
import os, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

s = Q.start("a3_wanted")
# the Downtown kill-frenzy rocket launcher (unlimited rockets) by the kerb
A.collect(181.5, 145.5, 2, "kf_rocket")
T.warp(164.5, 147.6, 2, why="kerb")
Q.set_view("third", settle=1.0)
t0 = time.time(); n = 0
while time.time() - t0 < 100 and A.mission()[0] < 3:
    A.fire(f"q_fire_{n:02d}", secs=0.3, every=0.3); n += 1
    time.sleep(1.2)
    hold("Left", 0.35)
    say(f"MARK wanted {A.mission()[0]} t={time.time() - t0:.0f}")
say("MARK police wait, wanted", A.mission()[0])
t0 = time.time(); n = 0
while time.time() - t0 < 130:
    shot(f"q_{n:03d}"); n += 1
    time.sleep(0.2)
    if n % 12 == 0: hold("Left", 0.5)
    if n % 40 == 0: A.fire(f"q_back_{n:03d}", secs=0.5, every=0.25)
    if n == 250: Q.set_view("first", settle=0.5)
    if n % 15 == 0: say(f"MARK police t={time.time() - t0:.0f} wanted {A.mission()[0]} health {A.mission()[1]}")
A.finish()
