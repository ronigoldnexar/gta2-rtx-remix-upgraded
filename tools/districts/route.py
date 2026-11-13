#!/usr/bin/env python3
"""route.py <work> <lvl> <district key> [n]: a drive loop through one district: the road cell nearest the centre of
each of n sectors of the district's cells, ordered round its centroid (game frame: x east, y south)."""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmap
work, lvl, dk = sys.argv[1:4]; n = int(sys.argv[4]) if len(sys.argv) > 4 else 6
d = json.load(open(os.path.join(work, f"{lvl}_districts.json")))
di = [x["key"] for x in d["districts"]].index(dk)
grid = []
for row in d["grid_rle"]:
    r = []
    for v, k in row: r += [v] * k
    grid.append(r)
m = gmap.Map(os.path.join(os.environ.get("GTA2_DATA", "/mnt/gta2/gta2-linux/game/data"), f"{lvl}.gmp"))
roads = [(x, y) for y in range(256) for x in range(256) if grid[y][x] == di and m.top(x, y)[2] == 1]
cx = sum(p[0] for p in roads) / len(roads); cy = sum(p[1] for p in roads) / len(roads)
pts = []
for k in range(n):
    a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
    sec = [p for p in roads if a0 <= (math.atan2(p[1] - cy, p[0] - cx) % (2 * math.pi)) < a1]
    if not sec: continue
    r = sorted(math.hypot(p[0] - cx, p[1] - cy) for p in sec)[len(sec) * 2 // 3]
    am = (a0 + a1) / 2
    tx, ty = cx + r * math.cos(am), cy + r * math.sin(am)
    p = min(sec, key=lambda p: math.hypot(p[0] - tx, p[1] - ty))
    pts.append([p[0] + 0.5, p[1] + 0.5])
print(json.dumps({"district": dk, "roads": len(roads), "centre": [round(cx, 1), round(cy, 1)], "waypoints": pts}))
