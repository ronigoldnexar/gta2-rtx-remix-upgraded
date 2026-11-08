#!/usr/bin/env python3
"""Plays Downtown's missions in the street-level views, by the decompiled
plans (missions.json) and the renderer's log. Usage inside the container:
    python3 /work/mission_play_wil.py [mission ...]     (default: wil_tra wil_ye1 wil_ze2)
Third person on foot, first person for a stretch of every walk and every drive.
Marks in /out/marks.txt, milestone frames /out/m_*.png."""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
wanted = sys.argv[1:] or os.environ.get("MISSIONS", "wil_ze1 wil_le2 wil_ze2").split()
VIEW = ["classic"]

VIEW_SLEEP = [1.7]   # after a V press; a timed job uses a short wait (WHEELER-DEALING lost
                     # about 5 s of its 180 at every walk to the classic view and back)
def set_view(name):
    order = ["classic", "third", "first"]
    while VIEW[0] != name:
        tap("v", 0.3); time.sleep(VIEW_SLEEP[0])
        VIEW[0] = order[(order.index(VIEW[0]) + 1) % 3]
    M.CUR_VIEW[0] = name
    M.mark(f"view {name}")

D.start()
s = D.wait_state(40)
if not s: sys.exit(1)
D.calibrate_turn()
world = M.World("wil")
M.mark("level")
M.arrows_baseline()
M.START[0] = (s["x"], s["y"]) if s else None
set_view("third")
FP = {"until": 0.0, "walk_until": 0.0}
WARPED_UP = [False]

def view_switch(s):
    now = time.time()
    if FP["until"] == 0.0:
        set_view("first"); FP["until"] = now + 18; M.mark("first person at the wheel")
    elif FP["until"] > 0 and now > FP["until"]:
        set_view("third"); FP["until"] = -1

M.VIEW_HOOK[0] = set_view

def walk(tx, ty, tl=None, tol=0.5, budget=300, fp_secs=12):
    """a walk (the walker takes the classic view itself: the 3D orbit camera
    remaps the keys; the first-person stretch is at the wheel now)"""
    return M.walk3(world, tx, ty, tl, tol=tol, budget=budget)

TITLES = {m["plan"][0].get("display_message"): m for m in []}
def answer(entry):
    """walk onto the phone and watch the message buffer closely: the job's title
    (19xx) flashes for a few seconds; the gang's refusals are 10xx"""
    before = M.mission_state(); m0 = before["msg"] if before else ""
    s = D.wait_state()
    M.arrows_baseline()      # only an arrow raised by this phone counts as a job
    # the Loonies refuse a job after a drive through their turf (1107 in pt4, 1103 in
    # pt7_le2a: one bump on the way, money +61): walk to their phones
    loony = entry.get("mission", "").startswith("wil_l")
    if s and not s["driving"] and not loony and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) > 40:
        M.mark(f"a long way to the phone ({math.hypot(entry['x'] - s['x'], entry['y'] - s['y']):.0f} blocks): by car")
        s = M.any_car2(world, budget=100)
    if s and s["driving"]:
        FP["until"] = 0.0
        # gently: every Loony run over on the way costs respect, and the Pizza phone
        # refused pt4_wil9 and pt4_wil12 (message 1107) after a fast drive through Loony turf
        s = M.drive3(world, entry["x"], entry["y"], tol=4.0, budget=360, view_switch=view_switch, slow=True)
        s = M.leave_car(); set_view("third"); M.mark("out of the car near the phone")
    s = walk(entry["x"], entry["y"], None, tol=0.35, budget=240, fp_secs=10)
    if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) > 1.2 and os.environ.get("WARP_OK", "1") == "1":
        lvl = M.top_level(world, entry["x"], entry["y"])
        say(f"phone at {entry['x']},{entry['y']} not reachable on foot (terrace level {lvl}); developer warp")
        set_view("classic")
        s = M.scene_warp(entry["x"], entry["y"], lvl, "phone on a terrace the walker cannot climb")
        WARPED_UP[0] = True
        set_view("third")
        if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) > 0.6:
            # the warp resolves to the nearest road cell at that level (pt4_wil13 landed
            # 2 blocks off the Zaibatsu phone): walk the rest in the classic view
            set_view("classic"); M.cruise_to(entry["x"], entry["y"], tol=0.3, secs=12); set_view("third")
        s = M.walk3(world, entry["x"], entry["y"], None, tol=0.35, budget=60)
    t0 = time.time(); seen = []
    while time.time() - t0 < 24:
        ms = M.mission_state()
        if ms and ms["msg"] != m0 and ms["msg"] not in ("", "svdone") and not (ms["msg"].isdigit() and 1600 <= int(ms["msg"]) <= 1615):   # 1600-1615: the tutorial's hints
            if ms["msg"] not in seen: seen.append(ms["msg"])
            k = ms["msg"]
            if k in ("1093", "1103", "1113"):
                # "you are already on a <gang> job": a job IS running - the one this phone
                # just started (pt7_le2a: PIZZA CAKE's brief 1531, then 1103 as he stepped on
                # the RADIO ZA-ZA phone beside it) or the neighbour's (pt7_le2d: 1954 RADIO
                # ZA-ZA, crossed at the corner). Not a refusal: name the running job
                title = next((x for x in seen if x.startswith("19")), None)
                if title:
                    say(f"phone: {k} (already on a job) after the title {title}"); ms = dict(ms); ms["msg"] = title; return True, ms
                o = M.objective()
                started = mission_from_arrow(o) if o else None
                if started:
                    say(f"phone: {k} (already on a job); the arrow names {started['mission']}")
                    ms = dict(ms); ms["msg"] = started["plan"][0].get("display_message", ""); return True, ms
            if k.startswith("19") or k in ("1097", "1096", "1103", "1098", "1102", "1104", "1113"):
                say(f"phone: message {k} (seen {seen})"); ms = dict(ms); ms["msg"] = k; return True, ms
        if time.time() - t0 > 6 and not seen:
            # a phone answers when he steps ONTO it: standing on it already (a warp lands
            # him there) does nothing, so step a block off and back on
            s = D.wait_state()
            if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) < 0.5:
                ox, oy = M.step_off_phone(world, entry, dist=1.2)
                M.cruise_to(ox, oy, tol=0.4, secs=5); time.sleep(0.5)
            nudge_to(entry["x"], entry["y"], tol=0.1, tries=6)
        time.sleep(0.25)
    # a message without a title (a hint such as 1608, the save-point sign) proves
    # nothing: pt4_wil9 took the Zaibatsu phone as answered on a hint and never had
    # a job. Only the game's objective arrow does
    if seen and M.objective() is None:
        say(f"phone: messages {seen}, no title and no mission arrow: not answered"); return False, M.mission_state()
    if seen:
        say(f"phone: messages {seen}, no title caught; a mission arrow is up"); ms = M.mission_state(); return True, ms
    # no message caught (a save-point sign can hold the HUD slot): the game's own
    # objective arrow tells whether a job started, and which
    o = M.objective()
    if o is not None:
        started = mission_from_arrow(o)
        ms = dict(M.mission_state() or {"money": 0, "msg": ""})
        if started:
            say(f"phone: no message, but the mission arrow at {o[0]:.1f},{o[1]:.1f} is {started['mission']} {started.get('title','')}")
            ms["msg"] = started["plan"][0].get("display_message", ""); return True, ms
        say(f"phone: no message; an arrow at {o[0]:.1f},{o[1]:.1f} matches no plan")
        return True, ms
    return False, M.mission_state()

def mission_from_arrow(o):
    """the mission whose first target (its car, or its first arrow point) stands
    where the new mission arrow points"""
    best = None
    for m in world.db["missions"]:
        plan = m.get("plan") or []
        for st in plan:
            at = st.get("at") if "car" in st else (st["arrow"] if isinstance(st.get("arrow"), list) else None)
            if at:
                d = math.hypot(at[0] - o[0], at[1] - o[1])
                if d < 3.0 and (best is None or d < best[0]): best = (d, m)
                break
    return best[1] if best else None

def nudge_to(x, y, tol=0.1, tries=30):
    """small aimed steps onto a point (the LOCATE boxes can be half a block)"""
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
            hold("Up", 0.12); time.sleep(0.45)          # a step makes the logged facing real
            continue
        hold("Up", max(0.08, min(0.4, (d - 0.05) / 1.9))); time.sleep(0.5)
    return D.wait_state()

def settle(x, y, msg0, secs=25, money0=None):
    """stand on (x,y) until the game reacts (message change or money); walks a
    small spiral of exact points"""
    t0 = time.time(); k = 0
    pts = [(0, 0), (0.12, 0), (-0.12, 0), (0, 0.12), (0, -0.12), (0.2, 0.2), (-0.2, -0.2), (0.2, -0.2), (-0.2, 0.2)]
    while time.time() - t0 < secs:
        ms = M.mission_state()
        if ms and ms["msg"] != msg0 and ms["msg"] not in ("1600", "1601"): return True
        if ms and money0 is not None and ms["money"] >= money0 + 5000: return True
        off = pts[k % len(pts)]; k += 1
        nudge_to(x + off[0], y + off[1], tol=0.08, tries=10); time.sleep(1.2)
    return False

def creep_in(x, y, msg0, money0, secs=50):
    """nose the car into a narrow block (a garage door) with short pulses,
    straightening toward it; stops when the game reacts or the car is inside"""
    t0 = time.time(); k = 0
    while time.time() - t0 < secs:
        s = D.wait_state()
        if not s or not s["driving"]: return s
        ms = M.mission_state()
        if ms and (ms["msg"] != msg0 or ms["money"] >= money0 + 5000): return s
        if abs(s["y"] - y) < 0.35 and abs(s["x"] - x) < 1.2: time.sleep(2); continue
        hx, hy = M.heading(s); dx, dy = x - s["x"], y - s["y"]
        a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
        if abs(a) > 0.5 and math.hypot(dx, dy) > 0.8:
            xdo("keydown", "Down"); xdo("keydown", "Left" if a > 0 else "Right"); time.sleep(0.6)
            xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right"); time.sleep(0.3)
            continue
        if abs(a) > 0.1:
            xdo("keydown", "Right" if a > 0 else "Left")
        xdo("keydown", "Up"); time.sleep(0.25); xdo("keyup", "Up"); xdo("keyup", "Right"); xdo("keyup", "Left")
        time.sleep(0.5); k += 1
        if k % 6 == 0: hold("Down", 0.8); time.sleep(0.3)      # back off and try again
    return D.wait_state()

def short_of(s, x, y, back=7):
    """the road cell `back` cells before (x,y) on the car route from here"""
    L = M.ped_level(s)
    path = M.route3(world, int(s["x"]), int(s["y"]), L, int(x), int(y), None, kinds=(1,), cost=M.CAR_COST)
    if path and len(path) > back + 2 and abs(path[-1][0] - int(x)) + abs(path[-1][1] - int(y)) <= 2:
        cx, cy, _ = path[-back - 1]; return (cx + 0.5, cy + 0.5)
    return None

def quick_enter(secs=4.0):
    """Return beside a car: GTA2 walks the ped to the nearest door (state 2/3/6)"""
    tap("Return", 0.25); t0 = time.time(); s = D.wait_state()
    while time.time() - t0 < secs:
        time.sleep(0.2); s = D.wait_state()
        if s["driving"]: break
        if time.time() - t0 > 1.5 and s.get("state") not in (2, 3, 6): break
    say(f"quick_enter: {'in' if s['driving'] else 'not in'} after {time.time() - t0:.1f}s")
    return M.check_entered(s) if s["driving"] else s

WD_TURN_AVOID = {(215, 212), (216, 212), (215, 211), (216, 211), (213, 212), (213, 213), (214, 212), (214, 213)}   # no way back north on the southbound carriageway at the third dealer
# PLAYTHROUGH-8: WHEELER-DEALING's stops, dealer -> where the car stands (see run_plan)
WD_STOPS = {(226.5, 82.5): (227.5, 80.4),      # southbound lane 227, he on the corner pavement 226,82
            (245.5, 132.5): (246.5, 130.4),    # the ramp down to row 132, lane 246, he on the west pavement
            (214.5, 211.5): (215.5, 209.3),    # southbound lane 215 (not 216), he on the west pavement 214
            (164.5, 125.5): (168.5, 123.2)}    # southbound lane 168 beside him, by way of WD_VIA (the junction first)
WD_VIA = {(164.5, 125.5): (169.5, 112.6)}   # the last corner taken from a standstill-ish (pt7: the race turn overshot onto the pavement)
TIMED = {"wil_ze2"}
GUN_FIRST = {"wil_le2"}   # jobs that end with a car to wreck: armed before the phone   # jobs on a DISPLAY_TIMER (WHEELER-DEALING: 180 s for four dealers): full driving speed

def run_plan(entry):
    plan = entry["plan"]; car_at = None; last_target = None; left_car = None
    timed = entry.get("mission") in TIMED
    if timed:
        # PLAYTHROUGH-7: twice the pace of pt6_ze2c (1.3-1.6 blocks/s): no speed cap on the
        # straights, braking only into a turn (2.6 + 1.2 x distance), turns taken rolling
        # (M.RACE), and the position line every 3 frames (GTA2DX9_STATE_EVERY) so the
        # controller sees a fast car between corners
        M.FAST_CAP = float(os.environ.get("RACE_CAP", "11")); VIEW_SLEEP[0] = 0.7; M.LANE_COST = 0.8
        M.CORNER_V = (float(os.environ.get("RACE_TURN_V", "2.6")), float(os.environ.get("RACE_BRAKE_K", "1.2")))
        M.RACE[0] = True; M.RACE_TURN_V = M.CORNER_V[0]; M.LEAVE_WAIT[0] = 1.0
    money0 = (M.mission_state() or {}).get("money", 0)
    for step in plan:
        if "car" in step:
            car_at = step["at"]; say("plan: mission car", step["car"], "at", car_at); continue
        if "wait" not in step: continue
        cond, nums = step["wait"], step["numbers"]
        s = D.wait_state()
        o, ms = M.outcome(money0)
        if o in ("complete", "failed", "dead"): return o
        if "IS_CHARACTER_IN_CAR" in cond or "IS_CHARACTER_IN_ANY_CAR" in cond:
            if car_at:
                M.mark(f"to the car at {car_at[0]},{car_at[1]}")
                s = M.enter_car3(world, car_at[0], car_at[1], budget=200)
                if not (s and s["driving"]) and os.environ.get("WARP_OK", "1") == "1":
                    say("the walk to the mission car failed; developer warp to its door (reported)")
                    set_view("classic"); M.scene_warp(car_at[0], car_at[1] + 1.0, M.top_level(world, car_at[0], car_at[1]) or 1, "to the mission car's door"); set_view("third")
                    s = M.enter_car3(world, car_at[0], car_at[1], budget=90)
                say("in car:", bool(s and s["driving"]))
                if not (s and s["driving"]): return "stuck: could not enter the car"
                FP["until"] = 0.0; M.shot(f"{entry['mission']}_incar")
                # stay at the wheel until the script notices (its arrow leaves the car)
                t1 = time.time()
                while time.time() - t1 < 100:
                    o = M.objective()
                    if o is None or math.hypot(o[0] - car_at[0], o[1] - car_at[1]) > 3.0: break
                    time.sleep(0.5)
                say(f"in car: the objective moved on after {time.time()-t1:.0f}s: {M.objective()}")
        elif "LOCATE_CHARACTER_ON_FOOT" in cond:
            x, y, z, w, h = nums[1], nums[2], nums[3], nums[4], nums[5]
            tl = None if z >= 200 else max(0, int(round(z)) - 1)
            M.mark(f"on foot to {x},{y}")
            far = math.hypot(x - s["x"], y - s["y"])
            if not s["driving"] and far > 25 and s.get("parked") and s["pd"] < 14:
                s = M.enter_car3(world, s["px"], s["py"], budget=40)
            if timed and not s["driving"] and far > 12:
                # the timer starts on this box (WHEELER-DEALING's pickup): arrive by
                # car and keep it at the kerb, so the dealer legs start at the wheel
                s = M.any_car2(world, budget=90)
            if timed and s["driving"]:
                # a sound car for the clock: pt7_ze2b started the dealer legs in a borrowed
                # car at carhp 18289 and it caught fire 17 s into the first leg
                for k_car in range(3):
                    hp = (M.mission_state() or {}).get("carhp", -1)
                    if hp < 0 or hp >= 26000: break
                    say(f"timed job: this car is at carhp {hp}; another before the clock starts")
                    M.BAD_CARS.append((s["x"], s["y"])); s = M.leave_car(); s = M.any_car2(world, budget=90)
                    if not s["driving"]: break
            if s["driving"] and (far > 25 or timed):
                cell = M.street_cell_walk_nearest(world, x, y, radius=8, tl=tl) if timed else None
                if cell:
                    # the timer starts in the box: leave the car on the road beside it, not
                    # in the lot (pt6_ze2a spent 40 of its 180 s wobbling out of the lot)
                    # PLAYTHROUGH-8: before the clock there is no hurry: the drive in at a careful
                    # pace (pt8_ze2b raced in and hit the walls seven times, 31118 -> 20785, and
                    # the car burned on the third dealer's leg), and a car that arrives under
                    # 25000 is swapped for another before the box
                    race0 = (M.RACE[0], M.FAST_CAP); M.RACE[0] = False; M.FAST_CAP = 5.0
                    try:
                        s = M.drive3(world, cell[0], cell[1], tol=1.2, budget=200, view_switch=view_switch, slow=False)
                        for k_rt in range(2):
                            # the drive given up (a pinned borrowed car, pt8_ze2c at 206.7,68.6): another
                            # car, not a walk to the box without one (the clock then ran on foot)
                            if s["driving"] and math.hypot(cell[0] - s["x"], cell[1] - s["y"]) < 4: break
                            say("timed job: no car at the box yet; another car before the clock starts")
                            if s["driving"]: M.BAD_CARS.append((s["x"], s["y"])); s = M.leave_car()
                            s = M.any_car2(world, budget=90)
                            if not s["driving"]: break
                            s = M.drive3(world, cell[0], cell[1], tol=1.2, budget=200, view_switch=view_switch, slow=False)
                        for k_sw in range(2):
                            hp = (M.mission_state() or {}).get("carhp", -1)
                            if not s["driving"] or hp < 0 or hp >= 25000: break
                            say(f"timed job: the car reached the box at carhp {hp}; another before the clock starts")
                            M.BAD_CARS.append((s["x"], s["y"])); s = M.leave_car(); s = M.any_car2(world, budget=90)
                            if not s["driving"]: break
                            s = M.drive3(world, cell[0], cell[1], tol=1.2, budget=200, view_switch=view_switch, slow=False)
                    finally:
                        M.RACE[0], M.FAST_CAP = race0
                else:
                    s = M.drive3(world, x, y, tol=3.0, budget=200, view_switch=view_switch, slow=not timed)
            if timed and s["driving"]:
                # PLAYTHROUGH-8: the car arrives at the box heading the wrong way for the first
                # dealer (pt8_ze2a: a three-point turn on the clock into the pavement at
                # 240.5,44.1, 9 s and 10000 carhp). Turn it round before the clock starts: drive
                # a few cells along the first leg's route and park there
                idx0 = plan.index(step)
                ch = next((p_["at"] for p_ in plan[idx0 + 1:] if "char" in p_), None)
                if ch:
                    dst = next((st for (dx_, dy_), st in WD_STOPS.items() if math.hypot(ch[0] - dx_, ch[1] - dy_) < 4), (ch[0], ch[1]))
                    path0 = M.route3(world, int(s["x"]), int(s["y"]), M.ped_level(s), int(dst[0]), int(dst[1]), None, kinds=(1,), cost=M.CAR_COST)
                    if path0 and len(path0) > 8:
                        k0 = path0[min(6, len(path0) - 1)]; hx0, hy0 = M.heading(s)
                        vx0, vy0 = k0[0] + 0.5 - s["x"], k0[1] + 0.5 - s["y"]
                        if (hx0 * vx0 + hy0 * vy0) < -0.2 * math.hypot(vx0, vy0):
                            say(f"timed job: the car faces away from the first leg; turned round before the clock, parked at {k0[0]}.5,{k0[1]}.5")
                            race0 = M.RACE[0]; M.RACE[0] = False
                            try: s = M.drive3(world, k0[0] + 0.5, k0[1] + 0.5, tol=1.0, budget=60, slow=True)
                            finally: M.RACE[0] = race0
            if s["driving"]: left_car = (s["x"], s["y"]); s = M.leave_car(); M.mark("out of the car, walking")
            from_x, from_y = s["x"], s["y"]
            t_a = time.time()
            while time.time() - t_a < 4.0:
                o = M.objective()
                if o and (o[3] != 1 or math.hypot(o[0] - x, o[1] - y) < 2.5): break
                time.sleep(0.3)
            key0 = M.objective_key()
            far = math.hypot(x - s["x"], y - s["y"])
            if timed and not s["driving"] and 8 < far <= 25 and s.get("parked") and s["pd"] < 6:
                # (timed jobs only: pt6_le2c died in the PIZZA CAKE hop between the two
                # boxes, a 23-leg road detour for a 15-block walk, in a borrowed car)
                # a short hop by the car that brought him, to the road cell nearest the box
                cell = M.street_cell_near(world, x, y, radius=6)
                if cell:
                    s = M.enter_car3(world, s["px"], s["py"], budget=30)
                    if s and s["driving"]:
                        s = M.drive3(world, cell[0], cell[1], tol=1.5, budget=60, slow=True); s = M.leave_car()
            s = walk(x, y, tl, tol=max(0.3, min(w, h) * 0.4), budget=420)
            ok = M.settle_box(x, y, w, h, money0=money0, secs=45, nudge=nudge_to, key0=key0)
            if not ok:
                s = M.walk3(world, x, y, tl, tol=0.3, budget=60)
                ok = M.settle_box(x, y, w, h, money0=money0, secs=40, nudge=nudge_to, key0=key0)
            M.shot(f"{entry['mission']}_at_{int(x)}_{int(y)}")
            idx = plan.index(step)
            nxt = next((p for p in plan[idx + 1:] if "wait" in p), None)
            if ok and nxt and "count" in nxt["wait"]:
                # a countdown follows (the dynamite): run back the way he came
                M.mark("countdown: running clear")
                s = D.wait_state(); legs = M.escape_route(world, s)
                if not legs:
                    ex, ey = M.escape_point(world, x, y, tl if tl is not None else 1); legs = [(ex, ey)]
                say("escape legs:", [(round(a, 1), round(b, 1)) for a, b in legs])
                t_e = time.time()
                for k, (ex, ey) in enumerate(legs[:4]):
                    if time.time() - t_e > 10: break
                    M.cruise_to(ex, ey, tol=0.8, secs=max(2.0, 10 - (time.time() - t_e)), stop=(k == len(legs[:4]) - 1))
                xdo("keyup", "Up"); s = D.wait_state()
        elif "LOCATE_ANOTHER_CHARACTER_ON_FOOT" in cond:
            # the character was created at the plan's last 'char' position
            at = step.get("at")
            if at is None:
                idx = plan.index(step); at = next((p["at"] for p in reversed(plan[:idx]) if "char" in p), None)
            if not at: say("plan: no character position"); continue
            x, y = at[0], at[1]
            o = M.objective()
            if o and o[3] != 1 and math.hypot(o[0] - x, o[1] - y) < 12: x, y = o[0], o[1]   # the arrow follows him
            M.mark(f"to the character at {x},{y}")
            far = math.hypot(x - s["x"], y - s["y"])
            if far > 18:
                if not s["driving"] and left_car and math.hypot(left_car[0] - s["x"], left_car[1] - s["y"]) < 30:
                    # the car he stepped out of at the last dealer (WHEELER-DEALING's
                    # 180 s timer leaves no time for a kerb wait)
                    if timed and math.hypot(left_car[0] - s["x"], left_car[1] - s["y"]) < 3.2:
                        # the game walks him to a car near enough on Return by itself: no route,
                        # no door approach (pt7_ze2d spent 7-8 s per dealer walking back)
                        s = quick_enter()
                    if not s["driving"]:
                        s = M.enter_car3(world, left_car[0], left_car[1], budget=45)
                if not s["driving"]: s = M.any_car2(world, budget=60)
                if s["driving"]:
                    # stop seven road cells short of him and walk: the dealer stands on
                    # the road and the job fails when he is run over (pt5_ze2b after 60 s;
                    # pt5_ze2c coasted onto dealer 2 with a plain tolerance of 6)
                    sp = short_of(s, x, y, back=(int(os.environ.get("WD_BACK", "2")) if timed else 7))   # pt7_ze2c: 6-15 s of walking per dealer at back=4
                    if timed:
                        # PLAYTHROUGH-8: each dealer's stop planned on the map, cell by cell: the
                        # car stands in the lane next to his pavement, about two blocks before him,
                        # so he is ahead of the car's nose and the walk is round the nose and a
                        # step (pt7: the car stopped beside or past him, the walk ran into it).
                        # The third dealer's stop moved off lane 216, where traffic queued behind
                        # the car and boxed the walker in against the median (pt7_ze2o, 38 s).
                        for (dx_, dy_), stop in WD_STOPS.items():
                            if math.hypot(x - dx_, y - dy_) < 4: sp = stop
                    if timed and math.hypot(x - 164.5, y - 125.5) < 4:
                        for c in WD_TURN_AVOID: M.CAR_AVOID.add(c)
                    via = next((v_ for (dx_, dy_), v_ in WD_VIA.items() if math.hypot(x - dx_, y - dy_) < 4), None) if timed else None
                    if sp and via:
                        s = M.drive3(world, via[0], via[1], tol=1.6, budget=240, view_switch=view_switch, slow=False)
                    if sp: s = M.drive3(world, sp[0], sp[1], tol=1.2, budget=240, view_switch=view_switch, slow=not timed)
                    else: s = M.drive3(world, x, y, tol=(4.5 if timed else 7.0), budget=240, view_switch=view_switch, slow=not timed)
            if s["driving"]:
                left_car = (s["x"], s["y"]); hcar = M.heading(s); s = M.leave_car()
                # the car as it stands now (it rolls on after the stop): the nearest parked car
                car_now, head_now = left_car, hcar
                if s.get("parked") and s.get("pd", 99) < 2.5 and math.hypot(s.get("phx", 0), s.get("phy", 0)) > 0.5:
                    car_now, head_now = (s["px"], s["py"]), (s["phx"], s["phy"])
                    left_car = car_now
                o = M.objective()
                if o and o[3] != 1 and math.hypot(o[0] - x, o[1] - y) < 12: x, y = o[0], o[1]
                s = M.walk_round_car(x, y, car_now, head_now)
            o = M.objective()
            if o and o[3] != 1 and math.hypot(o[0] - x, o[1] - y) < 12: x, y = o[0], o[1]
            key0 = M.objective_key()
            if timed and math.hypot(x - s["x"], y - s["y"]) < 7 and M.line_clear(world, (s["x"], s["y"]), (x, y), M.ped_level(s), kinds=(1, 2, 3), half_width=0.25):
                M.ensure_view("classic"); s, _ = M.cruise_to(x, y, tol=0.7, secs=8)
            else:
                s = walk(x, y, None, tol=0.7, budget=300, fp_secs=0)
            if M.wait_objective_change(key0, 3.0, money0): M.shot(f"{entry['mission']}_char_{int(x)}_{int(y)}"); continue
            # he may have wandered: circle a little
            for k in range(4):
                o, ms = M.outcome(money0)
                if ms and ms["msg"] != (M.mission_state() or {}).get("msg"): break
                M.cruise_to(x + 1.2 * math.cos(k * 1.57), y + 1.2 * math.sin(k * 1.57), tol=0.4, secs=5)
            M.shot(f"{entry['mission']}_char_{int(x)}_{int(y)}")
        elif "LOCATE_CHARACTER_BY_CAR" in cond or "IS_CAR_IN_BLOCK" in cond:
            if "LOCATE" in cond: x, y, w, h = nums[1], nums[2], nums[4], nums[5]
            else: x, y, w, h = nums[2], nums[3], nums[5], nums[6]
            M.mark(f"by car to {x},{y}")
            if not s["driving"] and car_at:
                s = M.enter_car3(world, car_at[0], car_at[1], budget=120)
            tol = max(0.5, min(w, h) * 0.45); last_target = (x, y)
            msg0 = (M.mission_state() or {}).get("msg")
            if h < 1.5:
                # a narrow strip (a garage door): approach from the open side, then creep in
                s = M.drive3(world, x, y + 2.5, tol=1.2, budget=300, view_switch=view_switch, slow=True, precious=True)
                s = creep_in(x, y, msg0, money0)
            else:
                s = M.drive3(world, x, y, tol=tol, budget=300, view_switch=view_switch, slow=True, precious=True)
            time.sleep(1.5); M.shot(f"{entry['mission']}_car_{int(x)}_{int(y)}")
        elif "LOCATE_CHARACTER_ANY_MEANS" in cond:
            x, y, z, w, h = nums[1], nums[2], nums[3], nums[4], nums[5]
            tl = None if z >= 200 else max(0, int(round(z)) - 1)
            M.mark(f"any means to {x},{y}")
            key0 = M.objective_key()
            far = math.hypot(x - s["x"], y - s["y"])
            if not s["driving"] and far > 60 and entry.get("mission") != "wil_tra":
                s = M.any_car2(world, budget=90)
            if s["driving"]:
                s = M.drive3(world, x, y, tol=max(1.5, min(w, h) * 0.4), budget=300, view_switch=view_switch, slow=True, precious=True)
                if not M.inside_box(s, x, y, w, h):
                    s = M.leave_car(); s = walk(x, y, tl, tol=0.3, budget=200, fp_secs=0)
            else:
                s = walk(x, y, tl, tol=max(0.3, min(w, h) * 0.4), budget=420)
            ok = M.settle_box(x, y, w, h, money0=money0, secs=45, nudge=nudge_to, key0=key0)
            if not ok:
                s = M.walk3(world, x, y, tl, tol=0.3, budget=60)
                M.settle_box(x, y, w, h, money0=money0, secs=40, nudge=nudge_to, key0=key0)
        elif "IS_CHAR_PRESSING_HORN" in cond:
            M.mark("horn")
            msg0 = (M.mission_state() or {}).get("msg")
            for k in range(8):
                if last_target and s and math.hypot(last_target[0] - s["x"], last_target[1] - s["y"]) > 1.3:
                    say("horn: back to the spot first")
                    s = M.drive3(world, last_target[0], last_target[1], tol=1.0, budget=45, slow=True, precious=True)
                M.horn(2); time.sleep(2.0)
                ms = M.mission_state(); s = D.wait_state()
                if ms and ms["msg"] not in (msg0, "1648"): break
        elif "IS_CHAR_OBJECTIVE_PASSED" in cond:
            say("plan: waiting for the character (car still)")
            s = D.wait_state(); o_c = M.objective()
            if not s["driving"] and o_c and o_c[3] in (3, 4):
                # PLAYTHROUGH-8: out of the car (the guards were shot on foot) and the arrow
                # back on it: in again, the character boards the player's car
                M.mark("back to the marked car for the character"); s = M.enter_car3(world, o_c[0], o_c[1], budget=90)
            t0 = time.time(); m_start = (M.mission_state() or {}).get("msg")
            while time.time() - t0 < 60:
                time.sleep(2); o, ms = M.outcome(money0)
                if o != "running": return o
                cur = M.mission_state()
                if cur and cur["msg"] in ("1648", "7007"):
                    say("objective: told to go back; re-approaching and horning")
                    if last_target: s = M.drive3(world, last_target[0], last_target[1], tol=1.0, budget=45, slow=True, precious=True)
                    M.horn(2); time.sleep(2)
                elif cur and cur["msg"] != m_start: break
        elif "HAS_PARK_FINISHED" in cond:
            say("plan: parking"); time.sleep(12)
        elif "IS_CAR_CRUSHED" in cond:
            # the crane lifts a car from its pickup point (wil.mis: crusher2 at
            # 176.5,9.5 is crane1's FIRST point); park there, get out, step clear
            # the crusher (176.5,9.5) is a raised 3x3 platform (GMP: level-2 lids with
            # diagonal corners) the car cannot climb: it is the crane's DROP point. The
            # crane (tower at 174.5,11.5) lifts a car parked under its hook; pt4_wil11
            # pressed the car against the platform's south wall at 176.5,11.5 with the
            # player inside and nothing happened. Park at two candidate spots in the
            # yard in turn, get out, step clear, and watch the outcome
            near = last_target and math.hypot(last_target[0] - 171.5, last_target[1] - 11.5) < 15
            spots = [(177.0, 11.5), (176.5, 13.5)] if near else [(244.5, 243.5)]
            for k, spot in enumerate(spots):
                M.mark(f"to the crusher pad {spot}")
                if not s["driving"] and car_at: s = M.enter_car3(world, car_at[0], car_at[1], budget=90)
                s = M.drive3(world, spot[0], spot[1], tol=0.7, budget=100, slow=True, precious=True)
                s = D.wait_state(); car_at = (s["x"], s["y"]) if s else car_at
                s = M.leave_car(); M.mark("out of the car at the crusher")
                s = M.walk3(world, spot[0] - 4.5, spot[1] + 1.0, None, tol=0.8, budget=40)
                t1 = time.time(); o = "running"
                while time.time() - t1 < (75 if k == 0 else 60):
                    o, ms = M.outcome(money0)
                    if o != "running": break
                    time.sleep(2)
                M.shot(f"{entry['mission']}_crusher{k}")
                if o != "running": break
        elif "IS_CAR_WRECKED" in cond:
            # the gun first (pt4/pt5: ramming burned our own cars before the van, and
            # the player died at the wheel in pt5_le2g); ramming is the fallback
            FP["until"] = 0.0
            r = "no gun"
            for k in range(3):
                # out of rounds (pt6_le2f) or unarmed: the next pickup, then on shooting
                if not M.gun_ready(): M.fetch_gun(world, budget=300)
                if not M.gun_ready(): break
                M.mark("shoot the marked car until it wrecks")
                r = M.shoot_target(world, money0, secs=720, view_switch=view_switch)
                say("shoot:", r)
                if r != "no gun": break
            if r == "no gun":
                M.mark("ram the marked car until it wrecks")
                r = M.ram_target(world, money0, secs=600, view_switch=view_switch)
                say("ram:", r)
            M.shot(f"{entry['mission']}_wrecked"); set_view("third"); M.shot(f"{entry['mission']}_wrecked_third")
        elif "count" in cond:
            say("plan: briefs on screen, waiting for the mission arrow")
            t1 = time.time()
            while time.time() - t1 < 120 and M.objective() is None: time.sleep(0.5)
            say(f"plan: arrow after {time.time()-t1:.0f}s: {M.objective()}")
            if M.char_arrows():
                # PLAYTHROUGH-8: a kill counter with the arrows on characters: shoot them
                M.mark(f"shoot the {len(M.char_arrows())} marked characters")
                r = M.shoot_chars(world, money0); say("shoot_chars:", r)
            elif M.objective() and M.objective()[3] == 1:
                M.follow_arrow(world, money0, view_switch=view_switch)
        elif "CHECK_HEADS" in cond:
            say("plan: a fight is expected; following the arrow")
            if not M.follow_arrow(world, money0, view_switch=view_switch): time.sleep(30)
        else:
            say("plan: unhandled wait", cond)
            if not M.follow_arrow(world, money0, view_switch=view_switch): time.sleep(5)
        o, ms = M.outcome(money0)
        say("state:", o, ms)
        if o in ("complete", "failed", "dead"): return o
    o, ms = M.wait_outcome(money0, 60)
    return o

results = {}
for name in wanted:
    entry = next((m for m in world.db["missions"] if m.get("mission") == name), None)
    if not entry: say("no such mission", name); continue
    M.mark(f"mission {name}: {entry.get('title','')}")
    t_m = time.time()
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    if name in GUN_FIRST and not M.gun_ready():
        # PIZZA CAKE ends with a van to wreck: the machine gun beside the Loonies' phone
        # (76.5,39.5) on the way in, before the job starts (pt7_le2b went for a pickup 60
        # blocks off after the countdown and was run over at the kerb waiting for a car)
        M.mark("the machine gun beside the phone first")
        M.set_avoid_phones(world, keep=None)           # keep off both phones on the way to the gun
        M.fetch_gun(world, budget=420, near=(entry["x"], entry["y"]), count=2, walk_only=True)   # on foot: no drive through Loony turf
        M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
        say("gun before the phone:", (M.mission_state() or {}).get("weapon"))
    ok, ms = answer(entry)
    if not ok and time.time() - t_m < 600:
        say("phone: not answered on the first approach; once more"); ok, ms = answer(entry)
    M.arm_lives()
    say("answered:", ok, ms); M.shot(f"{name}_phone")
    if not ok:
        results[name] = "phone not answered"; M.mark(f"mission {name}: phone not answered"); continue
    # which job actually started: the title message names it (two phones stand side by side)
    title_key = ms["msg"] if ms else ""
    started = next((m for m in world.db["missions"] if m.get("plan") and m["plan"][0].get("display_message") == title_key), None)
    if started and started.get("mission") != name:
        say(f"the phone next door answered: {started['mission']} {started.get('title','')}; playing that plan")
        M.mark(f"mission {started['mission']}: {started.get('title','')} (started instead of {name})")
        entry = started; name = started["mission"]
    elif title_key in ("1097", "1096", "1103", "1098", "1102", "1104", "1113"):
        say("the gang refused the job (message", title_key, ")")
        results[name] = f"refused ({title_key})"; M.mark(f"mission {name}: refused {title_key}"); continue
    # step off the phone pair first: standing on the neighbour re-answers it
    # and the game holds him for every answer; from here on every route keeps
    # off every phone cell
    ax, ay = M.step_off_phone(world, entry)
    M.set_avoid_phones(world, keep=None)
    M.cruise_to(ax, ay, tol=0.5, secs=12)
    s = D.wait_state()
    if s and (s["z"] > 3.5 or WARPED_UP[0]) and os.environ.get("WARP_OK", "1") == "1":
        cell = M.street_cell_near(world, entry["x"], entry["y"])
        if cell:
            say(f"on a terrace (z {s['z']:.1f}, warped up {WARPED_UP[0]}) with no way down for the walker; developer warp to the street at {cell[0]},{cell[1]}")
            set_view("classic"); M.scene_warp(cell[0], cell[1], cell[2], "down from the phone terrace"); set_view("third")
    WARPED_UP[0] = False
    r = run_plan(entry)
    results[name] = f"{r} ({time.time()-t_m:.0f}s)"
    if r == "complete": M.DONE_PHONES.add((entry["x"], entry["y"]))
    M.mark(f"mission {name}: {results[name]}"); M.shot(f"{name}_end")
    time.sleep(4)
    if r == "dead":
        time.sleep(12)           # hospital; the next phone walk starts from there
say("RESULTS", results)
M.mark("done " + " ".join(f"{k}={v}" for k, v in results.items()))
