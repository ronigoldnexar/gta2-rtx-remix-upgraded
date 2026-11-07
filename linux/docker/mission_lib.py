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

_FRAME0 = [None]
def frames_rendered():
    """Frames the renderer has drawn so far: its per-256-frame summaries (the
    'frame=' field of the mission line is not a counter)."""
    try:
        with open(D.LOG, "rb") as f: return 256 * f.read().count(b"frame times, avg/worst ms over 256 frames")
    except OSError:
        return 0
def mark(what):
    fr = frames_rendered()
    if _FRAME0[0] is None: _FRAME0[0] = fr
    gt = f" game={D.game_seconds(fr - _FRAME0[0]):.0f}s"   # game seconds since the first mark (1 frame = 1/30 game-second)
    with open(MARKS, "a") as f: f.write(f"{time.time():.3f} {what}{gt}\n")
    say("MARK", what + gt)

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
    """Blocks per game second: wall time is divided by the game speed."""
    return math.hypot(s1["x"] - s0["x"], s1["y"] - s0["y"]) / max(dt * D.SPEED, 0.1)

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

def arm_lives():
    ms = mission_state(); LIVES0[0] = ms["lives"] if ms else None

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

# the game's own "JOB COMPLETE!" / "JOB FAILED!" message keys per district
# (Downtown 1124/1125, Industrial file bil 3100/3730, Residential file ste 2999/2998)
COMPLETE_KEYS = {"1124", "3100", "2999"}
FAILED_KEYS = {"1125", "3730", "2998"}

LIVES0 = [None]   # lives when the current job started (a death costs one; JOB FAILED follows)
def outcome(money0):
    ms = mission_state()
    if not ms: return "unknown", ms
    if ms["msg"] in COMPLETE_KEYS or ms["money"] >= money0 + 10000: return "complete", ms
    if ms["msg"] in FAILED_KEYS: return "failed", ms
    if ms["health"] == 0 or ms["death"] != 0: return "dead", ms
    if LIVES0[0] is not None and ms["lives"] < LIVES0[0]:
        LIVES0[0] = ms["lives"]; return "dead", ms      # a life gone: he died; the job has failed with him
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
        if (x, y) in AVOID: return None
        return ("slope", g if g in (1, 2, 3) else 2)
    if not _lid(b) or g not in (1, 2, 3): return None
    above = _blk(world, x, y, level + 1)
    if above and _lid(above) and (_gtype(above) != 0 or any((above[i] & 1023) for i in range(4))):
        return None                                  # a solid block on top (an air-typed bare lid is a canopy)
    if (x, y) in AVOID: return None
    return ("flat", g)

COST = {1: 3.0, 2: 1.0, 3: 1.4}
CAR_COST = {1: 1.0, 2: 8.0, 3: 6.0}   # a car: roads cheap, a lot or a pavement only to get on or off them
# GMP arrows byte, in the face order left, right, up, down: bit 0 left (x-1), 1 right (x+1),
# 2 up (y-1), 3 down (y+1); bits 4-7 the red set (checked on the Downtown carriageway:
# rows 149-151 carry bit 0 and run west, rows 153-154 bit 1 and run east)
ARROW_BIT = {(-1, 0): 0x11, (1, 0): 0x22, (0, -1): 0x44, (0, 1): 0x88}
AVOID = set()      # cells the router must not step on (the other phones: standing on one answers it)

DONE_PHONES = set()   # (x,y) of phones whose job is complete: the game sets them dead, harmless to cross

def set_avoid_phones(world, keep=None):
    """every live phone cell of the district except the one at keep=(x,y)"""
    AVOID.clear()
    for p in world.db["phones"].values():
        if keep and abs(p["x"] - keep[0]) < 0.6 and abs(p["y"] - keep[1]) < 0.6: continue
        if any(abs(p["x"] - dx) < 0.6 and abs(p["y"] - dy) < 0.6 for dx, dy in DONE_PHONES): continue
        AVOID.add((int(p["x"]), int(p["y"])))
    say(f"router: avoiding {len(AVOID)} phone cells")

def step_off_phone(world, entry, dist=1.8):
    """a spot beside the answered phone that is flat at the phone's level and not
    another phone: away from the neighbour phone first, then sideways"""
    nb = [p for k, p in world.db["phones"].items() if 0.1 < math.hypot(p["x"] - entry["x"], p["y"] - entry["y"]) < 2.6]
    cands = []
    if nb:
        dx, dy = entry["x"] - nb[0]["x"], entry["y"] - nb[0]["y"]; n = math.hypot(dx, dy) or 1.0
        cands.append((dx / n, dy / n)); cands.append((-dy / n, dx / n)); cands.append((dy / n, -dx / n))
    cands += [(1, 0), (-1, 0), (0, 1), (0, -1), (0.71, 0.71), (-0.71, 0.71), (0.71, -0.71), (-0.71, -0.71)]
    lvl = top_level(world, entry["x"], entry["y"]) - 1
    others = [(p["x"], p["y"]) for p in world.db["phones"].values() if math.hypot(p["x"] - entry["x"], p["y"] - entry["y"]) > 0.1]
    best = None
    for ux, uy in cands:
        for d in (1.3, dist, dist + 1.0):
            x, y = entry["x"] + ux * d, entry["y"] + uy * d
            k = node_kind(world, int(x), int(y), lvl)
            if not k or k[0] != "flat": continue
            clear = min([math.hypot(x - ox, y - oy) for ox, oy in others] or [9.0])
            # the straight step must not cross another phone's cell
            crosses = any(abs(ox - (entry["x"] + ux * t)) < 0.6 and abs(oy - (entry["y"] + uy * t)) < 0.6
                          for ox, oy in others for t in (0.5, 1.0, 1.5, 2.0, 2.5) if t <= d)
            if crosses or clear < 1.0: continue
            score = clear - 0.1 * d
            if best is None or score > best[0]: best = (score, (x, y))
        if best and best[0] > 1.5: break
    return best[1] if best else (entry["x"] + 2.2, entry["y"])

def slope_high_dir(t):
    """unit step toward the high end of a slope block of type t (GTA2: up/down/
    left/right name the uphill direction on screen; verified on the Yakuza phone
    dais, types 3-4 rise toward the south)"""
    if 1 <= t <= 2 or 9 <= t <= 16 or t == 41: return (0, -1)
    if 3 <= t <= 4 or 17 <= t <= 24 or t == 42: return (0, 1)
    if 5 <= t <= 6 or 25 <= t <= 32 or t == 43: return (-1, 0)
    if 7 <= t <= 8 or 33 <= t <= 40 or t == 44: return (1, 0)
    return None

FACE_OF = {(-1, 0): 0, (1, 0): 1, (0, -1): 2, (0, 1): 3}      # GMP face order: left, right, top, bottom

def wall_between(world, x, y, L, dx, dy):
    """a side face (fence, railing, wall) between the flat cell (x,y,L) and its
    neighbour in direction (dx,dy): the block the body stands in is the one
    above the lid, at L+1, in either cell"""
    # a face blocks only with its wall bit (bit 10) set: a fence panel carries the
    # tile on both sides but the wall bit on one
    here = _blk(world, x, y, L + 1)
    if here and (here[FACE_OF[(dx, dy)]] & 0x400): return True
    there = _blk(world, x + dx, y + dy, L + 1)
    if there and (there[FACE_OF[(-dx, -dy)]] & 0x400): return True
    return False

def route3(world, sx, sy, sl, tx, ty, tl=None, kinds=(1, 2, 3), limit=200000, cost=None):
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
            if not here_slope and wall_between(world, x, y, L, dx, dy): continue
            moves = []   # (level, allowed kinds)
            if here_slope:
                if here_dir is None: continue
                # uphill: the top, the next piece of the same flight, or the low
                # piece of the next flight one level up (GTA2 stacks 26-degree
                # pairs: the Industrial Russian phone's stair is five such pairs)
                if (dx, dy) == here_dir: moves = [(L, ("flat", "slope")), (L + 1, ("slope",))]
                elif (dx, dy) == (-here_dir[0], -here_dir[1]): moves = [(L - 1, ("flat", "slope")), (L, ("slope",))]   # downhill
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
                c = d + ((cost or COST).get(nk[1], 2.0) if nk[0] == "flat" else 1.0)
                if (kinds == (1,) or cost is CAR_COST) and nk[0] == "flat" and nk[1] == 1:
                    # keep to the lanes: a road cell whose arrows exclude the way we enter it
                    # is the oncoming lane (head-on traffic wrecks a fragile mission car)
                    ab = _blk(world, nx, ny, nl)
                    ab = ab[5] if ab else 0
                    if ab & 0xFF and not (ab & ARROW_BIT.get((dx, dy), 0)): c += 2.5
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

def line_clear(world, p, q, L, kinds=(1, 2), half_width=0.42):
    """True when a car can drive straight from p to q at level L: every sample
    along the line (and 0.42 block either side of it) is on a cell of `kinds`
    with a lid and nothing built on it, and no wall face is crossed"""
    (px, py), (qx, qy) = p, q
    dx, dy = qx - px, qy - py; n = math.hypot(dx, dy)
    if n < 1e-6: return True
    ux, uy = dx / n, dy / n; lx, ly = -uy, ux
    steps = max(2, int(n / 0.2) + 1); prev = {}
    for k in range(steps + 1):
        t = n * k / steps
        for side in (0.0, half_width, -half_width):
            x = px + ux * t + lx * side; y = py + uy * t + ly * side
            cx, cy = int(math.floor(x)), int(math.floor(y))
            k2 = node_kind(world, cx, cy, L)
            if not (k2 and k2[0] == "flat" and k2[1] in kinds):
                k2 = node_kind(world, cx, cy, L + 1)
                if not (k2 and k2[0] == "flat" and k2[1] in kinds): return False
            last = prev.get(side)
            if last and last != (cx, cy):
                sx, sy = cx - last[0], cy - last[1]
                if abs(sx) + abs(sy) == 1 and wall_between(world, last[0], last[1], L, sx, sy): return False
            prev[side] = (cx, cy)
    return True

def straighten_los(world, path, kinds=(1, 2), half_width=0.42):
    """waypoints from a cell path: keep a cell only when the straight run to the
    next kept cell stays on drivable ground; the path's own level is used"""
    if len(path) < 3: return path
    out = [path[0]]; i = 0
    while i < len(path) - 1:
        j = len(path) - 1
        while j > i + 1:
            a, b = path[i], path[j]
            if a[2] == b[2] and line_clear(world, (a[0] + 0.5, a[1] + 0.5), (b[0] + 0.5, b[1] + 0.5), a[2], kinds, half_width): break
            j -= 1
        out.append(path[j]); i = j
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

VIEW_HOOK = [None]   # the session's set_view: the walker needs the classic view (direct keys)

def walk3(world, tx, ty, tl=None, tol=0.6, budget=300, kinds=(1, 2, 3)):
    """route (multi-level, pavements preferred) and cruise leg by leg; re-routes
    after a missed leg; returns the state. Walks in the classic view: the 3D
    orbit camera remaps the keys (Up walks where the camera looks, Left/Right
    turn a wanted heading through a lagging controller), so the heading-pulse
    steering that is calibrated in the classic view barely turns him there
    (pt4_wil11: 0.45 s Right pulses turned him 0.5 rad in three seconds and
    he walked away from the kerb). The 3D view comes back when the walk ends."""
    if VIEW_HOOK[0]: VIEW_HOOK[0]("classic")
    try: return _walk3(world, tx, ty, tl, tol, budget, kinds)
    finally:
        if VIEW_HOOK[0]: VIEW_HOOK[0]("third")

def _walk3(world, tx, ty, tl, tol, budget, kinds):
    t0 = time.time(); s = D.wait_state(); reroutes = 0; pinned = None; pins = 0
    while s and time.time() - t0 < budget:
        if math.hypot(tx - s["x"], ty - s["y"]) < tol and (tl is None or ped_level(s) == tl): return s
        path = route3(world, int(s["x"]), int(s["y"]), ped_level(s), int(tx), int(ty), tl, kinds)
        if AVOID and (len(path) < 2 or abs(path[-1][0] - int(tx)) + abs(path[-1][1] - int(ty)) > 2):
            # the phones can sit in a one-block walkway (the Zaibatsu rim): when
            # keeping off them leaves no route, cross them (a live phone only
            # holds him for a message)
            saved = set(AVOID); AVOID.clear()
            path2 = route3(world, int(s["x"]), int(s["y"]), ped_level(s), int(tx), int(ty), tl, kinds)
            AVOID.update(saved)
            if len(path2) > len(path): say("walk3: no route off the phones; crossing them"); path = path2
        # waypoints that never clip a wall or a railing (line of sight on walkable
        # ground, a body's half width), and no leg longer than 6 blocks so a
        # drift gets corrected before it meets a lamp post
        legs = []
        if len(path) > 1:
            pts = straighten_los(world, path, kinds, half_width=0.3)
            for a, b in zip(pts, pts[1:]):
                n = max(1, int(math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / 6.0)))
                for k in range(1, n + 1):
                    legs.append((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n, b[2]))
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
            gx, gy = (tx, ty) if last else (cx + 0.5, cy + 0.5)   # cells → centres (interpolated legs carry fractions)
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
        # pinned: two re-routes from the same spot (a body wedged in a wall corner,
        # pt4_wil10 at 81.9,25.2) - a reported developer warp a few cells down the path
        if s and pinned and math.hypot(s["x"] - pinned[0], s["y"] - pinned[1]) < 0.4:
            pins += 1
            if pins >= 2 and os.environ.get("WARP_OK", "1") == "1" and len(path) > 4:
                ahead = next((n for n in path[3:] if node_kind(world, *n) and node_kind(world, *n)[0] == "flat"), None)
                if ahead:
                    say(f"walk3: pinned at {s['x']:.1f},{s['y']:.1f} for {pins} re-routes; developer warp {ahead[0]}.5,{ahead[1]}.5 (reported)")
                    s = scene_warp(ahead[0] + 0.5, ahead[1] + 0.5, ahead[2], "pinned walker, a few cells down the path")
                    pins = 0
        else: pins = 0
        pinned = (s["x"], s["y"]) if s else None
    return s

SLOW_CAP = 3.0

def drive3(world, tx, ty, tol=2.0, budget=240, view_switch=None, slow=False):
    """wall-aware driving. Road-only route with lane preference, waypoints that
    never cut a corner (line of sight on drivable ground), a speed target that
    falls to a crawl before every turn and at the goal, Up never held while
    the heading error is over 40 degrees, a straight reverse when the car is
    pinned against something for a second, and a re-route after it."""
    t0 = time.time(); s = D.wait_state(); last = (s, time.time())
    vcap = SLOW_CAP if slow else 5.5   # SLOW_CAP: a script can lower it for a fragile mission car
    def legs_from(s):
        L = ped_level(s)
        path = route3(world, int(s["x"]), int(s["y"]), L, int(tx), int(ty), None, kinds=(1,), cost=CAR_COST)
        if not path or abs(path[-1][0] - int(tx)) + abs(path[-1][1] - int(ty)) > 2:
            # off the road (a lot, a ramp): roads plus the ground the car stands on,
            # before the anything-goes route that walks a car across pavements
            here = node_kind(world, int(s["x"]), int(s["y"]), L) or node_kind(world, int(s["x"]), int(s["y"]), L + 1)
            if here and here[1] != 1:
                path = route3(world, int(s["x"]), int(s["y"]), L, int(tx), int(ty), None, kinds=(1, here[1]), cost=CAR_COST)
        if not path or abs(path[-1][0] - int(tx)) + abs(path[-1][1] - int(ty)) > 2:
            path = route3(world, int(s["x"]), int(s["y"]), L, int(tx), int(ty), None, cost=CAR_COST)
        # the straight legs may only cross what the route itself stands on: a road-only
        # route gives road-only legs (pt4_wil7's cop car was wrecked against a wall after
        # a leg cut across a pavement); a lot or a field on the route admits those kinds
        onpath = {node_kind(world, *n)[1] for n in path if node_kind(world, *n)}
        kinds = tuple(k for k in (1, 2, 3) if k == 1 or k in onpath)
        cells = straighten_los(world, path, kinds, half_width=0.45)[1:] if len(path) > 1 else []
        lg = [(cx + 0.5, cy + 0.5) for cx, cy, _ in cells]
        if lg and math.hypot(lg[-1][0] - tx, lg[-1][1] - ty) > 0.6: lg.append((tx, ty))
        elif not lg: lg = [(tx, ty)]
        # the turn at each waypoint, for the braking lookahead
        turns = []
        for k in range(len(lg)):
            p0 = (s["x"], s["y"]) if k == 0 else lg[k - 1]
            if k + 1 < len(lg):
                v1 = (lg[k][0] - p0[0], lg[k][1] - p0[1]); v2 = (lg[k + 1][0] - lg[k][0], lg[k + 1][1] - lg[k][1])
                n1, n2 = math.hypot(*v1), math.hypot(*v2)
                turns.append(math.acos(max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))) if n1 > 1e-6 and n2 > 1e-6 else 0.0)
            else: turns.append(math.pi)          # the goal: stop there
        return lg, turns
    legs, turns = legs_from(s); i = 0; stall_t = None; stalls = 0; up = False; wedge_at = None
    say(f"drive3: {len(legs)} legs to {tx:.1f},{ty:.1f} (cap {vcap})")
    def keyup_all():
        xdo("keyup", "Up"); xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right")
    try:
        while s and s["driving"] and time.time() - t0 < budget and i < len(legs):
            gx, gy = legs[i]; final = i == len(legs) - 1
            d = math.hypot(gx - s["x"], gy - s["y"])
            if d < (tol if final else 1.4): i += 1; continue
            if not final:
                # passed it: the next waypoint is already nearer along the way
                nx, ny = legs[i + 1]
                if math.hypot(nx - s["x"], ny - s["y"]) < math.hypot(nx - gx, ny - gy) - 0.3: i += 1; continue
            hx, hy = heading(s); dx, dy = gx - s["x"], gy - s["y"]
            a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
            now = time.time(); v = speed_of(last[0], s, now - last[1]) if now - last[1] > 0.05 else 0.0; last = (s, now)
            if view_switch: view_switch(s)
            # distance along the path to the next real turn (or the goal)
            cd = d; k = i
            while k < len(legs) - 1 and turns[k] < 0.6:
                cd += math.hypot(legs[k + 1][0] - legs[k][0], legs[k + 1][1] - legs[k][1]); k += 1
            vt = vcap
            if cd < 4.0: vt = min(vt, 1.0 + cd * 0.55)
            if final and d < 3.0: vt = min(vt, 1.2)
            steer = "Right" if a > 0 else "Left"
            if abs(a) > 1.9 or (abs(a) > 0.9 and d < 2.2):
                # the waypoint is behind, or close and well off the nose (a parking lot,
                # a lot exit): a three-point turn. Reversing with the wheel the other way
                # swings the nose toward the target; then the forward branches take over.
                if up: xdo("keyup", "Up"); up = False
                if v > 1.0: hold("Down", 0.3); time.sleep(0.2)
                rkey = "Left" if a > 0 else "Right"
                xdo("keydown", rkey); xdo("keydown", "Down"); time.sleep(0.9); xdo("keyup", "Down"); xdo("keyup", rkey); time.sleep(0.15)
            elif abs(a) > 0.70:
                # a real turn: no throttle held; creep and steer in pulses, brake first when fast
                if up: xdo("keyup", "Up"); up = False
                if v > 1.5: hold("Down", 0.3)
                xdo("keydown", steer); xdo("keydown", "Up"); time.sleep(0.22); xdo("keyup", "Up"); time.sleep(0.12); xdo("keyup", steer)
            elif abs(a) > 0.22:
                if v > vt + 0.8:
                    if up: xdo("keyup", "Up"); up = False
                    hold("Down", 0.2)
                xdo("keydown", steer)
                if v < vt: xdo("keydown", "Up"); up = True
                time.sleep(min(0.3, 0.12 + abs(a) * 0.3)); xdo("keyup", steer)
            else:
                if v > vt + 0.8:
                    if up: xdo("keyup", "Up"); up = False
                    hold("Down", min(0.4, 0.12 + (v - vt) * 0.08))
                elif v < vt and not up: xdo("keydown", "Up"); up = True
                elif v >= vt and up: xdo("keyup", "Up"); up = False
                if abs(a) > 0.06:
                    xdo("keydown", steer); time.sleep(min(0.22, abs(a) * 0.5)); xdo("keyup", steer)
            time.sleep(0.12)
            s2 = D.wait_state()
            if not s2: break
            if s2.get("fire", 0) > 0:
                say(f"drive3: the car is burning ({s2['fire']} flames); out"); mark("the car is on fire: out and clear")
                keyup_all(); up = False
                s2 = flee_fire(world, s2)
                if not (s2 and s2["driving"]): return s2
                legs, turns = legs_from(s2); i = 0; s = s2; continue
            moved = math.hypot(s2["x"] - s["x"], s2["y"] - s["y"])
            wanted_motion = (up or abs(a) > 0.22)
            if wanted_motion and moved < 0.05:
                stall_t = stall_t or time.time()
                if time.time() - stall_t > 1.0:
                    stalls += 1; stall_t = None
                    keyup_all(); up = False
                    # stopped with the throttle on: traffic ahead (the usual case on a
                    # carriageway) or a wall. Wait a moment for traffic, then back off and
                    # pull out round it on the side with road, then re-route.
                    say(f"drive3: stopped with throttle at {s2['x']:.1f},{s2['y']:.1f} (stall {stalls}); waiting, then pulling out")
                    time.sleep(2.0); s3 = D.wait_state()
                    if s3 and math.hypot(s3["x"] - s2["x"], s3["y"] - s2["y"]) > 0.4:
                        s = s3; continue                      # the queue moved
                    # wedged in a traffic queue (two stalls within half a block): a borrowed
                    # car is abandoned for one past the jam; a mission car keeps trying
                    if stalls >= 2 and wedge_at is not None and math.hypot(s2["x"] - wedge_at[0], s2["y"] - wedge_at[1]) < 0.5:
                        if not slow:
                            say("drive3: wedged in traffic; out, past the jam on foot, another car"); mark("wedged in traffic: leaving the jam on foot")
                            hx2, hy2 = heading(s2); leave_car(); time.sleep(0.4)
                            cruise_to(s2["x"] + hx2 * 6.0, s2["y"] + hy2 * 6.0, tol=1.2, secs=8)
                            s2 = any_car2(world, budget=90)
                            if not (s2 and s2["driving"]): return s2
                            legs, turns = legs_from(s2); i = 0; s = s2; wedge_at = None; continue
                        hold("Down", 1.4); time.sleep(0.2)
                    wedge_at = (s2["x"], s2["y"])
                    hold("Down", 0.7); time.sleep(0.15)
                    hx2, hy2 = heading(s2)
                    lx, ly = -hy2, hx2                        # the car's left
                    def roadside(sign):
                        cx, cy = int(s2["x"] + lx * sign * 1.5 + hx2 * 1.5), int(s2["y"] + ly * sign * 1.5 + hy2 * 1.5)
                        return walkable(world.blocks, world.columns, cx, cy, ped_level(s2), (1,))
                    side = "Left" if roadside(1) or not roadside(-1) else "Right"
                    xdo("keydown", side); xdo("keydown", "Up"); time.sleep(0.9); xdo("keyup", side); time.sleep(0.5); xdo("keyup", "Up")
                    s2 = D.wait_state()
                    if stalls % 6 == 0 and not slow:
                        s2 = bail_out(world, s2)
                        if not (s2 and s2["driving"]): return s2
                    legs, turns = legs_from(s2); i = 0
            else:
                stall_t = None
            s = s2
    finally:
        keyup_all()
    hold("Down", 0.8)
    return D.wait_state()

def flee_fire(world, s):
    """the car is burning: leave it, run 7 blocks clear, wait out the blast,
    then another car"""
    cx, cy = s["x"], s["y"]; hx, hy = heading(s)
    xdo("keyup", "Up"); leave_car(); time.sleep(0.4)
    s = D.wait_state()
    ux, uy = (-hx, -hy)
    # run perpendicular if the way back is where the burning car stands
    cruise_to(s["x"] + ux * 7.0, s["y"] + uy * 7.0, tol=1.2, secs=7)
    time.sleep(8.0)
    s = D.wait_state()
    if s["parked"] and s["pd"] < 12 and math.hypot(s["px"] - cx, s["py"] - cy) > 2.5:
        s = enter_car3(world, s["px"], s["py"], budget=40)
        if s and s["driving"]: return s
    return any_car2(world, budget=90)

def bail_out(world, s):
    """leave the car, get 5 blocks clear for 7 s (an explosion), then re-enter
    it if it still stands, else any car"""
    cx, cy = s["x"], s["y"]; hx, hy = heading(s)
    say("drive3: bailing out of the car for a moment")
    mark("bail out: three wall hits, stepping clear")
    xdo("keyup", "Up"); leave_car(); time.sleep(0.5)
    cruise_to(cx - hx * 5.0, cy - hy * 5.0, tol=1.0, secs=6)
    time.sleep(2.0)
    s = D.wait_state()
    if s["parked"] and s["pd"] < 9:
        s = enter_car3(world, s["px"], s["py"], budget=40)
        if s and s["driving"]: return s
    return any_car2(world, budget=90)

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


# ================================================================ v3 (7 Nov, playthrough part 2)
# The game's objective arrows, read from the renderer's `view: arrows` line
# (slot:type:kind:x,y,z:obj for every slot with a target; positions are the
# arrow manager's 18.14 words). The base script keeps twelve gang/info-phone
# markers from level start; a mission's own arrow is any slot that differs
# from that baseline. That is the one reliable progress signal: a LOCATE box
# is passed when the mission arrow moves on (or goes), whatever the pager says.
ARROWS = re.compile(r"view: arrows((?: \d+:-?\d+:-?\d+:-?[\d.]+,-?[\d.]+,-?[\d.]+:[0-9A-F]{8}(?::[0-9A-F]{8},[0-9A-F]{8},[0-9A-F]{8})?)*)")
ARROW = re.compile(r" (\d+):(-?\d+):(-?\d+):(-?[\d.]+),(-?[\d.]+),(-?[\d.]+):([0-9A-F]{8})(?::([0-9A-F]{8}),([0-9A-F]{8}),([0-9A-F]{8}))?")
BASELINE = {}

def arrows():
    """{slot: (type, kind, x, y, z, obj)} from the last arrows line, or {}"""
    try:
        with open(D.LOG, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 40000)); tail = f.read().decode("latin-1")
    except OSError:
        return {}
    m = None
    for m in ARROWS.finditer(tail): pass
    if not m: return {}
    out = {}
    for a in ARROW.finditer(m.group(1)):
        out[int(a.group(1))] = (int(a.group(2)), int(a.group(3)), float(a.group(4)), float(a.group(5)), float(a.group(6)), a.group(7), a.group(8) or '', a.group(9) or '', a.group(10) or '')
    return out

def arrows_baseline():
    """remember the markers the base script keeps; call once at level start"""
    BASELINE.clear(); BASELINE.update(arrows()); say(f"arrows: baseline {len(BASELINE)} slots")

START = [None]   # (x, y) at level start: the tutorial's gifts (hint 1608, a car and a gun) get an arrow near it

def mission_arrows():
    """the slots that differ from the baseline: the current objective's arrow(s).
    An arrow within 8 blocks of the level start is the tutorial's (pt4_wil12 took
    the 1608 gift arrow at 156.5,142.5 for a job), never a mission's"""
    out = {}
    for k, v in arrows().items():
        if BASELINE.get(k) == v: continue
        if START[0] and math.hypot(v[2] - START[0][0], v[3] - START[0][1]) < 8.0: continue
        out[k] = v
    return out

def objective():
    """(x, y, z, kind, obj) of the mission arrow, or None when no mission arrow is up"""
    ma = mission_arrows()
    if not ma: return None
    k = max(ma)                       # the newest slot
    t, kind, x, y, z, obj = ma[k][:6]
    return (x, y, z, kind, obj)

def objective_key():
    o = objective()
    ma = mission_arrows()
    return None if o is None else (round(o[0], 1), round(o[1], 1), o[3], o[4], tuple(ma[max(ma)][6:]))

def wait_objective_change(key0, secs, money0=None):
    """True as soon as the mission arrow differs from key0 (moved on, or gone),
    or the money/outcome changes"""
    t0 = time.time()
    while time.time() - t0 < secs:
        if objective_key() != key0: return True
        ms = mission_state()
        if ms and (ms["msg"] in COMPLETE_KEYS or ms["msg"] in FAILED_KEYS or (money0 is not None and ms["money"] >= money0 + 5000)): return True
        time.sleep(0.3)
    return False

def inside_box(s, x, y, w, h):
    return abs(s["x"] - x) <= w / 2 - 0.04 and abs(s["y"] - y) <= h / 2 - 0.04

def settle_box(x, y, w, h, money0=None, secs=40, nudge=None, key0=None):
    """stand inside the LOCATE box (centre x,y, size w x h) until the mission
    arrow moves on from key0 (the arrow before the walk; the walk itself may
    have crossed the box); nudge is the caller's precise stepper (nudge_to)"""
    if key0 is None: key0 = objective_key()
    if objective_key() != key0:
        say(f"box {x},{y} ({w}x{h}): passed on the way"); return True
    t0 = time.time(); k = 0
    r = max(0.05, min(w, h) / 2 - 0.1)
    pts = [(0, 0), (r * 0.5, 0), (-r * 0.5, 0), (0, r * 0.5), (0, -r * 0.5), (r, r), (-r, -r), (r, -r), (-r, r)]
    while time.time() - t0 < secs:
        off = pts[k % len(pts)]; k += 1
        if nudge: nudge(x + off[0], y + off[1], tol=max(0.06, r * 0.4), tries=10)
        s = D.wait_state()
        inside = s and inside_box(s, x, y, w, h)
        if wait_objective_change(key0, 2.5 if inside else 0.6, money0):
            say(f"box {x},{y} ({w}x{h}): passed after {time.time()-t0:.0f}s"); return True
    say(f"box {x},{y} ({w}x{h}): not passed in {secs}s (last {s['x']:.2f},{s['y']:.2f} z {s['z']:.2f})")
    return False

def any_car(world, budget=150, within=14.0):
    """get into some car: the nearest parked car the renderer reports, else wait
    at the kerb for one that stops beside him (natural entry)"""
    t0 = time.time()
    while time.time() - t0 < budget:
        s = D.wait_state()
        if s["driving"]: return s
        if s["parked"] and s["pd"] < within:
            say(f"any_car: parked car at {s['px']:.1f},{s['py']:.1f} d={s['pd']:.1f}")
            s = enter_car3(world, s["px"], s["py"], budget=60)
            if s and s["driving"]: return s
        elif s["car"] and s["cd"] < 2.4:
            pts = []
            for _ in range(3):
                s = D.wait_state(); pts.append((s["cx"], s["cy"])); time.sleep(0.4)
            if max(math.hypot(p[0] - pts[0][0], p[1] - pts[0][1]) for p in pts) < 0.3:
                say(f"any_car: a car stopped beside him at {s['cx']:.1f},{s['cy']:.1f}")
                hold("Up", 0.2); tap("Return", 0.3); time.sleep(3.0)
                s = D.wait_state()
                if s["driving"]: return s
        time.sleep(0.6)
    return D.wait_state()


# ---------------------------------------------------------------- v3: kerb finding, warps, ramming
INI = "/tmp/wp/drive_c/Games/GTA2/gta2dx9.ini"
SCENE_KEY = ["F11"]   # the [devtools] scene key the run enabled (F10 is eaten every other press under Wine)

def nearest_kerb(world, s, radius=40):
    """the nearest pavement cell beside a road at street level"""
    sx, sy = int(s["x"]), int(s["y"]); best = None
    for r in range(1, radius):
        for dx in range(-r, r + 1):
            for dy in (-r, r):
                for (cx, cy) in ((sx + dx, sy + dy), (sx + dy, sy + dx)):
                    for lvl in (1, 2):
                        if walkable(world.blocks, world.columns, cx, cy, lvl, (2,)):
                            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                                if walkable(world.blocks, world.columns, nx, ny, lvl, (1,)):
                                    return (cx + 0.5, cy + 0.5, lvl)
    return None

def any_car2(world, budget=150):
    """a car by any honest means: a parked one nearby, else the nearest kerb
    and the first car that stops beside him"""
    s = D.wait_state()
    if s["driving"]: return s
    if s["parked"] and s["pd"] < 14:
        s = enter_car3(world, s["px"], s["py"], budget=60)
        if s and s["driving"]: return s
    k = nearest_kerb(world, s)
    if k:
        say(f"any_car2: to the kerb at {k[0]:.1f},{k[1]:.1f}")
        s = walk3(world, k[0], k[1], None, tol=0.5, budget=90)
    return any_car(world, budget=budget, within=14.0)

def devtools_lines():
    try:
        with open(D.LOG, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 60000)); tail = f.read().decode("latin-1")
    except OSError:
        return []
    return [l for l in tail.splitlines() if "devtools:" in l]

def scene_warp(x, y, level, why):
    """the developer scene warp (F10, [devtools] scene_xy re-read per press);
    only when the honest route failed, and always marked"""
    for _ in range(3):
        s = D.wait_state()
        if not s["driving"]: break
        tap("Return", 0.3); time.sleep(2.0)
    try:
        t = open(INI, encoding="latin-1").read()
        km = re.search(r"(?m)^scene_key=(\S+)", t)
        if km: SCENE_KEY[0] = km.group(1)
        else: say("scene_warp: no scene_key in the ini (run with INI_SED enabling [devtools]); the warp will be refused")
        t = re.sub(r"(?m)^scene_xy=.*$", f"scene_xy={x},{y},{level}", t)
        open(INI, "w", encoding="latin-1").write(t)
    except OSError as e:
        say("scene_warp: ini", e); return D.wait_state()
    s = D.wait_state()
    for attempt in range(4):
        n0 = len(devtools_lines())
        tap(SCENE_KEY[0], 0.3); time.sleep(2.5)
        new = devtools_lines()[n0:]
        s = D.wait_state()
        if new and "ignored" not in new[-1] and "refused" not in new[-1]: break
        say(f"warp attempt {attempt+1}: {new[-1].split('devtools:')[-1] if new else 'no devtools line'}")
        time.sleep(1.0)
    # the scene brings a car and pins him until Return; step out of it if the game put him in
    time.sleep(1.5); s = D.wait_state()
    if s["driving"]: tap("Return", 0.3); time.sleep(2.0); s = D.wait_state()
    mark(f"WARP to {x},{y},{level} ({why}) -> at {s['x']:.1f},{s['y']:.1f} z={s['z']:.2f}")
    return s

def top_level(world, x, y):
    """the level of the highest lid in the column (for a warp's level)"""
    best = None
    for lvl in range(0, 8):
        b = _blk(world, int(x), int(y), lvl)
        if b and _lid(b): best = lvl + 1
    return best or 2

def ram_target(world, money0, secs=240, view_switch=None):
    """wreck the car the mission arrow follows: drive at it at speed, back off,
    repeat until the outcome changes"""
    t0 = time.time(); hits = 0
    while time.time() - t0 < secs:
        o, ms = outcome(money0)
        if o != "running": return o
        tgt = objective()
        s = D.wait_state()
        if not s["driving"]:
            s = any_car2(world, budget=90)
            if not s["driving"]: continue
        if not tgt: time.sleep(1); continue
        d = math.hypot(tgt[0] - s["x"], tgt[1] - s["y"])
        if d > 6:
            # the car moves: aim a few seconds ahead of it, in short legs
            time.sleep(1.0); t2 = objective() or tgt
            vx, vy = (t2[0] - tgt[0]), (t2[1] - tgt[1])
            lead = min(3.0, d / 6.0)
            s = drive3(world, t2[0] + vx * lead, t2[1] + vy * lead, tol=3.0, budget=14, view_switch=view_switch, slow=False)
            continue
        # line up and charge
        hx, hy = heading(s); dx, dy = tgt[0] - s["x"], tgt[1] - s["y"]
        a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
        if abs(a) > 0.35:
            xdo("keydown", "Down"); xdo("keydown", "Left" if a > 0 else "Right"); time.sleep(0.7)
            xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right")
            continue
        # charge: Up held and re-aimed until the impact, then keep pushing into it
        xdo("keydown", "Up"); t1 = time.time(); last_d = d
        while time.time() - t1 < 4.0:
            s = D.wait_state(); tgt = objective()
            if not s["driving"] or not tgt: break
            if s.get("fire", 0) > 0: break
            hx, hy = heading(s); dx, dy = tgt[0] - s["x"], tgt[1] - s["y"]
            d = math.hypot(dx, dy); a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
            if abs(a) > 0.12:
                key = "Right" if a > 0 else "Left"; xdo("keydown", key); time.sleep(min(abs(a) * 0.4, 0.25)); xdo("keyup", key)
            if d < 1.3: time.sleep(1.2); break          # on it: push
            if abs(a) > 1.2: break                        # it got past us
            time.sleep(0.15)
        xdo("keyup", "Up")
        hits += 1; say(f"ram: charge {hits} ended at d={d:.1f}")
        s = D.wait_state()
        if s["driving"] and s.get("fire", 0) > 0:
            say("ram: my car burns; out"); mark("the car burns: out and clear")
            s = flee_fire(world, s); continue
        hold("Down", 0.7); time.sleep(0.2)
    return outcome(money0)[0]


def street_cell_near(world, x, y, radius=14):
    """the nearest road cell at street level (1 or 2) to a point"""
    cx0, cy0 = int(x), int(y); best = None
    for r in range(1, radius):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r: continue
                for lvl in (1, 2):
                    if walkable(world.blocks, world.columns, cx0 + dx, cy0 + dy, lvl, (1,)):
                        return (cx0 + dx + 0.5, cy0 + dy + 0.5, lvl)
    return None


def escape_route(world, s, dist=9):
    """waypoints for running clear of a blast: the nearest ring cell 7-10 blocks
    away that the router can actually reach from here in at most 1.6x the
    straight distance (walls, railings and drops respected), as line-of-sight
    legs; [] when nothing is reachable"""
    L = ped_level(s); sx, sy = int(s["x"]), int(s["y"]); best = None
    for r in (dist, dist - 2, dist + 1):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r: continue
                if not any(walkable(world.blocks, world.columns, sx + dx, sy + dy, lv, (1, 2, 3)) for lv in (L, L + 1, max(1, L - 1))): continue
                path = route3(world, sx, sy, L, sx + dx, sy + dy, None, limit=6000)
                if not path or (path[-1][0], path[-1][1]) != (sx + dx, sy + dy): continue
                if len(path) > r * 1.6 + 2: continue
                if best is None or len(path) < len(best): best = path
        if best: break
    if not best: return []
    return [(cx + 0.5, cy + 0.5) for cx, cy, _ in straighten_los(world, best, (1, 2, 3))[1:]]

def escape_point(world, x, y, level, dist=7):
    """a point `dist` blocks from (x,y) with open walkable ground all the way
    (for running clear of a timed charge): the first of eight directions"""
    best = None
    for k in range(8):
        a = k * math.pi / 4; dx, dy = math.cos(a), math.sin(a); ok = 0
        for d in range(1, dist + 1):
            cx, cy = int(x + dx * d), int(y + dy * d)
            if not any(walkable(world.blocks, world.columns, cx, cy, lv, (1, 2, 3)) for lv in (level, level + 1, level - 1) if lv >= 0): break
            ok = d
        if ok >= dist: return (x + dx * dist, y + dy * dist)
        if best is None or ok > best[0]: best = (ok, (x + dx * ok, y + dy * ok))
    return best[1] if best else (x, y - dist)
