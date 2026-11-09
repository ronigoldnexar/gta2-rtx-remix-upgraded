#!/usr/bin/env python3
"""Skill: steal a car of a given model (SKILL-STEALCAR, Wave M).

26 jobs of docs/missions-catalogue.md need `steal_model`: "Steal a Taxi", "a Z-Type", "a Medicar",
"a Cop Car", "a Bus"... The car is a traffic car of that model (often a gang car or one the script
asks the game to spawn more of with SET_RECYCLE_MODEL_WANTED), or a parked one. The job script then
waits on IS_CHARACTER_IN_MODEL(p1, MODEL).

    import skills.steal_car as SC
    s = SC.steal_car(world, "STYPECAB", search=[(x, y), ...], budget=600, check=fn)

What the previous attempt taught (mission_lib.steal_model, DOUBLE-CROSS CRUSH runs dcc3/dcc4, 8 Nov):
  - the target is usually moving: walking at it from 15-30 blocks never catches it;
  - when the borrowed car is left next to the target, Return gets back into the borrowed car
    (dcc3: "in a model 44, not the one" three times with the Z-Type 1.4 blocks off), or into a
    passing car ("in a model 69");
so this skill:
  1. reads every car within 30 blocks from the renderer's `view: cars` line (id, model, position,
     heading, speed, carhp, fire, driver) and tracks one target by its id;
  2. on foot and the target near: walks to its DRIVER DOOR (the car's left side from its heading,
     then the right), faces it, Return; a moving target close by is met at the door point
     predicted half a second ahead; a target coming down the road toward him is waited for in
     its lane (GTA2 traffic brakes for a ped in front of it);
  3. on foot and the target far: takes any car (the carrier) and follows the target with the
     shared driver (watched: the drive stops when the target stands within reach), stops the
     carrier at least CARRIER_GAP blocks from it, gets out, and does (2) with the carrier
     remembered so a wrong entry into it is recognised and left at once;
  4. nothing of the model in sight: tours the search points (or a ring of road cells round the
     start) by car, watching the cars line; on foot, walks toward the next point.
Every wrong car entered is left again; burning cars are never targets. Returns the state
(driving the model) or None when the budget runs out or check() says stop.

Model numbers: the vehicle +0x84 word the renderer logs (`carmodel=`, `view: cars mNN`), which is
the script's model enum (MESSER 36, VTYPE 70, STRATOSB 48, BUS 11, COPCAR 12 ... verified in the
logs of earlier runs). MODELS below is that enum.
"""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

MODELS = {n: i for i, n in enumerate("""ALFA ALLARD AMDB4 APC BANKVAN BMW BOXCAR BOXTRUCK BUG CAR9 BUICK BUS COPCAR
DART EDSEL CAR15 FIAT FIRETRUK GRAHAM GT24640 CAR20 GTRUCK GUNJEEP HOTDOG HOTDOG_D1 HOTDOG_D2 HOTDOG_D3
ICECREAM ISETLIMO ISETTA JEEP JEFFREY LIMO LIMO2 MEDICAR MERC MESSER MIURA MONSTER MORGAN MORRIS PICKUP
RTYPE CAR43 SPIDER SPRITE STINGRAY STRATOS STRATOSB STRIPETB STYPE STYPECAB SWATVAN T2000GT TANK TANKER
TAXI TBIRD TOWTRUCK TRAIN TRAINCAB TRAINFB TRANCEAM TRUKCAB1 TRUKCAB2 TRUKCONT TRUKTRNS TVVAN VAN VESPA
VTYPE WBTWIN WRECK0 WRECK1 WRECK2 WRECK3 WRECK4 WRECK5 WRECK6 WRECK7 WRECK8 WRECK9 XK120 ZCX5 EDSELFBI""".split())}
# 0-70 checked against the logs (36 Messer, 51 the SINK OR SWIM taxi, 70 Z-Type, 48 Stratos-B, 11 bus,
# 12 cop car); 71-84 (WBTWIN, the wrecks, XK120, ZCX5, EDSELFBI) follow the published enum, unverified
# a job that says "a Taxi" may accept either taxi body; the script names the one it checks
ALIASES = {"TAXI_ANY": ("STYPECAB", "TAXI")}

CARRIER_GAP = 3.2       # blocks between the carrier and the target when he gets out
DOOR_OFF = 0.85         # the door point's distance from the car's centre line
WALK_MAX = 14.0         # a target nearer than this is walked to; farther, a carrier follows it
STAND_V = 0.45          # a car slower than this counts as standing (blocks per game second)
STATS = {"seen": 0, "jack_tries": 0, "wrong_entries": 0, "carriers": 0, "follow_legs": 0, "lane_waits": 0}

def model_ids(models):
    """'STYPECAB', 51, ('VTYPE', 'STRATOSB'), 'TAXI_ANY' -> a set of model numbers"""
    if isinstance(models, (str, int)): models = (models,)
    out = set()
    for m in models:
        if isinstance(m, int): out.add(m); continue
        for n in ALIASES.get(m.upper(), (m.upper(),)): out.add(MODELS[n])
    return out

def model_name(i):
    return next((n for n, k in MODELS.items() if k == i), str(i))

# ---------------------------------------------------------------- what the cars line says

def car_by_id(cid):
    return next((c for c in M.cars() if c["id"] == cid), None)

def usable(c, ids):
    return (c["model"] in ids and c["driver"] != "P" and c["hp"] > M.CAR_HP_FIRE and c["fire"] == 0
            and not M.bad_car(c["x"], c["y"]))

def targets(ids, s):
    """the usable cars of the models, cheapest first: distance, standing ones preferred"""
    out = []
    for c in M.cars():
        if not usable(c, ids): continue
        d = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
        cost = d + (0.0 if c["v"] < STAND_V else 4.0) + (0.0 if c["driver"] == "-" else 1.0)
        out.append((cost, d, c))
    out.sort(key=lambda t: t[0])
    return [(d, c) for _, d, c in out]

def doors(c):
    """the driver's door point (the car's left, from its heading; y grows southward) and the other"""
    hx, hy = c["hx"], c["hy"]
    n = math.hypot(hx, hy)
    if n < 0.1: hx, hy = 0.0, 1.0
    else: hx, hy = hx / n, hy / n
    return [(c["x"] + hy * DOOR_OFF, c["y"] - hx * DOOR_OFF), (c["x"] - hy * DOOR_OFF, c["y"] + hx * DOOR_OFF)]

def in_model(s, ids):
    return bool(s and s["driving"] and s.get("cmodel") in ids)

# ---------------------------------------------------------------- on foot: the door and Return

def face(x, y, tries=4):
    for _ in range(tries):
        s = D.wait_state()
        if not s or s["driving"]: return s
        a = D.angle_to(s, x, y)
        if abs(a) < 0.35: return s
        key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
        hold(key, min(abs(a) / max(D.rate, 2.0), 0.35)); time.sleep(0.3)
    return D.wait_state()

def enter_wait(secs=5.0):
    """after Return: poll until driving, or until the ped is no longer on his way into a car"""
    t0 = time.time(); s = D.wait_state()
    while time.time() - t0 < secs:
        time.sleep(0.25); s = D.wait_state()
        if s["driving"]: return s
        if time.time() - t0 > 2.5 and s.get("state") not in (2, 3, 6): break
    return s

def leave_wrong(s, why):
    STATS["wrong_entries"] += 1
    say(f"steal_car: in a {model_name(s.get('cmodel', -1))} ({why}); out again")
    return M.leave_car()

def jack(c0, ids, budget=30.0, carrier=None):
    """on foot: into the car `c0` (tracked by its id) by its doors; returns the state"""
    t0 = time.time(); k = 0; cid = c0["id"]
    M.ensure_view("classic")              # the foot view (the chase view with GTA2_DIRECT_KEYS)
    while time.time() - t0 < budget:
        s = D.wait_state()
        if not s: return s
        if s["driving"]:
            if in_model(s, ids): return s
            s = leave_wrong(s, "a wrong car at the door"); continue
        c = car_by_id(cid)
        if not c or not usable(c, ids): say("steal_car: the target is gone (out of the line, burning, or taken)"); return s
        d = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
        if d > WALK_MAX + 4: say(f"steal_car: the target drove off ({d:.0f} blocks)"); return s
        lead = min(0.6, d / 4.0) if c["v"] > STAND_V else 0.0
        cc = dict(c); cc["x"] += c["hx"] * c["v"] * lead; cc["y"] += c["hy"] * c["v"] * lead
        dp = doors(cc)[k % 2]
        if carrier and math.hypot(dp[0] - carrier[0], dp[1] - carrier[1]) < 1.6:
            dp = doors(cc)[(k + 1) % 2]      # the door on the carrier's side: the other one
        dd = math.hypot(dp[0] - s["x"], dp[1] - s["y"])
        if dd > 4.0 and c["v"] < STAND_V:
            path = M.route3(WORLD[0], int(s["x"]), int(s["y"]), M.ped_level(s), int(dp[0]), int(dp[1]))
            if len(path) > 4:
                wx, wy, wl = path[min(len(path) - 1, 12)]
                M.walk3(WORLD[0], wx + 0.5, wy + 0.5, wl, tol=1.0, budget=20); continue
        if c["v"] >= STAND_V and d > 3.0:
            # moving and not at hand: a ped never catches it from behind (sos1: two Returns 2.5
            # and 15 blocks from a taxi doing 2.3 put him back into the carrier). Its lane ahead
            # of it, or back to the caller
            if not lane_wait(c, s): say(f"steal_car: the target moves on ({d:.1f} off, v {c['v']:.1f})"); return s
            continue
        if dd > 0.7:
            M.cruise_to(dp[0], dp[1], tol=0.6, secs=2.5 if c["v"] > STAND_V else 6)
            s = D.wait_state()
            if s["driving"]: continue
        c = car_by_id(cid) or c
        d = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
        if d > 2.1:
            # Return enters the NEAREST car: only with the target at hand (dcc3, sos1: the carrier
            # or a passing car otherwise)
            say(f"steal_car: not at the door yet ({d:.1f} from the target); no Return"); continue
        face(c["x"], c["y"])
        STATS["jack_tries"] += 1; k += 1
        say(f"steal_car: Return at {s['x']:.1f},{s['y']:.1f} for the {model_name(c['model'])} at {c['x']:.1f},{c['y']:.1f} (v {c['v']:.1f}, driver {c['driver']}), try {k}")
        tap("Return", 0.3)
        s = enter_wait(6.0 if c["v"] < STAND_V else 4.0)
    return D.wait_state()

def lane_wait(c, s, secs=6.0):
    """the target comes down the road at him: step into its path a few blocks ahead of it and
    wait; GTA2 traffic brakes for a ped in front. True when it stands within reach"""
    hx, hy = c["hx"], c["hy"]
    fx, fy = s["x"] - c["x"], s["y"] - c["y"]
    ahead = fx * hx + fy * hy; lat = -fx * hy + fy * hx
    if not (3.0 < ahead < 14.0 and abs(lat) < 3.0 and c["v"] > STAND_V): return False
    px, py = c["x"] + hx * ahead, c["y"] + hy * ahead
    STATS["lane_waits"] += 1
    say(f"steal_car: the {model_name(c['model'])} comes at him ({ahead:.1f} ahead, {lat:+.1f} aside): into its lane at {px:.1f},{py:.1f}")
    M.cruise_to(px, py, tol=0.4, secs=min(3.0, abs(lat) / 1.5 + 0.6))
    t0 = time.time()
    while time.time() - t0 < secs:
        c2 = car_by_id(c["id"]); s = D.wait_state()
        if not c2 or s["driving"]: return False
        d = math.hypot(c2["x"] - s["x"], c2["y"] - s["y"])
        if d < 3.2 and c2["v"] < STAND_V: return True
        if d < 1.8: return True
        time.sleep(0.2)
    return False

# ---------------------------------------------------------------- the carrier

WORLD = [None]

def stop_car():
    hold("space", 0.5); hold("Down", 0.2); time.sleep(0.3)
    return D.wait_state()

def follow(c0, ids, drive, budget=90.0):
    """in the carrier: after the target (by id) until it stands within reach; True then"""
    cid = c0["id"]; t0 = time.time(); lost = 0
    while time.time() - t0 < budget:
        s = D.wait_state()
        if not (s and s["driving"]): return False
        c = car_by_id(cid)
        if not c or not usable(c, ids):
            lost += 1
            if lost > 3: say("steal_car: lost the target while following"); return False
            time.sleep(0.4); continue
        lost = 0
        d = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
        if d < 7.0 and c["v"] < STAND_V: return True
        if d < CARRIER_GAP + 1.5:
            # right behind a moving one: keep the gap (sos1 got out here behind a taxi doing 2.3
            # and lost it); out only when it stands
            xdo("keyup", "Up"); time.sleep(0.3); continue
        # a goal a car length behind the target, on its track
        gx, gy = c["x"] - c["hx"] * CARRIER_GAP, c["y"] - c["hy"] * CARRIER_GAP
        STATS["follow_legs"] += 1
        def stop_when(cid=cid):
            s2 = D.wait_state(); c2 = car_by_id(cid)
            if not c2 or not s2: return True
            d2 = math.hypot(c2["x"] - s2["x"], c2["y"] - s2["y"])
            if d2 < 7.0 and c2["v"] < STAND_V: return True
            return math.hypot(c2["x"] - gx, c2["y"] - gy) > 6.0      # it moved on: a new goal
        drive(WORLD[0], gx, gy, tol=2.5, budget=12 if d < 25 else 25, until=stop_when)
    return False

def get_carrier(budget=90):
    STATS["carriers"] += 1
    s = M.any_car2(WORLD[0], budget=budget)
    return s

def rel(c, s):
    """(ahead, aside) of the point s in the frame of car c: ahead > 0 means c is driving at it"""
    hx, hy = c["hx"], c["hy"]; n = math.hypot(hx, hy) or 1.0; hx, hy = hx / n, hy / n
    fx, fy = s["x"] - c["x"], s["y"] - c["y"]
    return fx * hx + fy * hy, -fx * hy + fy * hx

def ambush_in_car(c0, ids, secs=10.0):
    """in a car with the target coming at it: stand still in its way; True when it stands (or
    is upon him) within reach, False when it passes or turns off"""
    STATS["ambushes"] = STATS.get("ambushes", 0) + 1
    say(f"steal_car: the {model_name(c0['model'])} comes at the car ({c0['v']:.1f}); waiting in its way")
    stop_car(); t0 = time.time()
    while time.time() - t0 < secs:
        s = D.wait_state(); c = car_by_id(c0["id"])
        if not c or not s or not usable(c, ids): return False
        d = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
        ahead, lat = rel(c, s)
        if c["v"] < STAND_V and d < 6.0: return True
        if ahead < 0.5 or abs(lat) > 4.0 or d > 32: return False
        time.sleep(0.25)
    c = car_by_id(c0["id"]); s = D.wait_state()
    return bool(c and s and c["v"] < STAND_V and math.hypot(c["x"] - s["x"], c["y"] - s["y"]) < 6.0)

def intercept(c, ids, drive):
    """a target driving away far off: a road point 14 blocks ahead of it, watched"""
    STATS["intercepts"] = STATS.get("intercepts", 0) + 1
    cell = M.street_cell_near(WORLD[0], c["x"] + c["hx"] * 14.0, c["y"] + c["hy"] * 14.0, radius=5)
    if not cell: return D.wait_state()
    say(f"steal_car: the {model_name(c['model'])} drives away ({c['v']:.1f}); to {cell[0]:.0f},{cell[1]:.0f} ahead of it")
    def stop_when(cid=c["id"]):
        s2 = D.wait_state(); c2 = car_by_id(cid)
        if not c2 or not s2: return True
        a2, l2 = rel(c2, s2); d2 = math.hypot(c2["x"] - s2["x"], c2["y"] - s2["y"])
        return (2.0 < a2 < 25.0 and abs(l2) < 3.0) or (c2["v"] < STAND_V and d2 < 10.0)
    return drive(WORLD[0], cell[0], cell[1], tol=3.0, budget=25, until=stop_when)

# ---------------------------------------------------------------- the skill

def ring_points(world, x, y, r=22):
    pts = []
    for ang in range(0, 360, 60):
        c = M.street_cell_near(world, x + r * math.cos(math.radians(ang)), y + r * math.sin(math.radians(ang)), radius=8)
        if c: pts.append((c[0], c[1]))
    return pts or [(x, y)]

def steal_car(world, models, search=None, budget=900, drive=None, check=None, view_switch=None):
    """into a car of `models` (names or numbers, see MODELS). `search`: (x,y) road points to
    tour when none is in sight (default: a ring round where he stands). `drive(world, x, y,
    tol=, budget=, until=)`: the driver (default the shared M.drive3). `check()`: called
    every step; a true value ends the skill (the job failed, he died). Returns the state
    when driving the model, else None."""
    WORLD[0] = world; M.world_ref[0] = world
    ids = model_ids(models)
    if drive is None:
        def drive(w, x, y, tol=2.0, budget=60, until=None):
            return M.drive3(w, x, y, tol=tol, budget=budget, view_switch=view_switch, until=until)
    s = D.wait_state()
    if search is None: search = ring_points(world, s["x"], s["y"])
    names = "/".join(model_name(i) for i in sorted(ids))
    M.mark(f"steal_car: wanted {names} ({sorted(ids)})")
    t0 = time.time(); k = 0; carrier = None
    while time.time() - t0 < budget:
        if check and check(): say("steal_car: check() says stop"); return None
        s = D.wait_state()
        if not s: return None
        if in_model(s, ids):
            M.mark(f"steal_car: in a {model_name(s['cmodel'])} at {s['x']:.1f},{s['y']:.1f} after {time.time() - t0:.0f}s {STATS}")
            return s
        cand = targets(ids, s)
        if cand:
            d, c = cand[0]
            STATS["seen"] += 1
            ahead, lat = rel(c, s)
            coming = c["v"] >= STAND_V and 2.0 < ahead < 30.0 and abs(lat) < 3.0
            if s["driving"]:
                carrier = None
                if coming:
                    # head-on: stop in its lane; traffic brakes for a car standing in its way
                    if not ambush_in_car(c, ids): continue
                elif c["v"] >= STAND_V:
                    if d < 15.0:
                        say(f"steal_car: following the {model_name(c['model'])} at {c['x']:.1f},{c['y']:.1f} ({d:.1f} off, v {c['v']:.1f}, driver {c['driver']})")
                        if not follow(c, ids, drive, budget=30): continue
                    else:
                        intercept(c, ids, drive); continue
                elif d > 7.0:
                    say(f"steal_car: to the standing {model_name(c['model'])} at {c['x']:.1f},{c['y']:.1f} ({d:.1f} off, driver {c['driver']})")
                    if not follow(c, ids, drive, budget=60): continue
                s = stop_car()
                c = car_by_id(c["id"]) or c
                d = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
                if c["v"] >= STAND_V and d > 3.0: continue
                carrier = (s["x"], s["y"])
                M.mark(f"steal_car: out of the carrier {d:.1f} from the {model_name(c['model'])} (v {c['v']:.1f})")
                s = M.leave_car()
                s = jack(c, ids, budget=30, carrier=carrier)
                continue
            # on foot
            if c["v"] < STAND_V and d <= 2 * WALK_MAX or d <= 3.0:
                M.mark(f"steal_car: on foot to the {model_name(c['model'])} at {c['x']:.1f},{c['y']:.1f} ({d:.1f} off, v {c['v']:.1f})")
                s = jack(c, ids, budget=40, carrier=carrier)
                continue
            if coming and ahead < 16.0:
                if lane_wait(c, s, secs=8.0):
                    s = jack(c, ids, budget=14, carrier=carrier)
                continue
            # moving, not toward him: a carrier (a parked car or one from the kerb)
            say(f"steal_car: the {model_name(c['model'])} is {d:.0f} off and moving away: a carrier")
            get_carrier(budget=60)
            continue
        # nothing of the model in sight
        if s["driving"]:
            px, py = search[k % len(search)]; k += 1
            M.mark(f"steal_car: no {names} in sight; touring to {px:.0f},{py:.0f}")
            drive(world, px, py, tol=4.0, budget=150,
                  until=lambda: any(usable(c, ids) for c in M.cars()))
            continue
        if s["parked"] and s["pd"] < 10 and not M.bad_car(s["px"], s["py"]):
            s2 = M.enter_car3(world, s["px"], s["py"], budget=40)
            if s2 and s2["driving"]: STATS["carriers"] += 1; continue
        px, py = search[k % len(search)]
        if math.hypot(px - s["x"], py - s["y"]) < 6: k += 1; continue
        path = M.route3(world, int(s["x"]), int(s["y"]), M.ped_level(s), int(px), int(py))
        if len(path) > 2:
            wx, wy, wl = path[min(len(path) - 1, 16)]
            M.walk3(world, wx + 0.5, wy + 0.5, wl, tol=1.0, budget=30)
        else:
            k += 1
            get_carrier(budget=40)
    M.mark(f"steal_car: no {names} taken in {budget}s {STATS}")
    return None
