#!/usr/bin/env python3
"""A brawl in the classic view: does the game keep drawing a dead pedestrian's body,
and with which sprite? Screenshots every 2 s."""
import sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
s = Q.start("pedanim_classic")
t0 = time.time(); n = 0
while time.time() - t0 < 60:
    hold("Up", 0.5)
    for _ in range(5): tap("Control_L", 0.15); time.sleep(0.1)
    n += 1
    if n % 3 == 0:
        hold("Left", 0.95)
        for _ in range(4): tap("Control_L", 0.15); time.sleep(0.12)
    if n % 2 == 0: shot(f"c{n:02d}")
say("done")
