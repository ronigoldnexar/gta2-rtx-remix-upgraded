#!/usr/bin/env python3
"""(h) First person inside tall vehicles: the F10 scene car is whatever is parked
nearest, so take cars until a tall one (van/truck/bus class) comes; shoot the
driver's view each time, with the model number from the player line, in third and
first person while driving. Up to TALL_TRIES cars."""
import os, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D

# model numbers of tall vehicles (catalog classes van/truck/bus): bus 5, box truck 8, fire truck 16,
# garbage truck 21, bank van 1, tv van/van 68, truck cabs 63/64, trucks 17/58, ice cream 23, hot dog 24
TALL = {1, 5, 8, 16, 17, 21, 23, 24, 58, 63, 64, 68, 69, 70}
tries = int(os.environ.get("TALL_TRIES", "6"))
s = Q.start("tall")
Q.set_view("third")
seen = []
for k in range(tries):
    car = Q.get_in_car(attempts=2)
    if not car:
        say("no car this try"); continue
    m = car.get("cmodel", -1)
    seen.append(m)
    say(f"try {k}: in model {m} ({'TALL' if m in TALL else 'low'})")
    Q.set_view("first"); time.sleep(0.6); shot(f"tall_{k}_m{m}_first_still")
    hold("Up", 3.0); shot(f"tall_{k}_m{m}_first_drive"); hold("Left", 0.6); shot(f"tall_{k}_m{m}_first_turn")
    Q.set_view("third"); hold("Up", 2.0); shot(f"tall_{k}_m{m}_third_drive")
    hold("Down", 1.0); Q.leave_car(); time.sleep(0.8)
    # walk a few blocks so the next F10 finds a different parked car
    hold("Up", 3.0); hold("Left", 1.0); hold("Up", 3.0)
    if m in TALL and len([x for x in seen if x in TALL]) >= 2: break
Q.report("tall", models=seen, tall=[x for x in seen if x in TALL])
say("done")
