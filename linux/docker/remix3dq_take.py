#!/usr/bin/env python3
"""REMIX-3D-QUALITY take (keys_remix3dq.sh): REMIX-3D-PARITY's take (below) plus, in the hours
listed in R3Q_SHADOW_HOURS, the first-person own-figure shadow A/B: at four headings, first person on
foot, a frame with [devtools] own_shadow_first_person=1 (sh_on_K) and one with 0 (sh_off_K), the
same moment otherwise; and the third-person frame at that heading (sh_third_K) as the reference.

REMIX-3D-PARITY take (keys_remix3d.sh, under gamerun/remix_l4.sh): the same moment path traced in
the classic view and in the 3D views, by day and by night, and the view switches in between.
Per hour (R3_HOURS "name=hour,...") and spot (R3_SPOTS "name:x,y[,z];..."), standing still:
  A classic (settled) -> V -> five frames of the camera move (M1..M5 at 0.15..1.4 s) -> C third
  -> D first -> V -> five frames of the move back (N1..N5) -> E classic again (settled).
Marks go to /out/marks.txt (frames are cut from game.mp4 by tools/remix_3d_parity.py), the view
switches also to /out/bev_events.json in the shape tools/bev_parity.py's switch check reads."""
import json, math, os, re, sys, time
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

CAM_RX = re.compile(r"cam\[(\d+)\][^\n]*? 98:([-\d.]+)/[-\d.]+ 9C:([-\d.]+)/")

def settle_classic(timeout=float(E("R3Q_CAM_WAIT", "30"))):
    """REMIX-3D-QUALITY: after a warp the game's own camera scrolls to the player for a while; the
    classic frame of a moment waits until the game camera's centre (cam[] +0x98/+0x9C, logged every 64
    frames) is within a block of the player twice in a row, so 'classic before' is the same place."""
    t0 = time.time(); ok = 0; last = None
    while time.time() - t0 < timeout:
        m = CAM_RX.findall(Q.log_text(200000)); s = D.state()
        if m and s and m[-1][0] != last:
            last = m[-1][0]
            d = math.hypot(float(m[-1][1]) - s["x"], float(m[-1][2]) - s["y"])
            ok = ok + 1 if d < 1.0 else 0
            if ok >= 2: mark(f"classic settled ({time.time() - t0:.1f} s, {d:.2f} blocks)"); return True
        time.sleep(0.5)
    mark("classic NOT settled"); return False

def moment(tag):
    to_view(tag, "classic"); settle_classic(); time.sleep(1.5)
    ev("moment_start", moment=tag); mark(f"{tag}_A_classic")
    time.sleep(1.0); mark(f"{tag}_A2_classic")
    press_v(tag, "third", "M")
    time.sleep(1.0); mark(f"{tag}_C_third")
    ev("switch", moment=tag, to="first"); to_view(tag, "first"); time.sleep(1.0); mark(f"{tag}_D_first")
    press_v(tag, "classic", "N")
    time.sleep(1.0); mark(f"{tag}_E_classic_again")
    time.sleep(1.0); mark(f"{tag}_E2_classic_again")
    ev("moment_end", moment=tag)


def shadow_ab(tag):
    """first person on foot: the own figure's shadow on (1) and off (0) at four headings"""
    to_view(tag, "first"); time.sleep(1.0)
    # mouse pixels down (the ground at his feet in frame), in 20 px steps: one move over 8x the look's
    # step clamp (mouse_max_step, 25) is taken for a remote pointer's jump and dropped (view_modes.cpp).
    # The run sets FirstReturnDelay=0 (remix3dq.settings) so the look does not swing back.
    pitch = int(E("R3Q_PITCH", "0"))
    nh = int(E("R3Q_HEADINGS", "4"))
    for k in range(nh):
        for _ in range(pitch // 20): D.xdo("mousemove_relative", "--", "0", "20"); time.sleep(0.04)
        if pitch: time.sleep(0.8)
        dev_set("own_shadow_first_person", 1); f0 = frame_now(); wait_frames(f0, 45); time.sleep(0.6)
        mark(f"{tag}_sh_on_{k}")
        dev_set("own_shadow_first_person", 0); f0 = frame_now(); wait_frames(f0, 45); time.sleep(0.6)
        mark(f"{tag}_sh_off_{k}")
        dev_set("own_shadow_first_person", 1)
        to_view(tag, "third"); time.sleep(1.0); mark(f"{tag}_sh_third_{k}")
        to_view(tag, "first")
        f0 = frame_now(); D.hold("Left", float(E("R3Q_TURN", "0.25"))); wait_frames(f0, 20)
    dev_set("own_shadow_first_person", -1)

def tagged_ab(tag):
    """third person: his figure drawn normally (tg_plain_K) and with the player-model textures
    ([devtools] own_tagged_third=1, tg_tagged_K); Remix must keep the shadow and drop the body"""
    to_view(tag, "third"); time.sleep(1.0)
    for k in range(int(E("R3Q_HEADINGS", "4"))):
        dev_set("own_tagged_third", 0); f0 = frame_now(); wait_frames(f0, 45); time.sleep(0.6)
        mark(f"{tag}_tg_plain_{k}")
        dev_set("own_tagged_third", 1); f0 = frame_now(); wait_frames(f0, 45); time.sleep(0.6)
        mark(f"{tag}_tg_tagged_{k}")
        dev_set("own_tagged_third", 0)
        f0 = frame_now(); D.hold("Left", float(E("R3Q_TURN", "0.25"))); wait_frames(f0, 45)

def tagged_diag(tag):
    """which half fails: the hash or the player-model handling. Third person, his figure drawn with the
    tagged copies; the copies' hashes (from the renderer's log) under rtx.hideInstanceTextures (gone,
    shadow too, if the hash matches), then re-pushed as rtx.playerModelTextures, then with
    rtx.playerModel.enableInPrimarySpace=False set explicitly."""
    to_view(tag, "third"); time.sleep(1.0)
    walk = float(E("R3Q_DIAG_WALK", "0"))   # out from behind whatever stands at the warp point
    if walk: D.hold("Up", walk); f0 = frame_now(); wait_frames(f0, 60)
    for name, tagged in (("plain", 0), ("tagged", 1)):
        dev_set("own_tagged_third", tagged); f0 = frame_now(); wait_frames(f0, 75); time.sleep(0.6); mark(f"{tag}_dg_{name}")
    hs = re.findall(r"own figure: \d+ player-model textures? tagged \(taken\), last (0x[0-9A-F]+)", Q.log_text(None))
    hs = ", ".join(dict.fromkeys(hs)); mark(f"{tag}_diag hashes {hs}")
    if E("R3Q_DIAG_SCHEMES", "0") == "1":
        # which hash scheme the runtime uses: each candidate set alone under hideInstanceTextures
        cand = {}
        for m in re.finditer(r"hash candidates \S+ \d+x\d+: (.*)", Q.log_text(None)):
            for k, v in re.findall(r"(\w+) (0x[0-9A-F]+)", m.group(1)): cand.setdefault(k, []).append(v)
        for k, vs in cand.items():
            dev_set("own_tagged_third", 1); dev_set("remix_config", "rtx.hideInstanceTextures=" + ", ".join(dict.fromkeys(vs)))
            f0 = frame_now(); wait_frames(f0, 75); time.sleep(0.6); mark(f"{tag}_dg_scheme_{k}")
        dev_set("remix_config", "rtx.hideInstanceTextures="); f0 = frame_now(); wait_frames(f0, 75)
    steps = [("hidden", 1, f"rtx.hideInstanceTextures={hs}"),
             ("unhidden", 1, "rtx.hideInstanceTextures="),
             ("repush", 1, f"rtx.playerModelTextures={hs}"),
             ("primoff", 1, f"rtx.playerModelTextures={hs}|rtx.playerModel.enableInPrimarySpace=False")]
    for name, tagged, cfg in steps:
        dev_set("own_tagged_third", tagged); dev_set("remix_config", cfg)
        f0 = frame_now(); wait_frames(f0, 75); time.sleep(0.6); mark(f"{tag}_dg_{name}")
    dev_set("own_tagged_third", 0); dev_set("remix_config", "")

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
        if E("R3Q_CLOCK_TEST", "1") == "1":
            # is the clock holding still? two classic frames a minute apart, no V in between
            to_view(f"r3_{tod}_{nm}", "classic"); settle_classic()
            mark(f"r3_{tod}_{nm}_clk_0"); time.sleep(60); mark(f"r3_{tod}_{nm}_clk_1")
        if E("R3Q_SHADOW_ONLY", "0") != "1": moment(f"r3_{tod}_{nm}")
        if tod in E("R3Q_SHADOW_HOURS", "day").split(","): shadow_ab(f"r3_{tod}_{nm}")
        if tod in E("R3Q_TAGGED_HOURS", "").split(","): tagged_ab(f"r3_{tod}_{nm}")
        if tod in E("R3Q_DIAG_HOURS", "").split(","): tagged_diag(f"r3_{tod}_{nm}")
T.finish("remix 3d quality take")
