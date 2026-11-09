#!/usr/bin/env python3
"""Skill: CAR BOMB (Wave M, SKILL-CARBOMB; 7 jobs in docs/missions-catalogue.md).

The jobs: wil_ym1 HAPPY GAS SMASH, wil_zm1 LICK THOSE LOONIES, ste_ze1 SCIENCE FRICTION, ste_re1
BLOW JOB (two stages), ste_rm1 GREATEST HITS, ste_rm2 BENSON BURNER, bil_rm2 KARMA ASSASSINS.
The decompiled scripts (assets-src/missions/*/...mis) write one of two openings and one ending:

  * a pre-rigged car: `CREATE_GANG_CAR ... PICKUP`, `POINT_ARROW_AT (arrow, car)`, and on boarding
    `GIVE_WEAPON (p1, CAR_BOMB)` (ste_re1, ste_ze1);
  * a car to rig: the arrow on a bomb shop until `HAS_CAR_GOT_WEAPON (car, CAR_BOMB)` (wil_ym1's
    shop at 84.5,160.5, wil_zm1, ste_rm2; the shop takes $5,000 and rigs the car you drive in);
  * then the same loop in every one: `IS_CAR_IN_BLOCK (car, x, y, z, w, h)` with him in the car
    (brief "parked": REMOVE_ARROW), out of the block ("get back": the arrow on the block), out of
    the car in the block un-armed ("get back in": the arrow on the car), `IS_CARBOMB_ACTIVE (car)`
    after fire (brief "armed"); a few game seconds later the car blows up, and
    `CHECK_CAR_WRECKED_IN_AREA` decides: in the block = the stage done (the script's own EXPLODEs
    follow along the target: ste_re1 row 19 x 47-51, column 111 rows 75-78; ste_ze1 the 4 x 5
    block 177-180 x 229-233), outside it = JOB FAILED (2998).

What loses it (playthrough parts 6-10, docs/playthrough-districts.md): the fragile rigged car
burning on the drive (wall hits, pinned in traffic), the car rolling back out of a thin block
after the park (Down brakes then reverses), firing with the car out of the block (it blows up
outside: failed), and above all the escape: the fuse is about 3 s of wall time at GTA2_SPEED=2
(5-6 game seconds); a turn on the spot, a route round the car's nose or a run along the
target the script blows up is a lost life (pt6_ste1, pt8_ste2, pt9_ste5, pt10_bj3); and the
blast's wanted level gets the next fragile car stopped and him arrested (pt7_ste1).

What this module does (on top of the frozen mission_lib / drive_lib, and skills/deliver_intact
for the fragile drive):

  * `Stage(...)`: one rig-park-arm-escape: the block, the game's message keys for its states,
    extra blast points to keep away from, the car's model, optional fixed escape routes.
  * `board(world, stage)`: into the mission car where the game's kind-3 arrow says it is
    (`tcar`), checked by the arrow leaving the car he sits in (a traffic car of the same model
    is not it: pt8_ste2 drove one for minutes).
  * `rig(world, shop)`: into a bomb shop with the car (the arrow on the shop), for the rig jobs.
  * `park(world, stage)`: the fragile drive and the creep into the block (a line-up point for
    thin blocks, else deliver_intact's open-side approach), handbrake as soon as the game says
    "parked", never a reverse after it.
  * `plan_escape(world, stage, car, heading)`: computed while the car stands in the block,
    before arming: from the door he gets out of (the car's right-hand side, y south), the
    route to a ring cell 10-13 blocks off that keeps getting further from the car and from
    every script blast point; fixed routes from the job when it has them.
  * `arm(stage)`: fire until the game says armed, never with the car out of the block.
  * `run_clear(world, legs)`: Return, and Up held from the moment he is on his feet, steering
    pulses only (no unstick moves: a step back is the fuse's last second); in the current view
    (the chase view with GTA2_DIRECT_KEYS=1: no V press in the fuse).
  * `watch(stage)`: the blast and the game's verdict (stage done / complete / failed / dead).
  * `car_bomb(world, stage, check=None)`: all of it with retries ("get back in" / "get back to
    the block" answered); `lie_low()` for the wanted level between stages.

Returns of car_bomb(): "done" (the stage's success brief), "complete" (JOB COMPLETE), "failed",
"dead", "busted", or "stuck: <why>". `check()` (raises) is the job's own guard; `JobOver` is
raised by `Job.check`. Frames: m_<prefix>_incar/_block/_armed/_run/_blast.png in /out, marks
`car_bomb: ...` in /out/marks.txt and in EVENTS.
"""
import math, os, re, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
try:
    from skills import deliver_intact as DI
except Exception:          # the skill works without it (the shared drive3 + its own creep)
    DI = None

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
EVENTS = []
STATS = dict(boards=0, parks=0, arms=0, escapes=0, blasts=0, retries=0)


def ev(what):
    EVENTS.append((time.time(), what)); M.mark(f"car_bomb: {what}")


def gsecs(t0):
    """game seconds since wall time t0"""
    return (time.time() - t0) * D.SPEED


# ---------------------------------------------------------------- the game's words

class JobOver(Exception):
    pass


class Job:
    """every message key the mission line showed (the brief changes inside a second: 2016 then
    2018), the job's end from them and from the player's own fields."""
    def __init__(self, done=("2999",), failed=("2998",), busted=("6155", "6159"), lives0=None):
        self.done, self.failed, self.busted = set(done), set(failed), set(busted)
        self.seen = []; self._off = 0
        ms = M.mission_state() or {}
        self.lives0 = lives0 if lives0 is not None else ms.get("lives")
        self.money0 = ms.get("money", 0)
        try: self._off = os.path.getsize(D.LOG)
        except OSError: self._off = 0

    def poll(self):
        try:
            with open(D.LOG, "rb") as f:
                f.seek(self._off); data = f.read(); self._off += len(data)
        except OSError:
            return self.seen
        for k in re.findall(r"view: mission [^\n]*?msg=(\S+)", data.decode("latin-1")):
            if not self.seen or self.seen[-1] != k: self.seen.append(k)
        return self.seen

    def saw(self, keys, since=0):
        self.poll(); return any(k in keys for k in self.seen[since:])

    def mark_pos(self):
        self.poll(); return len(self.seen)

    def last(self):
        self.poll(); return self.seen[-1] if self.seen else None

    def outcome(self):
        """complete / failed / busted / dead, or None while it runs"""
        self.poll()
        if any(k in self.done for k in self.seen): return "complete"
        ms = M.mission_state() or {}
        if any(k in self.failed for k in self.seen): return "failed"
        if any(k in self.busted for k in self.seen): return "busted"
        if ms.get("health", 1) == 0 or ms.get("death", 0) != 0: return "dead"
        if self.lives0 is not None and ms.get("lives", self.lives0) < self.lives0: return "dead"
        return None

    def check(self):
        o = self.outcome()
        if o: raise JobOver(o)


# ---------------------------------------------------------------- the stage

class Stage:
    """one car bomb.

    box: (x, y, w, h) of IS_CAR_IN_BLOCK; arrow: where the script's block arrow stands (often a
    cell off the box centre, ste_re1's barricade 110.5 vs 111.5); keys (message ids, strings):
      drive  - in the car, not in the block (the arrow goes to the block)
      parked - in the car in the block (REMOVE_ARROW)
      left   - the car left the block again
      out    - out of the car in the block, not armed (get back in)
      armed  - IS_CARBOMB_ACTIVE
      outside- wrecked outside the block (the job fails)
      done   - the stage's success (next stage's brief, or the payoff brief)
    blasts: extra points the script blows up after the car; model: the car's model number
    (vehicle +0x84 enum: 41 PICKUP); car: its spawn (fallback when no arrow); line: (approach,
    creep point) for a thin block that must be entered along its length; routes: {name: [legs]}
    fixed escape routes (else computed); name: for marks and frames."""
    def __init__(self, box, keys, arrow=None, blasts=(), model=None, car=None, line=None,
                 routes=None, name="cb", escape_dist=11):
        self.box = box; self.keys = {k: set(v) if not isinstance(v, str) else {v} for k, v in keys.items()}
        self.arrow = arrow or (box[0], box[1]); self.blasts = list(blasts); self.model = model
        self.car = car; self.line = line; self.routes = routes; self.name = name
        self.escape_dist = escape_dist

    def k(self, what):
        return self.keys.get(what, set())


def in_box(s, box, margin=0.0):
    x, y, w, h = box
    return abs(s["x"] - x) <= w / 2 - margin and abs(s["y"] - y) <= h / 2 - margin


# ---------------------------------------------------------------- driving

DRIVER = os.environ.get("CB_DRIVER", "")      # "" = the shared default, "old" = drive3 before the smooth driver, "smooth"

def drive(world, x, y, tol=1.0, budget=240, until=None):
    """the fragile mission car's drive (slow, precious); CB_DRIVER picks the shared driver"""
    saved = M.SMOOTH[0]
    if DRIVER == "old": M.SMOOTH[0] = False
    elif DRIVER == "smooth": M.SMOOTH[0] = True
    try:
        return M.drive3(world, x, y, tol=tol, budget=budget, slow=True, precious=True, until=until)
    finally:
        M.SMOOTH[0] = saved


def keys_off():
    for key in ("Up", "Down", "Left", "Right", "space", "Control_L"): xdo("keyup", key)


def mission_car_xy(default=None):
    """the mission car's position from the game: the target-car field (tcar), else a kind-3/4
    arrow, else default"""
    ms = M.mission_state() or {}
    tc = ms.get("tcar")
    if tc and tc[0] > 0: return tc
    o = M.objective()
    if o and o[3] in (3, 4): return (o[0], o[1])
    return default


def _enter(world, cx, cy, budget):
    P = sys.modules.get("mission_play_districts")
    if P is not None and hasattr(P, "enter_parked"):
        return P.enter_parked(cx, cy, budget=budget, why="the rigged car")
    return M.enter_car3(world, cx, cy, budget=budget)


def board(world, stage, check=None, tries=4):
    """into the mission car; returns the state when he drives it, else None"""
    for attempt in range(tries):
        if check: check()
        s = D.wait_state()
        if s and s["driving"] and _is_mission_car(stage): return s
        xy = mission_car_xy(stage.car)
        if xy is None:
            say("car_bomb.board: no arrow on a car and no spawn given"); return None
        cx, cy = xy
        STATS["boards"] += 1
        ev(f"{stage.name}: boarding the car at {cx:.1f},{cy:.1f} (try {attempt + 1})")
        if s and s["driving"]:
            M.leave_car(); s = D.wait_state()
        if s and math.hypot(s["x"] - cx, s["y"] - cy) > 12:
            M.walk3(world, cx, cy, None, tol=8.0, budget=240)
            xy2 = mission_car_xy(None)
            if xy2 and math.hypot(xy2[0] - cx, xy2[1] - cy) > 2.0:
                say(f"car_bomb.board: the car moved to {xy2[0]:.1f},{xy2[1]:.1f}"); continue
        s = _enter(world, cx, cy, 200)
        if check: check()
        if s and s["driving"]:
            if _is_mission_car(stage): return s
            say("car_bomb.board: in a car, but not the mission car: out")
            M.leave_car()
    return None


def _is_mission_car(stage):
    time.sleep(0.8)
    ms = M.mission_state() or {}
    if stage.model is not None and ms.get("carmodel") not in (stage.model, -1, None):
        return False
    # the kind-3 arrow leaves the car he sits in (the script points it at the block or removes it)
    return ms.get("tcarhp", -1) == -1


# ---------------------------------------------------------------- rig at a bomb shop

def rig(world, shop, check=None, rigged=None, secs=60, label="the bomb shop"):
    """drive into the shop (x, y) with the car; `rigged()` is the job's test (default: the
    mission arrow moved off the shop). The shop door is one block wide: deliver_intact's creep.
    Needs the money ($5,000 at the shops of these jobs). Untested in the game so far."""
    x, y = shop
    def done():
        if rigged: return rigged()
        o = M.objective()
        return o is None or math.hypot(o[0] - x, o[1] - y) > 2.5
    ev(f"to {label} at {x},{y} (money {(M.mission_state() or {}).get('money')})")
    if DI:
        r = DI.deliver(world, (x, y, 0.9, 1.0), done=done, check=check, label=label, park_wait=2)
    else:
        drive(world, x, y, tol=0.8, budget=300, until=done); r = "delivered" if done() else "stuck"
    t0 = time.time()
    while gsecs(t0) < secs and not done():
        if check: check()
        time.sleep(0.5)
    keys_off()
    ok = done()
    ev(f"{label}: {'rigged' if ok else 'not rigged'} ({r})")
    if ok: hold("Down", 1.4)                 # out of the shop door
    return ok


# ---------------------------------------------------------------- park

def creep(stage, x, y, job, since, secs=60, check=None):
    """nose the car toward (x, y) with short pulses until the game says parked"""
    t0 = time.time(); k = 0
    while gsecs(t0) < secs:
        if check: check()
        if job.saw(stage.k("parked"), since): return True
        s = D.wait_state()
        if not s or not s["driving"]: return False
        hx, hy = M.heading(s); dx, dy = x - s["x"], y - s["y"]
        if math.hypot(dx, dy) < 0.35:
            time.sleep(0.6); continue
        a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
        if abs(a) > 0.6 and math.hypot(dx, dy) > 0.7:
            xdo("keydown", "Down"); xdo("keydown", "Left" if a > 0 else "Right"); time.sleep(0.6)
            xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right"); time.sleep(0.3)
            continue
        if abs(a) > 0.12: xdo("keydown", "Right" if a > 0 else "Left")
        xdo("keydown", "Up"); time.sleep(0.25); xdo("keyup", "Up"); xdo("keyup", "Right"); xdo("keyup", "Left")
        time.sleep(0.45); k += 1
        if k % 6 == 0: hold("Down", 0.6); time.sleep(0.3)
    return job.saw(stage.k("parked"), since)


def hold_still():
    """stopped in the block: the handbrake, every key up (Down would reverse it out: pt7_ste2)"""
    xdo("keyup", "Up"); hold("space", 0.8); keys_off()


def park(world, stage, job, check=None, budget=600):
    """the car into the block; True when the game says parked"""
    x, y, w, h = stage.box
    since = job.mark_pos()
    STATS["parks"] += 1
    if job.saw(stage.k("parked"), max(0, since - 1)) and in_box(D.wait_state(), stage.box):
        hold_still(); return True
    parked = lambda: job.saw(stage.k("parked"), since)
    ev(f"{stage.name}: to the block {x},{y} ({w} x {h}), carhp {(M.mission_state() or {}).get('carhp')}")
    t0 = time.time()
    for attempt in range(3):
        if check: check()
        if time.time() - t0 > budget: break
        s = D.wait_state()
        if not (s and s["driving"]): return False
        if stage.line:
            (ax, ay), (cx, cy) = stage.line
            if math.hypot(s["x"] - cx, s["y"] - cy) > 5.0:
                drive(world, ax, ay, tol=0.9, budget=budget, until=parked)
            if parked(): hold_still(); return True
            if check: check()
            if creep(stage, cx, cy, job, since, secs=50, check=check): hold_still(); return True
        elif DI:
            DI.deliver(world, stage.box, done=parked, check=check, label=f"the {stage.name} block",
                       park_wait=0.5, budget=budget, tries=3)
            if parked(): hold_still(); return True
        else:
            drive(world, x, y, tol=max(0.5, min(w, h) * 0.45), budget=budget, until=parked)
            if parked(): hold_still(); return True
            if creep(stage, x, y, job, since, secs=50, check=check): hold_still(); return True
        say(f"car_bomb.park: not parked after attempt {attempt + 1}; again")
        hold("Down", 0.8)
    return parked()


# ---------------------------------------------------------------- the escape

def door_point(car, heading, world=None, level=1):
    """where he stands after Return: the car's right-hand side (y south: right = (-hy, hx));
    pt9_ste5 facing west came out north, pt10_bj3 facing north came out east. With the map
    given, a side whose cell has no floor (BLOW JOB's trailer on row 19 beside the block) gives
    way to the other side, then the ends"""
    hx, hy = heading
    cands = [(car[0] - hy * 1.0, car[1] + hx * 1.0), (car[0] + hy * 1.0, car[1] - hx * 1.0),
             (car[0] - hx * 1.8, car[1] - hy * 1.8), (car[0] + hx * 1.8, car[1] + hy * 1.8)]
    if world is None: return cands[0]
    for c in cands:
        if M.walkable(world.blocks, world.columns, int(c[0]), int(c[1]), level, (1, 2, 3)):
            return c
    return cands[0]


def _route_ok(legs, start, dangers, min_gain=1.0):
    """no waypoint nearer to any danger than the start (beyond the first block), and the end
    well clear of all of them"""
    d0 = min(math.hypot(start[0] - p[0], start[1] - p[1]) for p in dangers)
    for (lx, ly) in legs:
        d = min(math.hypot(lx - p[0], ly - p[1]) for p in dangers)
        if d < min(d0, 1.6) - 0.05: return False
    end = legs[-1]
    return min(math.hypot(end[0] - p[0], end[1] - p[1]) for p in dangers) >= d0 + min_gain


def _ray(world, x, y, dx, dy, level, dist):
    """free straight run along (dx, dy) from (x, y): how many cells are walkable"""
    ok = 0
    for d in range(1, dist + 1):
        cx, cy = int(x + dx * d), int(y + dy * d)
        if not any(M.walkable(world.blocks, world.columns, cx, cy, lv, (1, 2, 3))
                   for lv in (level, level + 1, level - 1) if lv >= 0): break
        ok = d
    return ok


def plan_escape(world, stage, car, heading, s=None, start=None, quick=False):
    """legs [(x, y), ...] from the exit door away from the car and the script's blast points;
    scored by the end's clearance, the first leg's direction (out of the door side and along the
    car's heading, never across the car) and the route's length"""
    hx, hy = heading
    level = M.ped_level(s) if s else 1
    door = start or door_point(car, heading, world, level)
    dangers = [tuple(car)] + list(stage.blasts)
    side = (door[0] - car[0], door[1] - car[1])
    cands = []
    if stage.routes:
        for name, legs in stage.routes.items():
            cands.append((name, list(legs)))
    else:
        sd = dict(s or {}); sd.update(x=door[0], y=door[1]); sd.setdefault("z", level + 1)
        for dist in (() if quick else (stage.escape_dist, stage.escape_dist - 2, stage.escape_dist + 2)):
            try:
                legs = M.escape_route(world, sd, dist=dist, away=car)
            except Exception as e:
                say(f"car_bomb.plan_escape: escape_route failed ({e})"); legs = []
            if legs: cands.append((f"routed{dist}", legs))
        # straight runs: ahead, the door side, the diagonals between them
        for name, (dx, dy) in (("ahead", (hx, hy)), ("door side", side),
                               ("ahead+side", (hx + side[0], hy + side[1])),
                               ("back+side", (-hx + side[0], -hy + side[1]))):
            n = math.hypot(dx, dy) or 1.0; dx, dy = dx / n, dy / n
            k = _ray(world, door[0], door[1], dx, dy, level, stage.escape_dist + 2)
            if k >= 6:
                cands.append((f"straight {name} {k}", [(door[0] + dx * k * 0.5, door[1] + dy * k * 0.5),
                                                       (door[0] + dx * k, door[1] + dy * k)]))
    best = None
    for name, legs in cands:
        if not legs: continue
        ok = stage.routes is not None or _route_ok(legs, door, dangers)
        fx, fy = legs[0][0] - door[0], legs[0][1] - door[1]; fn = math.hypot(fx, fy) or 1.0
        fx, fy = fx / fn, fy / fn
        sn = math.hypot(*side) or 1.0
        dir_score = (fx * side[0] + fy * side[1]) / sn + 0.6 * (fx * hx + fy * hy)
        end = legs[-1]
        clear = min(math.hypot(end[0] - p[0], end[1] - p[1]) for p in dangers)
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip([door] + legs[:-1], legs))
        score = (0 if ok else -10) + dir_score * 2.0 + min(clear, 14) * 0.5 - max(0.0, length - clear) * 0.4
        say(f"car_bomb.escape {name}: ok={ok} dir {dir_score:.2f} clear {clear:.1f} len {length:.1f} -> {score:.2f}")
        if best is None or score > best[0]: best = (score, name, legs)
    if not best:
        ex, ey = M.escape_point(world, car[0], car[1], level, dist=8)
        return "escape_point", [(ex, ey)]
    return best[1], best[2]


def run_legs(legs, secs):
    """Up held from the first moment, steering pulses toward each leg in turn"""
    t0 = time.time(); k = 0
    xdo("keydown", "Up")
    try:
        while gsecs(t0) < secs and k < len(legs):
            s = D.wait_state()
            if not s: break
            tx, ty = legs[k]
            if math.hypot(tx - s["x"], ty - s["y"]) < 1.2:
                k += 1; continue
            a = D.angle_to(s, tx, ty)
            if abs(a) > 0.15:
                key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
                xdo("keydown", key); time.sleep(min(abs(a) / max(D.rate, 2.0), 0.35)); xdo("keyup", key)
            time.sleep(0.08)
    finally:
        xdo("keyup", "Up")
    return D.wait_state()


def run_clear(world, stage, car, heading, legs=None, secs=14.0):
    """out of the car and away from the bomb along the planned legs (re-planned from where he
    actually stands when that is off the door point by more than a block)"""
    t0 = time.time()
    tap("Return", 0.2)
    for _ in range(20):
        s = D.wait_state()
        if s and not s["driving"]: break
        time.sleep(0.08)
    s = D.wait_state()
    door = door_point(car, heading, world, M.ped_level(s))
    if legs is None or math.hypot(s["x"] - door[0], s["y"] - door[1]) > 1.2:
        # out on another side than planned (or no plan): from where he stands
        name, legs = plan_escape(world, stage, car, heading, s, start=(s["x"], s["y"]), quick=True)
        say(f"car_bomb.run_clear: re-planned from {s['x']:.1f},{s['y']:.1f}: {name}")
    STATS["escapes"] += 1
    M.mark(f"car_bomb: out at {s['x']:.1f},{s['y']:.1f}, running {[(round(a, 1), round(b, 1)) for a, b in legs]}")
    s = run_legs(legs, secs)
    if s:
        d = math.hypot(s["x"] - car[0], s["y"] - car[1])
        say(f"car_bomb.run_clear: {d:.1f} blocks from the car after {gsecs(t0):.1f} game s")
    return s


# ---------------------------------------------------------------- arm, watch

def arm(stage, job, check=None, tries=8):
    """fire (Control) until the game says armed; never with the car out of the block"""
    since = job.mark_pos()
    STATS["arms"] += 1
    for k in range(tries):
        if check: check()
        if job.saw(stage.k("armed"), max(0, since - 1)): return True
        last = job.last()
        if last in stage.k("left"):
            say(f"car_bomb.arm: the car is out of the block (msg {last}); not firing"); return False
        if k == 3: tap("Tab", 0.3); time.sleep(0.4)      # the weapon slot, if the bomb is not selected
        xdo("keydown", "Control_L"); time.sleep(0.3); xdo("keyup", "Control_L"); time.sleep(0.35)
        if job.saw(stage.k("armed"), since): return True
    return job.saw(stage.k("armed"), since)


def watch(stage, job, secs=40, shot_prefix=None):
    """after the escape: the stage's verdict"""
    t0 = time.time(); shot_blast = False
    since = max(0, job.mark_pos() - 4)
    while gsecs(t0) < secs:
        o = job.outcome()
        if o: return o
        if job.saw(stage.k("done"), since): return "done"
        if job.saw(stage.k("outside"), since): return "failed"
        last = job.last()
        if last in stage.k("out") or last in stage.k("left"):
            return "again"
        ms = M.mission_state() or {}
        if not shot_blast and shot_prefix and ms.get("tcarhp", -1) == -1 and gsecs(t0) > 2.0:
            M.shot(f"{shot_prefix}_blast"); shot_blast = True
        time.sleep(0.25)
    return "no blast"


def lie_low(secs=25.0):
    """stand still while the blast's wanted level decays (pt7_ste1: a cop stopped the next
    fragile car and arrested him)"""
    w0 = (M.mission_state() or {}).get("wanted", 0)
    if w0 <= 0: return True
    ev(f"wanted level {w0} after the blast: lying low up to {secs:.0f} game s")
    t0 = time.time()
    while gsecs(t0) < secs:
        if (M.mission_state() or {}).get("wanted", 0) <= 0:
            ev(f"wanted level gone after {gsecs(t0):.0f} game s"); return True
        time.sleep(1.0)
    return False


# ---------------------------------------------------------------- the whole stage

def car_bomb(world, stage, job, check=None, tries=3, budget=900, shot_prefix=None, run_secs=14.0):
    """board, park, arm, escape, verdict; see the module docstring for the returns"""
    shot_prefix = shot_prefix or f"m_{stage.name}"
    chk = check or job.check
    t0 = time.time()
    try:
        for attempt in range(tries):
            if attempt: STATS["retries"] += 1
            if time.time() - t0 > budget: return "stuck: out of time"
            s = board(world, stage, check=chk)
            if not s: return "stuck: not in the car"
            M.shot(f"{shot_prefix}_incar")
            if not park(world, stage, job, check=chk):
                if not (D.wait_state() or {}).get("driving"): continue     # pulled out: board again
                return "stuck: not parked"
            s = D.wait_state()
            M.shot(f"{shot_prefix}_block")
            car = (s["x"], s["y"]); heading = M.heading(s)
            name, legs = plan_escape(world, stage, car, heading, s)
            ev(f"{stage.name}: parked at {car[0]:.2f},{car[1]:.2f} heading {heading[0]:.2f},{heading[1]:.2f}; "
               f"escape {name}")
            if not arm(stage, job, check=chk):
                if job.last() in stage.k("left"): continue
                return "stuck: not armed"
            ev(f"{stage.name}: armed (msg {job.last()})")
            run_clear(world, stage, car, heading, legs, secs=run_secs)
            M.shot(f"{shot_prefix}_run")
            v = watch(stage, job, shot_prefix=shot_prefix)
            ev(f"{stage.name}: {v}")
            if v == "again": continue
            if v == "done": STATS["blasts"] += 1
            return v
        return "stuck: retries spent"
    except JobOver as e:
        ev(f"{stage.name}: job over ({e})")
        return str(e)
    finally:
        keys_off()
