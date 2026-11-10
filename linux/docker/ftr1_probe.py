#!/usr/bin/env python3
"""FIX-TRAFFIC-1 traffic census probe: third person, stand FTR_STAND s at the level start (no warp),
then the nearest parked car (F9 + Return) driven by the route planner to FTR_DEST for FTR_DRIVE s.
Census from the renderer's `ai:` lines (tools/traffic_census.py), marks in /out/marks.txt."""
import os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
import qa_lib as Q
import tour_lib as T
say, tap, hold = D.say, D.tap, D.hold
STAND = float(os.environ.get("FTR_STAND", "180"))
DRIVE = float(os.environ.get("FTR_DRIVE", "150"))
DIST = os.environ.get("FTR_DIST", "wil")
DEST = [float(v) for v in os.environ.get("FTR_DEST", "88.5,27.5").split(",")]
s = Q.start("ftr1")
Q.set_view("third", settle=2.0)
T.mark("stand start")
t0 = time.time(); n = 0
while time.time() - t0 < STAND:
    time.sleep(5)
    if n % 4 == 0: Q.shot(f"stand_{n:03d}")
    n += 1
T.mark("stand end")
if DRIVE > 0:
    world = M.World(DIST)
    for attempt in range(3):
        tap("F9", 0.3); time.sleep(1.5); tap("Return", 0.3); time.sleep(3.0)
        s = D.wait_state()
        if s and s["driving"]: break
    if s and s["driving"]:
        Q.set_view("third", settle=1.0)
        T.mark("drive start")
        t1 = time.time()
        def snap(_s, k=[0]):
            if time.time() - t1 > 10 * k[0]: Q.shot(f"drive_{k[0]:02d}"); k[0] += 1
        M.drive_to(world, DEST[0], DEST[1], tol=2.5, budget=DRIVE, view_switch=snap)
        k = 0
        while time.time() - t1 < DRIVE:   # no route (or arrived early): cruise with gentle weaving
            s = D.wait_state()
            if not s or not s["driving"]: break
            hold("Up", 2.5); snap(s); k += 1
            hold("Left" if k % 2 else "Right", 0.3)
        T.mark("drive end")
    else:
        T.mark("no car")
T.mark("end")
say("done")
