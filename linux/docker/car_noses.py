#!/usr/bin/env python3
"""Stand at the kerb of a busy road in third person for a while, so the
renderer's car-nose log (GTA2DX9_LOG_CAR_NOSES=1) sees the traffic; then
tools/check_car_noses.py says which models are drawn tail-first.
Env: NOSE_XY=x,y (the scene_xy to warp to, default the Downtown carriageway),
NOSE_SECS (watch time), SCENE_KEY (devtools scene key, F11)."""
import os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import tour_lib as T

say = D.say
D.start()
s = D.wait_state(40)
if not s: sys.exit(1)
xy = os.environ.get("NOSE_XY", "164.5,147.5")
x, y = [float(v) for v in xy.split(",")[:2]]
secs = float(os.environ.get("NOSE_SECS", "360"))
T.Q.set_view("third", settle=1.5)
T.warp(x, y, why="car-nose watch")
time.sleep(1.0)
T.Q.set_view("third", settle=1.5)
t0 = time.time(); k = 0
while time.time() - t0 < secs:
    # face along the road one way, then the other, so cars come at the camera
    # from both directions; a short step keeps the game spawning traffic.
    D.hold("Left", 0.55); time.sleep(20)
    D.hold("Left", 0.55); time.sleep(20)
    D.hold("Up", 0.4); time.sleep(5)
    k += 1
    if k % 2 == 0: D.shot(f"nose_{k:02d}")
say("done")
