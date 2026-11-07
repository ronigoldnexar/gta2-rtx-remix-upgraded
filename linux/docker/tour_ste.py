#!/usr/bin/env python3
"""Industrial tour: spawn (113.5,124.7) beside the elevated railway station
(trak00st 121,122) on foot in the chase view, a car from the scene warp, a
drive west to crane9 (55.5,48.5) and on to the western docks (road 25,70),
a walk along the quay (8,72) past crane1 (4.5,72.5), the Rednecks' green
phone (18.5,67.5) and "DOUBLE-CROSS CRUSH!", then cuts to two map-hole spots
(160,10 z4) and (216,24 z4) with a look at each on foot."""
import sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, M, Q, say, tap, hold, mark, shot, view, warp, walk, drive

T.Q.start("tour_ste")
world = M.World("ste")
mark("level")
s = D.wait_state(); say("start:", T.words(s))
# ------------------------------------------------ 1 spawn and the railway station
hold("Up", 2.5); shot("01_spawn_classic")
view("third"); T.look_around("02_spawn_third", 0.8)
walk(world, 119.5, 122.5, budget=60, tol=1.0); shot("03_station_third")
view("first"); T.look_around("04_station_first", 0.9)
# ------------------------------------------------ 2 a car, drive west
s = warp(108.5, 128.5, 2, why="a parked car brought beside him on the road by the spawn")
view("third"); shot("05_car_arrives")
s = T.get_in_scene_car()
if s and s["driving"]:
    s = drive(world, 55.5, 50.5, "crane9 (55.5,48.5)", budget=170)
    shot("06_crane9_wheel")
    s = drive(world, 25.5, 70.5, "the western docks road", budget=150, fp_after=4.0)
    T.leave_car()
s = T.ensure_on_foot()
if abs(s["x"] - 25.5) + abs(s["y"] - 70.5) > 12:
    s = warp(25.5, 70.5, 2, why="to the western docks road (the drive did not arrive)")
view("third"); walk(world, 9.5, 72.5, budget=70, tol=1.5); T.look_around("07_quay_third", 0.8)
view("first"); T.look_around("08_quay_first", 0.9)
walk(world, 20.5, 70.5, budget=50, tol=1.5); view("third"); T.look_around("09_dock_green_third", 0.8)
# ------------------------------------------------ 3 the Rednecks' green phone and the mission
phone = world.db["phones"]["obj7"]
ok, m = T.answer(world, phone, "DOUBLE-CROSS CRUSH!")
shot("10_phone_answered"); time.sleep(6); shot("11_brief")
if ok:
    money0 = m.get("money", 0)
    view("first"); T.look_around("12_after_brief_first", 0.9)
    o, mm = M.wait_outcome(money0, 45); mark(f"mission outcome after 45 s: {o} msg={mm.get('msg') if mm else '?'}")
# ------------------------------------------------ 4 map-hole spots
for (x, y, z, tag) in ((160.5, 10.5, 4, "hole_160_8"), (216.5, 24.5, 4, "hole_216_22")):
    s = warp(x, y, z, why=f"to the map-hole spot {tag}")
    view("third"); walk(world, x, y - 2.0, budget=30, tol=1.2); T.look_around(f"13_{tag}_third", 0.8)
    view("first"); T.look_around(f"14_{tag}_first", 0.9)
T.finish("tour_ste")
