#!/usr/bin/env python3
"""VEHICLE-ART-4: the hero seated in every authored body. Gets into the parked car at the street
warp once, then for each model sets [devtools] force_car_model (third person, the driven car too)
and force_own_car_model (first person), waits for the ini re-read and shoots: third person still,
third person after a short drive with a turn (steering pose), first person. Frames /out/va4_<m>_<k>.png.
VA4_MODELS (default 36,13,8,56,63,68)."""
import os, re, subprocess, sys, time
sys.path.insert(0, "/work")
import feel_probe as F
from a3_lib import Q, T, D, say, tap, hold
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
def setmodel(m):
    s = open(INI, encoding="latin-1").read()
    s = re.sub(r"(?m)^force_car_model=.*$", f"force_car_model={m}", s)
    s = re.sub(r"(?m)^force_own_car_model=.*$", f"force_own_car_model={m}", s)
    open(INI, "w", encoding="latin-1").write(s)
def shot(name):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99",
                    "-frames:v", "1", f"/out/va4_{name}.png"])
    F.mark(f"shot {name}")
models = [int(x) for x in os.environ.get("VA4_MODELS", "36,13,8,56,63,68").split(",")]
T.warp(164.5, 147.6, 2, why="street")
F.into_car()
F.mark(f"driving {F.driving()}")
setmodel(models[0]); time.sleep(8.0)   # the first re-read
for m in models:
    setmodel(m)
    Q.set_view("third", settle=1.0)
    time.sleep(6.0)
    shot(f"{m:03d}_third")
    F.down("Up"); time.sleep(1.2); F.down("Left"); time.sleep(0.6)
    shot(f"{m:03d}_turn")
    time.sleep(0.6); shot(f"{m:03d}_turn2")
    F.up("Left"); F.up("Up"); F.down("Down"); time.sleep(0.8); F.up("Down"); time.sleep(1.0)
    Q.set_view("first", settle=1.5)
    time.sleep(2.0)
    shot(f"{m:03d}_first")
    Q.set_view("third", settle=1.0)
F.mark("done")
