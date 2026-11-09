#!/usr/bin/env python3
"""QB-20/21/39 probe (mocap locomotion): the player's figure in third person on the open
plaza, Downtown, each item filmed as a 15 fps burst (/out/b_<label>.mp4):
  idle    standing 14 s (the idle, then a fidget after 5-13 s)
  start   standing, Up held 1.6 s, released (run start, run/sprint, run stop)
  tap     Up tapped 0.35 s twice (start straight into a stop)
  turn    Left 1.4 s, Right 0.7 s on the spot
  curve   Up held 3 s with Left over the middle second (lean into the turn), released
Run with GTA2DX9_SCENE_NO_CAR=1, GTA2DX9_LOG_FIGURES=1 and INI_SED scene_key=F10, warp_key=F9,
nav_map=0 (tank controls: Left/Right turn on the spot)."""
import os, subprocess, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold


def mark(w):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {w}\n")
    say("MARK", w)


def burst(label, secs, fps=15):
    mark(f"burst {label} {secs}")
    return subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(fps),
                             "-video_size", "1280x720", "-i", ":99", "-t", str(secs), "-c:v", "libx264",
                             "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", f"/out/b_{label}.mp4"])


T.warp(159.5, 139.5, 2, why="plaza")
Q.set_view("third", settle=1.5)
hold("Up", 0.5); time.sleep(2.0)          # the camera settles behind at walking distance
items = os.environ.get("QB20_ITEMS", "idle side start tap turn side2 curve side3").split()
for it in items:
    if it == "idle":
        p = burst("idle", 15.0); p.wait()
    elif it.startswith("start"):
        p = burst(it, 5.0); time.sleep(0.6); hold("Up", 1.6); p.wait(); time.sleep(0.5)
        hold("Left", 0.9); time.sleep(1.0)
    elif it.startswith("side"):
        # a quarter turn and straight off: the chase camera is still side-on for the start and stop
        p = burst(it, 4.5); time.sleep(0.3); hold("Left", 0.45); hold("Up", 1.1); p.wait(); time.sleep(1.5)
    elif it == "tap":
        p = burst("tap", 5.0); time.sleep(0.5); hold("Up", 0.35); time.sleep(1.6); hold("Up", 0.35); p.wait()
        time.sleep(0.5)
    elif it == "turn":
        p = burst("turn", 4.5); time.sleep(0.4); hold("Left", 1.4); time.sleep(0.6); hold("Right", 0.7); p.wait()
        time.sleep(0.5)
    elif it == "curve":
        p = burst("curve", 5.5); time.sleep(0.4)
        subprocess.run(["xdotool", "keydown", "Up"]); time.sleep(1.0)
        hold("Left", 1.0); time.sleep(1.0)
        subprocess.run(["xdotool", "keyup", "Up"]); p.wait()
        time.sleep(0.5)
    A.save_log()
mark("done")
