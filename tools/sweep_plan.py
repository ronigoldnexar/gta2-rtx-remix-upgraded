#!/usr/bin/env python3
"""Plans the city sweep: the viewpoints a script visits in the street-level
views to look for defects everywhere, not only where a demo happens to go.

    sweep_plan.py <game/data> <out dir> [--grid 20] [--district wil]

Per district the plan holds, in visiting order:
  - a grid of road or pavement cells every `grid` blocks, each snapped to the
    nearest street-level road/pavement cell within half a grid step;
  - the centroid of every map zone (ZONE chunk) of at least 12 cells that is
    not already within 6 blocks of a grid point;
  - the first six cells of each map-hole class from tools/map_holes.py
    (lidless ground, deck undersides, slope bases) that have a walkable cell
    beside them, so the mesh fixes get looked at from the street.
Each point is {x, y, z, kind, name}: x,y the cell centre (map column, row),
z the lid height the devtools scene warp should resolve (block level + 1).
Written to <out dir>/sweep_plan_<district>.json.
"""
import json, os, struct, sys

W = H = 256
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import map_holes


def load_map(path):
    data = open(path, "rb").read()
    off = 6; chunks = {}
    while off + 8 <= len(data):
        tag = data[off:off + 4]; size = struct.unpack_from("<I", data, off + 4)[0]
        chunks[tag.decode("latin1")] = (off + 8, size); off = off + 8 + size
    blocks, columns = map_holes.load(path)
    o, sz = chunks["ZONE"]; z = data[o:o + sz]; p = 0; zones = []
    while p + 6 <= len(z):
        typ, x, y, w, h, nl = struct.unpack_from("<6B", z, p)
        zones.append((typ, x, y, w, h, z[p + 6:p + 6 + nl].decode("latin1"))); p += 6 + nl
    return blocks, columns, zones


def ground_level(blocks, columns, x, y):
    """lowest level whose lid is road (1) or pavement (2) with nothing built on it, else None"""
    if not (0 <= x < W and 0 <= y < H): return None, None
    offset, idx = columns[y * W + x]
    for i, bi in enumerate(idx):
        b = blocks[bi]
        if not (b[4] & 0x3FF): continue
        if i + 1 < len(idx):
            above = blocks[idx[i + 1]]
            if any(f & 0x3FF for f in above[:5]): continue
        g = b[6] & 3
        if g in (1, 2) and (b[6] >> 2) == 0:
            return offset + i, g
    return None, None


def snap(blocks, columns, x, y, radius):
    best = None
    for r in range(radius + 1):
        for dx in range(-r, r + 1):
            for dy in (-r, r) if abs(dx) != r else range(-r, r + 1):
                lvl, g = ground_level(blocks, columns, x + dx, y + dy)
                if lvl is not None:
                    cand = (abs(dx) + abs(dy), 0 if g == 1 else 1, x + dx, y + dy, lvl)
                    if best is None or cand < best: best = cand
        if best is not None and best[0] <= r: break
    return best


def plan(data_dir, district, grid):
    blocks, columns, zones = load_map(os.path.join(data_dir, f"{district}.gmp"))
    points = []
    taken = []

    def add(x, y, lvl, kind, name):
        for (px, py) in taken:
            if abs(px - x) + abs(py - y) < 3: return False
        points.append(dict(x=x + 0.5, y=y + 0.5, z=lvl + 1, kind=kind, name=name))
        taken.append((x, y)); return True

    half = grid // 2
    for gy in range(half, H, grid):
        for gx in range(half, W, grid):
            s = snap(blocks, columns, gx, gy, half)
            if s: add(s[2], s[3], s[4], "grid", f"g{gx}_{gy}")
    for typ, x, y, w, h, name in zones:
        if w * h < 30: continue
        cx, cy = x + w // 2, y + h // 2
        if any(abs(px - cx) + abs(py - cy) <= 6 for px, py in taken): continue
        s = snap(blocks, columns, cx, cy, 4)
        if s: add(s[2], s[3], s[4], "zone", f"z_{name.strip() or typ}")
    found = map_holes.classify(blocks, columns)
    for cls in ("lidless_ground", "deck_underside", "slope_base"):
        n = 0
        for (x, y, lvl) in found[cls]:
            s = snap(blocks, columns, x, y, 2)
            if not s: continue
            if add(s[2], s[3], s[4], "hole", f"h_{cls}_{x}_{y}"): n += 1
            if n >= 6: break
    return points


def main():
    args = sys.argv[1:]
    data_dir, out_dir = args[0], args[1]
    grid = int(args[args.index("--grid") + 1]) if "--grid" in args else 20
    districts = [args[args.index("--district") + 1]] if "--district" in args else ["wil", "bil", "ste"]
    for d in districts:
        pts = plan(data_dir, d, grid)
        path = os.path.join(out_dir, f"sweep_plan_{d}.json")
        json.dump(dict(district=d, grid=grid, points=pts), open(path, "w"), indent=0)
        kinds = {}
        for p in pts: kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
        print(d, len(pts), "points", kinds, "->", path)


if __name__ == "__main__":
    main()
