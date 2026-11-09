#!/usr/bin/env python3
"""Skill: DELIVER INTACT (Wave M, 25 jobs in docs/missions-catalogue.md).

The pattern, as the scripts write it: a mission car (and often a passenger) must reach a box,
usually a garage (`IS_CAR_IN_BLOCK (car, x, y, z, w, h)`, w x h often 3 x 0.8-1) or a
`LOCATE_CHARACTER_BY_CAR` box, without `IS_CAR_WRECKED` / `HAS_CAR_JUST_SUNK` /
`HAS_CHARACTER_DIED` failing the job on the way; the game then takes the car (`PARK (car, door)`,
`HAS_PARK_FINISHED`) and says JOB COMPLETE. What loses it in practice (playthrough parts 6-10):
wall and traffic hits that set the car alight (fire at carhp 16000, wreck ~30 s later), being
pulled out of the car (police, carjackers), stopping just outside a narrow garage strip, and
keys held while the game parks the car.

What this module does (all on top of the frozen mission_lib/drive_lib):
  * `deliver(world, box, ...)`: the whole leg. Re-boards the mission car whenever he is out of it
    (the script's arrow goes back to the car: kind 3/4), drives with the fragile-car guards
    (`M.drive3(..., slow=True, precious=True)`, avoid list cleared per leg), slows further as the
    car's health falls (`M.CARE_HP`/`CARE_CAP` raised per call), diverts to a respray when the car
    burns or is badly hurt and a shop is nearer than the car's remaining life (a respray repairs
    to carhp 32000 and clears the wanted level), approaches a narrow box from its open side (the
    road cell the car route enters it from) and creeps in with short pulses, then lets go of every
    key and waits for the game (arrow gone / brief change / JOB COMPLETE) while it parks the car.
  * `creep_into(box)`, `approach_point(world, s, box)`, `respray(world, ...)`, `board(world, car)`
    are usable on their own by a job runner (gamerun/missions/<job>.py).

Returns one of: "delivered" (in the box and the game reacted), "complete", "failed", "dead",
"stuck: ..." (a reason). The caller passes `check()` (raises on the job's end) if it has one.
"""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

# respray shops per district: (shop cell, the tunnel cell to drive to before the creep).
# Downtown's two are the ones BANK ROBBERY uses (CAR_SHOP 10 at 204.5,221.5 entered down column
# 204 from row 216; the job shop at 86.5,160.5 from the road at row 163); others can be passed in.
SHOPS = {"wil": [((204.5, 221.5), (204.5, 218.6)), ((86.5, 160.5), (86.5, 163.4))]}
REPAIR_HP = int(os.environ.get("DELIVER_REPAIR_HP", "17500"))   # below this (fire at 16000) a near shop is worth it
FIRE_LIFE = 28.0       # game seconds a burning car lasts, roughly (pt7-pt9: 25-35 s)
RESPRAY_COST = int(os.environ.get("SP_RESPRAY_COST", "5000"))   # a shop does nothing below this (pt8_respray2, br7)
SHOP_DETOUR = 1.6      # a respray is taken when it is at most this many times nearer than the goal
CARE_STEPS = ((26000, 2.6), (22000, 2.0), (18000, 1.6))   # carhp -> speed cap of the fragile drive
DRIVE_CALL = 240.0    # one drive3 call at most this long, then the leg re-plans (dl_zz5 spent 420 s in one)
EVENTS = []            # (wall time, event) for the job's doc


def _ev(what):
    EVENTS.append((time.time(), what)); M.mark(f"deliver: {what}")


def car_hp():
    return (M.mission_state() or {}).get("carhp", -1)


def mission_car_xy(default=None):
    """where the script's arrow says the mission car is (kind 3/4 arrows follow a car), else default"""
    o = M.objective()
    if o and o[3] in (3, 4): return (o[0], o[1])
    return default


def board(world, car, budget=90, check=None):
    """back into the mission car (at `car`, or where its arrow is); True when driving"""
    s = D.wait_state()
    if s and s["driving"]: return s
    xy = mission_car_xy(car) or car
    if xy is None: return s
    _ev(f"boarding the mission car at {xy[0]:.1f},{xy[1]:.1f}")
    for k in range(3):
        if check: check()
        s = M.enter_car3(world, xy[0], xy[1], budget=budget)
        if s and s["driving"]: return s
        xy = mission_car_xy(xy) or xy
    return s


def _box_inside(s, box, margin=0.15):
    x, y, w, h = box
    return abs(s["x"] - x) < max(0.2, w / 2 - margin) and abs(s["y"] - y) < max(0.2, h / 2 - margin)


def label_xy(p):
    return f"{p[0]:.1f},{p[1]:.1f}"


def open_side(world, box, level=None, reach=3):
    """the side of the box a car can come in from, read off the map: for each side, the cells
    1..reach out from the box's edge across its width, scored road 3, lot/field 1, pavement 0.5,
    a wall or nothing stops that lane. Returns (approach point 2.6 out from the edge on the box's
    centre line, (dx, dy) of the side, score), or None. dl_zz1: the hospital box (3 x 1, a
    forecourt entered from the road at its east end) was approached from the route's last cells
    north of it and the car turned into the kerb posts for two minutes."""
    x, y, w, h = box
    L = level if level is not None else 1
    best = None
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        # one lane per cell across the side: from the box's edge cell outward, stopping at a wall
        # face, a cell with no ground or a building
        if dx:
            edge = int(math.floor(x + dx * (w / 2 - 0.5)))
            lanes = [(edge, int(math.floor(y - h / 2 + 0.5 + j))) for j in range(max(1, int(round(h))))]
        else:
            edge = int(math.floor(y + dy * (h / 2 - 0.5)))
            lanes = [(int(math.floor(x - w / 2 + 0.5 + j)), edge) for j in range(max(1, int(round(w))))]
        score = 0.0
        for cx, cy in lanes:
            for k in range(1, reach + 1):
                px, py = cx + dx * (k - 1), cy + dy * (k - 1)
                if M.wall_between(world, px, py, L, dx, dy): break
                kind = M.node_kind(world, px + dx, py + dy, L)
                if not kind: break
                score += {1: 3.0, 3: 1.0, 2: 0.5}.get(kind[1], 0.0)
        if best is None or score > best[2]:
            ax, ay = (x + dx * (w / 2 + 2.6), y) if dx else (x, y + dy * (h / 2 + 2.6))
            best = ((ax, ay), (dx, dy), score)
    return best if best and best[2] > 0 else None


def approach_point(world, s, box, back=4):
    """where to stand before the creep: the box's open side (open_side), else a point on the
    car route `back` cells before the box, else the side of the box facing the car."""
    x, y, w, h = box
    try:
        side = open_side(world, box, M.ped_level(s))
    except Exception as e:
        say(f"deliver: open_side failed ({e})"); side = None
    if side:
        say(f"deliver: approach {label_xy(side[0])} from side {side[1]} (score {side[2]:.1f})")
        return side[0]
    try:
        path = M.car_route(world, s, x, y)
    except Exception as e:                      # the router is shared and frozen; never let it end the job
        say(f"deliver: car_route failed ({e})"); path = None
    if path and len(path) > back + 1 and abs(path[-1][0] - int(x)) + abs(path[-1][1] - int(y)) <= 2:
        cx, cy, _ = path[-back - 1]
        return (cx + 0.5, cy + 0.5)
    # the long side of the strip faces the open side
    if h <= w: return (x, y + (2.5 if s["y"] > y else -2.5))
    return (x + (2.5 if s["x"] > x else -2.5), y)


def box_arrow(box, r=3.0):
    """the script's arrow for a box: 'up' (pointing at it: not there yet), 'cleared' (no mission
    arrow, or the slot still at the box with target kind 0: REMOVE_ARROW, which the scripts do
    the moment the car is in the box), 'moved' (on to something else), 'car' (on the mission car:
    he is out of it). dl_zz2: the car stood in GET ZITZAKI's hospital box at 51.32,178.30 with
    the slot at kind 0 for 8 s and the runner, waiting for the arrow to vanish, backed out."""
    x, y = box[0], box[1]
    o = M.objective()
    if o is None: return "cleared"
    near = math.hypot(o[0] - x, o[1] - y) < r
    if o[3] == 0: return "cleared" if near else "moved"
    if o[3] in (3, 4): return "car"
    return "up" if near else "moved"


def creep_into(box, secs=50, done=None, check=None):
    """nose the car into the box with short pulses, straightening toward its centre (the
    pattern of mission_play_wil.creep_in / bank_robbery.creep_in, the box's own size); the
    handbrake when inside; returns the state. `done()` ends it early (the game reacted)."""
    x, y, w, h = box
    t0 = time.time(); k = 0
    while time.time() - t0 < secs:
        s = D.wait_state()
        if not s or not s["driving"]: return s
        if check: check()
        if done and done(): return s
        if _box_inside(s, box):
            # stopped inside, not rolling through: dl_zz4's Miura was in the hospital box with
            # the arrow cleared, rolled out after a 0.3 s handbrake and the horn came too late
            hold("space", 0.7); hold("Down", 0.15); time.sleep(0.5)
            s2 = D.wait_state()
            if s2 and _box_inside(s2, box): return s2
            say(f"deliver: rolled out of the box to {s2['x']:.2f},{s2['y']:.2f}; in again")
            continue
        hx, hy = M.heading(s); dx, dy = x - s["x"], y - s["y"]
        a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
        if abs(a) > 0.5 and math.hypot(dx, dy) > 0.8:
            # reverse with the wheel turned the other way: both swing the nose toward the box
            xdo("keydown", "Down"); xdo("keydown", "Left" if a > 0 else "Right"); time.sleep(0.6)
            xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right"); time.sleep(0.3)
            continue
        if abs(a) > 0.1: xdo("keydown", "Right" if a > 0 else "Left")
        xdo("keydown", "Up"); time.sleep(0.25); xdo("keyup", "Up"); xdo("keyup", "Right"); xdo("keyup", "Left")
        time.sleep(0.5); k += 1
        if k % 6 == 0: hold("Down", 0.8); time.sleep(0.3)      # pressed on a door frame: back off, again
    return D.wait_state()


def keys_off():
    for key in ("Up", "Down", "Left", "Right", "space", "Control_L"): xdo("keyup", key)


def nearest_shop(s, shops):
    best = None
    for shop, tunnel in shops or []:
        d = math.hypot(tunnel[0] - s["x"], tunnel[1] - s["y"])
        if best is None or d < best[0]: best = (d, shop, tunnel)
    return best


def respray(world, shop, tunnel, check=None, view_switch=None, secs=40):
    """drive to the shop's tunnel cell, creep into the shop, wait for the repair (carhp back up)
    or the wanted level gone; True when repaired"""
    hp0 = car_hp(); w0 = (M.mission_state() or {}).get("wanted", 0)
    _ev(f"to the respray {shop} (carhp {hp0}, wanted {w0})")
    M.CAR_AVOID.clear()
    s = M.drive3(world, tunnel[0], tunnel[1], tol=0.8, budget=240, view_switch=view_switch, slow=True, precious=True)
    if check: check()
    if not (s and s["driving"]): return False
    def fixed():
        ms = M.mission_state() or {}
        return ms.get("carhp", -1) >= 30000 and (hp0 < 30000 or ms.get("wanted", 0) < w0)
    creep_into((shop[0], shop[1], 0.8, 1.0), secs=secs, done=fixed, check=check)
    t0 = time.time()
    while time.time() - t0 < 25 and not fixed():
        if check: check()
        time.sleep(0.5)
    ok = fixed()
    _ev(f"respray {'done' if ok else 'not done'}: carhp {car_hp()} wanted {(M.mission_state() or {}).get('wanted')}")
    if not ok: hold("Down", 1.5)
    return ok


def _care_cap(hp):
    caps = [cap for limit, cap in CARE_STEPS if 0 <= hp < limit]
    return min(caps) if caps else None


def deliver(world, box, car=None, approach=None, done=None, check=None, view_switch=None,
            shops=None, budget=900, park_wait=45, tries=5, label="the box"):
    """Drive the mission car into box = (x, y, w, h) and hand it to the game.

    car: where the mission car is if he is not in it (its arrow overrides); approach: a road
    point to reach before the creep (else derived from the car route); done(): the job's own
    "delivered" test (default: the mission arrow gone or moved off the box, or JOB COMPLETE /
    FAILED); check(): the job's failure guard (raises); shops: respray list (default the
    district's, `world.district` or SHOPS['wil'])."""
    x, y, w, h = box
    if shops is None: shops = SHOPS.get(getattr(world, "district", "wil"), [])
    key0 = M.objective_key()

    def reacted():
        ms = M.mission_state() or {}
        if ms.get("msg") in M.COMPLETE_KEYS or ms.get("msg") in M.FAILED_KEYS: return True
        if done is not None: return bool(done())
        return box_arrow(box) in ("cleared", "moved")

    def finish(why):
        ms = M.mission_state() or {}
        if ms.get("msg") in M.COMPLETE_KEYS: return "complete"
        if ms.get("msg") in M.FAILED_KEYS: return "failed"
        return why

    t0 = time.time(); repaired = 0
    saved = (M.CARE_HP, M.CARE_CAP, M.SMOOTH_SLOW_CAP)
    _ev(f"to {label} {x},{y} ({w} x {h}), carhp {car_hp()}")
    try:
        for attempt in range(tries):
            if time.time() - t0 > budget: break
            if check: check()
            if reacted(): return finish("delivered")
            s = D.wait_state()
            if not (s and s["driving"]):
                s = board(world, car, check=check)
                if not (s and s["driving"]): continue
            # pace by the car's health
            hp = car_hp()
            cap = _care_cap(hp)
            if cap: M.SMOOTH_SLOW_CAP = cap; M.CARE_HP = 32001; M.CARE_CAP = cap
            else: M.CARE_HP, M.CARE_CAP, M.SMOOTH_SLOW_CAP = saved
            # a burning or badly hurt car: a respray when one is near enough to reach in its life
            ms = M.mission_state() or {}
            burning = ms.get("carfire", -1) > 0 or (0 <= hp < 16000)
            dgoal = math.hypot(x - s["x"], y - s["y"])
            sh = nearest_shop(s, shops)
            # rp6/rp8 (COP CAR CRUSH, $15-20 on hand): the 65-block detour to a shop that cannot
            # work at that money took the Cop Car from 14000 to 2000 and set it alight; with less
            # than RESPRAY_COST the leg goes on to the goal at the fragile pace instead
            money = ms.get("money", 0)
            if sh and money < RESPRAY_COST and (burning or 0 <= hp < REPAIR_HP) and not repaired:
                repaired = 2; _ev(f"no respray: money {money} < {RESPRAY_COST} (carhp {hp})")
            if sh and money >= RESPRAY_COST and repaired < 2 and (burning or 0 <= hp < REPAIR_HP) and sh[0] * SHOP_DETOUR < dgoal + 10 \
                    and (not burning or sh[0] / 2.2 < FIRE_LIFE + 10):
                repaired += 1
                respray(world, sh[1], sh[2], check=check, view_switch=view_switch)
                continue
            # the drive: to the approach point (a narrow strip) or the box itself
            ap = approach or (approach_point(world, s, box) if min(w, h) < 1.6 else None)
            M.CAR_AVOID.clear()
            side = None
            if min(w, h) < 1.6:
                try: side = open_side(world, box, M.ped_level(s))
                except Exception: side = None
            on_open = side is None or ((s["x"] - x) * side[1][0] + (s["y"] - y) * side[1][1]) > -0.2
            if math.hypot(x - s["x"], y - s["y"]) < 6.0 and on_open:
                # already at the box: the creep only (dl_zz4: a 2-block drive3 back to the approach
                # point re-routed itself 50 blocks away from 53.1,177.9)
                pass
            elif ap:
                s = M.drive3(world, ap[0], ap[1], tol=1.2, budget=min(DRIVE_CALL, max(60, budget - (time.time() - t0))),
                             view_switch=view_switch, slow=True, precious=True, until=reacted)
            else:
                s = M.drive3(world, x, y, tol=max(0.6, min(w, h) * 0.45), budget=min(DRIVE_CALL, max(60, budget - (time.time() - t0))),
                             view_switch=view_switch, slow=True, precious=True, until=reacted)
            if check: check()
            if reacted(): keys_off(); break
            s = D.wait_state()
            if not (s and s["driving"]): continue          # pulled out / bailed: board again
            if math.hypot(x - s["x"], y - s["y"]) > 8: continue
            _ev(f"creeping into {label} from {s['x']:.1f},{s['y']:.1f} (carhp {car_hp()})")
            creep_into(box, secs=45, done=reacted, check=check)
            keys_off()
            # hands off: the game may take the car now (PARK)
            t1 = time.time()
            while time.time() - t1 < 8:
                if reacted(): break
                if check: check()
                time.sleep(0.5)
            if reacted(): break
            hold("Down", 1.0)                              # not taken: back out and come in again
        else:
            return finish(f"stuck: {label} not reached in {tries} tries")
        if not reacted(): return finish(f"stuck: {label} not reached")
        keys_off()
        _ev(f"in {label}: the game has it (carhp {car_hp()}, {time.time() - t0:.0f}s)")
        # the park: no keys while HAS_PARK_FINISHED runs; the job's end follows
        t2 = time.time()
        while time.time() - t2 < park_wait:
            ms = M.mission_state() or {}
            if ms.get("msg") in M.COMPLETE_KEYS or ms.get("msg") in M.FAILED_KEYS: break
            if done is not None and done(): break
            time.sleep(0.5)
        return finish("delivered")
    finally:
        M.CARE_HP, M.CARE_CAP, M.SMOOTH_SLOW_CAP = saved
        keys_off()
