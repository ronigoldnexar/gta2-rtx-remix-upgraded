#!/usr/bin/env python3
"""FIX-KNOCKDOWN-4 pm3: warp beside the parked ambulance at ste (206.0,148.5, heading east) and walk the player into
its nose, then along its flank, third person, 30 fps bursts (KD4_AMB_VIEWS). Classic shot at the same spot."""
import os, sys, time, math
sys.path.insert(0, "/work")
import feel_probe as F
from feel_probe import *
import feel17_probe as X
vto = X.vto
SIGN = [1]
def cal_foot():
    s0 = D.wait_state(); hold("Left", 0.35); time.sleep(0.3); s1 = D.wait_state()
    turn = math.atan2(s0['fx']*s1['fy']-s0['fy']*s1['fx'], s0['fx']*s1['fx']+s0['fy']*s1['fy'])
    SIGN[0] = 1 if turn > 0 else -1; mark(f"foot cal turn {turn:+.2f} sign {SIGN[0]}")
def walk_to(x, y, secs):
    t0 = time.time(); down("Up")
    while time.time() - t0 < secs:
        s = D.wait_state(5)
        if not s: continue
        a = D.angle_to(s, x, y)
        up("Left"); up("Right")
        if abs(a) > 0.15: down("Left" if (a > 0) == (SIGN[0] > 0) else "Right")
        time.sleep(0.08)
    up("Up"); up("Left"); up("Right")
    mark(f"walked {D.wait_state()}")
for v in os.environ.get("KD4_AMB_VIEWS", "third,first").split(","):
    T.warp(208.3, 148.4, 2, why="beside the ambulance"); time.sleep(9); vto(v, 4.0)
    cal_foot(); T.warp(208.3, 148.4, 2, why="beside the ambulance"); time.sleep(4); vto(v, 3.0)
    p = burst(f"amb_{v}", 14.0); time.sleep(0.3)
    walk_to(205.0, 148.5, 5.0)      # into the nose, then on along the car (the game stops him at its box)
    walk_to(206.0, 149.6, 4.0)      # round to the flank
    walk_to(206.0, 148.5, 3.0)      # into the flank
    p.wait()
A.save_log()
