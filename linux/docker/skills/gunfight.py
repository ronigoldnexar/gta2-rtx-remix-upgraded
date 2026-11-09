#!/usr/bin/env python3
"""Skill: an on-foot gunfight with armed men who shoot back (Wave M, `combat_on_foot`,
22 jobs and 3 bonus levels in docs/missions-catalogue.md).

A job of this kind sends armed characters at the player (WHO'S MAD?'s three Zaibatsu hitmen with
machine guns, FOLLOW THAT TRAITOR!'s "traitor and his men", J-Lab's guards, the district finals'
bosses and escorts...) and waits for them to die, or for a counter, or for a time. Unlike
`kill_marked` (stand and shoot at marked, mostly passive targets) the targets here move, come in
cars, carry guns and kill the player if he stands still in the open. This module runs that fight
for any job, on the shared runner libraries (`mission_lib`, `drive_lib`, unchanged):

    import skills.gunfight as G
    r = G.gunfight(world, select=lambda p: p["gang"] == "zaibatsu", check=job_check, secs=240)
    # r: "done" (done() holds, or `count` down, or no hostile left for `clear` s), "no gun",
    #    "timeout"; check() raises the job's own exception when the job is over (JOB COMPLETE,
    #    JOB FAILED, death), which is how a job that ends on the last kill ends the fight

How it fights:
  - hostiles from `view: peds`: alive, picked by select(p) (or every marked ped), on foot or in a
    car; a ped once selected stays a hostile while alive (the job's arrows go when he is off screen);
  - out of any car first and a gun in the hand (`M.select_gun`, else the job's pickups); a few
    steps away from the car it left (an enemy who shoots at him blows it up beside him);
  - target: the nearest hostile on foot on the player's level, else the nearest at all; a hostile
    still in his car is shot through the car once it is within `engage` (the car burns and blows
    with him in it); far ones are walked at with the trigger off;
  - in range: the gun with the trigger held, walking at him while over `close` blocks (walking keeps
    the logged facing true and the player a moving target), standing under it;
  - no damage for `stall` s (a wall, a car body, a railing takes the rounds): a fire spot, a side
    step across the line, closer;
  - a burning car within `blast` blocks: step away from it first (GTA2 cars explode 1-3 s after
    they burn out; pt9 lost a life to one);
  - health: when it falls under `low`, the fight backs off along the line away from the nearest
    hostile (turning, then a short run) and turns round to fire again, instead of trading rounds
    standing; a `spare(p)` ped in the line of fire holds the trigger;
  - a line of fire checked on the map before the trigger (no building block, no wall face between,
    `clear_shot`); when blocked, a nearby spot with a clear line (`firing_spot`), else round by the
    router in short legs; every approach in sight is half-second slices, the targets read again
    after each (no blind walk3 leg toward an armed man);
  - with a wanted level, an officer on foot closing in is shot first (an arrest ends the job);
  - one seen and not down but out of sight for `hunt` s: to where he was last;
  - an `anchor` (x, y) with a `leash`: when no hostile is in sight the player goes back to it (the
    place the job sends the hostiles to), so the fight happens where the job expects it.
With GTA2_DIRECT_KEYS=1 every move and every round is played in the chase view
(mission_lib.foot_view), so the frames of the fight are third-person ones.

Run on its own (a job that is already running, hostiles near):
    python3 /work/skills/gunfight.py [secs] [gang]
"""
import math, os, re, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

STATS = {}          # the last fight's numbers, for the job runner's log line


# ------------------------------------------------------------------ the log

class JobOver(Exception):
    pass


# the game's words for an arrest: BUSTED! ("nicked"), "You have been arrested!" (1015) and the gangs'
# jail briefs (e.gxt). gf_wm3 was jailed mid-fight (7075, "Your madcap mayhem has put you in jail")
# with no JOB FAILED, no death and no life lost: the job ends silently (CHECK_DEATHARREST_EXECUTED)
ARREST_KEYS = {"nicked", "1015", "7075", "7078", "7087", "7099", "6177", "1513", "1534", "1669", "1670",
               "1351", "1991", "4226", "4227", "6166"}

_MSGS = {"off": None, "outcome": None}

def arm_job():
    """call when the job starts: from here on every message the log shows is read (job_state),
    not just the newest one. gf_wm7: JOB COMPLETE (1124) was up for 1.7 s and gave way to the save
    sign (svdone) while the fight stepped away from a burning car; the newest-line check missed it"""
    _MSGS["off"] = M.log_size(); _MSGS["outcome"] = None


def _scan():
    if _MSGS["off"] is None or _MSGS["outcome"]: return _MSGS["outcome"]
    try:
        with open(D.LOG, "rb") as f:
            f.seek(_MSGS["off"]); data = f.read()
    except OSError:
        return None
    k = data.rfind(b"\n")
    if k < 0: return None
    _MSGS["off"] += k + 1
    for m in re.finditer(rb"view: mission money=-?\d+ .*? msg=(\S*) frame=", data[:k]):
        key = m.group(1).decode("latin-1")
        if key in M.COMPLETE_KEYS: _MSGS["outcome"] = "complete"
        elif key in M.FAILED_KEYS: _MSGS["outcome"] = "failed"
        elif key in ARREST_KEYS: _MSGS["outcome"] = "arrested"
        if _MSGS["outcome"]: break
    return _MSGS["outcome"]


def job_state():
    """the job's outcome from the game's own words (as kill_marked.job_state: not M.outcome,
    which takes any +$10,000 for a completion); with arm_job() every message since the job began"""
    ms = M.mission_state()
    if not ms: return "unknown", {}
    o = _scan()
    if o: return o, ms
    if ms["msg"] in M.COMPLETE_KEYS: return "complete", ms
    if ms["msg"] in M.FAILED_KEYS: return "failed", ms
    if ms["msg"] in ARREST_KEYS: return "arrested", ms
    if ms["health"] == 0 or ms["death"] != 0: return "dead", ms
    if M.LIVES0[0] is not None and ms["lives"] < M.LIVES0[0]: return "dead", ms
    return "running", ms


def default_check():
    o, ms = job_state()
    if o not in ("running", "unknown"): raise JobOver(o)
    return ms


def level_of_z(z):
    return max(0, int(round(z)) - 1)


def dist(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def in_line(s, tx, ty, px, py, width=0.9):
    """is (px, py) between the player and the target, within `width` of the line of fire?"""
    dx, dy = tx - s["x"], ty - s["y"]; n = math.hypot(dx, dy)
    if n < 1e-6: return False
    ux, uy = dx / n, dy / n
    along = (px - s["x"]) * ux + (py - s["y"]) * uy
    if along < 0.2 or along > n + 0.5: return False
    return abs((px - s["x"]) * uy - (py - s["y"]) * ux) < width


def release():
    xdo("keyup", "Control_L"); xdo("keyup", "Up")


# ------------------------------------------------------------------ moving under fire

def step_away(s, fx, fy, d=2.5, secs=3.0):
    """a short run directly away from (fx, fy): turn, then Up (the cruise steers)"""
    dx, dy = s["x"] - fx, s["y"] - fy; n = math.hypot(dx, dy) or 1.0
    M.cruise_to(s["x"] + dx / n * d, s["y"] + dy / n * d, tol=0.5, secs=secs)


def side_step(s, tx, ty, k, d=1.5):
    """a step across the line of fire, alternating sides"""
    dx, dy = tx - s["x"], ty - s["y"]; n = math.hypot(dx, dy) or 1.0
    px, py = -dy / n, dx / n
    if k % 2: px, py = -px, -py
    M.cruise_to(s["x"] + px * d, s["y"] + py * d, tol=0.4, secs=3)


def clear_shot(world, s, tx, ty):
    """True when the map has nothing between the player and (tx, ty) at his level: every point of
    the line on an open lid, no building block and no wall face crossed (mission_lib.line_clear with
    a bullet's width). gf_wm5 fired 37 s and 270 rounds into the brick wall of the WHO'S MAD? yard
    at a hitman 1.5 blocks away on the other side of it"""
    try:
        return M.line_clear(world, (s["x"], s["y"]), (tx, ty), M.ped_level(s), kinds=(1, 2, 3), half_width=0.08)
    except Exception:
        return True


def firing_spot(world, s, tx, ty, engage, reach=5.0):
    """the nearest open spot within `reach` blocks that the player can walk to in a straight line
    and that has a clear shot at (tx, ty) from engage blocks or nearer; None when there is none"""
    L = M.ped_level(s); best = None
    for r in (1.0, 2.0, 3.0, 4.0, reach):
        for k in range(16):
            a = k * math.pi / 8
            x, y = s["x"] + r * math.cos(a), s["y"] + r * math.sin(a)
            d = math.hypot(tx - x, ty - y)
            if d > engage or d < 1.5: continue
            try:
                if not M.line_clear(world, (s["x"], s["y"]), (x, y), L, kinds=(1, 2, 3), half_width=0.3): continue
                if not M.line_clear(world, (x, y), (tx, ty), L, kinds=(1, 2, 3), half_width=0.08): continue
            except Exception:
                return None
            score = r + 0.3 * d
            if best is None or score < best[0]: best = (score, (x, y))
        if best: break
    return best[1] if best else None


def route_step(world, s, tx, ty, tl=None, secs=2.0):
    """one bounded step along the router's path toward (tx, ty): the first waypoint of the
    straightened route (walls and railings kept clear), walked for at most `secs`. walk3's budget is
    checked between legs only, and a leg can run on for its own 8-60 s: gf_wm9 was on such a leg when
    a hitman killed him, and the leg went on walking the dead man after the respawn"""
    try:
        path = M.route3(world, int(s["x"]), int(s["y"]), M.ped_level(s), int(tx), int(ty), tl)
    except Exception:
        path = []
    if len(path) < 2:
        return M.cruise_to(tx, ty, tol=0.6, secs=secs)[0]
    pts = M.straighten_los(world, path, (1, 2, 3), half_width=0.3)
    gx, gy = (pts[1][0] + 0.5, pts[1][1] + 0.5) if len(pts) > 2 else (tx, ty)
    if math.hypot(gx - s["x"], gy - s["y"]) > 3.0:      # a long leg: only its first 3 blocks
        k = 3.0 / math.hypot(gx - s["x"], gy - s["y"])
        gx, gy = s["x"] + (gx - s["x"]) * k, s["y"] + (gy - s["y"]) * k
    return M.cruise_to(gx, gy, tol=0.5, secs=secs)[0]


def burning_car_near(s, blast):
    """the nearest burning car (not the target's) within `blast` blocks, or None"""
    best = None
    for c in M.cars():
        if c["fire"] > 0 and c["driver"] != "P":
            d = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
            if d < blast and (best is None or d < best[0]): best = (d, c)
    return best[1] if best else None


def car_of(p):
    """the `view: cars` entry the hostile sits in (nearest car to him), or None"""
    best = None
    for c in M.cars():
        d = math.hypot(c["x"] - p["x"], c["y"] - p["y"])
        if d < 1.2 and (best is None or d < best[0]): best = (d, c)
    return best[1] if best else None


# ------------------------------------------------------------------ the skill

OFFICERS = ("cop",)

def gunfight(world, select=None, spare=None, done=None, count=None, check=None, secs=240,
             engage=7.0, close=2.5, close_car=4.0, far=26.0, stall=7.0, blast=3.2, low=45, clear=None,
             anchor=None, leash=6.0, fire_spots=None, car_targets=True, police="shoot", cop_r=4.5, hunt=8.0,
             shot_prefix="gf"):
    """Fight the hostiles picked by select(p) (every marked ped when None) until done() holds,
    `count` of them are down, no hostile has been in sight for `clear` seconds (None: never on
    that ground alone), or check() raises (the job ended).

    spare(p) -> True for peds that must not be hit. far: hostiles beyond this are ignored.
    anchor/leash: where to wait when none is in sight. fire_spots: positions to try in turn when
    the rounds do no damage. car_targets: shoot a hostile still in his car once within engage, from
    close_car or further (gf_wm3 walked to 2.5 blocks of a VTYPE and took a machine-gun burst, 100 -> 10
    in a second). police: with a wanted level an officer on foot who closes to cop_r blocks arrests him
    and the job ends (gf_wm3): 'shoot' takes him as the target first, 'avoid' steps away, 'ignore'.
    Returns 'done', 'no gun' or 'timeout'; STATS has the numbers."""
    check = check or default_check
    t0 = time.time(); seen = {}; killed = set(); hp_last = None; last_progress = time.time()
    none_since = None; spot_i = -1; steps = 0; fired = 0.0; t_said = 0.0; shots = set()
    hp_min = 100; hits = 0; backoffs = 0; blasts = 0; car_shots = 0; health_last = None
    last_xy = None; cops_shot = 0; cop_steps = 0; walls = 0
    STATS.clear()
    M.mark("gunfight: start")

    def pick(p):
        if not M.ped_alive(p): return False
        if p["id"] in seen: return True
        if spare and spare(p): return False
        return select(p) if select else p["mark"] is not None

    try:
        while time.time() - t0 < secs:
            ms = check() or {}
            if done and done(): M.mark(f"gunfight: done ({len(killed)} down)"); return "done"
            s = D.wait_state()
            if not s: time.sleep(0.3); continue
            if last_xy and not s["driving"] and math.hypot(s["x"] - last_xy[0], s["y"] - last_xy[1]) > 15:
                # a jump across the map: the hospital or the police station (an arrest that the
                # job's words did not show yet)
                M.mark(f"gunfight: moved {math.hypot(s['x'] - last_xy[0], s['y'] - last_xy[1]):.0f} blocks at once "
                       f"({last_xy[0]:.1f},{last_xy[1]:.1f} -> {s['x']:.1f},{s['y']:.1f}): arrested or killed")
                raise JobOver("arrested or killed (moved across the map)")
            last_xy = (s["x"], s["y"])
            if s["driving"]:
                release(); hold("Down", 0.3); s = M.leave_car(); M.mark("gunfight: out of the car")
                M.ensure_view("classic"); M.select_gun()
                # off the car's side: hostiles shoot at him, the car takes the rounds and burns
                c = min(M.cars(), key=lambda c: math.hypot(c["x"] - s["x"], c["y"] - s["y"]), default=None)
                if c: step_away(s, c["x"], c["y"], d=2.5, secs=2.5)
                continue
            # health: count the hits, remember the low point
            h = ms.get("health", 100)
            if health_last is not None and h < health_last: hits += 1
            health_last = h; hp_min = min(hp_min, h)

            allp = M.peds()
            hs = [p for p in allp if pick(p) and math.hypot(p["x"] - s["x"], p["y"] - s["y"]) < far]
            for p in hs: seen[p["id"]] = p
            ids = {p["id"] for p in hs}
            byid = {p["id"]: p for p in allp}
            for pid, p in seen.items():
                if pid in ids or pid in killed: continue
                q = byid.get(pid)
                if (q is not None and not M.ped_alive(q)) or (q is None and p["hp"] <= 0) or \
                   (q is None and math.hypot(p["x"] - s["x"], p["y"] - s["y"]) < 6):
                    # gone from the list counts only close by: the list is the nearest peds (near=11 of
                    # 14 live in gf_wm6), and a man 14 blocks off can drop out of it alive
                    killed.add(pid)
                    M.mark(f"gunfight: down {pid} ({p['type']}/{p['gang']}) at {p['x']:.1f},{p['y']:.1f}; {len(killed)} down, health {h}")
                    if "first" not in shots: M.shot(f"{shot_prefix}_first_down"); shots.add("first")
            if count is not None and len(killed) >= count:
                release(); M.mark(f"gunfight: {len(killed)} of {count} down"); return "done"

            # a burning car beside him: away from it before anything else
            bc = burning_car_near(s, blast)
            if bc:
                release(); blasts += 1
                say(f"gunfight: burning car {bc['id']} {math.hypot(bc['x'] - s['x'], bc['y'] - s['y']):.1f} off: stepping away")
                step_away(s, bc["x"], bc["y"], d=blast + 1.0, secs=3.0)
                continue

            if not hs:
                xdo("keyup", "Control_L")
                none_since = none_since or time.time()
                if clear is not None and time.time() - none_since > clear:
                    M.mark(f"gunfight: no hostile for {clear:.0f} s ({len(killed)} down)"); return "done"
                pending = [p for pid, p in seen.items() if pid not in killed]
                if pending and time.time() - none_since > hunt:
                    # one seen and not down: to where he was last (gf_wm6: the third hitman left his car
                    # at the yard's gate 14 blocks off and stood there out of the list for 6 minutes)
                    p = min(pending, key=lambda p: math.hypot(p["x"] - s["x"], p["y"] - s["y"]))
                    d = math.hypot(p["x"] - s["x"], p["y"] - s["y"])
                    if d > 2.5:
                        say(f"gunfight: none in sight; to {p['id']}'s last place {p['x']:.1f},{p['y']:.1f} ({d:.0f} blocks)")
                        route_step(world, s, p["x"], p["y"])
                        continue
                    seen.pop(p["id"], None)        # he is not there: forget him (he will be picked again)
                arrows = M.char_arrows()
                if arrows:
                    ax, ay = min(arrows, key=lambda a: math.hypot(a[0] - s["x"], a[1] - s["y"]))
                    d = math.hypot(ax - s["x"], ay - s["y"])
                    if d > engage:
                        say(f"gunfight: none in sight; to the arrow at {ax:.1f},{ay:.1f} ({d:.0f} blocks)")
                        route_step(world, s, ax, ay)
                        continue
                if anchor and math.hypot(anchor[0] - s["x"], anchor[1] - s["y"]) > leash:
                    say(f"gunfight: none in sight; back to the anchor {anchor[0]:.1f},{anchor[1]:.1f}")
                    route_step(world, s, anchor[0], anchor[1])
                    continue
                time.sleep(0.3); continue
            none_since = None

            if not M.gun_ready(ms) and not M.select_gun():
                release(); say("gunfight: no gun in hand"); M.fetch_gun(world, budget=120)
                if not M.gun_ready(): return "no gun"
                continue

            mylev = M.ped_level(s)
            # an officer closing in while wanted: an arrest ends the job
            cop = None
            if police != "ignore" and ms.get("wanted", 0) > 0:
                cs = [p for p in allp if p["type"] in OFFICERS and M.ped_alive(p) and p["car"] is None and dist(p, s) < cop_r]
                if cs: cop = min(cs, key=lambda p: dist(p, s))
            if cop is not None and police == "avoid":
                release(); cop_steps += 1
                say(f"gunfight: officer {cop['id']} {dist(cop, s):.1f} off (wanted {ms.get('wanted')}): stepping away")
                step_away(s, cop["x"], cop["y"], d=3.5, secs=2.5); continue
            on_foot = [p for p in hs if p["car"] is None]
            pool = on_foot or (hs if car_targets else [])
            if cop is not None:
                pool = [cop]; cops_shot += 1
                if cops_shot % 8 == 1: M.mark(f"gunfight: officer {cop['id']} {dist(cop, s):.1f} off with wanted {ms.get('wanted')}: shooting him first")
            if not pool:
                # all of them still in cars and cars not targets: wait at the anchor
                time.sleep(0.3); continue
            tgt = min(pool, key=lambda p: (level_of_z(p["z"]) != mylev, dist(p, s)))
            d = dist(tgt, s); tlev = level_of_z(tgt["z"])
            tx, ty = tgt["x"], tgt["y"]
            if time.time() - t_said > 4:
                say(f"gunfight: target {tgt['id']} {tgt['type']}/{tgt['gang']} hp {tgt['hp']} "
                    f"{'in car m' + str(tgt['car']) if tgt['car'] is not None else 'on foot'} at {tx:.1f},{ty:.1f} L{tlev}, "
                    f"me {s['x']:.1f},{s['y']:.1f} L{mylev} health {h}, d {d:.1f}, {ms.get('weapon')} ammo {ms.get('ammo')}, "
                    f"{len(hs)} in sight, {len(killed)} down, fired {fired:.0f}s"); t_said = time.time()

            # hurt and the man is close: back off along the line, then turn and fire again
            if h < low and d < engage and backoffs < 6 and h < (STATS.get("backoff_h", 101)):
                release(); backoffs += 1; STATS["backoff_h"] = h
                M.mark(f"gunfight: health {h}: backing off from {tgt['id']} ({d:.1f} off)")
                step_away(s, tx, ty, d=3.0, secs=2.5)
                continue

            if tlev != mylev and abs(tgt["z"] - s["z"]) > 0.7:
                release()
                route_step(world, s, tx, ty, tlev)
                continue
            if d > engage:
                release()
                c = car_of(tgt) if tgt["car"] is not None else None
                if c is not None and abs(c["v"]) > 0.8:
                    # a hostile driving round: chasing a car on foot loses; face it where he stands
                    # and let it come (WHO'S MAD?'s hitmen circle the block, and stop once on screen)
                    if time.time() - t_said > 3.5: say(f"gunfight: {tgt['id']} driving ({c['v']:.1f}) {d:.1f} off: facing it")
                    M._aim_walk(c["x"], c["y"], fire=False, walk=False, secs=0.4)
                    continue
                if d < 16 or tgt["car"] is not None:
                    # in sight: half-second slices, the targets read again after each one (gf_wm4: a
                    # 20-block walk3 leg went on blind for 4 s and ended 0.3 blocks from a hitman who
                    # had just stepped out of his car: 100 -> 0 in a second, no round fired)
                    M._aim_walk(tx, ty, fire=False, walk=True, secs=0.5)
                    continue
                route_step(world, s, tx, ty)
                continue
            if "engage" not in shots: M.shot(f"{shot_prefix}_engage"); shots.add("engage")

            blocker = None
            if spare:
                for p in allp:
                    if p["id"] != tgt["id"] and M.ped_alive(p) and spare(p) and in_line(s, tx, ty, p["x"], p["y"]):
                        blocker = p; break
            if blocker:
                xdo("keyup", "Control_L"); say(f"gunfight: {blocker['id']} ({blocker['gang']}) in the line of fire: holding")
                side_step(s, tx, ty, steps); steps += 1
                continue

            if tgt["car"] is not None:
                c = car_of(tgt)
                if c is not None:
                    tx, ty = c["x"], c["y"]
                    if c["fire"] > 0 and d < blast + 0.5:
                        release(); step_away(s, tx, ty, d=blast + 1.0, secs=3.0); continue
                car_shots += 1
            if not clear_shot(world, s, tx, ty):
                # a wall or a building between: to a spot with a clear line, else round by the router
                xdo("keyup", "Control_L"); walls += 1
                spot = firing_spot(world, s, tx, ty, engage)
                if time.time() - t_said > 2: say(f"gunfight: no clear shot at {tgt['id']} ({d:.1f} off): "
                                                 f"{'to %.1f,%.1f' % spot if spot else 'round by the router'}"); t_said = time.time()
                if spot: M.cruise_to(spot[0], spot[1], tol=0.4, secs=3)
                else: route_step(world, s, tx, ty)
                last_progress = time.time()
                continue
            t1 = time.time()
            if tgt["car"] is not None and d < close_car - 2.0:
                # too close to a car with a gunman in it: back off to close_car, then fire
                release(); step_away(s, tx, ty, d=close_car - d, secs=2.0); continue
            M._aim_walk(tx, ty, fire=True, walk=d > (close if tgt["car"] is None else close_car), secs=0.5)
            fired += time.time() - t1
            if "firing" not in shots and fired > 1.5: M.shot(f"{shot_prefix}_firing"); shots.add("firing")
            prog = tuple(sorted((p["id"], p["hp"]) for p in hs)) + tuple(sorted((c["id"], c["hp"]) for c in M.cars()
                                                                               if any(math.hypot(c["x"] - p["x"], c["y"] - p["y"]) < 1.2 for p in hs)))
            if prog != hp_last: hp_last = prog; last_progress = time.time()
            if time.time() - last_progress > stall / D.SPEED:
                xdo("keyup", "Control_L"); last_progress = time.time(); steps += 1
                if fire_spots and spot_i + 1 < len(fire_spots):
                    spot_i += 1; fx, fy = fire_spots[spot_i]
                    say(f"gunfight: no damage for {stall:.0f} s: to fire spot {fx},{fy}")
                    M.cruise_to(fx, fy, tol=0.4, secs=4)
                elif steps % 3 == 0:
                    say("gunfight: no damage: closer"); M._aim_walk(tx, ty, fire=True, walk=True, secs=1.0)
                else:
                    say("gunfight: no damage: side step"); side_step(s, tx, ty, steps)
        return "timeout"
    finally:
        release()
        STATS.update(down=len(killed), seen=len(seen), fired=round(fired, 1), health_min=hp_min, hits=hits,
                     backoffs=backoffs, blasts=blasts, car_shots=car_shots, cop_turns=cops_shot, cop_steps=cop_steps, walls=walls,
                     secs=round(time.time() - t0, 1))
        M.mark(f"gunfight: {STATS}")


def main():
    """standalone: the job is running and the hostiles are near"""
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 120
    gang = sys.argv[2] if len(sys.argv) > 2 else None
    D.start(); s = D.wait_state(40)
    if not s: sys.exit(1)
    D.calibrate_turn()
    world = M.World(os.environ.get("DISTRICT", "wil"))
    M.arm_lives()
    sel = (lambda p: p["gang"] == gang) if gang else None
    try:
        r = gunfight(world, select=sel, secs=secs)
    except JobOver as e:
        r = str(e)
    M.mark(f"gunfight standalone: {r}")


if __name__ == "__main__":
    main()
