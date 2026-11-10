#!/usr/bin/env python3
"""ASSET-PEDS-3 (qav14): same-pose closeups of the re-split avatars. The private stage's manifest gives
remap 47 -> f004 only, 40 -> f001 only, 19 -> m009 only; GTA2DX9_PED_REMAP_FILE=Z:\\tmp\\ap3_remap.txt draws
every figure (the player's too) as that remap. Plaza (AP3_AT), third person; per remap fixed regress-camera
poses about 2 m (0.53 block) from him: front, front 3/4, side, back, back high (the hair bun), then a few
first-person frames walking into the crowd (all drawn as the remap). GTA2DX9_REGRESS_CAM=Z:\\tmp\\ap3_cam.txt."""
import os, sys, time
sys.path.insert(0, "/work")
exec(open("/work/fig3_heavy_probe.py").read().split("PICK = {")[0])
import a3_lib as A
import drive_lib as D
import tour_lib as T
from qa_lib import shot, say, tap, hold
import qa_lib as Q
CAM = "/tmp/ap3_cam.txt"; REM = "/tmp/ap3_remap.txt"
open(CAM, "w").close(); open(REM, "w").write("-1\n")
remaps = [int(v) for v in os.environ.get("AP3_REMAPS", "47,40,19").split(",")]
ax, ay, al = [float(v) for v in os.environ.get("AP3_AT", "159.5,139.5,2").split(",")]
T.warp(ax, ay, int(al), why="plaza"); time.sleep(3)
for k in ("Up", "Down"): hold(k, 0.3); time.sleep(0.3)
Q.set_view("third", settle=2.0)
s = D.wait_state(10)
A.face(s["x"] + 5, s["y"])
time.sleep(1.0)
s = D.wait_state(10)
x, y, fx, fy = s["x"], s["y"], s["fx"], s["fy"]
z = al; rx, ry = -fy, fx
mark(f"hero at {x:.2f},{y:.2f} facing {fx:.2f},{fy:.2f}")
def pose(df, ds, h, th=0.30, fov=45):
    ex = x + fx * df + rx * ds; ey = y + fy * df + ry * ds
    return f"{ex:.3f} {ey:.3f} {z + h:.3f} {x:.3f} {y:.3f} {z + th:.3f} {fov}"
POSES = (("front", pose(0.53, 0.0, 0.40)), ("q34", pose(0.38, 0.38, 0.40)), ("side", pose(0.0, 0.53, 0.40)),
         ("back", pose(-0.53, 0.0, 0.40)), ("bun", pose(-0.30, 0.12, 0.52, 0.42, 40)))
for r in remaps:
    open(REM, "w").write(f"{r}\n"); time.sleep(1.5)
    mark(f"remap {r}")
    for name, p in POSES:
        with open(CAM, "w") as f: f.write("cam " + p + "\n")
        time.sleep(1.0)
        shot(f"r{r:02d}_{name}")
        mark(f"r{r:02d} {name} cam {p}")
    open(CAM, "w").close(); time.sleep(0.5)
open(CAM, "w").close()
if os.environ.get("AP3_FIRST", "1") == "1":
    for r in remaps:
        open(REM, "w").write(f"{r}\n"); time.sleep(1.0)
        Q.set_view("first", settle=1.5)
        for n in range(6):
            hold("Up", 0.8); shot(f"r{r:02d}_fp{n}")
            if n % 2 == 1: hold("Left", 0.35)
        Q.set_view("third", settle=1.0)
mark("end")
A.finish()
