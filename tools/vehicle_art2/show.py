#!/usr/bin/env python3
"""VEHICLE-ART-2 showcase: the player's own car drawn as model N (force_own_car_model) in a forced paint
(force_car_paint, the sprite's default remap), parked on the carriageway, filmed from fixed poses with the
regression camera (GTA2DX9_REGRESS_CAM): front 3/4, side, rear 3/4, eye height, close front, high, then the
game's own chase camera and the seat. Frames: show_<pose>_NNN.png.
Env: MODELS="36:117,88,77;8:179,137,105;56" (model[:paint]), VA2_CAM (container path of the camera file)."""
import os, re, sys, time, math, subprocess
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, say, mark, shot, warp, hold, tap

CAM = os.environ.get("VA2_CAM", "/tmp/va2_cam.txt")


def setkey(k, v):
    t = open(T.INI, encoding="latin-1").read()
    if re.search(rf"(?m)^{k}=", t): t = re.sub(rf"(?m)^{k}=.*$", f"{k}={v}", t)
    else: t = t.replace("[devtools]", f"[devtools]\n{k}={v}", 1)
    open(T.INI, "w", encoding="latin-1").write(t)


def cam(line):
    with open(CAM + ".tmp", "w") as f: f.write(line + "\n")
    os.replace(CAM + ".tmp", CAM)


T.Q.start("va2_show")
s = D.wait_state(40)
s = warp(164.5, 149.2, why="va2 showcase spot")
time.sleep(1.0)
T.Q.set_view("third", settle=1.5)
POSES = [("front34", 1.05, 0.75, 0.36), ("side", 0.0, 1.25, 0.16), ("rear34", -1.05, -0.70, 0.40),
         ("eye", 0.95, -0.55, 0.42), ("close", 0.62, 0.30, 0.20), ("high", -0.15, 0.10, 1.55),
         ("chase", -1.35, 0.0, 0.70)]
spec = os.environ.get("MODELS", "36:117,88,77")
for item in spec.split(";"):
    m, _, paint = item.partition(":")
    m = int(m)
    setkey("force_car_model", m)
    setkey("force_car_paint", paint)
    time.sleep(2.5)
    # the nearest car in the queue that comes at the spot from the east (heading west)
    t0 = time.time()
    while time.time() - t0 < 25:
        s = D.wait_state()
        if s and s["cd"] < 3.5 and s["cx"] > s["x"] + 0.6: break
        time.sleep(0.3)
    cx, cy, cz = s["cx"], s["cy"], s["z"]
    fx, fy = -1.0, 0.0
    rx, ry = -fy, fx
    say("model", m, "car at", round(cx, 2), round(cy, 2), "d", round(s["cd"], 2))
    for name, f, r, u in POSES:
        ex, ey = cx + fx * f + rx * r, cy + fy * f + ry * r
        cam(f"cam {ex:.3f} {ey:.3f} {cz + u:.3f} {cx:.3f} {cy:.3f} {cz + 0.10:.3f} 50")
        time.sleep(0.9)
        mark(f"model {m} {name}"); shot(f"show_{name}_{m:03d}")
    cam("")
    time.sleep(0.5)
setkey("force_car_model", -1)
setkey("force_car_paint", "")
mark("RESULT done")
open("/out/.keys_done", "w").close()
