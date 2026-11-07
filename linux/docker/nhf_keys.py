#!/usr/bin/env python3
"""NAV-HOOK-FIX check: after walking with the arrows in third person (the hook
remaps them), do Tab, F4, V and Return still reach the game?"""
import sys, time, shutil
sys.path.insert(0, "/work")
import qa_lib as Q
from qa_lib import say, tap, hold, shot, D
import tour_lib as T
Q.start("nhf_keys")
Q.set_view("third", settle=1.0)
say("MARK walk 20 s with the arrows (hook active)")
for i in range(4):
    hold("Up", 2.0); hold("Left", 1.2); hold("Up", 1.5); hold("Right", 0.8)
shot("after_walk")
say("MARK Tab x3"); 
for i in range(3): tap("Tab", 0.2); time.sleep(0.6); shot(f"tab_{i}")
say("MARK F4 open/close"); tap("F4", 0.2); time.sleep(1.5); shot("f4_open"); tap("F4", 0.2); time.sleep(1.0)
say("MARK V cycle"); Q.set_view("first", settle=1.0); shot("v_first"); Q.set_view("third", settle=1.0); shot("v_third")
say("MARK warp to a parked road car, then Return")
T.warp(164.5, 149.5, 2, why="car")
time.sleep(1.5)
for i in range(3):
    tap("Return", 0.3); time.sleep(2.5)
    s = D.wait_state(5)
    if s and s.get("driving"): say("MARK driving after Return", i); break
shot("after_return")
hold("Up", 3.0)
say("CHECK", Q.counts())
shutil.copy("/tmp/wp/drive_c/Games/GTA2/gta2dx9.log", "/out/gta2dx9.log")
say("done")
