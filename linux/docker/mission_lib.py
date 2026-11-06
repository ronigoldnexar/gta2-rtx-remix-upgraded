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
