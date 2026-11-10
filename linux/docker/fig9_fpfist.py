#!/usr/bin/env python3
"""FIX-FIGURE-9: first-person fists: the plaza, first person, unarmed: the guard, then punches (Ctrl taps), 30 fps."""
import os, sys, time
sys.path.insert(0, "/work")
import feel_probe as F
from feel_probe import *
exec(open("/work/fig3_heavy_probe.py").read().split("PICK = ")[0].split("from feel_probe import *")[1])
T.warp(159.5, 139.5, 2, why="open plaza")
time.sleep(9)
Q.set_view("first", settle=3.0); F.mark(f"view {Q.current_view()} weapon {A.weapon_name()}")
p = F.burst("fp_fist", 9.0); time.sleep(1.5)
for _ in range(6): tap("Control_L", 0.12); time.sleep(0.55)
time.sleep(1.0); hold("Up", 1.5)
p.wait()
A.save_log(); A.finish()
