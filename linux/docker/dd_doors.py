#!/usr/bin/env python3
"""Doors: the traffic with forced-open doors from the kerb (right, then left), then a real
re-entry filmed from the side (the orbit camera swung round by walking across the car)."""
import re, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
def setk(key, val):
    s = open(INI).read()
    s = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", s) if f"{key}=" in s else s.replace("[devtools]", f"[devtools]\n{key}={val}", 1)
    open(INI, "w").write(s); say(key, val); time.sleep(2.6)
def mark(w):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {w}\n")
s = Q.start("ddd")
tap("F10", 0.3); time.sleep(1.5); say("at the scene:", Q.words(D.wait_state()))
Q.set_view("third"); time.sleep(1.0)
for side in (1, -1):
    setk("force_car_door", side)
    for i in range(3):
        time.sleep(2.5); shot(f"ddd_kerb_third_door{'R' if side > 0 else 'L'}_{i}")
    Q.set_view("first"); time.sleep(1.2); shot(f"ddd_kerb_first_door{'R' if side > 0 else 'L'}"); Q.set_view("third"); time.sleep(0.8)
setk("force_car_door", 0)
# a car: F9 to its door, in, out, walk across its side so the camera orbits, back in
for attempt in range(3):
    tap("F9", 0.3); time.sleep(1.5); tap("Return", 0.3); t0 = time.time(); ok = False
    while time.time() - t0 < 8:
        s = D.wait_state()
        if s["driving"]: ok = True; break
        time.sleep(0.4)
    if ok: break
if ok:
    time.sleep(1.0); shot("ddd_in")
    mark("exit_start"); Q.leave_car(); mark("exit_done"); shot("ddd_out")
    hold("Left", 1.2); hold("Up", 1.6); time.sleep(0.5); hold("Right", 1.2); time.sleep(1.0); shot("ddd_side")
    mark("reenter_start"); tap("Return", 0.3); time.sleep(5.0); mark("reenter_done"); shot("ddd_reenter")
    say("end:", Q.words(D.wait_state()))
else:
    say("no car")
Q.report("ddd")
