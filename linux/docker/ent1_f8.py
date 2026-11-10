#!/usr/bin/env python3
"""FIX-ENTRY-1: enter_key (B) from a spot where Return boards nothing. F9 to a parked car's door, walk away along it
facing away (~2.5 blocks), Return (refused: nothing within the game's reach), F8 (the game's own entry objective:
he walks back and boards), Return (out again), then the F9 + Return path unchanged."""
import sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import qa_lib as Q
import tour_lib as T
from qa_lib import say
from ent1_sweep_lib import st, wait_driving, wait_foot, face

Q.start("ent1f8")
Q.set_view("third", settle=1.0)
for rnd in (1, 2):
    D.tap("F9", 0.3); time.sleep(2.5)
    s = st(f"r{rnd} door")
    hx, hy = s["phx"], s["phy"]
    if s["pd"] > 1.5: hx, hy = s["chx"], s["chy"]
    face(-hx, -hy); D.hold("Up", 1.3); time.sleep(0.8)
    if rnd == 2: face(-hx, -hy)
    s = st(f"r{rnd} away"); Q.shot(f"r{rnd}_away")
    if rnd == 2:   # control: the game's Return from 2.5 blocks facing away (boarded in ent1_f8a)
        T.mark(f"r{rnd} Return away"); D.tap("Return", 0.10)
        s = wait_driving(5); st(f"r{rnd} after Return"); Q.shot(f"r{rnd}_after_return")
        if s and s["driving"]:
            D.tap("Return", 0.1); wait_foot(8); continue
    T.mark(f"r{rnd} enter_key"); D.tap("b", 0.15)
    for i in range(6): time.sleep(0.5); Q.shot(f"r{rnd}_f8_{i}")
    s = wait_driving(10); st(f"r{rnd} after F8"); Q.shot(f"r{rnd}_f8_seated"); time.sleep(1.5); Q.shot(f"r{rnd}_f8_seated2")
    if s and s["driving"]:
        Q.set_view("first", settle=1.0); Q.shot(f"r{rnd}_f8_first"); Q.set_view("third", settle=1.0)
        T.mark(f"r{rnd} Return after enter_key"); D.tap("Return", 0.10); wait_foot(8); time.sleep(0.8); st(f"r{rnd} exited"); Q.shot(f"r{rnd}_exited")
    time.sleep(1.0)
T.mark("F9 + Return"); D.tap("F9", 0.3); time.sleep(2.5); st("E door"); D.tap("Return", 0.3)
s = wait_driving(8); st("E after"); Q.shot("E_after")
say("done")
