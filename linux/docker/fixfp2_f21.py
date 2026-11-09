#!/usr/bin/env python3
"""FIX-FP-2 feel21 rocket: the filer's spot and facing (wil plaza 159.5,139.5 face -0.41,-0.91), third person,
cycle Z through machine gun / pistol / launcher twice, filmed at 30 fps; then the same in first person."""
import os, sys, time
sys.path.insert(0, "/work")
import feel_probe as F
from feel_probe import *
A.collect(166.5, 140.5, 2, "machine_gun"); A.collect(227.5, 210.5, 2, "pistol"); A.collect(154.5, 129.5, 2, "rocket_launcher")
T.warp(159.5, 139.5, 2, why="plaza")
for _ in range(60):   # one way round in small steps until he faces the filer's way (-0.41,-0.91)
    st = D.wait_state(); fx, fy = st.get("fx", 0.0), st.get("fy", 0.0)
    if fx * -0.407 + fy * -0.914 > 0.985: break
    hold("Left", 0.06); time.sleep(0.3)
mark(f"facing {D.wait_state()}")
Q.set_view("third", settle=1.5); time.sleep(6)
p = burst("f21_third", 16.0); time.sleep(0.5)
for i in range(9):
    tap("z", 0.15); time.sleep(0.15); mark(f"z -> {A.weapon_name()}"); time.sleep(1.2)
p.wait()
Q.set_view("first", settle=1.5)
p = burst("f21_first", 8.0); time.sleep(0.5)
for i in range(4):
    tap("z", 0.15); time.sleep(0.15); mark(f"fp z -> {A.weapon_name()}"); time.sleep(1.4)
p.wait()
# feel17: the pistol fired dry in first person (fists after the last shot), filmed at 30 fps
for _ in range(8):
    if A.weapon_name() == "pistol": break
    tap("z", 0.15); time.sleep(0.6)
mark(f"dry: weapon {A.weapon_name()}")
p = burst("f17_dry_fp", 14.0); time.sleep(0.3)
for _ in range(8): tap("Control_L", 0.10); time.sleep(0.4)
down("Control_L"); time.sleep(6.0); up("Control_L")
time.sleep(1.0); mark(f"after firing: weapon {A.weapon_name()}")
for _ in range(4): tap("Control_L", 0.12); time.sleep(0.6)
mark("punches done")
p.wait(); Q.set_view("third", settle=1.0)
p = burst("f21_back_third", 5.0); p.wait()
say("done")
