#!/usr/bin/env python3
"""ANIM-VEHICLE-ENTRY probe: a full exit and a full entry of a parked car, third person, filmed at
30 fps (x11grab bursts /out/b_<label>.mp4). Downtown street with parked cars (same spot as a34_probe).
ENTRY_ROUNDS (default 2) repeats exit+enter. Run with GTA2DX9_SCENE_NO_CAR=1, GTA2DX9_LOG_PED_FRAMES=1,
GTA2DX9_LOG_FIGURES=1, INI_SED scene_key=F10, warp_key=F9, nav_map=0."""
import os, subprocess, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold


def mark(w):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {w}\n")
    say("MARK", w)


def burst(label, secs, fps=30):
    mark(f"burst {label} {secs}")
    return subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-framerate", str(fps),
                             "-video_size", "1280x720", "-i", ":99", "-t", str(secs), "-c:v", "libx264",
                             "-preset", "ultrafast", "-crf", "14", "-pix_fmt", "yuv420p", f"/out/b_{label}.mp4"])


def orbit(dx, secs):
    """the mouse orbit of the third-person camera (mouse_look=1): dx pixels every 30 ms"""
    mark(f"orbit {dx} {secs}")
    t0 = time.time()
    while time.time() - t0 < secs:
        D.xdo("mousemove_relative", "--", str(dx), "0")
        time.sleep(0.03)


def driving():
    s = D.wait_state(); return bool(s and s["driving"])


def into_car(tries=3):
    for _ in range(tries):
        if driving(): return True
        tap("F9", 0.3); time.sleep(1.5); tap("Return", 0.3)
        t0 = time.time()
        while time.time() - t0 < 8:
            if driving(): return True
            time.sleep(0.4)
    return driving()


def main():
    T.warp(164.5, 147.6, 2, why="street with parked cars")
    time.sleep(1.0)
    if not into_car():
        mark("no car"); A.save_log(); return
    Q.set_view("third", settle=2.0)
    for k in range(int(os.environ.get("ENTRY_ROUNDS", "2"))):
        time.sleep(1.0)
        side = int(os.environ.get("ENTRY_ORBIT", "12"))
        if k % 2 == 1 and side: orbit(side, 0.8); time.sleep(0.5)
        p = burst(f"exit_{k}", 5.0)
        time.sleep(0.6); tap("Return", 0.3)
        t0 = time.time()
        while driving() and time.time() - t0 < 3.0: time.sleep(0.2)
        p.wait()
        mark(f"out {k}: {Q.words(D.wait_state())}")
        # a step away from the door so the walk back, the reach and the climb are all seen
        hold("Down", 0.3); time.sleep(1.2)
        if k % 2 == 1 and side: orbit(side, 0.8); time.sleep(0.5)
        p = burst(f"enter_{k}", 6.0)
        time.sleep(0.5); tap("Return", 0.3)
        t0 = time.time()
        while not driving() and time.time() - t0 < 4.0: time.sleep(0.2)
        p.wait()
        mark(f"enter {k}: {Q.words(D.wait_state())}")
        if not driving() and not into_car(): mark("could not get back in"); break
        A.save_log()
    A.save_log()


if __name__ == "__main__":
    main()
