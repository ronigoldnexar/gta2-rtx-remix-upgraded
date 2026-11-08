#!/usr/bin/env python3
"""ACTIONS-3D probe 3, Downtown: an arrest. Wanted held at 1 (GTA2DX9_FORCE_WANTED=1),
bare hands, standing still at the plaza, so a policeman walks up and busts him;
a frame every 0.5 s (third person, a turn now and then), the player's frame and
state words logged (GTA2DX9_LOG_PED_FRAMES=1): the hands-up/cuffed frames."""
import os, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

s = Q.start("a3_arrest")
T.warp(159.5, 139.5, 2, why="plaza")
Q.set_view("third", settle=1.0)
t0 = time.time(); n = 0; busted_at = None
while time.time() - t0 < 200:
    w = A.mission()
    txt = Q.log_text(20000)
    if n % 10 == 0: say(f"MARK arrest t={time.time() - t0:.0f} wanted {w[0]} health {w[1]}")
    shot(f"a_{n:03d}"); n += 1
    time.sleep(0.3)
    if n % 30 == 0: hold("Left", 0.5)
    if busted_at is None and "BUST" in txt.upper():
        busted_at = time.time(); say("MARK busted seen")
    if busted_at and time.time() - busted_at > 25: break
A.finish()
