#!/usr/bin/env python3
"""VEHICLE-REVIEW: every car model in traffic from the chase camera and from eye height.
Copy of car_models_close.py with a nearer close frame (cd < 1.5) and a second eye-height frame.
Frames per model: vr_far_NNN (car within 4 blocks), vr_close_NNN (within 1.5), vr_fp_NNN (first person on foot),
vr_fp2_NNN (a second first-person frame 1.2 s later: the car has moved, another angle)."""
import os, re, sys, time, math
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
T.warp(x, y, why="vehicle review sheet")
time.sleep(1.0)
s = D.wait_state()
if math.hypot(s["x"] - x, s["y"] - y) > 2.5:
    T.mark(f"RESULT warp did not land: at {s['x']:.1f},{s['y']:.1f}, wanted {x},{y}; no frames taken")
    sys.exit(2)
T.Q.set_view("third", settle=1.5)
D.calibrate_turn()
s = D.wait_state()
fx_, fy_ = [float(v) for v in os.environ.get("FACE_XY", "150,151.2").split(",")[:2]]
def face():
    D.hold("Up", 0.25); time.sleep(0.5)
    for _ in range(8):
        s = D.wait_state()
        a = D.angle_to(s, fx_, fy_)
        if abs(a) < 0.2: break
        key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
        D.hold(key, min(abs(a) / D.rate, 0.3)); time.sleep(0.45)
face()
s = D.wait_state()
say("viewpoint", round(s["x"], 2), round(s["y"], 2), "facing", fx_, fy_, "angle", round(D.angle_to(s, fx_, fy_), 2))
time.sleep(2.0)

def car_ahead(s, maxd=6.0):
    if s.get("cd", 99) > maxd: return False
    return abs(D.angle_to(s, s["cx"], s["cy"])) < 1.1

s = D.wait_state(); ref = (s["x"], s["y"])
for n in models:
    s = D.wait_state()
    if math.hypot(s["x"] - x, s["y"] - y) > 2.5:
        say("re-warp: player at", round(s["x"], 1), round(s["y"], 1))
        T.warp(x, y, why="vehicle review (after a respawn)"); time.sleep(1.0)
        s = D.wait_state()
        if math.hypot(s["x"] - x, s["y"] - y) > 2.5:
            T.mark(f"RESULT re-warp did not land before model {n}: at {s['x']:.1f},{s['y']:.1f}"); sys.exit(2)
        T.Q.set_view("third", settle=1.5); face()
        s = D.wait_state(); ref = (s["x"], s["y"])
    elif math.hypot(s["x"] - ref[0], s["y"] - ref[1]) > 1.0 or abs(D.angle_to(s, fx_, fy_)) > 0.4:
        say("re-face: player at", round(s["x"], 1), round(s["y"], 1), "angle", round(D.angle_to(s, fx_, fy_), 2))
        T.warp(x, y, why="vehicle review (re-face)"); time.sleep(1.0)
        T.Q.set_view("third", settle=1.5); face()
        s = D.wait_state(); ref = (s["x"], s["y"])
    force(n); time.sleep(2.4)
    t0 = time.time()
    while time.time() - t0 < 7.0:
        s = D.wait_state()
        if car_ahead(s, 4.0): break
        time.sleep(0.4)
    D.shot(f"far_{n:03d}")
    t1 = time.time()
    while time.time() - t1 < 9.0:
        s = D.wait_state()
        if car_ahead(s, 1.5): break
        time.sleep(0.2)
    D.shot(f"close_{n:03d}")
    T.Q.set_view("first", settle=0.7); time.sleep(0.3)
    D.shot(f"fp_{n:03d}")
    time.sleep(1.2)
    D.shot(f"fp2_{n:03d}")
    T.Q.set_view("third", settle=0.7)
    say("model", n, "car d", round(s.get("cd", 99), 1))
force(-1)
say("done")
