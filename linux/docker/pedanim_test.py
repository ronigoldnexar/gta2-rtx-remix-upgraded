#!/usr/bin/env python3
"""Pedestrian action clips on show: a brawl in third person (punches, knock-downs),
then a car entry and exit, with marks for the frame cuts."""
import sys, time, os
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
def mark(w):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {w}\n")
s = Q.start("pedanim")
Q.set_view("third"); mark("third")
say("brawl"); t0 = time.time(); n = 0
while time.time() - t0 < float(os.environ.get("PEDANIM_BRAWL", "40")):
    hold("Up", 0.5)
    for _ in range(5): tap("Control_L", 0.15); time.sleep(0.1)
    n += 1
    if n % 3 == 0:
        # About-turn, then punch at once: the chase camera is still swinging round,
        # so the swing is seen from the side and the front.
        hold("Left", 0.95); mark(f"turnpunch{n}")
        for _ in range(4): tap("Control_L", 0.15); time.sleep(0.12)
    if n == 8: shot("brawl_a")
    if n == 16: shot("brawl_b")
mark("brawl_end"); shot("brawl_end")
import os
if os.environ.get("PEDANIM_SHORT"): mark("end"); say("done"); sys.exit(0)
say("first person punches"); Q.set_view("first"); mark("first")
for _ in range(6): tap("Control_L", 0.15); time.sleep(0.4)
shot("first_punch"); Q.set_view("third"); mark("third2")
say("car entry via F10"); tap("F10", 0.3); time.sleep(1.5); mark("return_in"); tap("Return", 0.3); time.sleep(0.6); shot("climb_a"); time.sleep(0.6); shot("climb_b"); time.sleep(2.5)
shot("in_car"); hold("Up", 2.0); time.sleep(0.5); mark("return_out"); tap("Return", 0.3); time.sleep(0.6); shot("out_a"); time.sleep(0.6); shot("out_b"); time.sleep(2)
shot("out_c"); mark("end"); say("done")
