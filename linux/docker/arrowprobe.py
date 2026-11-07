#!/usr/bin/env python3
"""Arrow-slot probe: answer the tutorial phone, get into the Messer, walk toward the
first box; the renderer dumps the arrow slots every half second."""
import sys, time, math
sys.path.insert(0, "/work")
import drive_lib as D, mission_lib as M
say, tap, hold = D.say, D.tap, D.hold
D.start(); s = D.wait_state(40); D.calibrate_turn()
world = M.World("wil")
tap("v", 0.3); time.sleep(1.7)                       # third person
ph = world.db["phones"]["obj86"]
M.walk3(world, ph["x"], ph["y"], None, tol=0.35, budget=120)
for k in range(10):
    hold("Up", 0.15); time.sleep(0.8)
    ms = M.mission_state()
    if ms and ms["msg"] not in ("", "svdone"): break
say("phone:", M.mission_state()); time.sleep(50)      # intro briefs
s = M.enter_car3(world, 156.5, 142.5, budget=90)
say("in car:", bool(s and s["driving"])); time.sleep(6)
M.leave_car(); time.sleep(3)
M.walk3(world, 188.5, 37.5, None, tol=0.4, budget=150)
say("at box 1"); time.sleep(8)
say("done")
