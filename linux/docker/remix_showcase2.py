#!/usr/bin/env python3
"""REMIX-SHOWCASE take (keys_remix_showcase2.sh): the path-traced showcase frames for one
district per session. The session starts with the play preset (RTX_EXTRA=/work/rtx_play.conf.extra:
Medium, TAA-U at full resolution, no motion blur/vignette/CA); every hour pushes the play
preset plus its time-of-day overlay live ([devtools] remix_config, as remix_post.py does),
so the frames show the presets as a player gets them at a fixed hour.

  1. warm-up: the views and hours at the start spot, so Remix has compiled its shaders
     before the first kept frame (lightbar2b_a lost its night part to shader compilation)
  2. per hour (SHOW_TODS: noon, golden, dusk, night, wet) and per spot (SHOW_SPOTS):
     first person and the chase view, two headings each
  3. at night: the scene car dressed as the cop car (12), the ambulance (34) and the fire
     truck (17) with force_sirens=1, orbited (beacons); by day the cop car again (PBR paint)
  4. the showcase preset at night (vignette, motion blur while turning)
Every frame is a mark in /out/marks.txt; frames come from game.mp4 (remix_frames.py dump).
Env: SHOW_TAG (district label for the marks), SHOW_SPOTS ("name:x,y[,z];..."; "start"
needs no warp), SHOW_TODS, SHOW_CARS (12,34,17), SHOW_WARM (seconds, 240),
SHOW_SETTLE (s after a push, 6)."""
import os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, Q, say, hold, mark, view, warp

E = os.environ.get
TAG = E("SHOW_TAG", "wil")
SETTLE = float(E("SHOW_SETTLE", "6"))
HOURS = {"noon": 12.5, "golden": 17.4, "dusk": 18.35, "night": 22.5, "wet": 22.5}
for _kv in filter(None, E("SHOW_HOURS", "").split(",")):   # e.g. noon=14.0
    _k, _v = _kv.split("="); HOURS[_k] = float(_v)
SKIP = {"rtx.graphicsPreset", "rtx.upscalerType", "rtx.taauPreset", "rtx.resolutionScale",
        "rtx.sharpening.sharpness", "rtx.dlssPreset", "rtx.dlfg.enable", "rtx.isReflexEnabled",
        "rtx.faultNotice.enable", "rtx.screenshot.hotkey", "rtx.shader.blockUntilPrewarmed",
        "rtx.gpuStallTimeoutSeconds", "rtx.ignoreGameDirectionalLights", "rtx.fallbackLightMode"}

def conf(path):
    out = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1); out[k.strip()] = v.strip()
    return out

PLAY = conf("/work/rtx_play.conf.extra")
SHOW = conf("/work/rtx_post_showcase.conf.extra") or conf("/work/rtx_showcase.conf.extra")
TOD = {n: conf(f"/work/rtx_tod_{n}.conf.extra") for n in HOURS}
DEFAULTS = __import__("json").load(open("/work/remix_post_defaults.json"))
KEYS = set(PLAY) | set(SHOW) | {k for t in TOD.values() for k in t}

def state(*layers):
    d = {k: PLAY.get(k, DEFAULTS.get(k)) for k in KEYS}
    for l in layers: d.update(l)
    return {k: v for k, v in d.items() if v is not None and k not in SKIP}

CUR = state()

def ini_set(key, val):
    t = open(T.INI, encoding="latin-1").read()
    if re.search(rf"(?m)^{key}=", t):
        t = re.sub(rf"(?m)^{key}=.*$", lambda m: f"{key}={val}", t)
    else:
        t = re.sub(r"(?m)^\[devtools\]\s*$", lambda m: f"[devtools]\n{key}={val}", t, count=1)
    open(T.INI, "w", encoding="latin-1").write(t)

def push(target, tag, settle=None):
    global CUR
    diff = [f"{k}={v}" for k, v in sorted(target.items()) if CUR.get(k) != v]
    chunks, line = [], ""
    for item in diff:
        if line and len(line) + 1 + len(item) > 480: chunks.append(line); line = ""
        line = f"{line}|{item}" if line else item
    if line: chunks.append(line)
    for i, c in enumerate(chunks):
        ini_set("remix_config", c + ("|" * (i % 2))); time.sleep(1.3)
    CUR = dict(CUR, **target)
    say(f"push {tag}: {len(diff)} options in {len(chunks)} lines")
    time.sleep(SETTLE if settle is None else settle)

def hour(h, settle=3.0):
    ini_set("set_hour_tenths", int(round(h * 10))); time.sleep(settle); mark(f"hour {h:.2f}")

def look(tag, steps=1, secs=0.55):
    mark(f"{tag}_0"); time.sleep(0.4); mark(f"{tag}_0b")
    for i in range(steps):
        hold("Left", secs); time.sleep(1.6); mark(f"{tag}_{i + 1}")

def spots():
    out = []
    for item in filter(None, E("SHOW_SPOTS", "start").split(";")):
        name, _, xy = item.partition(":")
        out.append((name, [float(c) for c in xy.split(",")] if xy else None))
    return out

def goto(name, xy):
    if xy is None:
        if START: warp(START[0], START[1], None, why="back to the start")
    else:
        warp(xy[0], xy[1], int(xy[2]) if len(xy) > 2 else None, why=f"spot {name}")
    s = D.wait_state(); mark(f"spot {name} at {s['x']:.2f},{s['y']:.2f}")
    return s

def scene_car():
    """bring a parked car to the player: at SHOW_CAR_XY if set, else where he stands; if the
    renderer reports no parked car within reach, warp to the nearest parked car it logs"""
    xy = [float(c) for c in E("SHOW_CAR_XY", "").split(",") if c]
    s = D.wait_state()
    if not xy: xy = [round(s["x"], 1), round(s["y"], 1)]
    s = warp(xy[0], xy[1], int(xy[2]) if len(xy) > 2 else None, why="the scene car")
    for attempt in range(3):
        time.sleep(1.0)
        recent = " ".join((T.devtools_lines() or [""])[-3:])
        if "no parked car" not in recent: mark("scene car brought"); return s
        s = D.wait_state()
        if not s or not s.get("parked"): break
        s = warp(round(s["px"], 1), round(s["py"], 1), None, why=f"the nearest parked car (try {attempt + 1})")
    mark("scene car: none found")
    return s

def car_sweep(tag, models):
    view("third"); time.sleep(1.0)
    for n in models:
        ini_set("force_car_model", n); time.sleep(2.8)
        mark(f"{tag}_car_{n:03d}_0")
        for i in range(3):
            hold("Left", 0.45); time.sleep(0.6); mark(f"{tag}_car_{n:03d}_{i + 1}a")
            time.sleep(0.5); mark(f"{tag}_car_{n:03d}_{i + 1}b")
    ini_set("force_car_model", -1); time.sleep(1.2)

mark("script start")
s = D.wait_state(timeout=float(E("SHOW_START_WAIT", "600")))   # under Remix the first 'view: player' line can come minutes after the level
if not s: mark("no player state"); sys.exit(1)
say("start:", T.words(s))
START = (round(s["x"], 1), round(s["y"], 1))
SP = spots()
tods = [t for t in E("SHOW_TODS", "noon,golden,dusk,night,wet").split(",") if t]
cars = [int(c) for c in E("SHOW_CARS", "12,34,17").split(",") if c]

# 1. warm-up (frames marked warm_* only to see when compilation ends)
t0 = time.time(); i = 0
while time.time() - t0 < float(E("SHOW_WARM", "240")):
    tod = tods[i % len(tods)]; hour(HOURS[tod], settle=1.0)
    for v in ("first", "third"):
        view(v); hold("Left", 0.5); time.sleep(2.0); mark(f"warm_{i}_{tod}_{v}")
    if i % 2 == 1 and len(SP) > 1:
        nm, xy = SP[1 + (i // 2) % (len(SP) - 1)]; goto(nm, xy)
    elif i % 2 == 0: goto(*SP[0])
    i += 1
mark("warm end")

# 1b. sun probe: the same spot and heading, before any live push and after (12:30, 14:00, 15:30)
if E("SHOW_PROBE", "1") == "1":
    goto(*SP[0]); view("third"); hold("Left", 0.5)
    for h in (12.5, 14.0, 15.5):
        hour(h, settle=4.0); mark(f"probe_{h:g}_nopush_third")
        view("classic"); time.sleep(1.5); mark(f"probe_{h:g}_nopush_classic"); view("third")
    hour(12.5, settle=3.0); push(state(TOD["noon"]), "probe: play+noon"); mark("probe_12.5_todnoon_third")
    hour(14.0, settle=4.0); mark("probe_14_todnoon_third")
    push(state(), "probe: play only"); mark("probe_14_playonly_third")
    hour(15.5, settle=4.0); mark("probe_15.5_playonly_third")

# 2. the hours at each spot
for tod in tods:
    hour(HOURS[tod]); push(state(TOD[tod]), f"play+{tod}")
    for nm, xy in SP:
        goto(nm, xy)
        view("first"); time.sleep(1.0); look(f"s_{TAG}_{tod}_{nm}_first")
        view("third"); time.sleep(1.0); look(f"s_{TAG}_{tod}_{nm}_third")

# 3. beacons at night, paint by day
goto(*SP[0]); scene_car()
hour(HOURS["night"]); push(state(TOD["night"]), "play+night")
ini_set("force_sirens", 1); time.sleep(1.0)
car_sweep(f"s_{TAG}_night", cars)
view("first"); time.sleep(1.0); look(f"s_{TAG}_night_carfp", steps=1)
ini_set("force_sirens", 0)
hour(HOURS["noon"]); push(state(TOD["noon"]), "play+noon")
car_sweep(f"s_{TAG}_noon", cars[:1] + [int(c) for c in E("SHOW_DAYCARS", "").split(",") if c])

# 4. the showcase preset at night (vignette, motion blur while turning)
goto(*SP[-1] if len(SP) > 1 else SP[0]); hour(HOURS["night"])
push(state(SHOW, TOD["night"]), "showcase+night")
view("third"); mark(f"s_{TAG}_show_night_0")
D.xdo("keydown", "Left")
for k in range(4): time.sleep(0.35); mark(f"s_{TAG}_show_turn_{k}")
D.xdo("keyup", "Left"); time.sleep(1.5); mark(f"s_{TAG}_show_night_1")
view("first"); time.sleep(1.5); mark(f"s_{TAG}_show_night_first")
push(state(TOD["night"]), "back to play+night")
T.finish(f"remix showcase2 {TAG}")
