#!/usr/bin/env python3
"""FIX-COCKPIT-CAB-3: seat view of a real vehicle. Warp to PROBE_X,PROBE_Y, wait for the game camera to hold him
(cam[] bounds), board the nearest car, first person: frames cs_<tag>_still / _left / _right / _drive / _look."""
import os, re, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot
X = float(os.environ.get("PROBE_X", "225.0")); Y = float(os.environ.get("PROBE_Y", "238.5")); TAG = os.environ.get("TAG", "x")
CAMB = re.compile(r"cam\[(\d+)\] bounds=([-\d.]+),([-\d.]+)\.\.([-\d.]+),([-\d.]+)")
def settle(timeout=45):
    t0 = time.time(); ok = 0; last = None
    while time.time() - t0 < timeout:
        m = CAMB.findall(Q.log_text(300000)); st = D.state()
        if m and st and m[-1][0] != last:
            last = m[-1][0]; x0, y0, x1, y1 = map(float, m[-1][1:])
            ok = ok + 1 if (x0 - 0.5 <= st["x"] <= x1 + 0.5 and y0 - 0.5 <= st["y"] <= y1 + 0.5) else 0
            if ok >= 2: say("MARK SETTLED", f"{time.time() - t0:.1f}s"); return True
        time.sleep(0.5)
    say("MARK NOT_SETTLED"); return False
Q.start("cab3_seat")
T.warp(X, Y, 2, why="vehicle")
settle()
s = T.get_in_scene_car()
say("MARK incar", Q.words(s) if s else None)
settle(20)
Q.set_view("first", settle=2.5)
shot(f"cs_{TAG}_still"); time.sleep(0.5)
D.xdo("keydown", "Left"); time.sleep(0.7); shot(f"cs_{TAG}_left"); D.xdo("keyup", "Left"); time.sleep(0.8)
D.xdo("keydown", "Right"); time.sleep(0.7); shot(f"cs_{TAG}_right"); D.xdo("keyup", "Right"); time.sleep(0.8)
D.xdo("keydown", "Up"); time.sleep(1.2); shot(f"cs_{TAG}_drive"); time.sleep(0.6); shot(f"cs_{TAG}_drive2"); D.xdo("keyup", "Up")
D.xdo("keydown", "Down"); time.sleep(1.0); D.xdo("keyup", "Down"); time.sleep(0.6)
Q.set_view("third", settle=2.0); shot(f"cs_{TAG}_third")
A.finish()
