#!/usr/bin/env python3
"""The definitive demonstration, one continuous take: a short classic-view
opening (spawn plaza to the Downtown carriageway), V to third person (walk,
look at the people and the traffic), V to first person (the street, a look
left and right), a car that stops beside him at the kerb entered the natural
way (the developer scene warp only as a last resort, and reported), a loop
drive through the chase view, the driver's seat and the classic view that
brings him back near the start, out of the car, a few steps in third person,
then the tutorial phone at the spawn plaza answered so the mission text shows.
Events go to /out/marks.txt."""
import math, os, subprocess, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
T0 = time.time()
PAV_Y = 148.55                   # the middle of the north pavement (railing on its north edge at y=148, kerb at y=149)
EAST, WEST = 166.5, 157.5
WAIT_X, WAIT_Y = 165.5, 148.6   # at the kerb, short of the lights, where cars stop
PHONE = {"x": 158.5, "y": 138.5}  # the tutorial phone at the spawn plaza

def mark(what):
    with open("/out/marks.txt", "a") as f: f.write(f"{time.time():.3f} {what}\n")
    say("MARK", what)

def words(s):
    return (f"state={s['state']} veh={s['veh']} at {s['x']:.2f},{s['y']:.2f} face={s['fx']:.2f},{s['fy']:.2f} "
            f"{'DRIVING' if s['driving'] else 'on foot'} car d={s['cd']:.2f} model={s.get('cmodel', -1)}")

def face(tx, ty, tol=0.25):
    """turn until facing (tx,ty); a standing ped's logged facing comes from the
    sprite and can be a half turn off, so a short step first makes it real"""
    for i in range(6):
        if i == 0 or i == 3: hold("Up", 0.2); time.sleep(0.6)
        s = D.wait_state()
        a = D.angle_to(s, tx, ty)
        if abs(a) < tol: return s
        key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
        hold(key, min(abs(a) / D.rate, 0.7)); time.sleep(0.3)
    return D.wait_state()

def walking_v(what):
    D.xdo("keydown", "Up"); time.sleep(0.4)
    tap("v"); mark(what); time.sleep(1.8)
    D.xdo("keyup", "Up")

def look(key, secs, pause):
    hold(key, secs); time.sleep(pause)

# ---------------------------------------------------------------- opening, classic
# Under RTX Remix the key script brings the game to the level itself (shader
# prewarm, the attract demo's Residential first) and sets SKIP_START.
if not os.environ.get("SKIP_START"): D.start()
s = D.wait_state(40)
if not s: sys.exit(1)
mark("level")
D.calibrate_turn()
world = M.World("wil")
t_open = time.time()
def step_to(tx, ty, tol=0.45, secs=14):
    """walk to a point; turning does not count as being stuck; a few seconds
    without progress means a bump into something: back off, sidestep, retry"""
    t0 = time.time(); best = 1e9; last_gain = time.time(); n = 0
    while time.time() - t0 < secs:
        s = D.wait_state()
        d = math.hypot(tx - s["x"], ty - s["y"])
        if d < tol: return s, True
        if d < best - 0.15: best = d; last_gain = time.time()
        if time.time() - last_gain > 3.5:
            n += 1; say(f"step: stuck {d:.1f} from {tx:.1f},{ty:.1f}; unsticking {n}")
            hold("Down", 0.5); hold("Right" if n % 2 else "Left", 0.35); hold("Up", 0.6); last_gain = time.time()
            continue
        a = D.angle_to(s, tx, ty)
        if abs(a) > 0.3:
            key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
            hold(key, min(abs(a) / D.rate, 0.3)); time.sleep(0.3)
        else:
            hold("Up", min(2.0, max(0.25, (d - 0.3) / 1.9)))
    return D.wait_state(), False
on_street = False
for wp in [(158.6, 139.5), (157.3, 139.6), (156.6, 140.6), (156.5, 144.0), (156.5, 147.2), (157.5, PAV_Y)]:
    s, ok = step_to(*wp)
    if not ok: say(f"opening: waypoint {wp} missed, at {s['x']:.1f},{s['y']:.1f}")
    if time.time() - t_open > 70: break
on_street = s and s["z"] < 2.5 and abs(s["y"] - PAV_Y) < 1.2
if not on_street and time.time() - t_open < 80:
    s = M.walk_to(world, WEST + 0.5, PAV_Y, tol=0.6, budget=30)
    on_street = s and s["z"] < 2.5 and abs(s["y"] - PAV_Y) < 1.2
say(f"opening walk: {time.time()-t_open:.0f}s, on street: {on_street}, at {s['x']:.1f},{s['y']:.1f},{s['z']:.1f}")
warped_to_street = False
if not on_street:
    mark("warp_to_street")
    tap("F10", 0.3); time.sleep(1.5); s = D.wait_state(); warped_to_street = True
    say("WARP to the street:", words(s))
mark("on_pavement")
s = D.goto(WEST + 3.5, PAV_Y, tol=0.35, limit=10)
hold("Up", 1.2); time.sleep(0.8)

# ---------------------------------------------------------------- third person
face(EAST, PAV_Y)
walking_v("to_third")
face(EAST, PAV_Y); hold("Up", 0.5)
s = D.goto(WEST + 6.0, PAV_Y, tol=0.35, limit=8)
look("Right", 0.7, 1.4); look("Left", 1.4, 1.2); look("Right", 0.7, 0.6)   # the road and the traffic, then the pavement behind
face(EAST, PAV_Y)
s = D.goto(WEST + 9.0, PAV_Y, tol=0.35, limit=8)
face(WEST, PAV_Y)
s = D.goto(WEST + 5.0, PAV_Y, tol=0.35, limit=8)       # back a little, so the people behind are seen
face(EAST, PAV_Y)
s = D.goto(WEST + 8.0, PAV_Y, tol=0.35, limit=8)
hold("Up", 0.8); time.sleep(0.6)

# ---------------------------------------------------------------- first person
face(EAST, PAV_Y)
walking_v("to_first")
face(EAST, PAV_Y); hold("Up", 0.5)
s = D.goto(EAST - 1.0, PAV_Y, tol=0.35, limit=8)
face(s["x"] + 1.5, 151.5); time.sleep(1.6)          # right: over the kerb at the traffic
face(s["x"] - 3.0, PAV_Y); time.sleep(1.0)          # left/back: along the pavement
s = D.goto(WEST + 3.0, PAV_Y, tol=0.35, limit=8)
face(s["x"] + 1.0, 151.5); time.sleep(1.4)          # the traffic again from the other end
face(EAST, PAV_Y)
s = D.goto(EAST - 2.0, PAV_Y, tol=0.35, limit=8)
mark("fp_done")

# ---------------------------------------------------------------- into a car
LOW_CARS = {0, 5, 10, 14, 18, 35, 42, 49, 50, 70, 1, 13, 57, 2, 19, 31, 37, 39, 44, 45, 46, 47, 48, 53, 82, 83,
            62, 71, 51, 56, 12, 52, 84, 8, 16, 40}
PICKY_UNTIL = [0.0]

def stopped_car(samples=3, gap=0.5, within=2.6):
    pts = []
    for _ in range(samples):
        s = D.wait_state()
        if not s["car"] or s["cd"] > within: return None
        if time.time() < PICKY_UNTIL[0] and s.get("cmodel", -1) in (7, 11, 21, 58, 63, 64, 86):
            say(f"letting a model {s['cmodel']} go (not a low car)"); return None
        pts.append((s["cx"], s["cy"])); time.sleep(gap)
    if max(math.hypot(p[0] - pts[0][0], p[1] - pts[0][1]) for p in pts) > 0.3: return None
    return D.wait_state()

def watch_entry(seconds, label):
    t0 = time.time(); last = ""; idle_since = None
    while time.time() - t0 < seconds:
        s = D.wait_state(); w = words(s)
        if w != last: say(f"{label} +{time.time()-t0:4.1f}s {w}"); last = w
        if s["driving"]: return s
        if s["state"] in (2, 3, 6): idle_since = None
        elif time.time() - t0 > 3.0:
            idle_since = idle_since or time.time()
            if time.time() - idle_since > 2.5: return None
        time.sleep(0.4)
    return None

WARP_ASSISTED = [False]
def back_to_kerb():
    """dead or arrested, he reappears far away (hospital/station): the walk back
    is long and unreliable, so the developer scene warp brings him (and a car)
    back to the street; reported in the marks and the log"""
    s = D.wait_state()
    if not (s["z"] < 2.5 and abs(s["y"] - WAIT_Y) < 3.0 and abs(s["x"] - WAIT_X) < 12):
        mark("respawned_warp_back"); WARP_ASSISTED[0] = True
        hold("Up", 0.3); time.sleep(0.3)
        tap("F10", 0.3); time.sleep(1.5)
        s = D.wait_state(); say("WARP back to the street:", words(s))
    s = D.goto(WAIT_X, WAIT_Y, tol=0.25, limit=6); face(EAST, WAIT_Y + 0.1)
    return s

def wake():
    hold("Up", 0.3); time.sleep(0.3)
    for _ in range(6):
        s = D.wait_state()
        if s["state"] != 7: return s
        hold("Left", 0.2); hold("Up", 0.3); time.sleep(0.5)
    return D.wait_state()

got = None; natural = False
mark("wait_for_car")
back_to_kerb()
t0 = time.time(); tries = 0
PICKY_UNTIL[0] = t0 + 100
while time.time() - t0 < 170 and not got:
    s = D.wait_state()
    if not (s["z"] < 2.5 and abs(s["y"] - WAIT_Y) < 3.0 and abs(s["x"] - WAIT_X) < 12): back_to_kerb(); continue
    c = stopped_car()
    if c:
        tries += 1; mark(f"car_stopped_{tries}")
        say(f"natural {tries}: car at {c['cx']:.2f},{c['cy']:.2f} d={c['cd']:.2f} model {c.get('cmodel')}")
        wake(); tap("Return", 0.3)
        got = watch_entry(14, f"natural {tries}")
        natural = bool(got)
        if not got: back_to_kerb()
    else:
        time.sleep(0.3)
if not got:
    mark("warp_fallback")
    for attempt in range(1, 5):
        back_to_kerb(); wake()
        tap("F10", 0.3); time.sleep(1.5)
        s = D.wait_state(); say(f"after F10 ({attempt}): {words(s)}")
        hold("Up", 0.3); time.sleep(0.4)             # placed standing still, he ignores Enter until he has moved
        tap("Return", 0.3)
        got = watch_entry(14, f"warp {attempt}")
        if got: break
mark("driving" if got else "no_car")
say("ENTRY:", ("natural" if natural else ("warp" if got else "none")) + (" (warp-assisted return after a death)" if WARP_ASSISTED[0] else ""))

# ---------------------------------------------------------------- the drive
# west along the carriageway in the chase view, a U-turn and back east from
# the driver's seat, the last stretch in the classic view, then a stop near
# where he started.
def heading_now(s):
    return (s["chx"], s["chy"]) if s["driving"] else (s["fx"], s["fy"])

def drive_along(dir_x, lane_y, seconds, stop_x=None, brake_at_end=False, min_seconds=0):
    """hold the throttle, nudge the wheel to stay in the lane heading dir_x"""
    t0 = time.time()
    xdo("keydown", "Up")
    try:
        while time.time() - t0 < seconds:
            s = D.wait_state()
            if not s or not s["driving"]: break
            if stop_x is not None and time.time() - t0 > min_seconds and (s["x"] - stop_x) * dir_x > 0: break
            hx, hy = heading_now(s)
            dy = lane_y - s["y"]
            want = (dir_x, max(-0.35, min(0.35, dy * 0.25)))
            n = math.hypot(*want); want = (want[0] / n, want[1] / n)
            a = math.atan2(hx * want[1] - hy * want[0], hx * want[0] + hy * want[1])
            if abs(a) > 0.06:
                key = "Right" if a > 0 else "Left"
                hold(key, min(abs(a) * 0.35, 0.25))
            time.sleep(0.25)
    finally:
        xdo("keyup", "Up")
    if brake_at_end: hold("Down", 1.6)
    return D.wait_state()

def u_turn(to_dir_x):
    hold("Down", 0.5)                                   # slow first, so the turn is tight and stays on the road
    xdo("keydown", "Up"); xdo("keydown", "Left"); t0 = time.time()
    try:
        while time.time() - t0 < 4.0:
            s = D.wait_state()
            if s["driving"] and s["chx"] * to_dir_x > 0.85: break
            time.sleep(0.15)
    finally:
        xdo("keyup", "Left"); xdo("keyup", "Up")

if got:
    time.sleep(2.0)
    # he got in while in first person: V, V takes him through classic to the chase view
    tap("v"); time.sleep(0.6); tap("v"); mark("drive_third"); time.sleep(1.5)
    s = D.wait_state(); west = s["chx"] < 0
    d1 = -1 if west else 1
    out_lane, back_lane = (150.5, 153.5) if west else (154.5, 151.0)
    s = drive_along(d1, out_lane, 24)
    mark("u_turn"); u_turn(-d1)                          # the turn, seen from the chase camera
    s = drive_along(-d1, back_lane, 6)
    tap("v"); mark("drive_first"); time.sleep(1.5)
    s = drive_along(-d1, back_lane, 32, stop_x=(150 if west else 170), min_seconds=18)
    tap("v"); mark("drive_classic"); time.sleep(1.5)
    s = drive_along(-d1, back_lane, 16, stop_x=(158 if west else 162), min_seconds=8, brake_at_end=True)
    time.sleep(0.8)
    tap("Return", 0.3); mark("leave_car"); time.sleep(2.5)
    s = D.wait_state(); say("after leaving:", words(s))
    tap("v"); mark("foot_third"); time.sleep(1.5)
    hold("Up", 1.5); hold("Left", 0.5); hold("Up", 1.5); time.sleep(1.0)

# ---------------------------------------------------------------- the phone
if not got:
    # still in first person: from inside the phone box the eye would see only
    # the box, so the phone is answered in the chase view (V, V: classic, third)
    tap("v"); time.sleep(0.6); tap("v"); mark("foot_third"); time.sleep(1.5)
mark("to_phone")
s = M.walk_to(world, 158.5, 139.3, tol=0.7, budget=60)
if not s or math.hypot(158.5 - s["x"], 139.3 - s["y"]) > 2.0:
    s2 = M.walk_to(world, 158.5, 139.3, tol=0.7, budget=40)
    if not s2 or math.hypot(158.5 - s2["x"], 139.3 - s2["y"]) > 2.0:
        mark("warp_to_street_for_phone")                 # pinned somewhere: the developer warp, reported
        hold("Up", 0.3); tap("F10", 0.3); time.sleep(1.5)
        s = M.walk_to(world, 158.5, 139.3, tol=0.7, budget=60)
    else:
        s = s2
say("at the phone?", words(s))
ok, ms = M.answer_phone(world, PHONE, budget=40)
mark("phone_answered" if ok else "phone_not_answered")
say("phone:", ok, ms)
time.sleep(10)
mark("end")
say("done")
