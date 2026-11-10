#!/usr/bin/env python3
"""FIX-COCKPIT-BODY probe: seated in the scene car (vr_seat recipe), first person, own car forced to each model in
CAB_MODELS; per model: drive, hold Left (with Up) 1.2 s, straight, hold Right 1.2 s, then a full-lock left from a crawl.
Marks per phase in /out/marks.txt (epoch). Wheel turn per frame in the log with GTA2DX9_FP_ARM_LOG=1.
DASHCAM=1: also a cockpit -> dashcam -> drive -> cockpit sequence at the end (key DASHKEY, default 'c')."""
import os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, say, mark, shot, warp, hold, tap
def setkey(k, v):
    t = open(T.INI, encoding="latin-1").read()
    t = re.sub(rf"(?m)^{k}=.*$", f"{k}={v}", t) if re.search(rf"(?m)^{k}=", t) else t.replace("[devtools]", f"[devtools]\n{k}={v}", 1)
    open(T.INI, "w", encoding="latin-1").write(t)
def down(k): T.xdo("keydown", k)
def up(k): T.xdo("keyup", k)
def seat():
    for attempt in range(3):
        s = warp(164.5, 149.5, why=f"scene car ({attempt + 1})")
        s = T.get_in_scene_car()
        if s and s["driving"]:
            # out and in again through the door: seated by the boarding (the warp's own seat can lose its figure)
            tap("Return", 0.3); time.sleep(3.5)
            s = T.get_in_scene_car()
            if s and s["driving"]: time.sleep(1.5); return s
    return s
def look_down(name):
    # the camera takes at most 25 counts a frame, 0.07 degrees each at 1280 wide: ~55 degrees down
    for _ in range(200): T.xdo("mousemove_relative", "--", "0", "12"); time.sleep(0.02)
    time.sleep(0.1); shot(name)
    for _ in range(200): T.xdo("mousemove_relative", "--", "0", "-12"); time.sleep(0.02)
    time.sleep(0.4)
T.Q.start("cb2grip")
for _ in range(30):
    s = D.wait_state()
    if s["parked"]: break
    hold("Up", 0.6); time.sleep(0.4)
models = [int(m) for m in os.environ.get("CAB_MODELS", "13,68,21").split(",") if m]
SWEEP = os.environ.get("SWEEP", "1") == "1"
for i, m in enumerate(models):
    if m >= 0: setkey("force_own_car_model", m); time.sleep(1.0)
    s = seat()
    if not (s and s["driving"]):
        mark(f"model {m}: not driving"); continue
    T.Q.set_view("first", settle=1.0); time.sleep(3.0)
    mark(f"model {m} still"); shot(f"g_{m:03d}_still")
    if SWEEP and i == 0:
        for k, v in (("fp_hand_scale", 0), ("fp_hand_scale", 100), ("fp_grip_tilt", 45), ("fp_grip_tilt", 90), ("fp_grip_tilt", 75),
                     ("fp_grip_deg", 17), ("fp_grip_deg", 45), ("fp_grip_deg", 30), ("fp_grip_curl", 65), ("fp_grip_curl", 95), ("fp_grip_curl", 80)):
            setkey(k, v); time.sleep(2.5); mark(f"sweep {k}={v}"); shot(f"g_{m:03d}_{k}_{v}")
    down("Up"); time.sleep(1.0)
    mark(f"model {m} left"); down("Left"); time.sleep(0.35); shot(f"g_{m:03d}_left_a"); time.sleep(0.35); shot(f"g_{m:03d}_left_b"); time.sleep(0.5); up("Left")
    mark(f"model {m} straight"); time.sleep(0.8); shot(f"g_{m:03d}_straight")
    mark(f"model {m} right"); down("Right"); time.sleep(0.35); shot(f"g_{m:03d}_right_a"); time.sleep(0.35); shot(f"g_{m:03d}_right_b"); time.sleep(0.5); up("Right")
    up("Up"); time.sleep(0.3)
    down("Down"); time.sleep(1.0); up("Down"); time.sleep(0.5)
setkey("force_own_car_model", -1)
mark("RESULT done")
open("/out/.keys_done", "w").close()
