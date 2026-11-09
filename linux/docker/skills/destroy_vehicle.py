#!/usr/bin/env python3
"""Skill: destroy a vehicle (Wave M, `destroy_vehicle`, 13 phone jobs in docs/missions-catalogue.md).

A job of this kind waits on `IS_CAR_WRECKED (car)` for one or more cars, usually marked
(`POINT_ARROW_AT (arrow, car)`, an arrow of kind 3; the renderer's `view: cars` line carries the
arrow slot on the car itself, `:aNN`, and its health `hp` = 32000 - damage, 0 for a wreck), or
counts wrecks of a model (GANG CAR BANG's Meteors and Z-Types, the kill frenzies). This module
does that one step for any job, on the shared runner libraries (`mission_lib`, `drive_lib`,
unchanged):

    from skills import destroy_vehicle as DV
    r = DV.destroy(world, select=None, count=1, check=job_check, secs=600)
    # r: "done" (count targets wrecked, or no marked car left), "no gun", "timeout" or "stuck";
    #    check() raises the job's own exception when the job is over

Targets: the marked cars of `view: cars` (or, with `models=`, any car of those models), tracked by
the renderer's car id; beyond the 30-block cars window the kind-3 arrows say where a marked one is.

How it fights (each line is a lesson from PIZZA CAKE, docs/playthrough-downtown.md parts 4-5):
  - the gun, on foot: ramming burned our own cars first and killed the player at the wheel
    (pt5_le2g, pt6_le2b, pt6_le2h); it stays the fallback when there are no rounds at all;
  - a gun in the hand before the fight (`select_gun`), a pickup fetched when there are no rounds;
  - a far target: by car to it (a borrowed car that catches fire is left at once, pt6_le2e), out
    of the car `leave_at` blocks off; a moving target that loops a circuit (the Pizza van) is
    waited for beside its track (the arrow track's nearest point, a pavement beside it);
  - in range: walk at it with the trigger held (walking keeps the logged facing true), aim a
    little ahead of a moving car, stop `stand_off` blocks short, step out of its lane when it
    comes straight on, fire after it while it is within `engage`;
  - a burning target (fire > 0, hp < 16000) is kept at `blast` blocks: its explosion kills a
    player who stands beside it;
  - no damage for `stall` game seconds while firing (a wall or a parked car takes the rounds):
    a side step across the line, then closer;
  - the step ends when `count` targets are wrecked (hp 0 or the car gone while we were near it),
    or, for marked targets, when no kind-3 arrow is left after one was seen.
With GTA2_DIRECT_KEYS=1 the walker and the gun run in the chase view (mission_lib.foot_view), so
every frame of the fight is a third-person one; milestone frames /out/m_<prefix>_*.png.

Run on its own (a job that is already running, its marked car up):
    python3 /work/skills/destroy_vehicle.py [secs]
"""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

EVENTS = []          # (wall time, text) for the runner's summary
BURN_HP = 16000      # mission_lib.CAR_HP_FIRE: the game sets a car alight at damage 16000
BLAST_HP = 4000      # under this a burning target is near its explosion: keep `blast` blocks off.
                     # dv_pc4 backed off at 16000 already and its rounds from 4.5-5.6 blocks did
                     # ~1000 hp per 100 rounds against 16000 in 10 s from 3-4 blocks
BURN_WATCH = 6.0     # out of rounds with the target alight and standing: watch it burn from here


def ev(text):
    EVENTS.append((time.time(), text)); M.mark(f"destroy_vehicle: {text}")


# ------------------------------------------------------------------ what the log says

def job_state():
    """complete (1124 and the district twins), failed, dead or running, from the game's words"""
    ms = M.mission_state()
    if not ms: return "unknown", {}
    if ms["msg"] in M.COMPLETE_KEYS: return "complete", ms
    if ms["msg"] in M.FAILED_KEYS: return "failed", ms
    if ms["health"] == 0 or ms["death"] != 0: return "dead", ms
    if M.LIVES0[0] is not None and ms["lives"] < M.LIVES0[0]: return "dead", ms
    return "running", ms


class JobOver(Exception):
    pass


def default_check():
    o, ms = job_state()
    if o not in ("running", "unknown"): raise JobOver(o)
    return ms


def car_arrows():
    """(slot, x, y) of the mission arrows on vehicles (kind 3)"""
    return [(k, v[2], v[3]) for k, v in M.mission_arrows().items() if v[1] == 3]


def targets(select=None, models=None, me=None):
    """the live target cars in `view: cars` (nearest first): marked ones, or with `models` any car
    of those models that is not the player's; select(c) filters further"""
    out = []
    for c in M.cars():
        if c["hp"] <= 0 or c["driver"] == "P": continue
        if models is not None:
            if c["model"] not in models: continue
        elif c["mark"] is None:
            continue
        if select and not select(c): continue
        out.append(c)
    return out


class Track:
    """per-car history from the `view: cars` samples: (wall time, x, y, hp)"""
    def __init__(self):
        self.h = {}

    def add(self, cs):
        now = time.time()
        for c in cs:
            h = self.h.setdefault(c["id"], [])
            if not h or now - h[-1][0] > 0.15: h.append((now, c["x"], c["y"], c["hp"]))
            del h[:-120]

    def motion(self, cid, span=1.0):
        """(ux, uy, speed in blocks per game second) over the last `span` game seconds"""
        h = self.h.get(cid) or []
        if len(h) < 2: return 0.0, 0.0, 0.0
        t1, x1, y1, _ = h[-1]
        t0, x0, y0 = h[-2][:3]
        for t0, x0, y0, _ in reversed(h[:-1]):
            if (t1 - t0) * D.SPEED >= span: break
        dt = max((t1 - t0) * D.SPEED, 0.05); dx, dy = x1 - x0, y1 - y0; n = math.hypot(dx, dy)
        if n < 0.2: return 0.0, 0.0, 0.0
        return dx / n, dy / n, n / dt

    def standing(self, cid, span, radius):
        """has car cid stayed within `radius` blocks for the last `span` game seconds (and been
        sampled that long)?"""
        h = self.h.get(cid) or []
        if not h: return False
        t1, x1, y1, _ = h[-1]
        old = [e for e in h if (t1 - e[0]) * D.SPEED <= span]
        if len(old) < 3 or (t1 - old[0][0]) * D.SPEED < span * 0.8: return False
        return all(math.hypot(e[1] - x1, e[2] - y1) < radius for e in old)

    def hp_drop_since(self, cid, t):
        """damage done to car cid since wall time t"""
        h = [e for e in (self.h.get(cid) or []) if e[0] >= t]
        return (h[0][3] - h[-1][3]) if len(h) >= 2 else 0


DRIVE_MIN = 90.0     # blocks: nearer goals are walked (every car leg so far ended in a bump, a
                     # wanted level and an arrest: dv_pc5, dv_pc7)
SPOT_KEEP = 300.0    # game seconds a waiting spot is kept while the target never comes within 20


def dwell_spot(track, s, min_dwell=4.0):
    """(x, y, ux, uy): where the target's arrow track shows it standing longest (traffic lights,
    a junction it waits at), weighted against the distance from us, with its heading on the way
    in. dv_pc4 and dv_pc6: the Pizza van stopped again and again on the x 59.5 street (y 113-148);
    mission_lib.ambush_point skips slow samples (it needs 0.8 blocks over six of them) and chose
    spots 100 blocks off. None when it has not stood `min_dwell` game seconds anywhere"""
    if len(track) < 10: return None
    dwell = {}; head = {}
    for i in range(1, len(track)):
        t0, x0, y0 = track[i - 1]; t1, x1, y1 = track[i]
        dt = (t1 - t0) * D.SPEED
        if dt <= 0 or dt > 2.0: continue
        if math.hypot(x1 - x0, y1 - y0) < 0.05:
            c = (int(x1), int(y1)); dwell[c] = dwell.get(c, 0.0) + dt
            if c not in head:
                for j in range(i - 1, max(0, i - 200), -1):
                    dx, dy = x1 - track[j][1], y1 - track[j][2]; n = math.hypot(dx, dy)
                    if n > 1.5: head[c] = (dx / n, dy / n); break
    best = None
    for c, w in dwell.items():
        if w < min_dwell or c not in head: continue
        dd = math.hypot(c[0] + 0.5 - s["x"], c[1] + 0.5 - s["y"])
        score = w / (1.0 + dd / 60.0)
        if best is None or score > best[0]: best = (score, c)
    if not best: return None
    c = best[1]; ux, uy = head[c]
    return (c[0] + 0.5, c[1] + 0.5, ux, uy)


# ------------------------------------------------------------------ moving

def release():
    xdo("keyup", "Control_L"); xdo("keyup", "Up")


def side_step(s, ux, uy, tx, ty, dist=1.8):
    """out of the target's lane: a step across its heading, to the side we already stand on"""
    px, py = -uy, ux
    if (s["x"] - tx) * px + (s["y"] - ty) * py < 0: px, py = -px, -py
    M.cruise_to(s["x"] + px * dist, s["y"] + py * dist, tol=0.4, secs=1.6)


def back_off(s, tx, ty, dist):
    """walk straight away from (tx, ty) to `dist` blocks"""
    dx, dy = s["x"] - tx, s["y"] - ty; n = math.hypot(dx, dy) or 1.0
    k = max(0.0, dist - n) + 0.5
    M.cruise_to(s["x"] + dx / n * k, s["y"] + dy / n * k, tol=0.6, secs=2.5)


def own_car_burning(s, ms):
    return s["driving"] and (s.get("fire", 0) > 0 or M.car_burning(ms))


def drive_toward(world, x, y, tol, budget, view_switch=None):
    """a leg by car toward (x, y): the borrowed car is left at once when it burns (pt6_le2e
    drove on in a burning car for 20 s and blew up with it)"""
    s = D.wait_state()
    ms0 = M.mission_state() or {}
    far = math.hypot(x - s["x"], y - s["y"])
    if s["driving"] and ms0.get("wanted", 0) > 0:
        # dv_pc5, dv_pc7: wanted 1 at the wheel of a borrowed car (a bump near a cop), the cop
        # pulled him out at the next stop: arrested, JOB FAILED. On foot at once
        ev("wanted at the wheel: out, on foot"); hold("Down", 0.4); s = M.leave_car()
    if not s["driving"] and (far < DRIVE_MIN or ms0.get("wanted", 0) > 0):
        return M.walk3(world, x, y, None, tol=max(tol, 6.0), budget=min(120, 10 + far * 0.8))
    if not s["driving"]:
        # only a parked car near by: a kerb wait for a passing one stands on the road edge
        # (dv_pc2: run over at 4.5,103.5 by a car at 4 blocks/s a second into the wait, the
        # pt7_le2b death again). No car: walk (the walker keeps to the pavements)
        if s["parked"] and s["pd"] < 10 and not M.bad_car(s["px"], s["py"]):
            s = M.enter_car3(world, s["px"], s["py"], budget=40)
        if not (s and s["driving"]):
            s = D.wait_state()
            return M.walk3(world, x, y, None, tol=max(tol, 6.0), budget=min(90, 10 + math.hypot(x - s["x"], y - s["y"]) * 0.8))
    ms = M.mission_state() or {}
    if own_car_burning(s, ms):
        ev("our car burns: out"); return M.bail_clear(world, s)
    cell = M.street_cell_near(world, x, y, radius=8)
    gx, gy = (cell[0], cell[1]) if cell else (x, y)
    return M.drive3(world, gx, gy, tol=tol, budget=budget, view_switch=view_switch, slow=True)


def pursue_leg(world, gx, gy, select, models, leave_at, view_switch=None, budget=15.0):
    """one short car leg toward (gx, gy), stopped early when the police want us or a target stands
    within leave_at (or is within 8 blocks)"""
    def stop():
        ms = M.mission_state() or {}
        if ms.get("wanted", 0) > 0: return True
        s = D.wait_state(2)
        if not s: return False
        for c in targets(select, models):
            dd = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
            if dd < 8 or (dd < leave_at and c["v"] < 0.6): return True
        return False
    cell = M.street_cell_near(world, gx, gy, radius=8)
    tx, ty = (cell[0], cell[1]) if cell else (gx, gy)
    return M.drive3(world, tx, ty, tol=3.0, budget=budget, view_switch=view_switch, slow=True, until=stop)


# ------------------------------------------------------------------ the skill

def destroy(world, select=None, models=None, count=1, check=None, secs=600, engage=11.0, stand_off=4.0,
            blast=4.5, leave_at=14.0, stall=10.0, view_switch=None, shot_prefix="dv", ram=True, money0=None):
    """Wreck `count` target cars (all marked cars when count is None).

    select(c): a predicate on the `view: cars` dict; models: count wrecks of these models instead of
    marked cars. check(): the job's own check, raising when the job is over (default JobOver on JOB
    COMPLETE / FAILED / death). Returns 'done', 'no gun', 'timeout' or 'stuck'."""
    check = check or default_check
    t0 = time.time(); tr = Track(); seen = {}; wrecked = set(); fired = 0.0; t_said = 0.0
    shots = set(); arrows_seen = False; ambush = None; stand = None; t_spot = None
    t_fire0 = None; hp_fire0 = None; steps = 0; no_target_since = None; t_close = 0.0
    try: log_off = max(0, os.path.getsize(D.LOG) - 400000)
    except OSError: log_off = 0

    def shot_once(tag):
        if tag in shots: return
        shots.add(tag); M.shot(f"{shot_prefix}_{tag}")

    ev(f"start: count {count}, models {sorted(models) if models else 'marked'}; "
       f"{len(targets(select, models))} in sight, {len(car_arrows())} vehicle arrows")
    try:
        while time.time() - t0 < secs:
            ms = check() or {}
            s = D.wait_state()
            if not s: time.sleep(0.3); continue
            allc = M.cars()
            ts = targets(select, models)
            tr.add([c for c in allc if c["driver"] != "P"])
            for c in ts: seen[c["id"]] = c
            # wrecks: a target seen alive that now shows hp 0, or is gone from the window while
            # its last position was well inside it (the window is 30 blocks)
            by_id = {c["id"]: c for c in allc}
            for cid, c in list(seen.items()):
                if cid in wrecked: continue
                q = by_id.get(cid)
                gone = q is None and math.hypot(c["x"] - s["x"], c["y"] - s["y"]) < 18
                if (q is not None and q["hp"] <= 0) or gone:
                    if gone and models is None and any(math.hypot(a[1] - c["x"], a[2] - c["y"]) > 3.0 for a in car_arrows()):
                        # a marked car out of the list with an arrow still up away from where it
                        # stood: it drove off, it is not wrecked
                        continue
                    if gone and models is not None:
                        # an unmarked roaming car that drove out of sight is no wreck: only a car
                        # last seen burning or badly hit counts
                        if c["hp"] > BURN_HP and c["fire"] == 0: seen.pop(cid); continue
                    wrecked.add(cid)
                    release()
                    ev(f"wrecked {cid} (m{c['model']}) at {c['x']:.1f},{c['y']:.1f}; {len(wrecked)} of {count}")
                    shot_once(f"wreck{len(wrecked)}")
            if count is not None and len(wrecked) >= count:
                return "done"
            arrows = car_arrows() if models is None else []
            if arrows: arrows_seen = True
            if models is None and arrows_seen and not arrows and not ts:
                ev(f"no marked vehicle left ({len(wrecked)} wrecked)"); return "done"

            # ---- the target: nearest in the window, else the nearest vehicle arrow
            tgt = None
            if ts:
                tgt = min(ts, key=lambda c: math.hypot(c["x"] - s["x"], c["y"] - s["y"]))
                tx, ty = tgt["x"], tgt["y"]
                ux, uy, vs = tr.motion(tgt["id"])
                no_target_since = None
            elif arrows:
                _, tx, ty = min(arrows, key=lambda a: math.hypot(a[1] - s["x"], a[2] - s["y"]))
                # its motion from the arrow samples (dv_pc4: a van standing 30 blocks off, out of the
                # cars window, was taken for a moving one and waited for at the ambush spot)
                tr.add([dict(id="arrow", x=tx, y=ty, hp=0)])
                ux, uy, vs = tr.motion("arrow", span=3.0)
                no_target_since = None
            else:
                release()
                no_target_since = no_target_since or time.time()
                if time.time() - no_target_since > 45:
                    return "stuck"
                if models is not None and time.time() - no_target_since > 4:
                    # roaming targets: walk the streets until one of the models shows up
                    ang = (time.time() - t0) * 0.21
                    M.walk3(world, s["x"] + 10 * math.cos(ang), s["y"] + 10 * math.sin(ang), None, tol=2.0, budget=20)
                time.sleep(0.4); continue
            d = math.hypot(tx - s["x"], ty - s["y"])
            if d < 20: t_close = time.time()
            along = ux * (s["x"] - tx) + uy * (s["y"] - ty)          # > 0: we are ahead of it
            lat = abs(ux * (s["y"] - ty) - uy * (s["x"] - tx))
            thp = tgt["hp"] if tgt else ms.get("tcarhp", -1)
            tfire = tgt["fire"] if tgt else ms.get("tcarfire", 0)
            burning = tfire > 0 or (0 < thp < BURN_HP)
            if time.time() - t_said > 5:
                say(f"destroy: target {tgt['id'] if tgt else 'arrow'} {'m%d' % tgt['model'] if tgt else ''} at {tx:.1f},{ty:.1f} "
                    f"hp {thp} fire {tfire} v {vs:.1f} d {d:.1f} along {along:.1f} lat {lat:.1f}; me "
                    f"{'driving' if s['driving'] else 'on foot'} {ms.get('weapon')} ammo {ms.get('ammo')}; "
                    f"{len(wrecked)} wrecked, fired {fired:.0f}s"); t_said = time.time()
            if burning: shot_once("burning")

            # ---- in a car: short pursuit legs at its current position (re-aimed every leg); out
            # when it stands near, or is within 8 blocks, or the police want us
            if s["driving"]:
                release()
                if own_car_burning(s, ms):
                    ev("our car burns: out and clear"); M.bail_clear(world, s); continue
                if ms.get("wanted", 0) > 0:
                    ev("wanted at the wheel: out, on foot"); hold("Down", 0.4); M.leave_car(); M.ensure_view("classic"); continue
                if (d < leave_at and vs < 0.6) or d < 8:
                    hold("Down", 0.4); s = M.leave_car(); ev(f"out of the car {d:.0f} blocks from the target (v {vs:.1f})")
                    M.ensure_view("classic"); M.select_gun(); continue
                if view_switch: view_switch(s)
                pursue_leg(world, tx + ux * min(6.0, 2.0 * vs), ty + uy * min(6.0, 2.0 * vs), select, models, leave_at, view_switch)
                continue


            # ---- on foot: a gun in the hand
            if not M.gun_ready(ms) and not M.select_gun():
                release()
                if burning and vs < 0.5:
                    # dv_pc4: out of rounds with the van alight at 12136 and standing; a burning car
                    # loses about 50 hp a game second by itself: watch it burn out from a safe
                    # distance instead of walking off to a pickup (that run ended at the pickup)
                    if d < BURN_WATCH: back_off(s, tx, ty, BURN_WATCH + 1.0)
                    else: time.sleep(0.5)
                    continue
                ev("no rounds: to a gun pickup")
                M.fetch_gun(world, budget=240)
                if not M.gun_ready():
                    if ram and models is None:
                        ev("no gun anywhere: ramming (the fallback)")
                        r = M.ram_target(world, money0 if money0 is not None else (ms.get("money") or 0), secs=max(60, secs - (time.time() - t0)), view_switch=view_switch)
                        say("ram:", r)
                        return "done" if r == "complete" else "no gun"
                    return "no gun"
                continue

            # ---- far: pursue. dv_pc4-8: the Pizza van roams the whole town (about 1.5 blocks per
            # game second over 30 s, standing half of the time at lights): waiting at a spot of its
            # track found it in 1 of 4 sessions, and 30-second car legs blind to the wanted level got
            # the player arrested twice. So: by car in short legs stopped by the wanted level or the
            # target near (pursue_leg), out near it; on foot while wanted or with no parked car near
            # (a kerb wait got him run over, dv_pc2), waiting at its favourite stop when far
            if d > engage + 2:
                release()
                wanted = ms.get("wanted", 0) > 0
                if not wanted and d > 16:
                    if s["parked"] and s["pd"] < 25 and not M.bad_car(s["px"], s["py"]):
                        s2 = M.enter_car3(world, s["px"], s["py"], budget=40)
                        if s2 and s2["driving"]: ev(f"in a car for the pursuit ({d:.0f} blocks)"); continue
                if d <= 45 or wanted:
                    M.walk3(world, tx, ty, None, tol=engage - 1.5, budget=min(25, 6 + d)); continue
                # far, no car: toward its favourite stop (where it stood longest), re-chosen when stale
                if ambush is None or (time.time() - max(t_spot or 0, t_close) > SPOT_KEEP / D.SPEED):
                    sl = M.objective_slot()
                    trk = M.arrow_track(log_off, sl, 3) if sl is not None else []
                    ap = dwell_spot(trk, s) or M.ambush_point(trk, s)
                    if ap:
                        ambush = ap; stand = M.stand_point(world, ap); t_spot = time.time()
                        ev(f"waiting spot {stand[0]:.1f},{stand[1]:.1f} ({ap[0]:.1f},{ap[1]:.1f}; {len(trk)} samples)")
                if stand:
                    ds = math.hypot(stand[0] - s["x"], stand[1] - s["y"])
                    if ds > 1.2: M.walk3(world, stand[0], stand[1], None, tol=0.8, budget=min(30, 8 + ds)); continue
                    time.sleep(0.4); continue
                M.walk3(world, tx, ty, None, tol=engage - 1.5, budget=30); continue


            # ---- in range
            shot_once("engage")
            if vs > 0.8 and along > 0 and d < 4.5 and lat < 1.3:
                xdo("keyup", "Control_L"); side_step(s, ux, uy, tx, ty); continue      # it comes at us
            if burning and thp < BLAST_HP and d < blast:
                xdo("keyup", "Control_L"); back_off(s, tx, ty, blast + 1.0); continue   # clear of its blast
            lead = min(1.2, 0.35 * vs)
            ax, ay = tx + ux * lead, ty + uy * lead
            t1 = time.time()
            if t_fire0 is None or (tgt and hp_fire0 is None):
                t_fire0 = time.time(); hp_fire0 = thp
            if d > stand_off or vs > 0.5:
                M._aim_walk(ax, ay, fire=True, walk=d > stand_off, secs=0.5)
            else:
                # standing target within stand_off: a short pulse at it keeps the facing true,
                # then fire without walking
                M._aim_walk(ax, ay, fire=True, walk=False, secs=0.5)
                if d < 2.6: xdo("keyup", "Control_L"); hold("Down", 0.35)
            fired += time.time() - t1
            # damage progress
            if thp != hp_fire0:
                t_fire0 = time.time(); hp_fire0 = thp
            elif time.time() - t_fire0 > stall / D.SPEED:
                xdo("keyup", "Control_L"); steps += 1; t_fire0 = time.time()
                if (vs < 0.5 and d > 3.0 or steps % 3 == 0) and not burning:
                    say("destroy: no damage: closer"); M.walk3(world, tx, ty, None, tol=max(2.6, stand_off - 1.5), budget=12)
                else:
                    say(f"destroy: no damage for {stall:.0f} s: side step"); side_step(s, (tx - s["x"]) / max(d, 0.1), (ty - s["y"]) / max(d, 0.1), tx, ty, dist=1.5)
        return "timeout"
    finally:
        release()
        say(f"destroy_vehicle: {len(wrecked)} wrecked in {time.time() - t0:.0f}s, fired {fired:.0f}s")


def main():
    """standalone: the job is running and its marked car is up"""
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 300
    D.start(); s = D.wait_state(40)
    if not s: sys.exit(1)
    D.calibrate_turn()
    world = M.World(os.environ.get("DISTRICT", "wil"))
    M.arm_lives()
    try:
        r = destroy(world, secs=secs)
    except JobOver as e:
        r = str(e)
    M.mark(f"destroy_vehicle standalone: {r}")


if __name__ == "__main__":
    main()
