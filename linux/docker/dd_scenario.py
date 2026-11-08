#!/usr/bin/env python3
"""Doors and dents: into a car (door swings), three wall hits (dents, smoke), out (door), in again."""
import sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
def mark(w):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {w}\n")
s = Q.start("dd")
Q.set_view("third"); time.sleep(1.0); shot("dd_00_third")
mark("enter_start")
got = Q.get_in_car()
mark("enter_done")
if not got:
    say("no car"); Q.report("dd"); sys.exit(0)
shot("dd_01_in_car"); time.sleep(1.0)
for i in range(3):
    mark(f"ram{i}")
    D.xdo("keydown", "Up"); time.sleep(2.0 + 0.6 * i); D.xdo("keyup", "Up"); time.sleep(0.6)
    shot(f"dd_02_after_ram{i}"); say(f"after ram {i}:", Q.words(D.wait_state()))
    hold("Down", 1.6); time.sleep(0.4)
    hold("Left", 0.4) if i % 2 == 0 else hold("Right", 0.4)
for i in range(4):
    # head-on into the traffic: swing across the lane and hold the throttle
    D.xdo("keydown", "Up"); hold("Left" if i % 2 == 0 else "Right", 0.8); time.sleep(4.5); D.xdo("keyup", "Up"); time.sleep(0.8)
    shot(f"dd_03_more_ram{i}"); say(f"after traffic ram {i}:", Q.words(D.wait_state()))
    hold("Down", 1.5); time.sleep(0.5)
time.sleep(1.0); shot("dd_04_damaged_third")
Q.set_view("first"); time.sleep(1.0); shot("dd_05_damaged_first")
Q.set_view("third"); time.sleep(1.0)
mark("exit_start"); s = Q.leave_car(); mark("exit_done"); shot("dd_06_out")
hold("Left", 0.8); time.sleep(0.5); shot("dd_07_look_back")
mark("reenter_start"); tap("Return", 0.3); time.sleep(4.0); mark("reenter_done"); shot("dd_08_reenter")
say("end:", Q.words(D.wait_state())); Q.report("dd")
