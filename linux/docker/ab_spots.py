#!/usr/bin/env python3
"""ASSET-BUILDINGS: street spots facing building walls, for the photo-tile check.
   ab_spots.py <map.gmp> <labels.json> <n> -> JSON list of [sx, sy, fx, fy, score]"""
import json, sys
sys.path.insert(0, "/mnt/gta2/gta2-linux/gamerun")
import gmp
blocks, cols = gmp.load(sys.argv[1]); labels = json.load(open(sys.argv[2])); N = int(sys.argv[3])
good = {int(t) for t, v in labels.items() if v["cls"] not in ("skip",)}
DIRS = [(1, 0, 0), (-1, 0, 1), (0, 1, 2), (0, -1, 3)]   # wall cell offset, face index on the wall block facing us
cand = []
for y in range(4, 252):
    for x in range(4, 252):
        if gmp.ground(blocks, cols, x, y, 1) != 2: continue
        for dx, dy, f in DIRS:
            # stand 2 cells out from the wall: cell (x,y) pavement, (x+dx,y+dy) open, (x+2dx,y+2dy) wall
            if gmp.ground(blocks, cols, x + dx, y + dy, 1) not in (1, 2): continue
            tiles = set(); n = 0
            px, py = -dy, dx      # along the wall
            for s in range(-3, 4):
                wx, wy = x + 2 * dx + s * px, y + 2 * dy + s * py
                for lv in range(2, 7):
                    b = gmp.block_at(blocks, cols, wx, wy, lv)
                    if not b: continue
                    t = b[f] & 0x3FF
                    if t in good: tiles.add(t); n += 1
            if n >= 14: cand.append((len(tiles) * 4 + n, x, y, dx, dy))
cand.sort(reverse=True); pick = []
for sc, x, y, dx, dy in cand:
    if all(abs(x - a) + abs(y - b) > 28 for _, a, b, _, _ in pick): pick.append((sc, x, y, dx, dy))
    if len(pick) >= N: break
print(json.dumps([[x + 0.5, y + 0.5, x + 2 * dx + 0.5, y + 2 * dy + 0.5, sc] for sc, x, y, dx, dy in pick]))
