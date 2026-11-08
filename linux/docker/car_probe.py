#!/usr/bin/env python3
"""PLAYTHROUGH-7 vehicle-field probe: F9 into the nearest parked car, then ram
walls (full throttle forward and back with the wheel turned) until the car
burns and explodes, with GTA2DX9_LOG_CAR_WORDS=1 logging every changed word of
the vehicle object every third frame. Frames every second, MARK lines for
every hit phase, so the candidate words can be lined up with the frames."""
import os, sys, time, shutil, subprocess
sys.path.insert(0, "/work")
import qa_lib as Q
import drive_lib as D
from qa_lib import say, tap, hold

def shot(name):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99",
                    "-frames:v", "1", f"/out/cp_{name}.png"])

s = Q.start("car_probe")
Q.set_view("third", settle=0.5)
inside = None
for attempt in range(4):
    tap("F9", 0.3); time.sleep(1.5); tap("Return", 0.3); time.sleep(3.0)
    s = D.wait_state()
    if s and s["driving"]: inside = s; break
    say("not in a car yet", attempt)
say("MARK in car", inside and inside.get("cmodel"))
t0 = time.time(); k = 0
SECS = float(os.environ.get("PROBE_SECS", "300"))
while time.time() - t0 < SECS:
    s = D.wait_state()
    if not s["driving"]:
        say("MARK out of the car (dead or thrown out) at", f"{s['x']:.1f},{s['y']:.1f}")
        shot(f"{k:03d}_out"); time.sleep(3); shot(f"{k:03d}_out2")
        break
    steer = "Left" if (k // 3) % 2 else "Right"
    say(f"MARK hit {k} fwd at {s['x']:.1f},{s['y']:.1f}")
    # straight at full throttle (into whatever wall or post is ahead), then back off turning
    D.xdo("keydown", "Up"); time.sleep(1.6); shot(f"{k:03d}_f"); time.sleep(1.2); shot(f"{k:03d}_g")
    D.xdo("keyup", "Up")
    say(f"MARK hit {k} back")
    D.xdo("keydown", "Down"); D.xdo("keydown", steer); time.sleep(1.0); shot(f"{k:03d}_b"); time.sleep(0.2); D.xdo("keyup", steer); D.xdo("keyup", "Down")
    k += 1
time.sleep(6); shot("end")
say("CHECK", Q.counts())
shutil.copy("/tmp/wp/drive_c/Games/GTA2/gta2dx9.log", "/out/gta2dx9.log")
open("/out/.keys_done", "w").close()
