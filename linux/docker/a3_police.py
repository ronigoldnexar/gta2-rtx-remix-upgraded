#!/usr/bin/env python3
"""ACTIONS-3D probe 2, Downtown: NPC gunfire. The wanted word is held up by
GTA2DX9_FORCE_WANTED (4: the police shoot), the player takes the machine gun
and stands at the plaza; frames every 0.4 s in third person, turning between
bursts of frames so the police around him come into view, then first person.
The log's 'ped anim:' lines (GTA2DX9_LOG_PED_FRAMES=1) carry every figure's
action, the 'shot fx' lines the muzzle effects."""
import os, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

s = Q.start("a3_police")
A.collect(166.5, 140.5, 2, "machine_gun")
T.warp(159.5, 139.5, 2, why="plaza")
Q.set_view("third", settle=1.0)
t0 = time.time(); n = 0
while time.time() - t0 < 150:
    w = A.mission()
    if n % 10 == 0: say(f"MARK police t={time.time() - t0:.0f} wanted {w[0]} health {w[1]} weapon {w[2]}")
    shot(f"p_{n:03d}"); n += 1
    time.sleep(0.25)
    if n % 8 == 0: hold("Left", 0.6)
    if n % 25 == 0: A.fire(f"p_fire_{n:03d}", secs=0.6, every=0.3)
    if n == 200: Q.set_view("first", settle=0.6)
    if w[1] == 0 or w[1] > 1000: time.sleep(2.0)   # dead: wait for the respawn
A.finish()
