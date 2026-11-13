#!/usr/bin/env python3
"""DISTRICTS streaming: pack a full (LOD0) and a coarse (LOD1) kit into one chunked, quantized file the renderer
streams around the eye (src/kit_stream.cpp).

    pack_kit.py <lod0 .kit> <lod1 .kit> <out .kit2> [--chunk 16]

Triangles go to the chunk of their centroid (chunk x 16 x 16 cells in plan); within a chunk and LOD they are grouped
by texture, split at 4 096 triangles (12 288 vertices). Vertex: 14 bytes (int16 x y z at 1/1024 block from the group's origin, int8
normal, half-float u v relative to the group's integer uv base) against 32 bytes as floats; indices 16-bit.
Layout (little endian): b"GDK2", u32 version 2, f32 chunk size, u32 entries; entry: i16 cx, i16 cz, u8 lod, 3 pad,
f32 bbox[6] (x0 y0 z0 x1 y1 z1), u32 groups, u32 offset, u32 bytes; at offset, per group: i32 tile, u32 flags,
u32 vertices, u32 indices, f32 origin[3], f32 uv base[2], vertices, u16 indices (padded to 4 bytes).
Deterministic: entries sorted by (cz, cx, lod), groups by (tile, flags)."""
import struct, sys
from collections import defaultdict
import numpy as np


def read_kit(path):
    data = open(path, "rb").read()
    ng = struct.unpack_from("<I", data, 8)[0]
    p, out = 12, []
    for _ in range(ng):
        tile, flags, nv, ni = struct.unpack_from("<iIII", data, p); p += 16
        vs = np.frombuffer(data, np.float32, nv * 8, p).reshape(nv, 8); p += nv * 32
        ix = np.frombuffer(data, np.uint32, ni, p).reshape(-1, 3); p += ni * 4
        out.append((tile, flags, vs, ix))
    return out


def main():
    l0, l1, outp = sys.argv[1:4]
    cs = float(sys.argv[sys.argv.index("--chunk") + 1]) if "--chunk" in sys.argv else 16.0
    buckets = defaultdict(list)    # (cz, cx, lod, tile, flags) -> list of triangle vertex arrays (n, 3, 8)
    for lod, path in ((0, l0), (1, l1)):
        for tile, flags, vs, ix in read_kit(path):
            tri = vs[ix]                                   # (n, 3, 8)
            cen = tri[:, :, :3].mean(1)
            cx = np.floor(cen[:, 0] / cs).astype(int); cz = np.floor(cen[:, 2] / cs).astype(int)
            for key in sorted(set(zip(cz.tolist(), cx.tolist()))):
                sel = (cz == key[0]) & (cx == key[1])
                buckets[(key[0], key[1], lod, tile, flags)].append(tri[sel])
    entries = defaultdict(list)
    for (cz, cx, lod, tile, flags), parts in sorted(buckets.items()):
        entries[(cz, cx, lod)].append((tile, flags, np.concatenate(parts)))
    blobs, table = [], []
    for (cz, cx, lod) in sorted(entries):
        gb = b""
        allp = np.concatenate([t[:, :, :3].reshape(-1, 3) for _, _, t in entries[(cz, cx, lod)]])
        bb = list(allp.min(0)) + list(allp.max(0))
        ngroups = 0
        for tile, flags, tri in entries[(cz, cx, lod)]:
            for s0 in range(0, len(tri), 4096):          # 12 288 vertices at most (no sharing: 3 a triangle): a group fits
                                                         # the holes of a used 2 MB page (a 63 000-vertex group needed a
                                                         # whole empty page and was refused once the pool was in use)
                t = tri[s0:s0 + 4096].reshape(-1, 8)
                origin = t[:, :3].min(0)
                uvb = np.floor(t[:, 6:8].min(0)) if flags & 4 else np.zeros(2, np.float32)
                pos = np.clip(np.round((t[:, :3] - origin) * 1024.0), -32768, 32767).astype(np.int16)
                nrm = np.clip(np.round(t[:, 3:6] * 127.0), -127, 127).astype(np.int8)
                uv = (t[:, 6:8] - uvb).astype(np.float16)
                v = np.zeros(len(t), dtype=[("p", "<i2", 3), ("n", "i1", 4), ("uv", "<f2", 2)])
                v["p"] = pos; v["n"][:, :3] = nrm; v["uv"] = uv
                idx = np.arange(len(t), dtype=np.uint16)
                gb += struct.pack("<iIII3f2f", tile, flags, len(t), len(idx), *origin.tolist(), *uvb.tolist())
                gb += v.tobytes() + idx.tobytes() + (b"\0\0" if len(idx) % 2 else b"")
                ngroups += 1
        table.append((cx, cz, lod, bb, ngroups, len(gb)))
        blobs.append(gb)
    head = b"GDK2" + struct.pack("<IfI", 2, cs, len(table))
    off = len(head) + len(table) * (2 + 2 + 4 + 24 + 12)
    tb = b""
    for (cx, cz, lod, bb, ng, nb) in table:
        tb += struct.pack("<hhB3x6fIII", cx, cz, lod, *[float(v) for v in bb], ng, off, nb)
        off += nb
    with open(outp, "wb") as f:
        f.write(head + tb + b"".join(blobs))
    tris = [sum(len(t) for _, _, t in entries[k]) for k in sorted(entries)]
    n0 = sum(t for k, t in zip(sorted(entries), tris) if k[2] == 0); n1 = sum(t for k, t in zip(sorted(entries), tris) if k[2] == 1)
    print(f"{outp}: {len(table)} chunk entries, LOD0 {n0} triangles, LOD1 {n1} triangles, {(len(head) + len(tb) + sum(map(len, blobs))) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
