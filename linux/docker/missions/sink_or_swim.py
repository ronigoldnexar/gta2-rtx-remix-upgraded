#!/usr/bin/env python3
"""SINK OR SWIM! (Residential file ste, the SRS Scientists' green phone 234.5,202.5, ste_se1.mis):
the proof job of the steal-a-given-model skill (gamerun/skills/steal_car.py, SKILL-STEALCAR).

What the script wants (assets-src/missions/ste_m/ste_se1.mis, texts from e.gxt):
  2957 title; SET_RECYCLE_MODEL_WANTED (STYPECAB): the game spawns more of that taxi in traffic;
  2272 "Steal a Taxi and keep it in one piece"; IS_CHARACTER_IN_MODEL(p1, STYPECAB) -> 2276, the
  car is stored (wrecking it fails: 2275, 2998; leaving it: 2277 and the arrow on it);
  four Z-Operatives in turn (CREATE_CHAR, WAIT_ON_FOOT, the arrow on each):
    193.5,110.5 (LOCATE_CHARACTER_BY_CAR 8 x 3), 43.5,114.5 z3 (8 x 4), 104.5,140.5 (8 x 3),
    34.5,215.5 (8 x 3); in the box in the taxi 2278 "Sound the horn", the horn sends him into
    the car as a passenger (2279/2281/2283/2285), the next one is created (2280/2282/2284);
  2286 "to the South-East Dock Crane" (arrow 197.5,245.5); crane on screen 2287 "get out";
  the taxi in IS_CAR_IN_BLOCK(197.5,247.5, 3 x 3) with him out of it: the crane dumps it,
  HAS_CAR_JUST_SUNK -> 2288, 2999 Mission Complete, $30,000.

Run inside the container (keys script missions/keys_sink_or_swim.sh, SWAP_LEVEL=ste):
    python3 /work/missions/sink_or_swim.py
Marks /out/marks.txt, milestone frames /out/m_sos_*.png, summary /out/sos_result.json.
"""
import json, math, os, re, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["DISTRICT"] = "ste"
os.environ["MISSIONS"] = " "
import drive_lib as D
import mission_lib as M
import mission_play_districts as P
import skills.steal_car as SC

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world

PHONE = (234.5, 202.5)
PICKUPS = [(193.5, 110.5, 8.0, 3.0), (43.5, 114.5, 8.0, 4.0), (104.5, 140.5, 8.0, 3.0), (34.5, 215.5, 8.0, 3.0)]
BOARDED = ["2279", "2281", "2283", "2285"]
NEXT = ["2280", "2282", "2284", "2286"]
CRANE_ARROW = (197.5, 245.5)
CRANE_BOX = (197.5, 247.5, 3.0, 3.0)
FAIL = {"2998", "2275", "2274"}
DONE = {"2999", "2288"}
RESULT = dict(stage="start", taxi_s=None, pickups=0, events=[], steal=None)

# ---------------------------------------------------------------- the game's words

_OFF = [0]
SEEN = []
def poll_msgs():
    """every msg key the mission line showed since the last call (the brief changes fast:
    2279 then 2280 inside a second)"""
    try:
        with open(D.LOG, "rb") as f:
            f.seek(_OFF[0]); data = f.read(); _OFF[0] += len(data)
    except OSError:
        return SEEN
    for k in re.findall(r"view: mission [^\n]*?msg=(\S+)", data.decode("latin-1")):
        if not SEEN or SEEN[-1] != k: SEEN.append(k)
    return SEEN

def seen(keys):
    poll_msgs(); return any(k in keys for k in SEEN)

class Over(Exception):
    pass

def over():
    """the job's end, from the game: failed / complete / dead"""
    poll_msgs()
    if any(k in DONE for k in SEEN): return "complete"
    if any(k in FAIL for k in SEEN): return "failed"
    ms = M.mission_state() or {}
    if ms.get("health", 1) == 0 or ms.get("death", 0) != 0: return "dead"
    if LIVES0[0] is not None and ms.get("lives", LIVES0[0]) < LIVES0[0]: return "dead"   # sos2: the 0.5 s samples missed health 0
    return None

LIVES0 = [None]

def check():
    o = over()
    if o: raise Over(o)

def carhp():
    return (M.mission_state() or {}).get("carhp", -1)

def ev(what):
    RESULT["events"].append(f"{time.strftime('%H:%M:%S')} {what}"); M.mark(what)

# ---------------------------------------------------------------- driving

DRIVER = os.environ.get("SOS_DRIVER", "smooth")
_calm = None
if DRIVER == "calm":
    try:
        import missions.russian_sailors as RS        # its calm_drive (no blind reversing)
        RS.world = world; _calm = RS.calm_drive
    except Exception as e:
        say(f"calm_drive not available ({e}); the shared driver"); _calm = None

STUCK_SECS = 40.0
def _drive1(w, x, y, tol, budget, until, slow, precious):
    if _calm: return _calm(w, x, y, tol=tol, budget=budget, slow=slow, precious=precious, until=until)
    return M.drive3(w, x, y, tol=tol, budget=budget, slow=slow, precious=precious, until=until)

def unstick():
    """sos4: the taxi stood nose to a wall on a pavement with a standing car 2-3 blocks behind;
    calm_drive refused every reverse (tail not clear) for minutes. Short steered reverses
    (0.35 s, slow: a bump at that speed costs little), toward the side with more room"""
    STATS_U[0] += 1
    s0 = D.wait_state()
    for k in range(4):
        side = "Left" if k % 2 == 0 else "Right"
        xdo("keydown", "Down"); xdo("keydown", side); time.sleep(0.35); xdo("keyup", "Down"); xdo("keyup", side)
        time.sleep(0.4)
        s = D.wait_state()
        if s and math.hypot(s["x"] - s0["x"], s["y"] - s0["y"]) > 1.0: break
    s = D.wait_state()
    ev(f"unstuck: {math.hypot(s['x'] - s0['x'], s['y'] - s0['y']):.1f} blocks back (carhp {carhp()})")
    return s
STATS_U = [0]

def drive(w, x, y, tol=2.0, budget=240, until=None, slow=True, precious=True):
    """the leg's driver with a watchdog: no progress for STUCK_SECS -> unstick, drive on"""
    t0 = time.time(); s = D.wait_state()
    while time.time() - t0 < budget:
        hist = [(time.time(), s["x"], s["y"])] if s else []
        flag = [False]
        def watch():
            if until and until(): return True
            s2 = D.wait_state(); now = time.time()
            if not s2: return False
            hist.append((now, s2["x"], s2["y"]))
            while len(hist) > 2 and now - hist[1][0] > STUCK_SECS: hist.pop(0)
            if now - hist[0][0] > STUCK_SECS and math.hypot(s2["x"] - hist[0][1], s2["y"] - hist[0][2]) < 1.0:
                flag[0] = True; return True
            return False
        s = _drive1(w, x, y, tol, max(10, budget - (time.time() - t0)), watch, slow, precious)
        if not flag[0]: return s
        if not (s and s["driving"]): return s
        say(f"drive: no progress for {STUCK_SECS:.0f}s at {s['x']:.1f},{s['y']:.1f}; unsticking")
        s = unstick()
    return s

def drive_skill(w, x, y, tol=2.0, budget=60, until=None):
    """the carrier's driver for the skill: not precious (the carrier is anybody's car)"""
    return M.drive3(w, x, y, tol=tol, budget=budget, until=until)

def back_in_taxi():
    """out of the taxi (pulled out, a bail-out): the arrow is on it; back in"""
    for _ in range(4):
        check()
        s = D.wait_state()
        if s["driving"] and s.get("cmodel") == SC.MODELS["STYPECAB"]: return s
        if s["driving"]: M.leave_car(); continue
        ms = M.mission_state() or {}
        tc = ms.get("tcar")
        o = M.objective()
        tx, ty = (tc if tc and tc[0] > 0 else ((o[0], o[1]) if o else (s["x"], s["y"])))
        ev(f"back to the taxi at {tx:.1f},{ty:.1f}")
        c = next((c for c in M.cars() if c["model"] == SC.MODELS["STYPECAB"] and math.hypot(c["x"] - tx, c["y"] - ty) < 2.5), None)
        if c: s = SC.jack(c, {SC.MODELS["STYPECAB"]}, budget=40)
        else: s = P.enter_parked(tx, ty, budget=90, why="the taxi")
    return D.wait_state()

def pickup(i):
    x, y, w, h = PICKUPS[i]
    s = D.wait_state()
    o = M.objective()
    if o and math.hypot(o[0] - x, o[1] - y) < 6: x, y = o[0], o[1]      # the arrow is on the man himself
    sp = P.dealer_stop(x, y, s) or (x, y)
    ev(f"operative {i+1}: by taxi to {sp[0]:.1f},{sp[1]:.1f} (he stands at {x:.1f},{y:.1f}; carhp {carhp()})")
    for leg in range(4):
        check()
        s = back_in_taxi()
        s = drive(world, sp[0], sp[1], tol=0.8, budget=420)
        s = D.wait_state()
        if s["driving"] and M.inside_box(s, PICKUPS[i][0], PICKUPS[i][1], w, h): break
        if s["driving"] and math.hypot(sp[0] - s["x"], sp[1] - s["y"]) < 2.5: break
    hold("space", 0.4)
    M.shot(f"sos_op{i+1}")
    t0 = time.time(); spot = 0; t_spot = time.time()
    while time.time() - t0 < 150:
        check()
        if seen([NEXT[i]]): break
        s = D.wait_state()
        if not s["driving"]:
            s = back_in_taxi(); s = drive(world, sp[0], sp[1], tol=0.8, budget=120); continue
        if seen([BOARDED[i]]):
            time.sleep(1.0); continue                   # he is walking to the door
        if time.time() - t_spot > 25:
            # not coming: another stop round him (the box is 8 wide)
            spot += 1; t_spot = time.time()
            ang = spot * 1.5708
            s_side = dict(s); s_side["x"], s_side["y"] = x + 2.5 * math.cos(ang), y + 2.5 * math.sin(ang)
            sp2 = P.dealer_stop(x, y, s_side)
            if sp2:
                say(f"operative {i+1}: not coming; the taxi to {sp2[0]:.1f},{sp2[1]:.1f}")
                drive(world, sp2[0], sp2[1], tol=0.8, budget=60); hold("space", 0.3)
        M.horn(1); time.sleep(1.5)
    ok = seen([NEXT[i]])
    ev(f"operative {i+1}: {'aboard' if ok else 'NOT aboard'} after {time.time() - t0:.0f}s (carhp {carhp()})")
    if ok:
        RESULT["pickups"] = i + 1; time.sleep(1.0); M.shot(f"sos_op{i+1}_aboard")
    return ok

def crane():
    x, y, w, h = CRANE_BOX
    ev(f"to the crane at {x},{y} (carhp {carhp()})")
    for leg in range(4):
        check()
        s = back_in_taxi()
        s = drive(world, CRANE_ARROW[0], CRANE_ARROW[1], tol=2.0, budget=420)
        if s and s["driving"] and math.hypot(CRANE_ARROW[0] - s["x"], CRANE_ARROW[1] - s["y"]) < 4: break
    s = D.wait_state()
    if not (s and s["driving"] and math.hypot(CRANE_ARROW[0] - s["x"], CRANE_ARROW[1] - s["y"]) < 8):
        # sos3: the taxi burned 165 blocks short and the steps below ran on foot far from the crane
        return over() or f"the taxi did not reach the crane (at {s['x']:.0f},{s['y']:.0f}, carhp {carhp()})"
    ok, s = P.creep_box(x, y, w, h, P.money(), secs=50)
    s = D.wait_state()
    say(f"crane box: creep {ok}, at {s['x']:.2f},{s['y']:.2f}, inside {M.inside_box(s, x, y, w, h)}")
    M.shot("sos_cranebox")
    M.leave_car(); ev("out of the taxi in the crane box")
    s = D.wait_state()
    ex, ey = M.escape_point(world, s["x"], s["y"], 1, dist=5)
    M.cruise_to(ex, ey, tol=1.0, secs=6)
    P.face_point(x, y)
    t0 = time.time(); n = 0
    while time.time() - t0 < 120:
        o = over()
        if o: return o
        if time.time() - t0 > 3 + 5 * n and n < 5: M.shot(f"sos_crane{n}"); n += 1
        s = D.wait_state()
        if time.time() - t0 > 30 and n >= 5:
            # nothing yet: the taxi may stand half out of the box; back in and creep again
            c = next((c for c in M.cars() if c["model"] == SC.MODELS["STYPECAB"] and math.hypot(c["x"] - x, c["y"] - y) < 6), None)
            if c and not M.inside_box(c, x, y, w, h):
                ev(f"the taxi stands at {c['x']:.1f},{c['y']:.1f}, outside the box: again")
                s = SC.jack(c, {SC.MODELS["STYPECAB"]}, budget=40)
                if s and s["driving"]:
                    P.creep_box(x, y, w, h, P.money(), secs=40); M.leave_car()
                    s = D.wait_state(); ex, ey = M.escape_point(world, s["x"], s["y"], 1, dist=5); M.cruise_to(ex, ey, tol=1.0, secs=6)
                n = 3
        time.sleep(1.0)
    return over() or "timeout at the crane"

def game_alive():
    for attempt in range(4):
        s0 = D.wait_state()
        hold("Left", 0.5); time.sleep(0.8); s1 = D.wait_state()
        if s0 and s1 and abs(s0["fx"] * s1["fy"] - s0["fy"] * s1["fx"]) + abs(s0["x"] - s1["x"]) + abs(s0["y"] - s1["y"]) > 0.02:
            return True
        say(f"start: the game does not move (attempt {attempt + 1}); Return"); tap("Return", 0.3); time.sleep(3.0)
    return False

def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == "ste_se1")
    wrong = {k for k, m in P.TITLES.items() if m.get("mission") != "ste_se1"}
    M.mark("mission ste_se1: SINK OR SWIM! (missions/sink_or_swim.py, skills/steal_car.py)")
    s = D.wait_state()
    if os.environ.get("SOS_WARP_PHONE", "0") == "1" and math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) > 40:
        # the 145-block trip from the district start to this phone is the shared driver's, not this
        # job (sos1/sos2: 14 minutes and more); with SOS_WARP_PHONE=1 the developer scene warp puts
        # him on the street 8 blocks from the phone (reported in the marks; run with
        # scene_key=F11 and GTA2DX9_SCENE_NO_CAR=1). The job itself is played from the phone on
        near = M.street_cell_near(world, PHONE[0] - 8, PHONE[1] + 3, radius=8)
        if near:
            P.set_view("classic"); M.scene_warp(near[0], near[1], near[2], "SOS_WARP_PHONE: to the street by the SRS phone; the job starts at the phone")
            P.set_view("third"); RESULT["events"].append(f"phone warp to {near}")
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    ok, key = P.answer(entry)
    say("answered:", ok, key); M.shot("sos_phone")
    poll_msgs()
    if not ok and "2957" not in SEEN and "2272" not in SEEN: return "phone not answered"
    if set(SEEN) & wrong: return f"wrong job started ({sorted(set(SEEN) & wrong)})"
    RESULT["stage"] = "phone"; ev(f"phone answered (messages {SEEN[-4:]})")
    LIVES0[0] = (M.mission_state() or {}).get("lives")
    ax, ay = M.step_off_phone(world, entry)
    M.set_avoid_phones(world, keep=None)
    M.cruise_to(ax, ay, tol=0.5, secs=10)
    # the skill: a taxi (STYPECAB), from traffic (the script asks the game for more of them)
    t0 = time.time()
    s = D.wait_state()
    # the ring round the phone, then toward operative 1 (a taxi found there costs no extra leg)
    search = SC.ring_points(world, s["x"], s["y"], r=18)
    for px, py in ((215, 175), (205, 150), (195, 125)):
        c = M.street_cell_near(world, px, py, radius=8)
        if c: search.append((c[0], c[1]))
    s = SC.steal_car(world, "STYPECAB", search=search, budget=900, drive=drive_skill, check=check)
    RESULT["steal"] = dict(SC.STATS)
    if not s: return "no taxi"
    RESULT["taxi_s"] = round(time.time() - t0); RESULT["stage"] = "taxi"
    P.set_view("third"); time.sleep(1.0); M.shot("sos_taxi")
    ev(f"in the taxi after {RESULT['taxi_s']}s (carhp {carhp()}; messages {SEEN[-3:]})")
    for i in range(4):
        if not pickup(i):
            return f"operative {i+1} not aboard"
        RESULT["stage"] = f"op{i+1}"
    return crane()

def main():
    D.start(); D.wait_state(40)
    if not game_alive(): return "frozen at start"
    poll_msgs()
    try:
        r = play()
    except Over as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    o = over()
    if o and r not in ("complete", "failed", "dead"): r = f"{o} ({r})"
    ev(f"mission ste_se1: {r}")
    time.sleep(2.5); M.shot("sos_end"); time.sleep(2.0); M.shot("sos_end2")
    RESULT["result"] = r; RESULT["messages"] = SEEN[-40:]
    with open("/out/sos_result.json", "w") as f: json.dump(RESULT, f, indent=1)
    say("RESULT", r, RESULT["steal"])
    return r

if __name__ == "__main__":
    main()
