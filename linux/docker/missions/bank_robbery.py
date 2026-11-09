#!/usr/bin/env python3
"""BANK ROBBERY! (Downtown, Yakuza green phone 46.5,150.5, wil_ye2) in the street-level views.

    python3 /work/missions/bank_robbery.py          (inside the container, after to_level.sh)

What the script (assets-src/missions/wil_m/wil_ye2.mis) wants, and how this runner does it:
  1. the GRAHAM at 52.5,150.5: walk in, drive to the City Bank box 194.5,177.5 (3 x 2), staying
     in the car (leaving it before the box makes the script wait for him to get back in, 1658);
  2. two guards (CRIMINAL_TYPE1 dressed as police, `crim/police` with an arrow slot in `view: peds`)
     appear on the bank's level-2 entrance walk at 185.5,174.5 / 185.5,175.5 (z 3). PLAYTHROUGH-9 shot
     at them from the street (z 2): the bank's front wall stopped every round, a passing patrol saw
     the gunfire and arrested him (pt9_wil6). Here: the getaway is pre-positioned first (the car turned
     to face west, the way the getaway runs), he waits in it until no police car or officer is near,
     then walks hand-placed points up the stairs (row 177, entered along the south half of the cell)
     to the walk's east end and shoots west along it from 3-4 blocks, walking at the nearer guard;
     the trigger is released the moment both are down (the inside man, Hiroshi, walks out behind them);
  3. straight back down and into the car, rolling at once: when Hiroshi is out the script raises the
     wanted level to 2 with NO_DROP and pays $5,000 for a respray (brief 1655);
  4. a respray clears the level (any CAR_SHOP n works; the job's own at 86.5,160.5 only adds a
     $5,000 bonus): the one at 204.5,221.5, 85 blocks from the bank instead of 156, a drive-through
     down column 204 from the road at row 216. It costs $5,000 and repairs the car (carhp 32000);
  5. the safehouse garage 76.5,200.5 (`IS_CAR_IN_BLOCK` 3 x 1, door12 on the south face): from the
     road at row 203 creep north into it; the game parks the car (PARK) and says JOB COMPLETE 1124.
Milestone frames /out/m_br_*.png, marks /out/marks.txt."""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

PHONE = (46.5, 150.5)
CAR0 = (52.5, 150.5)
BANK_BOX = (194.5, 177.5, 3.0, 2.0)
BANK_STOP = (195.3, 178.0)              # inside the box, on the pavement, clear of the stair foot (193,177)
GUARDS = [(185.5, 174.5), (185.5, 175.5)]
FIRE_SPOTS = [(190.5, 175.0), (189.0, 175.0), (188.0, 174.6)]   # the level-2 walk, east end first
WALK_LEVEL = 2
RESPRAY = (86.5, 160.5)
RESPRAY_ROAD = (86.5, 165.5)
SAFE = (76.9, 200.6)      # IS_CAR_IN_BLOCK(76.5, 200.5, 3 x 1); the opening in the south wall is cells 76-77 of row 201
SAFE_ROAD = (76.9, 203.0)
TITLE = "1976"
REFUSALS = ("1097", "1096", "1103", "1098", "1102", "1104", "1113", "1093")
FINAL_REWARD = 20000

VIEW = ["classic"]
VIEW_SLEEP = [1.7]
def set_view(name):
    order = ["classic", "third", "first"]
    while VIEW[0] != name:
        tap("v", 0.3); time.sleep(VIEW_SLEEP[0])
        VIEW[0] = order[(order.index(VIEW[0]) + 1) % 3]
    M.CUR_VIEW[0] = name
    M.mark(f"view {name}")

FP = {"until": 0.0}
def view_switch(s):
    """a first-person stretch at the wheel at the start of each drive, then the chase view"""
    now = time.time()
    if FP["until"] == 0.0:
        set_view("first"); FP["until"] = now + 15; M.mark("first person at the wheel")
    elif FP["until"] > 0 and now > FP["until"]:
        set_view("third"); FP["until"] = -1

# ------------------------------------------------------------------ state

MONEY0 = [0]
def outcome():
    """the job's outcome from the game's own words. Not M.outcome: that one calls +$10,000 a
    completion, and this job pays $5,000 at the bank and $5,000 for the respray first"""
    ms = M.mission_state()
    if not ms: return "unknown", ms
    if ms["msg"] in M.COMPLETE_KEYS: return "complete", ms
    if ms["msg"] in M.FAILED_KEYS: return "failed", ms
    if ms["health"] == 0 or ms["death"] != 0: return "dead", ms
    if M.LIVES0[0] is not None and ms["lives"] < M.LIVES0[0]: return "dead", ms
    return "running", ms

class Over(Exception):
    pass

def check():
    o, ms = outcome()
    if o not in ("running", "unknown"): raise Over(o)
    return ms or {}

def police_near(s, car_r=22.0, ped_r=16.0):
    """police cars and officers near him: (n cars, n officers, nearest distance)"""
    nc = no = 0; best = 99.0
    for c in M.cars():
        if c["model"] in (12, 52, 54) and c["driver"] != "P":
            d = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
            if d < car_r: nc += 1; best = min(best, d)
    for p in M.peds():
        if p["type"] == "cop" and M.ped_alive(p):
            d = math.hypot(p["x"] - s["x"], p["y"] - s["y"])
            if d < ped_r: no += 1; best = min(best, d)
    return nc, no, best

def guards():
    """the two marked guards still standing (dressed as police: gang 'police'; Hiroshi, who
    comes out after them, is a Yakuza and is never a target)"""
    out = []
    for p in M.peds():
        if p["mark"] is None or not M.ped_alive(p) or p["car"] is not None: continue
        if p["gang"] != "police" or p["type"] == "cop": continue
        if min(math.hypot(p["x"] - gx, p["y"] - gy) for gx, gy in GUARDS) > 8: continue
        out.append(p)
    return out

# ------------------------------------------------------------------ the phone (as mission_play_wil.answer)

def nudge_to(x, y, tol=0.1, tries=30):
    M.ensure_view("classic")
    for _ in range(tries):
        s = D.wait_state()
        if not s or s["driving"]: return s
        d = math.hypot(x - s["x"], y - s["y"])
        if d < tol: return s
        a = D.angle_to(s, x, y)
        if abs(a) > 0.35:
            key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
            hold(key, min(abs(a) / max(D.rate, 2.0), 0.3)); time.sleep(0.35)
            hold("Up", 0.12); time.sleep(0.45)
            continue
        hold("Up", max(0.08, min(0.4, (d - 0.05) / 1.9))); time.sleep(0.5)
    return D.wait_state()

def answer(world, entry):
    """to the phone (by car when far), onto it, and the title 1976 or a refusal"""
    before = M.mission_state(); m0 = before["msg"] if before else ""
    s = D.wait_state()
    M.arrows_baseline()
    # on foot from the spawn (113 blocks, about two game minutes): br2's borrowed car was pinned
    # and set alight at 57.4,143.6 on the way, 12000 lost in 20 s
    if s and not s["driving"] and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) > float(os.environ.get("PHONE_DRIVE_OVER", "160")):
        M.mark(f"a long way to the phone ({math.hypot(entry['x'] - s['x'], entry['y'] - s['y']):.0f} blocks): by car")
        s = M.any_car2(world, budget=100)
    if s and s["driving"]:
        FP["until"] = 0.0
        s = M.drive3(world, entry["x"], entry["y"], tol=4.0, budget=360, view_switch=view_switch, slow=True)
        s = M.leave_car(); set_view("third"); M.mark("out of the car near the phone")
    s = M.walk3(world, entry["x"], entry["y"], None, tol=0.35, budget=420)
    if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) > 1.2 and os.environ.get("WARP_OK", "1") == "1":
        lvl = M.top_level(world, entry["x"], entry["y"])
        say(f"phone not reachable on foot (level {lvl}); developer warp (reported)")
        set_view("classic"); M.scene_warp(entry["x"], entry["y"], lvl, "phone on a dais the walker cannot climb"); set_view("third")
        s = M.walk3(world, entry["x"], entry["y"], None, tol=0.35, budget=60)
    t0 = time.time(); seen = []
    while time.time() - t0 < 24:
        ms = M.mission_state()
        if ms and ms["msg"] != m0 and ms["msg"] not in ("", "svdone") and not (ms["msg"].isdigit() and 1600 <= int(ms["msg"]) <= 1615):
            if ms["msg"] not in seen: seen.append(ms["msg"])
            if ms["msg"] == TITLE or ms["msg"] == "1650": return "answered", seen
            if ms["msg"] in ("1093", "1103", "1113"):
                # "already on a job" (km7, kmg4: after the warp onto the dais the title went by
                # unseen and the phone then said 1093): the job IS running if the script's arrow
                # points at the GRAHAM
                time.sleep(1.0); o = M.objective()
                if o and math.hypot(o[0] - CAR0[0], o[1] - CAR0[1]) < 3.0: return "answered", seen
            if ms["msg"] in REFUSALS: return "refused", seen
        if time.time() - t0 > 6 and not seen:
            s = D.wait_state()
            if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) < 0.5:
                ox, oy = M.step_off_phone(world, entry, dist=1.2)
                M.cruise_to(ox, oy, tol=0.4, secs=5); time.sleep(0.5)
            nudge_to(entry["x"], entry["y"], tol=0.1, tries=6)
        time.sleep(0.25)
    o = M.objective()
    if o and math.hypot(o[0] - CAR0[0], o[1] - CAR0[1]) < 3.0: return "answered", seen
    return "no answer", seen

# ------------------------------------------------------------------ car helpers

def creep_in(x, y, w, h, secs=50, until=None):
    """nose the car into a narrow box with short pulses, straightening toward it (as
    mission_play_wil.creep_in); returns when inside (handbrake) or when until() holds"""
    t0 = time.time(); k = 0
    while time.time() - t0 < secs:
        s = D.wait_state()
        if not s or not s["driving"]: return s
        check()
        if until and until(): return s
        if abs(s["y"] - y) < max(0.2, h / 2 - 0.15) and abs(s["x"] - x) < max(0.3, w / 2 - 0.3):
            hold("space", 0.3); return s
        hx, hy = M.heading(s); dx, dy = x - s["x"], y - s["y"]
        a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
        if abs(a) > 0.5 and math.hypot(dx, dy) > 0.8:
            xdo("keydown", "Down"); xdo("keydown", "Left" if a > 0 else "Right"); time.sleep(0.6)
            xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right"); time.sleep(0.3)
            continue
        if abs(a) > 0.1: xdo("keydown", "Right" if a > 0 else "Left")
        xdo("keydown", "Up"); time.sleep(0.25); xdo("keyup", "Up"); xdo("keyup", "Right"); xdo("keyup", "Left")
        time.sleep(0.5); k += 1
        if k % 6 == 0: hold("Down", 0.8); time.sleep(0.3)
    return D.wait_state()

def arrow_near(x, y, r=3.0):
    o = M.objective()
    return bool(o and o[3] == 1 and math.hypot(o[0] - x, o[1] - y) < r)

def to_mission_car(world, car):
    """back into the GRAHAM (the script's arrow follows it when he is out: kind 3)"""
    s = D.wait_state()
    if s["driving"]: return s
    o = M.objective()
    if o and o[3] in (3, 4): car = (o[0], o[1])
    M.mark(f"back to the GRAHAM at {car[0]:.1f},{car[1]:.1f}")
    s = M.enter_car3(world, car[0], car[1], budget=60)
    if s and s["driving"]: FP["until"] = -1; M.ensure_view("third")
    return s

# ------------------------------------------------------------------ the job

# The stairs to the bank's entrance walk: a 26-degree flight on row 177 rising west from 193 to 190
# (z 2 -> 3), entered along the south half of the cell (br4 pressed against the stone block at its
# foot at y 177.1-177.5 for 80 s; br2 got up at y 177.9), then north along column 190 to the walk
CLIMB = [(193.6, 178.0), (192.3, 177.8), (190.8, 177.45), (190.35, 176.3), (190.25, 175.3), (189.0, 175.1)]
DESCEND = [(190.3, 175.4), (190.35, 176.6), (190.8, 177.45), (192.3, 177.75), (193.5, 178.0)]
# respray shops (CAR_SHOP n: a drive-through on one column under a roof): the job's own (86.5,160.5,
# remap 9, +$5,000 more) is 156 blocks from the bank with the police behind; any respray clears the
# level, and the one at 204.5,221.5 (CAR_SHOP 10) is 85 blocks away, entered from the road at row
# 216 down column 204. (x, y of the shop, the tunnel cell to drive to before the creep)
SHOPS = [((204.5, 221.5), (204.5, 218.6)), ((86.5, 160.5), (86.5, 163.4))]

def path_walk(points, secs_each=6.0):
    """straight cruise legs through hand-placed points (no router); False at the first miss"""
    for k, (x, y) in enumerate(points):
        s, ok = M.cruise_to(x, y, tol=0.45 if k < len(points) - 1 else 0.35, secs=secs_each, stop=(k == len(points) - 1))
        if not ok:
            xdo("keyup", "Up"); say(f"path_walk: missed {x},{y} (at {s['x']:.2f},{s['y']:.2f} z {s['z']:.2f})"); return False
    xdo("keyup", "Up")
    return True

def drive(world, x, y, tol, budget, **kw):
    """drive3 with the avoid list cleared first (stall cells from an earlier leg sent br2's second
    attempt round a 186-block loop by the north)"""
    M.CAR_AVOID.clear()
    return M.drive3(world, x, y, tol=tol, budget=budget, view_switch=view_switch, slow=True, precious=True, **kw)

def quick_board(car):
    """Return beside the car: the game walks him to the door"""
    tap("Return", 0.25); t0 = time.time(); s = D.wait_state()
    while time.time() - t0 < 4.0:
        time.sleep(0.2); s = D.wait_state()
        if s["driving"]: break
        if time.time() - t0 > 1.5 and s.get("state") not in (2, 3, 6): break
    return s

def turn_car_toward(px, py, secs=40):
    """point the parked car at (px, py) with short reverse/forward pulses, the wheel turned so
    both swing the nose the same way (as creep_in). PLAYTHROUGH-10: the getaway is pre-positioned
    before the guards are shot: br8 parked facing north, the first metres of the getaway were a
    turn and a re-route, and a cop pulled him out 14 s into it"""
    t0 = time.time()
    while time.time() - t0 < secs:
        s = D.wait_state()
        if not s or not s["driving"]: return s
        hx, hy = M.heading(s); dx, dy = px - s["x"], py - s["y"]
        a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
        if abs(a) < 0.3: return s
        xdo("keydown", "Down"); xdo("keydown", "Left" if a > 0 else "Right"); time.sleep(0.6)
        xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right"); time.sleep(0.3)
        s = D.wait_state(); hx, hy = M.heading(s); dx, dy = px - s["x"], py - s["y"]
        a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
        if abs(a) < 0.3: return s
        xdo("keydown", "Up"); xdo("keydown", "Right" if a > 0 else "Left"); time.sleep(0.45)
        xdo("keyup", "Up"); xdo("keyup", "Right"); xdo("keyup", "Left"); hold("space", 0.3); time.sleep(0.3)
    return D.wait_state()

def run(world, entry):
    # 1. the car
    M.mark("to the GRAHAM at 52.5,150.5")
    s = M.enter_car3(world, CAR0[0], CAR0[1], budget=200)
    if not (s and s["driving"]) and os.environ.get("WARP_OK", "1") == "1":
        say("the walk to the mission car failed; developer warp to its door (reported)")
        set_view("classic"); M.scene_warp(CAR0[0], CAR0[1] + 1.0, M.top_level(world, CAR0[0], CAR0[1]) or 1, "to the mission car's door"); set_view("third")
        s = M.enter_car3(world, CAR0[0], CAR0[1], budget=90)
    if not (s and s["driving"]): return "stuck: could not enter the car"
    M.shot("br_incar"); FP["until"] = 0.0
    t1 = time.time()
    while time.time() - t1 < 30 and not arrow_near(BANK_BOX[0], BANK_BOX[1]): time.sleep(0.5)
    check()

    # 2. the bank box, in the car (east of the stair foot, clear of it)
    M.mark("to the City Bank box 194.5,177.5 (in the car)")
    for k in range(4):
        s = D.wait_state()
        if not s["driving"]:
            s = to_mission_car(world, CAR0 if k == 0 else (s.get("px", CAR0[0]), s.get("py", CAR0[1])))
            if not s["driving"]: continue
        s = drive(world, BANK_STOP[0], BANK_STOP[1], 1.2, 420,
                  until=lambda: (M.mission_state() or {}).get("msg") == "1665" or bool(guards()))
        check()
        s = D.wait_state()
        if s["driving"] and math.hypot(BANK_STOP[0] - s["x"], BANK_STOP[1] - s["y"]) < 6:
            creep_in(BANK_STOP[0], BANK_STOP[1], 1.6, 1.2, secs=30)
        t2 = time.time()
        while time.time() - t2 < 8 and not guards(): time.sleep(0.5)
        if guards(): break
    t2 = time.time()
    while time.time() - t2 < 30 and not guards(): time.sleep(0.5); check()
    gs = guards()
    ms = check()
    say(f"guards: {[(p['id'], p['x'], p['y'], p['z'], p['hp']) for p in gs]}; carhp {ms.get('carhp')}")
    if not gs: return "stuck: no guards"
    M.shot("br_bank")
    # the getaway runs west along row 179 (to column 178 and the respray at 204.5,221.5): the car
    # faces west before he leaves it (the script needs the car no more until Hiroshi is out)
    s = turn_car_toward(184.0, 179.6)
    hold("space", 0.4)
    s = D.wait_state()
    car = (s["x"], s["y"])
    M.mark(f"getaway car set at {s['x']:.1f},{s['y']:.1f} heading {M.heading(s)[0]:.2f},{M.heading(s)[1]:.2f}")

    # 3. the guards: no police in sight first, then up the stairs and along the walk
    t3 = time.time()
    while time.time() - t3 < 70:
        check(); s = D.wait_state()
        nc, no, dmin = police_near(s)
        if nc == 0 and no == 0: break
        say(f"police near the bank ({nc} cars, {no} officers, nearest {dmin:.1f}): waiting in the car")
        time.sleep(2.0)
    M.mark("out of the car: up the bank stairs to the guards")
    s = M.leave_car(); M.select_gun(); FP["until"] = -1
    M.ensure_view("classic")
    if not path_walk(CLIMB):
        s = M.walk3(world, FIRE_SPOTS[1][0], FIRE_SPOTS[1][1], WALK_LEVEL, tol=0.5, budget=60)
    s = D.wait_state()
    M.mark(f"on the bank walk at {s['x']:.1f},{s['y']:.1f} z {s['z']:.1f}"); M.shot("br_stairs")
    t4 = time.time(); empty_since = None; hp_last = None; last_progress = time.time(); spot_i = 1
    while time.time() - t4 < 150:
        check()
        gs = guards()
        if gs: empty_since = None
        else:
            # trigger off at once: Hiroshi walks out of the door behind them
            xdo("keyup", "Control_L")
            empty_since = empty_since or time.time()
            if not M.char_arrows() or time.time() - empty_since > 3.0: break
            time.sleep(0.3); continue
        s = D.wait_state()
        if M.ped_level(s) != WALK_LEVEL:
            xdo("keyup", "Control_L")
            say(f"off the walk (z {s['z']:.2f}): back up")
            if not path_walk(CLIMB): M.walk3(world, FIRE_SPOTS[1][0], FIRE_SPOTS[1][1], WALK_LEVEL, tol=0.5, budget=40)
            continue
        if not M.gun_ready() and not M.select_gun():
            xdo("keyup", "Control_L"); say("no gun in hand at the guards"); M.fetch_gun(world, budget=120); continue
        tgt = min(gs, key=lambda p: math.hypot(p["x"] - s["x"], p["y"] - s["y"]))
        d = math.hypot(tgt["x"] - s["x"], tgt["y"] - s["y"])
        # walking at him keeps the logged facing true (a standing ped turned with the trigger held
        # lagged a second behind: br2 fired north for 10 s at 190.4,175.3)
        M._aim_walk(tgt["x"], tgt["y"], fire=True, walk=d > 2.2, secs=0.5)
        hp = tuple(sorted((p["id"], p["hp"]) for p in gs))
        if hp != hp_last: hp_last = hp; last_progress = time.time()
        if time.time() - last_progress > 8:
            xdo("keyup", "Control_L"); last_progress = time.time()
            spot_i = min(spot_i + 1, len(FIRE_SPOTS) - 1)
            say(f"guards unhurt for 8 s from {s['x']:.1f},{s['y']:.1f}: to {FIRE_SPOTS[spot_i]}")
            M.cruise_to(FIRE_SPOTS[spot_i][0], FIRE_SPOTS[spot_i][1], tol=0.4, secs=4)
    xdo("keyup", "Control_L")
    if guards(): return "stuck: guards alive"
    ms = check()
    M.mark(f"both guards down (wanted {ms.get('wanted')}, ammo {ms.get('ammo')})"); M.shot("br_guards")

    # 4. back to the car at once: Hiroshi walks out and the script raises the level to 2 stars
    # (NO_DROP); the police were at the car in br4 25 s after the last guard fell
    if not path_walk(DESCEND, secs_each=5.0):
        s = D.wait_state(); say(f"descent missed at {s['x']:.1f},{s['y']:.1f}")
    s = D.wait_state()
    if not s["driving"] and math.hypot(car[0] - s["x"], car[1] - s["y"]) < 3.0: s = quick_board(car)
    for k in range(3):
        if s and s["driving"]: break
        check(); s = to_mission_car(world, car)
    if not (s and s["driving"]): return "stuck: could not get back in the car"
    # rolling at once, west along the lane it faces, before the router plans the leg
    hold("Up", 0.8)
    ms = check()
    M.mark(f"in the getaway car (wanted {ms.get('wanted')}, carhp {ms.get('carhp')}, police {police_near(D.wait_state(), 12.0, 8.0)})")

    # 5. a respray, as soon as the level is up (the script's heads loop: its arrow on 86.5,160.5)
    def heads_up():
        return arrow_near(86.5, 160.5) or (M.mission_state() or {}).get("msg") in ("1655", "1666", "1668")
    def safe_up():
        return arrow_near(*SAFE, r=4.0) or (M.mission_state() or {}).get("msg") in ("1661", "1662", "1010")
    sprayed = False
    for k in range(6):
        check()
        if safe_up(): sprayed = True; break
        shop, tunnel = SHOPS[0] if k < 3 else SHOPS[1]
        s = D.wait_state()
        if not s["driving"]: s = to_mission_car(world, car)
        if not s["driving"]: continue
        FP["until"] = -1
        M.mark(f"to the respray at {shop} (try {k + 1})")
        s = drive(world, tunnel[0], tunnel[1], 0.8, 360)
        check()
        if not s["driving"]: continue
        t6 = time.time()
        while time.time() - t6 < 40 and not heads_up() and not safe_up():
            check(); time.sleep(0.5)
        if safe_up(): sprayed = True; break
        ms = check()
        M.mark(f"into the respray shop {shop} (wanted {ms.get('wanted')}, money {ms.get('money')}, carhp {ms.get('carhp')})")
        s = creep_in(shop[0], shop[1], 0.8, 1.0, secs=40, until=safe_up)
        M.shot("br_respray_in")
        t6 = time.time()
        while time.time() - t6 < 25 and not safe_up():
            check(); time.sleep(0.5)
        ms = check(); say(f"respray: wanted {ms.get('wanted')} money {ms.get('money')} carhp {ms.get('carhp')} msg {ms.get('msg')} arrow {M.objective()}")
        if safe_up(): sprayed = True; break
        # not sprayed: out of the shop the way he came, and in again
        hold("Down", 1.5); time.sleep(0.5)
    ms = check()
    M.mark(f"after the respray ({sprayed}): wanted {ms.get('wanted')}, money {ms.get('money')}, carhp {ms.get('carhp')}, msg {ms.get('msg')}")
    M.shot("br_resprayed")

    # 6. the safehouse garage: from the road at row 203 north into it; the game parks the car
    for k in range(4):
        check()
        s = D.wait_state()
        if not s["driving"]: s = to_mission_car(world, car)
        if not s["driving"]: continue
        M.mark(f"to the safehouse {SAFE}")
        s = drive(world, SAFE_ROAD[0], SAFE_ROAD[1], 1.0, 360)
        check()
        if not s["driving"]: continue
        s = creep_in(SAFE[0], SAFE[1], 3.0, 1.0, secs=50, until=lambda: M.objective() is None)
        M.shot("br_garage")
        o, ms = wait_outcome(45)
        if o != "running": return o
        if M.objective() is None: o, ms = wait_outcome(30); return o
    return "stuck: safehouse"

def wait_outcome(secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        o, ms = outcome()
        if o not in ("running", "unknown"): return o, ms
        time.sleep(1.0)
    return "running", M.mission_state()

def main():
    D.start()
    s = D.wait_state(40)
    if not s: sys.exit(1)
    D.calibrate_turn()
    world = M.World("wil")
    M.mark("level")
    M.arrows_baseline()
    M.START[0] = (s["x"], s["y"])
    M.VIEW_HOOK[0] = set_view
    set_view("third")
    entry = next(m for m in world.db["missions"] if m.get("mission") == "wil_ye2")
    M.mark("mission wil_ye2: BANK ROBBERY!")
    t_m = time.time()
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    r, seen = answer(world, entry)
    if r == "no answer": r, seen = answer(world, entry)
    say("phone:", r, seen); M.shot("br_phone")
    if r != "answered":
        M.mark(f"mission wil_ye2: phone {r} {seen}"); return
    M.arm_lives()
    MONEY0[0] = (M.mission_state() or {}).get("money", 0)
    ax, ay = M.step_off_phone(world, entry)
    M.set_avoid_phones(world, keep=None)
    M.cruise_to(ax, ay, tol=0.5, secs=12)
    s = D.wait_state()
    if s and s["z"] > 3.5 and os.environ.get("WARP_OK", "1") == "1":
        cell = M.street_cell_near(world, entry["x"], entry["y"])
        if cell:
            say(f"on the phone dais (z {s['z']:.1f}); developer warp to the street at {cell[0]},{cell[1]} (reported)")
            set_view("classic"); M.scene_warp(cell[0], cell[1], cell[2], "down from the phone dais"); set_view("third")
    try:
        r = run(world, entry)
    except Over as e:
        r = str(e)
    if r == "running":
        o, ms = wait_outcome(30); r = o
    ms = M.mission_state() or {}
    M.mark(f"mission wil_ye2: {r} ({time.time() - t_m:.0f}s) money {ms.get('money')} msg {ms.get('msg')}")
    M.shot("br_end")
    set_view("third"); time.sleep(1.0); M.shot("br_end_third")
    say("RESULTS", {"wil_ye2": r})
    M.mark(f"done wil_ye2={r}")

if __name__ == "__main__":
    main()
