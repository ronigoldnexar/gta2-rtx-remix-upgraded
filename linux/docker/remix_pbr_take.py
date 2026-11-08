#!/usr/bin/env python3
"""Remix take for the model PBR maps (tools/remix_model_pbr.py, docs/remix-materials.md
"Model PBR maps"): close-ups by day (14:00) and at night (22:30) of the scene car dressed
by [devtools] force_car_model as each of CAR_MODELS (cop 12, taxi 56, the Schmidt sedan
36, the fire truck 17), orbited by the chase camera and seen in first person; the phone
booth and the traffic lights walked up to; the nearest pedestrian (the renderer's
'view: peds' line) from a step away; the plaza at 198,188 (lamp posts). Every step is a
line in /out/marks.txt; frames are cut from game.mp4 (remix_frames.py dump).
Run by keys_remix_pbr.sh; env as remix_showcase.py (SCENE_XY, SCENE_KEY, ...)."""
import math, os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, Q, say, hold, mark, view, warp
import a3_lib as A
try:
    import mission_lib as M
except Exception:
    M = None


def ini_set(key, val):
    t = open(T.INI, encoding="latin-1").read()
    if re.search(rf"(?m)^{key}=", t):
        t = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    else:
        t = re.sub(r"(?m)^\[devtools\]\s*$", f"[devtools]\n{key}={val}", t, count=1)
    open(T.INI, "w", encoding="latin-1").write(t)

def hour(h, settle=4.0):
    ini_set("set_hour_tenths", int(round(h * 10))); time.sleep(settle); mark(f"hour {h:.1f}")

def look(tag, key="Left", steps=2, secs=0.5):
    mark(f"{tag}_0"); time.sleep(1.0)
    for i in range(steps):
        hold(key, secs); time.sleep(1.3); mark(f"{tag}_{i + 1}")

def scene_car():
    v = [float(c) for c in os.environ.get("SCENE_XY", "164.5,149.5").split(",")]
    s = warp(v[0], v[1], int(v[2]) if len(v) > 2 else None, why="the scene car")
    for attempt in range(3):
        last = (T.devtools_lines() or [""])[-1]
        if "no parked car" not in last: break
        s = D.wait_state()
        if not s or not s.get("parked"): break
        s = warp(round(s["px"], 1), round(s["py"], 1), None, why=f"the nearest parked car (try {attempt + 1})")
    return s

def approach(tx, ty, tol, tries=16):
    """props_check.py's walk (classic view, tank keys): ends within tol, facing (tx,ty)"""
    s = D.wait_state()
    for _ in range(tries):
        d = math.hypot(tx - s["x"], ty - s["y"]); a = D.angle_to(s, tx, ty)
        if abs(a) > 0.25:
            key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
            D.hold(key, min(abs(a) / D.rate, 0.3)); time.sleep(0.35)
            if d > tol + 0.3: D.hold("Up", 0.15); time.sleep(0.4)
        elif d > tol:
            D.hold("Up", min(1.5, max(0.15, (d - tol) / 1.9))); time.sleep(0.5)
        else:
            break
        s = D.wait_state()
    return s

def cars(tag, models):
    scene_car(); view("third"); time.sleep(1.0)
    for n in models:
        ini_set("force_car_model", n); time.sleep(2.6)
        look(f"{tag}_car_{n:03d}", steps=4, secs=0.4)
        view("first"); time.sleep(1.2); mark(f"{tag}_car_{n:03d}_first"); view("third"); time.sleep(0.8)
    ini_set("force_car_model", -1); time.sleep(1.2)

def props(tag):
    Q.set_view("classic", settle=1.0); D.calibrate_turn()
    for name, (tx, ty, fx, fy, tol) in [("booth", (158.5, 137.5, 158.5, 141.5, 1.6)), ("traffic", (171.0, 117.1, 171.0, 123.0, 2.5))]:
        warp(fx, fy, 2, why=f"near the {name}"); s = approach(tx, ty, tol)
        mark(f"{tag}_{name}: at {s['x']:.2f},{s['y']:.2f}")
        view("third"); time.sleep(1.0); mark(f"{tag}_{name}_third_0")
        hold("Left", 0.3); time.sleep(1.2); mark(f"{tag}_{name}_third_1")
        view("first"); time.sleep(1.0); mark(f"{tag}_{name}_first_0")
        hold("Right", 0.4); time.sleep(1.2); mark(f"{tag}_{name}_first_1")
        Q.set_view("classic", settle=1.0)
    warp(198.0, 188.0, 2, why="the plaza (lamp posts)")
    view("third"); look(f"{tag}_plaza_third", steps=3, secs=0.6)
    view("first"); look(f"{tag}_plaza_first", steps=3, secs=0.6)

def pedestrian(tag):
    """the nearest pedestrian on foot, from a step away, in first and third person"""
    for attempt in range(4):
        s = D.wait_state(); ps = []
        if M:
            try: ps = [p for p in M.peds() if M.ped_alive(p) and p["car"] is None]
            except Exception as e: say("peds:", e)
        if ps:
            p = min(ps, key=lambda p: math.hypot(p["x"] - s["x"], p["y"] - s["y"]))
            warp(round(p["x"] + 1.4, 1), round(p["y"] + 0.4, 1), None, why=f"pedestrian {p['id']} ({p['type']})")
            Q.set_view("classic", settle=0.6)
            ps2 = [q for q in M.peds() if q["id"] == p["id"]] or [p]
            A.face(ps2[0]["x"], ps2[0]["y"])
            view("first"); time.sleep(0.8); mark(f"{tag}_ped_first_0"); time.sleep(0.8); mark(f"{tag}_ped_first_1")
            view("third"); time.sleep(0.8); mark(f"{tag}_ped_third_0"); hold("Left", 0.3); time.sleep(1.0); mark(f"{tag}_ped_third_1")
            return True
        hold("Up", 1.0); time.sleep(1.0)
    mark(f"{tag}_ped: none found"); return False

mark("script start")
models = [int(m) for m in os.environ.get("CAR_MODELS", "12,56,36,17").split(",") if m.strip()]
for tag, h in (("day", 14.0), ("night", float(os.environ.get("NIGHT", "22.5")))):
    hour(h)
    cars(tag, models)
    pedestrian(tag)
    props(tag)
mark("take done")
