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
    """V until the renderer reports `target`; the mark carries the view it really reached"""
    for _ in range(4):
        if current_view() == target: break
        tap("v", 0.25); time.sleep(0.7)
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


def civilians(s, within):
    out = []
    for p in M.peds():
        if p["car"] is not None or p["type"] != "civ" or not M.ped_alive(p): continue
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


def punch_sequence(budget=75):
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
                    if (h and q["type"] == "civ" and math.hypot(q["x"] - s["x"], q["y"] - s["y"]) < 1.8
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
                c = civilians(s, 9.0)
                if not c:
                    if not in_box(s["x"], s["y"], 0.3):
                        step_to(min(BOX[1] - 1, max(BOX[0] + 1, s["x"])), PAV_Y, tol=0.4, secs=6)
                    elif time.time() - idle > 5:
                        hold(turn_key(1), 0.5); idle = time.time()
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
    mark(f"PUNCH RESULT {'CONNECTED' if first_hit else 'NO HIT'}: hits seen in the ped pool {hits}, renderer 'fig: hit' lines {fh}")
    return bool(first_hit)


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


# ================================================================== FIX-ACTIONS-3 probe: punch + jack + drive off
mark("probe start")
if not os.environ.get("SKIP_START"): D.start()
s = D.wait_state(40)
if not s: mark("NO PLAYER STATE"); sys.exit(1)
mark(f"LEVEL in play: {words(s)}")
D.calibrate_turn()
T.warp(WEST + 6.0, PAV_Y, 2, why="fa3 probe: the pavement"); time.sleep(2.0)
face(170, PAV_Y)
view_to("third", "third person for the fist fight")
time.sleep(10.0)   # memory probe-view-switch-after-warp: classic held ~7 s after a warp
view_to("third", "third person (again)")
mark("PUNCH sequence")
punched = punch_sequence(budget=int(os.environ.get("FA3_PUNCH_SECS", "70")))
time.sleep(1.0)
if os.environ.get("FA3_JACK", "1") == "1":
    mark("JACK beat")
    Q.set_view("third", settle=0.3)
    got = jack(budget=int(os.environ.get("FA3_JACK_SECS", "120")))
    mark(f"JACK RESULT: {words(got) if got else 'NO CAR'}")
    if got:
        time.sleep(float(os.environ.get("FA3_DRIVE_WAIT", "2.5")))
        mark("DRIVE OFF 2 s")
        hold("Up", float(os.environ.get("FA3_DRIVE_SECS", "2.0"))); time.sleep(3.0)
        mark(f"after the drive: {words(D.wait_state())}")
mark("end")
say("done")
