#!/usr/bin/env python3
"""AI-TRAFFIC-PEDS probe: the same scripted session with the city_ai reactions on or off
(GTA2DX9_CITY_AI=0), for counts from the renderer's `ai:` census lines
(tools/ai_census.py) and frames. Downtown, third person, direct keys:
  1. pistol from the first pickup (166.5,140.5)
  2. a busy street (150.5,133.5): 25 s calm (stroll baseline), then three 1 s bursts in
     the air, then 8 s watching the crowd (frames every 0.5 s)
  3. a scene car on the start carriageway, driven by the route planner across Downtown
     (traffic census, near misses, dodges), chase view
Timeline in /out/marks.txt (MARK lines in the run log)."""
import os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
import qa_lib as Q
import tour_lib as T
say, tap, hold = D.say, D.tap, D.hold

def shot(name): Q.shot(name)

s = Q.start("ai_probe")
T.mark("level")
# 1. pistol
x, y, l = 166.5, 140.5, 2
s = T.warp(x, y, l, why="pistol")
hold("Up", 0.5); time.sleep(0.4); hold("Left", 0.95); time.sleep(0.4); hold("Up", 0.6); time.sleep(0.6)
s = D.goto(x, y, tol=0.3, limit=8) or D.wait_state()
time.sleep(1.0)
# 2. the boulevard pavement by the pickup (CROWD's spot: first person looks along it)
s = T.warp(165.5, 140.5, 2, why="pavement")
s = T.ensure_on_foot()
Q.set_view("first", settle=2.0)
# face north along the boulevard's pavement: a standing ped's logged facing comes from his
# sprite and can be half a turn off, so walk a few blocks north and stop (D.goto)
st = D.wait_state()
D.goto(165.5, st["y"] - 4.0, tol=0.6, limit=20)
time.sleep(1.0)
T.mark("calm start")
for i in range(5):
    time.sleep(4); shot(f"calm_{i}")
T.mark("calm end")
T.mark("gunfire start")
for burst in range(3):
    D.xdo("keydown", "Control_L")
    for k in range(4): shot(f"fire{burst}_{k}"); time.sleep(0.15)
    D.xdo("keyup", "Control_L"); time.sleep(0.8)
T.mark("gunfire end")
for i in range(10): shot(f"after_{i:02d}"); time.sleep(0.4)
Q.set_view("third", settle=0.5)
for i in range(6): shot(f"after_t{i:02d}"); time.sleep(0.5)
T.mark("watch end")
# 3. drive: the nearest parked car (warp_key F9), then the route planner across Downtown
world = M.World("wil")
s = None
for attempt in range(3):
    tap("F9", 0.3); time.sleep(1.5); tap("Return", 0.3); time.sleep(3.0)
    s = D.wait_state()
    if s and s["driving"]: break
if s and s["driving"]:
    Q.set_view("third", settle=1.0)
    T.mark("drive start")
    t0 = time.time()
    def snap(_s, n=[0]):
        if time.time() - t0 > 3 * n[0]: shot(f"drive_{n[0]:02d}"); n[0] += 1
    s = M.drive_to(world, 88.5, 27.5, tol=2.5, budget=100, view_switch=snap)
    T.mark("drive end")
    s = M.drive_to(world, 164.5, 149.5, tol=2.5, budget=70, view_switch=snap)
    T.mark("drive2 end")
else:
    T.mark("no car")
T.mark("end")
say("CHECK", Q.counts())
import shutil
shutil.copy("/tmp/wp/drive_c/Games/GTA2/gta2dx9.log", "/out/gta2dx9.log")
