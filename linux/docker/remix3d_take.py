#!/usr/bin/env python3
"""REMIX-3D-PARITY take (keys_remix3d.sh, under gamerun/remix_l4.sh): the same moment path traced in
the classic view and in the 3D views, by day and by night, and the view switches in between.
Per hour (R3_HOURS "name=hour,...") and spot (R3_SPOTS "name:x,y[,z];..."), standing still:
  A classic (settled) -> V -> five frames of the camera move (M1..M5 at 0.15..1.4 s) -> C third
  -> D first -> V -> five frames of the move back (N1..N5) -> E classic again (settled).
Marks go to /out/marks.txt (frames are cut from game.mp4 by tools/remix_3d_parity.py), the view
switches also to /out/bev_events.json in the shape tools/bev_parity.py's switch check reads."""
import json, os, re, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import qa_lib as Q
import tour_lib as T
from tour_lib import mark, warp

E = os.environ.get
HOURS = [(n, float(h)) for n, h in (x.split("=") for x in E("R3_HOURS", "day=14.0,night=22.5").split(","))]
EVENTS = []
# Frames of the camera move, counted in rendered frames after V: the move is 1.4 s at the 30 fps
# step (42 frames, the camera is step-locked to the game, world_view.cpp UpdateCamera), and under
# Remix a session can run far below 30 fps, so wall-clock waits caught the camera mid-flight.
MOVE = (5, 11, 18, 27, 42)
SETTLE = 70        # frames after V before a view counts as settled (42 for the move + the follow)
FRAME_RX = re.compile(r"remix lights @(\d+):")

def frame_now():
    """the renderer's frame counter, from the light-set line (GTA2DX9_LOG_LIGHTS_EVERY=2)"""
    m = FRAME_RX.findall(Q.log_text(60000))
    return int(m[-1]) if m else None

def wait_frames(f0, n, timeout=60.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        f = frame_now()
        if f0 is None or f is None:
            time.sleep(n / 30.0); return
        if f - f0 >= n: return
        time.sleep(0.05)

def ev(name, **kw):
    EVENTS.append(dict(name=name, t=time.time(), **kw))
    json.dump(EVENTS, open("/out/bev_events.json", "w"), indent=1)

def dev_set(key, val):
    """key=val inside [devtools] (the renderer re-reads the section)"""
    t = open(T.INI, encoding="latin-1").read()
    m = re.search(r"(?m)^\[devtools\][^\n]*\n", t)
    if not m:
        t += f"\n[devtools]\n{key}={val}\n"
    else:
        start = m.end(); nxt = re.search(r"(?m)^\[", t[start:]); end = start + nxt.start() if nxt else len(t)
        sec = t[start:end]
        sec = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", sec) if re.search(rf"(?m)^{key}=", sec) else f"{key}={val}\n" + sec
        t = t[:start] + sec + t[end:]
    open(T.INI, "w", encoding="latin-1").write(t)

def hour(h, settle=8.0):
    """the clock to h, then time for the sun and the auto exposure to settle"""
    dev_set("set_hour_tenths", int(round(h * 10))); time.sleep(settle); mark(f"hour {h:.2f}")

def press_v(tag, to, frames):
    ev("switch", moment=tag, to=to)
    f0 = frame_now(); D.tap("v", 0.1)
    for k, n in enumerate(MOVE):
        wait_frames(f0, n); mark(f"{tag}_{frames}{k + 1}_to_{to}")
    wait_frames(f0, SETTLE)

def to_view(tag, target):
    """V (via set_view) and the camera settled, counted in frames"""
    f0 = frame_now(); Q.set_view(target, settle=0.3); wait_frames(f0, SETTLE)

def moment(tag):
    to_view(tag, "classic"); time.sleep(1.5)
    ev("moment_start", moment=tag); mark(f"{tag}_A_classic")
    time.sleep(1.0); mark(f"{tag}_A2_classic")
    press_v(tag, "third", "M")
    time.sleep(1.0); mark(f"{tag}_C_third")
    ev("switch", moment=tag, to="first"); to_view(tag, "first"); time.sleep(1.0); mark(f"{tag}_D_first")
    press_v(tag, "classic", "N")
    time.sleep(1.0); mark(f"{tag}_E_classic_again")
    time.sleep(1.0); mark(f"{tag}_E2_classic_again")
    ev("moment_end", moment=tag)

mark("script start")
s = D.wait_state(timeout=float(E("R3_START_WAIT", "600")))
if not s: mark("no player state"); sys.exit(1)
START = (round(s["x"], 1), round(s["y"], 1))
SPOTS = []
for item in filter(None, E("R3_SPOTS", "start").split(";")):
    name, _, xy = item.partition(":")
    SPOTS.append((name, [float(c) for c in xy.split(",")] if xy else None))
# warm-up: every view, so Remix has compiled its pipelines before the kept frames
t0 = time.time(); i = 0
while time.time() - t0 < float(E("R3_WARM", "120")):
    for v in ("classic", "third", "first"):
        Q.set_view(v, settle=0.5); D.hold("Left", 0.4); time.sleep(1.5)
    i += 1
mark("warm end")
for tod, h in HOURS:
    hour(h)
    for nm, xy in SPOTS:
        if xy is None: s = warp(START[0], START[1], None, why="the start")
        else: s = warp(xy[0], xy[1], int(xy[2]) if len(xy) > 2 else None, why=f"spot {nm}")
        T.clear_of_cars()
        mark(f"spot {nm} at {s['x']:.2f},{s['y']:.2f}")
        time.sleep(2.0)
        moment(f"r3_{tod}_{nm}")
T.finish("remix 3d parity take")
