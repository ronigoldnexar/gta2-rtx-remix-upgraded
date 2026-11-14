#!/usr/bin/env python3
"""DISTRICTS round 4 identity frames (inside a game container; keys_districts_identity.sh). For the DK_POINTS point
(tools/districts/id_plan.py: a straight road in the district, the chase camera's height): by day and at dusk, into
third person, then each drive-camera pose (GTA2DX9_REGRESS_CAM) with the facade kit on and off. Frames
/out/dk_*.png, one line per frame in /out/dk.jsonl. Shares districts_capture.py's helpers."""
import json, os, sys, time
sys.argv = sys.argv[:1]
os.environ.setdefault("DK_POINTS", "[]")
import districts_capture as C   # runs nothing at import: the capture's main loop is guarded below
D, Q, T = C.D, C.Q, C.T

DUSK = int(os.environ.get("DK_DUSK", "1820"))


def clock(tod):
    if tod == "day":
        C.ini_sec("weather", "enabled", 0)
    else:
        for k, v in (("rain_percent", 0), ("cloud_percent", 0), ("fog_percent", 0), ("wet_percent", 0), ("time_of_day", 1),
                     ("hour_hhmm", DUSK), ("clock_paused", 1), ("enabled", 1)):
            C.ini_sec("weather", k, v)
    time.sleep(3.0)


C.cam("off")
D.start()
s = D.wait_state(40)
C.say("start:", T.words(s) if s else "no state")
for p in C.POINTS:
    for tod in ("day", "dusk"):
        clock(tod)
        for attempt in range(4):     # the game's state can be briefly unreadable (a level still settling)
            D.wait_state(40)
            try:
                T.warp(p["x"], p["y"], int(p["z"]), why=f"districts identity {p['name']}")
                break
            except TypeError:
                time.sleep(3.0)
        time.sleep(2.0)
        Q.set_view("classic", settle=1.5)
        Q.set_view("third", settle=2.5)
        for pose in p["poses"]:
            C.cam(C.pose_line(p, pose)); time.sleep(3.0)
            C.ab(f"{p['name']}_{tod}_{pose['name']}")
        C.cam("off"); time.sleep(0.5)
        Q.set_view("classic", settle=1.0)
C.say("districts identity: done in", round(time.time() - C.T0), "s")
open("/out/.dk_done", "w").write("ok\n")
