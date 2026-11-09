#!/usr/bin/env python3
"""FIX-FP probe (pm3-fp-eye-inside-passing-car-black-blue-body): out of the F10 scene car, first person on foot,
face the car and walk into it, then along it; bursts of shots. Logs the eye-car lines."""
import sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, D, say, hold, tap
import feel_probe as F
from qa_lib import shot
Q.start("fixfp_carface")
for i in range(4):
    s = D.wait_state()
    if s.get("cmodel", -1) >= 0 or s["driving"]: break
    tap("F10", 0.3); time.sleep(2.5)
tap("Return", 0.3); time.sleep(3.0)
s = D.wait_state(); say(f"out: at {s['x']:.2f},{s['y']:.2f} car {s['cx']:.2f},{s['cy']:.2f} d={s['cd']:.2f} driving={s['driving']}")
Q.set_view("first", settle=1.0)
# a full turn on the spot beside the car: some steps look straight at it from a hand away
for k in range(16):
    for i in range(2): shot(f"t{k:02d}_{i}"); time.sleep(0.1)
    hold("Left", 0.12); time.sleep(0.35)
s = D.wait_state(); say(f"after turn: at {s['x']:.2f},{s['y']:.2f} car d={s['cd']:.2f}")
A.save_log(); say("done")
