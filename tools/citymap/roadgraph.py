"""CITYMAP-1 prototype: the drivable / walkable graph from a .gmp, routing, the route polyline.
This is the reference the DLL's C++ (dll/src/city_map.cpp) ports one to one."""
import heapq, math
import numpy as np
import gmp

W = H = 256
DIRS = {1: (-1, 0), 2: (1, 0), 4: (0, -1), 8: (0, 1)}     # arrow bits: left, right, up (north, -y), down
SIDE = {(-1, 0): 0, (1, 0): 1, (0, -1): 2, (0, 1): 3}      # edge index W, E, N, S
WALLKEY = {(-1, 0): "l", (1, 0): "r", (0, -1): "t", (0, 1): "b"}
OPP = {(-1, 0): "r", (1, 0): "l", (0, -1): "b", (0, 1): "t"}
WATER = range(608, 620)

# Slope piece -> (rise direction, lo, hi) as fractions of the block (block z spans heights z..z+1).
def slope_profile(t):
    if 1 <= t <= 8:   # 26 degrees, 2 pieces: up, down, left, right
        d = [(0, -1), (0, 1), (-1, 0), (1, 0)][(t - 1) // 2]; k = (t - 1) % 2
        return d, k / 2, (k + 1) / 2
    if 9 <= t <= 40:  # 7 degrees, 8 pieces
        d = [(0, -1), (0, 1), (-1, 0), (1, 0)][(t - 9) // 8]; k = (t - 9) % 8
        return d, k / 8, (k + 1) / 8
    if 41 <= t <= 44:
        d = [(0, -1), (0, 1), (-1, 0), (1, 0)][t - 41]
        return d, 0.0, 1.0
    return None

def edge_heights(z, slope):
    """height of the surface at the W, E, N, S edges (None: not crossable there)"""
    if slope == 0:
        h = z + 1.0
        return [h, h, h, h]
    p = slope_profile(slope)
    if p is None:
        return None            # diagonal / partial blocks: not a surface we route over
    d, lo, hi = p
    out = [None] * 4
    out[SIDE[d]] = z + hi
    out[SIDE[(-d[0], -d[1])]] = z + lo
    mid = z + (lo + hi) / 2
    for s in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        if s != d and s != (-d[0], -d[1]):
            out[SIDE[s]] = ("side", mid)   # sideways only onto the same slope piece
    return out

class Graph:
    def __init__(self, L):
        self.L = L
        nodes = []       # (x, y, z, ground, slope, arrows)
        cell = {}        # (x, y) -> [node ids]
        for z in range(8):
            ys, xs = np.nonzero((L.lid[z] > 0) & (L.ground[z] > 0))
            for y, x in zip(ys.tolist(), xs.tolist()):
                lid = int(L.lid[z, y, x])
                if lid in WATER:
                    continue
                if z + 1 < 8 and L.valid[z + 1, y, x] and any(L.wall[f][z + 1, y, x] for f in "lrtb") \
                        and L.lid[z + 1, y, x] > 0 and L.ground[z + 1, y, x] == 0:
                    continue   # built over: a building block sits on this lid
                eh = edge_heights(z, int(L.slopetype[z, y, x]))
                if eh is None:
                    continue
                i = len(nodes)
                nodes.append((x, y, z, int(L.ground[z, y, x]), int(L.slopetype[z, y, x]), int(L.arrows[z, y, x]), eh))
                cell.setdefault((x, y), []).append(i)
        self.nodes = nodes
        self.cell = cell
        self.car = [[] for _ in nodes]
        self.walk = [[] for _ in nodes]
        self._build()

    def match(self, a, d):
        """the node across edge d of node a whose surface meets a's there"""
        x, y, z, g, s, ar, eh = self.nodes[a]
        ha = eh[SIDE[d]]
        nx, ny = x + d[0], y + d[1]
        if not (0 <= nx < W and 0 <= ny < H):
            return None
        best = None
        for b in self.cell.get((nx, ny), ()):
            hb = self.nodes[b][6][SIDE[(-d[0], -d[1])]]
            if isinstance(ha, tuple) or isinstance(hb, tuple):
                # sideways across a ramp: only to the same piece at the same level
                if isinstance(ha, tuple) and isinstance(hb, tuple) and self.nodes[b][4] == s and self.nodes[b][2] == z:
                    best = b
                continue
            if abs(ha - hb) < 0.06:
                best = b
        return best

    def walled(self, a, d):
        """a wall face between the space above node a and its neighbour across d"""
        L = self.L
        x, y, z = self.nodes[a][:3]
        lv = z + 1
        if lv >= 8:
            return False
        nx, ny = x + d[0], y + d[1]
        if L.valid[lv, y, x] and L.wall[WALLKEY[d]][lv, y, x]:
            return True
        if L.valid[lv, ny, nx] and L.wall[OPP[d]][lv, ny, nx]:
            return True
        return False

    def _build(self):
        N = self.nodes
        nroad = 0
        for a, (x, y, z, g, s, ar, eh) in enumerate(N):
            # walking: road, pavement, field; undirected; walls stop it
            for d in DIRS.values():
                b = self.match(a, d)
                if b is None or self.walled(a, d):
                    continue
                gb = N[b][3]
                wc = {2: 1.0, 3: 1.15, 1: 1.35}
                cost = 0.5 * (wc[g] + wc[gb])   # symmetric, so the backward search is exact
                self.walk[a].append((b, cost))
            if g != 1:
                continue
            nroad += 1
            green = ar & 15
            red = (ar >> 4) & 15
            moves = {}
            for bit, d in DIRS.items():
                if green & bit:
                    moves[d] = 1.0
                elif red & bit:
                    moves[d] = 1.0      # red arrows (bridges, flyovers in bil): a road like any other
            if not moves:
                # a road cell with no arrows (car parks, yards, dead ends): any way, dearer
                for d in DIRS.values():
                    moves[d] = 1.4
            for d, c in moves.items():
                b = self.match(a, d)
                if b is not None and N[b][3] == 1:
                    self.car[a].append((b, c))
            # lane change: sideways onto a road cell that runs the same way
            for bit, d in DIRS.items():
                if not (green & bit):
                    continue
                for p in ((d[1], d[0]), (-d[1], -d[0])):
                    b = self.match(a, p)
                    if b is not None and N[b][3] == 1 and (N[b][5] & bit):
                        if all(bb != b for bb, _ in self.car[a]):
                            self.car[a].append((b, 1.6))
        self.nroad = nroad
        # reverse adjacency for the backward search
        self.car_rev = [[] for _ in N]
        for a, lst in enumerate(self.car):
            for b, c in lst:
                self.car_rev[b].append((a, c))
        # the main strongly connected part of each graph: where a destination may be snapped to
        self.main = {"car": self._main_scc(self.car, self.car_rev, [i for i, n in enumerate(N) if n[3] == 1]),
                     "walk": self._main_scc(self.walk, self.walk, list(range(len(N))))}

    def _main_scc(self, adj, rev, cand):
        """the largest strongly connected component among cand (Kosaraju, iterative)"""
        n = len(self.nodes)
        inc = [False] * n
        for i in cand: inc[i] = True
        seen = [False] * n; order = []
        for s0 in cand:
            if seen[s0]: continue
            seen[s0] = True; stack = [(s0, 0)]
            while stack:
                u, k = stack[-1]
                nb = adj[u]
                while k < len(nb) and (seen[nb[k][0]] or not inc[nb[k][0]]): k += 1
                if k < len(nb):
                    stack[-1] = (u, k + 1); v = nb[k][0]; seen[v] = True; stack.append((v, 0))
                else:
                    stack.pop(); order.append(u)
        comp = [-1] * n; best, bsize, c = -1, 0, 0
        for s0 in reversed(order):
            if comp[s0] >= 0: continue
            stack = [s0]; comp[s0] = c; size = 0
            while stack:
                u = stack.pop(); size += 1
                for v, _ in rev[u]:
                    if inc[v] and comp[v] < 0: comp[v] = c; stack.append(v)
            if size > bsize: best, bsize = c, size
            c += 1
        self.scc_count = getattr(self, "scc_count", {}); self.scc_count[id(adj)] = c
        return [comp[i] == best for i in range(n)]

    # ---------------------------------------------------------------- snapping
    def surface_at(self, x, y, zhint=None, want=None):
        ids = self.cell.get((x, y), [])
        if want:
            ids = [i for i in ids if self.nodes[i][3] in want]
        if not ids:
            return None
        if zhint is None:
            return max(ids, key=lambda i: self.nodes[i][2])
        return min(ids, key=lambda i: abs(self.nodes[i][2] + 1 - zhint))

    def snap(self, fx, fy, zhint=None, want=(1,), radius=12, graph=None):
        """nearest node of the wanted ground types to a map point (cells, float)"""
        best, bd = None, 1e9
        cx, cy = int(fx), int(fy)
        for r in range(radius + 1):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    i = self.surface_at(cx + dx, cy + dy, zhint, want)
                    if i is None or (graph is not None and not graph[i]):
                        continue
                    x, y, z = self.nodes[i][:3]
                    d = math.hypot(x + 0.5 - fx, y + 0.5 - fy)
                    if zhint is not None:
                        d += 2.0 * abs(z + 1 - zhint)
                    if d < bd:
                        best, bd = i, d
            if best is not None and r >= bd + 1:
                break
        return best

    # ---------------------------------------------------------------- search
    def cost_to(self, goal, mode="car"):
        """backward Dijkstra from the goal: cost-to-go and next hop for every node that reaches it"""
        rev = self.car_rev if mode == "car" else self.walk
        dist = {goal: 0.0}
        nxt = {goal: -1}
        pq = [(0.0, goal)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            for v, c in rev[u]:
                nd = d + c
                if nd < dist.get(v, 1e18):
                    dist[v] = nd
                    nxt[v] = u
                    heapq.heappush(pq, (nd, v))
        return dist, nxt

    def forward(self, start, mode="car"):
        adj = self.car if mode == "car" else self.walk
        dist = {start: 0.0}; prev = {start: -1}; pq = [(0.0, start)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            for v, c in adj[u]:
                nd = d + c
                if nd < dist.get(v, 1e18):
                    dist[v] = nd; prev[v] = u; heapq.heappush(pq, (nd, v))
        return dist, prev

    def start_node(self, px, py, pz, heading, dist, mode="car"):
        """the node to start from: near the player, reaching the goal, lined up with his heading"""
        want = (1,) if mode == "car" else (1, 2, 3)
        best, bc = None, 1e18
        hx, hy = (math.sin(heading), -math.cos(heading)) if heading is not None else (0, 0)
        R = 4
        while best is None and R <= 24:
          for dy in range(-R, R + 1):
            for dx in range(-R, R + 1):
                for i in self.cell.get((int(px) + dx, int(py) + dy), ()):
                    x, y, z, g, s, ar, eh = self.nodes[i]
                    if g not in want or i not in dist:
                        continue
                    off = math.hypot(x + 0.5 - px, y + 0.5 - py) + 3.0 * abs(z + 1 - pz)
                    pen = 0.0
                    if mode == "car" and heading is not None and ar & 15:
                        # the lane's way against his heading: a U-turn costs about a block's loop
                        best_dot = max(DIRS[b][0] * hx + DIRS[b][1] * hy for b in DIRS if ar & b)
                        pen = (1.0 - best_dot) * 6.0
                    c = dist[i] + off * 2.0 + pen
                    if c < bc:
                        best, bc = i, c
          R *= 2
        return best

    def path(self, start, nxt):
        out = [start]
        while nxt.get(out[-1], -1) != -1:
            out.append(nxt[out[-1]])
            if len(out) > 100000:
                break
        return out

    # ---------------------------------------------------------------- drawing
    def cross_offset(self, x, y, z, d, want):
        """offset (cells, along the perpendicular p=(-dy,dx)) from the cell centre to the middle
        of the road's cross-section at (x,y) for travel along d"""
        p = (-d[1], d[0])
        def ok(cx, cy):
            for i in self.cell.get((cx, cy), ()):
                if self.nodes[i][3] in want and abs(self.nodes[i][2] - z) <= 1:
                    return True
            return False
        a = b = 0
        while a < 8 and ok(x + p[0] * (a + 1), y + p[1] * (a + 1)):
            a += 1
        while b < 8 and ok(x - p[0] * (b + 1), y - p[1] * (b + 1)):
            b += 1
        return (a - b) / 2.0

    def polyline(self, nodes, centre=True, want=(1,)):
        """runs of one direction -> each run's line at its road's middle -> the corner points"""
        pts = [(self.nodes[i][0], self.nodes[i][1], self.nodes[i][2]) for i in nodes]
        if len(pts) < 2:
            return [(p[0] + 0.5, p[1] + 0.5) for p in pts]
        runs = []   # [d, [cells]]
        for k in range(1, len(pts)):
            d = (pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])
            if runs and runs[-1][0] == d:
                runs[-1][1].append(pts[k])
            else:
                runs.append([d, [pts[k - 1], pts[k]]])
        # each run's lateral line
        lines = []
        for d, cells in runs:
            if centre:
                offs = sorted(self.cross_offset(x, y, z, d, want) for x, y, z in cells[1:-1] or cells)
                o = offs[len(offs) // 2]
            else:
                o = 0.0
            p = (-d[1], d[0])
            x0, y0 = cells[0][0] + 0.5 + p[0] * o, cells[0][1] + 0.5 + p[1] * o
            lines.append([d, cells, (x0, y0)])
        # drop short sideways jogs (lane changes) whose neighbours line up after centring
        k = 1
        while k + 1 < len(lines):
            d0, c0, a0 = lines[k - 1]; d1, c1, a1 = lines[k]; d2, c2, a2 = lines[k + 1]
            if d0 == d2 and len(c1) <= 3 and d1 != d0 and (d1[0] * d0[0] + d1[1] * d0[1]) == 0:
                p = (-d0[1], d0[0])
                lat0 = a0[0] * p[0] + a0[1] * p[1]; lat2 = a2[0] * p[0] + a2[1] * p[1]
                if abs(lat0 - lat2) < 0.75 or centre:
                    lines[k - 1][1] = c0 + c1[1:] + c2[1:]
                    del lines[k:k + 2]
                    continue
            k += 1
        # corner points: where consecutive run lines meet
        out = []
        first = lines[0]
        p = (-first[0][1], first[0][0])
        fx, fy = first[1][0][0] + 0.5, first[1][0][1] + 0.5
        lat = first[2][0] * p[0] + first[2][1] * p[1]
        out.append((fx + p[0] * (lat - (fx * p[0] + fy * p[1])), fy + p[1] * (lat - (fx * p[0] + fy * p[1]))))
        for k in range(1, len(lines)):
            (da, ca, aa), (db, cb, ab) = lines[k - 1], lines[k]
            if da[0] * db[0] + da[1] * db[1] == 0:
                # perpendicular: x from the vertical line, y from the horizontal one
                if da[0] == 0:
                    out.append((aa[0], ab[1]))
                else:
                    out.append((ab[0], aa[1]))
            else:
                # straight on or a reversal: step across at the boundary cell
                cx, cy = cb[0][0] + 0.5, cb[0][1] + 0.5
                pa = (-da[1], da[0]); pb = (-db[1], db[0])
                la = aa[0] * pa[0] + aa[1] * pa[1]; lb = ab[0] * pb[0] + ab[1] * pb[1]
                ca_ = cx * pa[0] + cy * pa[1]; cb_ = cx * pb[0] + cy * pb[1]
                out.append((cx + pa[0] * (la - ca_), cy + pa[1] * (la - ca_)))
                out.append((cx + pb[0] * (lb - cb_), cy + pb[1] * (lb - cb_)))
        last = lines[-1]
        p = (-last[0][1], last[0][0])
        lx, ly = last[1][-1][0] + 0.5, last[1][-1][1] + 0.5
        lat = last[2][0] * p[0] + last[2][1] * p[1]
        c = lx * p[0] + ly * p[1]
        out.append((lx + p[0] * (lat - c), ly + p[1] * (lat - c)))
        return out

def fillet(pts, r=1.2, seg=5):
    """round each corner with an arc-ish quadratic of radius ~r cells"""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for k in range(1, len(pts) - 1):
        a, b, c = pts[k - 1], pts[k], pts[k + 1]
        la = math.hypot(b[0] - a[0], b[1] - a[1]); lc = math.hypot(c[0] - b[0], c[1] - b[1])
        if la < 1e-6 or lc < 1e-6:
            continue
        rr = min(r, la / 2, lc / 2)
        p0 = (b[0] + (a[0] - b[0]) / la * rr, b[1] + (a[1] - b[1]) / la * rr)
        p2 = (b[0] + (c[0] - b[0]) / lc * rr, b[1] + (c[1] - b[1]) / lc * rr)
        for i in range(seg + 1):
            t = i / seg
            out.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * b[0] + t * t * p2[0],
                        (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * b[1] + t * t * p2[1]))
    out.append(pts[-1])
    return out

def length(pts):
    return sum(math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]) for i in range(1, len(pts)))

def next_turn(pts):
    """(distance along the line to the first corner over 35 degrees, 'LEFT'/'RIGHT') or None"""
    acc = 0.0
    for k in range(1, len(pts) - 1):
        a, b, c = pts[k - 1], pts[k], pts[k + 1]
        acc += math.hypot(b[0] - a[0], b[1] - a[1])
        v1 = (b[0] - a[0], b[1] - a[1]); v2 = (c[0] - b[0], c[1] - b[1])
        n1 = math.hypot(*v1); n2 = math.hypot(*v2)
        if n1 < 1e-6 or n2 < 1e-6:
            continue
        cr = (v1[0] * v2[1] - v1[1] * v2[0]) / (n1 * n2)
        dt = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
        ang = math.degrees(math.atan2(cr, dt))
        if abs(ang) > 35 and math.hypot(c[0] - b[0], c[1] - b[1]) > 1.5 and acc > 1.0:
            # screen y down: a positive cross product turns clockwise = right
            return acc, "RIGHT" if ang > 0 else "LEFT"
    return None


def plan_route(g, px, py, pz, heading, gx, gy, mode="car"):
    """the whole request as the DLL makes it: the waypoint snapped onto the main network, one
    backward search from it (kept for re-routing), the start picked near the player.
    Returns dict(goal, start, path, pre (player -> start hop, cells), post (goal -> waypoint hop),
    dist (cost-to-go map), nxt)"""
    want = (1,) if mode == "car" else (1, 2, 3)
    goal = g.snap(gx, gy, None, want, radius=40, graph=g.main[mode])
    dist, nxt = g.cost_to(goal, mode)
    start = g.start_node(px, py, pz, heading, dist, mode)
    pre = 0.0
    if start is None:
        # he is somewhere the network cannot leave (a closed yard, an island): from the nearest
        # node that does reach the goal, with a dashed hop from him to it
        best, bd = None, 1e18
        for i in dist:
            x, y, z = g.nodes[i][:3]
            d = math.hypot(x + 0.5 - px, y + 0.5 - py) + 3 * abs(z + 1 - pz)
            if d < bd: best, bd = i, d
        start, pre = best, bd
    path = g.path(start, nxt)
    gxn, gyn = g.nodes[goal][0] + 0.5, g.nodes[goal][1] + 0.5
    post = math.hypot(gxn - gx, gyn - gy)
    return dict(goal=goal, start=start, path=path, pre=pre, post=post, dist=dist, nxt=nxt)


def along(pts, d):
    """the point d cells along the line, the heading there (radians, 0 north) and the rest of the line"""
    acc = 0.0
    for k in range(1, len(pts)):
        a, b = pts[k - 1], pts[k]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if acc + L >= d and L > 0:
            t = (d - acc) / L
            p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            return p, math.atan2(b[0] - a[0], -(b[1] - a[1])), [p] + pts[k:]
        acc += L
    return pts[-1], 0.0, [pts[-1]]
