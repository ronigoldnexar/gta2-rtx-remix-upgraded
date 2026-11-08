"""LIGHTBAR take: the siren light bars under Remix on the parked scene car dressed by
[devtools] force_car_model as the cop car (12), the ambulance (34) and the fire truck (17),
with force_sirens on, at night (NIGHT) and by day (14:00). Frames are cut at the marks.
With GTA2DX9_EFFECTS_LIVE=1 and VARIANTS set, the cop car at night is also seen under each
variant of the effects ini's [Sirens] section (written live; ';'-separated variants of
'|'-separated Key=value)."""
import os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, Q, say, hold, mark, view, warp

EFFECTS = "/tmp/wp/drive_c/Games/GTA2/gta2dx9_effects.ini"

def ini_set(key, val):
    t = open(T.INI, encoding="latin-1").read()
    if re.search(rf"(?m)^{key}=", t):
        t = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    else:
        t = re.sub(r"(?m)^\[devtools\]\s*$", f"[devtools]\n{key}={val}", t, count=1)
    open(T.INI, "w", encoding="latin-1").write(t)

def sirens_section(pairs):
    t = open(EFFECTS, encoding="latin-1").read() if os.path.exists(EFFECTS) else ""
    t = re.sub(r"(?ms)^\[Sirens\].*?(?=^\[|\Z)", "", t).rstrip() + "\n\n[Sirens]\n" + "".join(f"{k}={v}\n" for k, v in pairs) + "\n"
    open(EFFECTS, "w", encoding="latin-1").write(t)

def hour(h, settle=4.0):
    ini_set("set_hour_tenths", int(round(h * 10))); time.sleep(settle); mark(f"hour {h:.1f}")

def scene_car():
    v = [float(c) for c in os.environ.get("SCENE_XY", "164.5,149.5").split(",")]
    s = warp(v[0], v[1], None, why="the scene car")
    for attempt in range(3):
        last = (T.devtools_lines() or [""])[-1]
        if "no parked car" not in last: break
        s = D.wait_state()
        if not s or not s.get("parked"): break
        s = warp(round(s["px"], 1), round(s["py"], 1), None, why=f"the nearest parked car (try {attempt + 1})")
    return s

def burst(tag, n=6, gap=0.13):
    # several marks close together: the lamps alternate at the game's rate, so some catch each colour
    for i in range(n):
        mark(f"{tag}_f{i}"); time.sleep(gap)

def orbit(tag, steps=3, secs=0.45):
    time.sleep(1.0); burst(f"{tag}_0")
    for i in range(steps):
        hold("Left", secs); time.sleep(1.2); burst(f"{tag}_{i + 1}")

models = [int(m) for m in os.environ.get("CAR_MODELS", "12,34,17").split(",") if m.strip()]
night = float(os.environ.get("NIGHT", "22.5"))
mark("script start")
time.sleep(2)
hour(night)
s = scene_car(); mark(f"scene car at {s['x']:.1f},{s['y']:.1f}" if s else "scene car: none")
view("third"); time.sleep(1.0)
ini_set("force_sirens", 1)
for n in models:
    ini_set("force_car_model", n); time.sleep(2.6)
    orbit(f"night_car_{n:03d}")
variants = [v for v in os.environ.get("VARIANTS", "").split(";") if v.strip()]
if variants and models:
    ini_set("force_car_model", models[0]); time.sleep(2.6)
    for i, v in enumerate(variants):
        pairs = [tuple(p.split("=", 1)) for p in v.split("|") if "=" in p]
        sirens_section(pairs); time.sleep(2.5)
        mark(f"variant {i} {v}"); orbit(f"night_var{i}", steps=1)
    reset = os.environ.get("VARIANT_RESET", "")
    sirens_section([tuple(p.split("=", 1)) for p in reset.split("|") if "=" in p]); time.sleep(2.5)
    mark("variants reset")
hour(14.0)
for n in models:
    ini_set("force_car_model", n); time.sleep(2.6)
    orbit(f"day_car_{n:03d}")
ini_set("force_sirens", 0); ini_set("force_car_model", -1)
mark("lightbar done")
