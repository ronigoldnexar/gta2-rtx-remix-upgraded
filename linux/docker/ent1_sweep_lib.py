#!/usr/bin/env python3
"""FIX-ENTRY-1: the reach of the game's Return. F9 to a parked car's door, face along the car (as the 5090 operator
stood), walk forward/back a measured step, Return once; boarded -> out again. Then the refused spot: enter_key F8
must board there; a Return afterwards must get him out. GTA2DX9_LOG_ENTRY=1 gives the probe in the car's frame."""
import math, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import qa_lib as Q
import tour_lib as T
from qa_lib import say

def st(tag):
    s = D.wait_state(); say("S", tag, Q.words(s) if s else None, f"face={s['fx']:.2f},{s['fy']:.2f} parked d={s['pd']:.2f}" if s else ""); return s
def wait_driving(secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        s = D.wait_state()
        if s and s["driving"]: return s
        time.sleep(0.25)
    return D.wait_state()
def wait_foot(secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        s = D.wait_state()
        if s and not s["driving"] and s["state"] == 7: return s
        time.sleep(0.3)
    return D.wait_state()
def face(tx, ty, tol=0.1):
    n = math.hypot(tx, ty) or 1.0; tx, ty = tx / n, ty / n
    for i in range(30):
        time.sleep(0.15); s = D.wait_state()
        if not s or s["driving"]: return s
        a = math.atan2(s["fx"] * ty - s["fy"] * tx, s["fx"] * tx + s["fy"] * ty)
        if abs(a) < tol: return s
        key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
        D.hold(key, max(0.04, min(0.25, abs(a) / max(D.rate, 0.5) * 0.7))); time.sleep(0.35)
    return D.wait_state()

