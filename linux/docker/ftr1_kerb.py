#!/usr/bin/env python3
"""FIX-TRAFFIC-1 kerb clip: Downtown boulevard kerb (FTR_KX,FTR_KY, default 158.5,156.5), facing
along the kerb (walks FTR_KDX blocks first), third person, FTR_KSECS s of traffic (marks: clip start/end)."""
import os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import qa_lib as Q
import tour_lib as T
X = float(os.environ.get("FTR_KX", "158.5")); Y = float(os.environ.get("FTR_KY", "156.5"))
DX = float(os.environ.get("FTR_KDX", "-3")); SECS = float(os.environ.get("FTR_KSECS", "40")); WAIT = float(os.environ.get("FTR_KWAIT", "90"))
s = Q.start("ftr1_kerb")
s = T.warp(X - DX, Y, 2, why="kerb")
s = T.ensure_on_foot()
Q.set_view("third", settle=1.0)
D.goto(X, Y, tol=0.4, limit=10)
time.sleep(3.0)
Q.shot("kerb_pre")
T.mark("fill start")
time.sleep(WAIT)
T.mark("fill end")
T.mark("clip start")
t0 = time.time(); n = 0
while time.time() - t0 < SECS:
    time.sleep(2.5); Q.shot(f"kerb_{n:02d}"); n += 1
T.mark("clip end")
D.say("done")
