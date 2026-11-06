#!/usr/bin/env python3
"""(h2) Chase camera behind a tall vehicle: take F10 cars until a tall one, drive it in
third person and shoot frames; the body's back must not fill the frame."""
import os, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
TALL = {1, 5, 8, 16, 17, 21, 23, 24, 58, 63, 64, 68, 69, 70}
s = Q.start("tallcam"); Q.set_view("third"); seen = []
for k in range(6):
    car = Q.get_in_car(attempts=2)
    if not car: continue
    m = car.get("cmodel", -1); seen.append(m); say(f"try {k}: model {m}")
    hold("Up", 3.0); shot(f"tc_{k}_m{m}_third_drive"); hold("Left", 0.7); hold("Up", 2.0); shot(f"tc_{k}_m{m}_third_turn")
    hold("Down", 1.0); Q.leave_car(); time.sleep(0.8); hold("Up", 3.0); hold("Left", 1.0); hold("Up", 3.0)
    if m in TALL: break
Q.report("tallcam", models=seen); say("done")
