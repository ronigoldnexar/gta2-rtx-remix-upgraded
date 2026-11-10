#!/usr/bin/env python3
"""FIX-CAR-IDENTITY-4 (tracked copy: linux/docker/paint_parity_probe.py, run by keys_paint_parity.sh): the paint apply across hues. The player's stopped car, forced to each model in MODELS, painted
(force_car_paint = a sprite's mean paint, brighter-half) in each of PAINTS, shot from the top pose (the classic
camera) under each devtools mode in MODES. Frames /out/pt_<model>_<paint>_<mode>.png; marks in keys.log."""
import os, re, subprocess, sys, time, math
sys.path.insert(0, "/work")
import feel_probe as F
from a3_lib import Q, T, D, say
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
CAM = os.environ.get("VA2_CAM", "/tmp/va2_cam.txt")
def setkey(k, v):
    s = open(INI, encoding="latin-1").read()
    if re.search(rf"(?m)^{k}=", s): s = re.sub(rf"(?m)^{k}=.*$", f"{k}={v}", s)
    else: s = s.replace("[devtools]", f"[devtools]\n{k}={v}", 1)
    open(INI, "w", encoding="latin-1").write(s)
def cam(line):
    with open(CAM + ".tmp", "w") as f: f.write(line + "\n")
    os.replace(CAM + ".tmp", CAM)
def shot(name):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99",
                    "-frames:v", "1", f"/out/{name}.png"]); F.mark(f"shot {name}")
PAINTS = [("red", "133,65,65,189,109,108"), ("navy", "35,45,95,55,65,130"), ("black", "28,28,30,42,42,45"),
          ("yellow", "200,180,50,230,215,90"), ("green", "60,120,60,90,160,90"), ("white", "215,215,215,240,240,240"),
          ("teal", "60,93,102,90,130,140")]
MODES = [("old", {"paint_ref": 0, "paint_gain_percent": 100, "paint_spec_power": 26}),
         ("new", {"paint_ref": 1, "paint_gain_percent": 125, "paint_spec_power": 50})]
if os.environ.get("MODES"):
    MODES = [(x.split(":")[0], dict(kv.split("=") for kv in x.split(":")[1].split(";"))) for x in os.environ["MODES"].split("|") if x]
if os.environ.get("PAINTS"):
    PAINTS = [p for p in PAINTS if p[0] in os.environ["PAINTS"].split(",")]
POSES = {"top": (-0.08, 0.0, 5.0), "top3": (-0.6, 0.3, 3.0), "chase": (-1.7, 0.0, 0.75), "low": (-1.1, 0.25, 0.02), "under": (-0.7, 0.0, -0.05)}
T.warp(float(os.environ.get("WX", "164.5")), float(os.environ.get("WY", "147.6")), 2, why="street"); F.into_car(); F.mark(f"driving {F.driving()}")
Q.set_view("third", settle=1.0); time.sleep(4.0)
F.down("Up"); time.sleep(0.6); F.up("Up"); F.down("Down"); time.sleep(0.4); F.up("Down"); time.sleep(2.5)
for m in [x for x in os.environ.get("MODELS", "13,18,40").split(",") if x]:
    setkey("force_car_model", m); time.sleep(3.0)
    s = D.wait_state(10)
    x, y, z = s["x"], s["y"], s["z"]
    fx, fy = (s["chx"], s["chy"]) if abs(s.get("chx", 0)) + abs(s.get("chy", 0)) > 0.1 else (s["fx"], s["fy"])
    n = math.hypot(fx, fy) or 1.0; fx, fy = fx / n, fy / n
    rx, ry = -fy, fx
    say("model", m, "at", x, y, z, "head", fx, fy)
    for pose in os.environ.get("POSES", "top").split(","):
        f, r, u = POSES[pose]
        cam(f"cam {x + fx * f + rx * r:.3f} {y + fy * f + ry * r:.3f} {z + u:.3f} {x:.3f} {y:.3f} {z + (0.18 if pose in ("low", "under") else 0.10):.3f} 50")
        time.sleep(0.8)
        for pl, pv in PAINTS:
            setkey("force_car_paint", pv)
            time.sleep(4.0)   # devtools re-read (60 frames) + the record's paint hold (45 frames)
            for ml, kv in MODES:
                for k, v in kv.items(): setkey(k, v)
                time.sleep(float(os.environ.get("SETTLE", "2.5")))
                shot(f"pt_{pose}_{int(m):03d}_{pl}_{ml}")
    cam(""); time.sleep(0.5)
setkey("force_car_model", -1)
F.mark("done")
