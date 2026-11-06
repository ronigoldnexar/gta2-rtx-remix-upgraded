#!/usr/bin/env python3
"""POLISH-3 (2): leave the car at the kerb in first person, three times, and look round:
the eye must not sit inside a bin, bench or meter (props are kept off the doors)."""
import os, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
tag = os.environ.get("TAG", "exit")
s = Q.start(tag)
for i in range(3):
    car = Q.get_in_car(attempts=2)
    if not car:
        say(f"round {i}: no car"); continue
    Q.set_view("third"); hold("Up", 2.5 + i * 1.5); hold("Down", 1.5); time.sleep(0.6)
    Q.set_view("first"); time.sleep(0.8)
    Q.leave_car(); time.sleep(1.2)
    s = D.wait_state(); say(f"round {i} out: {Q.words(s)}")
    shot(f"{tag}_{i}_first_out"); hold("Left", 0.8); time.sleep(0.5); shot(f"{tag}_{i}_first_out_left")
    hold("Right", 1.6); time.sleep(0.5); shot(f"{tag}_{i}_first_out_right")
    Q.set_view("third"); time.sleep(1.0); shot(f"{tag}_{i}_third_out")
    Q.set_view("classic"); time.sleep(0.5)
say("done")
