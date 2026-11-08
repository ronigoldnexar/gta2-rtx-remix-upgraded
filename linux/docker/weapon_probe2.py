#!/usr/bin/env python3
"""WEAPON-OFFSET probe, pass 2: collect the plain weapon pickups named by
WEAPON_PICKUPS ("x,y,level,name,expect;...", no kill frenzies so Tab cycles),
then Z through the inventory: at each stop a third-person frame while firing
and a first-person frame, with 'weapon probe:' log lines (GTA2DX9_LOG_PED_WORDS)
to pair the HUD icon with the game's type and the renderer's weapon."""
import os, sys, time
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
import tour_lib as T

PICKUPS = []
for item in os.environ.get("WEAPON_PICKUPS", "").split(";"):
    if not item.strip(): continue
    x, y, lvl, name, wpn = item.split(",")
    PICKUPS.append((float(x), float(y), int(lvl), name, wpn))

def fire_frames(label):
    Q.set_view("third", settle=0.8)
    shot(f"{label}_aim")
    D.xdo("keydown", "Control_L"); time.sleep(0.45); shot(f"{label}_fire"); time.sleep(0.3); D.xdo("keyup", "Control_L")
    Q.set_view("first", settle=0.8)
    D.xdo("keydown", "Control_L"); time.sleep(0.4); shot(f"{label}_fp"); D.xdo("keyup", "Control_L")
    time.sleep(0.3)

s = Q.start("weapon_probe2")
Q.set_view("third", settle=1.0)
say("MARK weapon start (nothing collected)")
shot("start")
for (x, y, lvl, name, wpn) in PICKUPS:
    say("=== pickup", name, x, y, lvl, "expect", wpn)
    s = T.warp(x, y, lvl, why=name)
    hold("Up", 0.5); time.sleep(0.4); hold("Left", 0.95); time.sleep(0.4); hold("Up", 0.6); time.sleep(0.6)
    s = D.goto(x, y, tol=0.3, limit=8) or D.wait_state()
    say("at", f"{s['x']:.2f},{s['y']:.2f}", "state", s.get("state"))
    time.sleep(0.8)
    say("MARK weapon", name, "expect", wpn)
    shot(f"{name}_got")
say("=== tab cycle")
Q.set_view("third", settle=1.0)
for i in range(len(PICKUPS) + 2):
    tap("z", 0.2); time.sleep(0.8)   # Z: next weapon (Tab is the special key)
    say("MARK tab", i)
    fire_frames(f"tab_{i:02d}")
say("CHECK", Q.counts())
import shutil
shutil.copy("/tmp/wp/drive_c/Games/GTA2/gta2dx9.log", "/out/gta2dx9.log")
say("done")
