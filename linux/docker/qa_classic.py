#!/usr/bin/env python3
"""(i) The classic view must be the game as before: stand still at the spawn and
shoot the classic frame, then switch to third person and back and shoot again
(same spot), then walk to the carriageway and shoot classic with traffic. The
host-side check compares these against the same frames from a build with the
ground-view features off (QA_SED turns them off in the second run)."""
import sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D

s = Q.start("classic")
time.sleep(2.0); shot("cl_00_spawn")
Q.set_view("third"); time.sleep(1.0); Q.set_view("classic"); time.sleep(3.0); shot("cl_01_spawn_after_switch")
# a fixed walk: 3 s north-east-ish, same every run
hold("Up", 3.0); time.sleep(2.0); shot("cl_02_walked")
Q.report("classic")
say("done")
