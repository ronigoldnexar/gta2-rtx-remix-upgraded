#!/usr/bin/env python3
"""ACTIONS-3D probe 9: the police come to the player. Wanted words held by the
GTA2DX9_POKE probe (see live_geometry.cpp ActionProbes), the player stands in
the open street at 166.5,19.5 (Downtown, north) and is photographed every
0.4 s in third person, a turn every few seconds; the log's 'ped anim: object'
lines carry the policemen's actions (aim, carry), 'player frame' his own
(hands up, arrest), 'police words' the manager."""
import os, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

s = Q.start("a3_cops")
if os.environ.get("A3_ARMED") == "1":
    A.collect(166.5, 140.5, 2, "machine_gun")
T.warp(166.5, 19.5, 2, why="open street")
Q.set_view("third", settle=1.0)
t0 = time.time(); n = 0; busted = None
while time.time() - t0 < float(os.environ.get("A3_SECS", "140")):
    shot(f"c_{n:03d}"); n += 1
    time.sleep(0.25)
    if n % 15 == 0:
        w = A.mission(); say(f"MARK cops t={time.time() - t0:.0f} wanted {w[0]} health {w[1]}")
        hold("Left", 0.3)
    if busted is None and "BUST" in Q.log_text(8000).upper():
        busted = time.time(); say("MARK busted")
    if busted and time.time() - busted > 20: break
A.finish()
