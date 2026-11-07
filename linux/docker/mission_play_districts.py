#!/usr/bin/env python3
"""Plays missions of the Industrial (file bil) and Residential (file ste)
districts in the street-level views, with the Downtown runner's primitives
(mission_lib v3: the game's objective arrows, the multi-level router, the
held-key walker and driver) and per-mission scripts for the jobs whose plans
are counter loops rather than LOCATE waits.

Usage inside the container (the level is swapped by SWAP_LEVEL in the run script):
    DISTRICT=ste MISSIONS="ste_re1" python3 /work/mission_play_districts.py
    DISTRICT=bil MISSIONS="bil_re2" python3 /work/mission_play_districts.py

Third person on foot, first person for a stretch of every walk and every
drive. Marks in /out/marks.txt, milestone frames /out/m_*.png."""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
DISTRICT = os.environ.get("DISTRICT", "ste")
wanted = sys.argv[1:] or os.environ.get("MISSIONS", {"ste": "ste_re1", "bil": "bil_re2"}[DISTRICT]).split()
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
world = M.World(DISTRICT)
M.mark(f"level ({DISTRICT})")
M.arrows_baseline()
set_view("third")
FP = {"until": 0.0}
TITLES = {m["plan"][0].get("display_message"): m for m in world.db["missions"]
          if m.get("plan") and "display_message" in m["plan"][0]}

def view_switch(s):
    now = time.time()
    if FP["until"] == 0.0:
        set_view("first"); FP["until"] = now + 18; M.mark("first person at the wheel")
    elif FP["until"] > 0 and now > FP["until"]:
        set_view("third"); FP["until"] = -1

def money():
    return (M.mission_state() or {}).get("money", 0)

def msg():
    return (M.mission_state() or {}).get("msg", "")

def walk(tx, ty, tl=None, tol=0.5, budget=300, fp_secs=12):
    """a walk with a first-person stretch at its start"""
    if fp_secs:
        set_view("first")
        s = M.walk3(world, tx, ty, tl, tol=tol, budget=fp_secs)
        if s and math.hypot(tx - s["x"], ty - s["y"]) < tol: set_view("third"); return s
        set_view("third")
    return M.walk3(world, tx, ty, tl, tol=tol, budget=budget)

def nudge_to(x, y, tol=0.1, tries=30):
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

# ---------------------------------------------------------------- arrows

def wait_arrow(secs, kinds=None):
    """the mission arrow (x, y, z, kind, obj), optionally of the given kinds"""
    t0 = time.time()
    while time.time() - t0 < secs:
        o = M.objective()
        if o and (kinds is None or o[3] in kinds): return o
        time.sleep(0.4)
    return None

def wait_arrow_gone(secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        if M.objective() is None: return True
        time.sleep(0.3)
    return False

# ---------------------------------------------------------------- phones

def answer(entry):
    """get to the phone (by car when far, on foot up its stairs), stand on it,
    and read which job started from the game's title message or its arrow"""
    m0 = msg()
    s = D.wait_state()
    tl = None if entry["z"] >= 200 else max(1, int(round(entry["z"])) - 1)
    far = math.hypot(entry["x"] - s["x"], entry["y"] - s["y"])
    if s and not s["driving"] and far > 40:
        M.mark(f"a long way to the phone ({far:.0f} blocks): by car")
        s = M.any_car2(world, budget=120)
    if s and s["driving"]:
        FP["until"] = 0.0
        s = M.drive3(world, entry["x"], entry["y"], tol=5.0, budget=420, view_switch=view_switch, slow=False)
        s = M.leave_car(); set_view("third"); M.mark("out of the car near the phone")
    s = walk(entry["x"], entry["y"], tl, tol=0.35, budget=300, fp_secs=10)
    if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) > 1.2:
        s = M.walk3(world, entry["x"], entry["y"], tl, tol=0.35, budget=120)
    if s and math.hypot(entry["x"] - s["x"], entry["y"] - s["y"]) > 1.2 and os.environ.get("WARP_OK", "1") == "1":
        lvl = M.top_level(world, entry["x"], entry["y"])
        say(f"phone at {entry['x']},{entry['y']} not reached on foot (level {lvl}); developer warp")
        set_view("classic")
        s = M.scene_warp(entry["x"], entry["y"], lvl, "phone not reached on foot")
        set_view("third")
        s = M.walk3(world, entry["x"], entry["y"], None, tol=0.35, budget=60)
    t0 = time.time(); seen = []
    while time.time() - t0 < 30:
        k = msg()
        if k != m0 and k not in ("", "svdone"):
            if k not in seen: seen.append(k)
            if k in TITLES:
                say(f"phone: title {k} ({TITLES[k].get('title')})"); return True, k
        if M.mission_arrows():
            say(f"phone: a mission arrow is up (messages {seen})"); return True, (seen[-1] if seen else "")
        if time.time() - t0 > 6:
            nudge_to(entry["x"], entry["y"], tol=0.1, tries=4)
        time.sleep(0.25)
    say(f"phone: not answered (messages {seen})"); return False, (seen[-1] if seen else "")

# ---------------------------------------------------------------- driving helpers

def creep_box(x, y, w, h, money0, secs=75):
    """nose the car into the IS_CAR_IN_BLOCK box (w x h about x,y) with short
    pulses until the game reacts (the arrow leaves or the message changes)"""
    key0 = M.objective_key(); m0 = msg(); t0 = time.time(); k = 0
    while time.time() - t0 < secs:
        s = D.wait_state()
        if not s or not s["driving"]: return False, s
        if M.objective_key() != key0 or msg() != m0: return True, s
        o, ms = M.outcome(money0)
        if o != "running": return False, s
        if M.inside_box(s, x, y, w, h): time.sleep(1.5); continue
        hx, hy = M.heading(s); dx, dy = x - s["x"], y - s["y"]
        a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
        if abs(a) > 0.6 and math.hypot(dx, dy) > 0.7:
            xdo("keydown", "Down"); xdo("keydown", "Left" if a > 0 else "Right"); time.sleep(0.6)
            xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right"); time.sleep(0.3)
            continue
        if abs(a) > 0.12: xdo("keydown", "Right" if a > 0 else "Left")
        xdo("keydown", "Up"); time.sleep(0.25); xdo("keyup", "Up"); xdo("keyup", "Right"); xdo("keyup", "Left")
        time.sleep(0.5); k += 1
        if k % 6 == 0: hold("Down", 0.8); time.sleep(0.3)
    return False, D.wait_state()

def park_in_block(x, y, w, h, money0, budget=300):
    """drive the mission car into the block: the road route, then the creep"""
    M.mark(f"by car to the block at {x},{y} ({w}x{h})")
    s = M.drive3(world, x, y, tol=max(0.5, min(w, h) * 0.45 + 0.3), budget=budget, view_switch=view_switch, slow=True)
    ok, s = creep_box(x, y, w, h, money0)
    if not ok and s and s["driving"]:
        s = M.drive3(world, x, y, tol=0.5, budget=60, slow=True)
        ok, s = creep_box(x, y, w, h, money0, secs=60)
    say(f"park_in_block {x},{y}: {'reacted' if ok else 'no reaction'} at {s['x']:.2f},{s['y']:.2f}" if s else "park_in_block: no state")
    return ok, s

def arm_and_run(money0, armed_msgs, run_level=1):
    """the car bomb: fire arms it (the game says get out), leave, run clear"""
    M.mark("arming the explosives")
    m0 = msg(); armed = False
    for k in range(8):
        if k == 3: tap("Tab", 0.3); time.sleep(0.5)        # the weapon slot, in case the bomb is not selected
        xdo("keydown", "Control_L"); time.sleep(0.4); xdo("keyup", "Control_L"); time.sleep(1.0)
        if msg() in armed_msgs or (msg() != m0 and M.objective() is None): armed = True; break
    say(f"arm: {'armed' if armed else 'no reaction'} (msg {msg()})")
    s = D.wait_state(); cx, cy = s["x"], s["y"]
    M.leave_car(); M.mark("out of the car, running clear")
    s = D.wait_state()
    ex, ey = M.escape_point(world, cx, cy, run_level, dist=7)
    M.cruise_to(ex, ey, tol=1.0, secs=10)
    time.sleep(6.0)
    return armed

# ---------------------------------------------------------------- the jobs

def play_ste_re1(entry):
    """BLOW JOB! (Rednecks): a rigged Pickup at (24,41.5) into the 3x1 block
    by Fat Boy Jim's trailer (48.5,20.5); arm (fire), get out; then a second
    Pickup at (24,44.5) into the 3x1 block at the barricade (111.5,77.5)."""
    money0 = money()
    for stage, (car_at, box) in enumerate((((24.0, 41.5), (48.5, 20.5, 3.0, 1.0)), ((24.0, 44.5), (111.5, 77.5, 3.0, 1.0)))):
        o = wait_arrow(120 if stage else 30, kinds=(3, 4))
        if o: car_at = (o[0], o[1])
        M.mark(f"stage {stage+1}: to the Pickup at {car_at[0]:.1f},{car_at[1]:.1f}")
        s = D.wait_state()
        if s["driving"]: s = M.leave_car()
        s = M.enter_car3(world, car_at[0], car_at[1], budget=200)
        if not (s and s["driving"]): return f"stuck: pickup {stage+1} not entered"
        FP["until"] = 0.0; M.shot(f"{entry['mission']}_incar{stage+1}")
        o = wait_arrow(20, kinds=(1,))
        x, y, w, h = box if not o else (o[0], o[1], box[2], box[3])
        ok, s = park_in_block(x, y, w, h, money0)
        M.shot(f"{entry['mission']}_block{stage+1}")
        out, ms = M.outcome(money0)
        if out != "running": return out
        arm_and_run(money0, ("2006", "2018"))
        M.shot(f"{entry['mission']}_blast{stage+1}")
        t0 = time.time()
        while time.time() - t0 < 90:
            out, ms = M.outcome(money0)
            if out != "running": return out
            if stage == 0 and M.objective() is not None and M.objective()[3] in (3, 4): break
            if ms and ms["msg"] in ("2008", "2019"):      # "get back in and trigger the bomb": the arming did not take
                say("the game wants the bomb armed: back into the car")
                s = M.enter_car3(world, x, y, budget=90)
                if s and s["driving"]:
                    ok, s = creep_box(x, y, w, h, money0, secs=40)
                    arm_and_run(money0, ("2006", "2018"))
            time.sleep(1.0)
    o, ms = M.wait_outcome(money0, 120)
    return o

def play_bil_re2(entry):
    """MMM, RUSSIAN SAILORS! (Russians): the Z-Type at (48,73); four dealers
    to collect by car (horn beside each), then the car into the crane box at
    (135.5,5.5) and out of it: the crane dumps it in the water."""
    money0 = money()
    dealers = [(95.5, 171.5), (46.0, 187.0), (13.5, 233.5), (85.0, 147.0)]
    o = wait_arrow(30, kinds=(3, 4))
    car_at = (o[0], o[1]) if o else (48.0, 73.0)
    s = D.wait_state()
    if math.hypot(car_at[0] - s["x"], car_at[1] - s["y"]) > 40:
        M.mark(f"the Z-Type is {math.hypot(car_at[0] - s['x'], car_at[1] - s['y']):.0f} blocks away: by car")
        s = M.any_car2(world, budget=120)
        if s and s["driving"]:
            FP["until"] = 0.0
            s = M.drive3(world, car_at[0], car_at[1], tol=5.0, budget=420, view_switch=view_switch, slow=False)
            s = M.leave_car()
    o = M.objective()
    if o and o[3] in (3, 4): car_at = (o[0], o[1])
    s = M.enter_car3(world, car_at[0], car_at[1], budget=200)
    if not (s and s["driving"]): return "stuck: the Z-Type not entered"
    FP["until"] = 0.0; M.shot(f"{entry['mission']}_incar")
    stage = 0
    t_all = time.time()
    while time.time() - t_all < 1500:
        out, ms = M.outcome(money0)
        if out != "running": return out
        s = D.wait_state()
        if not s["driving"]:
            o = M.objective()
            if o and o[3] in (3, 4) and ms and ms["msg"] in ("3525",):
                M.mark("back to the Z-Type"); s = M.enter_car3(world, o[0], o[1], budget=120); continue
        o = wait_arrow(40)
        if o is None:
            time.sleep(2.0); continue
        x, y, z, kind = o[0], o[1], o[2], o[3]
        if kind in (3, 4) and stage < 4:
            M.mark(f"dealer {stage+1}: by car to {x:.1f},{y:.1f}")
            key0 = M.objective_key(); m0 = msg()
            s = M.drive3(world, x, y, tol=2.0, budget=360, view_switch=view_switch, slow=True)
            o2 = M.objective()
            if o2 and math.hypot(o2[0] - s["x"], o2[1] - s["y"]) > 2.6:
                s = M.drive3(world, o2[0], o2[1], tol=1.6, budget=120, slow=True)
            M.shot(f"{entry['mission']}_dealer{stage+1}")
            t0 = time.time(); boarded = False
            while time.time() - t0 < 100:
                cur = msg()
                if cur in ("3527", "3529", "3531", "3533"): boarded = True
                if M.objective_key() != key0 and boarded: break
                if M.objective_key() != key0 or cur == "3526":
                    M.horn(2); time.sleep(2.5)
                else:
                    o2 = M.objective()
                    if o2 and math.hypot(o2[0] - s["x"], o2[1] - s["y"]) > 2.6:
                        s = M.drive3(world, o2[0], o2[1], tol=1.6, budget=60, slow=True)
                    M.horn(1); time.sleep(2.0)
                out, ms = M.outcome(money0)
                if out != "running": return out
            say(f"dealer {stage+1}: {'boarded' if boarded else 'not confirmed'} after {time.time()-t0:.0f}s")
            stage += 1
            continue
        if kind == 1 or stage >= 4:
            M.mark(f"to the crane box at {x:.1f},{y:.1f}")
            s = M.drive3(world, x, y, tol=2.0, budget=420, view_switch=view_switch, slow=True)
            ok, s = creep_box(x, y, 7.0, 7.0, money0, secs=40)
            M.shot(f"{entry['mission']}_cranebox")
            M.leave_car(); M.mark("out of the car in the crane box")
            s = D.wait_state()
            ex, ey = M.escape_point(world, s["x"], s["y"], 1, dist=6)
            M.cruise_to(ex, ey, tol=1.0, secs=8)
            o, ms = M.wait_outcome(money0, 240)
            if o == "running":
                cur = msg()
                if cur == "3538":                       # "the car left the box": back in and park again
                    s = M.enter_car3(world, x, y, budget=90)
                    if s and s["driving"]:
                        creep_box(x, y, 7.0, 7.0, money0, secs=40); M.leave_car()
                        o, ms = M.wait_outcome(money0, 240)
            return o
    return "timeout"

PLAYS = {"ste_re1": play_ste_re1, "bil_re2": play_bil_re2}

results = {}
for name in wanted:
    entry = next((m for m in world.db["missions"] if m.get("mission") == name), None)
    if not entry: say("no such mission", name); continue
    M.mark(f"mission {name}: {entry.get('title','')}")
    t_m = time.time()
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    ok, key = answer(entry)
    say("answered:", ok, key); M.shot(f"{name}_phone")
    if not ok:
        results[name] = "phone not answered"; M.mark(f"mission {name}: phone not answered"); continue
    started = TITLES.get(key)
    if started and started.get("mission") != name:
        say(f"the phone next door answered: {started['mission']} {started.get('title','')}")
        M.mark(f"mission {started['mission']}: {started.get('title','')} (started instead of {name})")
        entry = started; name = started["mission"]
    ax, ay = M.step_off_phone(world, entry)
    M.set_avoid_phones(world, keep=None)
    M.cruise_to(ax, ay, tol=0.5, secs=12)
    play = PLAYS.get(name)
    if not play:
        say("no script for", name); results[name] = "no script"; continue
    r = play(entry)
    results[name] = f"{r} ({time.time()-t_m:.0f}s)"
    if r == "complete": M.DONE_PHONES.add((entry["x"], entry["y"]))
    M.mark(f"mission {name}: {results[name]}"); M.shot(f"{name}_end")
    time.sleep(4)
    if r == "dead": time.sleep(12)
say("RESULTS", results)
M.mark("done " + " ".join(f"{k}={v}" for k, v in results.items()))
