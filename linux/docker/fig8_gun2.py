#!/usr/bin/env python3
"""FIX-FIGURE-8 (pfl16, pm10, pm24) v2: pickups (MG, pistol), the plaza; a step so the hero is drawn after the
warp; third person pistol shots with the drawn figure turned 90 deg (side view; GTA2DX9_RIG_TEST_FILE=/tmp/rigtest:
'yaw period off stance'), new stance then the old (A/B, same session), then from behind; the MG side-on;
first person MG and pistol. 30 fps bursts."""
import os, sys, time
sys.path.insert(0, "/work")
import feel_probe as F
from feel_probe import *
RT = "/tmp/rigtest"
def rig(yaw, period=0, off=0, stance=1):
    for pth in (RT, "/tmp/wp/drive_c/tmp/rigtest", "/tmp/wp/drive_c/Games/GTA2/rigtest"):
        try:
            os.makedirs(os.path.dirname(pth), exist_ok=True); open(pth, "w").write(f"{yaw} {period} {off} {stance}\n")
        except Exception: pass
    F.mark(f"rigtest {yaw} {period} {off} {stance}"); time.sleep(0.8)
def select(name):
    for _ in range(6):
        if A.weapon_name() == name: return True
        tap("z", 0.2); time.sleep(0.8)
    return A.weapon_name() == name
def shots(n, gap=0.7):
    for _ in range(n): tap("Control_L", 0.1); time.sleep(gap)
rig(0)
A.collect(166.5, 140.5, 2, "machine_gun")
A.collect(227.5, 210.5, 2, "pistol")
T.warp(159.5, 139.5, 2, why="open plaza")
time.sleep(9)
Q.set_view("third", settle=2.0)
hold("Up", 0.5); time.sleep(1.0); hold("Down", 0.3); time.sleep(1.5)
F.mark(f"select pistol {select('pistol')}")
rig(90, 0, 0, 1)
p = F.burst("t_pistol_side_new", 4.5); time.sleep(0.6); shots(3); p.wait()
rig(90, 0, 0, 0)
p = F.burst("t_pistol_side_old", 4.5); time.sleep(0.6); shots(3); p.wait()
rig(0, 0, 0, 1)
p = F.burst("t_pistol_back_new", 4.5); time.sleep(0.6); shots(3); p.wait()
F.mark(f"select mg {select('machine_gun')}")
rig(90, 0, 0, 1)
p = F.burst("t_mg_side", 4.0); time.sleep(0.6); A.fire("mgx", secs=1.5, every=0.5); p.wait()
rig(0, 0, 0, 1)
Q.set_view("first", settle=2.0); time.sleep(1)
p = F.burst("f_mg", 5.0); time.sleep(1.0); A.fire("x", secs=1.5, every=0.5); time.sleep(0.5); hold("Left", 0.5); p.wait()
F.mark(f"select pistol {select('pistol')}"); time.sleep(1)
p = F.burst("f_pistol", 4.0); time.sleep(1.0); shots(3); p.wait()
A.save_log()
A.finish()
