#!/usr/bin/env python3
"""REMIX-POST take: the post stack and the time-of-day presets, before and after, at
the same three spots, in one Remix session (run after remix_keys_lib.sh has the level
up: Downtown, clock paused). The session starts with the BEFORE config (RTX_EXTRA);
each step pushes a whole option set live through [devtools] remix_config (512 chars
a line, so in chunks), waits for the exposure to settle, and marks a frame.
Frames: remix_frames.py dump out/<run> <secs> <dir> <regex>; sheet: remix_post_sheet.py.
Env:
  POST_BEFORE   conf file with the session's start config        (/work/rtx_post_before.conf.extra)
  POST_PLAY     the play preset                                    (/work/rtx_play.conf.extra)
  POST_SHOW     the showcase preset                                (/work/rtx_showcase.conf.extra)
  POST_TOD_DIR  folder of rtx_tod_<name>.conf.extra                (/work)
  POST_DEFAULTS json {option: default} for keys the before config leaves unset
  POST_SPOTS    spot names to visit (street,plaza,spawn)
  POST_TODS     time-of-day presets (noon,golden,dusk,night,wet)
  POST_PARTS    ab (before/after per spot and hour), explore (tonemappers, fog), aa
                (anti-aliasing and graphics preset, last: may recreate resources),
                motion (showcase motion blur while turning)
  POST_LIVE_SKIP options never pushed live (start-only or resource-recreating)
  POST_SETTLE   seconds after a push before the frame (6)"""
import json, math, os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
import a3_lib as A
from tour_lib import D, Q, say, tap, hold, mark, view, warp

E = os.environ.get
SETTLE = float(E("POST_SETTLE", "6"))
HOURS = {"noon": 12.5, "golden": 17.4, "dusk": 18.35, "night": 22.5, "wet": 22.5}
# x, y, level, face-at x, y, view
SPOTS = {"street": (171.0, 123.0, 2, 171.0, 117.1, "first"),
         "plaza": (198.5, 188.5, 2, 198.5, 178.0, "third"),
         "spawn": (159.5, 139.5, 2, 159.5, 149.5, "third")}
SKIP = set(filter(None, E("POST_LIVE_SKIP", "rtx.graphicsPreset,rtx.upscalerType,rtx.taauPreset,rtx.resolutionScale,"
                          "rtx.sharpening.sharpness,rtx.dlssPreset,rtx.dlfg.enable,rtx.isReflexEnabled,"
                          "rtx.faultNotice.enable,rtx.screenshot.hotkey,rtx.shader.blockUntilPrewarmed,"
                          "rtx.gpuStallTimeoutSeconds,rtx.ignoreGameDirectionalLights,rtx.fallbackLightMode").split(",")))

def conf(path):
    out = {}
    if not path or not os.path.exists(path): return out
    for line in open(path):
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, v = line.split("=", 1); out[k.strip()] = v.strip()
    return out

DEFAULTS = json.load(open(E("POST_DEFAULTS", "/work/remix_post_defaults.json")))
BEFORE = conf(E("POST_BEFORE", "/work/rtx_post_before.conf.extra"))
PLAY = conf(E("POST_PLAY", "/work/rtx_play.conf.extra"))
SHOW = conf(E("POST_SHOW", "/work/rtx_showcase.conf.extra"))
TOD = {n: conf(os.path.join(E("POST_TOD_DIR", "/work"), f"rtx_tod_{n}.conf.extra")) for n in HOURS}

def full(*layers):
    d = {}
    for l in layers: d.update(l)
    return d

ALLKEYS = set(BEFORE) | set(PLAY) | set(SHOW) | {k for t in TOD.values() for k in t}
def state(*layers):
    """every key any preset touches, with the before value (or the runtime default) underneath"""
    base = {k: BEFORE.get(k, DEFAULTS.get(k)) for k in ALLKEYS}
    return {k: v for k, v in full(base, *layers).items() if v is not None and k not in SKIP}

CUR = state()   # what the session started with

def ini_set(key, val):
    t = open(T.INI, encoding="latin-1").read()
    if re.search(rf"(?m)^{key}=", t):
        t = re.sub(rf"(?m)^{key}=.*$", lambda m: f"{key}={val}", t)
    else:
        t = re.sub(r"(?m)^\[devtools\]\s*$", lambda m: f"[devtools]\n{key}={val}", t, count=1)
    open(T.INI, "w", encoding="latin-1").write(t)

def push(target, tag, settle=None):
    """push the options whose value differs from the current state, in <500-char lines"""
    global CUR
    diff = [f"{k}={v}" for k, v in sorted(target.items()) if CUR.get(k) != v]
    chunks, line = [], ""
    for item in diff:
        if line and len(line) + 1 + len(item) > 480: chunks.append(line); line = ""
        line = f"{line}|{item}" if line else item
    if line: chunks.append(line)
    for i, c in enumerate(chunks):
        ini_set("remix_config", c + ("|" * (i % 2)))   # a trailing | keeps two equal lines distinct
        time.sleep(1.3)
    CUR = dict(CUR, **target)
    say(f"push {tag}: {len(diff)} options in {len(chunks)} lines")
    time.sleep(SETTLE if settle is None else settle)

def hour(h):
    ini_set("set_hour_tenths", int(round(h * 10))); time.sleep(3.0); mark(f"hour {h:.2f}")

def goto(name):
    x, y, lv, fx, fy, v = SPOTS[name]
    s = warp(x, y, lv, why=f"spot {name}")
    Q.set_view("classic", settle=0.8); A.face(fx, fy)
    view(v); time.sleep(1.5)
    s = D.wait_state(); mark(f"spot {name} at {s['x']:.2f},{s['y']:.2f} facing {s.get('fx', 0):.2f},{s.get('fy', 0):.2f}")

mark("script start")
s = D.wait_state(); say("start:", T.words(s))
Q.set_view("classic", settle=1.0); D.calibrate_turn()
parts = [p.strip() for p in E("POST_PARTS", "explore,ab,motion,aa").split(",")]
spots = [p.strip() for p in E("POST_SPOTS", "street,plaza,spawn").split(",")]
tods = [p.strip() for p in E("POST_TODS", "noon,golden,dusk,night,wet").split(",")]
BEF = state()
ALT = {"rtx.tonemap.tonemapOperator": "6", "rtx.tonemap.colorGradingEnabled": "True",
       "rtx.tonemap.contrast": "1.08", "rtx.tonemap.saturation": "1.15"}
AFT = {n: state(PLAY, TOD[n]) for n in tods}

if "explore" in parts:
    goto("street")
    tm = {"psycho17": {"rtx.tonemap.tonemapOperator": "6", "rtx.tonemap.colorGradingEnabled": "False"},
          "agx_punchy": {"rtx.tonemap.tonemapOperator": "4", "rtx.tonemap.agx.look": "2", "rtx.tonemap.agx.saturation": "1.15",
                         "rtx.tonemap.colorGradingEnabled": "False"},
          "gt7": {"rtx.tonemap.tonemapOperator": "7", "rtx.tonemap.colorGradingEnabled": "False"},
          "hable": {"rtx.tonemap.tonemapOperator": "3", "rtx.tonemap.colorGradingEnabled": "False"},
          "lottes": {"rtx.tonemap.tonemapOperator": "5", "rtx.tonemap.lottes.contrast": "1.35", "rtx.tonemap.colorGradingEnabled": "False"},
          "aces": {"rtx.tonemap.tonemapOperator": "2", "rtx.tonemap.colorGradingEnabled": "False"},
          "psycho17_grade": {"rtx.tonemap.tonemapOperator": "6", "rtx.tonemap.colorGradingEnabled": "True",
                             "rtx.tonemap.contrast": "1.08", "rtx.tonemap.saturation": "1.15"}}
    for tod in ("noon", "night"):
        hour(HOURS[tod])
        for name, over in tm.items():
            push(state(PLAY, TOD[tod], over), f"tm {name}"); mark(f"x_{tod}_tm_{name}")
    hour(HOURS["night"])
    for name, over in [("fog0", {"rtx.volumetrics.transmittanceMeasurementDistanceMeters": "2000"}),
                       ("fog180", {}),
                       ("fog60", {"rtx.volumetrics.transmittanceMeasurementDistanceMeters": "60"}),
                       ("fog60_far", {"rtx.volumetrics.transmittanceMeasurementDistanceMeters": "60", "rtx.volumetrics.froxelMaxDistanceMeters": "80"}),
                       ("bloom_wide", {"rtx.bloom.steps": "8", "rtx.bloom.burnIntensity": "0.8", "rtx.bloom.luminanceThreshold": "0.7"})]:
        push(state(PLAY, TOD["night"], over), f"x {name}"); mark(f"x_night_{name}")
        view("third"); time.sleep(2.0); mark(f"x_night_{name}_third"); view("first")

if "ab" in parts:
    for sp in spots:
        goto(sp)
        for tod in tods:
            hour(HOURS[tod])
            push(BEF, "before"); mark(f"ab_{sp}_{tod}_before")
            push(AFT[tod], f"after {tod}"); mark(f"ab_{sp}_{tod}_after")
            if tod in ("noon", "night"):   # the runtime's own tonemapper with a grade, for the choice
                push(state(PLAY, TOD[tod], ALT), f"alt {tod}"); mark(f"ab_{sp}_{tod}_alt")

if "motion" in parts:
    goto("plaza"); hour(HOURS["night"])
    for name, layer in (("play", PLAY), ("show", SHOW)):
        push(state(layer, TOD["night"]), f"motion {name}")
        D.xdo("keydown", "Left")
        for i in range(4): time.sleep(0.35); mark(f"mo_{name}_{i}")
        D.xdo("keyup", "Left"); time.sleep(1.5)

if "aa" in parts:
    goto("street"); hour(HOURS["noon"]); push(state(PLAY, TOD["noon"]), "aa base")
    mark("aa_none"); time.sleep(8); mark("aa_none_t")
    for name, conf_ in [("taau_full", "rtx.upscalerType=3|rtx.taauPreset=4|rtx.resolutionScale=1.0"),
                        ("taau_full_sharp", "rtx.sharpening.sharpness=0.2"),
                        ("gp_ultra", "rtx.graphicsPreset=0"),
                        ("gp_medium", "rtx.graphicsPreset=2"),
                        ("gp_high", "rtx.graphicsPreset=1")]:
        ini_set("remix_config", conf_); time.sleep(8); mark(f"aa_{name}"); time.sleep(12); mark(f"aa_{name}_t")
        view("third"); time.sleep(2); mark(f"aa_{name}_third"); view("first")
    # the play preset as it would start (High, TAA-U, sharpening), every hour, at the street
    for tod in tods:
        hour(HOURS[tod]); push(AFT[tod], f"final {tod}"); mark(f"fin_street_{tod}")

T.finish("remix post take")
