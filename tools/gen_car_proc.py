#!/usr/bin/env python3
"""Procedural period car bodies from GTA2 car sprites.

Every GTA2 vehicle is a top-down sprite drawn in a retro-futuristic 1940s-60s
American idiom. This tool turns each sprite into a clean 3D body that keeps the
sprite as its roof/hood/trunk paint (projected straight down, so the classic
view shows the game's own art) and gives it a period side profile: long hood,
rounded fenders, wraparound windscreen, tail fins, chrome bumpers with
over-riders, belt-line spear, round headlamps in bezels, wheels with hubcaps.
Vans, trucks (bonneted and cab-over), buses, trailers, trains, pickups, limos,
police cars, taxis, open jeeps, fastback compacts and microcars, bikes and the
tank get their own profiles.

Inputs
  --style       a GTA2 style file (wil.sty): CARI gives each model's sprite,
                width/length, wheel and window offsets, remaps and doors.
  --catalog     assets-src/cars/catalog.json (the CATALOG agent): names, class
                (`cls`), design brief, remap list with native and ESRGAN x4
                sprite files and paint colours. Without it classes are inferred.
  --sprite-root folder the catalog's sprite paths are relative to.

Outputs
  <out>/<name>.glb and <name>_<remap>.glb, status.json (measurements, wheel
  positions, triangle counts), and a preview sheet: sprite | top render |
  three-quarter render, from a small software rasteriser (no GPU needed).

Conventions (match assets-src/cars/design_language.md): 1 block = 64 px; the
model's origin is the sprite canvas centre on the ground plane; +x right,
+y up, +z toward the nose. The sprite is drawn nose-down (the nose is at the
larger image row), and the CARI wheel/window offsets are signed pixels from the
sprite centre, positive toward the nose.
"""
import argparse
import json
import math
import os
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BLOCK_PX = 64.0
M = 1.0 / 4.5          # one metre in blocks (a GTA2 block is about 4.5 m)


# ----------------------------------------------------------------------------
# Style file: palettes, car sprites, CARI
# ----------------------------------------------------------------------------
class Style:
    PAGE = 65536
    STRIDE = 256

    def __init__(self, path):
        d = open(path, "rb").read()
        if d[:4] != b"GBST":
            raise SystemExit(f"{path}: not a GTA2 style file")
        self.ppal = b""
        self.palx = []
        self.palb = [0] * 8
        self.sprg = b""
        self.sprx = []
        self.sprb = [0] * 6
        self.cars = []
        off = 6
        while off + 8 <= len(d):
            tag = d[off:off + 4].decode("ascii", "replace")
            size = struct.unpack_from("<I", d, off + 4)[0]
            body = d[off + 8:off + 8 + size]
            if tag == "PPAL":
                self.ppal = body
            elif tag == "PALX":
                self.palx = list(struct.unpack_from("<%dH" % (len(body) // 2), body))
            elif tag == "PALB":
                self.palb = list(struct.unpack_from("<8H", body))
            elif tag == "SPRG":
                self.sprg = body
            elif tag == "SPRX":
                self.sprx = [struct.unpack_from("<IBBH", body, i) for i in range(0, len(body) - 7, 8)]
            elif tag == "SPRB":
                self.sprb = list(struct.unpack_from("<6H", body))
            elif tag == "CARI":
                self._parse_cari(body)
            off += 8 + size

    def _parse_cari(self, b):
        sprite = -1
        at = 0
        while at + 14 <= len(b):
            r = b[at:at + 14]
            remaps = r[4]
            if at + 14 + remaps + 1 > len(b):
                break
            doors = b[at + 14 + remaps]
            if r[1]:
                sprite += 1
            door_list = []
            for k in range(doors):
                rx, ry = struct.unpack_from("<bb", b, at + 15 + remaps + 2 * k)
                door_list.append([rx, ry])
            c = dict(
                model=r[0], sprite=max(sprite, 0), width=r[2], height=r[3],
                passengers=r[5], wreck_type=r[6], rating=r[7],
                front_wheel=struct.unpack("<b", r[8:9])[0], rear_wheel=struct.unpack("<b", r[9:10])[0],
                front_window=struct.unpack("<b", r[10:11])[0], rear_window=struct.unpack("<b", r[11:12])[0],
                flags=[r[12], r[13]], remaps=list(b[at + 14:at + 14 + remaps]), doors=door_list)
            # The wreck models carry one placeholder measurement set and no doors.
            c["wreck"] = (not door_list) and c["front_wheel"] == 7 and c["rear_wheel"] == -17 and c["front_window"] == 17
            self.cars.append(c)
            at += 14 + remaps + 1 + 2 * doors

    def palette(self, virtual):
        p = self.palx[virtual]
        base = (p // 64) * self.PAGE + (p % 64) * 4
        pal = np.zeros((256, 3), np.uint8)
        for i in range(256):
            at = base + i * 256
            pal[i] = (self.ppal[at + 2], self.ppal[at + 1], self.ppal[at])
        return pal

    def car_sprite(self, index, remap=None):
        """RGBA image of car sprite `index` (within the car base), optionally
        through car remap palette `remap`."""
        ptr, w, h, _ = self.sprx[index]
        page, x, y = ptr // self.PAGE, ptr % self.STRIDE, (ptr % self.PAGE) // self.STRIDE
        idx = np.frombuffer(self.sprg, np.uint8).reshape(-1, self.STRIDE)
        rows = idx[page * self.STRIDE + y: page * self.STRIDE + y + h, x:x + w]
        virtual = self.palb[0] + index if remap is None else self.palb[0] + self.palb[1] + remap
        pal = self.palette(virtual)
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[..., :3] = pal[rows]
        rgba[..., 3] = np.where(rows == 0, 0, 255)
        return rgba


# ----------------------------------------------------------------------------
# Catalog
# ----------------------------------------------------------------------------
def infer_class(c):
    w, h = c["width"], c["height"]
    if w <= 14:
        return "bike"
    if h >= 120:
        return "train" if w <= 34 else "bus"
    if h >= 96:
        return "bus"
    if h >= 78 and w >= 34:
        return "truck"
    if c.get("rear_window", -99) >= -0.06 * h and c.get("front_window", 0) > 0.15 * h:
        return "pickup"
    if w >= 38 and h >= 60:
        return "van"
    return "sedan"


def load_catalog(path, style):
    """One record per CARI model: measurements from CARI, name/class/design/
    remap files from the catalog when present."""
    by_model = {}
    if path and os.path.exists(path):
        cat = json.load(open(path))
        entries = cat.get("cars", cat) if isinstance(cat, dict) else cat
        if isinstance(entries, dict):
            entries = list(entries.values())
        for e in entries:
            if "model" in e:
                by_model[int(e["model"])] = e
    records = []
    for c in style.cars:
        e = dict(c)
        x = by_model.get(c["model"], {})
        e["name"] = str(x.get("name", f"car_{c['model']:02d}"))
        e["slug"] = f"{c['model']:03d}_" + "".join(ch if ch.isalnum() else "_" for ch in e["name"].lower()).strip("_")
        e["class"] = str(x.get("cls", x.get("class", infer_class(c)))).lower()
        e["design"] = x.get("design", {})
        e["catalog_remaps"] = x.get("remaps", [])
        e["script_name"] = x.get("script_name", "")
        e["info_flags"] = x.get("info_flags", c["flags"])
        if e["class"] == "wreck":
            e["wreck"] = True
        records.append(e)
    return records


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def smoothstep(a, b, x):
    t = np.clip((x - a) / max(b - a, 1e-6), 0.0, 1.0)
    return float(t * t * (3 - 2 * t))


def sprite_body_colour(rgba):
    """Median paint colour: opaque pixels from the car's middle that are
    neither the dark outline nor glass."""
    h, w, _ = rgba.shape
    px = rgba[h // 6: h - h // 6, w // 5: w - w // 5]
    op = px[px[..., 3] > 0][..., :3].astype(np.float32)
    if len(op) == 0:
        return np.array([150, 150, 150], np.float32)
    lum = op.mean(axis=1)
    keep = op[lum > 40]
    if len(keep) < 10:
        keep = op
    blue = keep[:, 2] - keep[:, :2].mean(axis=1)
    mask = ~((blue > 20) & (keep.mean(axis=1) < 120))
    if mask.sum() > 10:
        keep = keep[mask]
    return np.median(keep, axis=0)


def sprite_glass_colour(rgba, rows):
    r0, r1 = rows
    h, w, _ = rgba.shape
    px = rgba[max(0, r0):min(h, r1), w // 4: w - w // 4]
    op = px[px[..., 3] > 0][..., :3].astype(np.float32)
    if len(op) < 5:
        return np.array([44, 54, 72], np.float32)
    dark = op[op.mean(axis=1) < np.percentile(op.mean(axis=1), 35)]
    c = np.median(dark if len(dark) else op, axis=0)
    # Keep it glass: cool and dark whatever the paint.
    return np.clip(c * 0.7 + np.array([10, 16, 30]), 20, 110)


def footprint(rgba, cari_width):
    """Per-row half-widths (blocks, already smoothed) of the car, the row and
    column range it occupies, and its centre column."""
    a = rgba[..., 3] > 0
    rows = np.where(a.any(axis=1))[0]
    cols = np.where(a.any(axis=0))[0]
    y0, y1 = int(rows[0]), int(rows[-1]) + 1
    x0, x1 = int(cols[0]), int(cols[-1]) + 1
    cx = (x0 + x1) / 2.0
    half = np.zeros(y1 - y0, np.float32)
    for i, r in enumerate(range(y0, y1)):
        c = np.where(a[r])[0]
        half[i] = max(c[-1] + 1 - cx, cx - c[0]) if len(c) else 0.0
    cap = cari_width / 2.0 + 1.0
    half = np.minimum(half, cap)
    k = np.array([1, 2, 3, 2, 1], np.float32) / 9.0
    half = np.convolve(np.pad(half, 2, mode="edge"), k, mode="valid")
    return half / BLOCK_PX, (y0, y1, x0, x1, cx)


# ----------------------------------------------------------------------------
# Class presets (heights in blocks). hb: belt line; hood: at the nose; roof;
# trunk: deck behind the cabin; box: cargo box roof (trucks); fin: tail fin
# rise; r: wheel radius; gi/th: greenhouse inset at the belt / at the roof.
# ----------------------------------------------------------------------------
def P_(g, hb, hood, roof, trunk, fin, r, gi, th, box=None):
    return dict(g=g * M, hb=hb * M, hood=hood * M, roof=roof * M, trunk=trunk * M, fin=fin * M, r=r * M, gi=gi, th=th, box=(box or roof) * M)


PRESETS = {
    "sedan":    P_(0.30, 0.92, 0.80, 1.46, 0.88, 0.16, 0.33, 0.90, 0.74),
    "coupe":    P_(0.28, 0.88, 0.76, 1.32, 0.84, 0.08, 0.33, 0.90, 0.70),
    "sports":   P_(0.24, 0.76, 0.66, 1.18, 0.72, 0.00, 0.32, 0.88, 0.68),
    "muscle":   P_(0.26, 0.84, 0.74, 1.30, 0.80, 0.00, 0.34, 0.90, 0.72),
    "limo":     P_(0.30, 0.92, 0.80, 1.44, 0.88, 0.20, 0.33, 0.92, 0.78),
    "police":   P_(0.30, 0.92, 0.80, 1.46, 0.88, 0.14, 0.33, 0.90, 0.74),
    "taxi":     P_(0.30, 0.96, 0.84, 1.52, 0.92, 0.10, 0.33, 0.90, 0.76),
    "compact":  P_(0.30, 0.90, 0.72, 1.44, 0.86, 0.00, 0.31, 0.90, 0.72),
    "microcar": P_(0.26, 0.80, 0.66, 1.30, 0.78, 0.00, 0.26, 0.92, 0.76),
    "pickup":   P_(0.36, 1.00, 0.90, 1.62, 1.00, 0.00, 0.36, 0.92, 0.82),
    "offroad":  P_(0.42, 1.05, 0.95, 1.95, 1.95, 0.00, 0.40, 0.97, 0.95),
    "van":      P_(0.34, 1.05, 0.95, 2.05, 2.05, 0.00, 0.36, 0.97, 0.94),
    "truck":    P_(0.40, 1.20, 1.05, 2.30, 2.30, 0.00, 0.44, 0.97, 0.95, box=2.75),
    "bus":      P_(0.36, 1.30, 1.30, 2.95, 2.95, 0.00, 0.44, 0.98, 0.96),
    "train":    P_(0.36, 1.30, 1.30, 2.90, 2.90, 0.00, 0.40, 0.98, 0.96),
    "trailer":  P_(0.50, 1.30, 1.30, 2.80, 2.80, 0.00, 0.44, 0.98, 0.97),
}
FAMILY = {  # how the profile is built
    "sedan": "threebox", "coupe": "threebox", "sports": "threebox", "muscle": "threebox", "limo": "threebox",
    "police": "threebox", "taxi": "threebox", "compact": "fastback", "microcar": "fastback", "pickup": "pickup",
    "offroad": "open", "van": "box", "truck": "box", "bus": "box", "train": "box", "trailer": "box", "emergency": "box",
    "special": "box", "bike": "bike", "tank": "tank",
}


def resolve_class(rec):
    """Preset key, family and a few per-name tweaks from the catalog class/name."""
    cls = rec["class"]
    name = rec["name"].lower()
    flags = {}
    if cls == "special":
        if "tank" in name:
            return "tank", "tank", flags
        if "roamer" in name or "jeep" in name:
            flags["gun"] = True
            return "offroad", "open", flags
        return "van", "box", flags       # Pacifier: armoured car
    if cls == "emergency":
        if "fire" in name:
            flags["ladder"] = True
            return "truck", "box", flags
        flags["lightbar"] = True
        return "van", "box", flags
    if cls == "offroad":
        if "bug" in name:
            flags["lifted"] = True
            return "compact", "fastback", flags
        return "offroad", "box", flags
    if cls == "police":
        flags["lightbar"] = True
        if rec["width"] >= 38:              # SWAT van
            return "van", "box", flags
    if cls == "taxi":
        flags["taxisign"] = True
    if cls == "wreck":
        return "sedan", "threebox", flags
    if cls not in PRESETS and cls not in ("bike", "tank"):
        cls = infer_class(rec)
    return cls, FAMILY.get(cls, "threebox"), flags


# ----------------------------------------------------------------------------
# Mesh building blocks
# ----------------------------------------------------------------------------
class Part:
    def __init__(self, material):
        self.material = material
        self.v, self.n, self.uv, self.f = [], [], [], []

    def add_tri(self, p, n, uv):
        b = len(self.v)
        self.v.extend(p)
        self.n.extend(n)
        self.uv.extend(uv)
        self.f.append((b, b + 1, b + 2))

    def add_quad(self, p, n, uv):
        self.add_tri([p[0], p[1], p[2]], [n[0], n[1], n[2]], [uv[0], uv[1], uv[2]])
        self.add_tri([p[0], p[2], p[3]], [n[0], n[2], n[3]], [uv[0], uv[2], uv[3]])

    def tri_count(self):
        return len(self.f)


def box(part, centre, size, uv_box=((0, 0), (1, 1))):
    cx, cy, cz = centre
    hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2

    def P(x, y, z):
        return (cx + x, cy + y, cz + z)
    (u0, v0), (u1, v1) = uv_box
    uv = [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]
    faces = [
        ([P(-hx, -hy, hz), P(hx, -hy, hz), P(hx, hy, hz), P(-hx, hy, hz)], (0, 0, 1)),
        ([P(hx, -hy, -hz), P(-hx, -hy, -hz), P(-hx, hy, -hz), P(hx, hy, -hz)], (0, 0, -1)),
        ([P(hx, -hy, hz), P(hx, -hy, -hz), P(hx, hy, -hz), P(hx, hy, hz)], (1, 0, 0)),
        ([P(-hx, -hy, -hz), P(-hx, -hy, hz), P(-hx, hy, hz), P(-hx, hy, -hz)], (-1, 0, 0)),
        ([P(-hx, hy, hz), P(hx, hy, hz), P(hx, hy, -hz), P(-hx, hy, -hz)], (0, 1, 0)),
        ([P(-hx, -hy, -hz), P(hx, -hy, -hz), P(hx, -hy, hz), P(-hx, -hy, hz)], (0, -1, 0)),
    ]
    for pts, n in faces:
        part.add_quad(pts, [n] * 4, uv)


def rounded_box(part, centre, size, radius, uv_box=((0, 0), (1, 1)), segs=3):
    """A box with every edge rounded: a loft of rounded-rectangle rings along
    z whose ends shrink into rounded caps (bumpers, light bars, tanks)."""
    cx, cy, cz = centre
    sx, sy, sz = size
    r = min(radius, sx / 2 * 0.95, sy / 2 * 0.95)
    ring = []
    corners = [(sx / 2 - r, sy / 2 - r, 0), (-sx / 2 + r, sy / 2 - r, 90), (-sx / 2 + r, -sy / 2 + r, 180), (sx / 2 - r, -sy / 2 + r, 270)]
    for ox, oy, a0 in corners:
        for k in range(segs + 1):
            a = math.radians(a0 + 90 * k / segs)
            ring.append((ox + r * math.cos(a), oy + r * math.sin(a), math.cos(a), math.sin(a)))
    n = len(ring)
    ez = min(r, sz / 2 * 0.95)
    zs = []
    for k in range(segs + 1):
        a = math.radians(90 * k / segs)
        zs.append((-sz / 2 + ez - ez * math.cos(a), math.sin(a), -math.cos(a)))
    for k in range(segs + 1):
        a = math.radians(90 * k / segs)
        zs.append((sz / 2 - ez + ez * math.sin(a), math.cos(a), math.sin(a)))
    (u0, v0), (u1, v1) = uv_box
    rings = []
    for z, sc, nz in zs:
        s = 0.05 + 0.95 * sc
        rings.append([(cx + x * s, cy + y * s, cz + z, nx * sc, ny * sc, nz) for x, y, nx, ny in ring])
    for i in range(len(rings) - 1):
        for j in range(n):
            a, b = rings[i][j], rings[i][(j + 1) % n]
            c, d = rings[i + 1][(j + 1) % n], rings[i + 1][j]
            part.add_quad([a[:3], b[:3], c[:3], d[:3]], [a[3:], b[3:], c[3:], d[3:]], [(u0, v1), (u1, v1), (u1, v0), (u0, v0)])
    for ring_, nz in ((rings[0], -1.0), (rings[-1], 1.0)):
        c = (cx, cy, ring_[0][2])
        for j in range(n):
            a, b = ring_[j], ring_[(j + 1) % n]
            tri = [c, a[:3], b[:3]] if nz > 0 else [c, b[:3], a[:3]]
            part.add_tri(tri, [(0, 0, nz)] * 3, [(u0, v0)] * 3)


def cylinder(part, centre, axis, radius, length, segs=20, uv_side=((0, 0), (1, 1)), cap_part=None, cap_uv=((0, 0), (1, 1)), cap_inset=0.0, caps=True):
    cx, cy, cz = centre
    ax = np.array(axis, np.float32)
    ax /= np.linalg.norm(ax)
    up = np.array([0, 1, 0], np.float32) if abs(ax[1]) < 0.9 else np.array([0, 0, 1], np.float32)
    side = np.cross(ax, up)
    side /= np.linalg.norm(side)
    up = np.cross(side, ax)
    ring = [math.cos(2 * math.pi * k / segs) * side + math.sin(2 * math.pi * k / segs) * up for k in range(segs)]
    (u0, v0), (u1, v1) = uv_side
    c0 = np.array(centre, np.float32) - ax * length / 2
    c1 = np.array(centre, np.float32) + ax * length / 2
    for k in range(segs):
        d0, d1 = ring[k], ring[(k + 1) % segs]
        pts = [tuple(c0 + d0 * radius), tuple(c0 + d1 * radius), tuple(c1 + d1 * radius), tuple(c1 + d0 * radius)]
        uu0, uu1 = u0 + (u1 - u0) * k / segs, u0 + (u1 - u0) * (k + 1) / segs
        part.add_quad(pts, [tuple(d0), tuple(d1), tuple(d1), tuple(d0)], [(uu0, v1), (uu1, v1), (uu1, v0), (uu0, v0)])
    if not caps:
        return
    cp = cap_part or part
    (cu0, cv0), (cu1, cv1) = cap_uv
    for c, sign in ((c0, -1.0), (c1, 1.0)):
        cc = c + ax * cap_inset * sign
        n = tuple(ax * sign)
        for k in range(segs):
            d0, d1 = ring[k], ring[(k + 1) % segs]
            a, b = tuple(cc + d0 * radius), tuple(cc + d1 * radius)
            uva = (cu0 + (cu1 - cu0) * (0.5 + 0.5 * float(d0 @ side)), cv0 + (cv1 - cv0) * (0.5 - 0.5 * float(d0 @ up)))
            uvb = (cu0 + (cu1 - cu0) * (0.5 + 0.5 * float(d1 @ side)), cv0 + (cv1 - cv0) * (0.5 - 0.5 * float(d1 @ up)))
            uvc = ((cu0 + cu1) / 2, (cv0 + cv1) / 2)
            if sign > 0:
                cp.add_tri([tuple(cc), a, b], [n] * 3, [uvc, uva, uvb])
            else:
                cp.add_tri([tuple(cc), b, a], [n] * 3, [uvc, uvb, uva])


# ----------------------------------------------------------------------------
# Body loft
# ----------------------------------------------------------------------------
def half_profile(hw, y_roof, y_belt, P, fin, greenhouse):
    """Nine (x, y) points of the left half of a section, bottom centre to top
    centre: sill chamfer, slab side, rounded shoulder, then either the
    greenhouse (inset, tumblehome, rounded roof edge) or a flat deck. Each
    point carries a kind (0 under, 1 side, 2 top) that decides which texture
    the faces between two points get: the greenhouse sides are glass from the
    side texture, every upward deck and the roof is the projected sprite."""
    g = P["g"]
    ch = min(0.035, hw * 0.3)
    sh = min(0.045, hw * 0.35) if P["gi"] < 0.96 else min(0.018, hw * 0.15)   # slab-sided vans: no shoulder ledge
    wb = hw
    pts = [(0.0, g, 0), (-(wb - ch), g, 0), (-wb, g + ch, 1), (-wb, y_belt - sh * 0.8, 1)]
    if greenhouse and y_roof > y_belt + 0.01:
        wgb, wgt = wb * P["gi"], wb * P["th"]
        rc = min(0.035, (y_roof - y_belt) * 0.4)
        pts += [(-(wb - sh * 0.5), y_belt + fin, 2), (-wgb, y_belt + fin + 0.004, 1), (-wgt, y_roof - rc, 1), (-(wgt - rc), y_roof, 2), (0.0, y_roof, 2)]
    else:
        pts += [(-(wb - sh * 0.5), y_belt + fin, 2), (-(wb - sh * 0.9), y_belt + fin * 0.9, 2), (-(wb - sh) * 0.66, y_belt + 0.004, 2), (-(wb - sh) * 0.33, y_belt + 0.006, 2), (0.0, y_belt + 0.006, 2)]
    return pts


def build_body(rec, rgba, P, cls, family, flags, parts, deform=None):
    half, (y0, y1, x0, x1, cx) = footprint(rgba, rec["width"])
    h_img, w_img = rgba.shape[:2]
    L = (y1 - y0) / BLOCK_PX
    W = 2 * float(half.max())
    # Origin: the sprite canvas centre. Rows grow toward the nose.
    z_tail, z_nose = (y0 - h_img / 2) / BLOCK_PX, (y1 - h_img / 2) / BLOCK_PX
    xo = (cx - w_img / 2) / BLOCK_PX
    z_fw = rec["front_window"] / BLOCK_PX
    z_rw = rec["rear_window"] / BLOCK_PX
    if z_fw <= z_rw + 0.05:
        z_rw, z_fw = z_tail + 0.08 * L, z_nose - 0.12 * L
    z_fw = min(z_fw, z_nose - 0.06)
    z_rw = max(z_rw, z_tail + 0.04)
    ws = float(np.clip(W / (2.2 * M), 0.8, 1.12))      # small cars sit lower
    belt_h, roof_h, hood_h, trunk_h, box_h = (P[k] * ws for k in ("hb", "roof", "hood", "trunk", "box"))
    cab_over = family == "box" and (z_nose - z_fw) < 0.22 and cls not in ("trailer", "offroad")
    has_cab = family == "box" and cls not in ("trailer",) and not (cls == "train" and not rec.get("doors"))
    cargo_box = family == "box" and cls == "truck" and (z_rw - z_tail) > 0.35 * L
    if cls in ("bus", "train", "trailer"):
        has_cab = cls == "bus"

    def roof_at(z):
        if family == "box":
            if cls == "trailer" or (cls == "train" and not has_cab):
                a = smoothstep(0.0, 1.0, (z_nose - z) / 0.10) * smoothstep(0.0, 1.0, (z - z_tail) / 0.10)
                return belt_h + (roof_h - belt_h) * (0.75 + 0.25 * a)
            if cls == "bus":
                a = smoothstep(0.0, 1.0, (z_nose - z) / 0.14)
                b = smoothstep(0.0, 1.0, (z - z_tail) / 0.10)
                return belt_h + (roof_h - belt_h) * (0.72 + 0.28 * min(a, b))
            start = z_nose - 0.02 if cab_over else z_fw + 0.02
            a = smoothstep(0.0, 1.0, (start - z) / 0.18)
            r = hood_h + (roof_h - hood_h) * a
            if cargo_box:
                step = smoothstep(0.0, 1.0, (z_rw - 0.02 - z) / 0.04)
                r = max(r, hood_h + (box_h - hood_h) * step) if z < z_rw else r
            return r
        if family == "open":
            return belt_h
        if family == "fastback":
            a = smoothstep(0.0, 1.0, (z_fw - z) / 0.16)
            b = smoothstep(0.0, 1.0, (z - z_tail) / max(z_rw + 0.10 - z_tail, 0.1))
            return belt_h + (roof_h - belt_h) * min(a, b)
        cabin = max(z_fw - z_rw, 0.08)
        ws_len = min(0.16 if cls != "sports" else 0.20, cabin * 0.42)
        rw_len = min(0.14 if family != "pickup" else 0.07, cabin * 0.3)
        a = smoothstep(0.0, 1.0, (z_fw - z) / ws_len)
        b = smoothstep(0.0, 1.0, (z - z_rw) / rw_len)
        return belt_h + (roof_h - belt_h) * min(a, b)

    def belt_at(z):
        if family == "box":
            return belt_h
        front = smoothstep(z_fw, z_nose, z)
        rear = smoothstep(z_rw, z_tail, z)
        b = belt_h + (hood_h - belt_h) * front * 0.9 + (trunk_h - belt_h) * rear * 0.7
        if family == "fastback":
            b -= (belt_h - hood_h) * 0.5 * smoothstep(z_fw, z_nose, z) ** 2   # rounder nose
        return b

    def fin_at(z):
        if P["fin"] <= 0 or family != "threebox":
            return 0.0
        t = smoothstep(z_rw - 0.05, z_tail, z)
        return P["fin"] * t * t

    NZ = 46
    sections = []
    zs = np.linspace(z_tail, z_nose, NZ)
    for z in zs:
        i = (z - z_tail) / L * (len(half) - 1)
        hw = max(float(np.interp(i, np.arange(len(half)), half)), 0.02)
        r, b = roof_at(z), belt_at(z)
        left = half_profile(hw, r, b, P, fin_at(z), r > b + 0.012)
        right = [(-x, y, k) for x, y, k in reversed(left[1:-1])]
        sections.append([(x + xo, y, float(z), k) for x, y, k in left + right])
    NP = len(sections[0])
    verts = np.array([p[:3] for s in sections for p in s], np.float32)
    kinds = np.array([p[3] for s in sections for p in s], np.int32)
    if deform is not None:
        verts = deform(verts, kinds, dict(z_tail=z_tail, z_nose=z_nose, z_fw=z_fw, z_rw=z_rw, L=L, W=W, xo=xo, g=P["g"], roof=roof_h, belt=belt_h))

    def vid(i, j):
        return i * NP + (j % NP)
    faces = []
    for i in range(NZ - 1):
        for j in range(NP):
            a, b, c, d = vid(i, j), vid(i, j + 1), vid(i + 1, j + 1), vid(i + 1, j)
            faces.append((a, b, c))
            faces.append((a, c, d))
    faces = np.array(faces, np.int32)
    fn = np.cross(verts[faces[:, 1]] - verts[faces[:, 0]], verts[faces[:, 2]] - verts[faces[:, 0]])
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-9)
    vn = np.zeros_like(verts)
    for k in range(3):
        np.add.at(vn, faces[:, k], fn)
    vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-9)
    out_dir = verts - np.array([xo, float(verts[:, 1].mean()), 0], np.float32)
    out_dir[:, 2] = 0
    if (vn[:, :2] * out_dir[:, :2]).sum() < 0:
        faces = faces[:, ::-1].copy()
        fn, vn = -fn, -vn
    Hmax = max(roof_h, box_h if cargo_box else 0) + 0.02
    m = dict(L=L, W=W, z_tail=z_tail, z_nose=z_nose, z_fw=z_fw, z_rw=z_rw, belt=belt_h, roof=roof_h, hood=hood_h, Hmax=Hmax, xo=xo,
             family=family, cab_over=cab_over, has_cab=has_cab, cargo_box=cargo_box, box=box_h, rows=(y0, y1, x0, x1, cx), img=(w_img, h_img))
    top, side, front, rear, under = parts["top"], parts["side"], parts["front"], parts["rear"], parts["under"]

    def uv_top(p):
        ix, iy = 1.5, 1.0   # pixels of outline kept off the body
        return ((x0 + ix + (p[0] - xo + W / 2) / W * (x1 - x0 - 2 * ix)) / w_img, (y0 + iy + (p[2] - z_tail) / L * (y1 - y0 - 2 * iy)) / h_img)
    for (a, b, c), n in zip(faces, fn):
        pa, pb, pc = verts[a], verts[b], verts[c]
        ks = (int(kinds[a]), int(kinds[b]), int(kinds[c]))
        kind = 0 if 0 in ks else (2 if all(k == 2 for k in ks) or (2 in ks and n[1] > 0.5) else 1)
        if kind == 2 and n[1] > 0.05:
            part, uv = top, [uv_top(p) for p in (pa, pb, pc)]
        elif kind == 0 or n[1] < -0.6:
            part, uv = under, [((p[0] - xo + W / 2) / W, (p[2] - z_tail) / L) for p in (pa, pb, pc)]
        elif abs(n[2]) > 0.72 and kind < 2:
            part = front if n[2] > 0 else rear
            uv = [((p[0] - xo + W / 2) / W, 1 - p[1] / Hmax) for p in (pa, pb, pc)]
        else:
            part, uv = side, [((p[2] - z_tail) / L, 1 - p[1] / Hmax) for p in (pa, pb, pc)]
        part.add_tri([tuple(pa), tuple(pb), tuple(pc)], [tuple(vn[a]), tuple(vn[b]), tuple(vn[c])], uv)
    for ring, nz, part in ((verts[:NP], -1.0, rear), (verts[-NP:], 1.0, front)):
        centre = ring.mean(axis=0)
        for j in range(NP):
            p1, p2 = ring[j], ring[(j + 1) % NP]
            tri = [tuple(centre), tuple(p1), tuple(p2)] if nz > 0 else [tuple(centre), tuple(p2), tuple(p1)]
            part.add_tri(tri, [(0, 0, nz)] * 3, [((p[0] - xo + W / 2) / W, 1 - p[1] / Hmax) for p in tri])
    g = P["g"]
    under.add_quad([(xo - W * 0.4, g + 0.002, z_tail + 0.02), (xo - W * 0.4, g + 0.002, z_nose - 0.02), (xo + W * 0.4, g + 0.002, z_nose - 0.02), (xo + W * 0.4, g + 0.002, z_tail + 0.02)],
                   [(0, -1, 0)] * 4, [(0, 0), (0, 1), (1, 1), (1, 0)])
    return m


def add_wheels(rec, m, P, parts, cls, whitewall, keep=None, askew=False):
    r = P["r"]
    heavy = cls in ("truck", "bus", "train", "trailer")
    tw = (0.26 if heavy else 0.19) * M
    xw = m["W"] / 2 - tw * 0.55
    zf, zr = rec["front_wheel"] / BLOCK_PX, rec["rear_wheel"] / BLOCK_PX
    if zf <= zr + 0.1:
        zf, zr = m["z_nose"] - 0.22 * m["L"], m["z_tail"] + 0.22 * m["L"]
    zf = min(zf, m["z_nose"] - r - 0.005)
    zr = max(zr, m["z_tail"] + r + 0.005)
    cap = parts["hubcap_ww"] if whitewall else parts["hubcap"]
    if askew:
        cap = parts["tyre"]      # a burnt wheel: no shiny hubcap left
    wheels = []
    pairs = [("fl", -xw, zf), ("fr", xw, zf), ("rl", -xw, zr), ("rr", xw, zr)]
    if cls in ("trailer", "train") and m["L"] > 1.3:
        pairs += [("rl2", -xw, zr + 2.2 * r), ("rr2", xw, zr + 2.2 * r)]
    rng = np.random.default_rng(rec["model"])
    for name, x, z in pairs:
        if keep is not None and name not in keep:
            continue
        axis = (1, 0, 0)
        if askew:
            # A wheel knocked off its hub: tilted, pushed in, sitting a little low.
            axis = (1.0, float(rng.uniform(-0.35, 0.35)), float(rng.uniform(-0.25, 0.25)))
            x *= float(rng.uniform(0.82, 0.98))
            z += float(rng.uniform(-0.03, 0.03))
        cylinder(parts["tyre"], (m["xo"] + x, r, z), axis, r, tw, segs=18, cap_part=cap, cap_inset=-0.004)
        wheels.append(dict(name="wheel_" + name, x=round(m["xo"] + x, 4), y=round(r, 4), z=round(z, 4), radius=round(r, 4)))
    return wheels


def add_trim(rec, m, P, parts, cls, flags, rgba):
    W, L, xo, g = m["W"], m["L"], m["xo"], P["g"]
    chrome = parts["chrome"]
    boxy = m["family"] == "box"
    openb = m["family"] == "open"
    bh = (0.14 if boxy else 0.11) * M
    by = g + 0.32 * M
    bt = 0.08 * M
    for z, sgn in ((m["z_nose"] + bt / 2 - 0.004, 1), (m["z_tail"] - bt / 2 + 0.004, -1)):
        if cls == "trailer" and sgn > 0:
            continue
        rounded_box(chrome, (xo, by, z), (W * 0.92, bh, bt), bh * 0.45, segs=2)
        if not boxy:
            for x in (-W * 0.27, W * 0.27):
                rounded_box(chrome, (xo + x, by + bh * 0.55, z + sgn * 0.006), (0.09 * M, bh * 1.2, bt * 1.1), bh * 0.4, segs=2)
    # Headlamps in chrome bezels at the nose corners.
    if cls != "trailer":
        hl_y = m["hood"] * 0.74 if not boxy else m["belt"] * 0.8
        hl_r = 0.15 * M
        for x in (-W * 0.36, W * 0.36):
            cylinder(parts["lamp"], (xo + x, hl_y, m["z_nose"] - 0.004), (0, 0, 1), hl_r, 0.02, segs=14, cap_part=parts["lamp"], cap_uv=((0, 0), (0.5, 1)))
            cylinder(chrome, (xo + x, hl_y, m["z_nose"] - 0.012), (0, 0, 1), hl_r * 1.18, 0.012, segs=14, caps=False)
        gh = (0.30 if boxy else 0.22) * M
        box(parts["grille"], (xo, hl_y - 0.02 * M, m["z_nose"] + 0.003), (W * 0.46, gh, 0.01))
    # Tail lamps: fin-tip lenses on finned cars, round elsewhere.
    tl_y = m["belt"] * 0.86 + (P["fin"] * 0.5 if P["fin"] > 0 and m["family"] == "threebox" else 0)
    for x in (-W * 0.40, W * 0.40):
        if P["fin"] > 0 and m["family"] == "threebox":
            box(parts["tail"], (xo + x, tl_y, m["z_tail"] + 0.004), (0.09 * M, 0.26 * M, 0.012))
        else:
            cylinder(parts["tail"], (xo + x, min(tl_y, m["belt"] * 0.9), m["z_tail"] + 0.004), (0, 0, 1), 0.09 * M, 0.016, segs=12, cap_part=parts["tail"])
    # The belt-line spear and door seams live in the side texture: anything
    # that stands proud of the shoulder shows up as a line in the top view.
    roof_y = m["roof"]
    zc = (m["z_fw"] + m["z_rw"]) / 2 + 0.04
    if flags.get("lightbar") or (cls == "police"):
        rounded_box(chrome, (xo, roof_y + 0.012, zc), (W * 0.62, 0.02, 0.055), 0.008, segs=2)
        box(parts["blue"], (xo - W * 0.16, roof_y + 0.036, zc), (W * 0.24, 0.03, 0.05))
        box(parts["red"], (xo + W * 0.16, roof_y + 0.036, zc), (W * 0.24, 0.03, 0.05))
    elif flags.get("taxisign"):
        box(parts["taxi"], (xo, roof_y + 0.03, zc + 0.01), (W * 0.42, 0.045, 0.08))
    else:
        px = roof_pixels(rgba, m)
        if px is not None:
            red = ((px[:, 0] > 150) & (px[:, 1] < 90) & (px[:, 2] < 90)).mean()
            blue = ((px[:, 2] > 150) & (px[:, 0] < 90) & (px[:, 1] < 120)).mean()
            amber = ((px[:, 0] > 200) & (px[:, 1] > 120) & (px[:, 1] < 200) & (px[:, 2] < 80)).mean()
            if red > 0.04 and blue > 0.04:
                box(parts["blue"], (xo - W * 0.16, roof_y + 0.03, zc), (W * 0.24, 0.03, 0.05))
                box(parts["red"], (xo + W * 0.16, roof_y + 0.03, zc), (W * 0.24, 0.03, 0.05))
            elif amber > 0.05:
                box(parts["taxi"], (xo, roof_y + 0.03, zc), (W * 0.3, 0.03, 0.05))
    if flags.get("ladder"):
        # Two rails and rungs over the body, from behind the cab to the tail.
        z0, z1 = m["z_rw"] - 0.05, m["z_tail"] + 0.06
        y = m["box"] + 0.03 if m["cargo_box"] else roof_y + 0.03
        for x in (-W * 0.18, W * 0.18):
            box(chrome, (xo + x, y, (z0 + z1) / 2), (0.008, 0.012, abs(z0 - z1)))
        n = max(3, int(abs(z0 - z1) / 0.07))
        for k in range(n):
            z = z1 + (z0 - z1) * (k + 0.5) / n
            box(chrome, (xo, y, z), (W * 0.36, 0.008, 0.008))
    if openb:
        # Windscreen frame, folded top, spare wheel, and the gun for the armed one.
        box(parts["glass"], (xo, m["belt"] + 0.17 * M, m["z_fw"]), (W * 0.86, 0.34 * M, 0.012))
        for x in (-W * 0.43, W * 0.43):
            box(chrome, (xo + x, m["belt"] + 0.17 * M, m["z_fw"]), (0.012, 0.36 * M, 0.02))
        rounded_box(parts["seat"], (xo, m["belt"] + 0.04, m["z_rw"] - 0.02), (W * 0.8, 0.07, 0.08), 0.02, segs=2)
        cylinder(parts["tyre"], (xo, m["belt"] * 0.75, m["z_tail"] - 0.02), (0, 0, 1), P["r"] * 0.9, 0.17 * M, segs=16, cap_part=parts["hubcap"])
        if flags.get("gun"):
            zg = (m["z_rw"] + m["z_tail"]) / 2
            cylinder(chrome, (xo, m["belt"] + 0.12, zg), (0, 1, 0), 0.012, 0.24, segs=8)
            cylinder(parts["under"], (xo, m["belt"] + 0.25, zg + 0.08), (0, 0, 1), 0.016, 0.34, segs=10)
    for x in ((-W * 0.3, W * 0.3) if not boxy else (-W * 0.3,)):
        cylinder(chrome, (xo + x, g + 0.01, m["z_tail"] - 0.01), (0, 0, 1), 0.012, 0.03, segs=8)


def roof_pixels(rgba, m):
    y0, y1, x0, x1, cx = m["rows"]
    r0 = int(y0 + (m["z_rw"] - m["z_tail"]) / m["L"] * (y1 - y0))
    r1 = int(y0 + (m["z_fw"] - m["z_tail"]) / m["L"] * (y1 - y0))
    if r1 <= r0 + 1:
        return None
    px = rgba[r0:r1, int(cx - (x1 - x0) * 0.3): int(cx + (x1 - x0) * 0.3)]
    op = px[px[..., 3] > 0][..., :3].astype(np.float32)
    return op if len(op) else None


# ----------------------------------------------------------------------------
# Bikes and tanks
# ----------------------------------------------------------------------------
def build_bike(rec, rgba, parts):
    half, (y0, y1, x0, x1, cx) = footprint(rgba, rec["width"])
    h_img, w_img = rgba.shape[:2]
    L = (y1 - y0) / BLOCK_PX
    W = max(2 * float(half.max()), 0.12)
    z_tail, z_nose = (y0 - h_img / 2) / BLOCK_PX, (y1 - h_img / 2) / BLOCK_PX
    xo = (cx - w_img / 2) / BLOCK_PX
    r = 0.30 * M
    rounded_box(parts["side"], (xo, r + 0.08 * M, 0.02), (W * 0.45, 0.22 * M, L * 0.55), 0.02, segs=2)
    rounded_box(parts["top"], (xo, r + 0.26 * M, z_nose - 0.36 * L), (W * 0.7, 0.18 * M, L * 0.22), 0.025, segs=2)
    rounded_box(parts["seat"], (xo, r + 0.25 * M, z_tail + 0.30 * L), (W * 0.75, 0.10 * M, L * 0.28), 0.02, segs=2)
    cylinder(parts["chrome"], (xo, r + 0.52 * M, z_nose - 0.30 * L), (1, 0, 0), 0.012, W * 1.3, segs=8)
    for z in (z_nose - 0.28 * L, z_nose - 0.34 * L):
        cylinder(parts["chrome"], (xo, r + 0.22 * M, z), (0, 1, 0), 0.01, 0.5 * M, segs=8)
    cylinder(parts["lamp"], (xo, r + 0.42 * M, z_nose - 0.26 * L), (0, 0, 1), 0.07 * M, 0.03, segs=10, cap_part=parts["lamp"], cap_uv=((0, 0), (0.5, 1)))
    cylinder(parts["chrome"], (xo + W * 0.2, r * 0.6, z_tail + 0.25 * L), (0, 0, 1), 0.015, L * 0.5, segs=8)
    wheels = []
    for name, z in (("wheel_f", z_nose - r - 0.01), ("wheel_r", z_tail + r + 0.01)):
        cylinder(parts["tyre"], (xo, r, z), (1, 0, 0), r, 0.09 * M, segs=18, cap_part=parts["hubcap"], cap_inset=-0.003)
        wheels.append(dict(name=name, x=round(xo, 4), y=round(r, 4), z=round(z, 4), radius=round(r, 4)))
    m = dict(L=L, W=W, z_tail=z_tail, z_nose=z_nose, Hmax=r + 0.6 * M, roof=r + 0.52 * M, belt=r + 0.3 * M, hood=r + 0.3 * M, xo=xo, z_fw=0, z_rw=0,
             family="bike", cab_over=False, has_cab=False, cargo_box=False, box=0, rows=(y0, y1, x0, x1, cx), img=(w_img, h_img))
    return m, wheels


def build_tank(rec, rgba, parts):
    half, (y0, y1, x0, x1, cx) = footprint(rgba, rec["width"])
    h_img, w_img = rgba.shape[:2]
    L = (y1 - y0) / BLOCK_PX
    W = 2 * float(half.max())
    z_tail, z_nose = (y0 - h_img / 2) / BLOCK_PX, (y1 - h_img / 2) / BLOCK_PX
    xo = (cx - w_img / 2) / BLOCK_PX
    g = 0.25 * M
    hy = 0.9 * M
    hx = W / 2 * 0.78
    top, side = parts["top"], parts["side"]

    def uvt(x, z):
        return ((x0 + (x - xo + W / 2) / W * (x1 - x0)) / w_img, (y0 + (z - z_tail) / L * (y1 - y0)) / h_img)
    pts = [(-hx, g + 0.1 * M, z_tail + 0.05), (-hx, g + hy, z_tail + 0.12), (-hx, g + hy, z_nose - 0.12), (-hx, g + 0.1 * M, z_nose - 0.05)]
    for sgn in (1, -1):
        q = [(xo + sgn * x, y, z) for x, y, z in pts]
        if sgn > 0:
            q = q[::-1]
        side.add_quad(q, [(sgn, 0, 0)] * 4, [(0, 1), (0, 0.4), (1, 0.4), (1, 1)])
    deck = [(xo - hx, g + hy, z_tail + 0.12), (xo - hx, g + hy, z_nose - 0.12), (xo + hx, g + hy, z_nose - 0.12), (xo + hx, g + hy, z_tail + 0.12)]
    top.add_quad(deck, [(0, 1, 0)] * 4, [uvt(p[0], p[2]) for p in deck])
    glacis = [(xo - hx, g + hy, z_nose - 0.12), (xo - hx, g + 0.1 * M, z_nose - 0.05), (xo + hx, g + 0.1 * M, z_nose - 0.05), (xo + hx, g + hy, z_nose - 0.12)]
    top.add_quad(glacis, [(0, 0.6, 0.8)] * 4, [uvt(p[0], p[2]) for p in glacis])
    rear = [(xo - hx, g + hy, z_tail + 0.12), (xo + hx, g + hy, z_tail + 0.12), (xo + hx, g + 0.1 * M, z_tail + 0.05), (xo - hx, g + 0.1 * M, z_tail + 0.05)]
    top.add_quad(rear, [(0, 0.6, -0.8)] * 4, [uvt(p[0], p[2]) for p in rear])
    for sgn in (-1, 1):
        rounded_box(parts["tyre"], (xo + sgn * (W / 2 - W * 0.11), g + 0.35 * M, (z_tail + z_nose) / 2), (W * 0.22, 0.7 * M, L * 0.96), 0.3 * M, segs=4)
    cylinder(side, (xo, g + hy + 0.3 * M, (z_tail + z_nose) / 2 - 0.05 * L), (0, 1, 0), W * 0.32, 0.6 * M, segs=18, cap_uv=((0.2, 0.2), (0.8, 0.8)))
    cylinder(parts["chrome"], (xo, g + hy + 0.42 * M, (z_tail + z_nose) / 2 + 0.25 * L + 0.05), (0, 0, 1), 0.07 * M, L * 0.7, segs=10)
    m = dict(L=L, W=W, z_tail=z_tail, z_nose=z_nose, Hmax=g + hy + 0.7 * M, roof=g + hy + 0.6 * M, belt=g + hy, hood=g + hy, xo=xo, z_fw=0, z_rw=0,
             family="tank", cab_over=False, has_cab=False, cargo_box=False, box=0, rows=(y0, y1, x0, x1, cx), img=(w_img, h_img))
    return m, []


# ----------------------------------------------------------------------------
# Textures
# ----------------------------------------------------------------------------
def tone(c, k):
    return tuple(int(np.clip(float(v) * k, 0, 255)) for v in c)


def charred_texture(tones, size=(1024, 384), seed=3):
    """Burnt-out bodywork: soot-black with scorched brown and rust patches, bare
    metal scratches and no paint left. `tones` are the wreck sprite's own
    colours, so the sides match the top-down art."""
    w, h = size
    rng = np.random.default_rng(seed)
    base = np.array(tones["dark"], np.float32)
    rust = np.array(tones["rust"], np.float32)
    bare = np.array([120, 118, 112], np.float32)
    # Low-frequency blotches from a few octaves of smoothed noise.
    def noise(scale):
        n = rng.random((h // scale + 2, w // scale + 2)).astype(np.float32)
        return np.array(Image.fromarray((n * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR)).astype(np.float32) / 255.0
    n1, n2, n3 = noise(64), noise(16), noise(4)
    soot = np.clip(0.55 * n1 + 0.3 * n2 + 0.15 * n3, 0, 1)
    img = base[None, None, :] * (0.6 + 0.8 * soot[..., None])
    rust_mask = np.clip((n1 - 0.55) * 4.0, 0, 1) * (0.5 + 0.5 * n2)
    img = img * (1 - rust_mask[..., None]) + rust[None, None, :] * rust_mask[..., None]
    bare_mask = np.clip((n3 - 0.82) * 6.0, 0, 1) * np.clip((n2 - 0.4) * 2, 0, 1)
    img = img * (1 - bare_mask[..., None]) + bare[None, None, :] * bare_mask[..., None]
    # Heat discolouration bands near the top.
    rows = np.linspace(1.0, 0.0, h)[:, None, None]
    img = img * (0.75 + 0.5 * rows)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def wreck_tones(rgba):
    """The dark and the rust tone of a wreck sprite."""
    a = rgba[..., 3] > 0
    px = rgba[a][:, :3].astype(np.float32)
    if len(px) == 0:
        return dict(dark=(32, 28, 26), rust=(96, 54, 30))
    lum = px.mean(axis=1)
    dark = px[lum <= np.percentile(lum, 40)].mean(axis=0)
    warm = px[(px[:, 0] > px[:, 2] + 12)]
    rust = warm.mean(axis=0) if len(warm) > 10 else dark * 1.6 + np.array([40, 10, 0])
    return dict(dark=tuple(int(v) for v in np.clip(dark, 14, 90)), rust=tuple(int(v) for v in np.clip(rust, 40, 160)))


def sstep(a, b, x):
    """smoothstep for arrays (b may be less than a: the ramp then goes down)."""
    t = np.clip((x - a) / ((b - a) if abs(b - a) > 1e-6 else 1e-6), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def wreck_deform(seed):
    """Crushes a lofted body: roof caved in, panels dented, a slight twist,
    the whole car sitting lower on its springs. Returns the deform hook for
    build_body."""
    rng = np.random.default_rng(seed)
    def deform(verts, kinds, m):
        v = verts.copy()
        x, y, z = v[:, 0] - m["xo"], v[:, 1], v[:, 2]
        g = m["g"]
        hw = max(m["W"] / 2, 0.05)
        # Roof: caved in over the cabin, more at the centre than the sides.
        cabin = sstep(m["z_rw"] - 0.05, m["z_rw"] + 0.05, z) * sstep(m["z_fw"] + 0.05, m["z_fw"] - 0.05, z)
        centre = np.clip(1 - np.abs(x) / hw, 0, 1)
        cave = (0.38 + 0.22 * rng.random()) * cabin * (0.3 + 0.7 * centre ** 1.5)
        above = np.clip((y - g - 0.02) / max(m["roof"] - g, 0.05), 0, 1)
        y = y - cave * (y - g) * above
        # Everything sags: springs gone.
        y = g + (y - g) * 0.86
        # Dents: low-frequency ripple along the length and height on the side panels.
        side = (kinds == 1).astype(np.float32)
        ripple = (np.sin(z * 37.0 + rng.random() * 6) * np.sin(y * 29.0 + rng.random() * 6) * 0.6 + np.sin(z * 91.0) * 0.4)
        dent = 0.04 * ripple * side * np.sign(x + 1e-6)
        x = x - dent * (np.abs(x) > hw * 0.5)
        # A crumpled end: one end pushed in and down.
        front_hit = rng.random() < 0.5
        t = sstep(m["z_nose"] - 0.25 * m["L"], m["z_nose"], z) if front_hit else sstep(m["z_tail"] + 0.25 * m["L"], m["z_tail"], z)
        z = z - (0.06 * m["L"]) * t * (1 if front_hit else -1)
        y = y - 0.05 * t * (y - g)
        x = x * (1 - 0.12 * t)
        # Twist about the length.
        ang = 0.06 * (z - (m["z_tail"] + m["z_nose"]) / 2) / max(m["L"], 0.1) * 2
        ca, sa = np.cos(ang), np.sin(ang)
        x, y = x * ca - (y - g) * sa, g + x * sa + (y - g) * ca
        y = np.maximum(y, g + 0.004 * (kinds > 0))
        v[:, 0], v[:, 1], v[:, 2] = x + m["xo"], y, z
        return v
    return deform


def make_top_texture(hx4, paint):
    arr = np.array(hx4.convert("RGBA")).astype(np.float32)
    a = arr[..., 3:4] / 255.0
    rgb = arr[..., :3] * a + np.array(paint, np.float32) * (1 - a)
    return Image.fromarray(rgb.astype(np.uint8), "RGB")


def make_side_texture(rec, m, P, cls, paint, glass, wheels):
    Wt, Ht = 1024, 384
    im = Image.new("RGB", (Wt, Ht))
    d = ImageDraw.Draw(im)
    Hmax = m["Hmax"]

    def Y(y):
        return int((1 - y / Hmax) * Ht)

    def Z(z):
        return int((z - m["z_tail"]) / m["L"] * Wt)
    for row in range(Ht):
        y = (1 - row / Ht) * Hmax
        k = 0.78 + 0.34 * min(1.0, max(0.0, (y - P["g"]) / max(m["belt"] - P["g"], 0.01)))
        d.line([(0, row), (Wt, row)], fill=tone(paint, k))
    d.rectangle([0, Y(P["g"] + 0.02), Wt, Ht], fill=tone(paint, 0.55))
    d.rectangle([Z(m["z_tail"] + 0.06), Y(P["g"] + 0.03), Z(m["z_nose"] - 0.06), Y(P["g"] + 0.018)], fill=(205, 208, 212))
    gl = tuple(int(v) for v in glass)
    fam = m["family"]
    if fam == "box":
        if cls == "bus":
            n = max(3, int(m["L"] / 0.2))
            for k in range(n):
                a = m["z_tail"] + 0.06 + (m["L"] - 0.12) * k / n
                b = a + (m["L"] - 0.12) / n - 0.025
                d.rectangle([Z(a), Y(m["roof"] - 0.04), Z(b), Y(m["belt"] + 0.02)], fill=gl, outline=(215, 218, 222), width=2)
                d.line([(Z(a) + 3, Y(m["roof"] - 0.04) + 3), (Z(b) - 3, Y(m["belt"] + 0.02) - 3)], fill=tone(glass, 1.6), width=2)
        elif cls == "train":
            n = max(4, int(m["L"] / 0.16))
            for k in range(n):
                a = m["z_tail"] + 0.08 + (m["L"] - 0.16) * k / n
                b = a + (m["L"] - 0.16) / n - 0.03
                d.rectangle([Z(a), Y(m["roof"] - 0.06), Z(b), Y(m["belt"] + 0.06)], fill=gl, outline=(200, 200, 200), width=2)
        elif cls == "trailer":
            # X-braced ribbed side.
            for z in np.arange(m["z_tail"] + 0.05, m["z_nose"], 0.08):
                d.line([(Z(z), Y(m["roof"] - 0.02)), (Z(z), Y(m["belt"]))], fill=tone(paint, 0.7), width=2)
        elif m["has_cab"]:
            cab1 = m["z_nose"] - 0.03 if m["cab_over"] else m["z_fw"] - 0.015
            cab0 = cab1 - (0.22 if m["cab_over"] else 0.24)
            d.rectangle([Z(cab0), Y(m["roof"] - 0.03), Z(cab1), Y(m["belt"] + 0.03)], fill=gl, outline=(215, 218, 222), width=3)
            d.line([(Z(cab0) + 3, Y(m["roof"] - 0.03) + 3), (Z(cab1) - 3, Y(m["belt"] + 0.03) - 3)], fill=tone(glass, 1.6), width=3)
            d.line([(Z(cab0 - 0.02), Y(m["roof"])), (Z(cab0 - 0.02), Y(P["g"]))], fill=tone(paint, 0.45), width=3)
            if m["cargo_box"]:
                for z in np.arange(m["z_tail"] + 0.05, m["z_rw"] - 0.05, 0.09):
                    d.line([(Z(z), Y(m["box"] - 0.02)), (Z(z), Y(m["belt"]))], fill=tone(paint, 0.8), width=2)
    elif fam in ("threebox", "fastback", "pickup"):
        z0, z1 = m["z_rw"] + 0.03, m["z_fw"] - 0.015
        if fam == "fastback":
            z0 = m["z_rw"] + 0.06
        top, bot = Y(m["roof"] - 0.012), Y(m["belt"] + 0.01)
        d.rectangle([Z(z0), top, Z(z1), bot], fill=gl)
        doors = [dd for dd in rec.get("doors", []) if abs(dd[0]) > 2 and abs(dd[0]) <= rec["width"] / 2 + 3]
        if doors and fam != "pickup":
            zb = doors[0][1] / BLOCK_PX + 0.01
            if z0 + 0.03 < zb < z1 - 0.03:
                d.rectangle([Z(zb) - 4, top, Z(zb) + 4, bot], fill=tone(paint, 0.85))
        d.line([(Z(z0) + 6, top + 6), (Z(z1) - 6, bot - 6)], fill=tone(glass, 1.7), width=4)
        d.rectangle([Z(z0), top, Z(z1), bot], outline=(215, 218, 222), width=3)
    d.line([(Z(m["z_tail"] + 0.05), Y(m["belt"]) + 2), (Z(m["z_nose"] - 0.08), Y(m["belt"]) + 2)], fill=(222, 224, 228), width=3)
    for dd in rec.get("doors", []):
        if abs(dd[0]) > rec["width"] / 2 + 3:
            continue
        z = dd[1] / BLOCK_PX
        d.line([(Z(z), Y(m["belt"] + 0.012)), (Z(z), Y(P["g"] + 0.025))], fill=tone(paint, 0.5), width=2)
    for w in wheels:
        r = w["radius"] * 1.22
        d.pieslice([Z(w["z"] - r), Y(w["y"] + r), Z(w["z"] + r), Y(w["y"] - r)], 180, 360, fill=(28, 26, 24))
    return im


def make_front_texture(m, paint, glass):
    Wt, Ht = 512, 256
    im = Image.new("RGB", (Wt, Ht), tone(paint, 0.9))
    d = ImageDraw.Draw(im)
    Hmax = m["Hmax"]

    def Y(y):
        return int((1 - y / Hmax) * Ht)
    for row in range(Ht):
        y = (1 - row / Ht) * Hmax
        d.line([(0, row), (Wt, row)], fill=tone(paint, 0.7 + 0.35 * min(1, y / max(m["belt"], 0.01))))
    if m["family"] == "box" and m["cab_over"]:
        d.rectangle([int(Wt * 0.1), Y(m["roof"] - 0.03), int(Wt * 0.9), Y(m["belt"] + 0.05)], fill=tuple(int(v) for v in glass), outline=(215, 218, 222), width=3)
    gy0, gy1 = Y(m["hood"] * 0.74 + 0.1 * M), Y(m["hood"] * 0.74 - 0.14 * M)
    d.rectangle([int(Wt * 0.27), gy0, int(Wt * 0.73), gy1], fill=(40, 40, 42))
    for y in range(gy0 + 3, gy1, 7):
        d.line([(int(Wt * 0.28), y), (int(Wt * 0.72), y)], fill=(200, 204, 210), width=3)
    return im


def make_rear_texture(m, paint, glass):
    Wt, Ht = 512, 256
    im = Image.new("RGB", (Wt, Ht), tone(paint, 0.85))
    d = ImageDraw.Draw(im)
    Hmax = m["Hmax"]

    def Y(y):
        return int((1 - y / Hmax) * Ht)
    for row in range(Ht):
        y = (1 - row / Ht) * Hmax
        d.line([(0, row), (Wt, row)], fill=tone(paint, 0.65 + 0.35 * min(1, y / max(m["belt"], 0.01))))
    if m["family"] == "box":
        top = m["box"] if m["cargo_box"] else m["roof"]
        d.rectangle([int(Wt * 0.15), Y(top - 0.03), int(Wt * 0.85), Y(m["belt"] * 0.5)], outline=tone(paint, 0.5), width=4)
        d.line([(Wt // 2, Y(top - 0.03)), (Wt // 2, Y(m["belt"] * 0.5))], fill=tone(paint, 0.5), width=4)
    d.rectangle([int(Wt * 0.42), Y(m["belt"] * 0.55 + 0.02), int(Wt * 0.58), Y(m["belt"] * 0.55 - 0.03)], fill=(230, 225, 200), outline=(60, 60, 60))
    return im


def make_grille_texture():
    im = Image.new("RGB", (128, 64), (36, 36, 38))
    d = ImageDraw.Draw(im)
    for y in range(4, 64, 8):
        d.line([(2, y), (126, y)], fill=(210, 214, 220), width=3)
    return im


def flat(colour, size=(16, 16)):
    return Image.new("RGB", size, tuple(int(v) for v in colour))


def make_lamp_texture():
    im = Image.new("RGB", (128, 64), (235, 225, 200))
    d = ImageDraw.Draw(im)
    d.ellipse([34, 2, 94, 62], fill=(255, 250, 230), outline=(200, 190, 160))
    d.ellipse([54, 22, 74, 42], fill=(255, 255, 255))
    return im


def make_tyre_texture():
    im = Image.new("RGB", (128, 32), (26, 26, 27))
    d = ImageDraw.Draw(im)
    for x in range(0, 128, 8):
        d.line([(x, 4), (x, 28)], fill=(40, 40, 41), width=2)
    return im


def make_hubcap_texture(whitewall=False):
    im = Image.new("RGB", (64, 64), (24, 24, 25))
    d = ImageDraw.Draw(im)
    d.ellipse([3, 3, 61, 61], fill=(30, 30, 31))
    if whitewall:
        d.ellipse([7, 7, 57, 57], fill=(236, 234, 226))
    d.ellipse([15, 15, 49, 49], fill=(205, 208, 214), outline=(150, 150, 155))
    d.ellipse([26, 26, 38, 38], fill=(240, 240, 244))
    return im


MATERIALS = {
    "top": (0.55, 0.32), "side": (0.55, 0.32), "front": (0.55, 0.35), "rear": (0.55, 0.35), "under": (0.1, 0.9),
    "chrome": (1.0, 0.12), "grille": (0.9, 0.3), "lamp": (0.0, 0.2), "tail": (0.0, 0.25), "tyre": (0.0, 0.85),
    "hubcap": (0.9, 0.2), "hubcap_ww": (0.9, 0.2), "blue": (0.0, 0.2), "red": (0.0, 0.2), "taxi": (0.0, 0.4),
    "seat": (0.0, 0.8), "glass": (0.0, 0.1),
}
EMISSIVE = {"lamp": (0.6, 0.55, 0.4), "tail": (0.5, 0.05, 0.02), "blue": (0.1, 0.2, 0.9), "red": (0.9, 0.1, 0.05), "taxi": (0.8, 0.7, 0.1)}


# ----------------------------------------------------------------------------
# One car
# ----------------------------------------------------------------------------
def generate(rec, rgba, hx4, variant, out_dir, render=True, paint_hint=None):
    import trimesh
    name = rec["slug"] + ("" if variant in (None, "default") else f"_{variant}")
    cls, family, flags = resolve_class(rec)
    P = dict(PRESETS.get(cls, PRESETS["sedan"]))
    if flags.get("lifted"):
        P["r"] = 0.52 * M
        for k in ("g", "hb", "hood", "roof", "trunk"):
            P[k] += 0.3 * M
    paint = np.array(paint_hint, np.float32) if paint_hint else sprite_body_colour(rgba)
    parts = {k: Part(k) for k in MATERIALS}
    whitewall = cls in ("limo", "taxi") or "t-bird" in rec["name"].lower()
    if family == "bike":
        m, wheels = build_bike(rec, rgba, parts)
        glass = np.array([44, 54, 72], np.float32)
    elif family == "tank":
        m, wheels = build_tank(rec, rgba, parts)
        glass = np.array([44, 54, 72], np.float32)
    elif rec.get("wreck"):
        # A burnt-out wreck: the sedan loft crushed, two or three wheels askew, no trim.
        m = build_body(rec, rgba, P, cls, family, flags, parts, deform=wreck_deform(rec["model"]))
        rng = np.random.default_rng(rec["model"] * 7 + 1)
        keep = [n for n in ("fl", "fr", "rl", "rr") if rng.random() < 0.7] or ["rl"]
        wheels = add_wheels(rec, m, P, parts, cls, False, keep=keep, askew=True)
        glass = np.array([30, 30, 30], np.float32)
    else:
        m = build_body(rec, rgba, P, cls, family, flags, parts)
        y0, y1 = m["rows"][0], m["rows"][1]
        rows = (int(y0 + (m["z_rw"] - m["z_tail"]) / m["L"] * (y1 - y0)), int(y0 + (m["z_fw"] - m["z_tail"]) / m["L"] * (y1 - y0)))
        glass = sprite_glass_colour(rgba, rows)
        wheels = add_wheels(rec, m, P, parts, cls, whitewall)
        add_trim(rec, m, P, parts, cls, flags, rgba)
    if rec.get("wreck"):
        tones = wreck_tones(rgba)
        charred = charred_texture(tones, seed=rec["model"])
        paint = np.array(tones["dark"], np.float32)
        side_tex, front_tex, rear_tex = charred, charred.resize((512, 384)), charred.transpose(Image.FLIP_LEFT_RIGHT).resize((512, 384))
    else:
        side_tex = make_side_texture(rec, m, P, cls, paint, glass, wheels)
        front_tex, rear_tex = make_front_texture(m, paint, glass), make_rear_texture(m, paint, glass)
    textures = {
        "top": make_top_texture(hx4, paint),
        "side": side_tex,
        "front": front_tex,
        "rear": rear_tex,
        "under": flat((28, 26, 24)), "chrome": flat((225, 228, 232)), "grille": make_grille_texture(), "lamp": make_lamp_texture(),
        "tail": flat((200, 20, 20)), "tyre": make_tyre_texture(), "hubcap": make_hubcap_texture(), "hubcap_ww": make_hubcap_texture(True),
        "blue": flat((40, 80, 240)), "red": flat((240, 40, 30)), "taxi": flat((250, 210, 40)), "seat": flat((40, 30, 25)),
        "glass": flat(tuple(int(v) for v in glass)),
    }
    scene = trimesh.Scene()
    tris = 0
    for key, part in parts.items():
        if not part.f:
            continue
        tris += part.tri_count()
        v = np.array(part.v, np.float32)
        f = np.array(part.f, np.int64)
        n = np.array(part.n, np.float32)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        uv = np.array(part.uv, np.float32)
        uv[:, 1] = 1.0 - uv[:, 1]
        met, rough = MATERIALS[key]
        if rec.get("wreck"):
            met, rough = (0.3, 0.92) if key in ("top", "side", "front", "rear") else (met, max(rough, 0.8))
        mat = trimesh.visual.material.PBRMaterial(name=key, baseColorTexture=textures[key], metallicFactor=met, roughnessFactor=rough,
                                                  emissiveFactor=EMISSIVE.get(key))
        mesh = trimesh.Trimesh(vertices=v, faces=f, vertex_normals=n, process=False)
        mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=mat)
        scene.add_geometry(mesh, node_name=key, geom_name=f"{name}_{key}")
    for w in wheels:
        T = np.eye(4)
        T[:3, 3] = (w["x"], w["y"], w["z"])
        scene.graph.update(frame_to=w["name"], matrix=T)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name + ".glb")
    scene.export(path)
    status = dict(name=name, model=rec["model"], display_name=rec["name"], cls=cls, family=family, variant=variant or "default",
                  triangles=tris, length=round(m["L"], 4), width=round(m["W"], 4), height=round(float(m["Hmax"]), 4),
                  z_tail=round(m["z_tail"], 4), z_nose=round(m["z_nose"], 4), wheels=wheels, forward="+z", pivot="sprite centre on the ground",
                  sprite=rec["sprite"], glb=os.path.basename(path), paint=[int(v) for v in paint], flags=flags)
    previews = None
    if render:
        previews = (Image.fromarray(rgba, "RGBA"), render_parts(parts, textures, m, "top"), render_parts(parts, textures, m, "threequarter"))
    return status, previews


# ----------------------------------------------------------------------------
# Software rasteriser for the preview sheet
# ----------------------------------------------------------------------------
def render_parts(parts, textures, m, view, size=(300, 240)):
    Wd, Hd = size
    img = np.full((Hd, Wd, 3), 0.20, np.float32)
    depth = np.full((Hd, Wd), np.inf, np.float32)
    L, W, H = m["L"], m["W"], m["Hmax"]
    cz = (m["z_tail"] + m["z_nose"]) / 2
    centre = np.array([m["xo"], H * 0.45, cz], np.float32)
    if view == "top":
        s = min(Wd / (W * 1.3), Hd / (L * 1.08))

        def project(v):
            return (v[:, 0] - m["xo"]) * s + Wd / 2, (v[:, 2] - cz) * s + Hd / 2, -v[:, 1]
        persp = False
        viewdir = np.array([0, 1, 0], np.float32)
    elif view == "side":
        s = min(Wd / (L * 1.1), Hd / (H * 1.3))

        def project(v):
            return (v[:, 2] - cz) * s + Wd / 2, Hd * 0.85 - v[:, 1] * s, v[:, 0]
        persp = False
        viewdir = np.array([-1, 0, 0], np.float32)
    else:
        yaw, pitch = math.radians(145), math.radians(22)
        cy, sy = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        R = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float32)
        Rp = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], np.float32)
        dist = max(L, W * 1.6, H * 2.2) * 2.1
        f = 1.5 * Wd

        def project(v):
            c = (v - centre) @ R.T @ Rp.T
            c[:, 2] += dist
            z = np.maximum(c[:, 2], 1e-3)
            return c[:, 0] / z * f + Wd / 2, -c[:, 1] / z * f + Hd / 2, z
        persp = True
        viewdir = -(R.T @ Rp.T @ np.array([0, 0, 1], np.float32))
        viewdir /= np.linalg.norm(viewdir)
    light = viewdir * 1.2 + np.array([0.0, 0.9, 0.0], np.float32)
    light /= np.linalg.norm(light)
    hv = light + viewdir
    hv /= np.linalg.norm(hv)
    for key, part in parts.items():
        if not part.f:
            continue
        v = np.array(part.v, np.float32)
        n = np.array(part.n, np.float32)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        uv = np.array(part.uv, np.float32)
        tex = np.array(textures[key].convert("RGB")).astype(np.float32) / 255.0
        th, tw = tex.shape[:2]
        met, rough = MATERIALS[key]
        x, y, z = project(v)
        shade = 0.55 + 0.55 * np.clip(n @ light, 0, 1)
        spec = (met * 0.8 + 0.08) * np.clip(n @ hv, 0, 1) ** (2.0 / max(rough * rough, 0.02))
        em = np.array(EMISSIVE.get(key, (0, 0, 0)), np.float32)
        for (a, b, c) in part.f:
            xs = np.array([x[a], x[b], x[c]])
            ys = np.array([y[a], y[b], y[c]])
            zs = np.array([z[a], z[b], z[c]])
            x0, x1 = int(max(0, np.floor(xs.min()))), int(min(Wd - 1, np.ceil(xs.max())))
            y0, y1 = int(max(0, np.floor(ys.min()))), int(min(Hd - 1, np.ceil(ys.max())))
            if x1 < x0 or y1 < y0:
                continue
            area = (xs[1] - xs[0]) * (ys[2] - ys[0]) - (xs[2] - xs[0]) * (ys[1] - ys[0])
            if abs(area) < 1e-6:
                continue
            px, py = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w0 = ((xs[1] - px) * (ys[2] - py) - (xs[2] - px) * (ys[1] - py)) / area
            w1 = ((xs[2] - px) * (ys[0] - py) - (xs[0] - px) * (ys[2] - py)) / area
            w2 = 1 - w0 - w1
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not inside.any():
                continue
            zz = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
            if persp:
                iw = np.stack([w0 / zs[0], w1 / zs[1], w2 / zs[2]])
                iw /= np.maximum(iw.sum(axis=0), 1e-9)
                w0, w1, w2 = iw
            sub = depth[y0:y1 + 1, x0:x1 + 1]
            visible = inside & (zz < sub)
            if not visible.any():
                continue
            u = w0 * uv[a, 0] + w1 * uv[b, 0] + w2 * uv[c, 0]
            vv = w0 * uv[a, 1] + w1 * uv[b, 1] + w2 * uv[c, 1]
            ti = np.clip((vv * th).astype(int), 0, th - 1)
            tj = np.clip((u * tw).astype(int), 0, tw - 1)
            col = tex[ti, tj]
            sh = w0 * shade[a] + w1 * shade[b] + w2 * shade[c]
            sp = w0 * spec[a] + w1 * spec[b] + w2 * spec[c]
            out = col * sh[..., None] + sp[..., None] * 0.55 + em
            region = img[y0:y1 + 1, x0:x1 + 1]
            region[visible] = out[visible]
            sub[visible] = zz[visible]
    return Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))


def make_sheet(rows, path, cols=3):
    cell_w, cell_h = 300 + 300 + 130 + 30, 240 + 32
    nrows = (len(rows) + cols - 1) // cols
    sheet = Image.new("RGB", (cell_w * cols, cell_h * nrows), (30, 30, 34))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
    except Exception:
        font = ImageFont.load_default()
    for i, (label, spr, top, tq) in enumerate(rows):
        cx, cy = (i % cols) * cell_w, (i // cols) * cell_h
        s = spr.convert("RGBA")
        scale = min(120 / max(s.size[0], 1), 236 / max(s.size[1], 1))
        s = s.resize((max(1, int(s.size[0] * scale)), max(1, int(s.size[1] * scale))), Image.NEAREST)
        bg = Image.new("RGBA", (130, 240), (60, 60, 66, 255))
        bg.paste(s, ((130 - s.size[0]) // 2, (240 - s.size[1]) // 2), s)
        sheet.paste(bg.convert("RGB"), (cx + 5, cy + 26))
        sheet.paste(top, (cx + 140, cy + 26))
        sheet.paste(tq, (cx + 445, cy + 26))
        d.text((cx + 6, cy + 6), label, fill=(235, 235, 235), font=font)
    sheet.save(path)


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--style", default=os.path.expanduser("~/gta2-linux/game/data/wil.sty"))
    ap.add_argument("--catalog", default=os.path.expanduser("~/gta2-linux/assets-src/cars/catalog.json"))
    ap.add_argument("--sprite-root", default=os.path.expanduser("~/gta2-linux/assets-src/cars"))
    ap.add_argument("--out", default=os.path.expanduser("~/gta2-linux/assets-src/cars/models_proc"))
    ap.add_argument("--sheet", default=os.path.expanduser("~/gta2-linux/out/cars_proc_sheet.png"))
    ap.add_argument("--models", default="", help="comma-separated model numbers (default all)")
    ap.add_argument("--no-remaps", action="store_true", help="only the default paint of each car")
    ap.add_argument("--max-remaps", type=int, default=99)
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--sheet-remaps", action="store_true", help="also put remap variants on the sheet")
    ap.add_argument("--wrecks", action="store_true", help="also build the wreck models")
    args = ap.parse_args()

    style = Style(args.style)
    records = load_catalog(args.catalog, style)
    if args.models:
        want = {int(x) for x in args.models.split(",")}
        records = [r for r in records if r["model"] in want]
    print(f"{len(style.cars)} car models in {os.path.basename(args.style)}, {len(records)} selected; catalog: {'yes' if os.path.exists(args.catalog) else 'no (classes inferred)'}")
    statuses, rows = [], []
    for rec in records:
        if rec.get("wreck") and not args.wrecks:
            continue
        # Variants: the catalog's remap list (native + x4 files), else decode the style ourselves.
        variants = []
        if rec["catalog_remaps"]:
            for e in rec["catalog_remaps"]:
                variants.append((e["remap"], os.path.join(args.sprite_root, e["file"]), os.path.join(args.sprite_root, e.get("file_x4", "")), e.get("paint_rgb")))
        else:
            variants.append(("default", None, None, None))
            for rm in rec["remaps"]:
                variants.append((f"remap{rm:02d}", None, None, None))
        if args.no_remaps:
            variants = variants[:1]
        variants = variants[:1 + args.max_remaps]
        for variant, native, x4, paint in variants:
            try:
                if native and os.path.exists(native):
                    rgba = np.array(Image.open(native).convert("RGBA"))
                else:
                    rm = None if variant == "default" else int(variant.replace("remap", ""))
                    rgba = style.car_sprite(rec["sprite"], rm)
                if x4 and os.path.exists(x4):
                    hx4 = Image.open(x4).convert("RGBA")
                else:
                    hx4 = Image.fromarray(rgba, "RGBA").resize((rgba.shape[1] * 4, rgba.shape[0] * 4), Image.LANCZOS)
                want_render = (not args.no_render) and (variant == "default" or args.sheet_remaps)
                st, prev = generate(rec, rgba, hx4, variant, args.out, render=want_render, paint_hint=paint)
            except Exception as e:
                import traceback
                traceback.print_exc()
                statuses.append(dict(name=rec["slug"], model=rec["model"], variant=variant, error=str(e)))
                continue
            statuses.append(st)
            if prev:
                rows.append((f"{rec['model']:>2} {rec['name']}  [{rec['class']} -> {st['cls']}/{st['family']}]  {st['triangles']} tris  {st['length']:.2f}x{st['width']:.2f}x{st['height']:.2f} blocks", *prev))
            if variant == "default":
                print(f"  {rec['model']:>2} {rec['name']:<22} {st['cls']:<8} {st['family']:<9} {st['triangles']:>5} tris  L {st['length']:.2f} W {st['width']:.2f} H {st['height']:.2f}  variants {len(variants)}")
    os.makedirs(args.out, exist_ok=True)
    json.dump(dict(cars=statuses, units="blocks (64 px)", axes="+x right, +y up, +z nose", pivot="sprite canvas centre, on the ground"),
              open(os.path.join(args.out, "status.json"), "w"), indent=1)
    if rows:
        os.makedirs(os.path.dirname(args.sheet), exist_ok=True)
        make_sheet(rows, args.sheet)
        print(f"sheet: {args.sheet}")
    ok = [s for s in statuses if "error" not in s]
    print(f"{len(ok)} models written to {args.out} ({len({s['model'] for s in ok})} car models), {len(statuses) - len(ok)} failed")


if __name__ == "__main__":
    main()
