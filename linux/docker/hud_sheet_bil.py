#!/usr/bin/env python3
"""MODERN HUD check, part two (Industrial): the level's opening brief, the walk to the
Zaibatsu phones (the phone prompt), the phone answered and its brief. Same pairs as
hud_sheet_run.py ([hud] modern rewritten in the ini, GTA2DX9_HUD_TEST=1)."""
import re, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, M, Q, say, tap, hold, mark, shot, view

def ini_set(key, val):
    t = open(T.INI, encoding="latin-1").read()
    t = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", t)
    open(T.INI, "w", encoding="latin-1").write(t)

def pair(name, gap=1.4):
    shot(f"{name}_modern"); ini_set("modern", "0"); time.sleep(gap)
    shot(f"{name}_classic"); ini_set("modern", "1"); time.sleep(gap)
    mark(f"pair {name}")

T.Q.start("hud_sheet_bil")
world = M.World("bil")
view("third"); time.sleep(0.5)
pair("brief_open")
s = T.walk(world, 44.5, 158.5, budget=150, tol=1.0)
view("third"); time.sleep(1.0)
pair("phone")
phone = world.db["phones"]["obj11"]
ok, m = T.answer(world, phone, "IT WAS AN ACCIDENT!")
time.sleep(0.5)
pair("brief")
time.sleep(2.0)
pair("brief_b")
T.finish("hud_sheet_bil")
