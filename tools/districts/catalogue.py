#!/usr/bin/env python3
"""DISTRICTS-POC step 1: the district map and the building catalogue of one level, from the map alone.

    catalogue.py <game/data> <wil|ste|bil> <out dir> [--overrides tools/districts/overrides]

Writes <out>/<lvl>_districts.json (cell -> district grid, RLE rows), <out>/<lvl>_districts.png (coloured
map over the roof heights, buildings outlined, legend) and <out>/<lvl>_buildings.json (the catalogue).

District of a cell: the map's ZONE records, priority local-nav (15) > gang (14) > nav (1) > the level's
default, the smallest zone winning within a kind; then the hand-editable override file
(<overrides>/<lvl>.json: {"rects": [{"rect": [x, y, w, h], "district": "<key>"}], "names": {"<key>": "..."},
"styles": {"<key>": "<style table row>"}}) is applied on top. Names come from the game's own text (e.gxt).

A building: a 4-connected run of cells whose roof stands at least one level above the street near it (the
road level spread out from the road cells), not a road, with at least one wall tile of its own, split where
the roof height changes (a plateau); fragments of one cell join the neighbour they share most edge with.
Per building: footprint cells, bbox, roof height(s), street level, levels above the street, district, and every
exterior wall face (cell, side, levels, tile id and the raw face word per level)."""
import json, os, struct, sys
from collections import Counter, deque
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmap
from gmap import W, H, SIDES

KIND_PRI = {15: 3, 14: 2, 1: 1}
LEVEL_NAMES = {"wil": "Downtown", "ste": "Residential", "bil": "Industrial"}


def read_gxt(path):
    data = open(path, "rb").read()
    if data[:3] != b"GBL":
        return {}
    off, keys, tdat = 6, [], b""
    while off + 8 <= len(data):
        tag = data[off:off + 4]; size = struct.unpack_from("<I", data, off + 4)[0]; body = off + 8
        if tag == b"TKEY":
            for i in range(size // 12):
                o = struct.unpack_from("<I", data, body + i * 12)[0]
                k = data[body + i * 12 + 4: body + i * 12 + 12].split(b"\0")[0].decode("latin-1")
                keys.append((k, o))
        elif tag == b"TDAT":
            tdat = data[body: body + size]
        off = body + size
    out = {}
    for k, o in keys:
        end = o
        while end + 1 < len(tdat) and tdat[end:end + 2] != b"\0\0":
            end += 2
        out[k] = tdat[o:end].decode("utf-16-le", "replace")
    return out


def district_grid(m, lvl, gxt, overrides):
    """grid[y][x] = index into districts; districts = [{key, kind, code, name}]"""
    keys = [f"{lvl}:default"]
    info = {keys[0]: {"key": keys[0], "kind": "level", "code": lvl, "name": LEVEL_NAMES[lvl]}}
    grid = [[0] * W for _ in range(H)]
    rank = [[(-1, 0)] * W for _ in range(H)]   # (kind priority, -area)
    for z in m.zones:
        if z["type"] not in KIND_PRI:
            continue
        key = f"{z['kind']}:{z['name'].lower()}"
        if key not in info:
            nm = gxt.get(z["name"]) or gxt.get(z["name"].lower()) or z["name"]
            info[key] = {"key": key, "kind": z["kind"], "code": z["name"], "name": nm.strip()}
            keys.append(key)
        di = keys.index(key)
        r = (KIND_PRI[z["type"]], -z["w"] * z["h"])
        for y in range(z["y"], min(H, z["y"] + z["h"])):
            for x in range(z["x"], min(W, z["x"] + z["w"])):
                if r > rank[y][x]:
                    rank[y][x] = r; grid[y][x] = di
    for o in overrides.get("rects", []):
        key = o["district"]
        if key not in info:
            info[key] = {"key": key, "kind": "override", "code": key, "name": overrides.get("names", {}).get(key, key)}
            keys.append(key)
        di = keys.index(key)
        x0, y0, w, h = o["rect"]
        for y in range(max(0, y0), min(H, y0 + h)):
            for x in range(max(0, x0), min(W, x0 + w)):
                grid[y][x] = di
    for k, nm in overrides.get("names", {}).items():
        if k in info:
            info[k]["name"] = nm
    for k, st in overrides.get("styles", {}).items():
        if k in info:
            info[k]["style"] = st
    if overrides.get("default_style"):     # the level's own flavour for every district without a row of its own
        for k in info:
            info[k].setdefault("style", overrides["default_style"])
    return [info[k] for k in keys], grid


def rle(row):
    out, prev, n = [], row[0], 0
    for v in row:
        if v == prev:
            n += 1
        else:
            out.append([prev, n]); prev, n = v, 1
    out.append([prev, n])
    return out


def buildings(m, dgrid):
    roof = [[0] * W for _ in range(H)]
    gtype = [[0] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            r, lid, g, st = m.top(x, y)
            roof[y][x] = r; gtype[y][x] = g
    # street level: spread out from the road cells (breadth first, nearest road wins)
    street = [[-1] * W for _ in range(H)]
    q = deque()
    for y in range(H):
        for x in range(W):
            if gtype[y][x] == 1 and roof[y][x] > 0:
                street[y][x] = roof[y][x]; q.append((x, y))
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and street[ny][nx] < 0:
                street[ny][nx] = street[y][x]; q.append((nx, ny))
    def own_wall(x, y):
        off, idx = m.columns[y * W + x]
        for i, bi in enumerate(idx):
            if bi < len(m.blocks) and off + i >= street[y][x] and any(f & 0x3FF for f in m.blocks[bi][:4]):
                return True
        return False
    isb = [[False] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            if gtype[y][x] != 1 and roof[y][x] - max(street[y][x], 0) >= 1:
                isb[y][x] = True
    # plateaus
    lab = [[-1] * W for _ in range(H)]
    parts = []
    for y in range(H):
        for x in range(W):
            if not isb[y][x] or lab[y][x] >= 0:
                continue
            pid = len(parts); cells = []; q = deque([(x, y)]); lab[y][x] = pid
            while q:
                cx, cy = q.popleft(); cells.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < W and 0 <= ny < H and isb[ny][nx] and lab[ny][nx] < 0 and roof[ny][nx] == roof[y][x]:
                        lab[ny][nx] = pid; q.append((nx, ny))
            parts.append(cells)
    # Thin parts (no 2 x 2 square of their own: a roof's raised rim, a parapet ring, a ledge, a one-cell
    # fragment) join the neighbouring part they share the longest edge with, until nothing changes; a thin
    # part with no neighbour stays (a free-standing wall or fence, catalogued as such).
    def thin(cells):
        cs = set(cells)
        return not any((x + 1, y) in cs and (x, y + 1) in cs and (x + 1, y + 1) in cs for x, y in cs)
    changed = True
    while changed:
        changed = False
        for pid in sorted(range(len(parts)), key=lambda p: len(parts[p])):
            cells = parts[pid]
            if not cells or not thin(cells):
                continue
            c = Counter()
            for x, y in cells:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H and lab[ny][nx] >= 0 and lab[ny][nx] != pid:
                        c[lab[ny][nx]] += 1
            if not c:
                continue
            to = c.most_common(1)[0][0]
            for x, y in cells:
                lab[y][x] = to
            parts[to].extend(cells); parts[pid] = []; changed = True
    out = []
    for pid, cells in enumerate(parts):
        if not cells or not any(own_wall(x, y) for x, y in cells):
            continue
        cellset = set(cells)
        xs = [c[0] for c in cells]; ys = [c[1] for c in cells]
        roofs = Counter(roof[y][x] for x, y in cells)
        st = Counter(max(street[y][x], 0) for x, y in cells).most_common(1)[0][0]
        dist = Counter(dgrid[y][x] for x, y in cells).most_common(1)[0][0]
        faces = []
        for x, y in cells:
            for side, (fi, table, nrm, (dx, dy)) in SIDES.items():
                nx, ny = x + dx, y + dy
                if (nx, ny) in cellset:
                    continue
                nroof = roof[ny][nx] if 0 <= nx < W and 0 <= ny < H else 0
                lo = max(nroof, st if not (0 <= nx < W and 0 <= ny < H) else max(street[ny][nx], 0)) if nroof < roof[y][x] else None
                if lo is None:
                    continue
                levels = []
                for lv in range(lo, roof[y][x]):
                    b = m.block(x, y, lv)
                    raw = b[fi] if b else 0
                    levels.append({"level": lv, "tile": raw & 0x3FF, "raw": raw, "slope": (b[6] >> 2) if b else -1})
                if levels:
                    faces.append({"x": x, "y": y, "side": side, "lo": lo, "hi": roof[y][x],
                                  "street": nroof <= max(street[ny][nx] if 0 <= nx < W and 0 <= ny < H else 0, 0) + 0,
                                  "levels": levels})
        out.append({"id": len(out), "thin": thin(cells), "cells": sorted(cells, key=lambda c: (c[1], c[0])), "bbox": [min(xs), min(ys), max(xs), max(ys)],
                    "roof": roofs.most_common(1)[0][0], "roofs": dict(roofs), "street": st,
                    "levels": roofs.most_common(1)[0][0] - st, "area": len(cells), "district": dist, "faces": faces})
    return out, roof, street


def render_png(path, lvl, districts, grid, roof, blds):
    from PIL import Image, ImageDraw
    import colorsys
    S = 4
    img = Image.new("RGB", (W * S + 260, max(H * S, 40 + 14 * len(districts))), (24, 24, 28))
    px = img.load()
    cols = []
    for i, d in enumerate(districts):
        h = (i * 0.618034) % 1.0
        r, g, b = colorsys.hsv_to_rgb(h, 0.55 if d["kind"] != "level" else 0.0, 0.95)
        cols.append((int(r * 255), int(g * 255), int(b * 255)))
    for y in range(H):
        for x in range(W):
            c = cols[grid[y][x]]
            k = 0.35 + 0.65 * min(roof[y][x], 8) / 8.0
            v = tuple(int(ch * k) for ch in c)
            for yy in range(S):
                for xx in range(S):
                    px[x * S + xx, y * S + yy] = v
    dr = ImageDraw.Draw(img)
    for b in blds:
        cs = set(map(tuple, b["cells"]))
        for x, y in cs:
            for dx, dy, seg in ((1, 0, ((x + 1, y), (x + 1, y + 1))), (-1, 0, ((x, y), (x, y + 1))),
                                (0, 1, ((x, y + 1), (x + 1, y + 1))), (0, -1, ((x, y), (x + 1, y)))):
                if (x + dx, y + dy) not in cs:
                    dr.line([(seg[0][0] * S, seg[0][1] * S), (seg[1][0] * S, seg[1][1] * S)], fill=(255, 255, 255))
    used = Counter(grid[y][x] for y in range(H) for x in range(W))
    yy = 6
    dr.text((W * S + 8, yy), f"{lvl} ({LEVEL_NAMES[lvl]}): {len(blds)} buildings", fill=(255, 255, 255)); yy += 16
    for i, d in enumerate(districts):
        if not used[i]:
            continue
        dr.rectangle([W * S + 8, yy, W * S + 18, yy + 9], fill=cols[i])
        dr.text((W * S + 24, yy - 1), f"{d['kind'][:5]} {d['code']} {d['name'][:22]}", fill=(230, 230, 230)); yy += 13
    img.save(path)


def main():
    data_dir, lvl, out = sys.argv[1], sys.argv[2], sys.argv[3]
    ovdir = sys.argv[sys.argv.index("--overrides") + 1] if "--overrides" in sys.argv else os.path.join(os.path.dirname(os.path.abspath(__file__)), "overrides")
    os.makedirs(out, exist_ok=True)
    m = gmap.Map(os.path.join(data_dir, f"{lvl}.gmp"))
    gxt = read_gxt(os.path.join(data_dir, "e.gxt")) if os.path.exists(os.path.join(data_dir, "e.gxt")) else {}
    ovp = os.path.join(ovdir, f"{lvl}.json")
    overrides = json.load(open(ovp)) if os.path.exists(ovp) else {}
    districts, grid = district_grid(m, lvl, gxt, overrides)
    blds, roof, street = buildings(m, grid)
    used = Counter(grid[y][x] for y in range(H) for x in range(W))
    for i, d in enumerate(districts):
        d["cells"] = used[i]
        d["buildings"] = sum(1 for b in blds if b["district"] == i)
    json.dump({"level": lvl, "priority": "local_nav > gang > nav > level default; smallest zone within a kind; overrides last",
               "districts": districts, "grid_rle": [rle(r) for r in grid]}, open(os.path.join(out, f"{lvl}_districts.json"), "w"))
    json.dump({"level": lvl, "buildings": blds}, open(os.path.join(out, f"{lvl}_buildings.json"), "w"))
    render_png(os.path.join(out, f"{lvl}_districts.png"), lvl, districts, grid, roof, blds)
    sizes = Counter(min(b["area"], 50) // 10 * 10 for b in blds)
    print(f"{lvl}: {len(districts)} districts, {len(blds)} buildings, faces {sum(len(b['faces']) for b in blds)}, "
          f"wall face-levels {sum(len(f['levels']) for b in blds for f in b['faces'])}, area buckets {sorted(sizes.items())}")
    for d in districts:
        if d["cells"]:
            print(f"   {d['kind']:9s} {d['code']:20s} {d['name'][:30]:30s} cells {d['cells']:6d} buildings {d['buildings']}")


if __name__ == "__main__":
    main()
