"""GTA2 .gmp + .gxt reader for the city-map prototype (numpy)."""
import struct
import numpy as np

W = H = 256

def chunks(data):
    off = 6; out = {}
    while off + 8 <= len(data):
        tag = data[off:off + 4].decode("latin1"); size = struct.unpack_from("<I", data, off + 4)[0]
        out[tag] = (off + 8, size); off += 8 + size
    return out

class Level:
    def __init__(self, path):
        data = open(path, "rb").read()
        assert data[:4] == b"GBMP"
        ch = chunks(data)
        base, _ = ch["DMAP"]
        pool = base + W * H * 4
        words = struct.unpack_from("<I", data, pool)[0]
        coldata = pool + 4
        nb_off = coldata + words * 4
        nb = struct.unpack_from("<I", data, nb_off)[0]
        b = np.frombuffer(data, dtype=np.dtype([("l","<u2"),("r","<u2"),("t","<u2"),("b","<u2"),("lid","<u2"),("arrows","u1"),("slope","u1")]), count=nb, offset=nb_off + 4)
        self.blocks = b
        # dense block index per (level, y, x); -1 = none
        self.grid = np.full((8, H, W), -1, dtype=np.int32)
        bw = np.frombuffer(data, dtype="<u4", count=W * H, offset=base)
        for cell in range(W * H):
            p = coldata + int(bw[cell]) * 4
            height, offset = data[p], data[p + 1]
            n = max(0, height - offset)
            if n:
                idx = np.frombuffer(data, dtype="<u4", count=n, offset=p + 4)
                y, x = divmod(cell, W)
                self.grid[offset:offset + n, y, x] = idx
        g = self.grid
        valid = g >= 0
        gi = np.where(valid, g, 0)
        self.lid = np.where(valid, b["lid"][gi] & 0x3FF, 0)
        self.slope = np.where(valid, b["slope"][gi], 0)
        self.arrows = np.where(valid, b["arrows"][gi], 0)
        self.ground = self.slope & 3
        self.slopetype = self.slope >> 2
        def wall(f): return np.where(valid, (b[f][gi] & 0x400) != 0, False)
        def tile(f): return np.where(valid, b[f][gi] & 0x3FF, 0)
        self.wall = {f: wall(f) for f in ("l", "r", "t", "b")}
        self.side = {f: tile(f) for f in ("l", "r", "t", "b")}
        self.valid = valid
        # zones
        self.zones = []
        if "ZONE" in ch:
            o, sz = ch["ZONE"]; z = data[o:o + sz]; p = 0
            while p + 6 <= len(z):
                typ, x, y, w, h, nl = struct.unpack_from("<6B", z, p)
                self.zones.append((typ, x, y, w, h, z[p + 6:p + 6 + nl].decode("latin1"))); p += 6 + nl
        self.chunks = list(ch)

def read_gxt(path):
    data = open(path, "rb").read()
    off = 6; keys = []; tdat = None
    while off + 8 <= len(data):
        tag = data[off:off + 4]; size = struct.unpack_from("<I", data, off + 4)[0]
        body = off + 8
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
        while end + 1 < len(tdat) and tdat[end:end + 2] != b"\0\0": end += 2
        out[k] = tdat[o:end].decode("utf-16-le", "replace")
    return out
