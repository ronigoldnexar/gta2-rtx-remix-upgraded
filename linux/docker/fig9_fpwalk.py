#!/usr/bin/env python3
"""FIX-FIGURE-9 pm7-fp: the open plaza in first person, walking back and forth among passers-by (30 fps burst)."""
import os, sys, time
sys.path.insert(0, "/work")
import feel_probe as F
from feel_probe import *
exec(open("/work/fig3_heavy_probe.py").read().split("PICK = ")[0].split("from feel_probe import *")[1])
T.warp(159.5, 139.5, 2, why="open plaza")
time.sleep(9)
Q.set_view("first", settle=3.0); F.mark(f"view {Q.current_view()}")
p = F.burst("fp_walk", 40.0)
for r in range(6):
    hold("Up", 2.5); time.sleep(0.8); hold("Down", 1.5); time.sleep(0.8); hold("Left", 0.3); time.sleep(0.6)
p.wait()
A.save_log(); A.finish()
