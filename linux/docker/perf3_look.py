#!/usr/bin/env python3
"""PERF-3 look check: the same frames from two builds, for an A/B strip. Three Downtown spots
(scene warp, so the same parked car and heading every run) in the chase and first-person
views on foot; then the traffic at the spawn with [devtools] force_car_damage 0/8000/25000 and
force_car_door 1; then the player's own car with set_car_damage 0/4000/8000/16000/25000 written at the
wheel (the game's own damage word; written alone it does not light the car), each seen on foot. Shots in /out/t_*.png,
marks in /out/marks.txt."""
import os, re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, Q, say, tap, mark, shot, view, warp
INI = T.INI
def setk(key, val):
    s = open(INI, encoding="latin-1").read()
    s = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", s) if f"{key}=" in s else s.replace("[devtools]", f"[devtools]\n{key}={val}", 1)
    open(INI, "w", encoding="latin-1").write(s); mark(f"SET {key}={val}")
T.Q.start("perf3_look")
for i, spot in enumerate([(164.5, 149.5), (122.5, 155.5), (124.5, 212.5)]):
    warp(*spot, None, why=f"look spot {i}")
    view("third"); time.sleep(3.0); shot(f"spot{i}_third")
    view("first"); time.sleep(2.5); shot(f"spot{i}_first")
warp(164.5, 149.5, None, why="traffic at the spawn"); view("third"); time.sleep(2.0)
for dmg in (0, 8000, 25000):
    setk("force_car_damage", dmg); time.sleep(3.5); shot(f"force_dmg{dmg}")
setk("force_car_door", 1); time.sleep(3.5); shot("force_door_right")
setk("force_car_door", 0); setk("force_car_damage", -1); time.sleep(1.5)
for attempt in range(3):   # a fresh scene warp each time, as perf2_drive.py does
    warp(164.5, 149.5, None, why=f"a parked car for the wheel ({attempt + 1})")
    s = T.get_in_scene_car()
    if s and s["driving"]: break
if s and s["driving"]:
    # set_car_damage writes the word into the car he drives; each frame is taken on foot
    # beside the car (the chase camera sits inside a long body), then he gets back in.
    view("third")
    for dmg in (0, 4000, 8000, 16000, 25000):
        setk("set_car_damage", dmg); time.sleep(1.2)
        Q.leave_car(); time.sleep(2.0); shot(f"own_dmg{dmg}")
        tap("Return", 0.3); time.sleep(2.5)
        if not D.wait_state()["driving"]: mark(f"RESULT could not get back in after {dmg}"); break
    setk("set_car_damage", -1)
else:
    mark("RESULT not driving")
view("classic"); time.sleep(1.0)
open("/out/.keys_done", "w").close()
