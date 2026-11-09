#!/usr/bin/env python3
"""Visual regression capture (QA-REGRESSION; docs/visual-regression.md). Runs inside a game
container as the keys script's worker. Takes the same frames every run:

  1. at the spawn, no input but Return and V: the classic view, then the third- and
     first-person views with their own cameras (the camera code itself is under test);
  2. for every point of the shot list: a developer warp there (GTA2DX9_SCENE_NO_CAR=1), the
     third-person view, then each fixed camera pose of the point written to the
     GTA2DX9_REGRESS_CAM file (dll/src/regress_cam.cpp draws from exactly that eye), a frame each.

Frames: /out/vr_<shot>.png; one line per frame in /out/vreg.jsonl (where the player
landed, the log offsets, the time), so the differ can tell "the scene changed" from
"the warp went elsewhere". Env: VREG_SHOTS (the list), VREG_CAM (the camera file the DLL
reads, Linux path), VREG_SETTLE (seconds after a camera move, default 2.0).
"""
import json, os, subprocess, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import qa_lib as Q
import tour_lib as T

say = D.say
SHOTS = json.load(open(os.environ.get("VREG_SHOTS", "/work/vreg_shots.json")))
CAM = os.environ.get("VREG_CAM", "/tmp/vreg_cam.txt")
SETTLE = float(os.environ.get("VREG_SETTLE", "2.0"))
W, H = os.environ.get("SCREEN_W", "1280"), os.environ.get("SCREEN_H", "720")
out = open("/out/vreg.jsonl", "a")
T0 = time.time()


def grab(name):
    p = f"/out/vr_{name}.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", f"{W}x{H}",
                    "-i", ":99", "-frames:v", "1", p])
    return p


def cam(line):
    with open(CAM + ".tmp", "w") as f: f.write(line + "\n")
    os.replace(CAM + ".tmp", CAM)


def wait_log(text, n0, timeout=4.0):
    t = time.time()
    while time.time() - t < timeout:
        if text in Q.log_text()[n0:]: return True
        time.sleep(0.1)
    return False


def record(name, **kw):
    s = D.state()
    rec = dict(shot=name, t=round(time.time() - T0, 1), view=Q.current_view(),
               at=[round(s["x"], 2), round(s["y"], 2), round(s["z"], 2)] if s else None, **kw)
    out.write(json.dumps(rec) + "\n"); out.flush()
    say("shot", name, json.dumps(rec))


cam("off")
D.start()
s = D.wait_state(40)
say("start:", T.words(s) if s else "no state")
time.sleep(3.0)                          # traffic and people spawned around the start
grab("spawn_classic"); record("spawn_classic")
for v in ("third", "first"):
    Q.set_view(v, settle=SETTLE + 1.5)
    grab(f"spawn_{v}"); record(f"spawn_{v}")

for p in SHOTS["points"]:
    try:
        s = T.warp(p["x"], p["y"], p.get("z"), why=f"vreg {p['name']}")
    except Exception as e:
        say(f"point {p['name']}: warp failed: {e}")
        record(f"{p['name']}_miss", error=str(e)); continue
    landed = bool(s) and abs(s["x"] - p["x"]) + abs(s["y"] - p["y"]) < 3
    Q.set_view("third", settle=1.0)
    for pose in p["poses"]:
        e, a = pose["eye"], pose["at"]
        n0 = len(Q.log_text())
        cam("cam " + " ".join(f"{v:.3f}" for v in (p["x"] + e[0], p["y"] + e[1], p["z"] + e[2], p["x"] + a[0], p["y"] + a[1], p["z"] + a[2]))
            + f" {pose.get('fov', 60)}")
        seen = wait_log("regress: camera fixed", n0)
        time.sleep(SETTLE)
        name = f"{p['name']}_{pose['name']}"
        grab(name); record(name, landed=landed, cam_seen=seen)
    cam("off"); time.sleep(0.4)

say("vreg: done in", round(time.time() - T0), "s")
open("/out/.vreg_done", "w").write("ok\n")
