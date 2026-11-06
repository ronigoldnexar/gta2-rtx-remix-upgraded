#!/usr/bin/env python3
"""Provoke pedestrian animation states on the player: punching, a car entry and exit,
standing in traffic, with the renderer logging his frame/state changes."""
import sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
s = Q.start("pedanim")
Q.set_view("third")
say("punching"); t0 = time.time(); n = 0
while time.time() - t0 < 40:
    hold("Up", 0.6)
    for _ in range(4): tap("Control_L", 0.15); time.sleep(0.12)
    n += 1
    if n % 3 == 0: hold("Left" if (n // 3) % 2 else "Right", 0.4)
shot("after_punch")
say("car entry via F10"); tap("F10", 0.3); time.sleep(1.5); tap("Return", 0.3); time.sleep(4)
shot("entered"); hold("Up", 3); tap("Return", 0.3); time.sleep(3); shot("exited")
say("standing in the carriageway"); hold("Down", 1.0); t0 = time.time()
while time.time() - t0 < 60:
    time.sleep(2); hold("Left", 0.2)
shot("end")
say("done")
