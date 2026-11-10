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
T.Q.start("cbody")
for _ in range(30):
    s = D.wait_state()
    if s["parked"]: break
    hold("Up", 0.6); time.sleep(0.4)
models = [int(m) for m in os.environ.get("CAB_MODELS", "13,68,21").split(",") if m]
for i, m in enumerate(models):
    # the own car's model is forced before he gets in (a model swapped under a seated driver is not play)
    if m >= 0: setkey("force_own_car_model", m); time.sleep(1.0)
    s = seat()
    if not (s and s["driving"]):
        mark(f"model {m}: not driving"); continue
    T.Q.set_view("first", settle=1.0); time.sleep(3.0)
    mark(f"model {m} still"); shot(f"cb_{m:03d}_still")
    down("Up"); time.sleep(1.0)
    mark(f"model {m} left"); down("Left"); time.sleep(0.6); shot(f"cb_{m:03d}_left"); time.sleep(0.6); up("Left")
    mark(f"model {m} straight"); time.sleep(0.6)
    mark(f"model {m} right"); down("Right"); time.sleep(0.6); shot(f"cb_{m:03d}_right"); time.sleep(0.6); up("Right")
    up("Up"); time.sleep(0.3)
    mark(f"model {m} lock"); down("Up"); down("Left"); time.sleep(1.6); shot(f"cb_{m:03d}_lock"); time.sleep(0.6); up("Left"); up("Up")
    mark(f"model {m} look-down"); time.sleep(1.0); look_down(f"cb_{m:03d}_down")
    down("Down"); time.sleep(1.0); up("Down"); time.sleep(0.5)
if os.environ.get("DASHCAM") == "1":
    key = os.environ.get("DASHKEY", "c")
    s = D.wait_state()
    if not (s and s["driving"]): s = seat()
    T.Q.set_view("first", settle=1.0)
    mark("dash cockpit drive"); down("Up"); time.sleep(1.5); shot("dc_cockpit")
    mark("dash switch to dashcam"); tap(key, 0.15); time.sleep(0.8)
    down("Left"); time.sleep(0.8); up("Left"); shot("dc_dashcam"); time.sleep(0.8)
    down("Right"); time.sleep(0.8); up("Right"); up("Up")
    mark("dash V cycle"); T.Q.set_view("third", settle=1.0); T.Q.set_view("first", settle=1.0); shot("dc_after_cycle")
    mark("dash get out/in"); tap("Return", 0.3); time.sleep(3.5); s = T.get_in_scene_car(); time.sleep(1.5)
    if not (s and s["driving"]): mark("dash re-entry failed: seat again"); seat(); T.Q.set_view("first", settle=1.0)
    shot("dc_after_reentry")
    mark("dash switch back to cockpit"); down("Up"); time.sleep(0.6); tap(key, 0.15); time.sleep(1.2); shot("dc_back"); up("Up")
setkey("force_own_car_model", -1)
mark("RESULT done")
open("/out/.keys_done", "w").close()
