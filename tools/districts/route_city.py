#!/usr/bin/env python3
"""route_city.py <work> <lvl> [n]: a drive across the level for round 5: one waypoint per district with a style row
(and the biggest unstyled ones, up to n in all), each the road cell nearest the district's road centroid, ordered as
a nearest-neighbour tour from the first; JSON like route.py's, with each waypoint's district and row."""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmap
work, lvl = sys.argv[1:3]; n = int(sys.argv[3]) if len(sys.argv) > 3 else 9
d = json.load(open(os.path.join(work, f"{lvl}_districts.json")))
grid = []
for row in d["grid_rle"]:
    r = []
    for v, k in row: r += [v] * k
    grid.append(r)
m = gmap.Map(os.path.join(os.environ.get("GTA2_DATA", "/mnt/gta2/gta2-linux/game/data"), f"{lvl}.gmp"))
roads = {}
for y in range(256):
    for x in range(256):
        if grid[y][x] >= 0 and m.top(x, y)[2] == 1 and m.top(x, y)[0] == 2:
            roads.setdefault(grid[y][x], []).append((x, y))
cands = []
for di, rs in roads.items():
    if len(rs) < 30: continue
    st = d["districts"][di].get("style")
    cands.append((0 if st else 1, -len(rs), di))
cands.sort()
pick = cands[:n]
pts = []
for _, _, di in pick:
    rs = roads[di]
    cx = sum(p[0] for p in rs) / len(rs); cy = sum(p[1] for p in rs) / len(rs)
    p = min(rs, key=lambda p: math.hypot(p[0] - cx, p[1] - cy))
    pts.append({"xy": [p[0] + 0.5, p[1] + 0.5], "district": d["districts"][di]["key"], "name": d["districts"][di].get("name"),
                "style": d["districts"][di].get("style") or "default"})
tour = [pts.pop(0)]
while pts:
    last = tour[-1]["xy"]
    j = min(range(len(pts)), key=lambda k: math.hypot(pts[k]["xy"][0] - last[0], pts[k]["xy"][1] - last[1]))
    tour.append(pts.pop(j))
print(json.dumps({"level": lvl, "waypoints": [t["xy"] for t in tour], "legs": tour}))
