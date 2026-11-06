#!/usr/bin/env python3
"""(d) Take a car, crash it into traffic and walls at speed in third and first person,
leave it, re-enter, crash again; views switched in between."""
import sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D

s = Q.start("crash")
for _ in range(40):
    s = D.wait_state()
    if s["parked"]: break
    hold("Up", 0.6); time.sleep(0.4)
got = Q.get_in_car()
if not got:
    say("could not get a car"); Q.report("crash"); sys.exit(0)
shot("crash_00_classic_wheel")
Q.set_view("third"); shot("crash_01_third_wheel")
# full speed ahead east along the carriageway: traffic and the junction ahead
hold("Up", 4.0); shot("crash_02_third_speed")
hold("Up", 4.0); shot("crash_03_third_impact")
say("after 8 s ahead:", Q.words(D.wait_state()))
hold("Down", 3.0); shot("crash_04_third_reverse")
# swing into the kerb/buildings: hard left while accelerating
D.xdo("keydown", "Up"); hold("Left", 1.5); time.sleep(2.0); D.xdo("keyup", "Up"); shot("crash_05_third_wall")
say("after the wall:", Q.words(D.wait_state()))
Q.set_view("first"); shot("crash_06_first_wheel")
hold("Down", 2.0); D.xdo("keydown", "Up"); hold("Right", 1.2); time.sleep(3.0); D.xdo("keyup", "Up"); shot("crash_07_first_impact")
hold("Up", 3.0); shot("crash_08_first_more")
say("first person crashes:", Q.words(D.wait_state()))
# out of the car in first person, look around, back in
s = Q.leave_car(); shot("crash_09_first_out")
hold("Left", 1.0); shot("crash_10_first_out_turned"); hold("Right", 1.0)
Q.set_view("third"); shot("crash_11_third_out")
tap("Return", 0.3); time.sleep(3.0); s = D.wait_state(); say("re-enter:", Q.words(s)); shot("crash_12_third_reenter")
if not s["driving"]:
    hold("Up", 0.5); tap("Return", 0.3); time.sleep(3.0); s = D.wait_state(); say("re-enter 2:", Q.words(s))
hold("Up", 3.0); shot("crash_13_third_drive_again")
Q.set_view("classic"); hold("Up", 2.0); shot("crash_14_classic_drive")
Q.set_view("first"); hold("Up", 2.0); shot("crash_15_first_drive")
Q.report("crash", driving_lines=Q.log_text().count(" driving |"))
say("done")
