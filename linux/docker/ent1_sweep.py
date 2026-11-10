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

Q.start("ent1sweep")
Q.set_view("third", settle=1.0)
refused = None
for step in (0.0, 0.25, 0.4, 0.55, 0.7, -0.25, -0.4, -0.55):
    D.tap("F9", 0.3); time.sleep(2.5)
    s = st(f"door step {step}")
    hx, hy = s["phx"], s["phy"]
    if s["pd"] > 1.5:   # F9 keeps the car beside him; the nearest-parked rule skips < 0.55: use the car line
        hx, hy = s["chx"], s["chy"]
    face(hx if step >= 0 else -hx, hy if step >= 0 else -hy)
    if step: D.hold("Up", abs(step)); time.sleep(0.6)
    if step < 0: face(-hx, -hy)   # walked back facing back; turn to face along the car again? no: keep the facing he has
    time.sleep(0.4)
    s = st(f"before Return step {step}"); T.mark(f"Return step {step}"); D.tap("Return", 0.10)
    s2 = wait_driving(5)
    if s2 and s2["driving"]:
        st(f"BOARDED step {step}"); time.sleep(0.8); D.tap("Return", 0.10); wait_foot(8)
    else:
        st(f"REFUSED step {step}"); Q.shot(f"refused_{step}")
        if refused is None:
            refused = step
            T.mark(f"enter_key at the refused spot {step}"); D.tap("b", 0.15)
            for i in range(4): time.sleep(0.6); Q.shot(f"f8_walk{i}")
            s3 = wait_driving(10); st("after F8"); Q.shot("f8_seated"); time.sleep(1.5); Q.shot("f8_seated2")
            if s3 and s3["driving"]:
                T.mark("Return after enter_key"); D.tap("Return", 0.10); s4 = wait_foot(8); time.sleep(0.8); st("exited after enter_key"); Q.shot("f8_exited")
    time.sleep(0.8)
say("done")
