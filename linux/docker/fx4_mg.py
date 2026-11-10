#!/usr/bin/env python3
"""FIX-FX-4 pmw10 probe: collect the pistol, machine gun and silenced MG (a3_weapons_pt2's pickups), warp to the
open plaza, then for each gun: a burst from the side in third person (frames every ~0.1 s), one facing the camera,
and one in first person. Labels: g<gun>_<view>_<n>. Env WEAPONS (pistol,machine_gun,silenced_mg)."""
import os, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot
ALL = {"pistol": (227.5, 210.5, 2), "machine_gun": (166.5, 140.5, 2), "silenced_mg": (97.5, 68.5, 2)}
want = os.environ.get("WEAPONS", "pistol,machine_gun,silenced_mg").split(",")
Q.start("fx4_mg")
for w in want: A.collect(*ALL[w], w)
T.warp(159.5, 139.5, 2, why="open plaza")
Q.set_view("third", settle=1.0)
def burst(label, secs, every=0.08):
    D.xdo("keydown", "Control_L"); t0 = time.time(); n = 0
    while time.time() - t0 < secs: shot(f"{label}_{n:02d}"); n += 1; time.sleep(every)
    D.xdo("keyup", "Control_L")
    for i in range(4): shot(f"{label}_post{i}"); time.sleep(0.1)
seen = []
for i in range(5):
    tap("z", 0.2); time.sleep(0.9)
    w = A.weapon_name(); say("MARK stop", i, "weapon", w)
    if w in seen or w == "none": continue
    seen.append(w)
    Q.set_view("third", settle=0.8)
    hold("Left", 0.25); time.sleep(0.5)
    burst(f"g_{w}_side", 1.2)
    hold("Down", 0.25); time.sleep(0.5)
    burst(f"g_{w}_front", 0.8)
    Q.set_view("first", settle=0.8)
    burst(f"g_{w}_fp", 0.8)
    Q.set_view("third", settle=0.6)
A.finish()
