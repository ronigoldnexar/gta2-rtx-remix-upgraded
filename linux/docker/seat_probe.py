#!/usr/bin/env python3
"""FIX-SEATED probe: the driver seated at the wheel in third person (Minx 013 at 120.5,152.5 by default, SEAT_XY).
Boards by walking up (F9 + Return), films parked (chase + orbit to the side), a drive with turns, first person,
the exit; classic-view stills at the start (before boarding) and parked in the car for the byte diff.
Run with GTA2DX9_SCENE_NO_CAR=1, INI_SED scene_key=F10, warp_key=F9, GTA2_DIRECT_KEYS=1."""
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
    t0 = time.time()
    while time.time() - t0 < secs:
        D.xdo("mousemove_relative", "--", str(dx), "0"); time.sleep(0.03)


def down(k): D.xdo("keydown", k)
def up(k): D.xdo("keyup", k)
def driving():
    s = D.wait_state(); return bool(s and s["driving"])


def main():
    ex, ey = (float(v) for v in os.environ.get("SEAT_XY", "120.5,152.5").split(","))
    T.warp(ex, ey, 2, why="street with a parked Minx")
    time.sleep(1.5)
    Q.set_view("classic", settle=2.0); Q.shot("classic_foot")
    Q.set_view("third", settle=1.0)
    p = burst("board", 7.0)
    tap("F9", 0.3); time.sleep(1.5); tap("Return", 0.3)
    t0 = time.time()
    while not driving() and time.time() - t0 < 6: time.sleep(0.3)
    p.wait(); mark(f"driving {driving()}")
    if not driving():
        tap("F9", 0.3); time.sleep(1.5); tap("Return", 0.3); time.sleep(5)
    Q.set_view("classic", settle=2.0); Q.shot("classic_car")
    Q.set_view("third", settle=2.0)
    p = burst("parked_orbit", 8.0)
    time.sleep(1.5); orbit(14, 2.2); time.sleep(1.5); orbit(14, 2.2); time.sleep(0.5)
    p.wait()
    p = burst("drive_third", 12.0)
    time.sleep(0.4); down("Up"); time.sleep(2.5)
    down("Left"); time.sleep(0.9); up("Left"); time.sleep(1.0)
    down("Right"); time.sleep(0.8); up("Right"); time.sleep(1.2); up("Up")
    down("Down"); time.sleep(1.0); up("Down")
    p.wait()
    Q.set_view("first", settle=1.5)
    p = burst("drive_first", 4.0); time.sleep(0.3); down("Up"); time.sleep(2.0); up("Up"); p.wait()
    Q.set_view("third", settle=2.0)
    p = burst("exit_third", 6.0)
    time.sleep(1.0); tap("Return", 0.3); time.sleep(3.0); hold("Up", 0.8)
    p.wait()
    A.save_log()


if __name__ == "__main__":
    main()
