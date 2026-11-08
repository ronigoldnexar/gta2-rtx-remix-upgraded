#!/usr/bin/env python3
"""PERF-2: a third-person drive through the current district for frame-time
measurement (GTA2DX9_FRAME_LOG). The scene warp puts a parked car on the road
beside the spawn, then drive3 takes it to road cells 25-50 blocks away, one
after another (seeded, so before/after runs take the same route choices), for
DRIVE_SECS (default 100) of driving in the chase view. Marks in /out/marks.txt."""
import math, os, random, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, M, Q, say, tap, hold, mark, shot, view, warp

district = os.environ.get("SWAP_LEVEL") or "wil"
DRIVE = float(os.environ.get("DRIVE_SECS", "100"))
rng = random.Random(int(os.environ.get("ROUTE_SEED", "7")))
T.Q.start("perf2_" + district)
world = M.World(district)
M.SLOW_CAP = M.FAST_CAP   # full speed, but drive3 keeps the car when wedged (slow=True)
mark("level")
s = D.wait_state(); say("start:", T.words(s))
SPOT = {"wil": (164.5, 149.5, None), "bil": (44.5, 108.5, 2), "ste": (108.5, 128.5, 2)}[district]
for attempt in range(3):
    s = warp(*SPOT, why=f"a parked car on the road by the spawn ({attempt + 1})")
    s = T.get_in_scene_car()
    if s and s["driving"]: break
if not (s and s["driving"]):
    mark("RESULT not driving"); sys.exit(1)
view("third")
L = M.ped_level(s)
roads = [(x, y) for x in range(2, 254) for y in range(2, 254)
         if (k := M.node_kind(world, x, y, L)) and k[1] == 1]
say(f"{len(roads)} road cells at level {L}")
mark("DRIVE start")
t0 = time.time(); legs = 0
while time.time() - t0 < DRIVE:
    s = D.wait_state()
    if not s["driving"]:
        mark("out of the car; back in"); s = warp(round(s["x"]) + 0.5, round(s["y"]) + 0.5, None, why="re-entry")
        if not s["driving"]: s = warp(*SPOT, why="re-entry at the start")
        s = T.get_in_scene_car(); view("third")
        if not (s and s["driving"]): break
        continue
    far = [c for c in roads if 25 <= math.hypot(c[0] - s["x"], c[1] - s["y"]) <= 50]
    if not far: far = roads
    tx, ty = rng.choice(far)
    legs += 1; mark(f"leg {legs} to {tx + 0.5},{ty + 0.5}")
    s = M.drive3(world, tx + 0.5, ty + 0.5, tol=3.0, budget=min(45, DRIVE - (time.time() - t0) + 1), slow=True)   # slow=True: never abandons the car in a jam; the cap is raised below
mark(f"DRIVE end after {time.time() - t0:.0f} s, {legs} legs")
view("classic")
time.sleep(2)
open("/out/.keys_done", "w").close()
