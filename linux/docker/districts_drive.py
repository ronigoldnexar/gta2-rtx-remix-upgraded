#!/usr/bin/env python3
"""DISTRICTS pilot drive-through (inside a game container): warp to the first waypoint with a car, get in, and drive
the loop (DK_ROUTE, JSON from tools/districts/route.py) in the chase view, twice round, at 12:30 with a clear sky.
Marks in /out/marks.txt; the run's game.mp4 is the video, gta2dx9.log the frame times and the stream's figures."""
import json, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
import qa_lib as Q
import tour_lib as T

route = json.loads(os.environ["DK_ROUTE"])
lvl = os.environ.get("DK_LEVEL", "wil")
world = M.World(lvl)
D.start()
s = D.wait_state(40)
wp = route["waypoints"]
T.warp(wp[0][0], wp[0][1], 2, why="districts drive start")
time.sleep(1.5)
s = T.get_in_scene_car()
T.view("third")
T.mark("drive start")
for lap in range(int(os.environ.get("DK_LAPS", "2"))):
    for i, (x, y) in enumerate(wp[1:] + wp[:1]):
        T.drive(world, x, y, f"lap{lap} wp{i}", budget=90, fp_after=10 ** 6)
T.mark("drive end")
open("/out/.dk_done", "w").write("ok\n")
