#!/usr/bin/env python3
"""(e) Die (run over in the carriageway, or shot after provoking the police) and continue
after the respawn in every view."""
import math, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
import gmp

s = Q.start("death")
# To the carriageway the way the demo walker goes (route from the map), then into the lanes.
level = int(s["z"]) - 1
blocks, columns = gmp.load("/tmp/wp/drive_c/Games/GTA2/data/wil.gmp")
path = gmp.route_to(blocks, columns, int(s["x"]), int(s["y"]), 156, 147, level) or []
say("route:", len(path), "cells")
for cx, cy in D.straighten(path)[1:]:
    s = D.goto(cx + 0.5, cy + 0.5, tol=0.5, limit=12)
Q.set_view("third")
s = D.goto(157.0, 149.6, tol=0.3, limit=8)
say("in the lane:", Q.words(s))
start = (s["x"], s["y"]); t0 = time.time(); died = False; last = ""; leg = 0
shot("death_00_third_lane")
while time.time() - t0 < 170:
    s = D.wait_state()
    w = Q.words(s)
    if w != last: say(f"+{time.time()-t0:5.1f}s {w}"); last = w
    jump = math.hypot(s["x"] - start[0], s["y"] - start[1])
    if jump > 12 or Q.counts()["waiting"] > 0 or s["state"] in (11, 12, 13):
        died = True; say("dead, respawned or lost:", w); break
    leg += 1
    ty = 150.6 if leg % 2 else 148.4
    s = D.goto(start[0] + (leg % 3) * 0.7, ty, tol=0.3, limit=4)
    if leg % 6 == 0: shot(f"death_wait_{int(time.time()-t0):03d}")
shot(f"death_01_after_{Q.current_view()}")
say("died:", died)
# whatever happened, exercise the views now
for view in ("third", "first", "classic", "third"):
    Q.set_view(view); hold("Up", 1.5); shot(f"death_02_{view}")
    say(f"{view}: {Q.words(D.wait_state())}")
Q.report("death", died=died)
say("done")
