#!/usr/bin/env python3
"""Plays GTA2 missions from the renderer's log and the decompiled scripts.

A mission is a plan (assets-src/missions/missions.json, built by
tools/missions_db.py from the decompiled .SCR files): the mission car and
where it stands, the places the script's arrow points at and the condition
it waits for at each (on foot, by car, in a given car, the horn, a crushed
car...). The runner answers the phone, then walks the plan: route on foot
with the map's streets (gmp.py), get into the mission car by walking to its
door and pressing Enter, drive by waypoints with a heading controller, sound
the horn, and watch the game's own state for the outcome: the 'view: mission'
log line (money, health, wanted level, the key of the last message the game
showed: 1124 = JOB COMPLETE!, 1125 = JOB FAILED!) and 'view: player'.

Keys: GTA2's default DirectInput bindings as the registry has them: arrows,
Ctrl fire, Return enter/exit, Space jump/handbrake, Z/X weapons, Tab special
(horn in a car)."""
import json, math, os, re, subprocess, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import gmp

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
MISSION = re.compile(r"view: mission money=(-?\d+) mult=(-?\d+) lives=(-?\d+) death=(-?\d+) wanted=(-?\d+) health=(-?\d+) cardmg=(-?\d+) carmodel=(-?\d+) msg=(\S*) frame=(-?\d+)")
GAME_DIR = "/tmp/wp/drive_c/Games/GTA2"
MARKS = "/out/marks.txt"

def mark(what):
    with open(MARKS, "a") as f: f.write(f"{time.time():.3f} {what}\n")
    say("MARK", what)

def mission_state():
    """The last 'view: mission' line, or None."""
    try:
        with open(D.LOG, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 20000)); tail = f.read().decode("latin-1")
    except OSError:
        return None
    m = None
    for m in MISSION.finditer(tail): pass
    if not m: return None
    g = m.groups()
    return dict(money=int(g[0]), mult=int(g[1]), lives=int(g[2]), death=int(g[3]), wanted=int(g[4]),
                health=int(g[5]), cardmg=int(g[6]), carmodel=int(g[7]), msg=g[8], frame=int(g[9]))

def message_log():
    """Every (frame, msg key) change in the log so far, oldest first."""
    out, last = [], None
    try:
        for line in open(D.LOG, encoding="latin-1"):
            m = MISSION.search(line)
            if m and m.group(9) != last:
                last = m.group(9); out.append((int(m.group(10)), last))
    except OSError:
        pass
    return out

def walkable(blocks, columns, x, y, level, kinds=(1, 2, 3)):
    """ground of a kind at this level, and not a slope: slopes are stairs and
    ramps up to terraces and bridges the street-level router cannot get back
    down from, so the walker keeps to the flat"""
    if not (0 <= x < gmp.W and 0 <= y < gmp.H): return False
    g = gmp.ground(blocks, columns, x, y, level)
    if g not in kinds: return False
    blk = gmp.block_at(blocks, columns, x, y, level)
    return bool(blk) and (blk[6] >> 2) == 0

def route_cells(blocks, columns, sx, sy, tx, ty, level, kinds=(1, 2, 3)):
    """BFS over walkable cells at one level, to the reachable cell nearest (tx,ty)"""
    from collections import deque
    start = (sx, sy); seen = {start: None}; q = deque([start]); best = start; bestd = abs(tx - sx) + abs(ty - sy)
    while q:
        c = q.popleft(); d = abs(c[0] - tx) + abs(c[1] - ty)
        if d < bestd: best, bestd = c, d
        if d == 0: break
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c[0] + dx, c[1] + dy)
            if n in seen: continue
            if walkable(blocks, columns, n[0], n[1], level, kinds): seen[n] = c; q.append(n)
    path = []; c = best
    while c: path.append(c); c = seen[c]
    return path[::-1]

class World:
    def __init__(self, district="wil"):
        self.district = district
        self.blocks, self.columns = gmp.load(f"{GAME_DIR}/data/{district}.gmp")
        self.db = json.load(open("/work/missions.json"))[district]

    def level(self, s):
        """the level whose lid he stands on: his z is that lid's height; a
        fraction means a slope, which counts as the level it climbs to"""
        return max(1, int(round(s["z"])) - 1)

    def route(self, s, tx, ty, roads_only=False):
        """cell path from the player's cell to (tx,ty); roads only for a car.
        If his own cell is not walkable at his level (a terrace, a stair top),
        the route starts at the nearest walkable cell at street level, which the
        unstick moves of the walker will reach."""
        sx, sy = int(s["x"]), int(s["y"])
        kinds = (1,) if roads_only else (1, 2, 3)
        for lvl in (self.level(s), 1, 2):
            if walkable(self.blocks, self.columns, sx, sy, lvl, (1, 2, 3)):
                path = route_cells(self.blocks, self.columns, sx, sy, int(tx), int(ty), lvl, kinds)
                if roads_only and not (path and abs(path[-1][0] - int(tx)) + abs(path[-1][1] - int(ty)) <= 2):
                    path = route_cells(self.blocks, self.columns, sx, sy, int(tx), int(ty), lvl)
                if path: return path
        # nearest walkable street-level cell around him, then from there
        for r in range(1, 6):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if walkable(self.blocks, self.columns, sx + dx, sy + dy, 1):
                        path = route_cells(self.blocks, self.columns, sx + dx, sy + dy, int(tx), int(ty), 1, kinds)
                        return [(sx, sy)] + path if path else []
        return []

# ---------------------------------------------------------------- on foot

def walk_to(world, tx, ty, tol=0.6, budget=240):
    """route and walk; re-routes when a leg is not reached; unsticks after
    repeated failures at the same spot (traffic at a crossing, a kerb, a post)"""
    t0 = time.time(); s = D.wait_state(); fails = 0; last_fail = None
    while s and time.time() - t0 < budget:
        if math.hypot(tx - s["x"], ty - s["y"]) < tol: return s
        path = world.route(s, tx, ty)
        legs = D.straighten(path)[1:] if len(path) > 1 else []
        if not legs:
            s = D.goto(tx, ty, tol=tol, limit=8); continue
        progressed = False
        for cx, cy in legs:
            gx, gy = cx + 0.5, cy + 0.5
            s = D.goto(gx, gy, tol=0.9, limit=14)
            if not s or s["driving"]: return s
            if math.hypot(gx - s["x"], gy - s["y"]) > 1.5:
                here = (round(s["x"]), round(s["y"]))
                fails = fails + 1 if here == last_fail else 1; last_fail = here
                say(f"walk: leg to {cx},{cy} not reached ({s['x']:.1f},{s['y']:.1f}); re-routing (fail {fails})")
                if fails >= 2:
                    # something in the way: wait for traffic, back off (a long
                    # reverse also walks back down a staircase), turn, step
                    time.sleep(1.5); hold("Down", 0.6 if fails == 2 else 2.0)
                    hold("Left" if fails % 2 else "Right", 0.55); hold("Up", 0.9)
                    s = D.wait_state()
                break
            progressed = True; fails = 0
        if progressed and legs:
            continue
    return s

# ---------------------------------------------------------------- cars

def heading(s):
    if s["driving"] and s["driven"]: return s["chx"], s["chy"]
    return s["fx"], s["fy"]

def enter_car_at(world, cx, cy, budget=90):
    """walk to the car parked at (cx,cy) and get in; True when driving"""
    t0 = time.time()
    s = walk_to(world, cx, cy, tol=1.6, budget=budget)
    tries = 0
    while s and time.time() - t0 < budget:
        if s["driving"]: return s
        # the game walks him to the nearest car on Enter; stand close to this one
        d = math.hypot(cx - s["x"], cy - s["y"])
        if d > 1.8: s = D.goto(cx, cy, tol=1.4, limit=6)
        # a ped that has stood still ignores Enter (state 7): a step first
        hold("Up", 0.25); time.sleep(0.3)
        tap("Return", 0.3); time.sleep(2.5)
        s = D.wait_state(); tries += 1
        if s["driving"]: return s
        if tries % 3 == 0:
            # another side of the car
            ang = tries * 1.2
            s = D.goto(cx + 0.9 * math.cos(ang), cy + 0.9 * math.sin(ang), tol=0.5, limit=6)
    return s

def speed_of(s0, s1, dt):
    return math.hypot(s1["x"] - s0["x"], s1["y"] - s0["y"]) / max(dt, 0.1)

def car_legs(world, s, tx, ty):
    """cell centres to drive through: straight runs merged, every corner kept"""
    path = world.route(s, tx, ty, roads_only=True)
    cells = D.straighten(path)[1:] if len(path) > 1 else []
    legs = [(cx + 0.5, cy + 0.5) for cx, cy in cells]
    legs.append((tx, ty))
    return legs

def drive_to(world, tx, ty, tol=2.0, budget=180, view_switch=None):
    """drive by waypoints to (tx,ty): a heading controller on the half-second
    samples, slow into corners, reverse out of walls, re-route after a stall"""
    t0 = time.time(); s = D.wait_state(); last = (s, time.time())
    legs = car_legs(world, s, tx, ty)
    say(f"drive: {len(legs)} legs to {tx:.1f},{ty:.1f}")
    i = 0; stall = 0; stalls = 0
    while s and s["driving"] and time.time() - t0 < budget and i < len(legs):
        gx, gy = legs[i]
        final = i == len(legs) - 1
        d = math.hypot(gx - s["x"], gy - s["y"])
        if d < (tol if final else 1.6):
            i += 1; continue
        # skip a leg we have already passed (the next one is closer and ahead)
        if not final and i + 1 < len(legs):
            nx, ny = legs[i + 1]
            if math.hypot(nx - s["x"], ny - s["y"]) < d: i += 1; continue
        hx, hy = heading(s)
        dx, dy = gx - s["x"], gy - s["y"]
        a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)   # + = target to the right (y south)
        now = time.time(); v = speed_of(last[0], s, now - last[1]); last = (s, now)
        if view_switch: view_switch(s)
        steer = "Right" if a > 0 else "Left"
        if abs(a) > 2.0:
            # facing away: back up with the wheel turned toward the target
            xdo("keydown", "Down"); xdo("keydown", "Left" if a > 0 else "Right"); time.sleep(0.8)
            xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right")
        elif abs(a) > 0.9:
            # a corner: creep and turn
            if v > 2.5: hold("Down", 0.3)
            xdo("keydown", steer); xdo("keydown", "Up"); time.sleep(0.3); xdo("keyup", "Up"); time.sleep(0.1); xdo("keyup", steer)
        else:
            turn = min(abs(a) * 0.4, 0.3)
            near = d < 3.0 or (not final and i + 1 < len(legs) and math.hypot(legs[i+1][0]-gx, legs[i+1][1]-gy) < 3)
            go = 0.25 if (near or v > 6.0) else 0.45
            xdo("keydown", "Up")
            if abs(a) > 0.1: xdo("keydown", steer); time.sleep(turn); xdo("keyup", steer)
            time.sleep(max(0.05, go - (turn if abs(a) > 0.1 else 0)))
            xdo("keyup", "Up")
            if final and d < 4 and v > 3: hold("Down", 0.3)
        time.sleep(0.2)
        s2 = D.wait_state()
        if s2 and math.hypot(s2["x"] - s["x"], s2["y"] - s["y"]) < 0.08 and abs(a) <= 2.0:
            stall += 1
            if stall >= 3:
                stalls += 1; stall = 0
                say(f"drive: stalled at {s2['x']:.1f},{s2['y']:.1f}; reversing and re-routing")
                xdo("keydown", "Down"); xdo("keydown", "Left" if stalls % 2 else "Right"); time.sleep(1.3)
                xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right"); time.sleep(0.4)
                s2 = D.wait_state(); legs = car_legs(world, s2, tx, ty); i = 0
        else:
            stall = 0
        s = s2
    hold("Down", 0.8)
    return D.wait_state()

def horn(times=3):
    for _ in range(times):
        for key in ("Tab", "space"):
            xdo("keydown", key); time.sleep(0.6); xdo("keyup", key); time.sleep(0.3)

def leave_car():
    tap("Return", 0.3); time.sleep(2.0); return D.wait_state()

# ---------------------------------------------------------------- phones and outcome

def answer_phone(world, phone, budget=300):
    """walk onto the phone; the mission starts when the game shows its title message"""
    before = mission_state()
    m0 = before["msg"] if before else ""
    s = walk_to(world, phone["x"], phone["y"], tol=0.45, budget=budget)
    t0 = time.time()
    while time.time() - t0 < 12:
        ms = mission_state()
        if ms and ms["msg"] != m0 and ms["msg"] not in ("", "svdone"):
            say(f"phone answered: message {ms['msg']}"); return True, ms
        # stand on it, jiggle
        s = D.goto(phone["x"] + 0.2, phone["y"], tol=0.25, limit=3); time.sleep(1.0)
        s = D.goto(phone["x"] - 0.2, phone["y"], tol=0.25, limit=3); time.sleep(1.0)
    return False, mission_state()

def outcome(money0):
    ms = mission_state()
    if not ms: return "unknown", ms
    if ms["msg"] == "1124" or ms["money"] >= money0 + 10000: return "complete", ms
    if ms["msg"] == "1125": return "failed", ms
    if ms["health"] == 0 or ms["death"] != 0: return "dead", ms
    return "running", ms

def wait_outcome(money0, seconds, poll=1.0):
    t0 = time.time()
    while time.time() - t0 < seconds:
        o, ms = outcome(money0)
        if o != "running": return o, ms
        time.sleep(poll)
    return "running", mission_state()

def shot(name):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99",
                    "-frames:v", "1", f"/out/m_{name}.png"])


# ================================================================ v2 (6 Nov, playthrough)
# A multi-level router that knows slopes (stairs and ramps join one lid level
# to the next), prefers pavements to roads, and a walker that keeps Up held
# and steers from the half-second samples instead of stop-turn-step.
import heapq

def _blk(world, x, y, level):
    if not (0 <= x < gmp.W and 0 <= y < gmp.H): return None
    return gmp.block_at(world.blocks, world.columns, x, y, level)

def _lid(b): return b[4] & 1023 if b else 0
def _slope(b): return (b[6] >> 2) if b else 0
def _gtype(b): return (b[6] & 3) if b else 0

def node_kind(world, x, y, level):
    """what a ped can stand on at (x,y,level): ('flat', ground) for a lid with
    nothing solid on top, ('slope', ground) for a slope block, else None"""
    b = _blk(world, x, y, level)
    if not b: return None
    g = _gtype(b); s = _slope(b)
    if 1 <= s <= 44:
        return ("slope", g if g in (1, 2, 3) else 2)
    if not _lid(b) or g not in (1, 2, 3): return None
    above = _blk(world, x, y, level + 1)
    if above and _lid(above): return None            # a full block on top
    return ("flat", g)

COST = {1: 3.0, 2: 1.0, 3: 1.4}

def slope_high_dir(t):
    """unit step toward the high end of a slope block of type t (GTA2: up/down/
    left/right name the uphill direction on screen; verified on the Yakuza phone
    dais, types 3-4 rise toward the south)"""
    if 1 <= t <= 2 or 9 <= t <= 16 or t == 41: return (0, -1)
    if 3 <= t <= 4 or 17 <= t <= 24 or t == 42: return (0, 1)
    if 5 <= t <= 6 or 25 <= t <= 32 or t == 43: return (-1, 0)
    if 7 <= t <= 8 or 33 <= t <= 40 or t == 44: return (1, 0)
    return None

def route3(world, sx, sy, sl, tx, ty, tl=None, kinds=(1, 2, 3), limit=200000):
    """Dijkstra over (x,y,level). tl None = any level with something to stand
    on at (tx,ty). A slope block stored at level L joins level L-1 (its low
    end) to level L (its high end) along its own axis only; a flat cell at L
    enters a slope at L+1 uphill or a slope at L downhill. Returns
    [(x,y,level), ...] or []."""
    start = None
    for cand in ((sx, sy, sl), (sx, sy, sl + 1)):
        if node_kind(world, *cand): start = cand; break
    if start is None:
        best = None
        for r in range(1, 4):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    for L in (sl, sl + 1):
                        k = node_kind(world, sx + dx, sy + dy, L)
                        if k and k[0] == "flat":
                            if best is None or abs(dx) + abs(dy) < abs(best[0] - sx) + abs(best[1] - sy):
                                best = (sx + dx, sy + dy, L)
            if best: break
        if not best: return []
        start = best
    def is_goal(n):
        return n[0] == tx and n[1] == ty and (tl is None or n[2] == tl)
    dist = {start: 0.0}; prev = {start: None}
    pq = [(0.0, start)]; seen = 0; best = (abs(tx - sx) + abs(ty - sy), start)
    while pq and seen < limit:
        d, n = heapq.heappop(pq); seen += 1
        if d > dist.get(n, 1e18): continue
        h = abs(tx - n[0]) + abs(ty - n[1])
        if h < best[0]: best = (h, n)
        if is_goal(n): best = (0, n); break
        x, y, L = n
        kind = node_kind(world, x, y, L)
        if not kind: continue
        here_slope = kind[0] == "slope"
        here_dir = slope_high_dir(_slope(_blk(world, x, y, L))) if here_slope else None
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            moves = []   # (level, allowed kinds)
            if here_slope:
                if here_dir is None: continue
                if (dx, dy) == here_dir: moves = [(L, ("flat", "slope"))]            # uphill: the top, or the next piece
                elif (dx, dy) == (-here_dir[0], -here_dir[1]): moves = [(L - 1, ("flat",)), (L, ("slope",))]   # downhill
                else: continue                                                        # sideways off a slope: a wall
            else:
                moves = [(L, ("flat",)), (L + 1, ("slope",)), (L, ("slope",))]
            for nl, allowed in moves:
                nk = node_kind(world, nx, ny, nl)
                if not nk or nk[0] not in allowed: continue
                if nk[0] == "slope":
                    sd = slope_high_dir(_slope(_blk(world, nx, ny, nl)))
                    if sd is None: continue
                    if not here_slope:
                        if nl == L + 1 and sd != (dx, dy): continue          # entering at the low end, going uphill
                        if nl == L and sd != (-dx, -dy): continue            # entering at the high end, going downhill
                    elif sd != here_dir: continue
                elif nk[1] not in kinds: continue
                c = d + (COST.get(nk[1], 2.0) if nk[0] == "flat" else 1.0)
                m = (nx, ny, nl)
                if c < dist.get(m, 1e18):
                    dist[m] = c; prev[m] = n; heapq.heappush(pq, (c, m))
    n = best[1]; path = []
    while n: path.append(n); n = prev[n]
    return path[::-1]

def straighten3(path):
    if len(path) < 3: return path
    out = [path[0]]
    for i in range(1, len(path) - 1):
        a, b, c = path[i - 1], path[i], path[i + 1]
        if (b[0] - a[0], b[1] - a[1], b[2] - a[2]) != (c[0] - b[0], c[1] - b[1], c[2] - b[2]) or b[2] != a[2]:
            out.append(b)
    out.append(path[-1])
    return out

def ped_level(s):
    return max(0, int(round(s["z"])) - 1)

def cruise_to(tx, ty, tol=0.6, secs=30, stop=True):
    """walk with Up held, steering from the samples; returns (state, reached)"""
    t0 = time.time(); best = 1e9; last_gain = time.time(); n = 0
    xdo("keydown", "Up")
    try:
        while time.time() - t0 < secs:
            s = D.wait_state()
            if not s: break
            if s["driving"]: return s, False
            d = math.hypot(tx - s["x"], ty - s["y"])
            if d < tol: return s, True
            if d < best - 0.12: best = d; last_gain = time.time()
            if time.time() - last_gain > 3.0:
                n += 1; say(f"cruise: stuck {d:.1f} from {tx:.1f},{ty:.1f}; unsticking {n}")
                xdo("keyup", "Up"); hold("Down", 0.6); hold("Right" if n % 2 else "Left", 0.4); hold("Up", 0.5)
                xdo("keydown", "Up"); last_gain = time.time(); best = 1e9
                if n >= 4: return s, False
                continue
            a = D.angle_to(s, tx, ty)
            if abs(a) > 0.12:
                key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
                xdo("keydown", key); time.sleep(min(abs(a) / max(D.rate, 2.0), 0.35)); xdo("keyup", key)
            time.sleep(0.15)
    finally:
        if stop: xdo("keyup", "Up")
    return D.wait_state(), False

def walk3(world, tx, ty, tl=None, tol=0.6, budget=300, kinds=(1, 2, 3)):
    """route (multi-level, pavements preferred) and cruise leg by leg; re-routes
    after a missed leg; returns the state"""
    t0 = time.time(); s = D.wait_state(); reroutes = 0
    while s and time.time() - t0 < budget:
        if math.hypot(tx - s["x"], ty - s["y"]) < tol and (tl is None or ped_level(s) == tl): return s
        path = route3(world, int(s["x"]), int(s["y"]), ped_level(s), int(tx), int(ty), tl, kinds)
        legs = straighten3(path)[1:] if len(path) > 1 else []
        say(f"walk3: {len(path)} cells, {len(legs)} legs from {s['x']:.1f},{s['y']:.1f} L{ped_level(s)} to {tx},{ty}" + (f" L{tl}" if tl is not None else ""))
        if not legs:
            s, ok = cruise_to(tx, ty, tol=tol, secs=12); 
            if ok: return s
            reroutes += 1
            if reroutes > 3: return s
            continue
        missed = False
        xdo("keydown", "Up")
        for i, (cx, cy, cl) in enumerate(legs):
            last = i == len(legs) - 1
            gx, gy = (tx, ty) if last else (cx + 0.5, cy + 0.5)
            s, ok = cruise_to(gx, gy, tol=(tol if last else 0.75), secs=max(8, 3 + 1.2 * 2), stop=False)
            # a long leg: allow the time its length needs
            if not ok and s:
                dd = math.hypot(gx - s["x"], gy - s["y"])
                if dd > 1.6:
                    s, ok = cruise_to(gx, gy, tol=(tol if last else 0.75), secs=min(60, 4 + dd / 1.5), stop=False)
            if not ok:
                missed = True; break
            if time.time() - t0 > budget: break
        xdo("keyup", "Up")
        if not missed: return D.wait_state()
        reroutes += 1
        say(f"walk3: re-routing ({reroutes})")
        if reroutes >= 12: break
        s = D.wait_state()
    return s

def drive3(world, tx, ty, tol=2.0, budget=240, view_switch=None, slow=False):
    """drive by road waypoints with Up held: steer from the samples, brake for
    corners, back out when stalled, re-route after a stall"""
    t0 = time.time(); s = D.wait_state(); last = (s, time.time())
    def legs_from(s):
        path = route3(world, int(s["x"]), int(s["y"]), ped_level(s), int(tx), int(ty), None, kinds=(1,))
        if not path or abs(path[-1][0] - int(tx)) + abs(path[-1][1] - int(ty)) > 2:
            path = route3(world, int(s["x"]), int(s["y"]), ped_level(s), int(tx), int(ty), None)
        cells = straighten3(path)[1:] if len(path) > 1 else []
        lg = [(cx + 0.5, cy + 0.5) for cx, cy, _ in cells]
        lg.append((tx, ty)); return lg
    legs = legs_from(s); i = 0; stall = 0; stalls = 0
    say(f"drive3: {len(legs)} legs to {tx:.1f},{ty:.1f}")
    xdo("keydown", "Up"); up = True
    try:
        while s and s["driving"] and time.time() - t0 < budget and i < len(legs):
            gx, gy = legs[i]; final = i == len(legs) - 1
            d = math.hypot(gx - s["x"], gy - s["y"])
            if d < (tol if final else 1.8): i += 1; continue
            if not final and i + 1 < len(legs):
                nx, ny = legs[i + 1]
                if math.hypot(nx - s["x"], ny - s["y"]) < d - 0.5: i += 1; continue
            hx, hy = heading(s); dx, dy = gx - s["x"], gy - s["y"]
            a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
            now = time.time(); v = speed_of(last[0], s, now - last[1]); last = (s, now)
            if view_switch: view_switch(s)
            steer = "Right" if a > 0 else "Left"
            nextd = math.hypot(legs[i + 1][0] - gx, legs[i + 1][1] - gy) if i + 1 < len(legs) else 99
            if abs(a) > 2.2:
                if up: xdo("keyup", "Up"); up = False
                xdo("keydown", "Down"); xdo("keydown", "Left" if a > 0 else "Right"); time.sleep(0.9)
                xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right")
            elif abs(a) > 0.8:
                if up: xdo("keyup", "Up"); up = False
                if v > 3.0: hold("Down", 0.35)
                xdo("keydown", steer); xdo("keydown", "Up"); time.sleep(0.35); xdo("keyup", "Up"); xdo("keyup", steer)
            else:
                want_slow = slow or d < 3.0 or nextd < 4.0 or (final and d < 6)
                if v > (4.5 if want_slow else 9.0):
                    if up: xdo("keyup", "Up"); up = False
                    hold("Down", 0.25)
                elif not up: xdo("keydown", "Up"); up = True
                if abs(a) > 0.08:
                    xdo("keydown", steer); time.sleep(min(abs(a) * 0.45, 0.3)); xdo("keyup", steer)
            time.sleep(0.2)
            s2 = D.wait_state()
            if s2 and v < 0.4 and math.hypot(s2["x"] - s["x"], s2["y"] - s["y"]) < 0.08 and abs(a) <= 2.2:
                stall += 1
                if stall >= 4:
                    stalls += 1; stall = 0
                    say(f"drive3: stalled at {s2['x']:.1f},{s2['y']:.1f}; backing out ({stalls})")
                    if up: xdo("keyup", "Up"); up = False
                    xdo("keydown", "Down"); xdo("keydown", "Left" if stalls % 2 else "Right"); time.sleep(1.4)
                    xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right"); time.sleep(0.3)
                    s2 = D.wait_state(); legs = legs_from(s2); i = 0
            else:
                stall = 0
            s = s2
    finally:
        xdo("keyup", "Up"); xdo("keyup", "Left"); xdo("keyup", "Right")
    hold("Down", 0.9)
    return D.wait_state()

def enter_car3(world, cx, cy, budget=120):
    """walk to the car's cell and get in; tries each side; True when driving"""
    t0 = time.time()
    s = walk3(world, cx, cy, tol=1.5, budget=budget)
    tries = 0
    while s and time.time() - t0 < budget:
        if s["driving"]: return s
        d = math.hypot(cx - s["x"], cy - s["y"])
        if d > 1.6:
            s, _ = cruise_to(cx, cy, tol=1.3, secs=8)
        hold("Up", 0.25); time.sleep(0.3)
        tap("Return", 0.3); time.sleep(2.8)
        s = D.wait_state(); tries += 1
        if s["driving"]: return s
        ang = tries * 1.57
        cruise_to(cx + 1.0 * math.cos(ang), cy + 1.0 * math.sin(ang), tol=0.45, secs=8)
    return s
