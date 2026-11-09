#!/usr/bin/env python3
"""QB-22: the car chase framing. The PERF-2 scene car by the Downtown spawn, the
chase view, a few seconds standing (low speed), then drive3 legs at full speed for
DRIVE_SECS with a screenshot every 2 s (turns come with the route). The renderer logs
"view: framing chase" every 150 frames (car width share, FOV, speed). Marks in /out/marks.txt."""
import math, os, random, sys, threading, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, M, say, mark, shot, view, warp

DRIVE = float(os.environ.get("DRIVE_SECS", "45"))
rng = random.Random(7)
T.Q.start("qb22")
world = M.World("wil")
M.SLOW_CAP = M.FAST_CAP
mark("level")
SPOT = (164.5, 149.5, None)
from tour_lib import hold, tap
for _ in range(30):   # the scene warp needs a parked traffic car within 40 tiles: walk until one is seen
    s = D.wait_state()
    if s["parked"]: break
    hold("Up", 0.6); time.sleep(0.4)
mark(f"parked seen={bool(s['parked'])}")
for attempt in range(3):
    s = warp(*SPOT, why=f"scene car ({attempt + 1})")
    s = T.get_in_scene_car()
    if s and s["driving"]: break
t1 = time.time()
while not (s and s["driving"]) and time.time() - t1 < 60:   # no parked car: take a passing one
    s = D.wait_state()
    if s["car"] and s["cd"] < 8:
        D.goto(s["cx"], s["cy"], tol=0.9, limit=4)
        tap("Return", 0.3); time.sleep(2.5); s = D.wait_state()
        if s["driving"]: mark("in a passing car")
    else:
        hold("Up", 0.6); time.sleep(0.3)
if not (s and s["driving"]):
    mark("RESULT not driving"); sys.exit(1)
view("third")
time.sleep(4)
mark("STILL"); shot("qb22_still_1"); time.sleep(1.5); shot("qb22_still_2")
# Full throttle down the boulevard: shots as the speed builds (the log's framing line has the speed)
D.xdo("keydown", "Up"); t2 = time.time()
for k in range(1, 6):
    time.sleep(1.2); mark(f"FAST {time.time() - t2:.1f}s"); shot(f"qb22_fast_{k}")
D.xdo("keydown", "Left"); time.sleep(0.5); mark("TURN at speed"); shot("qb22_turn_1"); time.sleep(0.4); shot("qb22_turn_2"); D.xdo("keyup", "Left")
time.sleep(0.8); shot("qb22_turn_3")
D.xdo("keyup", "Up"); D.xdo("keydown", "Down"); time.sleep(1.5); D.xdo("keyup", "Down")
L = M.ped_level(s)
roads = [(x, y) for x in range(2, 254) for y in range(2, 254)
         if (k := M.node_kind(world, x, y, L)) and k[1] == 1]
stop = False
def shooter():
    n = 0
    while not stop:
        time.sleep(2.0); n += 1; mark(f"SHOT drive_{n:02d}"); shot(f"qb22_drive_{n:02d}")
mark("DRIVE start")
threading.Thread(target=shooter, daemon=True).start()
t0 = time.time()
while time.time() - t0 < DRIVE:
    s = D.wait_state()
    if not s["driving"]: break
    far = [c for c in roads if 25 <= math.hypot(c[0] - s["x"], c[1] - s["y"]) <= 50] or roads
    tx, ty = rng.choice(far); mark(f"leg to {tx},{ty}")
    M.drive3(world, tx + 0.5, ty + 0.5, tol=3.0, budget=min(40, DRIVE - (time.time() - t0) + 1), slow=True)
stop = True
mark("DRIVE end")
open("/out/.keys_done", "w").close()
