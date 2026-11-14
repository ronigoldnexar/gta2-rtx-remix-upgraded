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
def board():
    """into the nearest car: wait for traffic to spawn round the warp point, walk to the car the locator reports,
    Return (a moving car stops for him in GTA2 when he steps in front of it; a parked one he just opens)"""
    for attempt in range(int(os.environ.get("DK_BOARD_TRIES", "30"))):
        s = D.wait_state()
        if s and s["driving"]:
            return s
        tgt = None
        if s and s.get("parked") and s.get("pd", 99) < 25:
            tgt = (s["px"], s["py"])
        elif s and s.get("car") and s.get("cd", 99) < 20:
            tgt = (s["cx"], s["cy"])
        if tgt:
            D.goto(tgt[0], tgt[1], tol=0.9, limit=16)
            D.tap("Return", 0.3); time.sleep(2.5)
            s = D.wait_state()
            if s and s["driving"]:
                T.mark(f"in car model={s.get('cmodel', -1)}"); return s
        else:
            time.sleep(2.0)
    return D.wait_state()


T.warp(wp[0][0], wp[0][1], 2, why="districts drive start")
time.sleep(3.0)
s = board()
if not (s and s["driving"]):
    T.mark("NO CAR: the drive-through is on foot")
T.view("third")
T.mark("drive start")
legs = route.get("legs")
for lap in range(int(os.environ.get("DK_LAPS", "2"))):
    for i, (x, y) in enumerate(wp[1:] + wp[:1]):
        if legs:
            lg = legs[(i + 1) % len(legs)]
            T.mark(f"leg {i} to {lg['district']} ({lg['style']}: {lg.get('name')})")
        T.drive(world, x, y, f"lap{lap} wp{i}", budget=int(os.environ.get("DK_LEG_BUDGET", "90")), fp_after=10 ** 6)
        s = D.wait_state()
        if not (s and s["driving"]):          # lost the car (a crash, a carjack): into another and on
            T.mark("on foot: boarding again")
            T.view("third")
            s = board()
            T.view("third")
T.mark("drive end")
open("/out/.dk_done", "w").write("ok\n")
