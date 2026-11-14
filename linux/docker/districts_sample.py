#!/usr/bin/env python3
"""DISTRICTS ship QA (inside a game container; keys_districts_sample.sh): for each DK_POINTS building (qa_sample.py),
warp to its street, third person, then its poses (GTA2DX9_REGRESS_CAM) with the facade kit on and off, by day.
Frames /out/dk_<lvl>_<id>_<pose>_<on|off>.png."""
import os, sys, time
import districts_capture as C
D, Q, T = C.D, C.Q, C.T

C.cam("off")
D.start()
s = D.wait_state(40)
C.clock("day")
for p in C.POINTS:
    for attempt in range(4):
        D.wait_state(40)
        try:
            T.warp(p["x"], p["y"], int(p["z"]), why=f"districts sample {p['name']}")
            break
        except TypeError:
            time.sleep(3.0)
    time.sleep(1.5)
    if Q.current_view() == "classic":
        Q.set_view("third", settle=2.5)
    for pose in p["poses"]:
        C.cam(C.pose_line(p, pose)); time.sleep(2.5)
        C.ab(f"{p['name']}_{pose['name']}")
    C.cam("off"); time.sleep(0.3)
C.say("districts sample: done in", round(time.time() - C.T0), "s")
open("/out/.dk_done", "w").write("ok\n")
