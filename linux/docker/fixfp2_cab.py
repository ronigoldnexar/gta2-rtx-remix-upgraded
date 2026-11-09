#!/usr/bin/env python3
"""FIX-FP-2 cockpit probe: seated in the scene car (vr_seat's recipe), first person, the own car forced to each
model in CAB_MODELS (force_own_car_model): a still frame, one steering left, one driving. Frames t_cab_<m>_*."""
import os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, say, mark, shot, warp, hold, tap
def setkey(k, v):
    t = open(T.INI, encoding="latin-1").read()
    t = re.sub(rf"(?m)^{k}=.*$", f"{k}={v}", t) if re.search(rf"(?m)^{k}=", t) else t.replace("[devtools]", f"[devtools]\n{k}={v}", 1)
    open(T.INI, "w", encoding="latin-1").write(t)
T.Q.start("fixfp2_cab")
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
models = [int(m) for m in os.environ.get("CAB_MODELS", "40,21,36,68,11,18,56").split(",")]
T.Q.set_view("first", settle=1.0)
setkey("force_own_car_model", models[0]); time.sleep(5.0)
for m in models:
    s = D.wait_state()
    if not (s and s["driving"]):
        mark(f"not driving before model {m}: re-enter")
        for attempt in range(3):
            s = warp(164.5, 149.5, why=f"scene car again ({attempt + 1})"); s = T.get_in_scene_car()
            if s and s["driving"]: break
        T.Q.set_view("first", settle=1.0)
    setkey("force_own_car_model", m); time.sleep(4.5)
    mark(f"model {m} still"); shot(f"cab_{m:03d}_still")
    T.xdo("keydown", "Left"); time.sleep(0.5); shot(f"cab_{m:03d}_left"); T.xdo("keyup", "Left"); time.sleep(0.6)
    T.xdo("keydown", "Up"); time.sleep(0.9); shot(f"cab_{m:03d}_drive"); T.xdo("keyup", "Up")
    T.xdo("keydown", "Down"); time.sleep(1.0); T.xdo("keyup", "Down"); time.sleep(0.5)
setkey("force_own_car_model", -1)
mark("RESULT done")
open("/out/.keys_done", "w").close()
