#!/usr/bin/env python3
"""CAR-PBR take (9 Nov 2026): path-traced third-person orbits of the regenerated cars (ASSET-VEHICLES rounds 9-11:
003 004 005 019 021 022 029 052 069 071) dressed onto the scene car by [devtools] force_car_model, by day and at night.
Derived from gamerun/remix_pbr_take.py (same helpers); env CAR_MODELS (model numbers), HOURS (default 14,22.5), SCENE_XY.
Run by keys_remix_carpbr.sh; env as remix_showcase.py (SCENE_XY, SCENE_KEY, ...)."""
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

mark("script start")
models = [int(m) for m in os.environ.get("CAR_MODELS", "3,19,71,22,4").split(",") if m.strip()]
for h in [float(x) for x in os.environ.get("HOURS", "14,22.5").split(",")]:
    hour(h)
    cars("d" if h < 18 else "n", models)
mark("take done")
