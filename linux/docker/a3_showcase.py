#!/usr/bin/env python3
"""ACTIONS-3D probe 7: every new clip on the player's own figure, in the game,
from behind, the side and the front (GTA2DX9_FORCE_ACTION_FILE=force_action.txt:
the renderer reads "action lying weapon" from the file in the game folder twice
a second and plays it on his figure). Checks the poses, the weapon placement
in each and the blend over the walk; what triggers each clip in play is checked
by the other probes and the 'ped anim:' log lines."""
import os, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot

FILE = "/tmp/wp/drive_c/Games/GTA2/force_action.txt"
def force(a, lie=0, w=-1):
    with open(FILE, "w") as f: f.write(f"{a} {lie} {w}\n")

ITEMS = [  # (label, action, lying clip, weapon (renderer numbering), walk across?)
    ("carry_pistol", 14, 0, 1, True), ("carry_dual", 15, 0, 2, False), ("carry_mg", 16, 0, 4, True),
    ("carry_shotgun", 16, 0, 9, False), ("carry_launcher", 17, 0, 5, True), ("carry_flame", 18, 0, 10, False),
    ("carry_molotov", 14, 0, 7, False),
    ("aim_pistol", 2, 0, 1, False), ("aim_dual", 10, 0, 2, False), ("aim_mg", 8, 0, 4, True),
    ("aim_launcher", 11, 0, 5, False), ("aim_flame", 12, 0, 10, False), ("aim_electro", 8, 0, 6, False),
    ("throw_grenade", 13, 0, 8, False),
    ("handsup", 3, 0, 0, False), ("cuffed", 21, 0, 0, True), ("burn", 19, 0, 0, True),
    ("fall_air", 20, 0, 0, False), ("drown", 9, 0, 0, False),
    ("dead_fall", 4, 0, 0, False), ("dead_front", 4, 1, 0, False), ("dead_runover", 4, 2, 0, False),
    ("dead_blown", 4, 3, 0, False), ("dead_burnt", 4, 4, 0, False),
]
only = [x for x in os.environ.get("A3_ITEMS", "").split(",") if x]
if only: ITEMS = [it for it in ITEMS if it[0] in only]
force(-1)
s = Q.start("a3_showcase")
T.warp(float(os.environ.get("A3_SX", "166.5")), float(os.environ.get("A3_SY", "19.5")), int(os.environ.get("A3_SL", "2")), why="open street")
Q.set_view("third", settle=2.5)
for (label, a, lie, w, walk) in ITEMS:
    force(-1); time.sleep(0.6)
    say("MARK show", label, a, lie, w)
    force(a, lie, w)
    time.sleep(0.25 if a == 13 else 1.2)
    shot(f"s_{label}_back")
    hold("Left", 0.22); time.sleep(0.15 if a == 13 else 0.5); shot(f"s_{label}_side")
    if walk:
        D.xdo("keydown", "Left"); time.sleep(0.6); shot(f"s_{label}_walk"); D.xdo("keyup", "Left")
    hold("Down", 0.22); time.sleep(0.5); shot(f"s_{label}_front")
    if a == 4:
        force(-1); time.sleep(0.45); shot(f"s_{label}_getup")
    hold("Up", 0.22); time.sleep(0.2)
force(-1)
# first person: the carry and the stance from the eye are the view model's, one look
Q.set_view("first", settle=0.6); shot("s_fp_end")
A.finish()
