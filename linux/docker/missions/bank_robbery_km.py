#!/usr/bin/env python3
"""BANK ROBBERY! (wil_ye2) with its guard fight done by the kill-marked skill (SKILL-KILLMARK).

    python3 /work/missions/bank_robbery_km.py        (inside the container, after to_level.sh)

The job's own runner (missions/bank_robbery.py, PLAYTHROUGH-10) is used unchanged for everything
around the fight: the phone, the GRAHAM, the bank box, the pre-positioned getaway, the respray and
the safehouse. Its hand-written guard loop is replaced by `skills/kill_marked.kill_marked` with the
job's facts as arguments only: the targets (marked `crim/police` peds near the bank walk; Hiroshi,
the Yakuza inside man who walks out behind them, is spared and never in the line of fire), the
stairs (the job's CLIMB points to level 2) and the walk's fire spots. Frames /out/m_km_*.png and
/out/m_br_*.png, marks /out/marks.txt."""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
from missions import bank_robbery as BR
from skills import kill_marked as K

say, hold, xdo = D.say, D.hold, D.xdo


def is_guard(p):
    return p["gang"] == "police" and p["type"] != "cop" and \
        min(math.hypot(p["x"] - gx, p["y"] - gy) for gx, gy in BR.GUARDS) < 8


def is_spare(p):
    # Hiroshi: a Yakuza out of door16 beside the guards; any non-target near the walk
    return p["gang"] == "yakuza" and math.hypot(p["x"] - 186.0, p["y"] - 175.0) < 6


def job_check():
    return BR.check()


CAR = {"model": None, "at": None}
GETAWAY_LEGS = [(216.5, 181.0), (216.5, 213.0)]   # east along row 180, south down column 216

def to_car(world):
    """back into the GRAHAM where it is now: the model read at the wheel, found in `view: cars`
    nearest to where it was last seen (km2: a gang member took it 17 s into the getaway and the
    job runner walked to where it had been parked)"""
    s = D.wait_state()
    if s["driving"]: return s
    at = CAR["at"] or BR.CAR0
    if CAR["model"] is not None:
        cs = [c for c in M.cars() if c["model"] == CAR["model"]]
        if cs:
            c = min(cs, key=lambda c: math.hypot(c["x"] - at[0], c["y"] - at[1]))
            at = (c["x"], c["y"])
    M.mark(f"back to the GRAHAM at {at[0]:.1f},{at[1]:.1f}")
    s = M.enter_car3(world, at[0], at[1], budget=60)
    if s and s["driving"]: BR.FP["until"] = -1; M.ensure_view("third"); remember_car()
    return s

def remember_car():
    s = D.wait_state(); ms = M.mission_state() or {}
    if s and s["driving"]:
        if ms.get("carmodel", -1) >= 0: CAR["model"] = ms["carmodel"]
        CAR["at"] = (s["x"], s["y"])

def roll_in(x, y, secs=25, until=None):
    """into a drive-through shop without stopping: Up held all the way, steering pulses toward
    (x, y), the handbrake once inside (km1: the drive stopped at the tunnel mouth with officers
    1-1.5 blocks off, he was pulled out and arrested, 1666)"""
    t0 = time.time()
    xdo("keydown", "Up")
    try:
        while time.time() - t0 < secs:
            s = D.wait_state()
            if not s or not s["driving"]: return s
            BR.check()
            if until and until(): return s
            if abs(s["x"] - x) < 0.45 and abs(s["y"] - y) < 0.5:
                xdo("keyup", "Up"); hold("space", 0.4); return s
            hx, hy = M.heading(s); dx, dy = x - s["x"], y - s["y"]
            a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
            if abs(a) > 0.7:
                # not lined up (km6: arriving along row 216 at speed, the Up-held turn into the
                # one-cell tunnel circled at its mouth until an officer pulled him out): stop,
                # point the nose with reverse/forward pulses, then on
                xdo("keyup", "Up"); hold("space", 0.3)
                BR.turn_car_toward(x, y, secs=12); xdo("keydown", "Up"); continue
            if abs(a) > 0.08:
                key = "Right" if a > 0 else "Left"
                xdo("keydown", key); time.sleep(min(0.25, abs(a) * 0.4)); xdo("keyup", key)
            time.sleep(0.12)
    finally:
        xdo("keyup", "Up")
    return D.wait_state()


# Each respray block is four one-cell drive-through bays under one roof (wil.mis): at row 221 the
# bays at columns 200/202/204/206 are the machine-gun, BOMB, respray (CAR_SHOP 10) and oil-slick
# shops, and the same at row 160 (82/84/86/88; respray 86). km6 swung into the shop turning off
# row 216 at speed, ended in the 202 bay, paid $5,000 for a car bomb (money 5040 -> 41, wanted
# still 2: no money left for the respray), and the reverse pulses of the turn backed him out into
# an officer (1666, arrest). The bay is now entered only lined up: stop on the carriageway in
# front of it, turn there, then a straight run down the bay's centre line.
BAYS = {(204.5, 221.5): +1, (86.5, 160.5): -1}     # shop -> direction along y into the bay

def bay_pre(shop):
    d = BAYS[shop]; return (shop[0], shop[1] - d * 6.0)

def speed(prev, s, dt):
    return math.hypot(s["x"] - prev["x"], s["y"] - prev["y"]) / max(dt, 1e-3)

def stop_car(secs=2.0):
    xdo("keyup", "Up"); t0 = time.time(); prev = D.wait_state(); tp = time.time()
    xdo("keydown", "space")
    try:
        while time.time() - t0 < secs:
            time.sleep(0.15); s = D.wait_state(); now = time.time()
            if not s or not s["driving"]: return s
            if speed(prev, s, now - tp) < 0.3: return s
            prev, tp = s, now
    finally:
        xdo("keyup", "space")
    return D.wait_state()

def lane_in(shop, secs=30, until=None, vmax=3.0):
    """into a one-cell drive-through bay along its centre line (pure pursuit on x = shop x, 1.8
    blocks ahead), the throttle on only while lined up and under vmax (blocks per wall second);
    a wrong bay (off the line past the bay's mouth) is backed out of straight"""
    lx, sy = shop; d = BAYS[shop]; mouth = sy - d * 1.7
    t0 = time.time(); prev = D.wait_state(); tp = time.time(); thr = [False]
    def throttle(on):
        if on != thr[0]: xdo("keydown" if on else "keyup", "Up"); thr[0] = on
    try:
        while time.time() - t0 < secs:
            time.sleep(0.07)
            s = D.wait_state(); now = time.time()
            if not s or not s["driving"]: return s
            v = speed(prev, s, now - tp); prev, tp = s, now
            BR.check()
            if until and until(): throttle(False); return s
            ex = s["x"] - lx; along = (s["y"] - sy) * d          # along: < 0 before the shop point
            if along > -0.35 and abs(ex) < 0.5:
                throttle(False); hold("space", 0.5); return s
            if (s["y"] - mouth) * d > 0 and abs(ex) > 0.7:
                throttle(False); M.mark(f"lane_in: in the wrong bay at {s['x']:.1f},{s['y']:.1f}: straight back out")
                stop_car(); hold("Down", 1.4); stop_car()
                BR.turn_car_toward(lx, sy, secs=8); prev, tp = D.wait_state(), time.time(); continue
            ty = s["y"] + d * 1.8
            if (ty - sy) * d > 1.0: ty = sy + d * 1.0
            hx, hy = M.heading(s); dx, dy = lx - s["x"], ty - s["y"]
            a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
            if abs(a) > 1.0 and (s["y"] - mouth) * d < 0:
                throttle(False); stop_car(); BR.turn_car_toward(lx, sy, secs=8)
                prev, tp = D.wait_state(), time.time(); continue
            throttle(abs(a) < 0.45 and v < vmax)
            if abs(a) > 0.05:
                key = "Right" if a > 0 else "Left"
                xdo("keydown", key); time.sleep(min(0.18, abs(a) * 0.3)); xdo("keyup", key)
    finally:
        throttle(False)
    return D.wait_state()


def run(world, entry):
    # 1-2. the car and the bank box: as the job's runner
    M.mark("to the GRAHAM at 52.5,150.5")
    s = M.enter_car3(world, BR.CAR0[0], BR.CAR0[1], budget=200)
    if not (s and s["driving"]) and os.environ.get("WARP_OK", "1") == "1":
        say("the walk to the mission car failed; developer warp to its door (reported)")
        BR.set_view("classic"); M.scene_warp(BR.CAR0[0], BR.CAR0[1] + 1.0, M.top_level(world, BR.CAR0[0], BR.CAR0[1]) or 1, "to the mission car's door"); BR.set_view("third")
        s = M.enter_car3(world, BR.CAR0[0], BR.CAR0[1], budget=90)
    if not (s and s["driving"]): return "stuck: could not enter the car"
    M.shot("br_incar"); BR.FP["until"] = 0.0; remember_car()
    t1 = time.time()
    while time.time() - t1 < 30 and not BR.arrow_near(BR.BANK_BOX[0], BR.BANK_BOX[1]): time.sleep(0.5)
    BR.check()
    M.mark("to the City Bank box 194.5,177.5 (in the car)")
    for k in range(4):
        s = D.wait_state()
        if not s["driving"]:
            s = BR.to_mission_car(world, BR.CAR0 if k == 0 else (s.get("px", BR.CAR0[0]), s.get("py", BR.CAR0[1])))
            if not s["driving"]: continue
        s = BR.drive(world, BR.BANK_STOP[0], BR.BANK_STOP[1], 1.2, 420,
                     until=lambda: (M.mission_state() or {}).get("msg") == "1665" or bool(BR.guards()))
        BR.check()
        s = D.wait_state()
        if s["driving"] and math.hypot(BR.BANK_STOP[0] - s["x"], BR.BANK_STOP[1] - s["y"]) < 6:
            BR.creep_in(BR.BANK_STOP[0], BR.BANK_STOP[1], 1.6, 1.2, secs=30)
        t2 = time.time()
        while time.time() - t2 < 8 and not BR.guards(): time.sleep(0.5)
        if BR.guards(): break
    t2 = time.time()
    while time.time() - t2 < 30 and not BR.guards(): time.sleep(0.5); BR.check()
    gs = BR.guards(); ms = BR.check()
    say(f"guards: {[(p['id'], p['x'], p['y'], p['z'], p['hp']) for p in gs]}; carhp {ms.get('carhp')}")
    if not gs: return "stuck: no guards"
    M.shot("br_bank")
    # the getaway runs EAST to the avenue at columns 216-220, south on it and west along row 215 to
    # the respray tunnel at 204.5,218.6: km4 (and br10 before it) were pulled out in the jams on the
    # column-178 avenue, the route west then south
    s = BR.turn_car_toward(206.0, 180.0); hold("space", 0.4)
    s = D.wait_state(); car = (s["x"], s["y"]); remember_car()
    M.mark(f"getaway car set at {s['x']:.1f},{s['y']:.1f} heading {M.heading(s)[0]:.2f},{M.heading(s)[1]:.2f}")
    t3 = time.time()
    while time.time() - t3 < 70:
        BR.check(); s = D.wait_state()
        nc, no, dmin = BR.police_near(s)
        if nc == 0 and no == 0: break
        say(f"police near the bank ({nc} cars, {no} officers, nearest {dmin:.1f}): waiting in the car")
        time.sleep(2.0)

    # 3. the guards: the skill
    M.mark("kill_marked skill: the two bank guards")
    s = M.leave_car(); M.select_gun(); BR.FP["until"] = -1
    M.ensure_view("classic")      # the chase view with GTA2_DIRECT_KEYS=1
    r = K.kill_marked(world, select=is_guard, spare=is_spare, approach=BR.CLIMB, level=BR.WALK_LEVEL,
                      fire_spots=BR.FIRE_SPOTS, secs=150, check=job_check, engage=7.0, close=2.2,
                      stall=8.0, confirm=3.0, shot_prefix="km_bank")
    ms = BR.check()
    M.mark(f"kill_marked skill: {r} (wanted {ms.get('wanted')}, ammo {ms.get('ammo')})"); M.shot("br_guards")
    if r != "done" or BR.guards(): return f"stuck: guards ({r})"

    # 4-6. getaway, respray, safehouse: as the job's runner (its run() from step 4 on)
    s = D.wait_state()
    if K.level_of_z(s["z"]) == BR.WALK_LEVEL:
        if not BR.path_walk(BR.DESCEND, secs_each=5.0):
            s = D.wait_state(); say(f"descent missed at {s['x']:.1f},{s['y']:.1f}")
    s = D.wait_state()
    if not s["driving"] and math.hypot(car[0] - s["x"], car[1] - s["y"]) < 3.0: s = BR.quick_board(car)
    for k in range(3):
        if s and s["driving"]: break
        BR.check(); s = to_car(world)
    if not (s and s["driving"]): return "stuck: could not get back in the car"
    hold("Up", 0.8)
    ms = BR.check()
    M.mark(f"in the getaway car (wanted {ms.get('wanted')}, carhp {ms.get('carhp')})")

    def heads_up():
        return BR.arrow_near(86.5, 160.5) or (M.mission_state() or {}).get("msg") in ("1655", "1666", "1668")
    def safe_up():
        return BR.arrow_near(*BR.SAFE, r=4.0) or (M.mission_state() or {}).get("msg") in ("1661", "1662", "1010")
    sprayed = False
    for k in range(6):
        BR.check()
        if safe_up(): sprayed = True; break
        shop, tunnel = BR.SHOPS[0] if k < 3 else BR.SHOPS[1]
        s = D.wait_state()
        if not s["driving"]: s = to_car(world)
        if not s["driving"]: continue
        BR.FP["until"] = -1
        M.mark(f"to the respray at {shop} (try {k + 1})")
        pre = bay_pre(shop)
        if shop == BR.SHOPS[0][0]:
            for wx, wy in GETAWAY_LEGS:
                s = D.wait_state()
                if not s["driving"] or (wy < 200 and s["x"] > 213) or (wy > 200 and s["y"] > 210): continue
                M.mark(f"getaway leg to {wx},{wy}")
                s = BR.drive(world, wx, wy, 2.5, 120)
                BR.check(); remember_car()
            if not s["driving"]: continue
        s = BR.drive(world, pre[0], pre[1], 1.2, 360)
        BR.check(); remember_car()
        if not s["driving"]: continue
        t6 = time.time()
        while time.time() - t6 < 12 and not heads_up() and not safe_up():
            BR.check(); time.sleep(0.5)
        if safe_up(): sprayed = True; break
        ms = BR.check()
        M.mark(f"into the respray shop {shop} (wanted {ms.get('wanted')}, money {ms.get('money')}, carhp {ms.get('carhp')}): rolling in")
        s = stop_car(); BR.turn_car_toward(shop[0], shop[1], secs=12)
        s = D.wait_state()
        M.mark(f"lined up at {s['x']:.1f},{s['y']:.1f} heading {M.heading(s)[0]:.2f},{M.heading(s)[1]:.2f}: down the bay")
        s = lane_in(shop, secs=25, until=safe_up)
        M.shot("br_respray_in")
        t6 = time.time()
        while time.time() - t6 < 25 and not safe_up():
            BR.check(); time.sleep(0.5)
        if safe_up(): sprayed = True; break
        hold("Down", 1.5); time.sleep(0.5)
    ms = BR.check()
    M.mark(f"after the respray ({sprayed}): wanted {ms.get('wanted')}, money {ms.get('money')}, carhp {ms.get('carhp')}, msg {ms.get('msg')}")
    M.shot("br_resprayed")
    for k in range(4):
        BR.check()
        s = D.wait_state()
        if not s["driving"]: s = to_car(world)
        if not s["driving"]: continue
        M.mark(f"to the safehouse {BR.SAFE}")
        s = BR.drive(world, BR.SAFE_ROAD[0], BR.SAFE_ROAD[1], 1.0, 360)
        BR.check(); remember_car()
        if not s["driving"]: continue
        s = BR.creep_in(BR.SAFE[0], BR.SAFE[1], 3.0, 1.0, secs=50, until=lambda: M.objective() is None)
        M.shot("br_garage")
        o, ms = BR.wait_outcome(45)
        if o != "running": return o
        if M.objective() is None: o, ms = BR.wait_outcome(30); return o
    return "stuck: safehouse"


def main():
    D.start()
    s = D.wait_state(40)
    if not s: sys.exit(1)
    D.calibrate_turn()
    world = M.World("wil")
    M.mark("level")
    M.arrows_baseline()
    M.START[0] = (s["x"], s["y"])
    M.VIEW_HOOK[0] = BR.set_view
    BR.set_view("third")
    entry = next(m for m in world.db["missions"] if m.get("mission") == "wil_ye2")
    M.mark("mission wil_ye2: BANK ROBBERY! (guards by the kill_marked skill)")
    t_m = time.time()
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    r, seen = BR.answer(world, entry)
    if r == "no answer": r, seen = BR.answer(world, entry)
    say("phone:", r, seen); M.shot("br_phone")
    if r != "answered":
        M.mark(f"mission wil_ye2: phone {r} {seen}"); return
    M.arm_lives()
    BR.MONEY0[0] = (M.mission_state() or {}).get("money", 0)
    ax, ay = M.step_off_phone(world, entry)
    M.set_avoid_phones(world, keep=None)
    M.cruise_to(ax, ay, tol=0.5, secs=12)
    s = D.wait_state()
    if s and s["z"] > 3.5 and os.environ.get("WARP_OK", "1") == "1":
        cell = M.street_cell_near(world, entry["x"], entry["y"])
        if cell:
            say(f"on the phone dais (z {s['z']:.1f}); developer warp to the street at {cell[0]},{cell[1]} (reported)")
            BR.set_view("classic"); M.scene_warp(cell[0], cell[1], cell[2], "down from the phone dais"); BR.set_view("third")
    try:
        r = run(world, entry)
    except (BR.Over, K.JobOver) as e:
        r = str(e)
    if r == "running":
        o, ms = BR.wait_outcome(30); r = o
    ms = M.mission_state() or {}
    M.mark(f"mission wil_ye2: {r} ({time.time() - t_m:.0f}s) money {ms.get('money')} msg {ms.get('msg')}")
    M.shot("br_end")
    BR.set_view("third"); time.sleep(1.0); M.shot("br_end_third")
    say("RESULTS", {"wil_ye2": r})
    M.mark(f"done wil_ye2={r}")


if __name__ == "__main__":
    main()
