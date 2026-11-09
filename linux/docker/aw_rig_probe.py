#!/usr/bin/env python3
"""ANIM-WEAPONS probe: the weapon rig on the player's figure, standing in an open street.
Forced clip + weapon (GTA2DX9_FORCE_ACTION_FILE=force_action.txt) and the rig's showcase
file (GTA2DX9_RIG_TEST_FILE=rig_test.txt: "yaw fire_period"): the figure is turned on the
spot for the camera (0 = from behind, 90/-90 the sides, 180 the front), shots synthesized
every period. Per item: stills from several yaws, and 15 fps bursts of firing (recoil) and
of the reload. AW_ITEMS picks items by label; AW_YAWS the still yaws."""
import os, subprocess, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

GAME = "/tmp/wp/drive_c/Games/GTA2/"
def force(a, w=-1):
    with open(GAME + "force_action.txt", "w") as f: f.write(f"{a} 0 {w}\n")
def rig(yaw, period=0.0, off=0):
    with open(GAME + "rig_test.txt", "w") as f: f.write(f"{yaw} {period} {off}\n")
def mark(w):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {w}\n")
    say("MARK", w)
def burst(label, secs, fps=15):
    mark(f"burst {label} {secs}")
    return subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(fps),
                             "-video_size", "1280x720", "-i", ":99", "-t", str(secs), "-c:v", "libx264",
                             "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", f"/out/b_{label}.mp4"])

# (label, action, weapon, fire period (0: no fire burst), reload action (0 none))
ITEMS = [
    ("pistol_aim", 2, 1, 0.45, 24), ("pistol_carry", 14, 1, 0, 0),
    ("mg_aim", 8, 4, 0.12, 25), ("mg_carry", 16, 4, 0, 0),
    ("shotgun_aim", 8, 9, 0.9, 25), ("shotgun_carry", 16, 9, 0, 0),
    ("launcher_aim", 11, 5, 1.2, 26), ("launcher_carry", 17, 5, 0, 0),
    ("flame_aim", 12, 10, 0.1, 0), ("flame_carry", 18, 10, 0, 0),
    ("dual_aim", 10, 2, 0.35, 0), ("silenced_aim", 8, 3, 0.12, 25),
]
only = [x for x in os.environ.get("AW_ITEMS", "").split(",") if x]
if only: ITEMS = [it for it in ITEMS if it[0] in only]
YAWS = [int(v) for v in os.environ.get("AW_YAWS", "90,150,-90,30").split(",")]
force(-1); rig(0, 0)
s = Q.start("aw_rig")
T.warp(float(os.environ.get("AW_SX", "159.5")), float(os.environ.get("AW_SY", "139.5")), int(os.environ.get("AW_SL", "2")), why="open street")
Q.set_view("third", settle=2.5)
for (label, a, w, period, rl) in ITEMS:
    force(-1); rig(0, 0); time.sleep(0.6)
    mark(f"item {label} action {a} weapon {w}")
    force(a, w)
    rig(0, 0); time.sleep(1.0); shot(f"aw_{label}_y0")
    rig(YAWS[0], 0, 1); time.sleep(1.0); shot(f"aw_{label}_off_y{YAWS[0]}")
    for yaw in YAWS:
        rig(yaw, 0); time.sleep(1.0)
        shot(f"aw_{label}_y{yaw}")
    if period > 0:
        rig(YAWS[0], period); time.sleep(0.2)
        p = burst(f"{label}_fire_y{YAWS[0]}", 2.4); p.wait()
        rig(YAWS[1], period); time.sleep(0.2)
        p = burst(f"{label}_fire_y{YAWS[1]}", 2.0); p.wait()
        rig(YAWS[0], 0)
    if rl:
        for yaw in (YAWS[0], YAWS[1]):
            force(a, w); rig(yaw, 0); time.sleep(0.5)
            force(rl, w); time.sleep(0.05)
            p = burst(f"{label}_reload_y{yaw}", 2.2); p.wait()
force(-1); rig(0, 0)
A.finish()
