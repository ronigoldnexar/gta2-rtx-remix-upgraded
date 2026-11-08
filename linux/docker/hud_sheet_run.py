#!/usr/bin/env python3
"""MODERN HUD check (hud3d.cpp): the same moments with the modern HUD and the classic one
([hud] modern rewritten in the ini, re-read once a second with GTA2DX9_HUD_TEST=1), in
Downtown: on foot, the machine gun, the information phone and its brief, a clock
([hud] test_clock: the game's own add-a-clock call), low health ([hud] test_health),
driving (chase and first person), wanted (force_wanted). Frames /out/t_<moment>_modern.png
and _classic.png."""
import re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, M, Q, say, tap, hold, mark, shot, view, warp

def ini_set(key, val):
    t = open(T.INI, encoding="latin-1").read()
    t = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    open(T.INI, "w", encoding="latin-1").write(t)

def pair(name, gap=1.4):
    shot(f"{name}_modern"); ini_set("modern", "0"); time.sleep(gap)
    shot(f"{name}_classic"); ini_set("modern", "1"); time.sleep(gap)
    mark(f"pair {name}")

T.Q.start("hud_sheet")
world = M.World("wil")
mark("level")
view("third"); time.sleep(1.0)
pair("onfoot")
# the machine gun beside the spawn (obj1, COLLECT_01)
s = warp(166.5, 140.5, 2, why="the machine gun (obj1, COLLECT_01)")
hold("Up", 0.5); time.sleep(0.4); hold("Left", 0.95); time.sleep(0.4); hold("Up", 0.6); time.sleep(0.6)
s = D.goto(166.5, 140.5, tol=0.3, limit=8) or D.wait_state()
time.sleep(1.0)
view("third"); time.sleep(1.5)
pair("weapon")
# the information phone at the spawn (obj86)
s = T.walk(world, 160.5, 139.5, budget=40, tol=0.6)
view("third"); time.sleep(1.0)
pair("phone")
phone = world.db["phones"]["obj86"]
ok, m = T.answer(world, phone, "information phone")
time.sleep(0.5)
pair("brief")
ini_set("test_clock", "1"); time.sleep(2.5)
pair("timer")
ini_set("test_health", "15"); time.sleep(1.2)
pair("lowhealth")
Q.set_view("classic", settle=1.0)
tap("F9", 0.3); time.sleep(2.5)   # warp_key: to the driver's door of the nearest parked car
s = T.get_in_scene_car()
if not (s and s.get("driving")):
    s = warp(164.5, 149.5, why="a parked car brought to the road"); s = T.get_in_scene_car()
view("third")
hold("Up", 2.0)
pair("driving")
view("first"); time.sleep(1.0)
pair("driving_first")
T.leave_car(); time.sleep(1.0)
view("third")
ini_set("force_wanted", "3"); time.sleep(4.0)
pair("wanted")
view("first"); time.sleep(1.0)
pair("wanted_first")
ini_set("force_wanted", "-1")
T.finish("hud_sheet")
