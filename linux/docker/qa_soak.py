#!/usr/bin/env python3
"""(f2) A soak in whatever district is loaded: walk in each view, take the F10 car,
drive in each view, leave it, repeat, for SOAK_SECONDS (default 540). Collects the
frame-time summaries and the texture-memory lines at the end."""
import os, re, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D

secs = int(os.environ.get("SOAK_SECONDS", "540"))
tag = os.environ.get("SOAK_TAG", "soak")
s = Q.start(tag)
t0 = time.time(); lap = 0
shot(f"{tag}_00_classic_start")
while time.time() - t0 < secs:
    lap += 1
    for view in ("third", "first"):
        Q.set_view(view)
        hold("Up", 2.5); hold("Left", 0.7); hold("Up", 2.0); hold("Right", 1.2); hold("Up", 2.0)
        shot(f"{tag}_{lap:02d}_{view}_walk")
    car = Q.get_in_car(attempts=2)
    if car:
        for view in ("third", "first", "classic"):
            Q.set_view(view)
            hold("Up", 4.0); hold("Left", 0.5); hold("Up", 3.0); hold("Right", 0.8); hold("Up", 2.0)
            shot(f"{tag}_{lap:02d}_{view}_drive")
        hold("Down", 1.2)
        Q.leave_car(); time.sleep(1.0); shot(f"{tag}_{lap:02d}_exit_{Q.current_view()}")
    Q.set_view("classic"); hold("Up", 1.5)
    say(f"lap {lap} at +{time.time()-t0:.0f}s: {Q.words(D.wait_state())}")
# texture memory and frame summaries
t = Q.log_text()
mem = [l.split("] ", 1)[1] for l in t.splitlines() if "textures," in l and "managed pool" in l]
say("MEM", mem[-1] if mem else "no memory line")
fs = Q.frame_summaries()
say("FRAMES", len(fs), "summaries; last:", fs[-1] if fs else "none")
Q.report(tag, laps=lap)
say("done")
