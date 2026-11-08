#!/usr/bin/env python3
"""Remix look-development take, run after remix_keys_lib.sh has the level up:
classic, the chase view and first person at the spawn; then (CAR_MODELS) a
parked car brought to SCENE_XY with the player at its door, dressed by
[devtools] force_car_model as each listed model in turn and orbited by the
chase camera, with a first-person look at each; then (DRIVE_XY) that car
driven through the chase view and the driver's seat (exposure while moving);
out, and a first-person look round. Every step is a line in /out/marks.txt;
frames are cut from game.mp4 (single x11grab frames of the Remix window are black).
Env: DISTRICT (wil|ste|bil, the map the run loaded), SCENE_XY (x,y[,level]),
CAR_MODELS (comma list), DRIVE_XY (x,y), SCENE_KEY (F11)."""
import os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, M, Q, say, tap, hold, mark, view, warp, drive

def force(n):
    t = open(T.INI, encoding="latin-1").read()
    t = re.sub(r"(?m)^force_car_model=.*$", f"force_car_model={n}", t)
    open(T.INI, "w", encoding="latin-1").write(t)

def look(tag, key="Left", steps=3, secs=0.55):
    mark(f"{tag}_0"); time.sleep(1.2)
    for i in range(steps):
        hold(key, secs); time.sleep(1.4); mark(f"{tag}_{i + 1}")
    time.sleep(0.6)

district = os.environ.get("DISTRICT", "wil")
world = M.World(district)
mark("script start")
s = D.wait_state(); say("start:", T.words(s))
time.sleep(2); mark("classic_spawn"); hold("Up", 1.5); time.sleep(2)
view("third"); look("third_spawn")
view("first"); look("first_spawn", steps=4)
scene = os.environ.get("SCENE_XY", "")
if scene:
    v = [float(c) for c in scene.split(",")]
    s = warp(v[0], v[1], int(v[2]) if len(v) > 2 else None, why="the showcase car")
    # No parked car near the point: go to the nearest parked car the renderer
    # reports and bring that one instead (up to three tries).
    for attempt in range(3):
        last = (T.devtools_lines() or [""])[-1]
        if "no parked car" not in last: break
        s = D.wait_state()
        if not s or not s.get("parked"): break
        s = warp(round(s["px"], 1), round(s["py"], 1), None, why=f"the nearest parked car (try {attempt + 1})")
    view("third"); time.sleep(1.5)
    for n in [int(m) for m in os.environ.get("CAR_MODELS", "").split(",") if m.strip()]:
        force(n); time.sleep(2.6)
        look(f"car_{n:03d}_third", steps=4, secs=0.45)
        Q.set_view("first", settle=1.0); mark(f"car_{n:03d}_first"); time.sleep(1.2)
        Q.set_view("third", settle=1.0)
    if os.environ.get("CAR_MODELS"):
        force(-1); time.sleep(1.5)
    drive_xy = os.environ.get("DRIVE_XY", "")
    if drive_xy:
        s = T.get_in_scene_car()
        if s and s["driving"]:
            dx, dy = [float(c) for c in drive_xy.split(",")[:2]]
            s = drive(world, dx, dy, "the showcase drive", budget=int(os.environ.get("DRIVE_BUDGET", "80")), fp_after=25.0)
            mark("drive_end"); time.sleep(2)
            T.leave_car()
view("first"); look("first_end", steps=4)
view("third"); look("third_end")
T.finish("remix showcase")
