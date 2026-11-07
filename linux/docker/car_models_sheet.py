#!/usr/bin/env python3
"""Every car model from the chase camera: the developer scene warp puts the
player at the door of a parked road car; he steps back; then [devtools]
force_car_model is stepped through the model numbers (the renderer re-reads it
once a second) and a frame is taken of the same parked car wearing each model.
Env: MODELS (comma list or a-b, default 0-71 and 82-86 minus the gaps),
SCENE_KEY (F11), SHEET_XY (scene_xy, default the Downtown carriageway)."""
import os, re, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import tour_lib as T

say = D.say
INI = T.INI

def force(n):
    t = open(INI, encoding="latin-1").read()
    t = re.sub(r"(?m)^force_car_model=.*$", f"force_car_model={n}", t)
    open(INI, "w", encoding="latin-1").write(t)

def parse(spec):
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-"); out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out

D.start()
s = D.wait_state(40)
if not s: sys.exit(1)
x, y = [float(v) for v in os.environ.get("SHEET_XY", "164.5,147.5").split(",")[:2]]
models = parse(os.environ.get("MODELS", "0-8,10-14,16-19,21-42,44-71,82-86"))
T.Q.set_view("third", settle=1.5)
T.warp(x, y, why="car model sheet")        # with a car: the player lands at its door
time.sleep(1.0)
T.Q.set_view("third", settle=1.5)
# An exact warp (GTA2DX9_SCENE_NO_CAR=1) onto the south kerb of the carriageway,
# facing along it, so passing traffic comes toward the chase camera and goes by
# a block or two away. Each model's frame waits for a car close ahead.
D.calibrate_turn()
s = D.wait_state()
import math
fx_, fy_ = [float(v) for v in os.environ.get("FACE_XY", "150,151.2").split(",")[:2]]
D.hold("Up", 0.25); time.sleep(0.5)
for _ in range(8):
    s = D.wait_state()
    a = D.angle_to(s, fx_, fy_)
    if abs(a) < 0.2: break
    key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
    D.hold(key, min(abs(a) / D.rate, 0.3)); time.sleep(0.45)
s = D.wait_state()
say("viewpoint", round(s["x"], 2), round(s["y"], 2), "facing", fx_, fy_, "angle", round(D.angle_to(s, fx_, fy_), 2))
time.sleep(2.0)

def car_ahead(s, maxd=6.0):
    if s.get("cd", 99) > maxd: return False
    return abs(D.angle_to(s, s["cx"], s["cy"])) < 1.1

# Standing in the lane, the traffic queues up behind him: a car stopped a couple
# of blocks away, nose toward him. He faces it a little off its bearing so the
# chase camera is not looking straight through him at it.
for n in models:
    force(n); time.sleep(2.4)
    t0 = time.time()
    while time.time() - t0 < 7.0:
        s = D.wait_state()
        if car_ahead(s, 4.0): break
        time.sleep(0.4)
    D.shot(f"model_{n:03d}")
    T.Q.set_view("first", settle=0.8); time.sleep(0.4)
    D.shot(f"fp_model_{n:03d}")
    T.Q.set_view("third", settle=0.8)
    say("model", n, "car d", round(s.get("cd", 99), 1))
force(-1)
say("done")
