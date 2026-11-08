#!/usr/bin/env python3
"""ACTIONS-3D probe 11, Downtown: the police for real. Rockets from the
kill-frenzy launcher (181.5,145.5) into the kerb traffic at 164.5,147.6 until the
wanted level rises (it reached 1 this way in a3q2), then out to the open street
at 166.5,19.5. A3_MODE=arrest: stand still and wait for a policeman to make the
arrest (frames every 0.3 s; the player's frame/state words logged).
A3_MODE=fight: keep firing now and then so the level climbs and the police shoot
back (their stance, muzzle flash and tracers)."""
import os, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

MODE = os.environ.get("A3_MODE", "arrest")
s = Q.start("a3_cops2")
A.collect(181.5, 145.5, 2, "kf_rocket")
T.warp(164.5, 147.6, 2, why="kerb")
Q.set_view("third", settle=1.0)
t0 = time.time(); n = 0
while time.time() - t0 < 70 and A.mission()[0] < (1 if MODE == "arrest" else 2):
    A.fire(f"k_fire_{n:02d}", secs=0.3, every=0.3); n += 1
    time.sleep(1.0); hold("Left", 0.35)
say("MARK wanted after rockets", A.mission()[0])
A.save_log()
if MODE == "arrest":
    T.warp(166.5, 19.5, 2, why="open street")
Q.set_view("third", settle=0.5)
t0 = time.time(); n = 0; busted = None
while time.time() - t0 < float(os.environ.get("A3_SECS", "120")):
    shot(f"k_{n:03d}"); n += 1
    time.sleep(0.15)
    if n % 20 == 0:
        w = A.mission(); say(f"MARK {MODE} t={time.time() - t0:.0f} wanted {w[0]} health {w[1]} weapon {w[2]}")
        A.save_log()
        if MODE == "fight": A.fire(f"k_fight_{n:03d}", secs=0.3, every=0.3)
        else: hold("Left", 0.2)
    if busted is None and "BUST" in Q.log_text(8000).upper():
        busted = time.time(); say("MARK busted")
    if busted and time.time() - busted > 15: break
A.finish()
