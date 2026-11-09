#!/usr/bin/env python3
"""Skill: TRUCK AND TRAILER (Wave M, SKILL-BUS; catalogue skill `truck_trailer`, 4 jobs).

The four jobs (docs/missions-catalogue.md): ste_zm1 OPERATION Z! (a cab found anywhere, the
transporter with a Cop Car behind the cop station, the crane at 250.5,39.5), ste_rm2 BENSON BURNER!
(a cab, Dwight T's transporter, crane9 loads the Benson, the bomb, the Cop crane), ste_zh2
DISTRACTION ACTION! (the cab comes hitched to the FBI-car transporter inside the cop station: get
in and keep the rig whole for 60 s at three stars) and bil_ze2 GRAND THEFT AUTO! (a cab, the
transporter with a Cop Car at 40.5,65.5, crane8, the car to the Power Cores). The scripts test:

  IS_CHARACTER_IN_MODEL (p1, TRUKCAB1 | TRUKCAB2)       any cab will do (the cab is not named)
  IS_TRAILER_ATTACHED (cab, trailer)                   lose it -> "re-attach" brief or a fail
  IS_CAR_IN_BLOCK (cab, crane box)                     the crane takes the car off the trailer
  GET_CAR_INFO_FROM_CRANE / IS_CAR_ON_TRAILER           the loaded car's state
  IS_CAR_WRECKED (trailer)                              a fail in every job

What the game does with a rig (seen in the runs, docs/skill-truck-trailer.md): the trailer is a car
of its own in the renderer's `view: cars` line (TRUKTRNS 66, TRUKCONT 65, TANKER 55; cabs TRUKCAB1 63, TRUKCAB2 64), hitched when
its front sits at the cab's rear; a cab backed slowly into a trailer's front hitches it. A hard hit
or a jack-knife past ~100 degrees unhitches it.

API (all on top of the frozen mission_lib/drive_lib):
  rig(s)                      (cab, trailer) from the cars line: the player's cab and the trailer
                              hitched behind it (nearest trailer whose front is at the cab's rear)
  hitched(s)                  True when a trailer follows the cab (geometry, over the last samples)
  get_cab(world, ...)         into any cab: a hitched one the script made, a parked one, or one
                              stolen from traffic (skills.steal_car)
  hook_up(world, trailer_xy)  back the cab onto the trailer's front until it hitches
  tow(world, x, y, ...)       drive with the rig: low speed caps, wide turns, re-hook on a loss
  evade(world, secs, ...)     keep the rig moving on a loop of straight roads for `secs` game
                              seconds (DISTRACTION ACTION's 60 s at three stars), away from cops
  crane_drop(world, box, ...) into a crane box, keys off, wait for the crane's lift
Every step marks /out/marks.txt with "truck: ..." and appends to EVENTS.
"""
import math, os, re, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

try:
    from skills.steal_car import MODELS, model_ids
except Exception:                                      # the enum, if steal_car is not importable
    MODELS = {"TRUKCAB1": 63, "TRUKCAB2": 64, "TRUKCONT": 65, "TRUKTRNS": 66, "TANKER": 55, "COPCAR": 12, "SWATVAN": 52}
    def model_ids(ms): return {MODELS[m] for m in ms}

CABS = {MODELS["TRUKCAB1"], MODELS["TRUKCAB2"]}
TRAILERS = {MODELS["TRUKTRNS"], MODELS["TRUKCONT"], MODELS["TANKER"]}
HITCH_GAP = (1.2, 4.2)      # cab centre -> trailer centre along the cab's axis when hitched (blocks)
TOW_CAP = float(os.environ.get("TRUCK_TOW_CAP", "2.2"))   # speed cap with a trailer (blocks / game s)
EVENTS = []
STATS = {"hookups": 0, "lost": 0, "reverse_pulses": 0, "evade_legs": 0}


def ev(what):
    EVENTS.append((time.time(), what)); M.mark(f"truck: {what}"); say(f"truck: {what}")


class Msgs:
    """every message key the mission line showed, in order (keys under a second are not missed)"""
    RX = re.compile(r"view: mission [^\n]*?msg=(\S+)")

    def __init__(self, start_at_end=True):
        self.off = 0; self.seen = []
        if start_at_end:
            try: self.off = os.path.getsize(D.LOG)
            except OSError: self.off = 0

    def poll(self):
        try:
            with open(D.LOG, "rb") as f:
                f.seek(self.off); data = f.read(); self.off += len(data)
        except OSError:
            return self.seen
        for k in self.RX.findall(data.decode("latin-1")):
            if not self.seen or self.seen[-1] != k: self.seen.append(k)
        return self.seen

    def mark(self):
        self.poll(); return len(self.seen)

    def since(self, keys, mark=0):
        self.poll(); keys = set(keys)
        return any(k in keys for k in self.seen[mark:])

    def last(self, n=4):
        self.poll(); return self.seen[-n:]


# ------------------------------------------------------------------ the rig from the cars line

def _heading(c):
    n = math.hypot(c["hx"], c["hy"]) or 1.0
    return c["hx"] / n, c["hy"] / n


def my_cab(s=None, cars=None):
    s = s or D.wait_state()
    cars = cars if cars is not None else M.cars()
    if not (s and s["driving"]): return None
    mine = [c for c in cars if c["model"] in CABS and math.hypot(c["x"] - s["x"], c["y"] - s["y"]) < 1.5]
    if not mine:
        mine = [c for c in cars if c["driver"] == "P"]
    return min(mine, key=lambda c: math.hypot(c["x"] - s["x"], c["y"] - s["y"])) if mine else None


def behind(cab, t):
    """(along, across) of trailer t in the cab's frame: along < 0 is behind the cab"""
    hx, hy = _heading(cab)
    dx, dy = t["x"] - cab["x"], t["y"] - cab["y"]
    return dx * hx + dy * hy, -dx * hy + dy * hx


def rig(s=None):
    """(cab, trailer or None): the player's cab and the trailer whose centre sits behind it at the
    hitch distance"""
    cars = M.cars()
    cab = my_cab(s, cars)
    if not cab: return None, None
    best = None
    for t in cars:
        if t["model"] not in TRAILERS or t["id"] == cab["id"]: continue
        along, across = behind(cab, t)
        d = math.hypot(t["x"] - cab["x"], t["y"] - cab["y"])
        if HITCH_GAP[0] <= d <= HITCH_GAP[1] + 0.8 and along < 0.3:
            if best is None or d < best[0]: best = (d, t)
    return cab, (best[1] if best else None)


HIST = []        # (wall time, cab xy, trailer xy) while towing


def hitched(s=None, window=3.0):
    """a trailer is behind the cab now, and over the last `window` game seconds of motion the
    cab-trailer distance stayed within the hitch range (a loose trailer standing behind a parked
    cab passes the first test only)"""
    cab, t = rig(s)
    now = time.time()
    if not cab or not t:
        HIST.append((now, None, None)); del HIST[:-40]; return False
    HIST.append((now, (cab["x"], cab["y"]), (t["x"], t["y"]))); del HIST[:-40]
    recent = [h for h in HIST if now - h[0] < window / D.SPEED and h[1]]
    if len(recent) < 2: return True
    moved = math.hypot(recent[-1][1][0] - recent[0][1][0], recent[-1][1][1] - recent[0][1][1])
    tmoved = math.hypot(recent[-1][2][0] - recent[0][2][0], recent[-1][2][1] - recent[0][2][1])
    if moved < 0.8: return True                  # standing: geometry only
    return tmoved > 0.4 * moved


def trailers_near(x, y, r=40.0):
    return sorted([c for c in M.cars() if c["model"] in TRAILERS and math.hypot(c["x"] - x, c["y"] - y) < r],
                  key=lambda c: math.hypot(c["x"] - x, c["y"] - y))


# ------------------------------------------------------------------ getting a cab

def in_cab(s=None):
    s = s or D.wait_state()
    return bool(s and s["driving"] and s.get("cmodel", -1) in CABS)


def get_cab(world, near=None, budget=600, check=None, drive=None):
    """into any truck cab: one standing within 25 blocks (walked to and entered), else
    skills.steal_car on the cab models (parked ones first, then traffic)"""
    s = D.wait_state()
    if in_cab(s): return s
    try:
        from skills import steal_car as SC
    except Exception as e:
        say("truck: steal_car not importable", e); return None
    ev(f"looking for a truck cab (near {near})")
    r = SC.steal_car(world, sorted(CABS), search=None, budget=budget, drive=drive, check=check)
    if r and in_cab(r): ev(f"in a cab (model {r.get('cmodel')}) at {r['x']:.1f},{r['y']:.1f}")
    return r


# ------------------------------------------------------------------ hooking up

def _steer_pulse(key, t):
    xdo("keydown", key); time.sleep(t); xdo("keyup", key)


def hook_up(world, trailer=None, budget=150, check=None, attached=None):
    """back the cab onto the trailer's front. `attached()` (the script's view: a brief, or
    IS_TRAILER_ATTACHED through the arrow leaving the trailer) ends it; else the geometry test.
    1) drive to a point 4 blocks ahead of the trailer's front on its axis, facing along it;
    2) reverse in short pulses, steering the cab's rear onto the trailer's front."""
    t0 = time.time(); tries = 0
    attached = attached or (lambda: hitched())
    while time.time() - t0 < budget:
        if check: check()
        s = D.wait_state()
        if not in_cab(s): return "out of the cab"
        if attached(): STATS["hookups"] += 1; ev(f"hitched after {time.time() - t0:.0f}s"); return "hitched"
        ts = trailers_near(s["x"], s["y"], 60)
        if trailer is not None:
            tid = trailer["id"] if isinstance(trailer, dict) else None
            if tid is not None: ts = [c for c in ts if c["id"] == tid] or ts
            elif isinstance(trailer, tuple): ts = sorted(ts, key=lambda c: math.hypot(c["x"] - trailer[0], c["y"] - trailer[1]))
        if not ts: say("truck: no trailer in sight"); time.sleep(1.0); continue
        t = ts[0]
        hx, hy = _heading(t)
        front = (t["x"] + hx * 2.0, t["y"] + hy * 2.0)         # the trailer's hitch, roughly
        stage = (t["x"] + hx * 5.5, t["y"] + hy * 5.5)         # where the cab lines up
        d_stage = math.hypot(stage[0] - s["x"], stage[1] - s["y"])
        cab = my_cab(s)
        ch = _heading(cab) if cab else (s["chx"], s["chy"])
        align = ch[0] * hx + ch[1] * hy                       # 1 = the cab faces the trailer's way
        rear = (s["x"] - ch[0] * 1.6, s["y"] - ch[1] * 1.6)
        d_hitch = math.hypot(front[0] - rear[0], front[1] - rear[1])
        if tries == 0 or (d_hitch > 3.5 and (d_stage > 1.5 or align < 0.85)):
            tries += 1
            if tries > 4: return "could not line up"
            ev(f"lining up ahead of the trailer at {t['x']:.1f},{t['y']:.1f} (try {tries})")
            M.drive3(world, stage[0] + hx * 2.5, stage[1] + hy * 2.5, tol=1.2, budget=60, slow=True)
            # come back to the stage facing away from the trailer: a three-point turn is the
            # driver's; here, just roll forward to the far point then reverse onto the axis
            s = D.wait_state()
            continue
        # reverse with steering: the cab's rear should move onto the hitch
        a = math.atan2(front[1] - rear[1], front[0] - rear[0])
        back = math.atan2(-ch[1], -ch[0])
        err = (a - back + math.pi) % (2 * math.pi) - math.pi
        STATS["reverse_pulses"] += 1
        xdo("keydown", "Down")
        if abs(err) > 0.08:
            # reversing: the rear swings the opposite way to the steering key
            key = "Right" if (err > 0) == (D.left_sign > 0) else "Left"
            _steer_pulse(key, min(0.25, abs(err) * 0.4))
        time.sleep(0.25 if d_hitch > 1.2 else 0.12)
        xdo("keyup", "Down")
        hold("Up", 0.05)                                       # brake
        time.sleep(0.3)
    return "timeout"


# ------------------------------------------------------------------ towing

def tow(world, x, y, tol=2.5, budget=300, check=None, lost=None, view_switch=None, cap=None):
    """drive the rig to (x,y): the shared driver at a trailer's speed cap, with `lost()` checked
    every step (the trailer came off: returns 'lost')"""
    saved = (M.CARE_HP, M.CARE_CAP)
    M.CARE_HP, M.CARE_CAP = 40000, cap or TOW_CAP           # every carhp counts as 'care': capped
    try:
        flag = {"lost": False}

        def until():
            if check: check()
            if lost and lost(): flag["lost"] = True; return True
            return False
        s = M.drive3(world, x, y, tol=tol, budget=budget, view_switch=view_switch, slow=True, precious=True, until=until)
    finally:
        M.CARE_HP, M.CARE_CAP = saved
    if flag["lost"]: STATS["lost"] += 1; ev("the trailer came off"); return "lost", s
    if s and math.hypot(x - s["x"], y - s["y"]) <= tol + 0.5: return "arrived", s
    return "short", s


# ------------------------------------------------------------------ evading with the rig

def loop_points(world, x, y, r=18):
    """road cells on a ring round (x,y): the evade loop's waypoints, in order round the ring"""
    pts = []
    for k in range(8):
        a = k * math.pi / 4
        c = M.street_cell_near(world, x + r * math.cos(a), y + r * math.sin(a), radius=6)
        if c and (not pts or math.hypot(c[0] - pts[-1][0], c[1] - pts[-1][1]) > 6): pts.append((c[0], c[1]))
    return pts


def cops_near(s, r=6.0):
    return [c for c in M.cars() if c["model"] in (MODELS.get("COPCAR", 12), MODELS.get("SWATVAN", 52))
            and math.hypot(c["x"] - s["x"], c["y"] - s["y"]) < r and c["driver"] != "P"]


def evade(world, done, check=None, lost=None, centre=None, budget=240, points=None, view_switch=None):
    """keep the rig rolling until done() (the script's timer ran out / JOB COMPLETE): a loop of
    road waypoints round `centre`, next waypoint always the one ahead of the cab; never stop
    (a stopped cab at three stars is a jacked cab)"""
    s = D.wait_state()
    centre = centre or (s["x"], s["y"])
    pts = points or loop_points(world, centre[0], centre[1])
    if not pts: pts = [(s["x"] + 10, s["y"]), (s["x"] - 10, s["y"])]
    ev(f"evading on a loop of {len(pts)} points round {centre[0]:.0f},{centre[1]:.0f}")
    t0 = time.time()
    while time.time() - t0 < budget:
        if done(): return "done"
        if check: check()
        s = D.wait_state()
        if not s["driving"]: return "out"
        hx, hy = M.heading(s)
        # the next waypoint: ahead of the cab (positive dot), farther than 6 blocks, nearest
        ahead = [p for p in pts if (p[0] - s["x"]) * hx + (p[1] - s["y"]) * hy > 0 and math.hypot(p[0] - s["x"], p[1] - s["y"]) > 6]
        p = min(ahead or pts, key=lambda p: math.hypot(p[0] - s["x"], p[1] - s["y"]))
        STATS["evade_legs"] += 1
        r, s = tow(world, p[0], p[1], tol=3.0, budget=40, check=check, lost=lambda: (done() or bool(lost and lost())),
                   view_switch=view_switch, cap=2.6)
        if done(): return "done"
        if r == "lost" and lost and lost(): return "lost"
    return "timeout"


# ------------------------------------------------------------------ the crane

def crane_drop(world, box, done, check=None, budget=200, view_switch=None, lost=None):
    """into the crane's box (x, y, w, h), stop, all keys off, wait for done() (the crane lifted the
    car: the script's brief/arrow change)"""
    x, y, w, h = box
    r, s = tow(world, x, y, tol=max(0.8, min(w, h) / 2), budget=budget, check=check, lost=lost, view_switch=view_switch)
    for k in ("Up", "Down", "Left", "Right", "space"): xdo("keyup", k)
    hold("space", 0.5)
    ev(f"in the crane box {x},{y} ({r}); waiting for the crane")
    t0 = time.time()
    while time.time() - t0 < 60:
        if done(): return "lifted"
        if check: check()
        time.sleep(0.5)
    return "no lift"
