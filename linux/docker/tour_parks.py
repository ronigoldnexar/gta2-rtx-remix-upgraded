#!/usr/bin/env python3
"""Lawn check per district after the grass-classifier change: cuts to the two
densest lawn clusters (offline count of grass cells with four grass neighbours
at the same height) and a look round in both street views."""
import os, sys, time
sys.path.insert(0, "/work")
import tour_lib as T
from tour_lib import D, M, Q, say, tap, hold, mark, shot, view, warp, walk

district = os.environ.get("SWAP_LEVEL", "wil")
SPOTS = {"bil": [(140.5, 243.5, 3, "krishna_yard"), (227.5, 163.5, 3, "east_lawn")],
         "ste": [(27.5, 107.5, 3, "west_lawn"), (212.5, 51.5, 6, "north_terrace_lawn")]}[district]
T.Q.start(f"tour_parks_{district}")
world = M.World(district)
mark("level"); hold("Up", 1.0)
for (x, y, z, tag) in SPOTS:
    s = warp(x, y, z, why=f"to the lawn {tag}")
    view("third"); walk(world, x + 2.0, y, budget=25, tol=1.0); T.look_around(f"30_{tag}_third", 0.8)
    view("first"); T.look_around(f"31_{tag}_first", 0.9)
    say("trees:", [l for l in Q.log_text(40000).splitlines() if "park trees:" in l][-1:])
T.finish(f"tour_parks_{district}")
