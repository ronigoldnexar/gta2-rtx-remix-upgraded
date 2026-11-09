#!/usr/bin/env python3
"""VEHICLE-GLASS A/B walk-around (from VEHICLE-REVIEW vr_walk.py): every frame twice at the same spot,
[devtools] car_glass=0 then =1 (suffix _off/_on); plus a chase frame from the jacked car. Original doc: the parked scene car drawn as every CARI model (force_car_model applies to
every car but the player's), the player on foot walks round it in first person and takes a frame from the
door (flank, half a block), the front three-quarter and the rear three-quarter (1.3 blocks), and from 3.5
blocks ahead (first and third person). Frames: drv_door_NNN, drv_fq_NNN, drv_rq_NNN, drv_far1_NNN, drv_far3_NNN.
Env: MODELS (list / ranges), SCENE_XY (164.5,149.5)."""
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

def setkey(key, val):
    t = open(INI, encoding="latin-1").read()
    if re.search(rf"(?m)^{key}=", t):
        t = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    else:
        t = re.sub(r"(?m)^\[devtools\]\s*$", f"[devtools]\n{key}={val}", t, count=1)
    open(INI, "w", encoding="latin-1").write(t)

def ab(name):
    for v, tag in ((0, "off"), (1, "on")):
        setkey(AB_KEY, v); time.sleep(2.4); D.shot(f"{name}_{tag}")

AB_KEY = os.environ.get("AB_KEY", "car_glass")

def parse(spec):
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-"); out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out

def face(tx, ty, tries=8):
    s = D.wait_state()
    for _ in range(tries):
        s = D.wait_state()
        a = D.angle_to(s, tx, ty)
        if abs(a) < 0.15: break
        key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
        D.hold(key, min(abs(a) / D.rate, 0.3)); time.sleep(0.4)
    return s

D.start()
s = D.wait_state(40)
if not s: sys.exit(1)
sx, sy = [float(v) for v in os.environ.get("SCENE_XY", "164.5,149.2").split(",")[:2]]
fx_, fy_ = [float(v) for v in os.environ.get("FACE_XY", "180,149.4").split(",")[:2]]
models = parse(os.environ.get("MODELS", "0-8,10-14,16-19,21-42,44-71,82-86"))

def car_ahead(s, maxd):
    return s.get("car") and s.get("cd", 99) <= maxd and abs(D.angle_to(s, s["cx"], s["cy"])) < 1.1

def scene():
    """Stand in the lane (the traffic queues up and stops nose-on), jack the queue head, step out again:
    the car is now a driverless parked car at a known spot, and force_car_model draws it."""
    for attempt in range(4):
        T.Q.set_view("third", settle=1.0)
        s = T.warp(sx, sy, why="vehicle review walk-around (lane)")
        time.sleep(1.0)
        D.calibrate_turn()
        T.Q.set_view("first", settle=1.0)
        D.hold("Up", 0.25); time.sleep(0.4); face(fx_, fy_)
        t0 = time.time(); s = D.wait_state()
        while time.time() - t0 < 25.0 and not car_ahead(s, 2.2):
            time.sleep(0.4); s = D.wait_state()
        if not car_ahead(s, 2.2):
            say("scene: no car stopped ahead (attempt", attempt + 1, ")"); continue
        # jack it
        for _ in range(3):
            D.tap("Return", 0.3); time.sleep(3.0)
            s = D.wait_state()
            if s and s["driving"]: break
        if not (s and s["driving"]):
            say("scene: could not enter the queue head (attempt", attempt + 1, ")"); continue
        time.sleep(0.8)
        T.Q.set_view("third", settle=1.2); ab("chase"); T.Q.set_view("first", settle=0.8)
        for _ in range(3):
            D.tap("Return", 0.3); time.sleep(2.5)
            s = D.wait_state()
            if s and not s["driving"]: break
        s = D.wait_state()
        say("scene: out of the car; parked d", s.get("pd"), "car d", s.get("cd"))
        if s and s.get("parked") and s["pd"] <= 2.5: return s
        if s and s.get("car") and s["cd"] <= 2.5: return s
    return D.wait_state()

s = scene()
for n in models:
    s = D.wait_state()
    # the scene car is logged as the nearest car (cx, cy, cd, carhead), not as "parked"
    for attempt in range(3):
        if s and not s["driving"] and ((s.get("parked") and s["pd"] <= 2.5) or (s.get("car") and s["cd"] <= 2.5 and not s.get("driven"))): break
        say("re-scene: player at", round(s["x"], 1), round(s["y"], 1), "car d", s.get("cd"), "parked d", s.get("pd"))
        s = scene()
    if s.get("parked") and s["pd"] <= 2.5:
        px, py, hx, hy = s["px"], s["py"], s["phx"], s["phy"]
    else:
        px, py, hx, hy = s["cx"], s["cy"], s["chx"], s["chy"]
    if hx == 0 and hy == 0: hx, hy = 1.0, 0.0
    hl = math.hypot(hx, hy); hx, hy = hx / hl, hy / hl
    qx, qy = -hy, hx                    # perpendicular
    # the side the player stands on
    side = 1 if (s["x"] - px) * qx + (s["y"] - py) * qy >= 0 else -1
    force(n); time.sleep(2.5)
    # 1. at the door: the flank from half a block
    D.goto(px + qx * side * 0.75, py + qy * side * 0.75, tol=0.25, limit=8)
    face(px, py); time.sleep(0.3); ab(f"door_{n:03d}")
    # 2. front three-quarter, 1.3 blocks ahead and 0.8 to the side
    D.goto(px + hx * 1.3 + qx * side * 0.8, py + hy * 1.3 + qy * side * 0.8, tol=0.3, limit=10)
    face(px, py); time.sleep(0.3); ab(f"fq_{n:03d}")
    # 3. far: 3.5 blocks ahead, first and third person
    D.goto(px + hx * 3.5 + qx * side * 0.4, py + hy * 3.5 + qy * side * 0.4, tol=0.4, limit=12)
    face(px, py); time.sleep(0.3); ab(f"far1_{n:03d}")
    T.Q.set_view("third", settle=0.8); ab(f"far3_{n:03d}"); T.Q.set_view("first", settle=0.5)
    # 4. rear three-quarter from the other side (the far flank)
    D.goto(px - hx * 1.3 - qx * side * 0.8, py - hy * 1.3 - qy * side * 0.8, tol=0.3, limit=14)
    face(px, py); time.sleep(0.3); ab(f"rq_{n:03d}")
    s = D.wait_state()
    say("model", n, "car d", round(s.get("cd", 99), 2), "parked d", round(s.get("pd", 99), 2), "at", round(s["x"], 1), round(s["y"], 1))
force(-1); setkey(AB_KEY, 1)
say("done")
open("/out/.keys_done", "w").close()
