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
MISSION = re.compile(r"view: mission money=(-?\d+) mult=(-?\d+) lives=(-?\d+) death=(-?\d+) wanted=(-?\d+) health=(-?\d+) cardmg=(-?\d+) carmodel=(-?\d+) msg=(\S*) frame=(-?\d+)(?: weapon=(\S+?)\((-?\d+)\) ammo=(-?\d+))?(?: carhp=(-?\d+) carfire=(-?\d+) tcarhp=(-?\d+) tcarfire=(-?\d+) tcar=(-?[\d.]+),(-?[\d.]+))?")
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
    # cardmg: the car's damage word (+0x74, 0..32000; a byte read of it wrapped before
    # PLAYTHROUGH-7). carhp = 32000 - damage: the car burns from 16000 damage on (carfire
    # 1, 2 from 25000) and then loses a point a frame by itself, so a burning car has
    # carhp / 30 game seconds left before it explodes. tcar*: the mission's target car
    # (the kind-3 arrow's vehicle), -1 when there is none
    return dict(money=int(g[0]), mult=int(g[1]), lives=int(g[2]), death=int(g[3]), wanted=int(g[4]),
                health=int(g[5]), cardmg=int(g[6]), carmodel=int(g[7]), msg=g[8], frame=int(g[9]),
                weapon=g[10] or "none", wid=int(g[11] or 0), ammo=int(g[12] or 0),
                carhp=int(g[13]) if g[13] else -1, carfire=int(g[14]) if g[14] else -1,
                tcarhp=int(g[15]) if g[15] else -1, tcarfire=int(g[16]) if g[16] else -1,
                tcar=(float(g[17]), float(g[18])) if g[17] else None)

CAR_HP_FIRE = 16000   # carhp at which the game sets a car alight (damage 16000)
def car_condition():
    """(carhp, carfire) of the player's car from the newest mission line, (-1, -1) on foot"""
    ms = mission_state() or {}
    return ms.get("carhp", -1), ms.get("carfire", -1)

def car_burning(ms=None):
    ms = ms or mission_state() or {}
    return ms.get("carfire", -1) > 0

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

LEAVE_WAIT = [2.0]   # a timed job shortens it (WHEELER-DEALING: eight exits and entries on the clock)
def leave_car():
    tap("Return", 0.3); time.sleep(LEAVE_WAIT[0]); return D.wait_state()

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
        if (x, y) in AVOID or (x, y) in BLOCKED: return None
        return ("slope", g if g in (1, 2, 3) else 2)
    if not _lid(b) or g not in (1, 2, 3): return None
    above = _blk(world, x, y, level + 1)
    if above and _lid(above) and (_gtype(above) != 0 or any((above[i] & 1023) for i in range(4))):
        return None                                  # a solid block on top (an air-typed bare lid is a canopy)
    if (x, y) in AVOID or (x, y) in BLOCKED: return None
    return ("flat", g)

COST = {1: 3.0, 2: 1.0, 3: 1.4}
CAR_COST = {1: 1.0, 2: 8.0, 3: 6.0}   # a car: roads cheap, a lot or a pavement only to get on or off them
# GMP arrows byte, in the face order left, right, up, down: bit 0 left (x-1), 1 right (x+1),
# 2 up (y-1), 3 down (y+1); bits 4-7 the red set (checked on the Downtown carriageway:
# rows 149-151 carry bit 0 and run west, rows 153-154 bit 1 and run east)
ARROW_BIT = {(-1, 0): 0x11, (1, 0): 0x22, (0, -1): 0x44, (0, 1): 0x88}
BLOCKED = set()    # cells the map calls walkable that are not (a runner fills it per district, with evidence)
CAR_AVOID = set()  # cells a car stalled against again and again (drive3): the car router keeps off them
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

EDGE_COST = 0.6   # PLAYTHROUGH-8: a car route pays for a road cell beside a wall or a drop
_EDGE = {}
def edge_cell(world, x, y, L):
    """1 when the road cell (x,y,L) has a wall face or no ground (a building, a deck's
    railing, a drop) beside it, else 0: the car router keeps to the middle of a deck or a
    wide road (pt8_ze2d scraped the west railing of the level-3 deck at 245.1,100.5 four
    times, -4000 carhp; pt7_bil9's Z-Type lost 5000 on a kerb pole)"""
    k = (world.district if hasattr(world, "district") else "", x, y, L)
    if k not in _EDGE:
        e = 0
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if wall_between(world, x, y, L, dx, dy) or not (node_kind(world, x + dx, y + dy, L) or node_kind(world, x + dx, y + dy, L + 1) or node_kind(world, x + dx, y + dy, L - 1)):
                e = 1; break
        _EDGE[k] = e
    return _EDGE[k]

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
                if CAR_AVOID and cost and cost.get(1) == 1.0 and (nx, ny) in CAR_AVOID: continue   # a car pinned there before
                c = d + ((cost or COST).get(nk[1], 2.0) if nk[0] == "flat" else (1.0 if not (cost and cost.get(1) == 1.0) else cost.get(nk[1], 2.0) + 0.5))
                # (a car pays a ramp's ground cost: pt6_ste2's rigged Pickup was routed off
                # the Residential carriageway down a grass ramp into a walled field, 15 stalls)
                if (kinds == (1,) or (cost and cost.get(1) == 1.0)) and nk[0] == "flat" and nk[1] == 1:
                    # keep to the lanes: a road cell whose arrows exclude the way we enter it
                    # is the oncoming lane (head-on traffic wrecks a fragile mission car)
                    ab = _blk(world, nx, ny, nl)
                    ab = ab[5] if ab else 0
                    if ab & 0xFF and not (ab & ARROW_BIT.get((dx, dy), 0)): c += LANE_COST
                    if EDGE_COST: c += EDGE_COST * edge_cell(world, nx, ny, nl)
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
    """walk with Up held, steering from the samples; returns (state, reached).
    Always in the classic view (the steering pulses are calibrated there)"""
    ensure_view("classic")
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
            if time.time() - last_gain > (1.6 if RACE[0] else 3.0) / D.SPEED:
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
CUR_VIEW = [None]    # the view the session's set_view last selected
# GTA2_DIRECT_KEYS=1 (gamerun/grun.sh turns nav_map=0 on in the run's ini with it): the
# renderer leaves the arrows to the game in the 3D views too, so Up walks where the
# ped faces and Left/Right turn him exactly as in the classic view. The walker, the
# nudges and the gun then run in the chase view (WALK_VIEW) and every frame of the
# session, the JOB COMPLETE one included, is a 3D one. Without it (nav_map=1, the
# player's default) the keys are camera relative there and the walker needs classic.
DIRECT_KEYS = os.environ.get("GTA2_DIRECT_KEYS", "0") == "1"
WALK_VIEW = ["third"]
def foot_view():
    """the view the on-foot steering runs in"""
    return WALK_VIEW[0] if DIRECT_KEYS else "classic"

def ensure_view(name):
    """every on-foot move (walk3, cruise_to, the nudges) runs in the classic view and
    every drive in a 3D view. pt6_ze2a: enter_car3's door approaches ran in the chase
    view after walk3 had handed it back, wandered ten blocks off and lost 69 s of
    WHEELER-DEALING's 180 at the first car. Now the walker leaves the view classic
    and drive3 takes the chase view itself, so a walk-then-drive costs one V press.
    With DIRECT_KEYS the classic request means foot_view() (the chase view)"""
    if name == "classic": name = foot_view()
    if VIEW_HOOK[0] and CUR_VIEW[0] != name: VIEW_HOOK[0](name)

def walk3(world, tx, ty, tl=None, tol=0.6, budget=300, kinds=(1, 2, 3)):
    """route (multi-level, pavements preferred) and cruise leg by leg; re-routes
    after a missed leg; returns the state. Walks in the classic view: the 3D
    orbit camera remaps the keys (Up walks where the camera looks, Left/Right
    turn a wanted heading through a lagging controller), so the heading-pulse
    steering that is calibrated in the classic view barely turns him there
    (pt4_wil11: 0.45 s Right pulses turned him 0.5 rad in three seconds and
    he walked away from the kerb). The 3D view comes back when the walk ends."""
    ensure_view("classic")
    return _walk3(world, tx, ty, tl, tol, budget, kinds)

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
FAST_CAP = 5.5
RACE = [False]       # a timed job (WHEELER-DEALING): turns taken rolling at RACE_TURN_V
RACE_TURN_V = 2.6
LANE_COST = 2.5               # per road cell entered against its arrows
CORNER_V = (1.0, 0.55)        # speed target near a turn: v0 + k * distance to it
# A timed job (WHEELER-DEALING) lowers the lane cost and raises the corner speed:
# pt6_ze2b drove dealer 1's 85 blocks at 1.3-1.6 blocks/s, round a block to keep
# to its lane and crawling into every corner of Downtown's grid

def back_toward(s, gx, gy, secs=0.9):
    """PLAYTHROUGH-8: reverse off an obstacle with the wheel turned so the nose swings toward
    the next waypoint (pt8_bil1's Z-Type, heading south a block west of the road at
    76.1,214.5, reversed straight five times and drove back into the same corner)"""
    hx, hy = heading(s); dx, dy = gx - s["x"], gy - s["y"]
    a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
    rkey = ("Left" if a > 0 else "Right") if abs(a) > 0.15 else None
    if rkey: xdo("keydown", rkey)
    hold("Down", secs)
    if rkey: xdo("keyup", rkey)

def drive3(world, tx, ty, tol=2.0, budget=240, view_switch=None, slow=False, precious=False):
    """wall-aware driving. Road-only route with lane preference, waypoints that
    never cut a corner (line of sight on drivable ground), a speed target that
    falls to a crawl before every turn and at the goal, Up never held while
    the heading error is over 40 degrees, a straight reverse when the car is
    pinned against something for a second, and a re-route after it."""
    if CUR_VIEW[0] == "classic": ensure_view("third")      # driving is recorded in the 3D views
    t0 = time.time(); s = D.wait_state(); last = (s, time.time())
    vcap = SLOW_CAP if slow else FAST_CAP   # SLOW_CAP: a script can lower it for a fragile mission car; FAST_CAP: a timed job raises it
    def legs_from(s):
        L = ped_level(s)
        path = route3(world, int(s["x"]), int(s["y"]), L, int(tx), int(ty), None, kinds=(1,), cost=CAR_COST)
        if not path or abs(path[-1][0] - int(tx)) + abs(path[-1][1] - int(ty)) > 2:
            # off the road (a lot, a ramp): roads plus the ground the car stands on,
            # before the anything-goes route that walks a car across pavements
            here = node_kind(world, int(s["x"]), int(s["y"]), L) or node_kind(world, int(s["x"]), int(s["y"]), L + 1)
            if here and here[1] != 1:
                # off the road (a lot, a lawn): the ground it stands on only to reach the road.
                # With CAR_COST the lawn was cheap enough to cut across fields and down grass
                # ramps (pt6_ste5/6: the rigged Pickup parked on grass at 24,44.5 was routed
                # through the walled field at 63-83 x 24-31, stalls, wrecked)
                off = dict(CAR_COST); off[here[1]] = 30.0
                path = route3(world, int(s["x"]), int(s["y"]), L, int(tx), int(ty), None, kinds=(1, here[1]), cost=off)
        if not path or abs(path[-1][0] - int(tx)) + abs(path[-1][1] - int(ty)) > 2:
            path = route3(world, int(s["x"]), int(s["y"]), L, int(tx), int(ty), None, cost=CAR_COST)
        if (not path or abs(path[-1][0] - int(tx)) + abs(path[-1][1] - int(ty)) > 2) and CAR_AVOID:
            # PLAYTHROUGH-8: the avoid list can wall the car in (pt8_bil6: the alley it stood in
            # was on it) and the fallback below is a straight line through everything
            saved = set(CAR_AVOID); CAR_AVOID.clear()
            path = route3(world, int(s["x"]), int(s["y"]), L, int(tx), int(ty), None, kinds=(1,), cost=CAR_COST) or path
            CAR_AVOID.update(saved)
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
    last_hp = [-1]; burn_said = [False]; pins = []; hp_hist = []
    say(f"drive3: {len(legs)} legs to {tx:.1f},{ty:.1f} (cap {vcap})")
    def keyup_all():
        xdo("keyup", "Up"); xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right")
    try:
        while s and s["driving"] and time.time() - t0 < budget and i < len(legs):
            gx, gy = legs[i]; final = i == len(legs) - 1
            d = math.hypot(gx - s["x"], gy - s["y"])
            # a corner waypoint is taken close (0.8): taken at 1.4 the car turned early and
            # the diagonal to the next waypoint cut a ramp off the road (pt6_ste2 at 62,24)
            if d < (tol if final else (0.8 if turns[i] > 0.6 else 1.4)): i += 1; continue
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
            if cd < (8.0 if RACE[0] else 4.0): vt = min(vt, CORNER_V[0] + cd * CORNER_V[1])
            if final and d < 3.0: vt = min(vt, 2.2 if RACE[0] else 1.2)   # PLAYTHROUGH-8: a timed job's last 3 blocks at 2.2 (1.2: ~2 s per dealer)
            steer = "Right" if a > 0 else "Left"
            if abs(a) > 1.9 or (abs(a) > 0.9 and d < 2.2):
                # the waypoint is behind, or close and well off the nose (a parking lot,
                # a lot exit): a three-point turn. Reversing with the wheel the other way
                # swings the nose toward the target; then the forward branches take over.
                if up: xdo("keyup", "Up"); up = False
                if v > 1.0: hold("Down", 0.3); time.sleep(0.2)
                rkey = "Left" if a > 0 else "Right"
                xdo("keydown", rkey); xdo("keydown", "Down"); time.sleep(0.9); xdo("keyup", "Down"); xdo("keyup", rkey); time.sleep(0.15)
            elif abs(a) > 0.70 and RACE[0] and d > 1.2:
                # a timed job: take the turn rolling, the wheel held, throttle kept below the
                # turn speed, a short brake only when it comes in fast
                if v > RACE_TURN_V + 1.0:
                    if up: xdo("keyup", "Up"); up = False
                    hold("Down", min(0.35, 0.1 + (v - RACE_TURN_V) * 0.06))
                xdo("keydown", steer)
                if v < RACE_TURN_V: xdo("keydown", "Up"); up = True
                elif up: xdo("keyup", "Up"); up = False
                time.sleep(0.2); xdo("keyup", steer)
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
            # the car's condition from the game (carhp = 32000 - damage, carfire): a hard hit
            # is logged, a damaged mission car is driven slower, a burning car is left in
            # time. A burning car loses a point a frame, so it has carhp/30 game seconds
            ms2 = mission_state() or {}
            hp, cf = ms2.get("carhp", -1), ms2.get("carfire", -1)
            if hp >= 0:
                if last_hp[0] >= 0 and last_hp[0] - hp > 600 and cf <= 0:
                    say(f"drive3: hit: carhp {last_hp[0]} -> {hp} at {s2['x']:.1f},{s2['y']:.1f}")
                last_hp[0] = hp
                hp_hist.append((time.time(), hp, s2["x"], s2["y"])); del hp_hist[:-12]
                old = [h for h in hp_hist if time.time() - h[0] > 1.2 / D.SPEED]
                # (burning or not: pt7_bil9's Z-Type, alight, lost 6000 against a wall at 130,110)
                if old and old[-1][1] - hp > 2500 + (30 * 1.2 if cf > 0 else 0) and math.hypot(old[-1][2] - s2["x"], old[-1][3] - s2["y"]) < 1.0:
                    # losing carhp fast on the spot (pt7_bil7: 1000 every 0.3 s at 173,35 and
                    # 156,61 until it burned, pressed against something or under fire): back out
                    # at once, keep the cells ahead off the route, go round
                    say(f"drive3: carhp {old[-1][1]} -> {hp} in a second on the spot at {s2['x']:.1f},{s2['y']:.1f}: backing out")
                    keyup_all(); up = False
                    hx4, hy4 = heading(s2)
                    for k4 in (0.8, 1.4): CAR_AVOID.add((int(s2["x"] + hx4 * k4), int(s2["y"] + hy4 * k4)))
                    hold("Down", 1.0); time.sleep(0.1)
                    hp_hist.clear(); s2 = D.wait_state()
                    legs, turns = legs_from(s2); i = 0; s = s2; continue
                if precious and ms2.get("wanted", 0) > 0 and hp >= CARE_HP and vcap < WANTED_CAP:
                    vcap = WANTED_CAP; say(f"drive3: wanted (level {ms2['wanted']}): cap {vcap} while carhp {hp} allows")
                if precious and hp < CARE_HP and vcap > CARE_CAP:
                    vcap = CARE_CAP; say(f"drive3: carhp {hp}: the mission car is fragile now; cap {vcap}")
            burning = cf > 0 or s2.get("fire", 0) > 0
            if burning:
                left = (hp / 100.0) if hp >= 0 else 0.0   # PLAYTHROUGH-8: measured ~100 a game second once alight (pt8_bil11: 15969 -> 5894 in 102 s), not one a frame
                togo = sum(math.hypot(legs[k + 1][0] - legs[k][0], legs[k + 1][1] - legs[k][1]) for k in range(i, len(legs) - 1)) + math.hypot(legs[i][0] - s2["x"], legs[i][1] - s2["y"])
                eta = togo / 1.6 + 6.0
                if precious and KEEP_BURNING[0] and left > eta + BURN_MARGIN:
                    if not burn_said[0]:
                        say(f"drive3: the car burns (carfire {cf}, carhp {hp}: {left:.0f} s left), {togo:.0f} blocks to go (~{eta:.0f} s): on")
                        mark(f"the mission car burns: {left:.0f} s left, {togo:.0f} blocks to go, driving on"); burn_said[0] = True
                else:
                    say(f"drive3: the car is burning (carfire {cf}, carhp {hp}: {left:.0f} s left; flames {s2.get('fire', 0)}); out")
                    mark(f"the car is on fire (carhp {hp}): out and clear")
                    keyup_all(); up = False
                    if precious: s2 = bail_clear(world, s2); return s2
                    s2 = flee_fire(world, s2)
                    if not (s2 and s2["driving"]): return s2
                    legs, turns = legs_from(s2); i = 0; s = s2; last_hp[0] = -1; continue
            moved = math.hypot(s2["x"] - s["x"], s2["y"] - s["y"])
            wanted_motion = (up or abs(a) > 0.22)
            if (precious or not RACE[0]) and hp >= 0 and len(hp_hist) >= 2:   # any car but a timed race: borrowed cars burned on the long Industrial drives (pt8_bil5/6)
                # PLAYTHROUGH-8: a mission car pressed against something loses a few hundred a
                # sample without moving (pt7_bil9's Z-Type: 4500 in 7 s against the railing at
                # 23.5,223.4, 5000 in a second at a gantry pole at 135.9,149.5, 5000 against a
                # wall at 130.5,110: the old guard wanted 2500 in 1.2 s and the stall branch then
                # pushed it on with the wheel turned). Any 450 lost within 0.8 game seconds on the
                # spot: off the throttle, straight back, the cells ahead off the route, re-route
                rec = [h for h in hp_hist if time.time() - h[0] <= 0.8 / D.SPEED]
                if rec and rec[0][1] - hp > 450 and math.hypot(rec[0][2] - s2["x"], rec[0][3] - s2["y"]) < 0.6 and cf <= 0:
                    say(f"drive3: car pressed at {s2['x']:.1f},{s2['y']:.1f} (carhp {rec[0][1]} -> {hp}): straight back, round it")
                    keyup_all(); up = False
                    hx5, hy5 = heading(s2)
                    for k5 in (0.8, 1.4): CAR_AVOID.add((int(s2["x"] + hx5 * k5), int(s2["y"] + hy5 * k5)))
                    back_toward(s2, gx, gy, 0.9); time.sleep(0.15); hp_hist.clear(); stall_t = None
                    s2 = D.wait_state(); legs, turns = legs_from(s2); i = 0; s = s2; continue
            if wanted_motion and moved < 0.05:
                stall_t = stall_t or time.time()
                if time.time() - stall_t > 1.0 / D.SPEED:
                    stalls += 1; stall_t = None
                    keyup_all(); up = False
                    # pinned: the same spot again and again (pt7_ze2a hammered a wall at
                    # 212.7,65.2 ten times; every hit costs carhp). The cell ahead goes to the
                    # car router's avoid set and the leg is re-routed; at the fifth such stall
                    # the drive gives up and the caller walks or swaps
                    pins.append((s2["x"], s2["y"]))
                    near = [p for p in pins if math.hypot(p[0] - s2["x"], p[1] - s2["y"]) < 1.2]
                    if len(near) >= 3:
                        hx3, hy3 = heading(s2)
                        for k3 in (0.8, 1.4):
                            CAR_AVOID.add((int(s2["x"] + hx3 * k3), int(s2["y"] + hy3 * k3)))
                        if len(near) >= 5:
                            say(f"drive3: pinned at {s2['x']:.1f},{s2['y']:.1f} for {len(near)} stalls: giving up this drive")
                            mark(f"drive pinned at {s2['x']:.1f},{s2['y']:.1f}: giving up")
                            if not precious: BAD_CARS.append((s2["x"], s2["y"]))   # PLAYTHROUGH-8: pt8_bil1 re-took the same pinned car at 147.3,107.1 four times
                            hold("Down", 0.8); return D.wait_state()
                        say(f"drive3: pinned at {s2['x']:.1f},{s2['y']:.1f} ({len(near)} stalls): the cells ahead are off the car route now")
                    if precious and not RACE[0]:
                        # PLAYTHROUGH-8: a mission car never pulls out with the throttle into
                        # what stopped it: a short wait for traffic, then straight back, re-route
                        say(f"drive3: mission car stopped at {s2['x']:.1f},{s2['y']:.1f} (stall {stalls}): straight back, re-route")
                        time.sleep(0.8 if ms2.get("wanted", 0) == 0 else 0.2); s3 = D.wait_state()
                        if s3 and math.hypot(s3["x"] - s2["x"], s3["y"] - s2["y"]) > 0.4: s = s3; continue
                        back_toward(s2, gx, gy, 0.9); time.sleep(0.15); hp_hist.clear()
                        s2 = D.wait_state(); legs, turns = legs_from(s2); i = 0; s = s2; continue
                    # stopped with the throttle on: traffic ahead (the usual case on a
                    # carriageway) or a wall. Wait a moment for traffic, then back off and
                    # pull out round it on the side with road, then re-route.
                    say(f"drive3: stopped with throttle at {s2['x']:.1f},{s2['y']:.1f} (stall {stalls}); waiting, then pulling out")
                    # wanted: no waiting about (a cop pulls him out of a standing car: pt7_ste4)
                    time.sleep(0.3 if (ms2.get("wanted", 0) > 0) else (0.6 if RACE[0] else 2.0)); s3 = D.wait_state()   # PLAYTHROUGH-8: a timed job waits 0.6 s (pt7_ze2n: 8 s at one stall)
                    if s3 and math.hypot(s3["x"] - s2["x"], s3["y"] - s2["y"]) > 0.4:
                        s = s3; continue                      # the queue moved
                    # wedged in a traffic queue (two stalls within half a block): a borrowed
                    # car is abandoned for one past the jam; a mission car keeps trying
                    if stalls >= 2 and wedge_at is not None and math.hypot(s2["x"] - wedge_at[0], s2["y"] - wedge_at[1]) < 0.5:
                        if RACE[0]:
                            # PLAYTHROUGH-8: a timed job keeps its car (pt8_ze2d left it at 245.1,100.5,
                            # walked past "the jam", found no car and walked back to the same one: 25 s)
                            say("drive3: wedged (timed job): back off toward the route, re-route")
                            back_toward(s2, gx, gy, 0.8); time.sleep(0.1); hp_hist.clear()
                            s2 = D.wait_state(); legs, turns = legs_from(s2); i = 0; s = s2; wedge_at = None; continue
                        if not slow:
                            say("drive3: wedged in traffic; out, past the jam on foot, another car"); mark("wedged in traffic: leaving the jam on foot")
                            hx2, hy2 = heading(s2); leave_car(); time.sleep(0.4)
                            cruise_to(s2["x"] + hx2 * 6.0, s2["y"] + hy2 * 6.0, tol=1.2, secs=8)
                            s2 = any_car2(world, budget=90)
                            if not (s2 and s2["driving"]): return s2
                            legs, turns = legs_from(s2); i = 0; s = s2; wedge_at = None; continue
                        hold("Down", 1.4); time.sleep(0.2)
                    wedge_at = (s2["x"], s2["y"])
                    if RACE[0]:
                        # a timed job: back off with the nose swung toward the route, no pull-out
                        # with the throttle into what stopped it
                        back_toward(s2, gx, gy, 0.7); time.sleep(0.1)
                        s2 = D.wait_state(); legs, turns = legs_from(s2); i = 0; s = s2; continue
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
    # stop: the handbrake for a mission car (Down brakes and then reverses: pt7_ste2's
    # Pickup rolled back out of the barricade block, 2016 -> 2017, and the bomb went off
    # outside it), the old brake-and-reverse otherwise
    if precious: hold("space", 0.8)
    elif RACE[0]: hold("space", 0.6)        # a timed job: the handbrake, no reverse (Down 0.8 rolls it back a block)
    else: hold("Down", 0.8)
    return D.wait_state()

CARE_HP = 22000       # a mission car below this carhp (damage 10000) is driven at CARE_CAP
CARE_CAP = 2.0
WANTED_CAP = 3.2      # a mission car with the police after it, while carhp >= CARE_HP: a crawl gets
                      # it stopped and the player pulled out and arrested (pt7_ste4, 6155)
KEEP_BURNING = [True]  # a burning mission car is driven on while carhp/30 s outlasts the way left
BURN_MARGIN = 20.0

def bail_clear(world, s):
    """out of a burning mission car and clear of its blast; the caller decides what next"""
    hx, hy = heading(s)
    xdo("keyup", "Up"); leave_car(); time.sleep(0.4)
    s = D.wait_state()
    cruise_to(s["x"] - hx * 7.0, s["y"] - hy * 7.0, tol=1.2, secs=7)
    return D.wait_state()

def flee_fire(world, s):
    """the car is burning: leave it, run 7 blocks clear, wait out the blast,
    then another car"""
    cx, cy = s["x"], s["y"]; hx, hy = heading(s)
    BAD_CARS.append((cx, cy))
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

BAD_CARS = []        # (x, y) of cars found burning on entry: never taken again (pt7_ze2b re-entered its burning car six times)
def bad_car(x, y):
    return any(math.hypot(x - bx, y - by) < 3.0 for bx, by in BAD_CARS)

def check_entered(s):
    """just got in: a burning car (carfire) is left at once and remembered"""
    if not (s and s["driving"]): return s
    time.sleep(0.6)
    ms = mission_state() or {}
    if ms.get("carfire", -1) > 0:
        say(f"enter: this car burns (carhp {ms.get('carhp')}); out, and never this one again")
        mark(f"entered a burning car at {s['x']:.1f},{s['y']:.1f}: out")
        BAD_CARS.append((s["x"], s["y"]))
        s = bail_clear(world_ref[0], s) if world_ref[0] else leave_car()
    return s
world_ref = [None]

def enter_car3(world, cx, cy, budget=120):
    """walk to the car's cell and get in; tries each side; True when driving"""
    world_ref[0] = world
    if bad_car(cx, cy): say(f"enter_car3: the car at {cx:.1f},{cy:.1f} burned before; not that one"); return D.wait_state()
    return check_entered(_enter_car3(world, cx, cy, budget))

def _enter_car3(world, cx, cy, budget=120):
    t0 = time.time()
    s = walk3(world, cx, cy, tol=1.5, budget=budget)
    tries = 0
    while s and time.time() - t0 < budget:
        if s["driving"]: return s
        d = math.hypot(cx - s["x"], cy - s["y"])
        if d > 1.6:
            s, _ = cruise_to(cx, cy, tol=1.3, secs=8)
        hold("Up", 0.25); time.sleep(0.3)
        tap("Return", 0.3)
        for k_e in range(20):                     # poll instead of a flat 2.8 s (a timed job enters eight times)
            time.sleep(0.25); s = D.wait_state()
            if s["driving"]: break
            if k_e >= 11 and s.get("state") not in (2, 3, 6): break   # not getting in: try another side
        tries += 1
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

POLICE_MODELS = {12, 52, 54, 17, 34}   # cop car, SWAT van, tank, fire truck, ambulance (vehicle +0x84)
def any_car(world, budget=150, within=14.0):
    """get into some car: the nearest parked car the renderer reports, else wait
    at the kerb for one that stops beside him (natural entry)"""
    t0 = time.time()
    while time.time() - t0 < budget:
        s = D.wait_state()
        if s["driving"]: return s
        if s["parked"] and s["pd"] < within and not bad_car(s["px"], s["py"]):
            say(f"any_car: parked car at {s['px']:.1f},{s['py']:.1f} d={s['pd']:.1f}")
            s = enter_car3(world, s["px"], s["py"], budget=60)
            if s and s["driving"]: return s
        elif s["car"] and s["cd"] < 2.4 and s.get("cmodel", -1) in POLICE_MODELS:
            # a police car stopping beside him is the police (pt7_bil5 took one, the wanted
            # level rose and every car after it was rammed to burning within a minute)
            time.sleep(0.6); continue
        elif s["car"] and s["cd"] < 2.4 and not bad_car(s["cx"], s["cy"]):
            pts = []
            for _ in range(3):
                s = D.wait_state(); pts.append((s["cx"], s["cy"])); time.sleep(0.4)
            if max(math.hypot(p[0] - pts[0][0], p[1] - pts[0][1]) for p in pts) < 0.3:
                say(f"any_car: a car stopped beside him at {s['cx']:.1f},{s['cy']:.1f}")
                hold("Up", 0.2); tap("Return", 0.3); time.sleep(3.0)
                s = check_entered(D.wait_state())
                if s["driving"]:
                    if (mission_state() or {}).get("wanted", 0) > 0:
                        # seen taking it: pull away at once. pt6_le2d sat 4 s in a taken
                        # taxi at wanted level 1 (the view change before the drive), a cop
                        # pulled him out and he was arrested to the station 50 blocks off
                        say("any_car: wanted for the car; pulling away"); hold("Up", 1.5)
                    return D.wait_state()
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
    if s["parked"] and s["pd"] < 30 and not bad_car(s["px"], s["py"]):
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

def van_motion(hist, span=1.2):
    """(ux, uy, speed) of the marked car from its last `span` game seconds of
    arrow samples; speed 0 when it has not moved"""
    if len(hist) < 2: return 0.0, 0.0, 0.0
    t1, x1, y1 = hist[-1]; t0, x0, y0 = hist[-2]
    for t0, x0, y0 in reversed(hist[:-1]):
        if (t1 - t0) * D.SPEED >= span: break
    dt = max((t1 - t0) * D.SPEED, 0.05)
    dx, dy = x1 - x0, y1 - y0; n = math.hypot(dx, dy)
    if n < 0.25: return 0.0, 0.0, 0.0
    return dx / n, dy / n, n / dt

def ram_car(world):
    """a car for the ramming: the nearest parked one within 45 blocks (the one
    he arrived in, usually; the router walks him there), else the kerb wait.
    pt4_wil14 stood 8 min at a kerb 16 blocks from its own car, pt4_wil16 was
    run over there"""
    s = D.wait_state()
    if s["driving"]: return s
    if s["parked"] and s["pd"] < 45:
        say(f"ram: the parked car at {s['px']:.1f},{s['py']:.1f} d={s['pd']:.1f}")
        s = enter_car3(world, s["px"], s["py"], budget=120)
        if s and s["driving"]: return s
    return any_car2(world, budget=90)

def face_target(s, tx, ty, pulses=3):
    """swing the nose toward (tx,ty) with reverse-and-steer pulses (drive3's
    three-point turn); True once within 0.4 rad"""
    for _ in range(pulses):
        hx, hy = heading(s); dx, dy = tx - s["x"], ty - s["y"]
        a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
        if abs(a) < 0.4: return True
        rkey = "Left" if a > 0 else "Right"; fkey = "Right" if a > 0 else "Left"
        xdo("keydown", rkey); xdo("keydown", "Down"); time.sleep(0.8); xdo("keyup", "Down"); xdo("keyup", rkey)
        xdo("keydown", fkey); xdo("keydown", "Up"); time.sleep(0.35); xdo("keyup", "Up"); xdo("keyup", fkey); time.sleep(0.25)
        s = D.wait_state()
        if not s["driving"]: return False
    return False

def objective_slot():
    ma = mission_arrows()
    return max(ma) if ma else None

def arrow_track(since_off, slot, kind):
    """(wall seconds, x, y) of every `view: arrows` sample since the log offset
    whose slot `slot` has kind `kind`: the marked car's dense track"""
    out = []
    try:
        with open(D.LOG, "rb") as f:
            f.seek(since_off); data = f.read().decode("latin-1")
    except OSError:
        return out
    for m in ARROWS.finditer(data):
        ls = data.rfind("\n", 0, m.start()) + 1
        ts = data[ls + 1:ls + 13]
        try: h, mi, sec = ts.split(":"); tw = int(h) * 3600 + int(mi) * 60 + float(sec)
        except ValueError: continue
        for a in ARROW.finditer(m.group(1)):
            if int(a.group(1)) == slot and int(a.group(3)) == kind:
                out.append((tw, float(a.group(4)), float(a.group(5)))); break
    return out

def ambush_point(track, s, min_age=6.0, now=None):
    """(x, y, ux, uy): the sample of the marked car's track nearest to us that
    is at least min_age wall seconds old, with the car's heading there (the
    car loops its route, so it will pass that point again, heading that way)"""
    if len(track) < 8: return None
    now = track[-1][0] if now is None else now; best = None
    for i in range(3, len(track) - 3):
        tw, x, y = track[i]
        if now - tw < min_age: continue
        dx, dy = track[i + 3][1] - track[i - 3][1], track[i + 3][2] - track[i - 3][2]; n = math.hypot(dx, dy)
        if n < 0.8: continue
        dd = math.hypot(x - s["x"], y - s["y"])
        if best is None or dd < best[0]: best = (dd, x, y, dx / n, dy / n)
    return best[1:] if best else None

def ram_target(world, money0, secs=420, view_switch=None):
    """wreck the car the mission arrow follows. The arrow samples give its
    heading and speed; far off, drive to a point ahead of it on its road; when
    standing in its path ahead of it, stop, face it and wait; within ten
    blocks charge it with Up held and the nose re-aimed until the impact
    (head-on when it comes at us, from behind when it is stopped), push for a
    moment, reverse well back for a run-up and charge again. A burning car of
    our own is left (flee_fire) and its blast beside the van counts too."""
    t0 = time.time(); hits = 0; hist = []; t_said = 0.0
    ambush = None; u_pre = (0.0, 0.0); t_wait = None
    try: log_off = os.path.getsize(D.LOG)
    except OSError: log_off = 0
    log_off = max(0, log_off - 400000)
    while time.time() - t0 < secs:
        o, ms = outcome(money0)
        if o != "running": return o
        s = D.wait_state()
        if s["driving"] and s.get("fire", 0) > 0:
            say("ram: my car burns; out"); mark("the car burns: out and clear")
            s = flee_fire(world, s); hist = []; continue
        if not s["driving"]:
            s = ram_car(world)
            if not s["driving"]: continue
        tgt = objective()
        if not tgt: time.sleep(1); continue
        hist.append((time.time(), tgt[0], tgt[1])); hist = hist[-40:]
        ux, uy, vs = van_motion(hist)
        dx, dy = tgt[0] - s["x"], tgt[1] - s["y"]; d = math.hypot(dx, dy)
        hx, hy = heading(s); a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
        along = ux * (s["x"] - tgt[0]) + uy * (s["y"] - tgt[1])      # > 0: we are further along its way
        lat = abs(ux * (s["y"] - tgt[1]) - uy * (s["x"] - tgt[0]))
        if time.time() - t_said > 8:
            say(f"ram: van {tgt[0]:.1f},{tgt[1]:.1f} v={vs:.1f} dir={ux:.1f},{uy:.1f} d={d:.1f} along={along:.1f} lat={lat:.1f} cardmg={(ms or {}).get('cardmg')}"); t_said = time.time()
        if view_switch: view_switch(s)
        if vs > 0.8: u_pre = (ux, uy)
        if d > 10:
            if vs > 1.0 and along > 2 and lat < 3.0 and d < 26:
                # in its path, ahead of it: stop, face it and let it come
                hold("Down", 0.5); face_target(s, tgt[0], tgt[1], pulses=2); time.sleep(0.4); continue
            if vs < 0.5 and d < 40 and len(hist) > 3:
                # it stands (a light, a jam): straight at it
                drive3(world, tgt[0], tgt[1], tol=3.0, budget=8, view_switch=view_switch, slow=False); continue
            if ambush is None or (t_wait and time.time() - t_wait > 150 / D.SPEED):
                # the van outruns a chase (pt5_le2a/c/d fell 50-130 blocks behind for
                # minutes): it drives a loop, so stand on its track, nose against its
                # travel, and let it come head-on; the nearest track point to us, again
                # after 150 game seconds without it
                sl = objective_slot(); tr = arrow_track(log_off, sl, tgt[3]) if sl is not None else []
                ap = ambush_point(tr, s)
                if ap:
                    ambush = ap; t_wait = time.time()
                    say(f"ram: ambush at {ap[0]:.1f},{ap[1]:.1f} against {ap[2]:.1f},{ap[3]:.1f} ({len(tr)} track samples)")
            if ambush and d > 12:
                ax, ay, aux, auy = ambush
                if t_wait is None: t_wait = time.time()
                if math.hypot(ax - s["x"], ay - s["y"]) > 3.0:
                    drive3(world, ax, ay, tol=2.0, budget=20, view_switch=view_switch, slow=True); continue
                face_target(s, ax - aux * 8.0, ay - auy * 8.0, pulses=2); hold("Down", 0.3); time.sleep(0.8); continue
            lead = min(d * 0.8, 18.0) if vs > 1.0 else 0.0
            gx, gy = tgt[0] + ux * lead, tgt[1] + uy * lead
            drive3(world, gx, gy, tol=3.0, budget=10, view_switch=view_switch, slow=False)
            continue
        t_wait = None
        if abs(a) > 0.45:
            face_target(s, tgt[0], tgt[1], pulses=3); continue
        # charge: Up held, nose re-aimed until the impact, then a push
        xdo("keydown", "Up"); t1 = time.time(); why = "time"
        while time.time() - t1 < 6.0:
            s = D.wait_state(); tgt = objective()
            if not s["driving"] or not tgt: why = "lost"; break
            if s.get("fire", 0) > 0: why = "fire"; break
            hx, hy = heading(s); dx, dy = tgt[0] - s["x"], tgt[1] - s["y"]
            d = math.hypot(dx, dy); a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
            if abs(a) > 0.12 and d > 1.0:
                key = "Right" if a > 0 else "Left"; xdo("keydown", key); time.sleep(min(abs(a) * 0.4, 0.25)); xdo("keyup", key)
            if d < 1.3: time.sleep(1.5); why = "contact"; break
            if abs(a) > 1.4 and d > 2.0: why = "passed"; break
            time.sleep(0.12)
        xdo("keyup", "Up")
        hits += 1; say(f"ram: charge {hits} ended ({why}) at d={d:.1f}")
        if why == "contact" and tgt and (u_pre[0] or u_pre[1]):
            ambush = (tgt[0], tgt[1], u_pre[0], u_pre[1]); t_wait = time.time()
        s = D.wait_state()
        if s["driving"] and s.get("fire", 0) > 0: continue
        # a run-up: straight back until it is seven blocks off (pt5_le2e's nine
        # contacts from one to three blocks were pushes that burned our own car
        # first), then the loop re-aims and charges at full speed
        if why == "contact":
            xdo("keydown", "Down"); t2 = time.time()
            while time.time() - t2 < 4.0:
                time.sleep(0.25); s = D.wait_state(); tgt = objective()
                if not tgt or not s["driving"]: break
                if math.hypot(tgt[0] - s["x"], tgt[1] - s["y"]) >= 7.0: break
            xdo("keyup", "Down")
        else:
            hold("Down", 0.7)
        time.sleep(0.2)
    return outcome(money0)[0]


# ---------------------------------------------------------------- the gun
GUN_IDS = {1, 2, 3, 4, 5, 6, 9}          # pistol, dual pistol, silenced MG, machine gun, rocket launcher, electro gun, shotgun
# machine-gun generators (COLLECT_01, 30 rounds, respawn 1800 frames) from <district>.mis;
# every gang phone of Downtown has one beside it (the Loonies' at 76.5,39.5 is two
# blocks from the PIZZA CAKE phone: pt5_le2g carried 300 rounds into the van step)
GUN_PICKUPS = {"wil": [(76.5, 39.5, 2), (41.5, 48.5, 2), (11.5, 47.5, 2), (90.5, 87.5, 2), (208.5, 7.5, 2),
                       (84.5, 184.5, 2), (50.5, 183.5, 2)]}

def gun_ready(ms=None):
    ms = ms or mission_state() or {}
    return ms.get("wid", 0) in GUN_IDS and ms.get("ammo", 0) > 0

def fetch_gun(world, budget=300, near=None, count=3, walk_only=False):
    """walk (or drive, when far) to the nearest machine-gun pickups in turn and
    over each until the weapon shows in the mission line (pt6_le2b found nothing
    at 11.5,47.5 and went on to ram; pt6_le2a had picked it up there)"""
    pk = list(GUN_PICKUPS.get(world.district) or [])
    s = D.wait_state(); t0 = time.time()
    if not pk or not s: return False
    ref = near or (s["x"], s["y"])
    pk.sort(key=lambda p: math.hypot(p[0] - ref[0], p[1] - ref[1]))
    for x, y, L in pk[:count]:
        if time.time() - t0 > budget: break
        s = D.wait_state()
        mark(f"to the gun pickup at {x},{y}")
        if math.hypot(x - s["x"], y - s["y"]) > 30 and not walk_only:
            if not s["driving"]: s = any_car2(world, budget=60)
            if s["driving"]:
                cell = street_cell_near(world, x, y, radius=6)
                if cell: s = drive3(world, cell[0], cell[1], tol=2.0, budget=150)
        if s["driving"]: s = leave_car()
        walk3(world, x, y, None, tol=0.35, budget=max(30, min(400 if walk_only else 120, budget - (time.time() - t0))))
        for k in range(8):
            if gun_ready(): say(f"gun: {(mission_state() or {}).get('weapon')}"); return True
            cruise_to(x + 0.3 * math.cos(k * 2.1), y + 0.3 * math.sin(k * 2.1), tol=0.15, secs=3)
            time.sleep(0.4)
        if gun_ready(): return True
        say(f"gun: nothing picked up at {x},{y}")
    return gun_ready()

def _aim_walk(tx, ty, fire=True, walk=True, secs=0.5):
    """one short slice of walking at (tx,ty) with the trigger held, heading
    corrected from the samples (a moving ped's logged facing is his real one)"""
    if fire: xdo("keydown", "Control_L")
    if walk: xdo("keydown", "Up")
    t1 = time.time()
    while time.time() - t1 < secs:
        s = D.wait_state()
        if not s or s["driving"]: break
        a = D.angle_to(s, tx, ty)
        if abs(a) > 0.1:
            key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
            xdo("keydown", key); time.sleep(min(abs(a) / max(D.rate, 2.0), 0.3)); xdo("keyup", key)
        time.sleep(0.08)
    if walk: xdo("keyup", "Up")

def char_arrows():
    """(x, y) of the mission arrows that point at characters (kind 2)"""
    return [(v[2], v[3]) for v in mission_arrows().values() if v[1] == 2]

def shoot_chars(world, money0, secs=240):
    """PLAYTHROUGH-8: a plan step that waits on a kill counter while the arrows point at
    characters (BANK ROBBERY's two guards, `m_20_count7 = 2`): walk at the nearest marked
    character with the trigger held until his arrow goes; on foot, in the third-person view.
    Returns 'done' (no character arrows left), 'no gun', or the job's outcome"""
    t0 = time.time()
    if not gun_ready(): fetch_gun(world, budget=200)
    if not gun_ready(): return "no gun"
    s = D.wait_state()
    if s["driving"]: s = leave_car()
    ensure_view("classic")
    while time.time() - t0 < secs:
        o, ms = outcome(money0)
        if o != "running": return o
        cs = char_arrows()
        if not cs: return "done"
        s = D.wait_state()
        tx, ty = min(cs, key=lambda c: math.hypot(c[0] - s["x"], c[1] - s["y"]))
        d = math.hypot(tx - s["x"], ty - s["y"])
        if d > 9:
            walk3(world, tx, ty, None, tol=6.0, budget=60); continue
        if not gun_ready():
            fetch_gun(world, budget=150)
            if not gun_ready(): return "no gun"
        _aim_walk(tx, ty, fire=True, walk=d > 3.0, secs=0.6)
    xdo("keyup", "Control_L")
    return "timeout"

def follow_arrow(world, money0, view_switch=None, secs=240):
    """PLAYTHROUGH-8: a plan step with no handler of its own while a point arrow is up
    (BANK ROBBERY's respray shop, `CHECK_HEADS_GREATER`): go to the arrow (by car when in
    one), stop there and wait for the objective to change. Returns True when it changed"""
    o = objective()
    if not o or o[3] != 1: return False
    key0 = objective_key(); x, y = o[0], o[1]
    s = D.wait_state()
    mark(f"following the arrow to {x:.1f},{y:.1f}")
    if s["driving"]: s = drive3(world, x, y, tol=1.2, budget=secs, view_switch=view_switch, slow=True, precious=True)
    else: s = walk3(world, x, y, None, tol=0.8, budget=secs)
    return wait_objective_change(key0, 20.0, money0)

def stand_point(world, ap, off=1.4):
    """a spot beside the marked car's track point ap=(x, y, ux, uy): off blocks
    to the side that is not road (a pavement), else on the road's edge"""
    x, y, ux, uy = ap
    for sgn in (1, -1):
        px, py = -uy * sgn, ux * sgn
        for o in (off, off + 0.8):
            cx, cy = x + px * o, y + py * o
            k = node_kind(world, int(cx), int(cy), 1) or node_kind(world, int(cx), int(cy), 2)
            if k and k[1] in (2, 3): return (cx, cy)
    return (x - uy * 0.9, y + ux * 0.9)

SHOOT_3D_BURST = False

def shoot_target(world, money0, secs=600, view_switch=None):
    """wreck the car the mission arrow follows with the gun, on foot (GTA2 has
    no drive-by). PIZZA CAKE's van loops a fixed circuit (about 400 blocks)
    and outruns a chase, and ramming it burned our own cars first (pt5_le2e:
    nine contacts; pt5_le2g: the player died at the wheel). So: pick the point
    of its circuit nearest to us (the arrow track), go there (by car when far),
    stand on the pavement beside it and wait; when the van comes within 12
    blocks walk at it with the trigger held, hold still within four blocks
    (the line of fire stays on its lane), step aside if it comes straight at
    us, fire after it while it is within eight, then back to the spot for the
    next lap. Walking keeps the logged facing true (a standing ped's sprite
    facing can be half a turn off), so the aim is the walking heading.
    pt6_le2a (first version) left the car as the van passed and chased it on
    foot. Returns the outcome, or 'no gun' when the ammunition runs out."""
    t0 = time.time(); hist = []; ambush = None; stand = None; t_spot = None; t_said = 0.0; fired = 0.0
    try: log_off = max(0, os.path.getsize(D.LOG) - 400000)
    except OSError: log_off = 0
    hook = VIEW_HOOK[0]; close = [0.0]; in3d = [False, 0.0, False]   # in3d: in the chase view, since, used once per stop
    def release(): xdo("keyup", "Control_L"); xdo("keyup", "Up")
    while time.time() - t0 < secs:
        o, ms = outcome(money0)
        if o != "running": release(); return o
        if not gun_ready(ms): release(); say("shoot: out of ammunition"); return "no gun"
        s = D.wait_state(); tgt = objective()
        if not s or not tgt: time.sleep(0.5); continue
        hist.append((time.time(), tgt[0], tgt[1])); hist = hist[-40:]
        ux, uy, vs = van_motion(hist)
        dx, dy = tgt[0] - s["x"], tgt[1] - s["y"]; d = math.hypot(dx, dy)
        along = ux * (s["x"] - tgt[0]) + uy * (s["y"] - tgt[1])      # > 0: we are ahead of it on its way
        lat = abs(ux * (s["y"] - tgt[1]) - uy * (s["x"] - tgt[0]))
        if time.time() - t_said > 6:
            say(f"shoot: van {tgt[0]:.1f},{tgt[1]:.1f} v={vs:.1f} d={d:.1f} along={along:.1f} lat={lat:.1f} "
                f"{'driving' if s['driving'] else 'on foot'} {ms.get('weapon')} ammo={ms.get('ammo')} fired={fired:.0f}s"); t_said = time.time()
        coming = vs > 0.8 and along > 0 and lat < 4.0 and d < 13
        standing = vs < 0.5 and len(hist) > 3 and d < 12
        if not standing: in3d[2] = False
        leaving = vs > 0.8 and along <= 0 and d < 8
        # the waiting spot: the nearest point of its circuit, renewed when it has
        # not come by for 200 game seconds (it changed its route)
        if ambush is None or (t_spot and time.time() - t_spot > 200 / D.SPEED):
            sl = objective_slot(); tr = arrow_track(log_off, sl, tgt[3]) if sl is not None else []
            ap = ambush_point(tr, s)
            if ap:
                ambush = ap; stand = stand_point(world, ap); t_spot = time.time()
                say(f"shoot: waiting spot {stand[0]:.1f},{stand[1]:.1f} beside its track at {ap[0]:.1f},{ap[1]:.1f} (heading {ap[2]:.1f},{ap[3]:.1f}; {len(tr)} samples)")
        if s["driving"]:
            if s.get("fire", 0) > 0 or car_burning(ms):
                say("shoot: my car burns; out"); s = flee_fire(world, s); hist = []; continue
            ds = math.hypot(stand[0] - s["x"], stand[1] - s["y"]) if stand else 1e9
            if coming or standing or ds < 5.0 or (stand is None and d < 10):
                hold("Down", 0.4); s = leave_car(); mark("out of the car: the gun")
                ensure_view("classic")
                continue
            if view_switch: view_switch(s)
            if stand: drive3(world, stand[0], stand[1], tol=3.0, budget=40, view_switch=view_switch, slow=True)
            else: drive3(world, tgt[0], tgt[1], tol=6.0, budget=10, view_switch=view_switch, slow=True)
            continue
        # on foot
        if coming and d < 4.5 and lat < 1.3:
            # it comes straight at us: a step to the side, out of its lane
            xdo("keyup", "Control_L")
            px, py = -uy, ux
            if (s["x"] - tgt[0]) * px + (s["y"] - tgt[1]) * py < 0: px, py = -px, -py
            cruise_to(s["x"] + px * 1.8, s["y"] + py * 1.8, tol=0.4, secs=1.6); continue
        if in3d[0] and not (standing and d < 6.0 and time.time() - in3d[1] < 10):
            ensure_view("classic")
            in3d[0] = False
        if coming or standing or leaving:
            t1 = time.time()
            if in3d[0]:
                # the last of the burst in the chase view: no steering keys (the 3D views
                # remap them), the trigger held on the standing car he already faces
                xdo("keydown", "Control_L"); time.sleep(0.5); fired += time.time() - t1; continue
            if SHOOT_3D_BURST and standing and d < 5.5 and close[0] >= 2.0 and hook and not in3d[2]:
                # aimed and firing at a standing van for two seconds: the rest of the
                # burst in the third-person view. Off: pt6_le2f emptied 290 rounds at a van
                # standing 2.5 blocks off in the chase view without wrecking it (110 rounds in
                # the classic view did it in pt6_le2a): the 3D view turns him
                hook("third"); in3d[:] = [True, time.time(), True]; continue
            if d > 4.0 or standing:
                _aim_walk(tgt[0], tgt[1], fire=True, walk=(d > 3.0), secs=0.5)
            else:
                xdo("keydown", "Control_L"); time.sleep(0.5)      # hold the line of fire across its lane
            if standing and d < 2.4:
                xdo("keyup", "Control_L"); hold("Down", 0.35)     # too close for its blast
            fired += time.time() - t1
            close[0] = close[0] + (time.time() - t1) if (standing and d < 5.5) else 0.0
            continue
        xdo("keyup", "Control_L")
        if stand is None:
            time.sleep(0.5); continue
        ds = math.hypot(stand[0] - s["x"], stand[1] - s["y"])
        if ds > 40:
            s = ram_car(world); hist = []
            continue
        if ds > 1.2:
            ensure_view("classic")
            _walk3(world, stand[0], stand[1], None, 0.8, min(60, 8 + ds * 1.5), (1, 2, 3))   # already in the classic view
            continue
        # at the spot: face the way it will come from (a short step toward it)
        if d > 13:
            fx, fy = stand[0] - ambush[2] * 6.0, stand[1] - ambush[3] * 6.0
            if abs(D.angle_to(s, fx, fy)) > 0.5:
                _aim_walk(fx, fy, fire=False, walk=True, secs=0.25); hold("Down", 0.2)
        time.sleep(0.4)
    release()
    return outcome(money0)[0]

CAR_HALF_LEN, CAR_HALF_W = 0.75, 0.45   # a parked car's footprint for the walker (most saloons; a truck is longer)
def car_blocks(sx, sy, tx, ty, car, head, pad=0.3):
    """does the straight walk (sx,sy)->(tx,ty) cross the footprint of the car at `car`
    facing `head` (padded by a body's half width)?"""
    hx, hy = head; n = math.hypot(hx, hy)
    if n < 0.1: return False
    hx, hy = hx / n, hy / n
    for k in range(21):
        px, py = sx + (tx - sx) * k / 20.0, sy + (ty - sy) * k / 20.0
        rx, ry = px - car[0], py - car[1]
        lon, lat = rx * hx + ry * hy, -rx * hy + ry * hx
        if abs(lon) < CAR_HALF_LEN + pad and abs(lat) < CAR_HALF_W + pad: return True
    return False

def walk_round_car(tx, ty, car, head, secs=4.0):
    """PLAYTHROUGH-8: the driver gets out on the car's left, on the road side, and the
    pedestrian he walks to stands on the pavement on its right: the straight walk runs
    into his own car (pt7_ze2i/m/n/o lost 10-38 s of WHEELER-DEALING's clock pressed
    against it, re-routing round it through the traffic queued behind it). When the
    car is in the way, walk to the corner of the car on his side (nose or tail,
    whichever makes the shorter walk) first. Returns the state."""
    s = D.wait_state()
    if not car_blocks(s["x"], s["y"], tx, ty, car, head): return s
    hx, hy = head; n = math.hypot(hx, hy); hx, hy = hx / n, hy / n
    rx, ry = s["x"] - car[0], s["y"] - car[1]
    side = 1.0 if (-rx * hy + ry * hx) >= 0 else -1.0
    lx, ly = -hy * side, hx * side                      # unit vector to his side of the car
    best = None
    for sgn in (1.0, -1.0):
        cx = car[0] + hx * (CAR_HALF_LEN + 0.55) * sgn + lx * (CAR_HALF_W + 0.25)
        cy = car[1] + hy * (CAR_HALF_LEN + 0.55) * sgn + ly * (CAR_HALF_W + 0.25)
        cost = math.hypot(cx - s["x"], cy - s["y"]) + math.hypot(tx - cx, ty - cy)
        if car_blocks(cx, cy, tx, ty, car, head, pad=0.2): cost += 3.0
        if best is None or cost < best[0]: best = (cost, cx, cy, sgn)
    _, cx, cy, sgn = best
    say(f"walk_round_car: the car at {car[0]:.1f},{car[1]:.1f} stands between; round its {'nose' if sgn > 0 else 'tail'} at {cx:.1f},{cy:.1f}")
    s, ok = cruise_to(cx, cy, tol=0.6, secs=secs, stop=False)
    return s

def street_cell_walk_nearest(world, x, y, radius=8, tl=None):
    """the road cell (level 1 or 2) within radius from which the walk to (x,y) is
    shortest: the place to leave a car for a box inside a walled block (pt6_ze2b
    parked on the road north of the WHEELER-DEALING briefcase, 32 cells of
    walking each way round the block wall, against 6 from the south road)"""
    cx0, cy0 = int(x), int(y); cands = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for lvl in (1, 2):
                if walkable(world.blocks, world.columns, cx0 + dx, cy0 + dy, lvl, (1,)):
                    cands.append((math.hypot(dx, dy), cx0 + dx, cy0 + dy, lvl)); break
    cands.sort(); best = None
    for _, cx, cy, lvl in cands[:48]:
        path = route3(world, cx, cy, lvl, cx0, cy0, tl, limit=4000)
        if not path or (path[-1][0], path[-1][1]) != (cx0, cy0): continue
        if best is None or len(path) < best[0]: best = (len(path), cx + 0.5, cy + 0.5, lvl)
    return best[1:] if best else street_cell_near(world, x, y, radius)

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


def escape_route(world, s, dist=9, away=None):
    """waypoints for running clear of a blast: the nearest ring cell 7-10 blocks
    away that the router can actually reach from here in at most 1.6x the
    straight distance (walls, railings and drops respected), as line-of-sight
    legs; [] when nothing is reachable"""
    L = ped_level(s); sx, sy = int(s["x"]), int(s["y"]); best = None
    for r in (dist, dist - 2, dist + 1):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r: continue
                if away is not None:
                    # only cells on the far side from the blast (a car bomb: pt6_ste1 died 3 s
                    # after arming, running along the trailer the script blows up)
                    bx, by = s["x"] - away[0], s["y"] - away[1]; bn = math.hypot(bx, by) or 1.0
                    if (dx * bx + dy * by) / (bn * math.hypot(dx, dy)) < 0.3: continue
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
