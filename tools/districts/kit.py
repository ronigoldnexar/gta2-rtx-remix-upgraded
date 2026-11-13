#!/usr/bin/env python3
"""DISTRICTS: the procedural facade kit, v2 ("bolder"). One generic, parametric generator: every element is derived
from the catalogue (catalogue.py) and the analysis (analyze.py); nothing is placed by hand, the same code runs on
any building, and the output is deterministic (same inputs, same bytes).

    kit.py <work> <lvl> <out .kit> [--ids 1,2,3 | --all] [--report <json>] [--hd <textures_hd>]

Rule: extrude the tile's own art, do not paint over it. Every proud element shows the texels of the wall region it
stands out of (a painted sill becomes a stone sill, a painted pier a pier, the painted band at the top of the wall a
cornice); kit materials only for what the art does not draw (iron, canvas, glass, tanks, pipes).

Depth ladder (block units from the box face, all distinct planes; nothing beyond 0.25):
  skin 0.15 (window reveals) | string course 0.18 | pier 0.195 | hood 0.20 (+ drip 0.215) | sill 0.21 |
  rusticated plinth 0.175/0.185 | cornice: frieze 0.17, dentils 0.20, brackets 0.225, crown 0.25 |
  stoop, bay window, balcony, fire escape, dock platform, awning, canopy <= 0.25
Archetype features: masonry (piers, string courses, hood moulds, heavy cornice, rusticated plinth); residential
(stoops with cheek walls and rails at street doors, bay windows and balconies on some window columns, fire escapes
on side and rear walls, a roof water tower); industrial (sawtooth or monitor roof, loading docks with platform,
bumpers and canopy, downpipes and a duct, cladding ribs, vents and stacks); shopfronts (sign band, deep awning
coloured from the art). Openings are cut only where the analysis is confident (contrast against the art round
them) and their edges are snapped to the art (analyze.py refine_openings).

Output (little endian): b"GDK1", u32 version 1, u32 groups; per group i32 tile (>= 0 the style's tile, -1-k kit
material k), u32 flags (1 alpha test, 2 double sided, 4 wrap uv), u32 vertex count, u32 index count, vertices
(x y z nx ny nz u v floats), u32 indices (group-relative). Sidecar <out>.owners.json: per group, which building
owns which index range (qa.py)."""
import json, math, os, struct, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmap
from gmap import FaceFrame, W, H

KIT = ["stone_light", "stone_brown", "metal_dark", "metal_galv", "grate", "awning_red", "awning_green",
       "awning_blue", "brick_dark", "concrete", "glass_dark", "wood", "awning_yellow", "awning_brown", "rubber",
       "canvas_red", "canvas_green", "canvas_navy", "canvas_maroon", "canvas_cream", "canvas_ochre", "shutter"]
K = {n: i for i, n in enumerate(KIT)}
ALPHA = {K["grate"]}

SKIN = 0.15          # wall proud of the box face: the window reveal depth (~60 cm at 4 m a block)
MAXO = 0.25          # nothing stands further out than this from the box face
CONF = 0.45          # openings cut only above this confidence (analyze.py)
DEPS = 0.04          # ends of a proud element move out by DEPS x its depth past the skin: no two elements of different
                     # depth end in one plane (their end caps z-fought: qa.py coplanar pairs, round 4)
HAXIS = {"N": (-1.0, 0.0, 0.0), "S": (1.0, 0.0, 0.0), "E": (0.0, 0.0, 1.0), "W": (0.0, 0.0, -1.0)}
NRM = {"N": (0.0, 0.0, 1.0), "S": (0.0, 0.0, -1.0), "E": (1.0, 0.0, 0.0), "W": (-1.0, 0.0, 0.0)}
ALONG = {"N": (-1, 0), "S": (1, 0), "E": (0, -1), "W": (0, 1)}      # map step toward +h
OUT = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}        # map step outward

MASONRY = dict(piers=True, courses=True, hoods=True, cornice="heavy", plinth="rusticated", trim="stone_light")
STYLE = {
    "brick_tenement": dict(MASONRY, residential=True, fire_escape=True, water_tower=True, balconies=True),
    "brownstone": dict(MASONRY, trim="stone_brown", piers=False, residential=True, fire_escape=True, water_tower=True, bays=True, stoops=True),
    "house": dict(courses=False, hoods=True, cornice="eave", plinth="plain", trim="stone_light", residential=True, stoops=True),
    "office_tower": dict(MASONRY, hoods=False, cornice="heavy", trim="concrete", parapet=0.10),
    "shopfront_row": dict(MASONRY, piers=False, parapet=0.08),
    "civic": dict(MASONRY, parapet=0.08),
    "block": dict(MASONRY, parapet=0.06),
    "warehouse": dict(courses=False, hoods=False, cornice="coping", plinth="plain", trim="concrete", parapet=0.12, industrial=True,
                      ribs=True, docks=True, roof="monitor", pipes=True, vents=True),
    "factory": dict(piers=True, courses=True, hoods=True, cornice="coping", plinth="plain", trim="concrete", parapet=0.12, industrial=True,
                    docks=True, roof="sawtooth", pipes=True, vents=True, stacks=2),
}
CANVAS = {"canvas_red": (150, 40, 36), "canvas_green": (40, 92, 56), "canvas_navy": (36, 50, 92), "canvas_maroon": (100, 34, 44),
          "canvas_cream": (214, 202, 170), "canvas_ochre": (176, 128, 52)}
FABRIC = {"shopfront_row", "brownstone", "brick_tenement", "house", "block", "civic", "office_tower"}   # who gets fabric awnings
AWNING_COLOURS = {"awning_red": (168, 36, 34), "awning_green": (34, 104, 58), "awning_blue": (40, 70, 140),
                  "awning_yellow": (200, 160, 40), "awning_brown": (110, 70, 40)}


HERE = os.path.dirname(os.path.abspath(__file__))
STYLES = json.load(open(os.path.join(HERE, "styles.json")))["styles"]   # per-district rows (docs/districts-plan.md)


def contrast(lum, bx):
    """the tile art's contrast of an opening box against a 3-texel ring round it (0..255 luminance): what qa.py
    measures; an opening the art does not set off from the wall (a sign, a vent, a painted panel) is not cut"""
    x0, y0, x1, y1 = [int(round(v)) for v in bx]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(64, x1), min(64, y1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return 0.0
    import numpy as np
    inner = lum[y0:y1, x0:x1].mean()
    ring = np.concatenate([lum[max(0, y0 - 3):y0, x0:x1].ravel(), lum[y1:min(64, y1 + 3), x0:x1].ravel(),
                           lum[y0:y1, max(0, x0 - 3):x0].ravel(), lum[y0:y1, x1:min(64, x1 + 3)].ravel()])
    return float(abs(inner - ring.mean())) if ring.size else 0.0


def cuttable(o):
    """an analysis opening the kit would cut, before the art check (kind, confidence, size): qa.py uses the same"""
    if o["kind"] == "sill" or o.get("conf", 1.0) < CONF:
        return None
    x0, y0, x1, y1 = o["box"]
    x0, x1 = max(1.5, x0), min(62.5, x1)
    y0, y1 = max(1.0, y0), min(63.0, y1)
    if o["kind"] in ("door", "loading_door", "shop window"):
        y1 = 64.0 if y1 > 56 else y1      # a door or shop window standing on the tile's foot opens to it
    if x1 - x0 < 7 or y1 - y0 < 9:
        return None   # an ornament, a vent or a sign panel, not an opening one could stand in
    return (x0, y0, x1, y1)


MIN_CONTRAST = 12.0   # qa.py's low-contrast limit


def h32(*v):
    h = 2166136261
    for x in v:
        h = ((h ^ (int(x) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    return h


class Mesh:
    def __init__(self):
        self.g = defaultdict(lambda: ([], []))   # key (tile, flags) -> (verts, idx)
        self.tris = 0
        self.owner = defaultdict(list)          # key -> [(building, first index, index count)]
        self.cur = None
        self.anchors = []                       # [building, kind, x, y, base height]: roof parts' host cells (qa.py)

    def poly(self, key, pts, uvs, n):
        vs, ix = self.g[key]
        b = len(vs)
        for p, uv in zip(pts, uvs):
            vs.append((p[0], p[1], p[2], n[0], n[1], n[2], uv[0], uv[1]))
        at = len(ix)
        for k in range(1, len(pts) - 1):
            ix.extend((b, b + k, b + k + 1))
            self.tris += 1
        own = self.owner[key]
        if own and own[-1][0] == self.cur and own[-1][1] + own[-1][2] == at:
            own[-1] = (self.cur, own[-1][1], own[-1][2] + len(ix) - at)
        else:
            own.append((self.cur, at, len(ix) - at))

    def kit(self, mat, pts, n, scale=2.0):
        """a kit-material polygon, world-planar UVs on the dominant axis of its normal"""
        ax = max(range(3), key=lambda i: abs(n[i]))
        if ax == 0:
            uvs = [(p[2] * scale, -p[1] * scale) for p in pts]
        elif ax == 1:
            uvs = [(p[0] * scale, p[2] * scale) for p in pts]
        else:
            uvs = [(p[0] * scale, -p[1] * scale) for p in pts]
        self.poly((-1 - K[mat], (1 if K[mat] in ALPHA else 0) | 2 | 4), pts, uvs, n)

    def write(self, path):
        keys = sorted(self.g.keys())
        json.dump([[k[0], k[1], self.owner[k]] for k in keys], open(path + ".owners.json", "w"))
        json.dump(self.anchors, open(path + ".anchors.json", "w"))
        with open(path, "wb") as f:
            f.write(b"GDK1" + struct.pack("<II", 1, len(keys)))
            for key in keys:
                vs, ix = self.g[key]
                f.write(struct.pack("<iIII", key[0], key[1], len(vs), len(ix)))
                f.write(struct.pack(f"<{len(vs) * 8}f", *[c for v in vs for c in v]))
                f.write(struct.pack(f"<{len(ix)}I", *ix))


class Wall:
    """one face-level: local (h, y, d) <-> world, and (h, y) <-> tile texel"""

    def __init__(self, x, y, level, side, raw):
        self.x, self.y, self.level, self.side, self.raw = x, y, level, side, raw
        self.tile = raw & 0x3FF
        zs = float(H - y - 1); zn = zs + 1.0
        self.o = {"N": (x + 1.0, 0.0, zn), "S": (float(x), 0.0, zs), "E": (x + 1.0, 0.0, zs), "W": (float(x), 0.0, zn)}[side]
        self.ha, self.n = HAXIS[side], NRM[side]
        self.f = FaceFrame(x, y, level, side, raw)
        # texel -> (h, y): affine from three points
        p0, p1, p2 = self.hy(self.f.at(0, 0)), self.hy(self.f.at(64, 0)), self.hy(self.f.at(0, 64))
        self.A = ((p1[0] - p0[0]) / 64, (p2[0] - p0[0]) / 64, (p1[1] - p0[1]) / 64, (p2[1] - p0[1]) / 64)
        self.b = p0
        a, b_, c, d = self.A
        det = a * d - b_ * c
        self.Ai = (d / det, -b_ / det, -c / det, a / det)

    def hy(self, p):
        return ((p[0] - self.o[0]) * self.ha[0] + (p[2] - self.o[2]) * self.ha[2], p[1])

    def w(self, h, y, d):
        return (self.o[0] + self.ha[0] * h + self.n[0] * d, y, self.o[2] + self.ha[2] * h + self.n[2] * d)

    def texel(self, h, y):
        a, b_, c, d = self.Ai
        u, v = h - self.b[0], y - self.b[1]
        return (a * u + b_ * v, c * u + d * v)

    def uv(self, h, y):
        tx, ty = self.texel(h, y)
        return self.f.uv(min(64.0, max(0.0, tx)), min(64.0, max(0.0, ty)))

    def box_local(self, bx):
        """a tile-art box (x0, y0, x1, y1 texels) -> (h0, h1, y0, y1) on this wall"""
        x0, y0, x1, y1 = bx
        pts = [self.hy(self.f.at(tx, ty)) for tx, ty in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        return (min(p[0] for p in pts), max(p[0] for p in pts), min(p[1] for p in pts), max(p[1] for p in pts))


def box(mesh, wl, mat, h0, h1, y0, y1, d0, d1, faces="tblrf"):
    """an axis-aligned box in a wall's frame (kit material); faces: t top, b bottom, l left, r right, f front"""
    e = DEPS * max(0.0, d1 - SKIN)     # the end caps only (neighbouring cells' fronts and tops still meet edge to edge)
    P = lambda h, y, d: wl.w(h, y, d)
    n_out, ha = wl.n, wl.ha
    if "f" in faces:
        mesh.kit(mat, [P(h0, y0, d1), P(h1, y0, d1), P(h1, y1, d1), P(h0, y1, d1)], n_out)
    if "t" in faces:
        mesh.kit(mat, [P(h0, y1, d0), P(h1, y1, d0), P(h1, y1, d1), P(h0, y1, d1)], (0.0, 1.0, 0.0))
    if "b" in faces:
        mesh.kit(mat, [P(h0, y0, d0), P(h1, y0, d0), P(h1, y0, d1), P(h0, y0, d1)], (0.0, -1.0, 0.0))
    if "l" in faces:
        mesh.kit(mat, [P(h0 - e, y0, d0), P(h0 - e, y0, d1), P(h0 - e, y1, d1), P(h0 - e, y1, d0)], (-ha[0], 0.0, -ha[2]))
    if "r" in faces:
        mesh.kit(mat, [P(h1 + e, y0, d0), P(h1 + e, y0, d1), P(h1 + e, y1, d1), P(h1 + e, y1, d0)], ha)


def art_box(mesh, wl, h0, h1, y0, y1, d0, d1, faces="tblrf"):
    """the tile art of a region stood out of the wall: the front shows the region's own texels, the top,
    bottom and sides its edge rows and columns drawn back to the wall (a painted sill becomes a stone sill)"""
    ee = DEPS * max(0.0, d1 - SKIN)    # the end caps only
    P, key, e = wl.w, (wl.tile, 2), 0.004
    if "f" in faces:
        mesh.poly(key, [P(h0, y0, d1), P(h1, y0, d1), P(h1, y1, d1), P(h0, y1, d1)],
                  [wl.uv(h0, y0), wl.uv(h1, y0), wl.uv(h1, y1), wl.uv(h0, y1)], wl.n)
    if "t" in faces:
        mesh.poly(key, [P(h0, y1, d0), P(h1, y1, d0), P(h1, y1, d1), P(h0, y1, d1)],
                  [wl.uv(h0, y1 - e), wl.uv(h1, y1 - e), wl.uv(h1, y1 - e), wl.uv(h0, y1 - e)], (0.0, 1.0, 0.0))
    if "b" in faces:
        mesh.poly(key, [P(h0, y0, d0), P(h1, y0, d0), P(h1, y0, d1), P(h0, y0, d1)],
                  [wl.uv(h0, y0 + e), wl.uv(h1, y0 + e), wl.uv(h1, y0 + e), wl.uv(h0, y0 + e)], (0.0, -1.0, 0.0))
    for hh, s_, tag in ((h0, -1, "l"), (h1, 1, "r")):
        if tag in faces:
            hu = hh + (e if s_ < 0 else -e)
            hh = hh + s_ * ee
            mesh.poly(key, [P(hh, y0, d0), P(hh, y0, d1), P(hh, y1, d1), P(hh, y1, d0)],
                      [wl.uv(hu, y0), wl.uv(hu, y0), wl.uv(hu, y1), wl.uv(hu, y1)], (wl.ha[0] * s_, 0.0, wl.ha[2] * s_))



def cyl(mesh, mat, cx, cz, y0, y1, r0, r1=None, n=10, cap=True):
    """a vertical (truncated) cone / cylinder in world space; r1 the top radius"""
    r1 = r0 if r1 is None else r1
    for k in range(n):
        a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        am = (a0 + a1) / 2
        p = [(cx + r0 * math.cos(a0), y0, cz + r0 * math.sin(a0)), (cx + r0 * math.cos(a1), y0, cz + r0 * math.sin(a1)),
             (cx + r1 * math.cos(a1), y1, cz + r1 * math.sin(a1)), (cx + r1 * math.cos(a0), y1, cz + r1 * math.sin(a0))]
        mesh.kit(mat, p, (math.cos(am), (r0 - r1) / max(1e-3, y1 - y0) * 0.5, math.sin(am)))
    if cap and r1 > 1e-3:
        mesh.kit(mat, [(cx + r1 * math.cos(2 * math.pi * k / n), y1, cz + r1 * math.sin(2 * math.pi * k / n)) for k in range(n)], (0.0, 1.0, 0.0))


def cuboid(mesh, mat, x0, x1, y0, y1, z0, z1, bottom=False):
    m = mesh
    m.kit(mat, [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)], (0, 1, 0))
    if bottom:
        m.kit(mat, [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (0, -1, 0))
    m.kit(mat, [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)], (0, 0, -1))
    m.kit(mat, [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], (0, 0, 1))
    m.kit(mat, [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], (-1, 0, 0))
    m.kit(mat, [(x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0)], (1, 0, 0))


class Builder:
    def __init__(self, m, cat, an, lvl, hd=None, coarse=False, work=None):
        self.m, self.lvl, self.hd, self.imgs = m, lvl, hd, {}
        self.coarse = coarse          # LOD1: skin without openings, a two-course cornice, roof silhouettes; nothing else
        self.cat = {b["id"]: b for b in cat["buildings"]}
        self.arch = {b["id"]: b for b in an["buildings"]}
        self.tiles = an["tiles"]
        self.roof = [[m.top(x, y)[0] for x in range(W)] for y in range(H)]
        self.mesh = Mesh()
        self.report = []
        self.rows = []      # per district index (catalogue.py), its style row (styles.json; overrides/<lvl>.json picks it)
        dp = os.path.join(work, f"{lvl}_districts.json") if work else None
        if dp and os.path.exists(dp):
            for d in json.load(open(dp))["districts"]:
                name = d.get("style") if d.get("style") in STYLES else "default"
                self.rows.append((name, STYLES[name]))

    def row(self, b):
        d = b.get("district", -1)
        return self.rows[d] if 0 <= d < len(self.rows) else ("default", STYLES["default"])

    def style_for(self, b, arch):
        """the archetype's style with the district row's kit overrides on it (styles.json: null keeps the archetype's)"""
        name, row = self.row(b)
        k = row["kit"]
        # the district's architecture: its row recasts the generic archetypes (a docks quarter builds factories and
        # warehouses, a brownstone row brownstones and tenements, a downtown core towers and shop rows)
        to = (k.get("recast") or {}).get(arch)
        if to == "industrial":
            to = "factory" if b["levels"] >= 3 else "warehouse"
        if to in STYLE:
            arch = to
        st = dict(STYLE[arch])
        ind = bool(st.get("industrial"))
        st["row"] = name
        if k.get("cornice") == "heavy" and not ind and arch != "house":
            st["cornice"] = "heavy"
        if k.get("parapet") is not None and arch != "house":
            st["parapet"] = k["parapet"]
        if k.get("stacks") is not None and ind:
            st["stacks"] = k["stacks"]
        fe = k.get("fire_escapes")
        if fe == "none":
            st["fire_escape"] = False
        elif fe == "front" and not ind and arch not in ("house", "civic"):
            st["fire_escape"], st["fire_front"] = True, True
        if k.get("water_towers") is not None and not ind:
            st["water_tower"] = h32(b["id"], 77) % 1000 < 1000 * k["water_towers"]
        if k.get("roof_units") and not ind:
            st["roof_units"] = k["roof_units"]
        if ind and k.get("stacks"):
            st["vents"] = True
        st["awnings"] = k.get("awnings") or STYLES["default"]["kit"]["awnings"]
        return st

    # ---- map and art queries
    def solid(self, x, y, level):
        return 0 <= x < W and 0 <= y < H and self.roof[y][x] > level

    def corner(self, x, y, side, level, end):
        ax, ay = ALONG[side]
        s = -1 if end == 0 else 1
        nx, ny = x + ax * s, y + ay * s
        ox, oy = OUT[side]
        if not self.solid(nx, ny, level):
            return "convex"
        if self.solid(nx + ox, ny + oy, level):
            return "concave"
        return "straight"

    def ext(self, side, kind, p):
        """how far an element p proud runs past a corner (+) or stops short of it (-): N/S walls own the corners"""
        if side not in "NS":
            return 0.0
        return p if kind == "convex" else (-p if kind == "concave" else 0.0)

    def img(self, tile):
        if tile not in self.imgs:
            self.imgs[tile] = None
            if self.hd:
                try:
                    from PIL import Image
                    import numpy as np
                    im = Image.open(os.path.join(self.hd, self.lvl, f"tile_{tile:04d}.dds")).convert("RGB").resize((64, 64), Image.BOX)
                    rgb = np.asarray(im, np.float32) / 255.0
                    lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
                    self.imgs[tile] = (rgb, lum, float(lum.mean()))
                except Exception:
                    pass
        return self.imgs[tile]

    def region(self, wl, h0, h1, y0, y1):
        im = self.img(wl.tile)
        if im is None:
            return None
        pts = [wl.texel(h0, y0), wl.texel(h1, y1)]
        x0, x1 = sorted(int(min(63, max(0, p[0]))) for p in pts)
        t0, t1 = sorted(int(min(63, max(0, p[1]))) for p in pts)
        return im[0][t0:t1 + 1, x0:x1 + 1], im[1][t0:t1 + 1, x0:x1 + 1], im[2]

    def lum(self, wl, h0, h1, y0, y1):
        r = self.region(wl, h0, h1, y0, y1)
        return None if r is None else float(r[1].mean()) / max(r[2], 1e-3)

    def trim(self, wl, mat, h0, h1, y0, y1, d0, d1, faces="tblrf", stats=None):
        """the art of a region stood out; the kit material where that region is a dark line (it would read as a black bar)"""
        rel = self.lum(wl, h0, h1, y0, y1)
        if rel is not None and rel < 0.6:
            box(self.mesh, wl, mat, h0, h1, y0, y1, d0, d1, faces)
            if stats is not None:
                stats["trim_kit"] += 1
        else:
            art_box(self.mesh, wl, h0, h1, y0, y1, d0, d1, faces)

    def band(self, wl, h0, h1, y0, y1, d0, d1, b0, b1, faces="tblrf"):
        """a box whose every face shows the art band b0..b1 (world y) of this wall stretched over it: cornice courses"""
        ee = DEPS * max(0.0, d1 - SKIN)    # the end caps only
        P, key = wl.w, (wl.tile, 2)
        U = lambda h, t: wl.uv(min(1.0, max(0.0, h)), b0 + (b1 - b0) * t)
        if "f" in faces:
            self.mesh.poly(key, [P(h0, y0, d1), P(h1, y0, d1), P(h1, y1, d1), P(h0, y1, d1)], [U(h0, 0), U(h1, 0), U(h1, 1), U(h0, 1)], wl.n)
        if "t" in faces:
            self.mesh.poly(key, [P(h0, y1, d0), P(h1, y1, d0), P(h1, y1, d1), P(h0, y1, d1)], [U(h0, .9), U(h1, .9), U(h1, .9), U(h0, .9)], (0.0, 1.0, 0.0))
        if "b" in faces:
            self.mesh.poly(key, [P(h0, y0, d0), P(h1, y0, d0), P(h1, y0, d1), P(h0, y0, d1)], [U(h0, .1), U(h1, .1), U(h1, .1), U(h0, .1)], (0.0, -1.0, 0.0))
        for hh, s_, tag in ((h0, -1, "l"), (h1, 1, "r")):
            if tag in faces:
                hc = hh + s_ * ee
                self.mesh.poly(key, [P(hc, y0, d0), P(hc, y0, d1), P(hc, y1, d1), P(hc, y1, d0)], [U(hh, 0), U(hh, 0), U(hh, 1), U(hh, 1)],
                               (wl.ha[0] * s_, 0.0, wl.ha[2] * s_))

    def openings(self, tile):
        return self.tiles.get(str(tile), {}).get("openings", [])

    # ---- one building
    def build(self, bid):
        b = self.cat[bid]
        a = self.arch[bid]
        if a["archetype"] not in STYLE:
            return None
        st = self.style_for(b, a["archetype"])
        tris0 = self.mesh.tris
        self.mesh.cur = bid
        stats = defaultdict(int)
        self.st_cur = st
        walls = {}
        for f in b["faces"]:
            for l in f["levels"]:
                feat = self.tiles.get(str(l["tile"]), {}).get("features") or {}
                if l["tile"] and l["slope"] == 0 and feat.get("alpha", 1.0) <= 0.02:   # no lattice, railing or cut-out tile
                    walls[(f["x"], f["y"], f["side"], l["level"])] = (Wall(f["x"], f["y"], l["level"], f["side"], l["raw"]), f)
        roof, street = b["roof"], b["street"]
        front = self.front_run(b, walls)
        for (x, y, side, level), (wl, f) in sorted(walls.items()):
            self.face(b, st, walls, front, x, y, side, level, wl, f, stats)
        if st.get("fire_escape") and b["levels"] >= (2 if st.get("fire_front") else 3) and not self.coarse:
            self.fire_escapes(b, walls, front, stats, st.get("fire_front", False))
        if st.get("roof_units"):
            self.roof_units(b, st, stats)
        if st.get("water_tower"):
            self.water_tower(b, stats)
        if st.get("roof"):
            self.industrial_roof(b, st, stats)
        if st.get("vents") or st.get("stacks"):
            self.roof_plant(b, st, stats)
        if st.get("pipes") and not self.coarse:
            self.pipes(b, walls, stats)
        n = self.mesh.tris - tris0
        self.report.append({"id": bid, "archetype": a["archetype"], "row": st["row"], "triangles": n, **stats})
        return n

    def front_run(self, b, walls):
        """(side, line) of the longest street-facing run: the front (stoops, shop signs); fire escapes go elsewhere"""
        runs = defaultdict(set)
        for (x, y, side, level) in walls:
            ox, oy = OUT[side]
            if 0 <= x + ox < W and 0 <= y + oy < H and self.m.top(x + ox, y + oy)[2] in (1, 2):
                runs[(side, y if side in "NS" else x)].add((x, y))
        return max(runs, key=lambda k: len(runs[k])) if runs else None

    def holes_of(self, wl, st, level, street):
        out = []
        im = self.img(wl.tile)
        for o in self.openings(wl.tile):
            bx = cuttable(o)
            if bx is None:
                continue
            if im is not None and contrast(im[1] * 255.0, o["box"]) < MIN_CONTRAST:
                continue   # the art does not set it off from the wall: a recess there would read as a hole in a flat wall
            x0, y0, x1, y1 = bx
            h0, h1, yy0, yy1 = wl.box_local((x0, y0, x1, y1))
            out.append([h0, h1, yy0, yy1, o["kind"]])
        return out

    def face(self, b, st, walls, front, x, y, side, level, wl, f, stats):
        roof, street = b["roof"], b["street"]
        el = self.ext(side, self.corner(x, y, side, level, 0), SKIN)
        er = self.ext(side, self.corner(x, y, side, level, 1), SKIN)
        if self.coarse:
            self.skin(wl, [], -el, 1.0 + er, stats)
            self.caps(wl, walls, x, y, side, level, el, er, roof, street, st, stats)
            if (x, y, side, level + 1) not in walls and level + 1 >= roof - 1 and level + 1 > street + 1:
                top = level + 1
                ex = lambda dd: (-self.ext(side, self.corner(x, y, side, level, 0), dd), 1 + self.ext(side, self.corner(x, y, side, level, 1), dd))
                l, r = ex(0.19); self.band(wl, l, r, top - 0.2, top - 0.06, SKIN, 0.19, top - 0.12, top - 0.01, "blrf")
                l, r = ex(MAXO); self.band(wl, l, r, top - 0.06, top + 0.02, SKIN, MAXO, top - 0.12, top - 0.01, "tblrf")
            return
        holes = self.holes_of(wl, st, level, street)
        is_front = front is not None and front == (side, y if side in "NS" else x)
        upper = level >= street + 1
        # bay windows: some window columns of a brownstone stand out as bays (the window's own art on the bay front)
        bays = []
        if st.get("bays") and upper and level < roof:
            for hl in holes:
                if hl[4] == "window" and h32(x, y, ord(side), int(round((hl[0] + hl[1]) * 8)), 3) % 3 == 0:
                    bays.append(hl)
            holes = [hl for hl in holes if hl not in bays]
        self.skin(wl, holes, -el, 1.0 + er, stats)
        self.caps(wl, walls, x, y, side, level, el, er, roof, street, st, stats)
        wins = [hl for hl in holes if hl[4] == "window"]
        lim = self.trim_limits(wins, el, er)
        # piers between window bays, standing out of the art (the Downtown tower's vertical bands)
        if st.get("piers"):
            art_piers = self.tiles.get(str(wl.tile), {}).get("piers", [])
            spans = []
            for x0_, x1_ in art_piers:       # the art's own vertical bands first
                h0_, h1_, _, _ = wl.box_local((x0_, 2, x1_, 62))
                spans.append([h0_, h1_])
            if not spans and wins:
                spans = self.pier_spans(holes + bays, el, er)
            for p0, p1 in spans:
                if p0 <= 1e-3 and el > 0: p0 = -0.195
                if p1 >= 1 - 1e-3 and er > 0: p1 = 1.195
                art_box(self.mesh, wl, p0, p1, level, level + 1.0, SKIN, 0.195, "lrf")
                stats["piers"] += 1
        # a string course at the floor line where the art has a band over the windows
        if st.get("courses") and wins and (x, y, side, level + 1) in walls:
            top_hole = max(hl[3] for hl in wins)
            if level + 1.0 - top_hole >= 0.06:
                cl = self.ext(side, self.corner(x, y, side, level, 0), 0.18)
                cr = self.ext(side, self.corner(x, y, side, level, 1), 0.18)
                self.trim(wl, st["trim"], -cl, 1 + cr, level + 1.0 - 0.05, level + 1.0, SKIN, 0.18, "tblrf", stats)
                stats["string_courses"] += 1
        for hl in holes:
            h0, h1, yy0, yy1, kind = hl
            elo, ehi = lim.get(tuple(hl[:4]), (max(-el, 0.0), min(1 + er, 1.0)))
            if kind == "window":
                # a sill ledge (the art under the window) and a hood mould with a drip over it
                s0, s1 = max(elo, h0 - 0.025), min(ehi, h1 + 0.025)
                proud = min(0.04, max(0.012, 0.15 * (h1 - h0)))      # at most 0.19 deep: the piers are at 0.195    # a small window gets a small sill (half of round 2)
                self.sill(wl, st["trim"], s0, s1, max(level + 0.002, yy0 - 0.012 - 0.25 * proud), yy0, proud, stats)
                stats["sills"] += 1
                if st.get("hoods") and yy1 < level + 0.94:
                    hy1 = min(level + 0.995, yy1 + 0.045)
                    hp = min(0.05, max(0.02, 0.25 * (h1 - h0)))
                    self.trim(wl, st["trim"], max(elo, h0 - 0.02), min(ehi, h1 + 0.02), yy1, hy1, SKIN, SKIN + hp, stats=stats)
                    box(self.mesh, wl, st["trim"], max(elo, h0 - 0.02), min(ehi, h1 + 0.02), yy1, yy1 + 0.012, SKIN + hp, SKIN + hp + 0.015, "blrf")
                    stats["hoods"] += 1
                if st.get("balconies") and upper and h32(x, y, ord(side), level, int(round(h0 * 8)), 9) % 4 == 1:
                    self.balcony(wl, max(elo, h0 - 0.04), min(ehi, h1 + 0.04), yy0 - 0.03)
                    stats["balconies"] += 1
            elif kind == "shop window" and level <= street:
                if st.get("industrial"):
                    # industrial: no fabric; a plain steel hood over the opening (some have none)
                    if h32(x, y, ord(side), int(h0 * 64), 21) % 3:
                        box(self.mesh, wl, "metal_galv", max(-el, h0 - 0.03), min(1 + er, h1 + 0.03), yy1, yy1 + 0.03, SKIN, 0.24, "tblrf")
                        self.wanchor("steel_hood", wl)
                        stats["steel_hoods"] += 1
                else:
                    self.shopfront(wl, max(-el, h0 - 0.03), min(1 + er, h1 + 0.03), yy1, level, stats, (b["id"], b["district"], x, y, side, h0))
            elif kind == "door" and level <= street and is_front and st["awnings"].get("doors") and not st.get("industrial"):
                # a district whose street doors are shop entrances (the downtown core): the shopfront treatment on them
                self.shopfront(wl, max(-el, h0 - 0.06), min(1 + er, h1 + 0.06), yy1, level, stats, (b["id"], b["district"], x, y, side, h0))
            elif kind in ("door", "loading_door") and level <= street:
                if st.get("industrial") and (kind == "loading_door" or h1 - h0 >= 0.33):
                    self.dock(wl, max(-el, h0 - 0.04), min(1 + er, h1 + 0.04), level, min(level + 0.96, yy1 + 0.03), stats, (h0, h1, yy0, yy1))
                elif st.get("stoops") and yy0 < level + 0.1:
                    self.stoop(wl, h0, h1, level, stats)
        for hl in bays:
            self.bay(wl, hl, el, er, stats)
        # base: a rusticated plinth broken at doors and shop windows
        if level == f["lo"] and level <= street:
            cuts = sorted((hl[0], hl[1]) for hl in holes if hl[4] in ("door", "loading_door", "shop window") and hl[2] < level + 0.2)
            at = -self.ext(side, self.corner(x, y, side, level, 0), 0.185)
            end = 1 + self.ext(side, self.corner(x, y, side, level, 1), 0.185)
            for c0, c1 in cuts + [(end, end)]:
                if c0 - at > 0.02:
                    if st.get("plinth") == "rusticated":
                        for k, (dd, gy0) in enumerate(((0.185, 0.0), (0.175, 0.105), (0.185, 0.21))):
                            self.trim(wl, st["trim"], at, c0, level + gy0, level + gy0 + 0.095, SKIN, dd, "tlrf" if k else "tlrf", stats)
                    else:
                        self.trim(wl, st["trim"], at, c0, level, level + 0.12, SKIN, 0.175, "tlrf", stats)
                at = max(at, c1)
            stats["plinth"] += 1
        if st.get("ribs") and not holes and not self.openings(wl.tile):
            for k in range(1, 8):
                hc = k / 8.0
                self.rib(wl, hc - 0.014, hc + 0.014, level, level + 1)
            stats["ribs"] += 7
        # the roof edge: the top of this column's solid wall at the roof or a level under it (a map railing stays above)
        if (x, y, side, level + 1) not in walls and level + 1 >= roof - 1 and level + 1 > street + 1:
            self.cornice(wl, st, x, y, side, level, level + 1, roof, stats)

    def sill(self, wl, mat, h0, h1, y0, y1, proud, stats):
        """a stone sill: the art under the window carried out, its top bevelled down to the front (water runs off)"""
        rel = self.lum(wl, h0, h1, y0, y1)
        P, d0, d1, bev = wl.w, SKIN, SKIN + proud, min(0.008, 0.4 * (y1 - y0))
        if rel is not None and rel < 0.6:
            mk = lambda pts, n: self.mesh.kit(mat, pts, n, scale=4.0)
            stats["trim_kit"] += 1
        else:
            key = (wl.tile, 2)
            uvs = [wl.uv(h0, y0), wl.uv(h1, y0), wl.uv(h1, y1 - 0.002), wl.uv(h0, y1 - 0.002)]   # the sill's own texels
            mk = lambda pts, n: self.mesh.poly(key, pts, uvs, n)
        mk([P(h0, y0, d1), P(h1, y0, d1), P(h1, y1 - bev, d1), P(h0, y1 - bev, d1)], wl.n)
        sl = math.hypot(proud, bev)
        mk([P(h0, y1, d0), P(h1, y1, d0), P(h1, y1 - bev, d1), P(h0, y1 - bev, d1)], (wl.n[0] * bev / sl, proud / sl, wl.n[2] * bev / sl))
        mk([P(h0, y0, d0), P(h1, y0, d0), P(h1, y0, d1), P(h0, y0, d1)], (0.0, -1.0, 0.0))
        for hh, s_ in ((h0, -1), (h1, 1)):
            mk([P(hh, y0, d0), P(hh, y0, d1), P(hh, y1 - bev, d1), P(hh, y1, d0)], (wl.ha[0] * s_, 0.0, wl.ha[2] * s_))

    def trim_limits(self, wins, el, er):
        lim = {}
        for hl in wins:
            lo_, hi_ = max(-el, 0.0), min(1 + er, 1.0)
            for o in wins:
                if o is hl or o[3] < hl[2] or o[2] > hl[3]:
                    continue
                if o[1] <= hl[0]: lo_ = max(lo_, (o[1] + hl[0]) / 2)
                if o[0] >= hl[1]: hi_ = min(hi_, (o[0] + hl[1]) / 2)
            lim[tuple(hl[:4])] = (lo_, hi_)
        return lim

    def pier_spans(self, holes, el, er):
        """the full-height bands between openings, a margin from each; at least 0.05 wide"""
        cuts = sorted((max(0.0, h[0] - 0.035), min(1.0, h[1] + 0.035)) for h in holes)
        spans, at = [], 0.0
        for c0, c1 in cuts + [(1.0, 1.0)]:
            if c0 - at >= 0.05:
                spans.append([at, c0])
            at = max(at, c1)
        for s in spans:   # piers at the face's ends join the neighbour's or wrap the corner
            if s[0] <= 1e-6 and el > 0: s[0] = -0.195
            if s[1] >= 1 - 1e-6 and er > 0: s[1] = 1.195
        return [s for s in spans if s[1] - s[0] < 0.6]   # a plain wall is not a pier

    def caps(self, wl, walls, x, y, side, level, el, er, roof, street, st, stats):
        for end in (0, 1):
            ax, ay = ALONG[side]; s = -1 if end == 0 else 1
            kind = self.corner(x, y, side, level, end)
            if kind == "straight" and (x + ax * s, y + ay * s, side, level) not in walls:
                hh = 0.0 if end == 0 else 1.0
                hu = hh + (0.02 if end == 0 else -0.02)
                self.mesh.poly((wl.tile, 2), [wl.w(hh, level, 0), wl.w(hh, level, SKIN), wl.w(hh, level + 1, SKIN), wl.w(hh, level + 1, 0)],
                               [wl.uv(hu, level), wl.uv(hu, level), wl.uv(hu, level + 1), wl.uv(hu, level + 1)], (wl.ha[0] * s, 0.0, wl.ha[2] * s))
        if (x, y, side, level + 1) not in walls and level + 1 < roof:
            self.mesh.poly((wl.tile, 2), [wl.w(-el, level + 1, 0), wl.w(1 + er, level + 1, 0), wl.w(1 + er, level + 1, SKIN), wl.w(-el, level + 1, SKIN)],
                           [wl.uv(0, level + 0.98), wl.uv(1, level + 0.98), wl.uv(1, level + 0.98), wl.uv(0, level + 0.98)], (0.0, 1.0, 0.0))
        if (x, y, side, level - 1) not in walls and level > street:
            # N/S and E/W walls' trims meet at a corner: their tops a hair apart (qa.py coplanar)
            ns = side in "NS"
            self.trim(wl, st["trim"], -el, 1 + er, level + (0.0 if ns else 0.002), level + (0.035 if ns else 0.032), SKIN, 0.165, "tbf", stats)

    def skin(self, wl, holes, h_lo, h_hi, stats):
        lvl = wl.level
        hs = sorted({h_lo, h_hi} | {max(h_lo, min(h_hi, v)) for hl in holes for v in hl[:2]})
        ys = sorted({lvl, lvl + 1.0} | {max(lvl, min(lvl + 1.0, v)) for hl in holes for v in hl[2:4]})
        def in_hole(hc, yc):
            return any(hl[0] < hc < hl[1] and hl[2] < yc < hl[3] for hl in holes)
        key = (wl.tile, 2)
        for i in range(len(hs) - 1):
            for j in range(len(ys) - 1):
                a0, a1, b0, b1 = hs[i], hs[i + 1], ys[j], ys[j + 1]
                if a1 - a0 < 1e-4 or b1 - b0 < 1e-4 or in_hole((a0 + a1) / 2, (b0 + b1) / 2):
                    continue
                pts = [wl.w(a0, b0, SKIN), wl.w(a1, b0, SKIN), wl.w(a1, b1, SKIN), wl.w(a0, b1, SKIN)]
                self.mesh.poly(key, pts, [wl.uv(a0, b0), wl.uv(a1, b0), wl.uv(a1, b1), wl.uv(a0, b1)], wl.n)
        for (h0, h1, y0, y1, k) in holes:
            e = 0.03   # the wall ~2 texels outside the opening: the returns are masonry, the frame stays set back
            sides = [((h0, y0), (h0, y1), (wl.ha[0], 0.0, wl.ha[2]), (h0 - e, None)),
                     ((h1, y0), (h1, y1), (-wl.ha[0], 0.0, -wl.ha[2]), (h1 + e, None)),
                     ((h0, y1), (h1, y1), (0.0, -1.0, 0.0), (None, y1 + e)),
                     ((h0, y0), (h1, y0), (0.0, 1.0, 0.0), (None, y0 - e))]
            for (pa, pb, n, (eh, ey)) in sides:
                if (ey is not None and ey < lvl + 0.01) or (k != "window" and ey is not None and pa[1] < lvl + 0.01):
                    continue
                ua = wl.uv(eh if eh is not None else pa[0], ey if ey is not None else pa[1])
                ub = wl.uv(eh if eh is not None else pb[0], ey if ey is not None else pb[1])
                self.mesh.poly(key, [wl.w(pa[0], pa[1], 0.0), wl.w(pb[0], pb[1], 0.0), wl.w(pb[0], pb[1], SKIN), wl.w(pa[0], pa[1], SKIN)],
                               [ua, ub, ub, ua], n)
            stats["recesses"] += 1

    def cornice(self, wl, st, x, y, side, level, top, roof, stats):
        kind = st.get("cornice", "heavy")
        def ex(dd):
            return -self.ext(side, self.corner(x, y, side, level, 0), dd), 1 + self.ext(side, self.corner(x, y, side, level, 1), dd)
        b0, b1 = top - 0.12, top - 0.01        # the art's top band: what every course shows
        if kind == "heavy":
            # frieze, dentil course, bracket course, crown and cap: a deep profile with a hard shadow line under it
            l, r = ex(0.17); self.band(wl, l, r, top - 0.26, top - 0.16, SKIN, 0.17, b0, b1, "blrf")
            l, r = ex(0.19); self.band(wl, l, r, top - 0.16, top - 0.13, SKIN, 0.19, b0, b1, "blrf")
            n = 16
            for k in range(n):
                hc = (k + 0.5) / n
                self.band(wl, hc - 0.012, hc + 0.012, top - 0.13, top - 0.095, 0.19, 0.205, b0, b1, "blrf")
            for k in range(4):
                hc = (k + 0.5) / 4
                self.band(wl, hc - 0.02, hc + 0.02, top - 0.13, top - 0.06, SKIN, 0.225, b0, b1, "blrf")
            l, r = ex(MAXO); self.band(wl, l, r, top - 0.06, top + 0.0, SKIN, MAXO, b0, b1, "tblrf")
            l, r = ex(0.24); self.band(wl, l, r, top, top + 0.025, SKIN, 0.24, b0, b1, "tlrf")
            stats["dentils"] += n
        elif kind == "eave":
            l, r = ex(0.22); box(self.mesh, wl, st["trim"], l, r, top - 0.05, top, SKIN, 0.22, "tblrf")
        else:   # coping: a concrete band and a capping
            l, r = ex(0.18); self.band(wl, l, r, top - 0.12, top - 0.04, SKIN, 0.18, b0, b1, "blrf")
            l, r = ex(0.2); box(self.mesh, wl, st["trim"], l, r, top - 0.04, top + 0.03, SKIN, 0.2, "tblrf")
        if st.get("parapet", 0) > 0 and top == roof and not self.above_roof(x, y, roof):
            box(self.mesh, wl, st["trim"], 0.0, 1.0, roof, roof + st["parapet"], -0.08, 0.001, "tlr")
        stats["cornice"] += 1

    # ---- elements
    def rib(self, wl, h0, h1, y0, y1):
        d0, d1 = SKIN, SKIN + 0.03
        key = (wl.tile, 2)
        self.mesh.poly(key, [wl.w(h0, y0, d1), wl.w(h1, y0, d1), wl.w(h1, y1, d1), wl.w(h0, y1, d1)],
                       [wl.uv(h0, y0), wl.uv(h1, y0), wl.uv(h1, y1), wl.uv(h0, y1)], wl.n)
        for hh, s in ((h0, -1), (h1, 1)):
            self.mesh.poly(key, [wl.w(hh, y0, d0), wl.w(hh, y0, d1), wl.w(hh, y1, d1), wl.w(hh, y1, d0)],
                           [wl.uv(hh, y0), wl.uv(hh, y0), wl.uv(hh, y1), wl.uv(hh, y1)], (wl.ha[0] * s, 0.0, wl.ha[2] * s))

    def awning_colour(self, wl, h0, h1, y0, y1):
        r = self.region(wl, h0, h1, y0, y1)
        if r is None:
            return "awning_red"
        import colorsys
        rgb = r[0].reshape(-1, 3)
        sat = rgb.max(1) - rgb.min(1)
        pick = rgb[sat >= max(0.15, float(sat.mean()))]
        c = (pick if len(pick) else rgb).mean(0)
        hh, ss, vv = colorsys.rgb_to_hsv(*[float(v) for v in c])
        best, bd = "awning_brown", 9.0
        for name, col in AWNING_COLOURS.items():
            h2, s2, v2 = colorsys.rgb_to_hsv(*[v / 255.0 for v in col])
            d = min(abs(hh - h2), 1 - abs(hh - h2)) * (2.0 if ss > 0.2 else 0.3) + abs(vv - v2) * 0.5
            if d < bd:
                best, bd = name, d
        return best

    def shopfront(self, wl, h0, h1, yy1, level, stats, key):
        """a sign band (the art over the shop window) stood out; under it, varied by the shop: a striped or a solid
        canvas awning, sloped or a flat box canopy, or none; the colour from a small palette per district, the entry
        nearest the art's own colour"""
        bid, district, x, y, side, hh = key
        self.wanchor("shopfront", wl)
        sb1 = min(level + 0.98, yy1 + 0.13)
        if sb1 - yy1 > 0.05:
            art_box(self.mesh, wl, h0, h1, yy1 + 0.005, sb1, SKIN, 0.2, "tblrf")
        v = h32(bid, x, y, ord(side), int(hh * 64), 17)
        aw = self.st_cur["awnings"]
        if (v % 1000) >= 1000 * aw["rate"]:
            stats["shop_no_awning"] += 1
            return
        striped = ((v >> 3) % 1000) < 1000 * aw["striped"]
        if aw.get("palette"):     # the district row's own palette: striped from its awning_*, solid from its canvas_*
            names = sorted(n for n in aw["palette"] if n in (AWNING_COLOURS if striped else CANVAS))
            if not names:
                striped = not striped
                names = sorted(n for n in aw["palette"] if n in (AWNING_COLOURS if striped else CANVAS))
            pal = names
        else:
            names = sorted(AWNING_COLOURS) if striped else sorted(CANVAS)
            pal = [names[(h32(district, k, 3) + k) % len(names)] for k in range(3)]       # three per district
        mat = self.nearest_colour(wl, h0, h1, yy1, sb1, {n: (AWNING_COLOURS if striped else CANVAS)[n] for n in pal})
        P = wl.w
        top = yy1
        if (v >> 5) % 3 == 0:     # a flat box canopy
            box(self.mesh, wl, mat, h0, h1, top - 0.06, top, SKIN, MAXO, "tblrf")
            stats["canopies_flat"] += 1
            return
        dep, drop = MAXO, 0.10 + 0.05 * ((v >> 7) % 2)
        n = (wl.n[0] * drop, dep - SKIN, wl.n[2] * drop)
        ln = math.sqrt(sum(c * c for c in n)); n = tuple(c / ln for c in n)
        self.mesh.kit(mat, [P(h0, top, SKIN), P(h1, top, SKIN), P(h1, top - drop, dep), P(h0, top - drop, dep)], n, scale=1.0)
        self.mesh.kit(mat, [P(h0, top - drop, dep), P(h1, top - drop, dep), P(h1, top - drop - 0.05, dep), P(h0, top - drop - 0.05, dep)], wl.n, scale=1.0)
        for hh2, s in ((h0, -1), (h1, 1)):
            self.mesh.kit(mat, [P(hh2, top, SKIN), P(hh2, top - drop, dep), P(hh2, top - drop - 0.05, dep), P(hh2, top - drop - 0.01, SKIN)],
                          (wl.ha[0] * s, 0.0, wl.ha[2] * s), scale=1.0)
        stats["awnings_striped" if striped else "awnings_solid"] += 1

    def nearest_colour(self, wl, h0, h1, y0, y1, choices):
        r = self.region(wl, h0, h1, y0, y1)
        names = sorted(choices)
        if r is None:
            return names[0]
        import colorsys
        rgb = r[0].reshape(-1, 3)
        sat = rgb.max(1) - rgb.min(1)
        pick = rgb[sat >= max(0.12, float(sat.mean()))]
        c = (pick if len(pick) else rgb).mean(0)
        hh, ss, vv = colorsys.rgb_to_hsv(*[float(v) for v in c])
        def d(name):
            h2, s2, v2 = colorsys.rgb_to_hsv(*[v / 255.0 for v in choices[name]])
            return min(abs(hh - h2), 1 - abs(hh - h2)) * (2.0 if ss > 0.2 else 0.3) + abs(vv - v2) * 0.5
        return min(names, key=d)

    def stoop(self, wl, h0, h1, level, stats):
        """steps up to a street door (stone), cheek walls and an iron rail each side"""
        self.wanchor("stoop", wl)
        a, b_ = h0 - 0.01, h1 + 0.01
        for k, (d0, d1, hgt) in enumerate(((0.0, 0.12, 0.12), (0.12, 0.178, 0.08), (0.178, 0.245, 0.04))):   # not the plinth's 0.185
            box(self.mesh, wl, "stone_brown", a, b_, level, level + hgt, d0 if k else SKIN * 0.0, d1, "tlrf")
        for hh in (a - 0.03, b_):
            box(self.mesh, wl, "stone_brown", hh, hh + 0.03, level, level + 0.16, SKIN, 0.245, "tlrf")
            # the rail: posts at the ends of the cheek wall and a sloped handrail
            for dp in (SKIN + 0.01, 0.235):
                box(self.mesh, wl, "metal_dark", hh + 0.01, hh + 0.02, level + 0.16, level + 0.29, dp - 0.006, dp + 0.006, "lrf")
            P = wl.w
            self.mesh.kit("metal_dark", [P(hh + 0.01, level + 0.29, SKIN), P(hh + 0.01, level + 0.29, 0.24), P(hh + 0.01, level + 0.275, 0.24),
                                         P(hh + 0.01, level + 0.275, SKIN)], (wl.ha[0], 0.0, wl.ha[2]), scale=4.0)
        stats["stoops"] += 1

    def bay(self, wl, hl, el, er, stats):
        """a bay window: the window's own art carried out to the bay front, the wall's art on its cheeks, a lead roof"""
        h0, h1, y0, y1, k = hl
        self.wanchor("bay", wl)
        a, b_ = h0 - 0.03, h1 + 0.03
        art_box(self.mesh, wl, a, b_, y0 - 0.04, y1 + 0.03, SKIN, 0.24, "lrf")
        box(self.mesh, wl, "metal_dark", a - 0.01, b_ + 0.01, y1 + 0.03, y1 + 0.06, SKIN, MAXO, "tblrf")
        box(self.mesh, wl, "stone_brown", a, b_, y0 - 0.08, y0 - 0.04, SKIN, 0.232, "tblrf")   # not the bay's own 0.24 plane
        stats["bays"] += 1

    def balcony(self, wl, h0, h1, yb):
        self.wanchor("balcony", wl)
        # 0.235 deep: the fire escape's landings stand at 0.245 (two parts never share a plane: qa.py coplanar)
        box(self.mesh, wl, "stone_light", h0, h1, yb - 0.03, yb, SKIN, 0.235, "tblrf")
        for k in range(6):
            hc = h0 + (h1 - h0) * k / 5
            box(self.mesh, wl, "metal_dark", hc - 0.005, hc + 0.005, yb, yb + 0.1, 0.225, 0.235, "lrf")
        box(self.mesh, wl, "metal_dark", h0, h1, yb + 0.1, yb + 0.112, SKIN, 0.235, "tbf")

    def dock(self, wl, h0, h1, level, ytop, stats, hole=None):
        """a loading dock: concrete platform, rubber bumpers, a roller shutter in the opening (closed, or part way up)
        under its housing, and a canopy on tie rods"""
        self.wanchor("dock", wl)
        if hole is not None:
            a0, a1, y0, y1 = hole
            v = h32(wl.x, wl.y, ord(wl.side), wl.level, int(a0 * 64), 23)
            down = (1.0, 1.0, 0.62, 0.38, 1.0, 0.8)[v % 6]           # how far down the shutter is
            yb = y1 - (y1 - y0) * down
            P = wl.w
            self.mesh.kit("shutter", [P(a0, yb, 0.03), P(a1, yb, 0.03), P(a1, y1, 0.03), P(a0, y1, 0.03)], wl.n, scale=2.0)
            box(self.mesh, wl, "metal_dark", a0, a1, yb, yb + 0.02, 0.02, 0.045, "tbf")                  # the bottom rail
            box(self.mesh, wl, "metal_galv", a0 - 0.02, a1 + 0.02, y1, y1 + 0.07, SKIN, 0.205, "tblrf")   # the housing
            ytop = max(ytop, y1 + 0.07)
            stats["roller_doors"] += 1
        box(self.mesh, wl, "concrete", h0, h1, level, level + 0.13, 0.0, 0.235, "tlrf")
        for hc in (h0 + 0.05, h1 - 0.05):
            box(self.mesh, wl, "rubber", hc - 0.025, hc + 0.025, level + 0.03, level + 0.11, 0.235, MAXO, "tblrf")
        box(self.mesh, wl, "metal_galv", h0 - 0.02, h1 + 0.02, ytop, ytop + 0.035, SKIN, MAXO, "tblrf")
        P = wl.w
        for hh in (h0, h1 - 0.02):
            self.mesh.kit("metal_dark", [P(hh, ytop + 0.035, 0.24), P(hh + 0.02, ytop + 0.035, 0.24), P(hh + 0.02, ytop + 0.25, SKIN), P(hh, ytop + 0.25, SKIN)],
                          (0.0, 0.6, 0.0), scale=4.0)
        stats["docks"] += 1

    def fire_escapes(self, b, walls, front, stats, on_front=False):
        """on side and rear walls (not the front) with windows on 3+ levels: two cells wide, the middle of the run;
        a district row with fire_escapes "front" (the brownstone rows) puts them on the street front first"""
        runs = defaultdict(list)
        for (x, y, side, level), (wl, f) in walls.items():
            runs[(side, y if side in "NS" else x)].append((x, y, level, wl))
        cands = []
        for key, cells in runs.items():
            side = key[0]
            pos = sorted({(c[0], c[1]) for c in cells}, key=lambda p: p[0] * -ALONG[side][0] + p[1] * -ALONG[side][1])
            lv = {c[2] for c in cells if any(o["kind"] == "window" and o.get("conf", 1) >= CONF for o in self.openings(c[3].tile))}
            if len(pos) < 2 or len(lv) < (2 if on_front else 3):
                continue
            cands.append(((key == front) if on_front else (key != front), len(pos) + len(lv), key, pos, cells))
        cands.sort(reverse=True)
        for side_rear, score, key, pos, cells in cands[:2 if len(cands) > 1 and (cands[1][0] or on_front) else 1]:
            self.fire_escape(b, walls, key[0], pos, cells, stats)

    def fire_escape(self, b, walls, side, pos, cells, stats):
        mid = len(pos) // 2
        span = [pos[mid - 1], pos[mid]]
        levels = sorted({c[2] for c in cells if (c[0], c[1]) in span})
        landings = []
        for lv in levels:
            if lv < b["street"] + 1 or lv >= b["roof"]:
                continue
            wls = [walls[(x, y, side, lv)][0] for (x, y) in span if (x, y, side, lv) in walls]
            if len(wls) < len(span):
                continue
            ys = [wl.box_local(o["box"])[2] for wl in wls for o in self.openings(wl.tile) if o["kind"] == "window"]
            landings.append((lv, (min(ys) - 0.01) if ys else lv + 0.05, wls))
        dep = 0.245
        for i, (lv, yf, wls) in enumerate(landings):
            for wl in wls:
                P = wl.w
                self.wanchor("fire_escape", wl)
                self.mesh.kit("grate", [P(0, yf, SKIN), P(1, yf, SKIN), P(1, yf, dep), P(0, yf, dep)], (0.0, 1.0, 0.0), scale=6.0)
                box(self.mesh, wl, "metal_dark", 0.0, 1.0, yf - 0.028, yf - 0.004, dep - 0.012, dep, "tbf")
                for ry in (yf + 0.12, yf + 0.065):
                    box(self.mesh, wl, "metal_dark", 0.0, 1.0, ry - 0.008, ry, dep - 0.01, dep, "tbf")
                for k in range(5):
                    hc = k / 4.0
                    box(self.mesh, wl, "metal_dark", hc - 0.006, hc + 0.006, yf, yf + 0.12, dep - 0.012, dep, "lrf")
                for hc in (0.093, 0.907):      # off the round numbers sills and hoods end on (qa.py coplanar)
                    self.mesh.kit("metal_dark", [P(hc, yf, SKIN), P(hc, yf, dep - 0.01), P(hc, yf - 0.12, SKIN)], (wl.ha[0], 0.0, wl.ha[2]), scale=4.0)
            stats["fire_landings"] += 1
            wl = wls[i % len(wls)]
            P = wl.w
            if i > 0:
                y_lo = landings[i - 1][1]
                h0, h1 = (0.15, 0.85) if i % 2 else (0.85, 0.15)
                d0, d1 = SKIN + 0.01, dep - 0.02
                self.mesh.kit("grate", [P(h0, yf, d0), P(h0, yf, d1), P(h1, y_lo, d1), P(h1, y_lo, d0)], (0.0, 0.8, 0.0), scale=6.0)
                for dd in (d0, d1 - 0.004):
                    self.mesh.kit("metal_dark", [P(h0, yf, dd), P(h0, yf - 0.02, dd), P(h1, y_lo - 0.02, dd), P(h1, y_lo, dd)], wl.n, scale=4.0)
                stats["fire_flights"] += 1
            else:
                y_bot = b["street"] + 0.3
                for hc in (0.42, 0.52):
                    box(self.mesh, wl, "metal_dark", hc - 0.005, hc + 0.005, y_bot, yf, dep - 0.03, dep - 0.02, "lrf")
                yy = y_bot + 0.05
                while yy < yf - 0.02:
                    box(self.mesh, wl, "metal_dark", 0.42, 0.52, yy - 0.004, yy, dep - 0.03, dep - 0.02, "tf")
                    yy += 0.07
                stats["fire_ladders"] += 1

    def roof_host(self, x, y, height):
        """a roof part may stand on (x, y) at `height` only where the map has a real flat roof there: the column's
        top block is at height - 1, flat (slope 0), has a lid, and is not a floating deck (the column reaches down
        to the block under it)"""
        if not (0 <= x < W and 0 <= y < H) or self.roof[y][x] != height:
            return False
        off, idx = self.m.columns[y * W + x]
        top = height - 1 - off
        if top < 1 or top >= len(idx) or idx[top] >= len(self.m.blocks):
            return False
        blk = self.m.blocks[idx[top]]
        under = self.m.blocks[idx[top - 1]] if idx[top - 1] < len(self.m.blocks) else None
        return (blk[6] >> 2) == 0 and (blk[4] & 0x3FF) != 0 and under is not None and any(f & 0x3FF for f in under[:4] + (under[4],))

    def interior(self, b):
        cs = {tuple(c) for c in b["cells"]}
        R = b["roof"]
        return cs, [(x, y) for (x, y) in cs if all((x + dx, y + dy) in cs for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                    and self.roof_host(x, y, R)]

    def anchor(self, kind, x, y, base):
        self.mesh.anchors.append([self.mesh.cur, kind, x, y, base])

    def wanchor(self, kind, wl):
        """a wall-mounted part's host: the map face it is fixed to (qa.py checks the face is there, flat and open)"""
        self.mesh.anchors.append([self.mesh.cur, kind, wl.x, wl.y, wl.level, wl.side])

    def above_roof(self, x, y, roof):
        blk = self.m.block(x, y, roof)
        return bool(blk) and any(f & 0x3FF for f in blk[:5])

    def roof_units(self, b, st, stats):
        """downtown roof plant: a plant-room box on the biggest roofs, rooftop units on a share of the inner roof
        cells and an antenna mast on the tallest, all on real flat roof (roof_host); kit materials (the art has none)"""
        cs, inner = self.interior(b)
        if not inner:
            return
        R = b["roof"]
        ranked = sorted(inner, key=lambda c: h32(c[0], c[1], 31))
        used = set()
        if len(inner) >= 6:      # a plant room over two inner cells side by side
            for (x, y) in ranked:
                for dx, dy in ((1, 0), (0, 1)):
                    if (x + dx, y + dy) in inner:
                        x0, x1 = x + 0.15, x + dx + 0.85
                        z0, z1 = H - (y + dy) - 1 + 0.15, H - y - 0.15
                        cuboid(self.mesh, "concrete", x0, x1, R, R + 0.55, z0, z1)
                        cuboid(self.mesh, "metal_dark", x0 - 0.03, x1 + 0.03, R + 0.55, R + 0.6, z0 - 0.03, z1 + 0.03, bottom=True)
                        self.anchor("plant_room", x, y, R); self.anchor("plant_room", x + dx, y + dy, R)
                        used |= {(x, y), (x + dx, y + dy)}
                        stats["plant_rooms"] += 1
                        break
                if used:
                    break
        n = 0
        for (x, y) in ranked:
            if (x, y) in used or h32(x, y, 37) % 1000 >= 1000 * st["roof_units"]:
                continue
            hv = h32(x, y, 41)
            cx = x + 0.3 + ((hv >> 4) & 15) / 15.0 * 0.4
            cz = H - y - 0.7 + ((hv >> 8) & 15) / 15.0 * 0.4
            w, d = (0.34, 0.24) if hv & 1 else (0.24, 0.34)
            cuboid(self.mesh, "metal_galv", cx - w / 2, cx + w / 2, R, R + 0.2, cz - d / 2, cz + d / 2)
            cyl(self.mesh, "metal_dark", cx, cz, R + 0.2, R + 0.23, 0.08, n=8)
            self.anchor("roof_unit", x, y, R)
            n += 1
        stats["roof_units"] += n
        if b["levels"] >= 4 and ranked:
            x, y = ranked[-1]
            if (x, y) not in used:
                cx, cz = x + 0.5, H - y - 0.5
                cyl(self.mesh, "metal_dark", cx, cz, R, R + 1.6, 0.03, 0.015, n=6)
                for k in range(3):
                    yy = R + 0.5 + 0.35 * k
                    cuboid(self.mesh, "metal_dark", cx - 0.18 + 0.04 * k, cx + 0.18 - 0.04 * k, yy, yy + 0.015, cz - 0.01, cz + 0.01)
                self.anchor("antenna", x, y, R)
                stats["antennas"] += 1

    def water_tower(self, b, stats):
        cs, inner = self.interior(b)
        if not inner:
            return
        x, y = max(inner, key=lambda c: h32(c[0], c[1], 5))
        cx, cz, r = x + 0.5, H - y - 0.5, 0.28
        y0 = b["roof"]
        self.anchor("water_tower", x, y, y0)
        for dx, dz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            cuboid(self.mesh, "metal_dark", cx + dx * 0.2 - 0.02, cx + dx * 0.2 + 0.02, y0, y0 + 0.36, cz + dz * 0.2 - 0.02, cz + dz * 0.2 + 0.02)
        cuboid(self.mesh, "metal_dark", cx - 0.25, cx + 0.25, y0 + 0.33, y0 + 0.36, cz - 0.25, cz + 0.25, bottom=True)
        cyl(self.mesh, "wood", cx, cz, y0 + 0.36, y0 + 0.82, r, n=12, cap=False)
        for yb in (y0 + 0.45, y0 + 0.62, y0 + 0.78):
            cyl(self.mesh, "metal_dark", cx, cz, yb, yb + 0.015, r + 0.008, n=12, cap=False)
        cyl(self.mesh, "wood", cx, cz, y0 + 0.82, y0 + 1.0, r + 0.02, 0.02, n=12, cap=False)
        stats["water_towers"] += 1

    def industrial_roof(self, b, st, stats):
        """sawtooth teeth (factory) or a monitor (warehouse) over the largest all-interior rectangle of the roof"""
        cs, inner = self.interior(b)
        inner = set(inner)
        if len(inner) < 9:
            return
        best = None
        for (x0, y0) in inner:
            x1 = x0
            while (x1 + 1, y0) in inner: x1 += 1
            for xe in range(x0, x1 + 1):
                y1 = y0
                while all((xx, y1 + 1) in inner for xx in range(x0, xe + 1)): y1 += 1
                area = (xe - x0 + 1) * (y1 - y0 + 1)
                if min(xe - x0, y1 - y0) >= 2 and (best is None or area > best[0]):
                    best = (area, x0, y0, xe, y1)
        if not best:
            return
        _, x0, y0, x1, y1 = best
        R = b["roof"]
        for xx in range(x0, x1 + 1):
            for yy in range(y0, y1 + 1):
                self.anchor("roof_" + st["roof"], xx, yy, R)
        wx0, wx1 = x0 + 0.1, x1 + 0.9
        if st["roof"] == "sawtooth":
            for yy in range(y0, y1 + 1):
                zs, zn = H - yy - 1 + 0.05, H - yy - 0.05       # each tooth one row: glass faces north (+Z)
                hgt = 0.45
                self.mesh.kit("glass_dark", [(wx0, R, zn), (wx1, R, zn), (wx1, R + hgt, zn), (wx0, R + hgt, zn)], (0, 0, 1))
                nrm = (0.0, (zn - zs), -hgt); ln = math.sqrt(nrm[1] ** 2 + nrm[2] ** 2); nrm = (0.0, nrm[1] / ln, nrm[2] / ln)
                self.mesh.kit("metal_galv", [(wx0, R, zs), (wx1, R, zs), (wx1, R + hgt, zn), (wx0, R + hgt, zn)], nrm)
                for xx, s in ((wx0, -1), (wx1, 1)):
                    self.mesh.kit("metal_galv", [(xx, R, zs), (xx, R, zn), (xx, R + hgt, zn)], (s, 0, 0))
                stats["sawtooth_teeth"] += 1
        else:
            zs, zn = H - y1 - 1 + 0.6, H - y0 - 0.6
            if zn - zs < 0.6:
                return
            cuboid(self.mesh, "glass_dark", wx0 + 0.2, wx1 - 0.2, R, R + 0.3, zs, zn)
            cuboid(self.mesh, "metal_galv", wx0 + 0.15, wx1 - 0.15, R + 0.3, R + 0.36, zs - 0.05, zn + 0.05, bottom=True)
            stats["monitor_roofs"] += 1

    def roof_plant(self, b, st, stats):
        cs, inner = self.interior(b)
        if not inner:
            return
        R = b["roof"]
        ranked = sorted(inner, key=lambda c: h32(c[0], c[1], 13))
        for k in range(min(st.get("stacks", 0), len(ranked))):
            x, y = ranked[k]
            self.anchor("stack", x, y, R)
            cyl(self.mesh, "brick_dark", x + 0.5, H - y - 0.5, R, R + 1.4 + 0.5 * k, 0.17, 0.15, n=10)
            cyl(self.mesh, "metal_dark", x + 0.5, H - y - 0.5, R + 1.3 + 0.5 * k, R + 1.4 + 0.5 * k, 0.17, n=10)
            stats["stacks"] += 1
        for (x, y) in ranked[st.get("stacks", 0):]:
            hv = h32(x, y, 11)
            if hv % 3:
                continue
            cx = x + 0.3 + ((hv >> 8) & 15) / 15.0 * 0.4
            cz = H - y - 0.7 + ((hv >> 12) & 15) / 15.0 * 0.4
            self.anchor("vent", x, y, R)
            if (hv >> 16) & 1:
                cyl(self.mesh, "metal_galv", cx, cz, R, R + 0.2, 0.07, n=8)
                cyl(self.mesh, "metal_galv", cx, cz, R + 0.2, R + 0.26, 0.12, 0.05, n=8)
            else:
                cuboid(self.mesh, "metal_galv", cx - 0.16, cx + 0.16, R, R + 0.18, cz - 0.11, cz + 0.11)
            stats["roof_vents"] += 1

    def pipes(self, b, walls, stats):
        """a downpipe at each end of every street-level wall run, and a duct along the longest run under the roof"""
        runs = defaultdict(list)
        for (x, y, side, level), (wl, f) in walls.items():
            runs[(side, y if side in "NS" else x)].append((x, y, level, wl))
        if not runs:
            return
        longest = max(runs, key=lambda k: len({(c[0], c[1]) for c in runs[k]}))
        for key, cells in runs.items():
            side = key[0]
            pos = sorted({(c[0], c[1]) for c in cells}, key=lambda p: p[0] * -ALONG[side][0] + p[1] * -ALONG[side][1])
            if len(pos) < 3:
                continue
            for (x, y), hh in ((pos[0], 0.12), (pos[-1], 0.88)):
                lvls = sorted(c[2] for c in cells if (c[0], c[1]) == (x, y))
                wl = walls[(x, y, side, lvls[0])][0]
                self.wanchor("downpipe", wl)
                p = wl.w(hh, 0, SKIN + 0.05)
                cyl(self.mesh, "metal_galv", p[0], p[2], max(b["street"], lvls[0]), lvls[-1] + 0.9, 0.025, n=6, cap=False)
                stats["downpipes"] += 1
            if key == longest:
                for (x, y) in pos[1:-1]:
                    lvls = sorted(c[2] for c in cells if (c[0], c[1]) == (x, y))
                    if lvls[-1] + 1 < b["roof"]:
                        continue
                    wl = walls[(x, y, side, lvls[-1])][0]
                    if any(wl.box_local(o["box"])[3] > lvls[-1] + 0.5 for o in self.openings(wl.tile) if o["kind"] != "sill"):
                        continue   # never across a window
                    box(self.mesh, wl, "metal_galv", 0.0, 1.0, lvls[-1] + 0.55, lvls[-1] + 0.63, SKIN, 0.23, "tbf")
                    self.wanchor("duct", wl)
                    stats["duct"] += 1


def main():
    work, lvl, out = sys.argv[1:4]
    data = os.environ.get("GTA2_DATA", "/mnt/gta2/gta2-linux/game/data")
    cat = json.load(open(os.path.join(work, f"{lvl}_buildings.json")))
    an = json.load(open(os.path.join(work, f"{lvl}_analysis.json")))
    m = gmap.Map(os.path.join(data, f"{lvl}.gmp"))
    hd = sys.argv[sys.argv.index("--hd") + 1] if "--hd" in sys.argv else "/mnt/gta2/gta2-linux/repo/assets/textures_hd"
    bld = Builder(m, cat, an, lvl, hd if os.path.isdir(hd) else None, coarse="--coarse" in sys.argv, work=work)
    if "--district" in sys.argv:
        # every building of one district of the map (catalogue.py's district keys: gang:..., nav:..., local_nav:...)
        dk = sys.argv[sys.argv.index("--district") + 1]
        keys = [d["key"] for d in json.load(open(os.path.join(work, f"{lvl}_districts.json")))["districts"]]
        arch = {a["id"]: a["archetype"] for a in an["buildings"]}
        ids = [b["id"] for b in cat["buildings"] if keys[b["district"]] == dk and arch.get(b["id"]) not in (None, "structure")]
    elif "--all" in sys.argv:
        ids = [b["id"] for b in an["buildings"] if b["archetype"] != "structure"]
    elif "--ids" in sys.argv:
        ids = [int(v) for v in sys.argv[sys.argv.index("--ids") + 1].split(",")]
    else:
        # the picked building and its street: every building whose footprint comes within --street cells (default 6)
        # of the picked one's, so a whole street changes (and the generator is exercised on its neighbours too)
        pid = json.load(open(os.path.join(work, f"{lvl}_pick.json")))["id"]
        r = float(sys.argv[sys.argv.index("--street") + 1]) if "--street" in sys.argv else 6.0
        cb = {b["id"]: b for b in cat["buildings"]}
        x0, y0, x1, y1 = cb[pid]["bbox"]
        arch = {a["id"]: a["archetype"] for a in an["buildings"]}
        ids = [i for i, b in cb.items() if arch.get(i) not in (None, "structure") and
               b["bbox"][0] <= x1 + r and b["bbox"][2] >= x0 - r and b["bbox"][1] <= y1 + r and b["bbox"][3] >= y0 - r]
    for i in sorted(ids):
        bld.build(i)
    bld.mesh.write(out)
    verts = sum(len(v) for v, _ in bld.mesh.g.values())
    print(f"{lvl}: {len(ids)} building(s), {bld.mesh.tris} triangles, {verts} vertices, {len(bld.mesh.g)} groups, "
          f"{os.path.getsize(out) / 1024:.0f} KB -> {out}")
    if "--report" in sys.argv:
        json.dump(bld.report, open(sys.argv[sys.argv.index("--report") + 1], "w"), indent=0)
    for r in bld.report[:5]:
        print("  ", r)


if __name__ == "__main__":
    main()
