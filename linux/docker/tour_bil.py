#!/usr/bin/env python3
"""Residential tour: spawn (44.5,102) on foot in the chase view, a car from the
scene warp on the spawn road (44.5,108.5), a drive north to the railway
station (trak22st 47,59; road 50,58), out and a look, a cut to the raised
map-hole spot (37,45, z3), the river bank (north edge, 80,17), the raised
southern park (140,246, z3, Krishna land), then the Zaibatsu green phone on
its terrace (44.5,163.5, z3) and the first leg of "IT WAS AN ACCIDENT!" by car
to the package at 133,230.5 (road 139,230)."""
import sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, M, Q, say, tap, hold, mark, shot, view, warp, walk, drive

T.Q.start("tour_bil")
world = M.World("bil")
mark("level")
s = D.wait_state(); say("start:", T.words(s))
# ------------------------------------------------ 1 spawn, classic then chase
hold("Up", 2.5); shot("01_spawn_classic")
view("third"); T.look_around("02_spawn_third", 0.8)
walk(world, 44.5, 107.5, budget=40); shot("03_spawn_walk")
view("first"); T.look_around("04_spawn_first", 0.9)
# ------------------------------------------------ 2 a car on the spawn road, drive north to the station
s = warp(44.5, 108.5, 2, why="a parked car brought beside him on the spawn road")
view("third"); shot("05_car_arrives")
s = T.get_in_scene_car()
if s and s["driving"]:
    s = drive(world, 50.5, 58.5, "railway station trak22st", budget=170)
    shot("06_station_wheel")
    T.leave_car()
view("third"); T.look_around("07_station_third", 0.8)
# ------------------------------------------------ 3 the raised map-hole spot (37,45)
s = warp(37.5, 45.5, 3, why="to the map-hole spot (37,45), one level up")
view("third"); walk(world, 38.5, 47.5, budget=30, tol=1.0); T.look_around("08_hole_37_45_third", 0.8)
view("first"); T.look_around("09_hole_37_45_first", 0.9)
# ------------------------------------------------ 4 the river bank (north edge water)
s = warp(80.5, 20.5, 2, why="to the river bank, north edge")
view("third"); walk(world, 80.5, 17.5, budget=40, tol=1.2); T.look_around("10_river_third", 0.8)
view("first"); T.look_around("11_river_first", 0.9)
# ------------------------------------------------ 5 the raised southern park (grass, trees)
s = warp(140.5, 246.5, 3, why="to the park, Krishna land, one level up")
view("third"); walk(world, 146.5, 247.5, budget=40, tol=1.2); T.look_around("12_park_third", 0.8)
view("first"); walk(world, 150.5, 248.5, budget=30, tol=1.2); T.look_around("13_park_first", 0.9)
# ------------------------------------------------ 6 the Zaibatsu green phone on its terrace, and the mission
s = warp(44.5, 164.5, 3, why="to the Zaibatsu phone terrace")
view("third"); shot("14_phone_approach")
phone = world.db["phones"]["obj11"]
ok, m = T.answer(world, phone, "IT WAS AN ACCIDENT!")
shot("15_phone_answered"); time.sleep(6); shot("16_brief")
if ok:
    money0 = m.get("money", 0)
    s = warp(44.5, 170.5, 2, why="a car on the street below the terrace for the mission drive")
    view("third"); s = T.get_in_scene_car()
    if s and s["driving"]:
        s = drive(world, 139.5, 230.5, "the Special Package (mission arrow)", budget=210, fp_after=15.0)
        T.leave_car(); view("third")
        walk(world, 133.0, 230.5, budget=60, tol=0.8); shot("17_package")
        o, mm = M.wait_outcome(money0, 40); mark(f"mission outcome: {o} msg={mm.get('msg') if mm else '?'}")
        shot("18_after_package")
T.finish("tour_bil")
