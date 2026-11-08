#!/usr/bin/env python3
"""ACTIONS-3D probe 12, Downtown: drowning. The developer warp to 225.0,241.5
(beside the parked tank) leaves the player in the water; frames every 0.15 s in
third person, then first person; his frame/state words in the log (state 8 sub
0x14: in the water)."""
import os, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

s = Q.start("a3_water")
Q.set_view("third", settle=0.5)
say("MARK water")
T.warp(225.0, 241.5, 2, why="water by the tank")
Q.set_view("third", settle=0.0)
for i in range(16): shot(f"wa_{i:02d}"); time.sleep(0.1)
time.sleep(8.0)
say("MARK water 2 (first person)")
T.warp(225.0, 241.5, 2, why="water by the tank, again")
Q.set_view("first", settle=0.0)
for i in range(10): shot(f"wb_{i:02d}"); time.sleep(0.1)
A.finish()
