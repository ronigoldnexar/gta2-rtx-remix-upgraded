#!/usr/bin/env python3
"""MMM, RUSSIAN SAILORS! (Industrial, bil_re2) in the street-level views, PLAYTHROUGH-10.

The shared runner (mission_play_districts.play_bil_re2) reaches dealers 1-3 but loses the
Z-Type before the crane. The logs of PLAYTHROUGH-9 (pt9_bil1-16, every carhp drop of the
player's car in the renderer's `view: cars` line, with the nearest other car at that moment)
say where the carhp went: about 70 % of it was lost with no other car within 2.6 blocks
(walls, kerbs, poles) and much of it while the car was going backwards: the smooth driver's
three-point turns after a re-route, the stall and press back-offs, the gridlock back-away,
all of them a blind hold of Down. Traffic hitting a car standing in a queue is the smaller
part. This module keeps the shared runner's steps (phone, walk, Z-Type, dealer stops, horn,
crane) and drives every leg with `calm_drive`, the smooth driver with these changes:

- never reverses into what it cannot see: a reverse only with the tail clear (no car in a
  1.5-wide band 4 blocks behind, the cells 1-2.2 blocks behind the tail drivable ground with
  no wall between), in short pulses re-checked each time; otherwise a forward turn or a wait;
- queues: a standing car ahead with a driver is waited for (QUEUE_WAIT game seconds) before
  its cell goes off the route; a re-route starts forward (the cells behind the tail are off
  the route for the plan, so a re-route is not a U-turn in the road);
- a lower cap for the Z-Type (CALM_CAP), and the pull-out waits for a gap in the traffic
  coming up behind.

Usage inside the container (keys_russian_sailors.sh):
    DISTRICT=bil python3 /work/missions/russian_sailors.py
"""
import math, os, re, sys, time
sys.path.insert(0, "/work")
# mission_play_districts is the session (start, calibration, views, the phone, the Z-Type
# door, the dealer stops): imported with no missions to play, so its main loop is empty
sys.argv = sys.argv[:1]
os.environ["DISTRICT"] = "bil"
os.environ["MISSIONS"] = " "
import drive_lib as D
import mission_lib as M
import mission_play_districts as P

say, xdo, hold = D.say, D.xdo, D.hold
world = P.world

CALM_CAP = float(os.environ.get("RS_CAP", "1.8"))       # the Z-Type's top speed, blocks per game second
QUEUE_WAIT = float(os.environ.get("RS_QUEUE", "14"))    # game seconds behind a standing driven car before going round
REAR_REACH = 4.0
STATS = {"rev_pulses": 0, "rev_refused": 0, "fwd_turns": 0, "waits": 0, "replans": 0}

# ---------------------------------------------------------------- what is behind the car

def rear_clear(s, reach=REAR_REACH, check_map=True):
    """True when reversing is safe: no other car in a 1.5-wide band `reach` blocks behind the
    tail (or closing on it from behind within 7 blocks), and the ground 1.0-2.2 blocks behind
    the car's tail is drivable with no wall face on the way"""
    if s["z"] > 3.3:
        # on the Escobar Power Cores deck (level 3, dealer 3): lamps and railings the map does
        # not show; pt10_rs12 lost 1800 in one reverse of 1.3 blocks there. Forward turns only
        return False
    hx, hy = M.heading(s)
    for c in M.cars():
        if c["driver"] == "P": continue
        dx, dy = c["x"] - s["x"], c["y"] - s["y"]
        fwd = dx * hx + dy * hy; lat = -dx * hy + dy * hx
        if -reach < fwd < 0.2 and abs(lat) < 1.5: return False
        if -7.0 < fwd < 0.2 and abs(lat) < 1.2 and c["v"] > 0.5 and (c["hx"] * hx + c["hy"] * hy) > 0.5: return False
    if not check_map: return True
    L = M.ped_level(s)
    cx, cy = int(s["x"]), int(s["y"])
    px, py = cx, cy
    for d in (1.0, 1.6, 2.2):
        x, y = int(s["x"] - hx * d), int(s["y"] - hy * d)
        if (x, y) == (px, py): continue
        k = M.node_kind(world, x, y, L) or M.node_kind(world, x, y, L + 1) or M.node_kind(world, x, y, L - 1)
        if not k: return False
        if abs(x - px) + abs(y - py) == 1 and M.wall_between(world, px, py, L, x - px, y - py): return False
        if abs(x - px) == 1 and abs(y - py) == 1:
            # a diagonal step: both ways round the corner must be open
            if M.wall_between(world, px, py, L, x - px, 0) and M.wall_between(world, px, py, L, 0, y - py): return False
        px, py = x, y
    return True

def reverse(s, steer=None, secs=0.6, why="", check_map=True):
    """reverse in pulses of 0.3 game s with the tail re-checked before each; False when the
    first check refuses"""
    done = 0.0; first = True
    while done < secs - 1e-6:
        s = D.wait_state() or s
        if not rear_clear(s, check_map=check_map):
            if first:
                STATS["rev_refused"] += 1
                say(f"calm: no reversing ({why}): the tail is not clear at {s['x']:.1f},{s['y']:.1f}")
            break
        first = False
        if steer: xdo("keydown", steer)
        hold("Down", 0.3)
        if steer: xdo("keyup", steer)
        done += 0.3; STATS["rev_pulses"] += 1
    return not first

def marked_ahead(s, reach=3.2):
    """a marked character on foot (the dealer) in front of the nose within `reach`"""
    hx, hy = M.heading(s)
    for p_ in M.peds():
        if p_["mark"] is None or p_["car"] is not None: continue
        dx, dy = p_["x"] - s["x"], p_["y"] - s["y"]
        f = dx * hx + dy * hy; l = -dx * hy + dy * hx
        if -0.3 < f < reach and abs(l) < 1.8: return True
    return False

def forward_turn(steer, secs=0.3):
    """a crawl forward with the wheel hard over (instead of a three-point turn); never toward
    the dealer (pt10_rs13 ran dealer 2 over with one: 3730, JOB FAILED)"""
    s = D.wait_state()
    if s and marked_ahead(s):
        say("calm: no forward turn: the marked character is in front"); hold("space", 0.3); time.sleep(0.4); return
    STATS["fwd_turns"] += 1
    xdo("keydown", steer); xdo("keydown", "Up"); time.sleep(secs); xdo("keyup", "Up"); xdo("keyup", steer)

def gap_behind(s, secs=6.0):
    """before pulling out from a stop: wait (up to `secs` game seconds) while a car comes up
    behind in the lane within 8 blocks"""
    t0 = time.time()
    while time.time() - t0 < secs / D.SPEED:
        hx, hy = M.heading(s); busy = None
        for c in M.cars():
            if c["driver"] == "P" or c["v"] < 0.6: continue
            dx, dy = c["x"] - s["x"], c["y"] - s["y"]
            fwd = dx * hx + dy * hy; lat = -dx * hy + dy * hx
            if -8.0 < fwd < -0.5 and abs(lat) < 1.3 and (c["hx"] * hx + c["hy"] * hy) > 0.5: busy = (fwd, c); break
        if not busy: return
        say(f"calm: a car coming up {-busy[0]:.1f} behind at {busy[1]['v']:.1f}: waiting for the gap")
        time.sleep(0.5); s = D.wait_state() or s

# ---------------------------------------------------------------- the driver

def calm_drive(world_, tx, ty, tol=2.0, budget=240, view_switch=None, slow=False, precious=False, until=None):
    """mission_lib.drive3_smooth with the reversing guarded, the queues waited for and the
    re-routes started forward (see the module's docstring). Same signature as M.drive3."""
    if M.CUR_VIEW[0] == "classic": M.ensure_view("third")
    t0 = time.time(); s = D.wait_state()
    if not s: return s
    if not s["driving"]: return s
    cap = min(CALM_CAP, 4.0) if (slow or precious) else min(M.FAST_CAP, M.SMOOTH_CAP)
    FLAGS = [[]]

    def plan(s, forward=True):
        saved = M.EDGE_COST; M.EDGE_COST = M.SMOOTH_EDGE_COST
        added = []
        if forward and math.hypot(tx - s["x"], ty - s["y"]) > 4.0:
            # a re-route starts forward: the cells behind the tail are off the plan
            hx, hy = M.heading(s); here = (int(s["x"]), int(s["y"]))
            for d in (1.0, 1.7):
                c = (int(s["x"] - hx * d), int(s["y"] - hy * d))
                if c != here and c not in M.CAR_AVOID: M.CAR_AVOID.add(c); added.append(c)
        try:
            path = M.car_route(world, s, tx, ty)
            if added and (not path or abs(path[-1][0] - int(tx)) + abs(path[-1][1] - int(ty)) > 2):
                for c in added: M.CAR_AVOID.discard(c)
                added = []
                path = M.car_route(world, s, tx, ty)
        finally:
            M.EDGE_COST = saved
            for c in added: M.CAR_AVOID.discard(c)
        path = M.unjog(world, path)
        pts = [(s["x"], s["y"])] + M.lane_points(world, path)[1:]
        if math.hypot(pts[-1][0] - tx, pts[-1][1] - ty) > 0.3: pts.append((tx, ty))
        Pp = D.dense_path(pts)
        info = {}
        for c in path:
            k = M.node_kind(world, c[0], c[1], c[2])
            info[(c[0], c[1])] = ((k is not None and k[0] == "slope"), bool(M.edge_cell(world, c[0], c[1], c[2])) if k else False)
        FLAGS[0] = [info.get((int(px), int(py)), (False, False)) for px, py in Pp]
        return Pp, D.path_headings(Pp)

    Pth, H = plan(s); j = 0
    say(f"calm: {len(Pth) * D.STEP:.0f} blocks of path to {tx:.1f},{ty:.1f} (cap {cap})")
    if precious: gap_behind(s)
    up = [False]; hist = [(time.time(), s["x"], s["y"])]; hp_hist = []; last_hp = -1
    hit_until = 0.0; stall_t = None; stalls = 0; pins = []; burn_said = False; replans = 0
    queue_t = None; near_t = None; mark_said = [False]; ahead_now = [None]; loops = 0
    queued = [None]; wait_until = [0.0]; parked_seen = set(); turn_waits = [0]; cop_said = [False]

    def keyup_all():
        for k in ("Up", "Down", "Left", "Right"): xdo("keyup", k)
        up[0] = False

    def throttle(on):
        if on and not up[0]: xdo("keydown", "Up"); up[0] = True
        elif not on and up[0]: xdo("keyup", "Up"); up[0] = False

    def replan(s2, why, forward=True):
        nonlocal Pth, H, j, replans
        keyup_all()
        replans += 1; STATS["replans"] += 1; Pth, H = plan(s2, forward); j = 0
        say(f"calm: re-route ({why}) at {s2['x']:.1f},{s2['y']:.1f}")

    try:
        while s and s["driving"] and time.time() - t0 < budget:
            dgoal = math.hypot(tx - s["x"], ty - s["y"])
            if dgoal < max(tol, M.SMOOTH_MIN_TOL): break
            loops += 1
            if until and loops % 8 == 0 and until(): say("calm: the watched condition holds: stopping"); break
            marked = [p_ for p_ in M.peds() if p_["mark"] is not None and p_["car"] is None]
            if dgoal < 1.6 and any(abs(p_["x"] - s["x"]) < 1.3 and abs(p_["y"] - s["y"]) < 1.3 for p_ in marked):
                say(f"calm: {dgoal:.1f} from the goal with the marked character beside the car: there"); break
            if dgoal < 2.0:
                near_t = near_t or time.time()
                if time.time() - near_t > 6.0 / D.SPEED: say(f"calm: {dgoal:.1f} from the goal for 6 s: there"); break
            else: near_t = None
            j, lat = D.nearest_index(Pth, j, s["x"], s["y"])
            if lat > 2.2 or (j >= len(Pth) - 2 and dgoal > tol + 1.0):
                if replans > 60: say("calm: too many re-routes; giving up"); break
                replan(s, f"{lat:.1f} off the path"); continue
            now = time.time()
            old = [h for h in hist if now - h[0] >= 0.3]
            ref = old[-1] if old else hist[0]
            v = math.hypot(s["x"] - ref[1], s["y"] - ref[2]) / max((now - ref[0]) * D.SPEED, 0.1)
            mine = next((c for c in M.cars() if c["driver"] == "P"), None)
            if mine is not None and math.hypot(mine["x"] - s["x"], mine["y"] - s["y"]) < 1.5: v = mine["v"]
            if view_switch and v < 0.3 and not M.carjackers(s, False, 12.0): keyup_all(); view_switch(s)
            ms = M.mission_state() or {}
            hp = ms.get("carhp", -1)
            cap_now = cap
            if now < hit_until: cap_now = min(cap_now, M.HIT_SLOW)
            if precious and 0 <= hp < M.CARE_HP: cap_now = min(cap_now, M.CARE_CAP)
            final_left = (len(Pth) - 1 - j) * D.STEP
            nearf = FLAGS[0][j:j + int(3.0 / D.STEP)]
            if any(f[0] for f in nearf): cap_now = min(cap_now, M.RAMP_CAP)
            if precious and any(f[1] for f in nearf): cap_now = min(cap_now, M.NARROW_CAP)
            vt = D.speed_target(Pth, H, j, cap_now, end_tol=max(0.3, tol * 0.5))
            if precious and dgoal < 3.5: vt = min(vt, 0.5 + 0.4 * dgoal)
            if time.time() < wait_until[0]: vt = 0.0
            for p_ in M.peds():
                if p_["mark"] is None or p_["car"] is not None: continue
                hx7, hy7 = M.heading(s); dx7, dy7 = p_["x"] - s["x"], p_["y"] - s["y"]
                f7 = dx7 * hx7 + dy7 * hy7; l7 = -dx7 * hy7 + dy7 * hx7
                if 0.3 < f7 < 1.3 + v * 0.6 and abs(l7) < 0.9:
                    vt = 0.0
                    if not mark_said[0]: say(f"calm: the marked character {f7:.1f} ahead: stopping short"); mark_said[0] = True
                    break
            else: mark_said[0] = False
            gx0, gy0 = D.lookahead(Pth, j, v)
            hx0, hy0 = M.heading(s)
            a0 = math.atan2(hx0 * (gy0 - s["y"]) - hy0 * (gx0 - s["x"]), hx0 * (gx0 - s["x"]) + hy0 * (gy0 - s["y"]))
            ahead = M.traffic_ahead(s, v) if abs(a0) < 0.9 else None; ahead_now[0] = ahead
            if ahead is not None:
                gap, vo, car_ = ahead
                vt = min(vt, max(0.0, vo + (gap - M.TRAFFIC_GAP) * 0.9))
                if car_["driver"] == "-" and car_["v"] < 0.1 and car_["id"] not in parked_seen:
                    parked_seen.add(car_["id"]); M.CAR_AVOID.add((int(car_["x"]), int(car_["y"])))
                    keyup_all(); replan(s, f"a parked car {gap:.1f} ahead"); continue
                if vo < 0.15 and v < 0.25 and gap < M.TRAFFIC_GAP + 1.2:
                    # a standing car with a driver: a queue (it moves on) or a jam; waited for
                    queue_t = queue_t or time.time()
                    if time.time() - queue_t > QUEUE_WAIT / D.SPEED:
                        hx6, hy6 = M.heading(s)
                        for k6 in (gap - 0.4, gap, gap + 0.6):
                            M.CAR_AVOID.add((int(s["x"] + hx6 * k6), int(s["y"] + hy6 * k6)))
                        qn = queued[0]
                        queued[0] = (s["x"], s["y"], (qn[2] + 1) if qn and math.hypot(qn[0] - s["x"], qn[1] - s["y"]) < 1.0 else 1)
                        if queued[0][2] >= 3:
                            for k6 in (1.0, 2.0, 3.0, 4.0):
                                for l6 in (-1.0, 0.0, 1.0):
                                    M.CAR_AVOID.add((int(s["x"] + hx6 * k6 - hy6 * l6), int(s["y"] + hy6 * k6 + hx6 * l6)))
                            keyup_all(); reverse(s, None, 0.9, "gridlock")
                            queued[0] = None; say("calm: gridlock ahead: the band ahead off the route")
                        queue_t = None; keyup_all(); replan(D.wait_state() or s, f"a standing car {gap:.1f} ahead (waited)", forward=False); continue
                else: queue_t = None
            else: queue_t = None
            # never touch a police car (pt10_rs11: pressed against a cop car at the Power Cores
            # entrance, wanted level 1, pulled out and arrested within two seconds): a police car
            # within 3.2 ahead of the nose, in a band 1.6 wide each side, stops the car
            hxp, hyp = M.heading(s)
            for c in M.cars():
                if c["driver"] == "P" or c["model"] not in M.POLICE_MODELS: continue
                dxp, dyp = c["x"] - s["x"], c["y"] - s["y"]
                fp = dxp * hxp + dyp * hyp; lp = -dxp * hyp + dyp * hxp
                if 0.0 < fp < 3.2 and abs(lp) < 1.6:
                    vt = 0.0
                    if not cop_said[0]: say(f"calm: a police car {fp:.1f} ahead: stopping clear of it"); cop_said[0] = True
                    break
            else: cop_said[0] = False
            if v < 2.4 and final_left > 3.0:
                jack = M.carjackers(s, ms.get("wanted", 0) > 0, 4.5)
                if jack and not (ahead is not None and ahead[0] < M.TRAFFIC_GAP + 0.5): vt = max(vt, 2.4)
            gx, gy = D.lookahead(Pth, j, v)
            if final_left < 1.5: gx, gy = tx, ty
            hx, hy = M.heading(s); dx, dy = gx - s["x"], gy - s["y"]
            a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
            steer = "Right" if a > 0 else "Left"
            if abs(a) > 1.9 or (abs(a) > 1.1 and v < 0.8 and dgoal < 3.0) or (abs(a) > 0.9 and v < 1.0 and M.blocked_ahead(world, s)):
                hb_ = M.heading(s)
                if any(math.hypot(p_["x"] - s["x"], p_["y"] - s["y"]) < 3.0 and (p_["x"] - s["x"]) * hb_[0] + (p_["y"] - s["y"]) * hb_[1] < 0.5 for p_ in marked):
                    throttle(False); hold("space", 0.4)
                    if dgoal < 3.0: say(f"calm: no reversing beside the marked character; {dgoal:.1f} from the goal: there"); break
                    forward_turn(steer, 0.25); s = D.wait_state(); continue
                throttle(False)
                if v > 1.0: hold("space", 0.3); time.sleep(0.2)
                rkey = "Left" if a > 0 else "Right"
                if reverse(s, rkey, 0.6, "turn"):
                    turn_waits[0] = 0
                elif not M.blocked_ahead(world, s, 1.2) and not (ahead is not None and ahead[0] < M.TRAFFIC_GAP + 0.3):
                    forward_turn(steer, 0.3)
                else:
                    # neither way: wait for the traffic behind to pass; then a reverse with only the
                    # cars checked (the map test can refuse a kerb or a pavement edge: pt10_rs8 stood
                    # 100 s on the pavement at 122.7,113.8), then a forward turn whatever is ahead
                    turn_waits[0] += 1; STATS["waits"] += 1
                    if turn_waits[0] >= 8:
                        forward_turn(steer, 0.35); turn_waits[0] = 0
                    elif turn_waits[0] >= 4 and reverse(s, rkey, 0.6, "boxed in, cars only", check_map=False):
                        pass
                    else:
                        hold("space", 0.3); time.sleep(0.5)
                    if turn_waits[0] % 6 == 0: replan(D.wait_state() or s, "boxed in", forward=False)
                time.sleep(0.15)
            else:
                if v > vt + 0.3:
                    throttle(False); hold("Down", min(0.45, 0.1 + 0.18 * (v - vt)))
                elif v < vt - 0.25 and abs(a) < 1.0: throttle(True)
                elif abs(a) >= 1.0 and v > 1.0: throttle(False)
                elif v >= vt: throttle(False)
                elif abs(a) >= 1.0: throttle(True)
                pulse = min(0.22, 0.04 + 0.22 * abs(a)) if abs(a) > 0.04 else 0.0
                if abs(a) > 0.04: xdo("keydown", steer)
                if up[0] and vt <= 2.7 and v > vt - 0.8:
                    time.sleep(min(0.1, pulse) if pulse else 0.1); throttle(False); time.sleep(max(0.0, pulse - 0.1))
                else: time.sleep(pulse)
                if abs(a) > 0.04: xdo("keyup", steer)
            time.sleep(0.07)
            s2 = D.wait_state()
            if not s2: break
            hist.append((time.time(), s2["x"], s2["y"])); del hist[:-20]
            ms2 = M.mission_state() or {}
            hp, cf = ms2.get("carhp", -1), ms2.get("carfire", -1)
            if hp >= 0:
                if last_hp >= 0 and last_hp - hp > 250 and cf <= 0:
                    hit_until = time.time() + M.HIT_SLOW_SECS / D.SPEED
                    if precious: cap = max(M.CARE_CAP, cap - 0.2)
                    near_c = min((math.hypot(c["x"] - s2["x"], c["y"] - s2["y"]) for c in M.cars() if c["driver"] != "P"), default=99.0)
                    say(f"calm: hit: carhp {last_hp} -> {hp} at {s2['x']:.1f},{s2['y']:.1f} (v {v:.1f}, target {vt:.1f}, nearest car {near_c:.1f}); cap {cap:.1f}")
                    M.DRIVE_LOG.append((time.time(), "hit", s2["x"], s2["y"], hp))
                last_hp = hp
                hp_hist.append((time.time(), hp, s2["x"], s2["y"])); del hp_hist[:-12]
                rec = [h for h in hp_hist if time.time() - h[0] <= 0.8 / D.SPEED]
                if rec and (rec[0][1] - hp > 450 or (rec[0][1] - hp > 250 and up[0])) and math.hypot(rec[0][2] - s2["x"], rec[0][3] - s2["y"]) < 0.5 and cf <= 0:
                    if math.hypot(tx - s2["x"], ty - s2["y"]) < 2.5:
                        say("calm: pressed near the goal: there"); keyup_all(); s = s2; break
                    say(f"calm: pressed at {s2['x']:.1f},{s2['y']:.1f} (carhp {rec[0][1]} -> {hp})")
                    keyup_all(); hx5, hy5 = M.heading(s2)
                    for k5 in (0.8, 1.4): M.CAR_AVOID.add((int(s2["x"] + hx5 * k5), int(s2["y"] + hy5 * k5)))
                    if not reverse(s2, ("Left" if a > 0 else "Right") if abs(a) > 0.15 else None, 0.9, "pressed"):
                        hold("space", 0.3); wait_until[0] = time.time() + 2.0 / D.SPEED
                    time.sleep(0.15); hp_hist.clear(); stall_t = None
                    s2 = D.wait_state(); replan(s2, "pressed"); s = s2; continue
            burning = cf > 0 or s2.get("fire", 0) > 0
            if burning:
                left = (hp / 100.0) if hp >= 0 else 0.0
                togo = (len(Pth) - 1 - j) * D.STEP
                eta = togo / 1.6 + 6.0
                if precious and M.KEEP_BURNING[0] and left > eta + M.BURN_MARGIN:
                    if not burn_said:
                        say(f"calm: the car burns (carhp {hp}: {left:.0f} s left), {togo:.0f} blocks to go: on")
                        M.mark(f"the mission car burns: {left:.0f} s left, {togo:.0f} blocks to go, driving on"); burn_said = True
                else:
                    say(f"calm: the car is burning (carfire {cf}, carhp {hp}: {left:.0f} s left); out")
                    M.mark(f"the car is on fire (carhp {hp}): out and clear")
                    keyup_all()
                    if precious: return M.bail_clear(world, s2)
                    s2 = M.flee_fire(world, s2)
                    if not (s2 and s2["driving"]): return s2
                    replan(s2, "a new car"); s = s2; last_hp = -1; continue
            moved = math.hypot(s2["x"] - s["x"], s2["y"] - s["y"])
            if up[0] and moved < 0.04:
                stall_t = stall_t or time.time()
                if time.time() - stall_t > 1.0 / D.SPEED:
                    stalls += 1; stall_t = None; keyup_all()
                    if math.hypot(tx - s2["x"], ty - s2["y"]) < 2.0:
                        say("calm: stopped near the goal: there"); s = s2; break
                    pins.append((s2["x"], s2["y"]))
                    nearp = [p for p in pins if math.hypot(p[0] - s2["x"], p[1] - s2["y"]) < 1.2]
                    if len(nearp) >= 8:
                        say(f"calm: pinned at {s2['x']:.1f},{s2['y']:.1f} for {len(nearp)} stalls: giving up this drive")
                        M.mark(f"drive pinned at {s2['x']:.1f},{s2['y']:.1f}: giving up")
                        reverse(s2, None, 0.6, "pinned"); return D.wait_state()
                    time.sleep(0.9); s3 = D.wait_state()
                    if s3 and math.hypot(s3["x"] - s2["x"], s3["y"] - s2["y"]) > 0.3: s = s3; continue
                    if ahead_now[0] is not None:
                        say(f"calm: stopped at {s2['x']:.1f},{s2['y']:.1f} behind traffic: waiting"); time.sleep(0.8); s = D.wait_state(); continue
                    say(f"calm: stopped at {s2['x']:.1f},{s2['y']:.1f} (stall {stalls})")
                    if len(nearp) >= 3:
                        hx3, hy3 = M.heading(s2)
                        for k3 in (0.8, 1.4): M.CAR_AVOID.add((int(s2["x"] + hx3 * k3), int(s2["y"] + hy3 * k3)))
                    if not reverse(s2, ("Left" if a > 0 else "Right") if abs(a) > 0.15 else None, 0.9, "stall"):
                        time.sleep(0.6)
                    time.sleep(0.15); hp_hist.clear()
                    s2 = D.wait_state(); replan(s2, "stall"); s = s2; continue
            else:
                stall_t = None
            s = s2
    finally:
        keyup_all()
    if not (s and s["driving"]):
        sx_ = D.wait_state() or {}
        say(f"calm: out of the car at {sx_.get('x', 0):.1f},{sx_.get('y', 0):.1f}")
        M.mark("out of the car during the drive")
        return sx_ or s
    if time.time() - t0 >= budget: say(f"calm: budget {budget} s spent, {math.hypot(tx - s['x'], ty - s['y']):.1f} from the goal")
    hold("space", 0.8 if precious else 0.6)
    say(f"calm: stats {STATS}")
    return D.wait_state()

# every drive of the job (the dealer legs, the "not coming" spots, the crane, the door
# helpers of mission_play_districts) goes through calm_drive
M.drive3 = calm_drive

# ---------------------------------------------------------------- the job

def carhp():
    return (M.mission_state() or {}).get("carhp", -1)

def back_out_of_alley():
    """the Z-Type stands in the two-wide alley at 47-48 x 67-78 facing south; back it out
    north to the road on rows 65-66 in short pulses (the shared runner's 0.6 s holds came
    out fast and scraped: pt9_bil13 -1350 between the alley and the road)"""
    M.mark("the Z-Type backs out of its alley to the road")
    still = 0
    for _ in range(40):
        s0 = D.wait_state()
        if s0["y"] < 66.6: break
        hold("Down", 0.3); time.sleep(0.15); s1 = D.wait_state()
        if math.hypot(s1["x"] - s0["x"], s1["y"] - s0["y"]) < 0.04:
            still += 1
            if still >= 3: break
        else: still = 0
    hold("space", 0.4); s = D.wait_state()
    say(f"backed out to {s['x']:.1f},{s['y']:.1f} (carhp {carhp()})")
    return s

DEALERS = [(95.5, 171.5), (46.0, 187.0), (13.5, 233.5), (85.0, 147.0)]   # bil_re2.mis CREATE_CHAR

def enter_ztype(cx, cy, budget=300):
    """the shared door tries, without the developer door warp (pt10_rs1: F9 put him in a
    passing police car, which enter_parked then drove into the Z-Type's alley)"""
    os.environ["WARP_OK"] = "0"
    try: return P.enter_parked(cx, cy, budget=budget, why="the Z-Type")
    finally: os.environ["WARP_OK"] = "1"

def play(entry):
    """the shared play_bil_re2's steps with calm_drive and the alley back-out above"""
    money0 = P.money()
    M.SLOW_CAP = 2.0; M.FAST_CAP = 4.0
    M.CAR_AVOID.update({(xx, yy) for xx in range(54, 58) for yy in range(141, 166)})   # the dealer-1 flyover (pt8_bil13/14)
    M.CAR_AVOID.update({(xx, yy) for xx in range(58, 71) for yy in range(88, 93)})     # the car-shop strip (pt8_bil22)
    o = P.wait_arrow(30, kinds=(3, 4))
    car_at = (o[0], o[1]) if o else (48.0, 73.0)
    s = D.wait_state()
    if s["z"] > 3.2 and not (s.get("parked") and s["pd"] < 8):
        near = M.street_cell_near(world, s["x"], s["y"], radius=12)
        if near:
            say(f"the phone's terrace is at z={s['z']:.1f}; developer warp down to the street at {near[0]},{near[1]}")
            P.set_view("classic"); s = M.scene_warp(near[0], near[1], near[2], "down from the rooftop phone"); P.set_view("third")
    if not s["driving"]:
        M.mark("walking to the Z-Type")
    o = M.objective()
    if o and o[3] in (3, 4): car_at = (o[0], o[1])
    s = M.walk3(world, car_at[0], car_at[1], None, tol=2.2, budget=480)
    s = enter_ztype(car_at[0], car_at[1], budget=300)
    if not (s and s["driving"]): return "stuck: the Z-Type not entered"
    P.FP["until"] = -1           # no first-person stretch: a view change is 3.4 s with no steering
    M.shot(f"{entry['mission']}_incar"); SHEET.append(("in the Z-Type", f"m_{entry['mission']}_incar.png"))
    t0 = time.time()
    while time.time() - t0 < 20:
        o = M.objective(); s = D.wait_state()
        if o and math.hypot(o[0] - s["x"], o[1] - s["y"]) > 3.0: break
        time.sleep(0.5)
    s = D.wait_state()
    if s["driving"] and math.hypot(s["x"] - 48.0, s["y"] - 73.0) < 3.0:
        s = back_out_of_alley()
        if s["y"] < 67.5:
            for yy in range(67, 79):
                for xx in (46, 47, 48, 49): M.CAR_AVOID.add((xx, yy))
    say(f"carhp at the start of the dealer legs: {carhp()}")
    stage = 0; t_all = time.time()
    while time.time() - t_all < 2400:
        out, ms = M.outcome(money0)
        if out == "dead" and P.not_over(money0): out = "running"
        if out != "running": return out
        s = D.wait_state()
        if not s["driving"]:
            o = M.objective()
            tc_ = (ms or {}).get("tcar") or (0.0, 0.0)
            if o and ((o[3] in (3, 4) and ms and ms["msg"] in ("3525",)) or o[3] == 0 or (tc_[0] > 0 and math.hypot(o[0] - tc_[0], o[1] - tc_[1]) < 1.5)):
                M.mark("back to the Z-Type"); s = enter_ztype(o[0], o[1], budget=420); continue
        o = P.wait_arrow(40)
        if o is None:
            time.sleep(2.0); continue
        x, y, z, kind = o[0], o[1], o[2], o[3]
        s = D.wait_state() or s
        if kind == 0 and s["driving"] and stage < 4 and math.hypot(x - s["x"], y - s["y"]) < 4.0:
            # after an arrest the arrow on the Z-Type comes back as kind 0 and stays on the car
            # once he is in it again (pt10_rs11: 95 'not handled' at the Power Cores with the
            # Z-Type driven and dealer 3 waiting): the dealer's own spawn point
            x, y = DEALERS[stage]; kind = 2
            say(f"the arrow is on the car (kind 0); dealer {stage+1} at his spawn point {x},{y}")
        if kind in (2, 3, 4) and stage < 4:
            M.mark(f"dealer {stage+1}: by car to {x:.1f},{y:.1f} (carhp {carhp()})")
            key0 = M.objective_key(); m0 = P.msg()
            leg_avoid = set()
            if stage == 2:
                # dealer 3 (the Power Cores deck): up the east ramp (52-55 x 224-231, then the deck
                # road on rows 221-222 westward), not the west ramp at 5-8 x 211-218, where pt10_rs12
                # stood 30 s in a queue on the slope and was rammed for 4300 (pt9 lost 3000-7000 on
                # the turns at 25-33 x 197-208 before it)
                leg_avoid = {(xx, yy) for xx in range(3, 10) for yy in range(208, 224)} - M.CAR_AVOID
                M.CAR_AVOID.update(leg_avoid)
            sp = P.dealer_stop(x, y, s)
            say(f"dealer {stage+1} at {x:.1f},{y:.1f}: the car stops at {sp}")
            if sp: s = calm_drive(world, sp[0], sp[1], tol=0.6, budget=480, slow=True, precious=True)
            else: s = calm_drive(world, x, y, tol=2.6, budget=480, slow=True, precious=True)
            M.CAR_AVOID.difference_update(leg_avoid)
            M.shot(f"{entry['mission']}_dealer{stage+1}")
            t0 = time.time(); boarded = False; spot = 0; t_spot = time.time()
            while time.time() - t0 < 160:
                s_now = D.wait_state() or s
                if not s_now["driving"]:
                    # pulled out (pt10_rs9: the police at dealer 1) or out of a burning car: the
                    # loop above takes him back to the Z-Type; horns from the pavement do nothing
                    say(f"dealer {stage+1}: not in the car; back to the Z-Type first"); break
                cur = P.msg()
                if cur != m0 and cur in ("3527", "3529", "3531", "3533", "3528", "3530", "3532", "3534"): boarded = True
                if M.objective_key() != key0 and boarded: break
                if time.time() - t_spot > 20 and not boarded:
                    spot += 1; t_spot = time.time()
                    ang = spot * 1.5708
                    px, py = x + 2.2 * math.cos(ang), y + 2.2 * math.sin(ang)
                    s_side = dict(s); s_side["x"], s_side["y"] = px, py
                    sp3 = P.dealer_stop(x, y, s_side)
                    if sp3: px, py = sp3
                    say(f"dealer {stage+1}: not coming; moving the car to {px:.1f},{py:.1f} (spot {spot})")
                    s = calm_drive(world, px, py, tol=1.0, budget=40, slow=True, precious=True)
                o3 = M.objective()
                if o3 and math.hypot(o3[0] - x, o3[1] - y) > 8.0:
                    boarded = True; break
                if M.objective_key() != key0 or cur == "3526":
                    M.horn(2); time.sleep(2.5)
                else:
                    o2 = M.objective()
                    if o2 and math.hypot(o2[0] - s["x"], o2[1] - s["y"]) > 3.2:
                        sp2 = P.dealer_stop(o2[0], o2[1], s)
                        if sp2: s = calm_drive(world, sp2[0], sp2[1], tol=0.6, budget=60, slow=True, precious=True)
                    M.horn(1); time.sleep(2.0)
                out, ms = M.outcome(money0)
                if out == "dead" and P.not_over(money0): out = "running"; break
                if out != "running": return out
            say(f"dealer {stage+1}: {'boarded' if boarded else 'not confirmed'} after {time.time()-t0:.0f}s (carhp {carhp()})")
            o4 = M.objective()
            if boarded or (o4 and math.hypot(o4[0] - x, o4[1] - y) > 8.0):
                stage += 1
                if boarded and carhp() > 0: SHEET.append((f"dealer {stage} aboard (carhp {carhp()})", f"m_{entry['mission']}_dealer{stage}.png"))
            else: M.mark(f"dealer {stage+1} not aboard: the same dealer again")
            continue
        if kind not in (1, 2, 3, 4):
            say(f"arrow of kind {kind} at {x:.1f},{y:.1f}: not handled"); time.sleep(2.0); continue
        if kind == 1 or stage >= 4:
            if math.hypot(x - 135.5, y - 5.5) > 4.0:
                say(f"arrow of kind {kind} at {x:.1f},{y:.1f} with {stage} dealers counted: not the crane box; waiting"); time.sleep(2.0); continue
            M.mark(f"to the crane box at {x:.1f},{y:.1f} (carhp {carhp()})")
            s = calm_drive(world, x, y, tol=2.0, budget=600, slow=True, precious=True)
            ok, s = P.creep_box(x, y, 7.0, 7.0, money0, secs=40)
            M.shot(f"{entry['mission']}_cranebox"); SHEET.append((f"in the crane box (carhp {carhp()})", f"m_{entry['mission']}_cranebox.png"))
            M.leave_car(); M.mark("out of the car in the crane box")
            s = D.wait_state()
            ex, ey = M.escape_point(world, s["x"], s["y"], 1, dist=6)
            M.cruise_to(ex, ey, tol=1.0, secs=8)
            # the crane, seen from beside the box (the chase view keeps on the player)
            t_c = time.time(); shots = 0
            while time.time() - t_c < 240:
                o_, ms = M.outcome(money0)
                if o_ != "running": break
                if shots < 3 and time.time() - t_c > 4 + 6 * shots:
                    M.shot(f"{entry['mission']}_crane{shots}"); shots += 1
                if P.msg() == "3538":
                    s = P.enter_parked(x, y, budget=90, why="the Z-Type in the crane box")
                    if s and s["driving"]:
                        P.creep_box(x, y, 7.0, 7.0, money0, secs=40); M.leave_car()
                        s = D.wait_state(); ex, ey = M.escape_point(world, s["x"], s["y"], 1, dist=6); M.cruise_to(ex, ey, tol=1.0, secs=8)
                time.sleep(1.0)
            if shots: SHEET.append(("the crane", f"m_{entry['mission']}_crane{min(shots - 1, 1)}.png"))
            return o_
    return "timeout"

SHEET = []

# The Russians' two rooftop phones stand two cells apart on the level-5 terrace (RUSSIAN SAILORS
# at 189.5,76.5, HOT DOG HOMICIDE at 187.5,76.5). The terrace has three stairs: from the north
# (column 187, rows 73-74) and the west (row 77, columns 185-186) they end beside the HOT DOG
# phone, and pt10_rs1's walker, unsticking at 187.5,72.5, stepped on it: 3400 (the HOT DOG
# brief), then 3103 on the right phone ("you are working a Russian contract"), no Z-Type job.
# Only the east stair (row 75, from 197 up to 190) is left to the walker.
TERRACE_BLOCK = {(187, 73), (187, 74), (187, 75), (185, 77), (186, 77), (187, 77)}
WRONG_TITLES = set()

def game_alive():
    """the ped turns on a held Left: some sessions start with the game standing still at the
    level brief (pt10_rs3/4/6/7/14: 'turn calibration unreliable (+0.00 rad)', every walk
    pinned at the spawn for the whole run on a loaded host)"""
    for attempt in range(4):
        s0 = D.wait_state()
        hold("Left", 0.5); time.sleep(0.8); s1 = D.wait_state()
        if s0 and s1 and abs(s0["fx"] * s1["fy"] - s0["fy"] * s1["fx"]) + abs(s0["x"] - s1["x"]) + abs(s0["y"] - s1["y"]) > 0.02:
            return True
        say(f"start: the game does not move (attempt {attempt + 1}); Return")
        D.tap("Return", 0.3); time.sleep(3.0)
    return False

def main():
    if not game_alive():
        M.mark("mission bil_re2: the game stood still at the start"); say("RESULT frozen at start"); return "frozen at start"
    entry = next(m for m in world.db["missions"] if m.get("mission") == "bil_re2")
    M.BLOCKED.update(TERRACE_BLOCK)
    for k, m in P.TITLES.items():
        if m.get("mission") != "bil_re2": WRONG_TITLES.add(k)
    M.mark(f"mission bil_re2: {entry.get('title', '')} (missions/russian_sailors.py)")
    t_m = time.time()
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    ok, key = P.answer(entry)
    say("answered:", ok, key); M.shot("bil_re2_phone"); SHEET.append(("the phone", "m_bil_re2_phone.png"))
    if not ok:
        M.mark("mission bil_re2: phone not answered"); return "phone not answered"
    seen = set(re.findall(r"msg=(\d+)", open(D.LOG, encoding="latin-1", errors="replace").read()))
    wrong = seen & WRONG_TITLES
    if wrong or key in WRONG_TITLES:
        r = f"wrong job started (titles {sorted(wrong | ({key} & WRONG_TITLES))})"
        M.mark(f"mission bil_re2: {r}"); say("RESULT", r); return r
    M.BLOCKED.difference_update(TERRACE_BLOCK)
    ax, ay = M.step_off_phone(world, entry)
    M.set_avoid_phones(world, keep=None)
    M.cruise_to(ax, ay, tol=0.5, secs=12)
    r = play(entry)
    M.mark(f"mission bil_re2: {r} ({time.time()-t_m:.0f}s) stats {STATS}")
    time.sleep(3); M.shot("bil_re2_end"); SHEET.append((f"end: {r}", "m_bil_re2_end.png"))
    with open("/out/rs_sheet.txt", "w") as f:
        for cap_, fn in SHEET: f.write(f"{fn}\t{cap_}\n")
    say("RESULT", r, STATS)
    return r

if __name__ == "__main__":
    main()
