#!/usr/bin/env python3
"""FIX-ENTRY-1: Return with the SHIPPED nav_map=1 (camera-relative arrows, the DirectInput hook active on foot in the
street views), as the 5090 operator plays. F9 to a parked car's door, Return in third person, exit, Return in first
person, exit, then classic. GTA2DX9_LOG_ENTRY=1 traces every Return."""
import sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import qa_lib as Q
import tour_lib as T
from qa_lib import say

def st(tag):
    s = D.wait_state(); say("S", tag, Q.words(s) if s else None); return s
def wait_driving(secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        s = D.wait_state()
        if s and s["driving"]: return s
        time.sleep(0.3)
    return D.wait_state()
def wait_foot(secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        s = D.wait_state()
        if s and not s["driving"] and s["state"] == 7: return s
        time.sleep(0.3)
    return D.wait_state()

Q.start("ent1nav")
for view in ("third", "first", "classic"):
    Q.set_view(view, settle=1.0)
    # walk a step with the arrows first, so the camera-relative controller is engaged as in play
    D.hold("Up", 0.4); time.sleep(0.6)
    D.tap("F9", 0.3); time.sleep(3.0)
    Q.set_view(view, settle=0.5)
    st(f"{view} at the door"); Q.shot(f"{view}_door")
    T.mark(f"{view} Return 0.10"); D.tap("Return", 0.10)
    s = wait_driving(8); st(f"{view} after Return"); Q.shot(f"{view}_after")
    if not (s and s["driving"]):
        T.mark(f"{view} Return x5"); 
        for h in (0.07, 0.09, 0.12, 0.10, 0.08): D.tap("Return", h); time.sleep(0.45)
        s = wait_driving(6); st(f"{view} after x5"); Q.shot(f"{view}_after5")
    if s and s["driving"]:
        time.sleep(1.0); T.mark(f"{view} Return exit"); D.tap("Return", 0.10); wait_foot(8); st(f"{view} exited")
    time.sleep(1.0)
say("done")
