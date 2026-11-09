#!/usr/bin/env python3
"""ASSET-PEDS probe (Downtown): every pedestrian type drawn in its sprite outfit.
The renderer draws everyone (the player's figure included) as the remap in
assetpeds_remap.txt (GTA2DX9_PED_REMAP_FILE); at the plaza, in third person, a
frame from behind and two after quick turns per remap (AP_REMAPS, default all
0-53, 53 = the SWAT/FBI body), then AP_CROWD seconds of the natural crowd
(remap file -1) while walking, with frames. Run with GTA2DX9_SCENE_NO_CAR=1,
INI_SED scene_key=F10, warp_key=F9, nav_map=0 (GTA2_DIRECT_KEYS=1)."""
import os, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, say, hold, shot

REMAP_FILE = "/tmp/wp/drive_c/Games/GTA2/assetpeds_remap.txt"
remaps = [int(x) for x in os.environ.get("AP_REMAPS", ",".join(str(r) for r in range(54))).split(",") if x]
open(REMAP_FILE, "w").write("-1\n")
T.warp(*[float(v) for v in os.environ.get("AP_AT", "159.5,139.5").split(",")], 2, why="plaza")
Q.set_view("third", settle=1.0)
for r in remaps:
    open(REMAP_FILE, "w").write(f"{r}\n"); time.sleep(1.2)
    say(f"MARK remap {r}")
    shot(f"r{r:02d}_a")
    A.side(f"r{r:02d}_b", "Left", 0.45)
    A.side(f"r{r:02d}_c", "Left", 0.45)
open(REMAP_FILE, "w").write("-1\n"); time.sleep(1.0)
say("MARK natural crowd")
t0 = time.time(); n = 0
while time.time() - t0 < float(os.environ.get("AP_CROWD", "40")):
    hold("Up", 1.2); shot(f"crowd_{n:03d}"); n += 1
    if n % 4 == 0: hold("Left", 0.5)
A.finish()
