#!/usr/bin/env python3
"""Turn-rate test through a real VNC connection, as a person's keys would arrive.

Usage: camera_feel_test.py <container> <vnc host::port> <label>
Drives the game in the play container: through the front end, then on foot a
90-degree-ish turn in third person and first person, then at the wheel of a
parked car (devtools F9 warp, Return) the same two turns while moving. Each turn
is captured at 30 fps from the container's Xvfb into /out/<label>_<phase>.mp4,
and the renderer log is copied out afterwards for the per-frame camera yaw.
"""
import subprocess, sys, time
from vncdotool import api

CONTAINER, VNC, LABEL = sys.argv[1], sys.argv[2], sys.argv[3]
PORT = CONTAINER.rsplit("-", 1)[-1]

def dx(*cmd, **kw):
    return subprocess.run(["sudo", "-n", "docker", "exec", CONTAINER] + list(cmd), capture_output=True, text=True, **kw)

def log_tail(n=400):
    return dx("bash", "-c", f"tail -n {n} /tmp/wp/drive_c/Games/GTA2/gta2dx9.log 2>/dev/null").stdout

def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

MARKS = {}
def capture(name, seconds):
    dx("bash", "-c", f"rm -f /out/{name}.mp4; (DISPLAY=:99 nohup ffmpeg -y -loglevel error -f x11grab -framerate 30 -video_size 1280x720 -i :99 -t {seconds} -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p /out/{name}.mp4 >/dev/null 2>&1 &)")
    MARKS[name] = [time.time(), seconds]
    say("capture", name, seconds, "s")

# 1. the VNC server, then the game window
for i in range(90):
    r = dx("bash", "-c", "pgrep -c x11vnc; DISPLAY=:99 xwininfo -root -tree 2>/dev/null | grep -c '\"GTA2\"'").stdout.split()
    if len(r) == 2 and r[0] != "0" and r[1] != "0": break
    time.sleep(2)
say("window up")
c = api.connect(VNC, password=None, timeout=10)

def tap(key, seconds=0.3):
    """A real press: the game reads its keyboard once a frame, so a zero-length
    tap is missed when a frame is long (a loaded host); hold it a few frames."""
    c.keyDown(key); time.sleep(seconds); c.keyUp(key)

def hold(key, seconds, also=None):
    if also: c.keyDown(also)
    c.keyDown(key); time.sleep(seconds); c.keyUp(key)
    if also: c.keyUp(also)

time.sleep(12)
# 2. the front end: the proven recipe (keys_demo_fp2.sh): five Returns six
# seconds apart, then wait for the player state line to tick (the attract
# demo logs one too, so the count must rise after the last Return).
for i in range(5):
    tap("return"); time.sleep(6)
base = log_tail(4000).count("view: player x=")
for i in range(30):
    time.sleep(2)
    if log_tail(4000).count("view: player x=") > base + 2: break
say("level up")
time.sleep(4)
tap("v"); time.sleep(2.5)                     # third person

# 3. on foot
capture(f"{LABEL}_third_foot", 7); time.sleep(1.5); hold("left", 2.0); time.sleep(4.0)   # camera-relative: walk to the camera's left; the orbit drifts round
tap("v"); time.sleep(2.5)                     # first person
capture(f"{LABEL}_first_foot", 6); time.sleep(1.5); hold("left", 1.0); time.sleep(3.5)   # first person: the view turns 90 deg at 90 deg/s, the pedestrian follows
tap("v"); time.sleep(2.0)                     # classic

# 4. a car: F9 warps to the nearest parked car's door; Return gets in
tap("f9"); time.sleep(2.0); tap("return"); time.sleep(4.0)
drv = "driving" in log_tail(60)
say("driving:", drv)
if drv:
    tap("v"); time.sleep(2.0)                 # third person
    hold("up", 1.5)
    capture(f"{LABEL}_third_car", 6); time.sleep(1.0); hold("left", 1.0, also="up"); hold("up", 1.0); time.sleep(3.0)
    tap("v"); time.sleep(2.0)                 # first person at the wheel
    hold("up", 1.0)
    capture(f"{LABEL}_first_car", 6); time.sleep(1.0); hold("right", 1.0, also="up"); hold("up", 1.0); time.sleep(3.0)
    tap("v"); time.sleep(1.0)
time.sleep(2)
dx("bash", "-c", f"cp /tmp/wp/drive_c/Games/GTA2/gta2dx9.log /out/{LABEL}_gta2dx9.log")
import json; json.dump(MARKS, open(f"out/play-6091/{LABEL}_marks.json" if False else f"/home/roni_goldshmidt/gta2-linux/out/play-{PORT}/{LABEL}_marks.json", "w"))
api.shutdown()
say("done")
