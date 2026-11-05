#!/usr/bin/env python3
"""Reads a GTA2 .gmp map (GBMP, DMAP chunk) and answers walkability questions,
for steering the game from a script: which cells are road, pavement or field at
street level, and a walking route from a cell to the nearest road.
   gmp.py <map.gmp> <x> <y>            route from (x,y) to the nearest road cell
"""
import struct, sys
from collections import deque

W = H = 256

def load(path):
    data = open(path, "rb").read()
    assert data[:4] == b"GBMP"
    off = 6; dmap = None
    while off + 8 <= len(data):
        tag = data[off:off+4]; size = struct.unpack_from("<I", data, off + 4)[0]
        body = off + 8
        if tag == b"DMAP": dmap = (body, size)
        off = body + size
    base, size = dmap
    pool = base + W * H * 4
    words = struct.unpack_from("<I", data, pool)[0]
    coldata = pool + 4
    nblocks_off = coldata + words * 4
    nblocks = struct.unpack_from("<I", data, nblocks_off)[0]
    bdata = nblocks_off + 4
    blocks = [struct.unpack_from("<HHHHHBB", data, bdata + i * 12) for i in range(nblocks)]
    columns = {}
    for cell in range(W * H):
        wi = struct.unpack_from("<I", data, base + cell * 4)[0]
        p = coldata + wi * 4
        height, offset = data[p], data[p + 1]
        count = height - offset
        idx = [struct.unpack_from("<I", data, p + 4 + i * 4)[0] for i in range(max(0, count))]
        columns[cell] = (offset, idx)
    return blocks, columns

def block_at(blocks, columns, x, y, level):
    offset, idx = columns[y * W + x]
    i = level - offset
    if i < 0 or i >= len(idx): return None
    return blocks[idx[i]]

def ground(blocks, columns, x, y, level=1):
    """ground type of the block whose lid you stand on at `level`: 0 air 1 road 2 pavement 3 field, None if nothing"""
    b = block_at(blocks, columns, x, y, level)
    if not b or not b[4]: return None          # no lid: nothing to stand on
    above = block_at(blocks, columns, x, y, level + 1)
    if above and any(above[:5]): return None   # something built on it
    return b[6] & 3

def route(blocks, columns, sx, sy, level=1):
    start = (sx, sy)
    seen = {start: None}; q = deque([start])
    while q:
        c = q.popleft()
        g = ground(blocks, columns, c[0], c[1], level)
        if g == 1 and c != start:
            path = []; 
            while c: path.append(c); c = seen[c]
            return path[::-1]
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
            n = (c[0] + dx, c[1] + dy)
            if n in seen or not (0 <= n[0] < W and 0 <= n[1] < H): continue
            gn = ground(blocks, columns, n[0], n[1], level)
            if gn in (1, 2, 3):
                seen[n] = c; q.append(n)
    return None

def route_to(blocks, columns, sx, sy, tx, ty, level=1):
    """walking route to the cell nearest (tx,ty) that can be reached, over road, pavement and field"""
    start = (sx, sy)
    seen = {start: None}; q = deque([start]); best = start; bestd = abs(tx - sx) + abs(ty - sy)
    while q:
        c = q.popleft()
        d = abs(c[0] - tx) + abs(c[1] - ty)
        if d < bestd: best, bestd = c, d
        if d == 0: break
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
            n = (c[0] + dx, c[1] + dy)
            if n in seen or not (0 <= n[0] < W and 0 <= n[1] < H): continue
            if ground(blocks, columns, n[0], n[1], level) in (1, 2, 3):
                seen[n] = c; q.append(n)
    path = []; c = best
    while c: path.append(c); c = seen[c]
    return path[::-1]

if __name__ == "__main__":
    blocks, columns = load(sys.argv[1])
    x, y = int(float(sys.argv[2])), int(float(sys.argv[3]))
    lvl = int(sys.argv[4]) - 1 if len(sys.argv) > 4 else 1
    print("here:", ground(blocks, columns, x, y, lvl))
    names = {None: "#", 0: " ", 1: "=", 2: ".", 3: ","}
    for yy in range(y - 8, y + 9):
        print("".join("P" if (xx, yy) == (x, y) else names[ground(blocks, columns, xx, yy, lvl)] for xx in range(x - 20, x + 21)))
    r = route(blocks, columns, x, y, lvl)
    print("route:", r)
