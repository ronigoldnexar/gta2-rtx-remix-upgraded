#!/usr/bin/env python3
"""Skill: kill marked people (Wave M, `kill_marked`, 23 jobs in docs/missions-catalogue.md).

A job of this kind puts an arrow on one or more characters (`POINT_ARROW_AT (arrow, char)`, kind 2
in `view: arrows`; the renderer's `view: peds` line carries the arrow slot on the ped itself, `:aNN`)
and waits for them to die (`IS_CHARACTER_DEAD`, `CHECK_DEATH_ARR`, a kill counter). This module does
that one step for any job, on the shared runner libraries (`mission_lib`, `drive_lib`, unchanged):

    import skills.kill_marked as K
    r = K.kill_marked(world, select=lambda p: p["gang"] == "police", spare=hiroshi, approach=CLIMB,
                      level=2, check=job_check, secs=150)
    # r: "done" (every selected marked ped down and the arrows gone), "no gun", "timeout"
    #    or "stuck"; check() raises the job's own exception when the job is over

How it fights (each line is a lesson from PLAYTHROUGH-8..10, see docs/playthrough-downtown.md):
  - targets from `view: peds` (own position, alive, on foot), nearest first, a target on the
    player's level preferred; when none is within the 24-block peds window, the kind-2 arrows;
  - out of the car first and a gun in the hand (`select_gun`: the hand can come back empty with
    990 rounds in the inventory), a pickup fetched only when there are no rounds at all;
  - a target on another level: the job's hand-placed `approach` points first (a flight of stairs
    the router presses against, br4), else the multi-level router to the target's level;
  - far (> engage): walk at him with the trigger off (walking keeps the logged facing true);
  - in range: walk at him with the trigger held while over `close` blocks, stand and fire under it;
  - no damage for `stall` seconds (a wall or a railing takes the rounds, pt9_wil6): the next
    `fire_spots` point, else a side step across the line, else closer;
  - a `spare` ped (escort, informant, the inside man) in the line of fire: hold the trigger;
  - the trigger is released the moment the last selected target falls (the inside man walks out
    behind the guards in BANK ROBBERY and the job hangs if he dies), and the step only ends when
    the character arrows are gone or `confirm` seconds have passed with no target in the log.
With GTA2_DIRECT_KEYS=1 the walker and the gun run in the chase view (mission_lib.foot_view), so
every frame of the fight is a third-person one.

Run on its own (a job that is already running, the player near the targets):
    python3 /work/skills/kill_marked.py [secs]
"""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

OFFICER_TYPES = ("cop",)


# ------------------------------------------------------------------ what the log says

def job_state():
    """the job's outcome from the game's own words: complete (1124 and the district twins),
    failed, dead, or running. Not M.outcome: that one calls any +$10,000 a completion, and a
    job can pay on the way (BANK ROBBERY pays $5,000 twice before the end)"""
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


def marked(select=None, on_foot=True):
    """the marked peds still alive in `view: peds` (nearest first), filtered by select(p)"""
    out = []
    for p in M.peds():
        if p["mark"] is None or not M.ped_alive(p): continue
        if on_foot and p["car"] is not None: continue
        if select and not select(p): continue
        out.append(p)
    return out


def level_of_z(z):
    return max(0, int(round(z)) - 1)


def police_near(s, ped_r=12.0):
    """officers on foot within ped_r of (s): their count and the nearest distance"""
    n, best = 0, 99.0
    for p in M.peds():
        if p["type"] in OFFICER_TYPES and M.ped_alive(p):
            d = math.hypot(p["x"] - s["x"], p["y"] - s["y"])
            if d < ped_r: n += 1; best = min(best, d)
    return n, best


def in_line(s, tx, ty, px, py, width=0.9):
    """is (px, py) between the player and the target, within `width` of the line of fire?"""
    dx, dy = tx - s["x"], ty - s["y"]; n = math.hypot(dx, dy)
    if n < 1e-6: return False
    ux, uy = dx / n, dy / n
    along = (px - s["x"]) * ux + (py - s["y"]) * uy
    if along < 0.2 or along > n + 0.5: return False
    return abs((px - s["x"]) * uy - (py - s["y"]) * ux) < width


# ------------------------------------------------------------------ moving

def path_walk(points, secs_each=6.0, retries=1):
    """straight cruise legs through hand-placed points (no router); a miss is retried once from 1.2
    blocks back along the leg (KILLMARK-GETAWAY, kmg14: the walker slowed at the first stair point and
    then stood pressed against the foot of the flight at 193.3,177.9; the router's climb that followed
    brought him up beside the guards and the second one shot him). False at a miss after the retries"""
    k = 0
    while k < len(points):
        x, y = points[k]
        s, ok = M.cruise_to(x, y, tol=0.45 if k < len(points) - 1 else 0.35, secs=secs_each, stop=(k == len(points) - 1))
        if ok:
            k += 1; continue
        xdo("keyup", "Up"); say(f"kill_marked: approach missed {x},{y} (at {s['x']:.2f},{s['y']:.2f} z {s['z']:.2f})")
        if retries <= 0: return False
        retries -= 1
        d = math.hypot(x - s["x"], y - s["y"]) or 1.0
        bx, by = s["x"] + (s["x"] - x) / d * 1.2, s["y"] + (s["y"] - y) / d * 1.2
        if k > 0:
            px, py = points[k - 1]; bx, by = (bx + px) / 2.0, (by + py) / 2.0
        M.cruise_to(bx, by, tol=0.4, secs=3.0)
        say(f"kill_marked: approach backed off to {bx:.1f},{by:.1f}, again")
    xdo("keyup", "Up")
    return True


def release():
    xdo("keyup", "Control_L"); xdo("keyup", "Up")


def side_step(s, tx, ty, k):
    """a step across the line of fire, alternating sides"""
    dx, dy = tx - s["x"], ty - s["y"]; n = math.hypot(dx, dy) or 1.0
    px, py = -dy / n, dx / n
    if k % 2: px, py = -px, -py
    M.cruise_to(s["x"] + px * 1.5, s["y"] + py * 1.5, tol=0.4, secs=3)


# ------------------------------------------------------------------ the skill

def kill_marked(world, select=None, spare=None, count=None, approach=None, level=None, fire_spots=None,
                secs=180, check=None, engage=8.0, close=2.2, stall=8.0, confirm=3.0, shot_prefix="km",
                arrows_count=True):
    """Kill the marked characters picked by select(p) (all marked peds when None).

    spare(p) -> True for peds that must not be hit (the trigger is held off while one stands in
    the line of fire). count: stop after that many kills (else when none is left). approach: the
    job's hand-placed points to the targets' level, walked once; level: that level (target z - 1).
    fire_spots: positions to try in turn when the rounds do no damage. check(): the job's own check,
    raising when the job is over (default: JobOver on JOB COMPLETE/FAILED/death).
    Returns 'done', 'no gun', 'timeout' or 'stuck'."""
    check = check or default_check
    t0 = time.time(); seen = {}; killed = set(); empty_since = None; hp_last = None
    last_progress = time.time(); spot_i = -1; steps = 0; approached = False; fired = 0.0; t_said = 0.0
    shots_taken = set()
    M.mark(f"kill_marked: start ({len(marked(select))} marked in sight, {len(M.char_arrows())} character arrows)")
    try:
        while time.time() - t0 < secs:
            ms = check() or {}
            s = D.wait_state()
            if not s: time.sleep(0.3); continue
            if s["driving"]:
                release(); hold("Down", 0.3); s = M.leave_car(); M.mark("kill_marked: out of the car")
                M.select_gun()
                continue
            ts = marked(select)
            for p in ts: seen[p["id"]] = p
            # kills: a ped seen marked and alive that is now dead or gone from a log that still
            # covers his last position (the peds window is 24 blocks)
            ids = {p["id"] for p in ts}
            allp = {p["id"]: p for p in M.peds()}
            for pid, p in seen.items():
                if pid in ids or pid in killed: continue
                q = allp.get(pid)
                if (q is not None and not M.ped_alive(q)) or (q is None and math.hypot(p["x"] - s["x"], p["y"] - s["y"]) < 18):
                    killed.add(pid); M.mark(f"kill_marked: down {pid} ({p['type']}/{p['gang']}) at {p['x']:.1f},{p['y']:.1f}; {len(killed)} down")
                    if "first" not in shots_taken: M.shot(f"{shot_prefix}_first_down"); shots_taken.add("first")
            if count is not None and len(killed) >= count:
                release(); M.mark(f"kill_marked: {len(killed)} of {count} down"); return "done"
            if not ts:
                xdo("keyup", "Control_L")
                arrows = M.char_arrows() if arrows_count else []
                empty_since = empty_since or time.time()
                if spare:
                    # an arrow on someone who must live (the inside man, an escort) is no target
                    keep = [p for p in M.peds() if M.ped_alive(p) and spare(p)]
                    arrows = [a for a in arrows if not any(math.hypot(a[0] - p["x"], a[1] - p["y"]) < 1.0 for p in keep)]
                pending = [pid for pid in seen if pid not in killed]
                if not arrows and (seen or time.time() - empty_since > confirm):
                    M.mark(f"kill_marked: no marked character left ({len(killed)} down)"); return "done"
                if seen and not pending and time.time() - empty_since > confirm:
                    M.mark(f"kill_marked: every target seen is down ({len(killed)}); {len(arrows)} other character arrows"); return "done"
                if arrows and time.time() - empty_since > confirm:
                    # the targets are beyond the peds window (or in a car): go to the arrow
                    ax, ay = min(arrows, key=lambda a: math.hypot(a[0] - s["x"], a[1] - s["y"]))
                    d = math.hypot(ax - s["x"], ay - s["y"])
                    if d > engage:
                        say(f"kill_marked: no target in sight; to the arrow at {ax:.1f},{ay:.1f} ({d:.0f} blocks)")
                        M.walk3(world, ax, ay, None, tol=engage - 2, budget=min(90, 10 + d * 1.5))
                    else:
                        # a marked ped in a car right here: shoot at the car (the explosion kills him)
                        M._aim_walk(ax, ay, fire=True, walk=d > 4.0, secs=0.5); fired += 0.5
                        if d < 2.5: release(); hold("Down", 0.4)
                    continue
                if not seen and time.time() - empty_since > 30:
                    return "stuck"
                time.sleep(0.3); continue
            empty_since = None
            if not M.gun_ready(ms) and not M.select_gun():
                release(); say("kill_marked: no gun in hand"); M.fetch_gun(world, budget=150)
                if not M.gun_ready(): return "no gun"
                continue
            mylev = M.ped_level(s)
            # nearest, the player's own level first
            tgt = min(ts, key=lambda p: (level_of_z(p["z"]) != mylev, math.hypot(p["x"] - s["x"], p["y"] - s["y"])))
            tlev = level_of_z(tgt["z"]); d = math.hypot(tgt["x"] - s["x"], tgt["y"] - s["y"])
            if time.time() - t_said > 5:
                say(f"kill_marked: target {tgt['id']} {tgt['type']}/{tgt['gang']} hp {tgt['hp']} at {tgt['x']:.1f},{tgt['y']:.1f} L{tlev}, "
                    f"me {s['x']:.1f},{s['y']:.1f} L{mylev}, d {d:.1f}, {ms.get('weapon')} ammo {ms.get('ammo')}, "
                    f"{len(ts)} left, {len(killed)} down, fired {fired:.0f}s"); t_said = time.time()
            if tlev != mylev and abs(tgt["z"] - s["z"]) > 0.7:
                release()
                if approach and not approached:
                    approached = True; M.mark(f"kill_marked: approach to level {level if level is not None else tlev}")
                    if path_walk(approach): continue
                M.walk3(world, tgt["x"], tgt["y"], level if level is not None else tlev, tol=min(engage - 2, max(1.5, d - 1)), budget=60)
                continue
            if d > engage:
                release()
                M.walk3(world, tgt["x"], tgt["y"], None, tol=engage - 2.5, budget=min(60, 8 + d * 1.5))
                continue
            if "engage" not in shots_taken: M.shot(f"{shot_prefix}_engage"); shots_taken.add("engage")
            # someone who must live in the line of fire: walk, trigger off
            blocker = None
            if spare:
                for p in M.peds():
                    if p["id"] != tgt["id"] and M.ped_alive(p) and spare(p) and in_line(s, tgt["x"], tgt["y"], p["x"], p["y"]):
                        blocker = p; break
            if blocker:
                xdo("keyup", "Control_L"); say(f"kill_marked: {blocker['id']} ({blocker['gang']}) in the line of fire: holding")
                side_step(s, tgt["x"], tgt["y"], steps); steps += 1
                continue
            t1 = time.time()
            M._aim_walk(tgt["x"], tgt["y"], fire=True, walk=d > close, secs=0.5)
            fired += time.time() - t1
            hp = tuple(sorted((p["id"], p["hp"]) for p in ts))
            if hp != hp_last: hp_last = hp; last_progress = time.time()
            if time.time() - last_progress > stall / D.SPEED:
                # the rounds hit something else: another spot, a side step, or closer
                xdo("keyup", "Control_L"); last_progress = time.time(); steps += 1
                if fire_spots and spot_i + 1 < len(fire_spots):
                    spot_i += 1; fx, fy = fire_spots[spot_i]
                    say(f"kill_marked: no damage for {stall:.0f} s from {s['x']:.1f},{s['y']:.1f}: to fire spot {fx},{fy}")
                    M.cruise_to(fx, fy, tol=0.4, secs=4)
                elif steps % 3 == 0:
                    say("kill_marked: no damage: closer"); M.walk3(world, tgt["x"], tgt["y"], None, tol=1.2, budget=15)
                else:
                    say("kill_marked: no damage: side step"); side_step(s, tgt["x"], tgt["y"], steps)
        return "timeout"
    finally:
        release()
        say(f"kill_marked: {len(killed)} down in {time.time() - t0:.0f}s, fired {fired:.0f}s")


def main():
    """standalone: the job is running and the player is near the targets"""
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 120
    D.start(); s = D.wait_state(40)
    if not s: sys.exit(1)
    D.calibrate_turn()
    world = M.World(os.environ.get("DISTRICT", "wil"))
    M.arm_lives()     # no arrows baseline: the job's arrows are already up
    try:
        r = kill_marked(world, secs=secs)
    except JobOver as e:
        r = str(e)
    M.mark(f"kill_marked standalone: {r}")


if __name__ == "__main__":
    main()
