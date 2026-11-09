#!/usr/bin/env python3
"""QB-11 probe: the railings at two Downtown spots (the park's spear fence, tile 635, and a
bar fence, tile 217), the same in every run. At each spot: a no-car warp, third person,
frames at six headings, then first person at six headings. Frames /out/t_rl_<spot>_<view>_<n>.png.
Run with GTA2_DIRECT_KEYS=1, GTA2DX9_SCENE_NO_CAR=1 and
INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/'; GTA2DX9_RAILINGS=0 for the
flat panels (before)."""
import sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import mark, shot, view, warp

SPOTS = [("park", 146.3, 121.5, None), ("park2", 148.5, 117.3, None), ("bars", 205.5, 36.2, None)]

T.Q.start("qb11_railings")
for name, x, y, lvl in SPOTS:
    warp(x, y, lvl, why=f"railing spot {name}")
    for v in ("third", "first"):
        view(v)
        time.sleep(1.0)
        for i in range(6):
            shot(f"rl_{name}_{v}_{i}")
            T.hold("Left", 0.5); time.sleep(0.8)
    view("classic")
    time.sleep(1.0); shot(f"rl_{name}_classic")
T.finish("qb11_railings")
