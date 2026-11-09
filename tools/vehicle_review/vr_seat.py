#!/usr/bin/env python3
"""VEHICLE-REVIEW: the player's own car drawn as every CARI model (force_own_car_model): a chase-camera
frame (third person, the view a player sees most while driving), a first-person frame from the seat, and
a chase frame while steering/moving. Frames: t_own3_NNN, t_own1_NNN, t_own3drive_NNN."""
import os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, say, mark, shot, warp, hold, tap

def setkey(k, v):
    t = open(T.INI, encoding="latin-1").read()
    if re.search(rf"(?m)^{k}=", t): t = re.sub(rf"(?m)^{k}=.*$", f"{k}={v}", t)
    else: t = t.replace("[devtools]", f"[devtools]\n{k}={v}", 1)
    open(T.INI, "w", encoding="latin-1").write(t)

def parse(spec):
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-"); out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out

T.Q.start("vr_seat")
for _ in range(30):
    s = D.wait_state()
    if s["parked"]: break
    hold("Up", 0.6); time.sleep(0.4)
for attempt in range(3):
    s = warp(164.5, 149.5, why=f"scene car ({attempt + 1})")
    s = T.get_in_scene_car()
    if s and s["driving"]: break
if not (s and s["driving"]):
    mark("RESULT not driving"); sys.exit(1)
WAIT = float(os.environ.get("VR_WAIT", "2.5"))
models = parse(os.environ.get("MODELS", "0-8,10-14,16-19,21-42,44-71,82-86"))
T.view("third"); time.sleep(1.0)
for m in models:
    s = D.wait_state()
    if not (s and s["driving"]):
        mark(f"not driving before model {m}: re-enter")
        for attempt in range(3):
            s = warp(164.5, 149.5, why=f"scene car again ({attempt + 1})")
            s = T.get_in_scene_car()
            if s and s["driving"]: break
        T.Q.set_view("third", settle=1.0)
    setkey("force_own_car_model", m); time.sleep(WAIT)
    mark(f"model {m} chase"); shot(f"own3_{m:03d}")
    T.Q.set_view("first", settle=0.8); time.sleep(0.4)
    mark(f"model {m} seat"); shot(f"own1_{m:03d}")
    T.Q.set_view("third", settle=0.8)
    T.xdo("keydown", "Up"); time.sleep(0.7); T.xdo("keydown", "Left"); time.sleep(0.5)
    shot(f"own3drive_{m:03d}")
    T.xdo("keyup", "Left"); T.xdo("keyup", "Up"); time.sleep(0.2)
    T.xdo("keydown", "Down"); time.sleep(1.1); T.xdo("keyup", "Down"); time.sleep(0.6)
setkey("force_own_car_model", -1)
mark("RESULT done")
open("/out/.keys_done", "w").close()
