#!/usr/bin/env python3
"""FIX-CAR-SHADING-1: frame-time A/B of the car coat pass in one session. Warp to the street, sit in the car,
third person, a fixed regression camera down the street (traffic passes), then [devtools] car_coat toggled
0/1 every PERIOD s for CYCLES cycles; marks 'coat=N' in keys.log for the analysis (csh_perf_an.py)."""
import os, re, sys, time, math
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
time.sleep(3.0)
T.warp(float(os.environ.get("WX", "164.5")), float(os.environ.get("WY", "147.6")), 2, why="street"); F.into_car()
Q.set_view("third", settle=1.0); time.sleep(4.0)
s = D.wait_state(10)
x, y, z = s["x"], s["y"], s["z"]
fx, fy = (s["chx"], s["chy"]) if abs(s.get("chx", 0)) + abs(s.get("chy", 0)) > 0.1 else (s["fx"], s["fy"])
n = math.hypot(fx, fy) or 1.0; fx, fy = fx / n, fy / n
# behind and above the car, looking down the street ahead (the car and the traffic in frame)
cam(f"cam {x - fx * 1.6:.3f} {y - fy * 1.6:.3f} {z + 0.9:.3f} {x + fx * 4:.3f} {y + fy * 4:.3f} {z:.3f} 55")
time.sleep(3.0)
for c in range(int(os.environ.get("CYCLES", "3"))):
    for v in (0, 1):
        setkey("car_coat", v); time.sleep(2.5); F.mark(f"coat={v} start")
        time.sleep(float(os.environ.get("PERIOD", "18"))); F.mark(f"coat={v} end")
setkey("car_coat", -1)
F.mark("done")
