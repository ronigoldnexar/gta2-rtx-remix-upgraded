#!/usr/bin/env python3
"""ACTIONS-3D probe 1, Downtown (wil): the weapon the game names drives the
figure. Collect the six plain pickups (pistol, machine gun, rocket launcher,
molotov, flamethrower, silenced machine gun), then at every Z stop: the carry
standing, from the side and walking, a burst (frames, one from the side mid
burst), the stance held after the burst, and first person. Log: weapon= on the
mission line, 'player figure:' lines (GTA2DX9_LOG_PED_FRAMES=1)."""
import os, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

PICKUPS = [(227.5, 210.5, 2, "pistol"), (166.5, 140.5, 2, "machine_gun"), (154.5, 129.5, 2, "rocket_launcher"),
           (19.5, 35.5, 4, "flamethrower"), (97.5, 68.5, 2, "silenced_mg"), (164.5, 118.5, 6, "molotov")]
s = Q.start("a3_weapons")
for (x, y, lvl, name) in PICKUPS:
    A.collect(x, y, lvl, name)
# an open, flat spot: the park lawn by the first pickup
T.warp(159.5, 139.5, 2, why="open plaza")
Q.set_view("third", settle=1.0)
seen = []
for i in range(len(PICKUPS) + 1):
    tap("z", 0.2); time.sleep(0.9)
    w = A.weapon_name()
    say("MARK stop", i, "weapon", w)
    if w in seen or w == "none":
        continue
    seen.append(w)
    L = f"w{i:02d}_{w}"
    Q.set_view("third", settle=0.8)
    shot(f"{L}_carry_back")
    # the camera holds its yaw (nav_map): stepping left turns him side-on to it
    hold("Left", 0.25); time.sleep(0.5); shot(f"{L}_carry_side")
    A.walk_frame(f"{L}_carry_walk_side", secs=0.7, key="Left")
    time.sleep(0.5)
    A.fire(f"{L}_fire_side", secs=1.0, every=0.25)
    time.sleep(0.3); shot(f"{L}_after_side")
    time.sleep(1.4); shot(f"{L}_settled_side")
    # aim on the move: fire while walking across the frame
    D.xdo("keydown", "Left"); A.fire(f"{L}_fire_walk", secs=0.6, every=0.3); D.xdo("keyup", "Left")
    # facing the camera
    hold("Down", 0.25); time.sleep(0.5); shot(f"{L}_carry_front")
    A.fire(f"{L}_fire_front", secs=0.6, every=0.3)
    hold("Up", 0.3)
    Q.set_view("first", settle=0.6)
    shot(f"{L}_fp_carry")
    A.fire(f"{L}_fp_fire", secs=0.5, every=0.25)
    Q.set_view("third", settle=0.6)
A.finish()
