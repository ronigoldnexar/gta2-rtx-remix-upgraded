#!/usr/bin/env python3
"""POLISH-3 (1): the devtools scene warp must land on a floor. F10 at the configured
scene_xy, then the chase and first-person views at that spot, with the state words."""
import os, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
tag = os.environ.get("TAG", "warp")
s = Q.start(tag)
shot(f"{tag}_00_before")
say("before F10:", Q.words(s))
tap("F10", 0.3); time.sleep(2.5)
s = D.wait_state(); say("after F10:", Q.words(s))
Q.set_view("third"); time.sleep(1.5); shot(f"{tag}_01_third")
hold("Left", 0.8); time.sleep(0.8); shot(f"{tag}_02_third_turned")
Q.set_view("first"); time.sleep(1.5); shot(f"{tag}_03_first")
hold("Left", 1.0); time.sleep(0.8); shot(f"{tag}_04_first_turned")
hold("Right", 1.2); time.sleep(0.5); shot(f"{tag}_05_first_turned_back")   # no step onto the carriageway: traffic
s = D.wait_state(); say("RESULT:", Q.words(s))
Q.set_view("classic"); time.sleep(1.0); shot(f"{tag}_06_classic")
say("done")
