#!/usr/bin/env python3
"""Chase camera at a railing: third person, F10 scene at the kerb (the railing
block behind the player), hold; get in, drive, leave, hold. Marks for strips."""
import sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
def mark(w):
    with open("/out/marks.txt","a") as f: f.write(f"{time.time():.3f} {w}\n")
s = Q.start("camexit3")
Q.set_view("third"); mark("third")
tap("F10", 0.3); time.sleep(1.5); s = D.wait_state(); say("after F10:", Q.words(s), f"parked d={s['pd']:.2f}")
mark("warp"); time.sleep(5); shot("cx_00_third_at_door")
hold("Left", 0.8); time.sleep(2); shot("cx_01_third_turned"); hold("Right", 0.8); time.sleep(1.5)
got = Q.get_in_car()
if got:
    mark("in"); D.xdo("keydown","Up"); time.sleep(5.0); D.xdo("keyup","Up"); hold("Down", 1.5); time.sleep(0.8)
    mark("exit"); Q.leave_car(); time.sleep(6); shot("cx_02_third_after_exit")
    say("after exit:", Q.words(D.wait_state()))
mark("end"); Q.report("camexit3")
