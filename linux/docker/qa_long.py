#!/usr/bin/env python3
"""(f) Eight minutes of everything on: driving with view changes, out and in, walking,
frame-time summaries and the car-model texture budget read back from the log."""
import sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D

s = Q.start("long")
for _ in range(40):
    s = D.wait_state()
    if s["parked"]: break
    hold("Up", 0.6); time.sleep(0.4)
t0 = time.time(); n = 0; views = ["third", "first", "classic"]
got = Q.get_in_car()
while time.time() - t0 < 480:
    n += 1
    view = views[n % 3]
    Q.set_view(view, settle=1.0)
    s = D.wait_state()
    if s["driving"]:
        hold("Up", 3.0); hold("Left" if n % 2 else "Right", 0.6); hold("Up", 2.0)
        if n % 5 == 0:
            Q.leave_car(); hold("Up", 1.5); hold("Left", 1.0); shot(f"long_{n:03d}_{view}_onfoot")
        elif n % 5 == 2:
            hold("Down", 2.0)
    else:
        hold("Up", 1.5); hold("Right", 0.6); hold("Up", 1.0)
        if n % 3 == 0:
            s = Q.get_in_car(attempts=1) or s
    if n % 4 == 0:
        shot(f"long_{n:03d}_{view}")
    say(f"+{time.time()-t0:5.1f}s n={n} {Q.words(D.wait_state())}")
shot("long_end")
c = Q.report("long", minutes=round((time.time() - t0) / 60, 1))
for line in Q.frame_summaries()[-12:]:
    say("FT", line)
for line in Q.log_text().splitlines():
    if "car models:" in line or "managed pool" in line:
        say("MEM", line.split("] ", 1)[-1])
say("done")
