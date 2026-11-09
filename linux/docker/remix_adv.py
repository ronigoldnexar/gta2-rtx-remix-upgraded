#!/usr/bin/env python3
"""REMIX-ADVANCED take (keys_remix_adv.sh): before/after frames at matched camera positions
and frame-time benches, for one start preset per session (RTX_EXTRA = the play preset for
"before", rtx_advanced.conf.extra for "after"). The same take runs in both sessions, so the
frames pair up by mark name.

  0. warm-up (SHOW_WARM s): views and hours, so the shaders are compiled
  1. sun probe first (before the warm-up): at the plaza, chase view, the session's StartHour
     (12:30, paused), waiting SUN_WAIT s in place with no hour change (sun_<tag>_0_wait<k>,
     sun_<tag>_0_asis: whatever the renderer pushed at start), then sun_<tag>_1_nudge (hour
     moved and back, forcing a fresh push)
  2. per hour (ADV_TODS) and per spot (ADV_SPOTS): first person and chase view, one heading
     each, the time-of-day overlay pushed live over the session's start preset. Every hour
     change moves the clock 0.2 h past and back, so the sun is pushed fresh (see 1)
  3. benches: 20 s still in the chase view at the plaza at noon and at night, then 10 s
     turning; the frame-log line numbers at the begin/end marks (bench_<tag>_begin n=...)
  4. live GI A/B at the plaza (noon, night): integrateIndirectMode 0 (importance sampled,
     what the NRC fallback gives) then 1 (ReSTIR GI), each held 8 s
Env: ADV_TAG (label), ADV_BASE (the start preset file), ADV_SPOTS ("name:x,y;..."),
ADV_TODS, ADV_JUMP (1: only the night-to-day jump test), ADV_BENCH (0: no benches / GI A/B), SUN_WAIT, SHOW_WARM, SHOW_SETTLE."""
import json, os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, say, hold, mark, view, warp

E = os.environ.get
TAG = E("ADV_TAG", "a")
SETTLE = float(E("SHOW_SETTLE", "6"))
HOURS = {"noon": 13.0, "golden": 17.4, "dusk": 17.9, "night": 22.5, "wet": 22.5}
TODF = {"noon": "noon", "golden": "golden", "dusk": "dusk", "night": "night", "wet": "wet"}
FLOG = "/out/frames.tsv"
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

BASE = conf(E("ADV_BASE", "/work/rtx_play.conf.extra"))
TOD = {n: conf(f"/work/rtx_tod_{f}.conf.extra") for n, f in TODF.items()}
DEFAULTS = json.load(open("/work/remix_post_defaults.json"))
KEYS = set(BASE) | {k for t in TOD.values() for k in t}

def state(*layers):
    d = {k: BASE.get(k, DEFAULTS.get(k)) for k in KEYS}
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

_raw_n = [0]
def raw(kv, tag, settle=8.0):
    """one option pushed as is (not tracked in CUR); alternate a trailing | so the line changes"""
    _raw_n[0] += 1
    ini_set("remix_config", kv + ("|" * (_raw_n[0] % 2))); time.sleep(settle); say(f"raw {tag}: {kv}")

def hour(h, settle=3.0, nudge=True):
    if nudge:
        ini_set("set_hour_tenths", int(round((h + 0.2) * 10))); time.sleep(1.2)
    ini_set("set_hour_tenths", int(round(h * 10))); time.sleep(settle); mark(f"hour {h:.2f}")

def flog_n():
    try:
        with open(FLOG, "rb") as f: return sum(1 for _ in f)
    except OSError: return -1

def bench(tag, still=20.0, turn=10.0):
    mark(f"bench_{TAG}_{tag}_begin n={flog_n()}")
    time.sleep(still)
    mark(f"bench_{TAG}_{tag}_still_end n={flog_n()}")
    t0 = time.time()
    while time.time() - t0 < turn:
        hold("Left", 0.6); time.sleep(0.4)
    mark(f"bench_{TAG}_{tag}_end n={flog_n()}")

def spots():
    out = []
    for item in filter(None, E("ADV_SPOTS", "start;plaza:198.5,188.5;street:171,123").split(";")):
        name, _, xy = item.partition(":")
        out.append((name, [float(c) for c in xy.split(",")] if xy else None))
    return out

def goto(name, xy):
    if xy is None: warp(START[0], START[1], None, why="back to the start")
    else: warp(xy[0], xy[1], int(xy[2]) if len(xy) > 2 else None, why=f"spot {name}")
    s = D.wait_state(); mark(f"spot {name} at {s['x']:.2f},{s['y']:.2f}")
    return s

def frames(tag):
    """first person and chase view, the heading the warp leaves (the same in both sessions)"""
    view("first"); time.sleep(2.0); mark(f"f_{tag}_first")
    view("third"); time.sleep(2.0); mark(f"f_{tag}_third")
    hold("Left", 0.55); time.sleep(2.0); mark(f"f_{tag}_third_l")

mark("script start")
s = D.wait_state(timeout=float(E("SHOW_START_WAIT", "600")))
if not s: mark("no player state"); sys.exit(1)
say("start:", T.words(s))
START = (round(s["x"], 1), round(s["y"], 1))
SP = spots()
tods = [t for t in E("ADV_TODS", "noon,golden,dusk,night,wet").split(",") if t]

# 1. sun probe first, before any hour change or push (what a session starting at 12:30 shows):
# at the plaza (in sun at 12:30-13:00), wait in place for the shaders, no hour change at all
plaza0 = [p for p in SP if p[0] == "plaza"] or SP[:1]
goto(*plaza0[0]); view("third")
for k in range(int(float(E("SUN_WAIT", "180")) // 30)):
    time.sleep(30.0); mark(f"sun_{TAG}_0_wait{k}")
mark(f"sun_{TAG}_0_asis")
view("first"); time.sleep(2.0); mark(f"sun_{TAG}_0_asis_first"); view("third"); time.sleep(2.0)
hour(12.5, settle=5.0, nudge=True); mark(f"sun_{TAG}_1_nudge")
view("first"); time.sleep(2.0); mark(f"sun_{TAG}_1_nudge_first"); view("third")

# 1c. ADV_JUMP=1: the night-to-day jump test (sunless daytime): at the plaza, the clock set
# straight from 22:30 to 13:00 (no intermediate value), frames 4 s and 10 s after, three times
if E("ADV_JUMP", "0") == "1":
    goto(*plaza0[0]); view("third"); time.sleep(2.0)
    for k in range(3):
        hour(22.5, settle=8.0, nudge=False); mark(f"jump_{TAG}_{k}_night")
        hour(13.0, settle=4.0, nudge=False); mark(f"jump_{TAG}_{k}_day_4s")
        time.sleep(6.0); mark(f"jump_{TAG}_{k}_day_10s")
        view("first"); time.sleep(2.0); mark(f"jump_{TAG}_{k}_day_first"); view("third")
    T.finish(f"remix adv jump {TAG}"); sys.exit(0)

# 0. warm-up (frames warm_* only show when compilation ends)
t0 = time.time(); i = 0
while time.time() - t0 < float(E("SHOW_WARM", "60")):
    tod = tods[i % len(tods)]; hour(HOURS[tod], settle=1.0, nudge=False)
    for v in ("first", "third"):
        view(v); hold("Left", 0.5); time.sleep(2.0); mark(f"warm_{i}_{tod}_{v}")
    goto(*SP[i % len(SP)]); i += 1
mark("warm end")

# 2. the hours at each spot
for tod in tods:
    hour(HOURS[tod]); push(state(TOD[tod]), f"{TAG}+{tod}")
    for nm, xy in SP:
        goto(nm, xy); frames(f"{TAG}_{tod}_{nm}")

# 3. benches and 4. live GI A/B at the plaza, noon and night
plaza = [p for p in SP if p[0] == "plaza"] or SP[:1]
for tod in (("noon", "night") if E("ADV_BENCH", "1") == "1" else ()):
    hour(HOURS[tod]); push(state(TOD[tod]), f"{TAG}+{tod} (bench)")
    goto(*plaza[0]); view("third"); time.sleep(3.0)
    bench(tod)
    view("third"); time.sleep(2.0)
    for mode in (0, 1, 2):
        raw(f"rtx.integrateIndirectMode={mode}", f"gi {mode}")
        mark(f"gi_{TAG}_{tod}_mode{mode}_third")
        view("first"); time.sleep(3.0); mark(f"gi_{TAG}_{tod}_mode{mode}_first"); view("third")
    raw(f"rtx.integrateIndirectMode={BASE.get('rtx.integrateIndirectMode', '2')}", "gi back")
T.finish(f"remix adv {TAG}")
