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

def set_view(name):
    order = ["classic", "third", "first"]
    while VIEW[0] != name:
        tap("v", 0.3); time.sleep(1.7)
        VIEW[0] = order[(order.index(VIEW[0]) + 1) % 3]
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
    if s and not s["driving"] and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) > 40:
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

def run_plan(entry):
    plan = entry["plan"]; car_at = None; last_target = None
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
            if s["driving"] and far > 25:
                s = M.drive3(world, x, y, tol=3.0, budget=200, view_switch=view_switch, slow=True)
            if s["driving"]: s = M.leave_car(); M.mark("out of the car, walking")
            from_x, from_y = s["x"], s["y"]
            t_a = time.time()
            while time.time() - t_a < 4.0:
                o = M.objective()
                if o and (o[3] != 1 or math.hypot(o[0] - x, o[1] - y) < 2.5): break
                time.sleep(0.3)
            key0 = M.objective_key()
            far = math.hypot(x - s["x"], y - s["y"])
            if not s["driving"] and 8 < far <= 25 and s.get("parked") and s["pd"] < 6:
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
            if far > 30:
                if not s["driving"]: s = M.any_car2(world, budget=60)
                if s["driving"]:
                    s = M.drive3(world, x, y, tol=3.0, budget=240, view_switch=view_switch, slow=True)
            if s["driving"]: s = M.leave_car()
            o = M.objective()
            if o and o[3] != 1 and math.hypot(o[0] - x, o[1] - y) < 12: x, y = o[0], o[1]
            key0 = M.objective_key()
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
                s = M.drive3(world, x, y + 2.5, tol=1.2, budget=300, view_switch=view_switch, slow=True)
                s = creep_in(x, y, msg0, money0)
            else:
                s = M.drive3(world, x, y, tol=tol, budget=300, view_switch=view_switch, slow=True)
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
                s = M.drive3(world, x, y, tol=max(1.5, min(w, h) * 0.4), budget=300, view_switch=view_switch, slow=True)
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
                    s = M.drive3(world, last_target[0], last_target[1], tol=1.0, budget=45, slow=True)
                M.horn(2); time.sleep(2.0)
                ms = M.mission_state(); s = D.wait_state()
                if ms and ms["msg"] not in (msg0, "1648"): break
        elif "IS_CHAR_OBJECTIVE_PASSED" in cond:
            say("plan: waiting for the character (car still)")
            t0 = time.time(); m_start = (M.mission_state() or {}).get("msg")
            while time.time() - t0 < 60:
                time.sleep(2); o, ms = M.outcome(money0)
                if o != "running": return o
                cur = M.mission_state()
                if cur and cur["msg"] in ("1648", "7007"):
                    say("objective: told to go back; re-approaching and horning")
                    if last_target: s = M.drive3(world, last_target[0], last_target[1], tol=1.0, budget=45, slow=True)
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
                s = M.drive3(world, spot[0], spot[1], tol=0.7, budget=100, slow=True)
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
            M.mark("ram the marked car until it wrecks")
            FP["until"] = 0.0
            r = M.ram_target(world, money0, secs=420, view_switch=view_switch)
            say("ram:", r)
        elif "count" in cond:
            say("plan: briefs on screen, waiting for the mission arrow")
            t1 = time.time()
            while time.time() - t1 < 120 and M.objective() is None: time.sleep(0.5)
            say(f"plan: arrow after {time.time()-t1:.0f}s: {M.objective()}")
        elif "CHECK_HEADS" in cond:
            say("plan: a fight is expected; waiting"); time.sleep(30)
        else:
            say("plan: unhandled wait", cond); time.sleep(5)
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
