#!/usr/bin/env python3
"""ANIM-WEAPONS game-driven probe, Downtown: the plain pickups collected, then per weapon (Z
stops) the game drives everything: the carry, a burst on the fire key (the game's shots: the
stance, the recoil), the release (the notional magazine spent: the reload). Only the camera
angle is helped: the rig's showcase yaw (GTA2DX9_RIG_TEST_FILE=rig_test.txt) turns the drawn
figure side-on. 15 fps bursts b_<weapon>_<yaw>.mp4. Run with set_player_ammo=200 and nav_map=0."""
import os, subprocess, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

GAME = "/tmp/wp/drive_c/Games/GTA2/"
def rig(yaw, period=0.0):
    with open(GAME + "rig_test.txt", "w") as f: f.write(f"{yaw} {period}\n")
def mark(w):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {w}\n")
    say("MARK", w)
def burst(label, secs, fps=15):
    mark(f"burst {label} {secs}")
    return subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(fps),
                             "-video_size", "1280x720", "-i", ":99", "-t", str(secs), "-c:v", "libx264",
                             "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", f"/out/b_{label}.mp4"])

PICKUPS = [(227.5, 210.5, 2, "pistol"), (166.5, 140.5, 2, "machine_gun"), (154.5, 129.5, 2, "rocket_launcher"),
           (19.5, 35.5, 4, "flamethrower"), (97.5, 68.5, 2, "silenced_mg")]
only = [x for x in os.environ.get("AW_WEAPONS", "").split(",") if x]
if only: PICKUPS = [p for p in PICKUPS if p[3] in only]
YAWS = [int(v) for v in os.environ.get("AW_YAWS", "90,150").split(",")]
FIRE = {"pistol": 1.6, "machine_gun": 3.2, "rocket_launcher": 0.4, "flamethrower": 1.5, "silenced_mg": 3.2}
rig(0, 0)
s = Q.start("aw_play")
for (x, y, lvl, name) in PICKUPS:
    A.collect(x, y, lvl, name)
T.warp(float(os.environ.get("AW_SX", "159.5")), float(os.environ.get("AW_SY", "139.5")), int(os.environ.get("AW_SL", "2")), why="open street")
Q.set_view("third", settle=2.0)
seen = []
for i in range(len(PICKUPS) + 2):
    tap("z", 0.2); time.sleep(1.0)
    w = A.weapon_name()
    mark(f"stop {i} weapon {w}")
    if w in seen or w == "none": continue
    seen.append(w)
    for yaw in YAWS:
        rig(yaw, 0); time.sleep(1.2)
        shot(f"aw_{w}_carry_y{yaw}")
        secs = FIRE.get(w, 1.5)
        p = burst(f"{w}_y{yaw}", secs + 3.0)
        time.sleep(0.3)
        D.xdo("keydown", "Control_L"); time.sleep(secs); D.xdo("keyup", "Control_L")
        p.wait()
        time.sleep(1.0)
rig(0, 0)
A.finish()
