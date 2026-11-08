#!/usr/bin/env python3
"""Dents at forced damage steps (0/96/160/255): the traffic from the kerb in third and first
person, then at the wheel of a car, then the door swing on exit and re-entry."""
import re, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
STEPS = (0, 96, 160, 255)
def force(damage):
    s = open(INI).read()
    s = re.sub(r"(?m)^force_car_damage=.*$", f"force_car_damage={damage}", s) if "force_car_damage=" in s else s.replace("[devtools]", f"[devtools]\nforce_car_damage={damage}", 1)
    open(INI, "w").write(s); say("force_car_damage", damage); time.sleep(2.6)
def mark(w):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {w}\n")
def get_car():
    """F9: the player warped to the nearest parked car's door; Return gets in. Else wait at the kerb for a stopping car."""
    for attempt in range(3):
        tap("F9", 0.3); time.sleep(1.5)
        s = D.wait_state(); say(f"after F9 ({attempt}):", Q.words(s), f"parked d={s['pd']:.2f}")
        tap("Return", 0.3); t0 = time.time()
        while time.time() - t0 < 8:
            s = D.wait_state()
            if s["driving"]: say("in the car:", Q.words(s)); return s
            time.sleep(0.4)
    t0 = time.time()
    while time.time() - t0 < 90:
        s = D.wait_state()
        if s["car"] and s["cd"] < 1.3:
            tap("Return", 0.3); time.sleep(3.0); s = D.wait_state()
            if s["driving"]: say("in a stopped car:", Q.words(s)); return s
        time.sleep(0.5)
    return None
s = Q.start("dds")
tap("F10", 0.3); time.sleep(1.5); s = D.wait_state(); say("at the scene:", Q.words(s))   # to the carriageway kerb (with or without a car)
Q.set_view("third"); time.sleep(1.0)
for dmg in STEPS:
    force(dmg)
    Q.set_view("third"); time.sleep(1.2); shot(f"dds_kerb_third_{dmg:03d}"); time.sleep(2.5); shot(f"dds_kerb_third_{dmg:03d}_b")
    Q.set_view("first"); time.sleep(1.2); shot(f"dds_kerb_first_{dmg:03d}"); time.sleep(2.5); shot(f"dds_kerb_first_{dmg:03d}_b")
force(-1); Q.set_view("third"); time.sleep(0.8)
mark("enter_start"); got = get_car(); mark("enter_done")
if got:
    for dmg in STEPS:
        force(dmg)
        Q.set_view("third"); time.sleep(1.2); shot(f"dds_wheel_third_{dmg:03d}"); hold("Up", 1.0); time.sleep(0.8); shot(f"dds_wheel_third_{dmg:03d}_b")
        Q.set_view("first"); time.sleep(1.2); shot(f"dds_wheel_first_{dmg:03d}"); hold("Left", 0.5); time.sleep(0.6); shot(f"dds_wheel_first_{dmg:03d}_b"); hold("Right", 0.5)
    force(-1); Q.set_view("third"); time.sleep(1.0)
    mark("exit_start"); Q.leave_car(); mark("exit_done"); shot("dds_out")
    hold("Left", 0.8); time.sleep(0.6); shot("dds_out_look")
    mark("reenter_start"); tap("Return", 0.3); time.sleep(4.0); mark("reenter_done"); shot("dds_reenter")
else:
    say("no car for the wheel frames")
Q.report("dds")
