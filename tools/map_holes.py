#!/usr/bin/env python3
"""Lists the cells of a GTA2 map where a street-level camera can look at
"nothing": places the top-down renderer never had to draw, so the map stores no
face for them.

    map_holes.py <game/data dir> [--district wil|bil|ste] [--list N]

Classes (a cell can be in several):
  lidless_ground   a stored block with no lid but a ground type or road arrows
                   (a road or pavement running under a deck): its top is the
                   surface the game walks and drives on, and nothing is drawn.
  deck_underside   a block with a lid whose lower neighbour in the column is a
                   stored, empty block: the underside of a bridge or overhang,
                   seen from the ground below.
  slope_base       a column whose first stored block is a slope (no flat lid to
                   stand on at the base).
  lidless_top      a column whose top stored block has no lid and nothing with
                   a lid under it in the stack (nothing at all faces upward).
Each class is counted per district with the cells ranked by how many
neighbouring cells are walkable at street level (a rough visibility weight).
"""
import os, struct, sys
from collections import Counter

W = H = 256


def load(path):
    data = open(path, "rb").read()
    assert data[:4] == b"GBMP"
    off = 6
    dmap = None
    while off + 8 <= len(data):
        tag = data[off:off + 4]
        size = struct.unpack_from("<I", data, off + 4)[0]
        body = off + 8
        if tag == b"DMAP":
            dmap = (body, size)
        off = body + size
    base, _ = dmap
    pool = base + W * H * 4
    words = struct.unpack_from("<I", data, pool)[0]
    coldata = pool + 4
    nblocks_off = coldata + words * 4
    nblocks = struct.unpack_from("<I", data, nblocks_off)[0]
    bdata = nblocks_off + 4
    blocks = [struct.unpack_from("<HHHHHBB", data, bdata + i * 12) for i in range(nblocks)]
    columns = []
    for cell in range(W * H):
        wi = struct.unpack_from("<I", data, base + cell * 4)[0]
        p = coldata + wi * 4
        height, offset = data[p], data[p + 1]
        idx = [struct.unpack_from("<I", data, p + 4 + i * 4)[0] for i in range(max(0, height - offset))]
        columns.append((offset, idx))
    return blocks, columns


def tile(face):
    return face & 0x3FF


def classify(blocks, columns):
    found = {"lidless_ground": [], "deck_underside": [], "slope_base": [], "lidless_top": []}
    for y in range(H):
        for x in range(W):
            offset, idx = columns[y * W + x]
            if not idx:
                continue
            stack = [blocks[i] for i in idx]
            first = stack[0]
            if (first[6] >> 2) not in (0, 63) and (first[6] >> 2) < 61:
                found["slope_base"].append((x, y, offset))
            for i, b in enumerate(stack):
                level = offset + i
                lid, arrows, slope = tile(b[4]), b[5], b[6]
                stype, gtype = slope >> 2, slope & 3
                empty = not any(tile(f) for f in b[:5])
                if lid == 0 and stype == 0 and (gtype != 0 or arrows != 0) and i + 1 < len(stack):
                    found["lidless_ground"].append((x, y, level))
                if lid != 0 and i > 0:
                    below = stack[i - 1]
                    below_empty = not any(tile(f) for f in below[:5]) and (below[6] >> 2) == 0
                    if below_empty:
                        found["deck_underside"].append((x, y, level))
            if not any(tile(b[4]) for b in stack):
                found["lidless_top"].append((x, y, offset + len(stack) - 1))
    return found


def main():
    args = sys.argv[1:]
    data_dir = args[0] if args else "game/data"
    districts = ["wil", "bil", "ste"]
    if "--district" in args:
        districts = [args[args.index("--district") + 1]]
    limit = int(args[args.index("--list") + 1]) if "--list" in args else 8
    print("| district | class | cells | examples (x,y,level) |")
    print("|---|---|---|---|")
    for d in districts:
        path = os.path.join(data_dir, f"{d}.gmp")
        if not os.path.exists(path):
            continue
        blocks, columns = load(path)
        found = classify(blocks, columns)
        for cls, cells in found.items():
            # Rank by how many of the 8 neighbours are lidded at the same level:
            # a hole in open road is seen more than one inside a building.
            def weight(c):
                x, y, level = c
                n = 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dx == dy == 0:
                            continue
                        cx, cy = x + dx, y + dy
                        if 0 <= cx < W and 0 <= cy < H:
                            off, idx = columns[cy * W + cx]
                            for i, j in enumerate(idx):
                                if off + i == level and tile(blocks[j][4]):
                                    n += 1
                return -n
            cells = sorted(cells, key=weight)
            ex = ", ".join(f"({x},{y},{l})" for x, y, l in cells[:limit])
            print(f"| {d} | {cls} | {len(cells)} | {ex} |")


if __name__ == "__main__":
    main()
