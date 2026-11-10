#!/usr/bin/env python3
"""The owner's gameplay demo, ONE continuous take (keys_owner_demo.sh), every beat a real
game event and written to /out/marks.txt:

  classic opening (spawn plaza -> Downtown pavement) -> V third person, walking among the
  people and the traffic -> V first person, a look around -> V V third person, a PUNCH
  sequence on a civilian (confirmed by his health dropping in the game's own ped pool) ->
  INTO A CAR by jacking one that stops in the kerb lane (developer warp only as a last
  resort, and then marked DEVWARP) -> the chase view drive -> V driver's seat -> V classic
  while driving -> out of the car -> V third person, a few steps.

Why the older harnesses could not do this (DEMO-HARNESS, 9 Nov):
  * drive_enter.py waited for a 'parked nearest' car that never exists within reach of the
    wil spawn, holding Up into the church wall silently for the whole run.
  * combat_probe.py aims from 'qb16: near ped' lines, which the DLL writes only with
    GTA2DX9_LOG_NEAR_PED=1: without it no target is ever found and the fist is never pressed.
    Here the targets come from the always-on 'view: peds' line (position and health).
  * final_demo2.py waited on the PAVEMENT for a car to stop beside him; GTA2 traffic does not
    stop for a pedestrian on the pavement (it stops for the lights and for something in its
    lane), so it fell back to the warp after 178 s. Here he stands in the kerb lane, as
    pf_jack.py does, so the next car brakes in front of him, and he jacks it.

Each mark: '<epoch> <video seconds> <event>'. Video seconds count from this script's start,
which run_game_gpu.sh launches together with the recorder (within a fraction of a second).
Needs: GTA2_DIRECT_KEYS=1, GTA2DX9_STATE_EVERY=3 (keys_owner_demo.sh documents the command)."""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
import qa_lib as Q
import tour_lib as T

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
T0 = float(os.environ.get("DEMO_T0", "0") or 0) or time.time()
PAV_Y = 148.55                   # the middle of the north pavement (railing at y=148, kerb at y=149)
WEST = 157.5
KERB_X, KERB_Y = 165.5, 149.45   # standing in the kerb lane: traffic halts in front of him (pf_jack.py)
POLICE = {12, 52, 54, 17, 34}
DEVWARP = []                     # every developer warp used, for the summary


class LogWatch:
    """reads the renderer's log incrementally from byte 0: the newest view line and the
    number of 'fig: hit' lines. qa_lib.current_view() reads only the last 400 KB, and with
    STATE_EVERY=3 / PEDS_EVERY=3 the last view line falls out of that window within ~15 s,
    so it answered 'classic' and set_view pressed V from the wrong view (dh_owner1)."""
    NAMES = {"Classic (top down)": "classic", "Third person": "third", "First person": "first"}

    def __init__(self):
        self.off = 0; self.view = "classic"; self.hits = 0; self.rest = b""

    def poll(self):
        try:
            with open(D.LOG, "rb") as f:
                f.seek(self.off); data = f.read(); self.off += len(data)
        except OSError:
            return
        data = self.rest + data
        cut = data.rfind(b"\n") + 1
        self.rest = data[cut:]
        for line in data[:cut].decode("latin-1").splitlines():
            line = line.rstrip("\r")
            k = line.find("] view: ")
            if k >= 0 and line[k + 8:] in self.NAMES: self.view = self.NAMES[line[k + 8:]]
            elif "fig: hit " in line: self.hits += 1


LW = LogWatch()


def current_view():
    LW.poll(); return LW.view


Q.current_view = current_view     # set_view / tour_lib.warp use it too


def mark(what):
    now = time.time()
    with open("/out/marks.txt", "a") as f: f.write(f"{now:.3f} {now - T0:7.1f} {what}\n")
    say("MARK", f"{now - T0:7.1f}", what)


def words(s):
    return (f"state={s['state']} veh={s['veh']} at {s['x']:.2f},{s['y']:.2f} face={s['fx']:.2f},{s['fy']:.2f} "
            f"{'DRIVING' if s['driving'] else 'on foot'} view={current_view()}")


def turn_key(a): return "Left" if (a > 0) == (D.left_sign > 0) else "Right"


def face(tx, ty, tol=0.25):
    """a standing ped's logged facing comes from the sprite and can be a half turn off, so
    a short step first makes it real"""
    for i in range(6):
        if i in (0, 3): hold("Up", 0.2); time.sleep(0.5)
        s = D.wait_state()
        a = D.angle_to(s, tx, ty)
        if abs(a) < tol: return s
        hold(turn_key(a), min(abs(a) / D.rate, 0.7)); time.sleep(0.3)
    return D.wait_state()


def view_to(target, what):
    """V until the renderer reports `target` (ONE tap, then up to 3 s for the log line: a second tap
    while the first move is still running would cycle on to the next view); the mark carries the
    view it really reached"""
    for _ in range(4):
        if current_view() == target: break
        tap("v", 0.25)
        t1 = time.time()
        while time.time() - t1 < 3.0 and current_view() != target: time.sleep(0.1)
    got = current_view()
    mark(f"VIEW {got}{'' if got == target else ' (WANTED ' + target + ')'} - {what}")
    return got == target


def step_to(tx, ty, tol=0.45, secs=14):
    """walk to a point; a few seconds without progress = a bump: back off, sidestep, retry"""
    t0 = time.time(); best = 1e9; last_gain = time.time(); n = 0
    s = D.wait_state()
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
            hold(turn_key(a), min(abs(a) / D.rate, 0.3)); time.sleep(0.25)
        else:
            hold("Up", min(1.5, max(0.2, (d - 0.3) / 1.9)))
    return s, False


def on_pavement(s, slack=1.2):
    return s and s["z"] < 2.5 and abs(s["y"] - PAV_Y) < slack and 150 < s["x"] < 175


def look(key, secs, pause):
    hold(key, secs); time.sleep(pause)


# ------------------------------------------------------------------ punching
# the pavement strip the fight stays on: north pavement of the Downtown carriageway
BOX = (151.5, 172.0, 147.7, 149.25)


def in_box(x, y, m=0.0):
    return BOX[0] - m < x < BOX[1] + m and BOX[2] - m < y < BOX[3] + m


def civilians(s, within, exclude=()):
    out = []
    for p in M.peds():
        if p["car"] is not None or p["type"] != "civ" or not M.ped_alive(p) or p["id"] in exclude: continue
        if abs(p["z"] - s["z"]) > 0.6 or not in_box(p["x"], p["y"]): continue
        d = math.hypot(p["x"] - s["x"], p["y"] - s["y"])
        if d < within: out.append((d, p))
    return sorted(out, key=lambda t: t[0])


def ped_by_id(pid):
    for p in M.peds():
        if p["id"] == pid: return p
    return None


def fig_hits():
    LW.poll(); return LW.hits


def punch_sequence(budget=75, exclude=()):
    """chase the nearest civilian on the pavement strip (Up held, the wheel pulsed), the fist
    held once within reach. A hit = his health in the game's ped pool drops, or he goes down
    (state 8: knocked over; dh_owner1 showed 50 -> 30 and state 8 sub 0x16 from one punch).
    After the first hit keep swinging ~2 s, then stand and watch him lie there."""
    t_end = time.time() + budget
    target = None; hp0 = None; st0 = None; hits = 0; fig0 = fig_hits(); first_hit = None
    keys = set(); idle = time.time(); seen_hp = {}

    def down(k):
        if k not in keys: xdo("keydown", k); keys.add(k)

    def up(k):
        if k in keys: xdo("keyup", k); keys.discard(k)

    try:
        while time.time() < t_end:
            s = D.wait_state()
            if s["driving"]: tap("Return", 0.3); time.sleep(2); continue
            pool = {q["id"]: q for q in M.peds()}
            # a blow lands on whoever stands in reach, not always the chosen target (dh_owner3: two
            # bystanders at health 30 before the target went down): any civilian in reach losing
            # health or going down while the fist is held is the hit, and becomes the target
            if "Control_L" in keys and not first_hit:
                for qid, q in pool.items():
                    h = seen_hp.get(qid)
                    if (h and q["type"] == "civ" and qid not in exclude and math.hypot(q["x"] - s["x"], q["y"] - s["y"]) < 1.8
                            and (q["hp"] < h[0] or (q["state"] == 8 and h[1] != 8))):
                        if qid != target: say(f"the blow landed on {qid}, not on {target}: he is the target now")
                        target, hp0, st0 = qid, h[0], h[1]
                        break
            seen_hp.clear(); seen_hp.update({qid: (q["hp"], q["state"]) for qid, q in pool.items()})
            p = pool.get(target) if target is not None else None
            if p is not None and (p["hp"] < hp0 or (p["state"] == 8 and st0 != 8)) and (hp0 > p["hp"] or not first_hit):
                hits += 1
                if not first_hit:
                    first_hit = time.time()
                    mark(f"PUNCH HIT civ {target}: health {hp0} -> {p['hp']}, state {st0} -> {p['state']} sub {p['sub']}"
                         f"{' (KNOCKED DOWN)' if p['state'] == 8 else ''} at {p['x']:.2f},{p['y']:.2f}")
                else:
                    say(f"punch hit again: hp {hp0} -> {p['hp']} state {p['state']}")
                hp0, st0 = p["hp"], p["state"]
            if first_hit and (time.time() - first_hit > 5.0 or (p is not None and p["state"] == 8 and time.time() - first_hit > 1.0)):
                if p is not None and p["state"] == 8: mark(f"PUNCH target {target} is DOWN (state 8 sub {p['sub']}, health {p['hp']})")
                break
            if p is not None and first_hit and not in_box(p["x"], p["y"], 0.4):
                say(f"target {target} fled off the pavement after the hit: not following him into the road"); break
            if p is not None and not first_hit and (not M.ped_alive(p) or not in_box(p["x"], p["y"], 0.4)):
                say(f"target {target} left the pavement or went down without our fist (state {p['state']} hp {p['hp']})")
                p = None
            if p is None or math.hypot(p["x"] - s["x"], p["y"] - s["y"]) > 9:
                up("Up"); up("Control_L")
                if first_hit: break
                c = civilians(s, 12.0, exclude)
                if not c:
                    if not in_box(s["x"], s["y"], 0.3):
                        step_to(min(BOX[1] - 1, max(BOX[0] + 1, s["x"])), PAV_Y, tol=0.4, secs=6)
                    elif time.time() - idle > 3:
                        # nobody in reach: walk the strip to its far end and look again
                        far = BOX[1] - 1.5 if s["x"] < (BOX[0] + BOX[1]) / 2 else BOX[0] + 1.5
                        say(f"punch: nobody in reach; walking the pavement to x {far:.1f}")
                        step_to(far, PAV_Y, tol=0.5, secs=7); idle = time.time()
                    time.sleep(0.2); target = None; continue
                d, p = c[0]; target = p["id"]; hp0 = p["hp"]; st0 = p["state"]; idle = time.time()
                mark(f"PUNCH target civ {target} at {p['x']:.2f},{p['y']:.2f} d={d:.2f} hp={hp0}")
                continue
            d = math.hypot(p["x"] - s["x"], p["y"] - s["y"])
            a = D.angle_to(s, p["x"], p["y"])
            if d < 1.5: down("Control_L")
            elif d > 2.0: up("Control_L")
            if d > 0.6: down("Up")
            else: up("Up")
            if abs(a) > 0.3: hold(turn_key(a), min(abs(a) / D.rate, 0.15))
            time.sleep(0.06)
    finally:
        for k in list(keys): xdo("keyup", k)
    time.sleep(2.0)
    fh = fig_hits() - fig0
    mark(f"PUNCH RESULT {'CONNECTED' if first_hit else 'NO HIT'} on civ {target}: hits seen in the ped pool {hits}, renderer 'fig: hit' lines {fh}")
    return target if first_hit else None


# ------------------------------------------------------------------ into a car
def watch_entry(seconds, label):
    t0 = time.time(); last = ""
    while time.time() - t0 < seconds:
        s = D.wait_state(); w = words(s)
        if w != last: say(f"{label} +{time.time()-t0:4.1f}s {w}"); last = w
        if s["driving"]: return s
        time.sleep(0.3)
    return None


def to_kerb():
    s = D.wait_state()
    if math.hypot(s["x"] - KERB_X, s["y"] - KERB_Y) > 14 or s["z"] > 2.5:
        return s, False
    s, ok = step_to(KERB_X, KERB_Y, tol=0.35, secs=20)
    return s, ok


def jack(budget=110):
    """stand in the kerb lane; the first civilian car that brakes within 2 blocks: Return.
    The game runs him to the door and pulls the driver out."""
    t0 = time.time(); tries = 0
    s, ok = to_kerb()
    mark(f"JACK waiting in the kerb lane at {s['x']:.2f},{s['y']:.2f} (reached={ok})")
    while time.time() - t0 < budget:
        s = D.wait_state()
        if s["driving"]: return s
        if math.hypot(s["x"] - KERB_X, s["y"] - KERB_Y) > 1.5: s, ok = to_kerb()
        cs = [c for c in M.cars() if c["driver"] not in ("-", "P") and c["model"] not in POLICE and abs(c["z"] - s["z"]) < 0.6]
        near = [c for c in cs if math.hypot(c["x"] - s["x"], c["y"] - s["y"]) < 2.2 and abs(c["v"]) < 0.45]
        if not near: time.sleep(0.1); continue
        c = min(near, key=lambda c: abs(c["v"]) + 0.3 * math.hypot(c["x"] - s["x"], c["y"] - s["y"]))
        tries += 1
        mark(f"JACK attempt {tries}: car {c['id']} m{c['model']} v={c['v']:.2f} driver {c['driver']} at {c['x']:.2f},{c['y']:.2f}")
        tap("Return", 0.3)
        got = watch_entry(9, f"jack {tries}")
        if got: return got
    return None


def warp_car():
    """last resort: the developer scene warp puts a parked car beside him (marked DEVWARP)"""
    T.retarget(KERB_X, KERB_Y, 2)
    for attempt in range(1, 4):
        Q.set_view("third", settle=0.5)
        key = T.ini_scene_key() or "F11"
        mark(f"DEVWARP attempt {attempt}: developer scene key {key} (car placed beside him)"); DEVWARP.append("car")
        tap(key, 0.3); time.sleep(1.5)
        hold("Up", 0.3); time.sleep(0.4)
        tap("Return", 0.3)
        got = watch_entry(12, f"warp {attempt}")
        if got: return got
    return None


# ================================================================== the take
# The owner's 12 beats, one continuous take (docs/HANDOVER.md, order owner-demo-v2-full-sequence):
#  1 real spawn  2 walk in classic  3 approach the road  4 ONE smooth V to third  5 punch THREE people
#  6 get into a car  7 first person at the wheel  8 C dashcam  9 reckless driving in dashcam
# 10 V back to classic while moving  11 exit the car  12 walk around in third person
mark("probe start (video t counts from the keys script start = the recorder start, within a fraction of a second)")
if not os.environ.get("SKIP_START"): D.start()
s = D.wait_state(40)
if not s: mark("NO PLAYER STATE"); sys.exit(1)
mark(f"BEAT 1 REAL SPAWN: the level's own start, no developer warp: {words(s)}")
D.calibrate_turn()

# ---- beats 2 and 3: classic walk from the spawn plaza to the road
mark("BEAT 2 walking in the classic top-down view (BEV), from the spawn plaza")
t_open = time.time()
for wp in [(158.6, 139.5), (157.3, 139.6), (156.6, 140.6), (156.5, 144.0), (156.5, 147.2), (WEST, PAV_Y)]:
    s, ok = step_to(*wp)
    if not ok: say(f"opening: waypoint {wp} missed, at {s['x']:.1f},{s['y']:.1f}")
    if time.time() - t_open > 60: break
if not on_pavement(s):
    world = M.World("wil")
    s = M.walk_to(world, WEST + 0.5, PAV_Y, tol=0.6, budget=30) or D.wait_state()
if not on_pavement(s):
    T.warp(WEST + 1.0, PAV_Y, 2, why="the street, opening walk failed"); DEVWARP.append("street")
    mark("DEVWARP to the pavement (opening walk failed)")
s = D.wait_state()
mark(f"BEAT 3 at the road: on the pavement beside the carriageway, classic view: {words(s)}")
face(170, PAV_Y)
s, _ = step_to(WEST + 3.0, PAV_Y, tol=0.4, secs=8)     # a few more steps along the kerb in classic

# ---- beat 4: ONE smooth V move to third person (switch_dissolve_percent=0), walking
face(170, PAV_Y)
xdo("keydown", "Up"); time.sleep(0.3)
view_to("third", "BEAT 4 transition to 3D: one smooth camera move, walking")
xdo("keyup", "Up")
s, _ = step_to(WEST + 6.0, PAV_Y, tol=0.4, secs=8)
look("Right", 0.6, 1.0); look("Left", 1.0, 0.8)

# ---- beat 5: attack a few people: at least three separate pedestrians, each hit landing
mark("BEAT 5 attacking pedestrians: three separate targets, each confirmed by health/state in the game's ped pool")
hit_ids = []; fig_start = fig_hits(); t5 = time.time()
while len(hit_ids) < 3 and time.time() - t5 < 230:
    got_id = punch_sequence(budget=70, exclude=tuple(hit_ids))
    if got_id is not None:
        hit_ids.append(got_id); mark(f"PUNCH {len(hit_ids)} of 3 landed on civ {got_id}")
    else: mark("PUNCH attempt without a hit; the next civilian")
    time.sleep(0.8)
mark(f"BEAT 5 RESULT {len(hit_ids)} separate pedestrians hit (civ {hit_ids}), renderer 'fig: hit' lines {fig_hits() - fig_start}")
punched = len(hit_ids)

# ---- beat 6: into a car
mark("BEAT 6 getting into a car (jack at the kerb lane)")
Q.set_view("third", settle=0.3)
got = jack(budget=110)
how = "NATURAL jack (no developer warp)" if got else None
if not got:
    got = warp_car()
    how = "DEVELOPER WARP (scene key placed a parked car beside him)" if got else None
if not got:
    mark("CAR ENTRY FAILED"); mark("end"); sys.exit(0)
mark(f"BEAT 6 IN THE CAR: {how}: {words(got)}")
time.sleep(1.5)

# ---- driving: legs on roads read from wil.gmp round the block west of the start
world = M.World("wil")
def leg(tx, ty, budget, label, until=None):
    s0 = D.wait_state()
    s1 = M.drive3_smooth(world, tx, ty, tol=2.0, budget=budget, until=until)
    for k in ("Up", "Down", "Left", "Right"): xdo("keyup", k)
    s1 = s1 or D.wait_state()
    say(f"leg {label}: {s0['x']:.1f},{s0['y']:.1f} -> {s1['x']:.1f},{s1['y']:.1f} (goal {tx},{ty}) driving={s1['driving']}")
    return s1
M.QUEUE_SECS = 30.0      # wait at the lights like the traffic does (dh_owner4/5: a westbound queue)
s = D.wait_state()
east = s["chx"] > 0.5
L1, L2, L3 = ((173.5, 128.5), (155.5, 112.5), (142.5, 140.5)) if east else ((144.5, 128.5), (155.5, 115.5), (169.5, 140.5))

# beat 7: first person at the wheel, a calm drive with a turn (hands, wheel turning with the car)
view_to("first", "BEAT 7 first person at the wheel: hands on the rim, the wheel turns with the car")
time.sleep(1.0)
t7 = time.time()
s = leg(*L1, 45, "first person, careful", until=lambda: time.time() - t7 > 16)   # 16 s of cockpit with a turn is enough to read hands and wheel
s = D.wait_state()

# beat 8: C = the dashcam (clean forward view, no wheel, hands or body)
if s["driving"]:
    tap("c", 0.3); time.sleep(0.8)
    mark("BEAT 8 DASHCAM (key C): clean forward view, no wheel, no hands, no body")

# beat 9: reckless driving in the dashcam: a high cap, no braking for traffic, hard swerves
# onto the kerbs and across the lanes (cars and walls, not people)
M.SMOOTH_CAP = M.FAST_CAP = 7.0; M.HIT_SLOW = 7.0; M.SMOOTH_EDGE_COST = 0.1
M.traffic_ahead = lambda s_, v_: None
SW = {"n": 0, "t": 0.0, "v_sent": False}
def reckless_until():
    """called every few control loops by drive3_smooth: a hard swerve every ~2.5 s"""
    now = time.time()
    if now - SW["t"] > 1.8:
        SW["t"] = now; SW["n"] += 1
        k = "Left" if SW["n"] % 2 else "Right"
        xdo("keydown", "Up"); xdo("keydown", k)
        if SW["n"] % 3 == 0: xdo("keydown", "space")      # a handbrake slide every third swerve
        time.sleep(0.6); xdo("keyup", "space"); xdo("keyup", k)
    return False
mark("BEAT 9 RECKLESS DRIVING in the dashcam: full speed, hard swerves, traffic not given way to")
s = leg(*L2, 40, "reckless 1", until=reckless_until)

# beat 10: V = back to the classic top-down view while the car is moving
def to_classic_moving():
    if not SW["v_sent"]:
        SW["v_sent"] = True; tap("v", 0.25)
        mark("BEAT 10 V pressed: back to classic (BEV) while the car is moving")
    return reckless_until()
s = leg(*L3, 40, "classic while moving", until=to_classic_moving)
time.sleep(1.0); view_to("classic", "BEAT 10 classic top-down (checked after the leg)")
hold("Down", 1.2)
time.sleep(0.8)
mark(f"stopped: {words(D.wait_state())}")

# ---- beat 11: out of the car (classic view, the full get-out), beat 12: third person walk
mark("BEAT 11 exiting the vehicle")
for _ in range(3):
    tap("Return", 0.3); time.sleep(3.0)
    s = D.wait_state()
    if not s["driving"]: break
mark(f"BEAT 11 out of the car: {words(s)}")
time.sleep(1.5)
view_to("third", "BEAT 12 third person, walking around on foot")
hold("Up", 1.5); hold("Left", 0.4); hold("Up", 1.8); hold("Right", 0.5); hold("Up", 1.5); time.sleep(1.5)
mark(f"SUMMARY pedestrians hit={punched}; car entry={how}; real spawn, developer warps used: "
     f"{', '.join(DEVWARP) if DEVWARP else 'none'}")
mark("end")
say("done")
