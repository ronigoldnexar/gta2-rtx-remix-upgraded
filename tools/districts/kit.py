#!/usr/bin/env python3
"""DISTRICTS-POC step 4: the procedural facade kit. One generic, parametric generator: every element is
derived from the catalogue (catalogue.py) and the analysis (analyze.py); nothing is placed by hand, and the
same code runs on any building.

    kit.py <work> <lvl> <out .kit> [--ids 1,2,3 | --all] [--report <json>]

Elements (all in a wall's own frame: h along the wall as seen from outside, y up, d outward from the
wall plane; openings come from the tile art's boxes mapped through the renderer's own face mapping, so
detail sits where the texture shows it):
  skin          the wall stood 0.05 block proud of the box face, the same tile, with a hole at every
                window / door / shop window: the box face behind becomes the recessed glass or door
  reveals       the hole sides, textured with the opening's edge texels (the painted frame turns in)
  sills         a stone sill under each window (the grounded sill box where the art has one)
  lintels       a header over each window (masonry archetypes)
  cornice       a stepped cornice (frieze, bracket course, crown) on every roof edge; profile by archetype
  parapet       a low wall with coping on the roof edge, inside the footprint
  plinth        a base course at the street, broken at doors and shop windows
  awnings       a sloped canvas with a valance over each street-level shop window
  fire escape   landings at every window row, railings, stair flights, a drop ladder (tenements)
  ribs          vertical cladding ribs on plain industrial walls (the wall's own texture)
  dock canopy   a canopy on brackets over each loading door
  roof plant    vents, units and a chimney on the roof's interior cells (hash of the cell)
Overhangs stay within 0.15 block of the box face. Materials: the wall's own tile (skin, reveals, ribs) or a
kit material (kit_textures.py; one texture each, stable content, so stable Remix hashes).

Output (little endian): b"GDK1", u32 version 1, u32 groups; per group i32 tile (>= 0 the style's tile,
-1-k kit material k), u32 flags (1 alpha test, 2 double sided, 4 wrap uv), u32 vertex count, u32 index
count, vertices (x y z nx ny nz u v floats), u32 indices (group-relative)."""
import json, math, os, struct, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmap
from gmap import FaceFrame, W, H

KIT = ["stone_light", "stone_brown", "metal_dark", "metal_galv", "grate", "awning_red", "awning_green",
       "awning_blue", "brick_dark", "concrete", "glass_dark"]
K = {n: i for i, n in enumerate(KIT)}
ALPHA = {K["grate"]}

SKIN = 0.065         # wall proud of the box face (window recess depth, ~26 cm at 4 m a block)
HAXIS = {"N": (-1.0, 0.0, 0.0), "S": (1.0, 0.0, 0.0), "E": (0.0, 0.0, 1.0), "W": (0.0, 0.0, -1.0)}
NRM = {"N": (0.0, 0.0, 1.0), "S": (0.0, 0.0, -1.0), "E": (1.0, 0.0, 0.0), "W": (-1.0, 0.0, 0.0)}
ALONG = {"N": (-1, 0), "S": (1, 0), "E": (0, -1), "W": (0, 1)}      # map step toward +h
OUT = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}        # map step outward

# per archetype: trim material, cornice profile [(y from roof, height, depth)], parapet height, lintel?
STYLE = {
    "brick_tenement": dict(trim="stone_light", cornice="metal_dark", prof=[(-0.16, 0.06, 0.03), (-0.10, 0.06, 0.07), (-0.04, 0.05, 0.12)],
                           brackets=True, parapet=0.0, lintel=True, sill=True, fire_escape=True, plinth="stone_brown"),
    "brownstone": dict(trim="stone_brown", cornice="stone_brown", prof=[(-0.14, 0.05, 0.03), (-0.09, 0.05, 0.06), (-0.04, 0.05, 0.10)],
                       brackets=True, parapet=0.0, lintel=True, sill=True, fire_escape=True, plinth="stone_brown"),
    "office_tower": dict(trim="concrete", cornice="metal_galv", prof=[(-0.06, 0.06, 0.04)], brackets=False, parapet=0.10,
                         lintel=False, sill=True, fire_escape=False, plinth="stone_brown"),
    "shopfront_row": dict(trim="stone_light", cornice="stone_light", prof=[(-0.10, 0.05, 0.04), (-0.05, 0.05, 0.08)], brackets=False,
                          parapet=0.08, lintel=True, sill=True, fire_escape=False, plinth="stone_brown"),
    "warehouse": dict(trim="concrete", cornice="concrete", prof=[(-0.05, 0.05, 0.04)], brackets=False, parapet=0.12, lintel=False,
                      sill=False, fire_escape=False, plinth="concrete", ribs=True, dock=True, plant=True),
    "factory": dict(trim="concrete", cornice="concrete", prof=[(-0.08, 0.04, 0.03), (-0.04, 0.04, 0.06)], brackets=False, parapet=0.12,
                    lintel=True, sill=True, fire_escape=False, plinth="concrete", dock=True, plant=True, chimney=True),
    "house": dict(trim="stone_light", cornice="stone_light", prof=[(-0.06, 0.06, 0.08)], brackets=False, parapet=0.0, lintel=False,
                  sill=True, fire_escape=False, plinth="stone_brown"),
    "block": dict(trim="stone_light", cornice="stone_light", prof=[(-0.10, 0.05, 0.03), (-0.05, 0.05, 0.07)], brackets=False,
                  parapet=0.06, lintel=True, sill=True, fire_escape=False, plinth="stone_brown"),
}
AWNINGS = ["awning_red", "awning_green", "awning_blue"]


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
    P = lambda h, y, d: wl.w(h, y, d)
    n_out, ha = wl.n, wl.ha
    if "f" in faces:
        mesh.kit(mat, [P(h0, y0, d1), P(h1, y0, d1), P(h1, y1, d1), P(h0, y1, d1)], n_out)
    if "t" in faces:
        mesh.kit(mat, [P(h0, y1, d0), P(h1, y1, d0), P(h1, y1, d1), P(h0, y1, d1)], (0.0, 1.0, 0.0))
    if "b" in faces:
        mesh.kit(mat, [P(h0, y0, d0), P(h1, y0, d0), P(h1, y0, d1), P(h0, y0, d1)], (0.0, -1.0, 0.0))
    if "l" in faces:
        mesh.kit(mat, [P(h0, y0, d0), P(h0, y0, d1), P(h0, y1, d1), P(h0, y1, d0)], (-ha[0], 0.0, -ha[2]))
    if "r" in faces:
        mesh.kit(mat, [P(h1, y0, d0), P(h1, y0, d1), P(h1, y1, d1), P(h1, y1, d0)], ha)


def art_box(mesh, wl, h0, h1, y0, y1, d0, d1, faces="tblrf"):
    """the tile art of a region stood out of the wall: the front shows the region's own texels, the top,
    bottom and sides its edge rows and columns drawn back to the wall (a painted sill becomes a stone sill)"""
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
            mesh.poly(key, [P(hh, y0, d0), P(hh, y0, d1), P(hh, y1, d1), P(hh, y1, d0)],
                      [wl.uv(hu, y0), wl.uv(hu, y0), wl.uv(hu, y1), wl.uv(hu, y1)], (wl.ha[0] * s_, 0.0, wl.ha[2] * s_))


class Builder:
    def __init__(self, m, cat, an, lvl, hd=None):
        self.m, self.lvl, self.hd, self.imgs = m, lvl, hd, {}
        self.cat = {b["id"]: b for b in cat["buildings"]}
        self.arch = {b["id"]: b for b in an["buildings"]}
        self.tiles = an["tiles"]
        self.roof = [[m.top(x, y)[0] for x in range(W)] for y in range(H)]
        self.mesh = Mesh()
        self.report = []

    def solid(self, x, y, level):
        return 0 <= x < W and 0 <= y < H and self.roof[y][x] > level

    def corner(self, x, y, side, level, end):
        """end 0 = the wall's left end (h = 0), 1 = right: 'convex', 'concave' or 'straight'"""
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

    def lum(self, wl, h0, h1, y0, y1):
        """mean luminance of the tile art under a region of a wall (None without the HD tiles)"""
        if not self.hd:
            return None
        if wl.tile not in self.imgs:
            try:
                from PIL import Image
                import numpy as np
                im = Image.open(os.path.join(self.hd, self.lvl, f"tile_{wl.tile:04d}.dds")).convert("RGB").resize((64, 64), Image.BOX)
                a = np.asarray(im, np.float32) @ np.array([0.299, 0.587, 0.114], np.float32) / 255.0
                self.imgs[wl.tile] = (a, float(a.mean()))
            except Exception:
                self.imgs[wl.tile] = None
        if self.imgs[wl.tile] is None:
            return None
        a, mean = self.imgs[wl.tile]
        pts = [wl.texel(h0, y0), wl.texel(h1, y1)]
        x0, x1 = sorted(int(min(63, max(0, p[0]))) for p in pts)
        t0, t1 = sorted(int(min(63, max(0, p[1]))) for p in pts)
        return float(a[t0:t1 + 1, x0:x1 + 1].mean()) / max(mean, 1e-3)

    def trim(self, wl, mat, h0, h1, y0, y1, d0, d1, faces="tblrf", stats=None):
        rel = self.lum(wl, h0, h1, y0, y1)
        if rel is not None and rel < 0.6:
            box(self.mesh, wl, mat, h0, h1, y0, y1, d0, d1, faces)
            if stats is not None:
                stats["trim_kit"] += 1
        else:
            art_box(self.mesh, wl, h0, h1, y0, y1, d0, d1, faces)

    def course(self, wl, mat, h0, h1, y0, y1, d0, d1, top, stats):
        """a cornice course: the front shows the wall art's top band (the painted cornice line the tile already
        has, so the colours are the building's own), drawn back along its top and bottom; the kit material only
        where that band is a dark line (it would read as a black slab)"""
        band0, band1 = top - 0.10, top - 0.005
        P, key = wl.w, (wl.tile, 2)
        def U(h, t):   # the band's texel for a point of the course (t: 0 bottom .. 1 top of the course)
            return wl.uv(min(1.0, max(0.0, h)), band0 + (band1 - band0) * t)
        self.mesh.poly(key, [P(h0, y0, d1), P(h1, y0, d1), P(h1, y1, d1), P(h0, y1, d1)], [U(h0, 0), U(h1, 0), U(h1, 1), U(h0, 1)], wl.n)
        self.mesh.poly(key, [P(h0, y1, d0), P(h1, y1, d0), P(h1, y1, d1), P(h0, y1, d1)], [U(h0, 0.9), U(h1, 0.9), U(h1, 0.9), U(h0, 0.9)], (0.0, 1.0, 0.0))
        self.mesh.poly(key, [P(h0, y0, d0), P(h1, y0, d0), P(h1, y0, d1), P(h0, y0, d1)], [U(h0, 0.1), U(h1, 0.1), U(h1, 0.1), U(h0, 0.1)], (0.0, -1.0, 0.0))
        for hh, s_ in ((h0, -1), (h1, 1)):
            self.mesh.poly(key, [P(hh, y0, d0), P(hh, y0, d1), P(hh, y1, d1), P(hh, y1, d0)], [U(hh, 0), U(hh, 0), U(hh, 1), U(hh, 1)], (wl.ha[0] * s_, 0.0, wl.ha[2] * s_))

    def openings(self, tile):
        return self.tiles.get(str(tile), {}).get("openings", [])

    def build(self, bid):
        b = self.cat[bid]
        a = self.arch[bid]
        st = STYLE.get(a["archetype"])
        if not st:
            return None
        tris0 = self.mesh.tris
        self.mesh.cur = bid
        stats = defaultdict(int)
        walls = {}
        for f in b["faces"]:
            for l in f["levels"]:
                feat = self.tiles.get(str(l["tile"]), {}).get("features") or {}
                if l["tile"] and l["slope"] == 0 and feat.get("alpha", 1.0) <= 0.02:   # no lattice, railing or cut-out tile
                    walls[(f["x"], f["y"], f["side"], l["level"])] = (Wall(f["x"], f["y"], l["level"], f["side"], l["raw"]), f)
        roof = b["roof"]
        street = b["street"]
        aw_mat = AWNINGS[h32(b["district"], 7) % 3]
        for (x, y, side, level), (wl, f) in walls.items():
            ops = [o for o in self.openings(wl.tile) if o["kind"] != "sill"]
            sills = [o for o in self.openings(wl.tile) if o["kind"] == "sill"]
            el = self.ext(side, self.corner(x, y, side, level, 0), SKIN)
            er = self.ext(side, self.corner(x, y, side, level, 1), SKIN)
            holes = []
            for o in ops:
                x0, y0, x1, y1 = o["box"]
                x0, x1 = max(1.5, x0), min(62.5, x1)
                y0, y1 = max(1.0, y0), min(63.0, y1)
                if o["kind"] in ("door", "loading_door", "shop window"):
                    y1 = 64.0 if y1 > 56 else y1      # a door or shop window standing on the tile's foot opens to it
                if x1 - x0 < 7 or y1 - y0 < 9:
                    continue   # an ornament, a vent or a sign panel, not an opening one could stand in
                h0, h1, yy0, yy1 = wl.box_local((x0, y0, x1, y1))
                holes.append((h0, h1, yy0, yy1, o["kind"]))
            self.skin(wl, holes, -el, 1.0 + er, stats)
            # caps where the skin's run ends without a neighbour skin (missing face, slope)
            for end in (0, 1):
                ax, ay = ALONG[side]; s = -1 if end == 0 else 1
                kind = self.corner(x, y, side, level, end)
                if kind == "straight" and (x + ax * s, y + ay * s, side, level) not in walls:
                    hh = 0.0 if end == 0 else 1.0
                    hu = hh + (0.02 if end == 0 else -0.02)   # the wall's edge column, top to bottom
                    self.mesh.poly((wl.tile, 2), [wl.w(hh, level, 0), wl.w(hh, level, SKIN), wl.w(hh, level + 1, SKIN), wl.w(hh, level + 1, 0)],
                                   [wl.uv(hu, level), wl.uv(hu, level), wl.uv(hu, level + 1), wl.uv(hu, level + 1)], (wl.ha[0] * s, 0.0, wl.ha[2] * s))
            if (x, y, side, level + 1) not in walls and level + 1 < roof:
                self.mesh.poly((wl.tile, 2), [wl.w(-el, level + 1, 0), wl.w(1 + er, level + 1, 0), wl.w(1 + er, level + 1, SKIN), wl.w(-el, level + 1, SKIN)],
                               [wl.uv(0, level + 0.98), wl.uv(1, level + 0.98), wl.uv(1, level + 0.98), wl.uv(0, level + 0.98)], (0.0, 1.0, 0.0))
            if (x, y, side, level - 1) not in walls and level > street:
                self.trim(wl, st["trim"], -el, 1 + er, level, level + 0.03, SKIN, SKIN + 0.012, "tbf", stats)
            # sills and lintels; neighbouring windows' trims stop half way across the pier between them
            wins = sorted(hl for hl in holes if hl[4] == "window")
            lim = {}
            for i, hl in enumerate(wins):
                lo_, hi_ = max(-el, 0.0), min(1 + er, 1.0)   # trims stay on their own face: the next cell's sill would share its plane
                for o in wins:
                    if o is hl or o[3] < hl[2] or o[2] > hl[3]:
                        continue
                    if o[1] <= hl[0]: lo_ = max(lo_, (o[1] + hl[0]) / 2)
                    if o[0] >= hl[1]: hi_ = min(hi_, (o[0] + hl[1]) / 2)
                lim[hl[:4]] = (lo_, hi_)
            for (h0, h1, yy0, yy1, kind) in holes:
                elo, ehi = lim.get((h0, h1, yy0, yy1), (max(-el, 0.0), min(1 + er, 1.0)))
                if kind == "window":
                    if st.get("sill"):
                        sb = None
                        for s_ in sills:
                            sh0, sh1, sy0, sy1 = wl.box_local(s_["box"])
                            if sh0 < h1 and sh1 > h0 and abs(sy1 - yy0) < 0.12:
                                sb = (min(sh0, h0), max(sh1, h1))
                        s0, s1 = sb if sb else (h0 - 0.015, h1 + 0.015)
                        sy0 = max(level + 0.002, yy0 - 0.035)
                        self.trim(wl, st["trim"], max(elo, s0), min(ehi, s1), sy0, yy0, SKIN, SKIN + 0.04, stats=stats)
                        stats["sills"] += 1
                    if st.get("lintel") and yy1 < level + 0.96:
                        ly1 = min(level + 0.995, yy1 + 0.03)
                        self.trim(wl, st["trim"], max(elo, h0 - 0.01), min(ehi, h1 + 0.01), yy1, ly1, SKIN, SKIN + 0.018, stats=stats)
                        stats["lintels"] += 1
                elif kind == "shop window" and level <= street and f["lo"] <= street:
                    self.awning(wl, max(-el, h0 - 0.02), min(1 + er, h1 + 0.02), min(level + 0.98, yy1 + 0.03), aw_mat)
                    stats["awnings"] += 1
                elif kind == "loading_door" and level <= street and st.get("dock"):
                    self.canopy(wl, max(-el, h0 - 0.04), min(1 + er, h1 + 0.04), min(level + 0.97, yy1 + 0.04))
                    stats["dock_canopies"] += 1
            # plinth at the street, broken at doors and shop windows
            if level == f["lo"] and level <= street:
                cuts = sorted((h0, h1) for (h0, h1, yy0, yy1, k) in holes if k in ("door", "loading_door", "shop window") and yy0 < level + 0.2)
                at = -el
                for c0, c1 in cuts + [(1 + er, 1 + er)]:
                    if c0 - at > 0.02:
                        self.trim(wl, st["plinth"], at, c0, level, level + 0.1, SKIN, SKIN + 0.025, "tlrf", stats)
                    at = max(at, c1)
                stats["plinth"] += 1
            # industrial ribs on plain walls
            if st.get("ribs") and not ops:
                for k in range(1, 8):
                    hc = k / 8.0
                    self.rib(wl, hc - 0.012, hc + 0.012, level, level + 1)
                stats["ribs"] += 7
            # roof edge: cornice and parapet
            # the roof edge: the top of this column's solid wall, at the roof or one level under it (a lattice
            # railing or a sign the map stands on the roof edge is left above the cornice)
            if (x, y, side, level + 1) not in walls and level + 1 >= roof - 1 and level + 1 > street + 1:
                top = level + 1
                prof = st["prof"]
                fl = self.ext(side, self.corner(x, y, side, level, 0), SKIN + 0.02)
                fr = self.ext(side, self.corner(x, y, side, level, 1), SKIN + 0.02)
                self.trim(wl, st["cornice"], -fl, 1 + fr, top + prof[0][0] - 0.08, top + prof[0][0], SKIN, SKIN + 0.024, "blrf", stats)
                for (yo, hgt, dep) in prof:
                    dd = min(0.15, SKIN + dep)
                    l_ = self.ext(side, self.corner(x, y, side, level, 0), dd)
                    r_ = self.ext(side, self.corner(x, y, side, level, 1), dd)
                    self.course(wl, st["cornice"], -l_, 1 + r_, top + yo, top + yo + hgt, SKIN, dd, top, stats)
                if st.get("brackets"):
                    dep = prof[-1][2]
                    y_top = top + prof[-1][0]
                    for k in range(4):
                        hc = (k + 0.5) / 4.0
                        box(self.mesh, wl, st["cornice"], hc - 0.018, hc + 0.018, y_top - 0.06, y_top, SKIN, min(0.15, SKIN + dep) - 0.012, "blrf")
                if st["parapet"] > 0 and top == roof:
                    box(self.mesh, wl, st["cornice"], 0.0, 1.0, roof, top + st["parapet"], -0.08, 0.001, "tlr")
                stats["cornice"] += 1
        if st.get("fire_escape") and b["levels"] >= 3:
            self.fire_escape(b, walls, stats)
        if st.get("plant"):
            self.roof_plant(b, st, stats)
        n = self.mesh.tris - tris0
        self.report.append({"id": bid, "archetype": a["archetype"], "triangles": n, **stats})
        return n

    def skin(self, wl, holes, h_lo, h_hi, stats):
        lvl = wl.level
        hs = sorted({h_lo, h_hi} | {max(h_lo, min(h_hi, v)) for hl in holes for v in hl[:2]})
        ys = sorted({lvl, lvl + 1.0} | {max(lvl, min(lvl + 1.0, v)) for hl in holes for v in hl[2:4]})
        def in_hole(hc, yc):
            return any(h0 < hc < h1 and y0 < yc < y1 for (h0, h1, y0, y1, k) in holes)
        key = (wl.tile, 2)
        for i in range(len(hs) - 1):
            for j in range(len(ys) - 1):
                a0, a1, b0, b1 = hs[i], hs[i + 1], ys[j], ys[j + 1]
                if a1 - a0 < 1e-4 or b1 - b0 < 1e-4 or in_hole((a0 + a1) / 2, (b0 + b1) / 2):
                    continue
                pts = [wl.w(a0, b0, SKIN), wl.w(a1, b0, SKIN), wl.w(a1, b1, SKIN), wl.w(a0, b1, SKIN)]
                self.mesh.poly(key, pts, [wl.uv(a0, b0), wl.uv(a1, b0), wl.uv(a1, b1), wl.uv(a0, b1)], wl.n)
        # reveals: the four sides of every hole, the opening's edge texels drawn in
        for (h0, h1, y0, y1, k) in holes:
            e = 0.03   # the wall ~2 texels outside the opening: the returns are masonry, the frame stays set back
            sides = [((h0, y0), (h0, y1), (wl.ha[0], 0.0, wl.ha[2]), (h0 - e, None)),
                     ((h1, y0), (h1, y1), (-wl.ha[0], 0.0, -wl.ha[2]), (h1 + e, None)),
                     ((h0, y1), (h1, y1), (0.0, -1.0, 0.0), (None, y1 + e)),
                     ((h0, y0), (h1, y0), (0.0, 1.0, 0.0), (None, y0 - e))]
            for (pa, pb, n, (eh, ey)) in sides:
                if (ey is not None and ey < lvl + 0.01) or (k != "window" and ey is not None and pa[1] < lvl + 0.01):
                    continue   # a door's foot: no floor reveal at the street
                ua = wl.uv(eh if eh is not None else pa[0], ey if ey is not None else pa[1])
                ub = wl.uv(eh if eh is not None else pb[0], ey if ey is not None else pb[1])
                self.mesh.poly(key, [wl.w(pa[0], pa[1], 0.0), wl.w(pb[0], pb[1], 0.0), wl.w(pb[0], pb[1], SKIN), wl.w(pa[0], pa[1], SKIN)],
                               [ua, ub, ub, ua], n)
            stats["recesses"] += 1

    def rib(self, wl, h0, h1, y0, y1):
        d0, d1 = SKIN, SKIN + 0.016   # every proud element has its own depth: no two share a plane
        key = (wl.tile, 2)
        self.mesh.poly(key, [wl.w(h0, y0, d1), wl.w(h1, y0, d1), wl.w(h1, y1, d1), wl.w(h0, y1, d1)],
                       [wl.uv(h0, y0), wl.uv(h1, y0), wl.uv(h1, y1), wl.uv(h0, y1)], wl.n)
        for hh, s in ((h0, -1), (h1, 1)):
            self.mesh.poly(key, [wl.w(hh, y0, d0), wl.w(hh, y0, d1), wl.w(hh, y1, d1), wl.w(hh, y1, d0)],
                           [wl.uv(hh, y0), wl.uv(hh, y0), wl.uv(hh, y1), wl.uv(hh, y1)], (wl.ha[0] * s, 0.0, wl.ha[2] * s))

    def awning(self, wl, h0, h1, y_top, mat):
        dep, drop = 0.15, 0.09
        P = wl.w
        n = (wl.n[0] * drop, dep, wl.n[2] * drop)
        ln = math.sqrt(sum(c * c for c in n)); n = tuple(c / ln for c in n)
        self.mesh.kit(mat, [P(h0, y_top, SKIN), P(h1, y_top, SKIN), P(h1, y_top - drop, dep), P(h0, y_top - drop, dep)], n, scale=1.0)
        self.mesh.kit(mat, [P(h0, y_top - drop, dep), P(h1, y_top - drop, dep), P(h1, y_top - drop - 0.035, dep), P(h0, y_top - drop - 0.035, dep)], wl.n, scale=1.0)
        for hh, s in ((h0, -1), (h1, 1)):
            self.mesh.kit(mat, [P(hh, y_top, SKIN), P(hh, y_top - drop, dep), P(hh, y_top - drop - 0.035, dep), P(hh, y_top - drop - 0.01, SKIN)],
                          (wl.ha[0] * s, 0.0, wl.ha[2] * s), scale=1.0)

    def canopy(self, wl, h0, h1, y):
        box(self.mesh, wl, "metal_galv", h0, h1, y, y + 0.03, SKIN, 0.15)
        for hh in (h0 + 0.03, h1 - 0.05):
            # a tie rod from the wall above to the canopy's front edge
            P = wl.w
            self.mesh.kit("metal_dark", [P(hh, y + 0.03, 0.14), P(hh + 0.02, y + 0.03, 0.14), P(hh + 0.02, y + 0.22, SKIN), P(hh, y + 0.22, SKIN)],
                          (0.0, 0.6, 0.0), scale=4.0)

    def fire_escape(self, b, walls, stats):
        """on the longest street-facing wall run with windows on 3+ levels: two cells wide, centred"""
        runs = defaultdict(list)
        for (x, y, side, level), (wl, f) in walls.items():
            key = (side, y if side in "NS" else x)
            runs[key].append((x, y, level, wl))
        best, best_n = None, 0
        for (side, line), cells in runs.items():
            ox, oy = OUT[side]
            pos = sorted({(c[0], c[1]) for c in cells}, key=lambda p: p[0] * -ALONG[side][0] + p[1] * -ALONG[side][1])
            if len(pos) < 2:
                continue
            front = sum(1 for (x, y) in pos if 0 <= x + ox < W and 0 <= y + oy < H and self.m.top(x + ox, y + oy)[2] in (1, 2))
            lv = {c[2] for c in cells if any(o["kind"] == "window" for o in self.openings(c[3].tile))}
            if len(lv) < 3 or front < len(pos) // 2:
                continue
            score = len(pos) + len(lv)
            if score > best_n:
                best, best_n = (side, pos, cells), score
        if not best:
            return
        side, pos, cells = best
        mid = len(pos) // 2
        span = [pos[mid - 1], pos[mid]] if len(pos) >= 2 else [pos[mid]]
        levels = sorted({c[2] for c in cells if (c[0], c[1]) in span})
        lv_lo = b["street"] + 1
        landings = []
        for lv in levels:
            if lv < lv_lo or lv >= b["roof"]:
                continue
            wls = [walls[(x, y, side, lv)][0] for (x, y) in span if (x, y, side, lv) in walls]
            if len(wls) < len(span):
                continue
            ys = []
            for wl in wls:
                for o in self.openings(wl.tile):
                    if o["kind"] == "window":
                        ys.append(wl.box_local(o["box"])[2])
            yfloor = (min(ys) - 0.01) if ys else lv + 0.05
            landings.append((lv, yfloor, wls))
        dep = 0.145
        for i, (lv, yf, wls) in enumerate(landings):
            for wl in wls:
                P = wl.w
                # grating deck and a front beam
                self.mesh.kit("grate", [P(0, yf, SKIN), P(1, yf, SKIN), P(1, yf, dep), P(0, yf, dep)], (0.0, 1.0, 0.0), scale=6.0)
                box(self.mesh, wl, "metal_dark", 0.0, 1.0, yf - 0.028, yf - 0.004, dep - 0.012, dep, "tbf")
                # rails and posts
                for ry in (yf + 0.12, yf + 0.065):
                    box(self.mesh, wl, "metal_dark", 0.0, 1.0, ry - 0.008, ry, dep - 0.01, dep, "tbf")
                for k in range(5):
                    hc = k / 4.0
                    box(self.mesh, wl, "metal_dark", hc - 0.006, hc + 0.006, yf, yf + 0.12, dep - 0.012, dep, "lrf")
                # a bracket under the deck
                for hc in (0.1, 0.9):
                    self.mesh.kit("metal_dark", [P(hc, yf, SKIN), P(hc, yf, dep - 0.01), P(hc, yf - 0.1, SKIN)], (wl.ha[0], 0.0, wl.ha[2]), scale=4.0)
            stats["fire_landings"] += 1
            # stair flight down to the landing below (alternating cells), or the drop ladder
            wl = wls[i % len(wls)]
            P = wl.w
            if i > 0:
                y_lo = landings[i - 1][1]
                h0, h1 = (0.15, 0.85) if i % 2 else (0.85, 0.15)
                d0, d1 = SKIN + 0.005, dep - 0.02
                self.mesh.kit("grate", [P(h0, yf, d0), P(h0, yf, d1), P(h1, y_lo, d1), P(h1, y_lo, d0)], (0.0, 0.8, 0.0), scale=6.0)
                for dd in (d0, d1 - 0.004):
                    self.mesh.kit("metal_dark", [P(h0, yf, dd), P(h0, yf - 0.02, dd), P(h1, y_lo - 0.02, dd), P(h1, y_lo, dd)], wl.n, scale=4.0)
                stats["fire_flights"] += 1
            else:
                y_bot = b["street"] + 0.3
                for hc in (0.42, 0.52):
                    box(self.mesh, wl, "metal_dark", hc - 0.005, hc + 0.005, y_bot, yf, dep - 0.03, dep - 0.02, "lrf")
                k = 0
                yy = y_bot + 0.05
                while yy < yf - 0.02:
                    box(self.mesh, wl, "metal_dark", 0.42, 0.52, yy - 0.004, yy, dep - 0.03, dep - 0.02, "tf")
                    yy += 0.07; k += 1
                stats["fire_ladders"] += 1

    def roof_plant(self, b, st, stats):
        cs = {tuple(c) for c in b["cells"]}
        roof = b["roof"]
        inner = [(x, y) for (x, y) in cs if all((x + dx, y + dy) in cs for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))) and self.roof[y][x] == roof]
        if not inner:
            return
        chim = None
        if st.get("chimney"):
            # the inner cell furthest from the edge, ties by the cell hash
            def depth(c):
                d = 0
                while all((c[0] + dx * (d + 1), c[1] + dy * (d + 1)) in cs for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    d += 1
                return (d, h32(c[0], c[1]) & 255)
            chim = max(inner, key=depth)
            x, y = chim
            self.cylinder("brick_dark", x + 0.5, H - y - 0.5, roof, roof + 1.6, 0.17, 10)
            self.cylinder("metal_dark", x + 0.5, H - y - 0.5, roof + 1.5, roof + 1.6, 0.185, 10)
            stats["chimneys"] += 1
        for (x, y) in inner:
            if (x, y) == chim:
                continue
            hv = h32(x, y, 11)
            if hv % 4:
                continue
            cx = x + 0.3 + ((hv >> 8) & 15) / 15.0 * 0.4
            cz = H - y - 0.7 + ((hv >> 12) & 15) / 15.0 * 0.4
            if (hv >> 16) & 1:
                self.cylinder("metal_galv", cx, cz, roof, roof + 0.16, 0.06, 8)
                self.cylinder("metal_galv", cx, cz, roof + 0.16, roof + 0.2, 0.1, 8)
            else:
                self.cuboid("metal_galv", cx - 0.14, cx + 0.14, roof, roof + 0.14, cz - 0.1, cz + 0.1)
            stats["roof_vents"] += 1

    def cylinder(self, mat, cx, cz, y0, y1, r, n):
        pts = [(cx + r * math.cos(2 * math.pi * k / n), cz + r * math.sin(2 * math.pi * k / n)) for k in range(n)]
        for k in range(n):
            a, b_ = pts[k], pts[(k + 1) % n]
            ang = 2 * math.pi * (k + 0.5) / n
            self.mesh.kit(mat, [(a[0], y0, a[1]), (b_[0], y0, b_[1]), (b_[0], y1, b_[1]), (a[0], y1, a[1])], (math.cos(ang), 0.0, math.sin(ang)))
        self.mesh.kit(mat, [(p[0], y1, p[1]) for p in pts], (0.0, 1.0, 0.0))

    def cuboid(self, mat, x0, x1, y0, y1, z0, z1):
        m = self.mesh
        m.kit(mat, [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)], (0, 1, 0))
        m.kit(mat, [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)], (0, 0, -1))
        m.kit(mat, [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], (0, 0, 1))
        m.kit(mat, [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], (-1, 0, 0))
        m.kit(mat, [(x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0)], (1, 0, 0))


def main():
    work, lvl, out = sys.argv[1:4]
    data = os.environ.get("GTA2_DATA", "/mnt/gta2/gta2-linux/game/data")
    cat = json.load(open(os.path.join(work, f"{lvl}_buildings.json")))
    an = json.load(open(os.path.join(work, f"{lvl}_analysis.json")))
    m = gmap.Map(os.path.join(data, f"{lvl}.gmp"))
    hd = sys.argv[sys.argv.index("--hd") + 1] if "--hd" in sys.argv else "/mnt/gta2/gta2-linux/repo/assets/textures_hd"
    bld = Builder(m, cat, an, lvl, hd if os.path.isdir(hd) else None)
    if "--all" in sys.argv:
        ids = [b["id"] for b in an["buildings"] if b["archetype"] != "structure"]
    elif "--ids" in sys.argv:
        ids = [int(v) for v in sys.argv[sys.argv.index("--ids") + 1].split(",")]
    else:
        ids = [json.load(open(os.path.join(work, f"{lvl}_pick.json")))["id"]]
    for i in ids:
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
