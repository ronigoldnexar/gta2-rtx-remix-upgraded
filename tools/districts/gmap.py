"""GTA2 block map (.gmp) reader shared by the districts tools (DMAP columns and blocks, ZONE
records) plus the renderer's wall-face texture mapping (src/world_mesh.cpp FaceUvs), so the
offline kit can put geometry exactly where a tile's art is. Map frame: x east, y south, 256 x 256.
World frame (renderer): X = x, Y = level, Z = 255 - y for a cell's south edge (+Z north)."""
import struct

W = H = 256
KTILE = 64
UV_INSET = 0.5 / KTILE
UV_MIN, UV_MAX = UV_INSET, 1.0 - UV_INSET

ZONE_TYPES = {0: "general", 1: "nav", 2: "traffic_light", 5: "arrow_blocker", 6: "rail_station",
              7: "bus_stop", 8: "trigger", 10: "info", 11: "rail_entry", 12: "rail_exit", 13: "rail_stop",
              14: "gang", 15: "local_nav", 16: "restart", 20: "arrest_restart"}


def chunks(data):
    out, off = {}, 6
    while off + 8 <= len(data):
        tag = data[off:off + 4].decode("latin1")
        size = struct.unpack_from("<I", data, off + 4)[0]
        out[tag] = (off + 8, size)
        off += 8 + size
    return out


class Map:
    def __init__(self, path):
        data = open(path, "rb").read()
        assert data[:4] == b"GBMP", path
        c = chunks(data)
        base, _ = c["DMAP"]
        pool = base + W * H * 4
        words = struct.unpack_from("<I", data, pool)[0]
        coldata = pool + 4
        nb_off = coldata + words * 4
        nblocks = struct.unpack_from("<I", data, nb_off)[0]
        bdata = nb_off + 4
        self.blocks = [struct.unpack_from("<HHHHHBB", data, bdata + i * 12) for i in range(nblocks)]
        self.columns = []
        for cell in range(W * H):
            wi = struct.unpack_from("<I", data, base + cell * 4)[0]
            p = coldata + wi * 4
            height, offset = data[p], data[p + 1]
            idx = [struct.unpack_from("<I", data, p + 4 + i * 4)[0] for i in range(max(0, height - offset))]
            self.columns.append((offset, idx))
        self.zones = []
        if "ZONE" in c:
            zb, zs = c["ZONE"]
            p = zb
            while p + 6 <= zb + zs:
                t, x, y, w, h, nl = data[p:p + 6]
                name = data[p + 6:p + 6 + nl].decode("latin1")
                self.zones.append({"type": t, "kind": ZONE_TYPES.get(t, str(t)), "x": x, "y": y, "w": w, "h": h, "name": name})
                p += 6 + nl

    def block(self, x, y, level):
        """(left, right, top, bottom, lid, arrows, slope) at (x, y, level) or None"""
        if not (0 <= x < W and 0 <= y < H):
            return None
        off, idx = self.columns[y * W + x]
        i = level - off
        if 0 <= i < len(idx) and idx[i] < len(self.blocks):
            return self.blocks[idx[i]]
        return None

    def top(self, x, y):
        """(roof height, lid tile, ground type, slope type) of the highest block that has a lid or a
        side face; roof height = that block's level + 1; (0, 0, 0, 0) for an empty column"""
        off, idx = self.columns[y * W + x]
        for i in range(len(idx) - 1, -1, -1):
            if idx[i] >= len(self.blocks):
                continue
            b = self.blocks[idx[i]]
            if any(f & 0x3FF for f in b[:5]):
                return off + i + 1, b[4] & 0x3FF, b[6] & 3, b[6] >> 2
        return 0, 0, 0, 0


# ---- wall faces: the renderer's corner order and orientation tables (world_mesh.cpp AddBlock) ----
LEFT_FLAGS = (0x23, 0x33, 0x43, 0x53, 0x63, 0x73, 0x03, 0x13)
RIGHT_FLAGS = (0x64, 0x74, 0x04, 0x14, 0x24, 0x34, 0x44, 0x54)
TOP_FLAGS = (0x41, 0x49, 0x61, 0x69, 0x01, 0x09, 0x21, 0x29)
BOTTOM_FLAGS = (0x02, 0x0A, 0x22, 0x2A, 0x42, 0x4A, 0x62, 0x6A)
SIDES = {  # side name: (block field index, flags table, outward normal in world (x, z), neighbour map offset (dx, dy))
    "W": (0, LEFT_FLAGS, (-1.0, 0.0), (-1, 0)),
    "E": (1, RIGHT_FLAGS, (1.0, 0.0), (1, 0)),
    "N": (2, TOP_FLAGS, (0.0, 1.0), (0, -1)),
    "S": (3, BOTTOM_FLAGS, (0.0, -1.0), (0, 1)),
}


def face_uvs(raw, table):
    uv = [[UV_MIN, UV_MIN], [UV_MAX, UV_MIN], [UV_MAX, UV_MAX], [UV_MIN, UV_MAX]]
    flags = table[(raw >> 13) & 7]
    r = flags & 0x60
    if r == 0x20:
        uv = [uv[3], uv[0], uv[1], uv[2]]
    elif r == 0x40:
        flags ^= 0x18
    elif r == 0x60:
        uv = [uv[1], uv[2], uv[3], uv[0]]
    if flags & 0x8:
        uv = [uv[1], uv[0], uv[3], uv[2]]
    if flags & 0x10:
        uv = [uv[3], uv[2], uv[1], uv[0]]
    return uv


def wall_corners(x, y, level, side):
    """the four corners of a full-height wall in the renderer's slot order (AddBlock)"""
    xw, xe = float(x), float(x + 1)
    zs = float(H - y - 1)
    zn = zs + 1.0
    b, t = float(level), float(level + 1)
    return {
        "W": [(xw, b, zn), (xw, t, zn), (xw, t, zs), (xw, b, zs)],
        "E": [(xe, t, zn), (xe, b, zn), (xe, b, zs), (xe, t, zs)],
        "N": [(xw, b, zn), (xe, b, zn), (xe, t, zn), (xw, t, zn)],
        "S": [(xw, t, zs), (xe, t, zs), (xe, b, zs), (xw, b, zs)],
    }[side]


class FaceFrame:
    """affine map tile-art texel (tx, ty in 0..64, y down) -> world point on a wall face, the inverse
    of the renderer's mapping (LidFrame in world_mesh.cpp), and back to the face's UV"""

    def __init__(self, x, y, level, side, raw):
        c = wall_corners(x, y, level, side)
        uv = face_uvs(raw, SIDES[side][1])
        self.o = c[0]
        self.ds = tuple(c[1][k] - c[0][k] for k in range(3))
        self.dt = tuple(c[3][k] - c[0][k] for k in range(3))
        self.uo = uv[0]
        self.us = (uv[1][0] - uv[0][0], uv[1][1] - uv[0][1])
        self.ut = (uv[3][0] - uv[0][0], uv[3][1] - uv[0][1])
        self.det = self.us[0] * self.ut[1] - self.us[1] * self.ut[0]
        n = SIDES[side][2]
        self.n = (n[0], 0.0, n[1])

    def uv(self, tx, ty):
        """texel -> the texture coordinate the renderer would give that spot (inset range)"""
        return (UV_MIN + tx / KTILE * (UV_MAX - UV_MIN), UV_MIN + ty / KTILE * (UV_MAX - UV_MIN))

    def at(self, tx, ty, d=0.0):
        u, v = self.uv(tx, ty)
        u -= self.uo[0]
        v -= self.uo[1]
        s = (u * self.ut[1] - v * self.ut[0]) / self.det
        t = (self.us[0] * v - self.us[1] * u) / self.det
        return tuple(self.o[k] + self.ds[k] * s + self.dt[k] * t + self.n[k] * d for k in range(3))
