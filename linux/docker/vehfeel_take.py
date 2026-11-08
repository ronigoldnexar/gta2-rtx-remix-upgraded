"""VEHICLE-FEEL take: the same manoeuvres with [devtools] vehicle_feel=0 (before) and =1
(after), in the chase view, on the scene car by the Downtown carriageway. Every phase is
a mark in /out/marks.txt (epoch seconds) so the sheet cuts its frames from game.mp4.
  day:   launch, brake, reverse, turn, handbrake turn, kerb run, wall scrape
  night: idle (exhaust), brake, reverse (lamps and pools)
  wreck: the player's car set to damage 31650 (burning), he gets out and steps back,
         the car blows up (one per variant)
Run (CPUs 0-4, nohup):
  STAGE=~/gta2-linux/stage_vehfeel GTA2_DIRECT_KEYS=1 FPS=25 CPUS=3 \
  INI_SED='s/^scene_key=.*/scene_key=F11/' gamerun/grun.sh vf_<n> 900 keys_vehfeel.sh \
  -e SCENE_KEY=F11 -e GTA2DX9_LOG_VEHICLE_FEEL=1 -e 'GTA2DX9_FRAME_LOG=Z:\\out\\frames.tsv'"""
import os, re, subprocess, sys, threading, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, Q, say, hold, mark, view, warp

xdo = D.xdo
SCENE = [float(c) for c in os.environ.get("SCENE_XY", "164.5,149.5").split(",")]
PHASES = os.environ.get("PHASES", "day,night,wreck").split(",")


def ini_set(key, val):
    t = open(T.INI, encoding="latin-1").read()
    if re.search(rf"(?m)^{key}=", t):
        t = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    else:
        t = re.sub(r"(?m)^\[devtools\]\s*$", f"[devtools]\n{key}={val}", t, count=1)
    open(T.INI, "w", encoding="latin-1").write(t)


REC = None


def snap(name):
    subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99",
                      "-frames:v", "1", f"/out/vf_{name}.png"])


def burst(name, n, gap):
    def run():
        for i in range(n):
            snap(f"{name}_{i}"); time.sleep(gap)
    threading.Thread(target=run, daemon=True).start()


def rec_start(name, secs):
    global REC
    REC = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", "25", "-video_size", "1280x720",
                            "-i", ":99", "-t", str(secs), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                            f"/out/clip_{name}.mp4"])


def rec_stop():
    global REC
    if REC:
        REC.terminate(); REC.wait(); REC = None


def keys(down, secs):
    for k in down: xdo("keydown", k)
    time.sleep(secs)
    for k in reversed(down): xdo("keyup", k)


def into_car():
    for attempt in range(6):
        time.sleep(2.0)   # the exit animation done: a warp during it is ignored
        s = warp(SCENE[0], SCENE[1], None, why="scene car")
        s = T.get_in_scene_car(s)
        if s and s.get("driving"):
            view("third"); time.sleep(1.5)
            return s
        T.leave_car()
    return None


def day(tag):
    if not into_car():
        mark(f"{tag} NO CAR"); return
    if tag.endswith("after"): rec_start("day", 40)
    mark(f"{tag} launch"); burst(f"{tag}_launch", 4, 0.3); keys(["Up"], 2.2)
    mark(f"{tag} brake"); burst(f"{tag}_brake", 4, 0.2); keys(["Down"], 0.7)
    mark(f"{tag} reverse"); keys(["Down"], 0.6); burst(f"{tag}_reverse", 3, 0.3); keys(["Down"], 1.0)
    time.sleep(0.6)
    mark(f"{tag} turn"); keys(["Up"], 1.2); burst(f"{tag}_turn", 5, 0.3); keys(["Up", "Left"], 1.6); keys(["Up"], 0.4)
    mark(f"{tag} handbrake"); keys(["Up"], 1.0); burst(f"{tag}_handbrake", 6, 0.35); keys(["Up", "Right", "space"], 1.3); keys(["Down"], 0.5)
    time.sleep(1.0)
    mark(f"{tag} kerb"); keys(["Up"], 0.8); burst(f"{tag}_kerb", 8, 0.3)
    for i in range(3):
        keys(["Up", "Left"], 0.35); keys(["Up"], 0.4); keys(["Up", "Right"], 0.35); keys(["Up"], 0.4)
    keys(["Down"], 0.8)
    mark(f"{tag} scrape"); keys(["Up", "Left"], 0.5); burst(f"{tag}_scrape", 14, 0.4); keys(["Up"], 2.5); keys(["Up", "Left"], 2.0); keys(["Up", "Right"], 0.3); keys(["Up"], 1.5)
    keys(["Down"], 0.6)
    rec_stop()
    mark(f"{tag} day end")
    time.sleep(1.0)
    T.leave_car()


def night(tag):
    if not into_car():
        mark(f"{tag} NO CAR"); return
    if tag.endswith("after"): rec_start("night", 20)
    mark(f"{tag} idle"); burst(f"{tag}_idle", 5, 0.5); time.sleep(3.0)
    mark(f"{tag} drive"); keys(["Up"], 1.2); burst(f"{tag}_drive", 3, 0.3); keys(["Up"], 0.8)
    mark(f"{tag} brake"); burst(f"{tag}_brake", 3, 0.2); keys(["Down"], 0.7)
    mark(f"{tag} reverse"); keys(["Down"], 0.6); burst(f"{tag}_reverse", 3, 0.3); keys(["Down"], 1.2)
    time.sleep(0.5)
    mark(f"{tag} turn"); keys(["Up"], 1.0); keys(["Up", "Left"], 1.4); keys(["Down"], 0.8)
    rec_stop()
    mark(f"{tag} night end")
    time.sleep(1.0)
    T.leave_car()


def wreck(tag):
    # The damage word alone does not light a car (the game does that when a hit crosses
    # 16000), so the car is set just short of 32000 and driven into the next thing it
    # meets; the moment it burns he bails out and backs off, and it blows ~3 s later.
    if not into_car():
        mark(f"{tag} NO CAR"); return
    if tag.endswith("after"): rec_start("wreck", 32)
    ini_set("set_car_damage", 31850); time.sleep(1.5)
    mark(f"{tag} armed")
    t0 = time.time(); k = 0
    xdo("keydown", "Up")
    while time.time() - t0 < 10:
        s = D.state() or {}
        if s.get("fire", 0) > 0: break
        k += 1
        if k % 10 == 5: xdo("keydown", "Left")    # weave so it meets a wall or a car
        if k % 10 == 0: xdo("keyup", "Left")
        time.sleep(0.15)
    xdo("keyup", "Left"); xdo("keyup", "Up")
    mark(f"{tag} burning")
    D.tap("Return", 0.25)
    time.sleep(0.8); keys(["Down"], 1.2)
    n0 = Q.log_text().count("blew up")
    burst(f"{tag}_burn", 4, 0.5)
    t1 = time.time()
    while time.time() - t1 < 14:   # it blows ~5-10 s after catching fire; the log says when (feel on)
        if Q.log_text().count("blew up") > n0: break
        if not tag.endswith("after") and time.time() - t1 > 7.5: break
        time.sleep(0.1)
    mark(f"{tag} blown")
    burst(f"{tag}_blown", 16, 0.2)
    time.sleep(3.5)
    burst(f"{tag}_after", 6, 0.5)
    time.sleep(3.5)
    rec_stop()
    mark(f"{tag} wreck end")
    ini_set("set_car_damage", -1)
    time.sleep(3.0)



mark("script start")
ini_set("force_car_model", int(os.environ.get("VF_MODEL", "13")))
time.sleep(2)
for phase in PHASES:
    if phase == "day":
        ini_set("set_hour_tenths", 140); time.sleep(2)
        for feel in (0, 1):
            ini_set("vehicle_feel", feel); time.sleep(1.5)
            day(f"day_{'after' if feel else 'before'}")
    elif phase == "night":
        ini_set("set_hour_tenths", 225); time.sleep(3)
        for feel in (0, 1):
            ini_set("vehicle_feel", feel); time.sleep(1.5)
            night(f"night_{'after' if feel else 'before'}")
        ini_set("set_hour_tenths", 140); time.sleep(2)
    elif phase == "wreck":
        for feel in (0, 1):
            ini_set("vehicle_feel", feel); time.sleep(1.5)
            wreck(f"wreck_{'after' if feel else 'before'}")
ini_set("vehicle_feel", 1)
mark("vehfeel done")

import pathlib
pathlib.Path("/out/.keys_done").touch()
