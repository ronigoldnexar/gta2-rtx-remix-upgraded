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
wanted = sys.argv[1:] or os.environ.get("MISSIONS", "wil_tra wil_ye1 wil_ze2").split()
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
set_view("third")
FP = {"until": 0.0, "walk_until": 0.0}

def view_switch(s):
    now = time.time()
    if FP["until"] == 0.0:
        set_view("first"); FP["until"] = now + 18; M.mark("first person at the wheel")
    elif FP["until"] > 0 and now > FP["until"]:
        set_view("third"); FP["until"] = -1

def walk(tx, ty, tl=None, tol=0.5, budget=300, fp_secs=12):
    """a walk with a first-person stretch at its start"""
    if fp_secs:
        set_view("first")
        s = M.walk3(world, tx, ty, tl, tol=tol, budget=fp_secs)
        if s and math.hypot(tx - s["x"], ty - s["y"]) < tol: set_view("third"); return s
        set_view("third")
    return M.walk3(world, tx, ty, tl, tol=tol, budget=budget)

TITLES = {m["plan"][0].get("display_message"): m for m in []}
def answer(entry):
    """walk onto the phone and watch the message buffer closely: the job's title
    (19xx) flashes for a few seconds; the gang's refusals are 10xx"""
    before = M.mission_state(); m0 = before["msg"] if before else ""
    s = walk(entry["x"], entry["y"], None, tol=0.35, budget=360, fp_secs=10)
    t0 = time.time(); seen = []
    while time.time() - t0 < 24:
        ms = M.mission_state()
        if ms and ms["msg"] != m0 and ms["msg"] not in ("", "svdone", "1600", "1601", "1602", "1603"):
            if ms["msg"] not in seen: seen.append(ms["msg"])
            k = ms["msg"]
            if k.startswith("19") or k in ("1097", "1096", "1103", "1098", "1102", "1104"):
                say(f"phone: message {k} (seen {seen})"); ms = dict(ms); ms["msg"] = k; return True, ms
        if time.time() - t0 > 6 and not seen:
            nudge_to(entry["x"], entry["y"], tol=0.1, tries=4)
        time.sleep(0.25)
    if seen:
        say(f"phone: messages {seen}, no title caught"); ms = M.mission_state(); return True, ms
    return False, M.mission_state()

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
                s = M.enter_car3(world, car_at[0], car_at[1], budget=150)
                say("in car:", bool(s and s["driving"]))
                if not (s and s["driving"]): return "stuck: could not enter the car"
                FP["until"] = 0.0; M.shot(f"{entry['mission']}_incar")
        elif "LOCATE_CHARACTER_ON_FOOT" in cond:
            x, y, z = nums[1], nums[2], nums[3]
            tl = None if z >= 200 else max(0, int(round(z)) - 1)
            M.mark(f"on foot to {x},{y}")
            if s["driving"]: s = M.leave_car(); M.mark("out of the car, walking")
            msg0 = (M.mission_state() or {}).get("msg")
            s = walk(x, y, tl, tol=0.45, budget=420)
            settle(x, y, msg0, money0=money0); M.shot(f"{entry['mission']}_at_{int(x)}_{int(y)}")
        elif "LOCATE_ANOTHER_CHARACTER_ON_FOOT" in cond:
            # the character was created at the plan's last 'char' position
            at = step.get("at")
            if at is None:
                idx = plan.index(step); at = next((p["at"] for p in reversed(plan[:idx]) if "char" in p), None)
            if not at: say("plan: no character position"); continue
            x, y = at[0], at[1]
            M.mark(f"to the character at {x},{y}")
            if s["driving"]: s = M.leave_car()
            s = walk(x, y, None, tol=0.8, budget=420)
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
            x, y = nums[1], nums[2]
            M.mark(f"any means to {x},{y}")
            if s["driving"]:
                s = M.drive3(world, x, y, tol=2.0, budget=240, view_switch=view_switch, slow=True)
                if math.hypot(x - s["x"], y - s["y"]) > 1.0:
                    s = M.leave_car(); s = walk(x, y, None, tol=0.45, budget=200, fp_secs=0)
            else:
                msg0 = (M.mission_state() or {}).get("msg")
                s = walk(x, y, None, tol=0.45, budget=360)
                settle(x, y, msg0, money0=money0)
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
                if cur and cur["msg"] == "1648":
                    say("objective: told to go back; re-approaching and horning")
                    if last_target: s = M.drive3(world, last_target[0], last_target[1], tol=1.0, budget=45, slow=True)
                    M.horn(2); time.sleep(2)
                elif cur and cur["msg"] != m_start: break
        elif "HAS_PARK_FINISHED" in cond:
            say("plan: parking"); time.sleep(12)
        elif "IS_CAR_CRUSHED" in cond:
            say("plan: waiting for the crusher"); time.sleep(25)
        elif "IS_CAR_WRECKED" in cond:
            say("plan: ram the car until it wrecks")
            if car_at and not s["driving"]:
                s = M.enter_car3(world, car_at[0], car_at[1], budget=120)
            time.sleep(10)
        elif "count" in cond:
            say("plan: briefs on screen, waiting"); time.sleep(45)
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
    ok, ms = answer(entry)
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
    elif title_key in ("1097", "1096", "1103", "1098", "1102", "1104"):
        say("the gang refused the job (message", title_key, ")")
        results[name] = f"refused ({title_key})"; M.mark(f"mission {name}: refused {title_key}"); continue
    r = run_plan(entry)
    results[name] = f"{r} ({time.time()-t_m:.0f}s)"
    M.mark(f"mission {name}: {results[name]}"); M.shot(f"{name}_end")
    time.sleep(4)
    if r == "dead":
        time.sleep(12)           # hospital; the next phone walk starts from there
say("RESULTS", results)
M.mark("done " + " ".join(f"{k}={v}" for k, v in results.items()))
