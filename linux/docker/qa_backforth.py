#!/usr/bin/env python3
"""(b) Back and forth ten times with V presses mid-move; (g) rapid V presses while walking."""
import sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D

s = Q.start("backforth")
# face along the plaza (south) so there is room both ways
s = D.goto(s["x"], s["y"] + 4.0, tol=0.3, limit=6)
Q.set_view("third")
switch_at = {3: "v", 6: "v", 9: "v"}   # third -> first -> classic -> third
for n in range(1, 11):
    D.xdo("keydown", "Up"); time.sleep(0.5)
    if n in switch_at:
        tap("v", 0.25); say(f"V mid-move at {n}")
    time.sleep(0.7); D.xdo("keyup", "Up")
    D.xdo("keydown", "Down"); time.sleep(1.2); D.xdo("keyup", "Down")
    shot(f"bf_{n:02d}_{Q.current_view()}")
    say(f"leg {n}: {Q.words(D.wait_state())}")
Q.report("backforth")

# (g) rapid V presses while walking: 0.3 s apart for 10 s
say("rapid V")
D.xdo("keydown", "Up")
t0 = time.time(); n = 0
while time.time() - t0 < 10:
    tap("v", 0.12); n += 1; time.sleep(0.18)
D.xdo("keyup", "Up")
say(f"{n} V presses; view now {Q.current_view()}")
time.sleep(2.0); shot(f"rapidv_end_{Q.current_view()}")
hold("Up", 2.0); shot(f"rapidv_walk_{Q.current_view()}")
Q.set_view("first"); hold("Up", 1.5); shot("rapidv_first_after")
Q.set_view("classic"); shot("rapidv_classic_after")
Q.report("rapidv", presses=n)
say("done")
