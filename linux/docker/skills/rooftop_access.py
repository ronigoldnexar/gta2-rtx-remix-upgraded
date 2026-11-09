#!/usr/bin/env python3
"""Skill: rooftop access (Wave M, SKILL-ROOFTOP).

32 of GTA2's 67 phone/tutorial/final jobs start from a phone on a raised terrace or roof
(catalogue skill `rooftop_access`: the phone stands at L4+ or a LOCATE box is at z >= 4).
The runners so far reached those phones with a developer scene warp (mission_play_wil.answer,
mission_play_districts.answer: "phone on a terrace the walker cannot climb") and warped back
down to the street after the answer. This module climbs and descends on foot, with no warp:

- `launch_cell`: the cell beside the phone the walker stops on before stepping onto the phone:
  flat at the phone's level, no wall face towards the phone, not a phone, reachable with every
  other phone cell avoided, and as far from the other phones as possible (the Downtown Zaibatsu
  pair stands two cells apart on a one-block rim: approaching COP CAR CRUSH from between them
  answers WHEELER-DEALING first);
- `climb`: the multi-level route (mission_lib.route3: stairs and ramps join lid levels) cut into
  flights; each flight is walked to the first flat cell above it and checked by the ped's height
  (`ped_level`). A flight the walker cannot get up twice (a stair top that does not go through,
  a railing the map does not show) is learned into mission_lib.BLOCKED and the route is planned
  again without it. A fall (height below the last flight reached) re-plans from where he lands;
- `descend`: back to street level (level 1) along the route towards the next objective, the
  same check by height;
- `answer_roof_phone`: climb to the launch cell, then the session's own `answer` (step on, the
  title message, step off and on again) with warps off;
- `survey` (host side, no game): every rooftop job's phone routed from the district start.

Per-mission logic stays out of here: the CLI plays a job by handing it to the district session's
plan runner (mission_play_wil.run_plan for Downtown) once the phone has been answered and the
player is back on the street.

Usage inside the container (keys_rooftop_access.sh):
    python3 /work/skills/rooftop_access.py wil_ze1          (Downtown; DISTRICT=wil)
Host (offline route survey, no game):
    python3 gamerun/skills/rooftop_access.py --survey <game dir> <missions-catalogue.json>
"""
import math, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.dirname(HERE)
sys.path.insert(0, WORK)

STATS = {"flights": 0, "flight_retries": 0, "learned_blocks": 0, "falls": 0, "replans": 0, "warps": 0}
LOG_LINES = []

def _say(*a):
    msg = " ".join(str(x) for x in a)
    LOG_LINES.append(msg)
    if "D" in globals(): D.say("rooftop:", msg)
    else: print("rooftop:", msg, flush=True)

# ---------------------------------------------------------------- map side (no game needed)

def stand_level(world, x, y, hint=None):
    """the lid level a ped can stand on at cell (x,y): the hint if it is standable, else the
    lowest one"""
    if hint is not None and M.node_kind(world, x, y, hint): return hint
    for L in range(0, 8):
        if M.node_kind(world, x, y, L): return L
    return None

def phone_level(world, entry):
    """lid level of a phone: the script's z (standing height) minus one, or for z=255 (on
    top) the highest standable level of the column"""
    x, y = int(entry["x"]), int(entry["y"])
    z = entry.get("z", entry.get("level", 255))
    if z is not None and z < 200: return max(0, int(round(z)) - 1)
    best = None
    for L in range(0, 8):
        if M.node_kind(world, x, y, L): best = L
    return best if best is not None else M.top_level(world, x, y) - 1

def flights(path, world=None):
    """[(i0, i1, level_from, level_to)]: runs of the path that change level (a stair or a
    ramp), as path indices of the last flat cell before the run and the first flat cell
    after it (a 7-degree ramp is eight slope pieces stored at one level: its top is the
    flat cell past the eighth, not the first piece)"""
    def is_slope(c):
        if world is None: return False
        k = M.node_kind(world, *c); return bool(k and k[0] == "slope")
    out = []; i = 1
    while i < len(path):
        if path[i][2] != path[i - 1][2] or is_slope(path[i]):
            a = i - 1; j = i
            while j + 1 < len(path) and (path[j + 1][2] != path[j][2] or is_slope(path[j]) or is_slope(path[j + 1])): j += 1
            if path[j][2] != path[a][2]: out.append((a, j, path[a][2], path[j][2]))
            i = j + 1
        else: i += 1
    return out

def _other_phones(world, keep):
    return [(p["x"], p["y"]) for p in world.db["phones"].values()
            if math.hypot(p["x"] - keep[0], p["y"] - keep[1]) > 0.1]

def launch_cell(world, entry, start=None):
    """(x, y, level, path) of the cell beside the phone to step on from, or None.
    start = (x, y, level) to check reachability from (the route with all other phones
    avoided); without it the cells are scored only"""
    px, py = int(entry["x"]), int(entry["y"]); tl = phone_level(world, entry)
    others = _other_phones(world, (entry["x"], entry["y"]))
    cands = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        x, y = px + dx, py + dy
        for L in (tl, tl + 1, tl - 1):
            k = M.node_kind(world, x, y, L)
            if not k or k[0] != "flat": continue
            if L == tl and M.wall_between(world, x, y, L, -dx, -dy): continue
            if any(int(ox) == x and int(oy) == y for ox, oy in others): continue
            clear = min([math.hypot(x + 0.5 - ox, y + 0.5 - oy) for ox, oy in others] or [9.0])
            # a launch cell off the phone's level only when none is level with it (a ped
            # drops a level but never climbs one without a stair)
            cands.append((-(clear) + (20.0 if L != tl else 0.0), x, y, L))
            break
    cands.sort()
    if not start: return (cands[0][1], cands[0][2], cands[0][3], []) if cands else None
    best = None
    for score, x, y, L in cands:
        path = M.route3(world, start[0], start[1], start[2], x, y, L)
        if path and path[-1] == (x, y, L):
            # a route that crosses the phone itself (or another phone) is no launch route
            if any((c[0], c[1]) == (px, py) for c in path): continue
            cost = score * 6.0 + len(path) * 0.02
            if best is None or cost < best[0]: best = (cost, (x, y, L, path))
    return best[1] if best else None

# ---------------------------------------------------------------- in the game

def _here(world):
    s = D.wait_state()
    if not s: return None, None
    return s, (int(s["x"]), int(s["y"]), stand_level(world, int(s["x"]), int(s["y"]), M.ped_level(s)) or M.ped_level(s))

class GameClock:
    """seconds of play since start: the wall clock, but never more than the game's own clock
    (the renderer's frame counter, 256-frame granular) plus a margin. The CPU governor freezes the
    whole container when the host's load passes 20; with a wall-time budget ccc1 spent its whole
    climb (991 s) in a 16-minute pause after 17 game seconds"""
    MARGIN = 12.0

    def __init__(self):
        self.t0 = time.time(); self.f0 = M.frames_rendered()

    def __call__(self):
        wall = time.time() - self.t0
        game = D.game_seconds(M.frames_rendered() - self.f0) / max(1.0, getattr(D, "SPEED", 1.0))   # wall-equivalent at GTA2_SPEED
        return min(wall, game + self.MARGIN)

    def paused(self, since_wall, since_game):
        """True when a stretch that took since_wall wall seconds advanced the game far less"""
        return (time.time() - since_wall) > 3 * max(10.0, self() - since_game) and time.time() - since_wall > 60


def _no_warps():
    old = os.environ.get("WARP_OK", "1"); os.environ["WARP_OK"] = "0"; return old

def climb(world, tx, ty, tl, budget=600, tol=0.6, learn=True):
    """walk to cell (tx,ty) at lid level tl by stairs and ramps, flight by flight, no warp.
    Returns (state, reached)"""
    old = _no_warps(); clk = GameClock(); fails = {}; best_level = None
    try:
        while clk() < budget:
            s, here = _here(world)
            if not s: return s, False
            if s["driving"]:
                M.leave_car(); continue
            if math.hypot(tx + 0.5 - s["x"], ty + 0.5 - s["y"]) < tol + 0.2 and M.ped_level(s) == tl:
                return s, True
            path = M.route3(world, here[0], here[1], here[2], tx, ty, tl)
            if not path or path[-1] != (tx, ty, tl):
                _say(f"climb: no route from {here} to {tx},{ty} L{tl} (end {path[-1] if path else None})")
                if fails.get("noroute", 0) >= 1: return s, False
                fails["noroute"] = fails.get("noroute", 0) + 1
                # step onto the walkable ground first (he may stand on a kerb edge), then again
                M.cruise_to(here[0] + 0.5, here[1] + 0.5, tol=0.4, secs=4); continue
            fl = flights(path, world)
            STATS["replans"] += 1
            _say(f"climb: {len(path)} cells, {len(fl)} flights from {here} to {tx},{ty} L{tl}: "
                 + ", ".join(f"{path[a][:2]}L{la}->{path[b][:2]}L{lb}" for a, b, la, lb in fl))
            if not fl:
                s = M.walk3(world, tx + 0.5, ty + 0.5, tl, tol=tol, budget=max(30, budget - clk()))
                if s and math.hypot(tx + 0.5 - s["x"], ty + 0.5 - s["y"]) < tol + 0.3 and M.ped_level(s) == tl: return s, True
                fails["flat"] = fails.get("flat", 0) + 1
                if fails["flat"] >= 3: return s, False
                continue
            # the next flight: walk to the first flat cell above (below) it
            a, b, la, lb = fl[0]
            top = path[b]
            key = (path[a], top)
            seg_budget = 60 + 1.6 * (b + 1)
            w0, g0 = time.time(), clk()
            s = M.walk3(world, top[0] + 0.5, top[1] + 0.5, top[2], tol=0.6, budget=seg_budget)
            if s and M.ped_level(s) == top[2] and math.hypot(top[0] + 0.5 - s["x"], top[1] + 0.5 - s["y"]) < 1.3:
                STATS["flights"] += 1
                best_level = top[2] if best_level is None else max(best_level, top[2])
                M.mark(f"rooftop: flight {path[a][:2]} L{la} -> {top[:2]} L{lb} climbed (z {s['z']:.2f})")
                continue
            if clk.paused(w0, g0):
                # the container was frozen during the flight: not a failure of the flight
                STATS["pauses"] = STATS.get("pauses", 0) + 1
                M.mark(f"rooftop: flight {path[a][:2]}->{top[:2]} spanned a pause ({time.time()-w0:.0f} wall-s, {clk()-g0:.0f} game-s); not counted")
                continue
            fails[key] = fails.get(key, 0) + 1; STATS["flight_retries"] += 1
            lvl = M.ped_level(s) if s else None
            if best_level is not None and lvl is not None and lvl < best_level:
                STATS["falls"] += 1; M.mark(f"rooftop: fell from L{best_level} to L{lvl} at {s['x']:.1f},{s['y']:.1f}; planning again")
                best_level = lvl
            _say(f"climb: flight {path[a][:2]}->{top[:2]} not made (try {fails[key]}; at {s['x']:.1f},{s['y']:.1f} L{lvl})" if s else "climb: no state")
            if fails[key] >= 2 and learn:
                cells = {(c[0], c[1]) for c in path[a + 1:b + 1] if M.node_kind(world, *c) and M.node_kind(world, *c)[0] == "slope"}
                cells = cells or {(top[0], top[1])}
                M.BLOCKED.update(cells); STATS["learned_blocks"] += len(cells)
                M.mark(f"rooftop: flight {path[a][:2]}->{top[:2]} learned blocked ({sorted(cells)}); another way up")
        return D.wait_state(), False
    finally:
        os.environ["WARP_OK"] = old

def descend(world, toward=None, budget=300):
    """back down to the street (level 1, or the lowest level of the route towards `toward`),
    on foot, no warp. Returns (state, reached)"""
    s, here = _here(world)
    if not s: return s, False
    if here[2] <= 1: return s, True
    tgt = None
    if toward:
        path = M.route3(world, here[0], here[1], here[2], int(toward[0]), int(toward[1]), None)
        low = [i for i, c in enumerate(path) if c[2] <= 1]
        if low:
            i = low[0]
            # a few cells past the foot of the last flight, so the walker is clear of the stair
            i = min(len(path) - 1, i + 2)
            tgt = path[i]
    if tgt is None:
        # nearest street cell by route
        cell = M.street_cell_walk_nearest(world, here[0], here[1], radius=12, tl=1) if hasattr(M, "street_cell_walk_nearest") else None
        if cell: tgt = (int(cell[0]), int(cell[1]), cell[2] if len(cell) > 2 else 1)
    if tgt is None: _say("descend: no street cell found"); return s, False
    M.mark(f"rooftop: descending from {here} to {tgt}")
    s, ok = climb(world, tgt[0], tgt[1], tgt[2], budget=budget, tol=0.9)
    if ok: M.mark(f"rooftop: back on the street at {s['x']:.1f},{s['y']:.1f} z {s['z']:.2f}")
    return s, ok

def answer_roof_phone(world, entry, answer_fn, budget=900):
    """climb to the phone's launch cell, then the session's answer (step on, title, step off
    and on), warps off. Returns (ok, ms_or_key, info)"""
    t0 = time.time(); clk = GameClock()
    s, here = _here(world)
    if not s: return False, None, {"why": "no state"}
    tl = phone_level(world, entry)
    M.set_avoid_phones(world, keep=None)          # every phone avoided, this one too, until the step on
    lc = launch_cell(world, entry, start=here)
    if not lc:
        _say(f"phone {entry['x']},{entry['y']} L{tl}: no reachable launch cell from {here}")
        return False, None, {"why": "no launch cell"}
    lx, ly, ll, path = lc
    M.mark(f"rooftop: phone {entry['x']},{entry['y']} L{tl}: launch cell {lx},{ly} L{ll}, {len(path)} cells, {len(flights(path, world))} flights")
    s, ok = climb(world, lx, ly, ll, budget=budget * 0.8, tol=0.45)
    info = {"launch": (lx, ly, ll), "climb_s": round(clk()), "climb_wall_s": round(time.time() - t0), "reached": ok, "z": s["z"] if s else None}
    if not ok:
        M.mark(f"rooftop: launch cell not reached ({clk():.0f} game-s, at {s['x']:.1f},{s['y']:.1f} z {s['z']:.2f})" if s else "rooftop: no state")
        return False, None, info
    M.mark(f"rooftop: on the terrace at {s['x']:.1f},{s['y']:.1f} z {s['z']:.2f} after {clk():.0f} game-s, no warp")
    M.shot("rooftop_terrace")
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    old = _no_warps()
    try:
        ok, ms = answer_fn(entry)
    finally:
        os.environ["WARP_OK"] = old
    info["answer_s"] = round(clk())
    return ok, ms, info

# ---------------------------------------------------------------- the CLI: a real job

def play_job(job):
    """answer the job's rooftop phone, come down, hand over to the district's plan runner"""
    entry = next((m for m in world.db["missions"] if m.get("mission") == job), None)
    if not entry: return f"no such mission {job}"
    M.mark(f"mission {job}: {entry.get('title', '')} (skills/rooftop_access.py)")
    t_m = time.time()
    ok, ms, info = answer_roof_phone(world, entry, P.answer)
    M.arm_lives()
    say("answered:", ok, ms, info); M.shot(f"{job}_phone")
    if not ok: return f"phone not answered ({info})"
    title_key = ms["msg"] if isinstance(ms, dict) else (ms or "")
    started = next((m for m in world.db["missions"] if m.get("plan") and m["plan"][0].get("display_message") == title_key), None)
    if started and started.get("mission") != job:
        M.mark(f"rooftop: the neighbour phone answered ({started['mission']} {started.get('title','')})")
        return f"wrong job started ({started['mission']})"
    M.mark(f"rooftop: phone answered after {info.get('answer_s')}s (message {title_key})")
    # off the phone the way he came (the launch cell): step_off_phone picked (208,56) on the
    # Downtown Zaibatsu terrace in rf1, a dead end whose only way out is the phone itself
    lx, ly, ll = info["launch"]
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))   # the answered phone may be crossed
    M.cruise_to(lx + 0.5, ly + 0.5, tol=0.45, secs=8)
    # down towards the first thing the plan goes to (the mission car, else its first arrow)
    toward = None
    for st in entry.get("plan", []):
        if "car" in st: toward = st["at"]; break
        if isinstance(st.get("arrow"), list): toward = st["arrow"]; break
    s, down = descend(world, toward=toward, budget=300)
    M.set_avoid_phones(world, keep=None)
    say("descended:", down, f"{s['x']:.1f},{s['y']:.1f} z {s['z']:.2f}" if s else None)
    if not down: M.mark("rooftop: the descent did not reach the street; the plan walks from here")
    M.shot(f"{job}_street")
    os.environ["WARP_OK"] = os.environ.get("ROOF_WARP_PLAN", "0")
    r = P.run_plan(entry)
    return f"{r} ({time.time()-t_m:.0f}s)"

def game_alive():
    for attempt in range(4):
        s0 = D.wait_state()
        D.hold("Left", 0.5); time.sleep(0.8); s1 = D.wait_state()
        if s0 and s1 and abs(s0["fx"] * s1["fy"] - s0["fy"] * s1["fx"]) + abs(s0["x"] - s1["x"]) + abs(s0["y"] - s1["y"]) > 0.02:
            return True
        D.say(f"start: the game does not move (attempt {attempt + 1}); Return")
        D.tap("Return", 0.3); time.sleep(3.0)
    return False

def session_main(jobs):
    global D, M, P, world, say
    district = os.environ.get("DISTRICT", jobs[0][:3])
    if district != "wil":
        print(f"rooftop: the CLI hands Downtown jobs to mission_play_wil; {district} needs its session wired"); return
    sys.argv = sys.argv[:1]; os.environ["MISSIONS"] = " "
    import drive_lib as D_; import mission_lib as M_
    D, M = D_, M_
    import mission_play_wil as P_      # the session: start, calibration, views, answer, run_plan
    P = P_; world = P.world; say = D.say
    if not game_alive():
        M.mark("rooftop: the game stood still at the start"); say("RESULT frozen at start"); return
    results = {}
    for job in jobs:
        r = play_job(job)
        results[job] = r
        M.mark(f"mission {job}: {r} stats {STATS}")
        time.sleep(3); M.shot(f"{job}_end")
    say("RESULTS", results, STATS)
    M.mark("done " + " ".join(f"{k}={v}" for k, v in results.items()))
    with open("/out/rooftop_result.txt", "w") as f:
        for k, v in results.items(): f.write(f"{k}\t{v}\t{STATS}\n")

# ---------------------------------------------------------------- host survey

def survey(game_dir, catalogue):
    """route every rooftop job's phone from its district start (no game): launch cell,
    route length, flights; prints one line per phone"""
    global M, D
    import json, types
    stub = types.ModuleType("drive_lib")
    for n in ("say", "tap", "hold", "xdo"): setattr(stub, n, lambda *a, **k: None)
    stub.SPEED = 1.0
    sys.modules.setdefault("drive_lib", stub)
    import mission_lib as M_
    M = M_
    db = json.load(open(os.path.join(WORK, "missions.json")))
    cat = json.load(open(catalogue))
    class W(M.World):
        def __init__(self, d):
            self.district = d
            self.blocks, self.columns = M.gmp.load(os.path.join(game_dir, "data", f"{d}.gmp"))
            self.db = db[d]
    n_ok = n = 0
    for dk, dv in cat["districts"].items():
        w = W(dk); st = dv["start"]
        sl = stand_level(w, int(st[0]), int(st[1]))
        for j in dv["jobs"]:
            if "rooftop_access" not in j["skills"]: continue
            for ph in j["phones"]:
                n += 1
                entry = {"x": ph["x"], "y": ph["y"], "z": ph["level"]}
                M.BLOCKED.clear(); M.set_avoid_phones(w, keep=None)
                lc = launch_cell(w, entry, start=(int(st[0]), int(st[1]), sl))
                if lc:
                    n_ok += 1; lx, ly, ll, path = lc
                    fl = flights(path, w)
                    print(f"{dk} {j['id']:8s} phone {ph['x']},{ph['y']} L{ph['level']:g}: launch {lx},{ly} L{ll}, "
                          f"{len(path)} cells, {len(fl)} flights, top L{max(c[2] for c in path)}")
                else:
                    print(f"{dk} {j['id']:8s} phone {ph['x']},{ph['y']} L{ph['level']:g}: NO ROUTE to a launch cell")
    print(f"survey: {n_ok} of {n} rooftop phones have a stair/ramp route to a launch cell")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--survey":
        survey(sys.argv[2], sys.argv[3])
    else:
        session_main(sys.argv[1:] or os.environ.get("ROOF_JOBS", "wil_ze1").split())
