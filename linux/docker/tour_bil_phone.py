#!/usr/bin/env python3
"""Residential, the mission part only: a cut straight to the Zaibatsu green
phone on its terrace (44.5,163.5, z3), the phone answered, the brief, then a
car on the street below and the first leg of "IT WAS AN ACCIDENT!" to the
Special Package at 133,230.5 (road 139,230)."""
import sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, M, Q, say, tap, hold, mark, shot, view, warp, walk, drive

T.Q.start("tour_bil_phone")
world = M.World("bil")
mark("level")
hold("Up", 1.0)
s = warp(44.5, 163.5, 3, why="to the Zaibatsu phone terrace (the phone's own cell, z3)")
view("third"); T.look_around("20_terrace_third", 0.8)
phone = world.db["phones"]["obj11"]
ok, m = T.answer(world, phone, "IT WAS AN ACCIDENT!")
shot("21_phone_answered"); time.sleep(8); shot("22_brief")
if ok:
    money0 = m.get("money", 0)
    view("first"); T.look_around("23_brief_first", 0.9)
    s = warp(44.5, 170.5, 2, why="a car on the street below the terrace for the mission drive")
    view("third"); s = T.get_in_scene_car()
    if s and s["driving"]:
        s = drive(world, 139.5, 230.5, "the Special Package (mission arrow)", budget=240, fp_after=15.0)
        T.leave_car(); view("third")
        walk(world, 133.0, 230.5, budget=70, tol=0.8); shot("24_package")
        o, mm = M.wait_outcome(money0, 40); mark(f"mission outcome: {o} msg={mm.get('msg') if mm else '?'}")
        shot("25_after_package")
T.finish("tour_bil_phone")
