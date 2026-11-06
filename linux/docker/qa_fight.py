#!/usr/bin/env python3
"""(c) Punch pedestrians in third person until the police react; keep going through
whatever follows (arrest, death), and check the views still follow the player."""
import sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D

s = Q.start("fight")
Q.set_view("third")
# The plaza south of the spawn has people; wander and punch (Ctrl is fire/punch, fists by default).
t0 = time.time(); n = 0; last = None
while time.time() - t0 < 150:
    s = D.wait_state()
    w = Q.words(s)
    if w != last: say(f"+{time.time()-t0:5.1f}s {w}"); last = w
    hold("Up", 0.8)
    for _ in range(4):
        tap("Control_L", 0.15); time.sleep(0.15)
    n += 1
    if n % 4 == 0:
        hold("Left" if (n // 4) % 2 else "Right", 0.5)
    if n % 6 == 0:
        shot(f"fight_{n:03d}_{Q.current_view()}")
    if n == 30:
        Q.set_view("first"); say("first person for the rest of the brawl")
    if n == 45:
        Q.set_view("third")
shot("fight_end_third")
Q.set_view("classic"); shot("fight_end_classic")
Q.report("fight", punches=n * 4)
say("done")
