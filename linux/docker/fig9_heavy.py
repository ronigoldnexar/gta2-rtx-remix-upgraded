#!/usr/bin/env python3
"""FIX-FIGURE-9 feel12: heavy weapons side-on. Pickups (flamethrower, molotov, launcher), the open plaza, a step so the
hero is drawn after the warp, third person; the drawn figure turned 90 deg (GTA2DX9_RIG_TEST_FILE=/tmp/rigtest
'yaw period off stance'). Per weapon: idle 1 s, taps, a held trigger. FIG9_AB=1: each weapon again with the rig file's
4th field 0 (old behaviour switch, if the build reads it). FIG9_WEAPONS=flame,molotov,rocket. 30 fps bursts."""
import os, sys, time
sys.path.insert(0, "/work")
import feel_probe as F
from feel_probe import *
exec(open("/work/fig3_heavy_probe.py").read().split("PICK = ")[0].split("from feel_probe import *")[1])  # whole-log view helpers
RT = "/tmp/rigtest"
def rig(yaw, period=0, off=0, stance=1):
    for pth in (RT, "/tmp/wp/drive_c/tmp/rigtest", "/tmp/wp/drive_c/Games/GTA2/rigtest"):
        try:
            os.makedirs(os.path.dirname(pth), exist_ok=True); open(pth, "w").write(f"{yaw} {period} {off} {stance}\n")
        except Exception: pass
    F.mark(f"rigtest {yaw} {period} {off} {stance}"); time.sleep(0.8)
def select(name):
    for _ in range(8):
        if A.weapon_name() == name: return True
        tap("z", 0.2); time.sleep(0.8)
    return A.weapon_name() == name
PICK = {"rocket": (154.5, 129.5, 2, "rocket_launcher"), "flame": (19.5, 35.5, 4, "flamethrower"),
        "molotov": (164.5, 118.5, 6, "molotov")}
W = os.environ.get("FIG9_WEAPONS", "flame,molotov,rocket").split(",")
YAW = int(os.environ.get("FIG9_YAW", "90"))
rig(0)
for k in W: A.collect(*PICK[k])
T.warp(159.5, 139.5, 2, why="open plaza")
time.sleep(9)
Q.set_view("third", settle=4.0)
hold("Up", 0.5); time.sleep(1.0); hold("Down", 0.3); time.sleep(1.5)
F.mark(f"view {Q.current_view()}")
# FIG9_PASSES: per weapon "yaw:stance" list, e.g. flame=90:1,0:1;molotov=90:1,90:0
PASSES = {}
for part in os.environ.get("FIG9_PASSES", "").split(";"):
    if "=" in part:
        w, l = part.split("=", 1); PASSES[w] = [tuple(int(v) for v in x.split(":")) for x in l.split(",")]
for k in W:
    F.mark(f"select {k} {select(PICK[k][3])}")
    for yaw, st in PASSES.get(k, [(YAW, 1)]):
        rig(yaw, 0, 0, st)
        p = F.burst(f"h_{k}_y{yaw}_s{st}", 6.5); time.sleep(1.0)
        for _ in range(2): tap("Control_L", 0.12); time.sleep(1.1)
        down("Control_L"); time.sleep(1.4); up("Control_L")
        p.wait()
rig(0)
A.save_log()
A.finish()
