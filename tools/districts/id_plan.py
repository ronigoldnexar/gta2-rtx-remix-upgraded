#!/usr/bin/env python3
"""DISTRICTS round 4: a drive-camera point in a district, the same camera height in every district, for the identity
frames: the road cell in the district whose next 12 cells of straight road have the most of the district's kit
buildings (2+ levels over the street) close on both sides. Poses (game frame: x east, y south, z up, from the road
cell's middle at street level): "drive" eye 3 cells back and 2.2 up looking 10 ahead at 1.0 up (the chase camera's
height and pitch in the drive videos); "drive_rev" the same the other way along the road.

    id_plan.py <work> <lvl> <district key>   -> JSON list with one point (districts_identity.py DK_POINTS)"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmap
from gmap import W, H

work, lvl, dk = sys.argv[1:4]
m = gmap.Map(os.path.join(os.environ.get("GTA2_DATA", "/mnt/gta2/gta2-linux/game/data"), f"{lvl}.gmp"))
keys = [d["key"] for d in json.load(open(os.path.join(work, f"{lvl}_districts.json")))["districts"]]
an = {a["id"]: a["archetype"] for a in json.load(open(os.path.join(work, f"{lvl}_analysis.json")))["buildings"]}
own = {}
for b in json.load(open(os.path.join(work, f"{lvl}_buildings.json")))["buildings"]:
    if keys[b["district"]] == dk and an.get(b["id"]) not in (None, "structure"):
        for x, y in b["cells"]:
            own[(x, y)] = b
best = None
for (bx, by) in list(own):
    for x in range(bx - 5, bx + 6):
        for y in range(by - 5, by + 6):
            if not (0 <= x < W and 0 <= y < H):
                continue
            z, _, g, sl = m.top(x, y)
            if g != 1 or sl:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ok = all(0 <= x + dx * t < W and 0 <= y + dy * t < H and m.top(x + dx * t, y + dy * t)[0] == z and
                         m.top(x + dx * t, y + dy * t)[2] == 1 for t in range(-3, 13))   # road all the way (2 is pavement)
                if not ok:
                    continue
                left = right = 0
                seen = set()
                for t in range(1, 13):
                    for s in range(1, 5):
                        for sgn in (1, -1):
                            c = (x + dx * t + dy * s * sgn, y + dy * t - dx * s * sgn)
                            b = own.get(c)
                            if b and b["roof"] >= z + 2 and c not in seen:
                                seen.add(c)
                                w = min(b["roof"] - z, 6) / 2.0     # taller frontage counts more
                                if sgn > 0: left += w
                                else: right += w
                sc = min(left, right) * 2 + left + right
                if best is None or sc > best[0]:
                    best = (sc, x, y, z, dx, dy)
sc, x, y, z, dx, dy = best
pose = lambda name, s: {"name": name, "eye": [-3 * dx * s, -3 * dy * s, 2.2], "at": [10 * dx * s, 10 * dy * s, 1.0], "fov": 60}
p = {"name": f"{lvl}_{dk.replace(':', '_')}", "level": lvl, "district": dk, "score": sc, "x": x + 0.5, "y": y + 0.5, "z": z,
     "dir": [dx, dy], "poses": [pose("drive", 1)]}
p["poses"].append({"name": "drive_rev", "eye": [12 * dx, 12 * dy, 2.2], "at": [-1 * dx, -1 * dy, 1.0], "fov": 60})
print(json.dumps([p]))
