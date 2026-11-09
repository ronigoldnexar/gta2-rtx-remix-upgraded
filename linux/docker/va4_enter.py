#!/usr/bin/env python3
"""VEHICLE-ART-4: walk-up entry, drive and exit of the nearest parked car at a spot (VA4_XY, default the
playfeel1 plaza where a 036 Schmidt parks), third person; bursts b_enter / b_drive / b_exit at 30 fps."""
import os, sys, time
sys.path.insert(0, "/work")
import feel_probe as F
from a3_lib import Q, T, D, say, tap, hold
x, y = (float(v) for v in os.environ.get("VA4_XY", "159.5,139.5").split(","))
T.warp(x, y, 2, why="spot")
Q.set_view("third", settle=1.0); time.sleep(8.0)
tap("F9", 0.3); time.sleep(4.0)
if os.environ.get("VA4_WALKOFF", "0") == "1": hold("Left", 0.55); hold("Up", 0.5); time.sleep(1.0)
p = F.burst("enter", 7.0); time.sleep(0.3); tap("Return", 0.3)
t0 = time.time()
while not F.driving() and time.time() - t0 < 6: time.sleep(0.2)
p.wait(); F.mark(f"entered {F.driving()}")
if not F.driving(): F.into_car()
time.sleep(1.5)
p = F.burst("drive", 9.0); time.sleep(0.3)
F.down("Up"); time.sleep(2.5); F.down("Left"); time.sleep(0.8); F.up("Left"); time.sleep(1.0); F.up("Up"); F.down("Down"); time.sleep(1.0); F.up("Down")
p.wait()
time.sleep(1.5)
p = F.burst("exit", 6.0); time.sleep(0.5); tap("Return", 0.3); time.sleep(5.0); p.wait()
Q.set_view("first", settle=1.0); F.into_car(); time.sleep(2.5)
F.drive_lib_shot = None
import subprocess
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99", "-frames:v", "1", "/out/va4_first.png"])
F.mark("done")
