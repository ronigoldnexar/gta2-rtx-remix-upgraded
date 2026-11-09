#!/usr/bin/env python3
"""Skill: ESCORT / PROTECT (Wave M, SKILL-ESCORT; 15 jobs carry `escort_protect` in
docs/missions-catalogue.md).

What the job scripts ask (assets-src/missions/*/*.mis):
  * a character the script creates walks to the player's car and boards it
    (`SET_CHAR_OBJECTIVE (chr, ENTER_CAR_AS_PASSENGER, car)`, `IS_CHAR_OBJECTIVE_PASSED`): GET GAMA REI,
    GET ZITZAKI, BANK ROBBERY's Hiroshi, the Z-Men, the Russian workers, Gran'pa, Ivan's soldiers;
  * he must arrive alive (`HAS_CHARACTER_DIED (chr)` fails the job, brief + 1125) and usually still aboard
    (`IS_CHARACTER_IN_CAR (chr, car)` before `PARK`), often with killers sent after him
    (`SET_CHAR_OBJECTIVE (killer, KILL_CHAR_ANY_MEANS, chr)`, GET GAMA REI's two Loony Isettas);
  * or a character follows the player on foot (`FOLLOW_CHAR` / walk-behind) and must be led there
    (DECONSTRUCTION YARD's Leo, LOCK-OUT's slow Satchmo, ROOFTOP RESCUE's Krishna).

What this module gives a job runner (gamerun/missions/<job>.py), all on the frozen mission_lib /
drive_lib and the deliver_intact skill:
  * `Escort(name, pick, near=..., count=...)`: picks the protected people out of `view: peds`
    (a predicate, a spawn point and radius) and tracks them by ped id: `members()`, `dead()`,
    `aboard(s)`, `spread(s)`;
  * `wait_board(world, esc, ...)`: in the car, hands off the keys (a moving car is never boarded),
    optional horn, waits until every member is in the player's car; a member who stalls (no
    progress toward the car for STALL_SECS) gets the car brought to him (a short drive to a point
    beside him), unless the job pins the car in a box (`move=False`);
  * `drive(world, box, esc, ...)`: deliver_intact.deliver to the box with two watches added to the
    job's check: an escortee no longer aboard stops the drive and goes back to wait_board, and
    killers near (`threat_cars` / `threats`) raise the fragile pace so the car is not caught
    crawling (the GET GAMA REI Isettas shoot at a slow Medicar);
  * `lead(world, esc, goal, ...)`: on foot, short legs along the walker's route, waiting when the
    follower falls GAP blocks behind and walking back to him past LOST blocks; `defend` on the way;
  * `threats(esc, ...)` / `threat_cars(...)` / `defend(world, esc, ...)`: armed or hostile peds near
    the escort, shot at with the trigger held off while an escortee is in the line of fire.

Returns are strings: "aboard", "delivered", "arrived", "complete", "failed", "dead" (an escortee
died), "timeout", "stuck: ...". The events go to /out/marks.txt with an `escort:` prefix and to
EVENTS for the job's doc.
"""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
from skills import deliver_intact as DI

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

ABOARD_R = 1.6          # an escortee logged in a car within this of the player's car is aboard
STALL_SECS = 14.0       # wall seconds (at speed 1) without progress before the car goes to him
STALL_GAIN = 0.6        # blocks of progress that count
GAP = 3.5               # lead: wait when the follower is this far behind
LOST = 11.0             # lead: walk back to him beyond this
LEG = 3.0               # lead: blocks per walking leg
THREAT_R = 9.0          # a hostile ped this near an escortee is a threat
THREAT_CAR_R = 14.0     # a hostile driver this near the player's car is a threat
THREAT_CAP = float(os.environ.get("ESCORT_THREAT_CAP", "3.4"))   # fragile-drive cap while killers are near
THREAT_MIN_HP = 19000   # ... unless the car is this hurt (then care wins)
# occupations that carry a gun or attack (docs/actions-3d.md table): angry/armed robbed drivers,
# psycho, mugger, car thief, bank robber, armed gang member, the criminals the scripts create
ARMED_OCC = {11, 12, 13, 14, 15, 16, 17, 19, 33, 34, 40}
EVENTS = []


def _ev(what):
    EVENTS.append((time.time(), what)); M.mark(f"escort: {what}")


def _scale(secs):
    return secs / max(1.0, getattr(D, "SPEED", 1.0))


# ------------------------------------------------------------------ who is escorted

class Escort:
    """the protected people: picked by pick(p) (and near=(x, y) within radius), tracked by id"""

    def __init__(self, name, pick=None, near=None, radius=4.0, count=1, ids=None):
        self.name, self.pick, self.near, self.radius, self.count = name, pick, near, radius, count
        self.ids = list(ids or [])
        self.last = {}          # id -> the last ped dict seen
        self.gone = set()       # ids seen dead, or vanished with the player close to the last position

    def _match(self, p):
        if p["id"] == 1 or p["occ"] == 0: return False
        if not M.ped_alive(p): return False
        if self.pick and not self.pick(p): return False
        if self.near and math.hypot(p["x"] - self.near[0], p["y"] - self.near[1]) > self.radius: return False
        return True

    def acquire(self, secs=0.0, check=None):
        """add matching peds up to `count`; waits up to secs for them to appear. True when complete"""
        t0 = time.time()
        while True:
            for p in M.peds():
                if len(self.ids) >= self.count: break
                if p["id"] in self.ids or not self._match(p): continue
                self.ids.append(p["id"]); self.last[p["id"]] = p
                _ev(f"{self.name}: ped {p['id']} {p['type']}/{p['gang']} remap {p['remap']} occ {p['occ']} at {p['x']:.1f},{p['y']:.1f}")
            if len(self.ids) >= self.count or time.time() - t0 >= secs: return len(self.ids) >= self.count
            if check: check()
            time.sleep(0.4)

    def adopt_aboard(self, pick=None):
        """take the matching peds already in the player's car (a boarding that was quicker than the
        on-foot pick: gr4's Dr ZitZaki was on foot in the log for nine lines). True when complete"""
        s = D.state()
        if not s or not s["driving"]: return len(self.ids) >= self.count
        for p in M.peds():
            if len(self.ids) >= self.count: break
            if p["id"] in self.ids or p["id"] == 1 or p["car"] is None or not M.ped_alive(p): continue
            if math.hypot(p["x"] - s["x"], p["y"] - s["y"]) > ABOARD_R: continue
            if not (pick or (lambda q: self.pick(dict(q, car=None)) if self.pick else True))(p): continue
            self.ids.append(p["id"]); self.last[p["id"]] = p
            _ev(f"{self.name}: ped {p['id']} {p['type']}/{p['gang']} remap {p['remap']} occ {p['occ']} found aboard")
        return len(self.ids) >= self.count

    def members(self, s=None):
        """{id: ped dict} of the members in the log now; refreshes `last` and `gone`"""
        cur = {p["id"]: p for p in M.peds()}
        s = s or D.state()
        out = {}
        for pid in self.ids:
            p = cur.get(pid)
            if p is not None:
                self.last[pid] = p
                if not M.ped_alive(p):
                    if pid not in self.gone: self.gone.add(pid); _ev(f"{self.name}: ped {pid} down at {p['x']:.1f},{p['y']:.1f}")
                    continue
                out[pid] = p
            elif s and pid in self.last and pid not in self.gone:
                q = self.last[pid]
                # out of the 24-block peds window is "unknown"; gone from the window near him is a death
                # (or the script deleting him, which only happens at the end of a job)
                if math.hypot(q["x"] - s["x"], q["y"] - s["y"]) < 12 and q["car"] is None:
                    self.gone.add(pid); _ev(f"{self.name}: ped {pid} vanished at {q['x']:.1f},{q['y']:.1f}")
        return out

    def dead(self):
        return bool(self.gone)

    def aboard(self, s=None):
        """every member logged in a car at the player's car (the player driving)"""
        s = s or D.state()
        if not s or not s["driving"] or not self.ids: return False
        mem = self.members(s)
        if len(mem) < len([i for i in self.ids if i not in self.gone]): return False
        return all(p["car"] is not None and math.hypot(p["x"] - s["x"], p["y"] - s["y"]) < ABOARD_R for p in mem.values())

    def on_foot(self, s=None):
        return [p for p in self.members(s).values() if p["car"] is None]

    def spread(self, s=None):
        """the farthest member's distance from the player (0 with none in sight)"""
        s = s or D.state()
        mem = self.members(s)
        if not s or not mem: return 0.0
        return max(math.hypot(p["x"] - s["x"], p["y"] - s["y"]) for p in mem.values())

    def where(self):
        """(x, y) of the members' centre, from the last positions seen"""
        pts = [self.last[i] for i in self.ids if i in self.last and i not in self.gone]
        if not pts: return None
        return (sum(p["x"] for p in pts) / len(pts), sum(p["y"] for p in pts) / len(pts))


# ------------------------------------------------------------------ threats

def threats(esc, pick=None, radius=THREAT_R, s=None):
    """hostile peds on foot near an escortee (or the player): pick(p) -> True for a killer;
    default an armed occupation. Nearest to the escort first"""
    s = s or D.state()
    centres = [(p["x"], p["y"]) for p in esc.members(s).values()] or ([(s["x"], s["y"])] if s else [])
    out = []
    for p in M.peds():
        if p["id"] == 1 or p["id"] in esc.ids or not M.ped_alive(p) or p["car"] is not None: continue
        if not (pick(p) if pick else p["occ"] in ARMED_OCC): continue
        d = min((math.hypot(p["x"] - cx, p["y"] - cy) for cx, cy in centres), default=99.0)
        if d < radius: out.append((d, p))
    return [p for d, p in sorted(out, key=lambda t: t[0])]


def threat_cars(pick=None, radius=THREAT_CAR_R, s=None):
    """cars near the player driven by killers: pick(car) (the `view: cars` dict: model, driver
    'type/gang', ...) -> True; default none. Nearest first"""
    if pick is None: return []
    s = s or D.state()
    if not s: return []
    out = []
    for c in M.cars():
        if c["driver"] in ("P", "-") or c["fire"] > 1: continue
        d = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
        if d < radius and pick(c): out.append((d, c))
    return [c for d, c in sorted(out, key=lambda t: t[0])]


def _in_line(s, tx, ty, px, py, width=0.9):
    dx, dy = tx - s["x"], ty - s["y"]; n = math.hypot(dx, dy)
    if n < 1e-6: return False
    ux, uy = dx / n, dy / n
    along = (px - s["x"]) * ux + (py - s["y"]) * uy
    if along < 0.2 or along > n + 0.5: return False
    return abs((px - s["x"]) * uy - (py - s["y"]) * ux) < width


def defend(world, esc, pick=None, secs=60, radius=THREAT_R, check=None, engage=7.0):
    """on foot: shoot the threats near the escort until none is left (or secs). Returns the number
    of threats seen down"""
    t0 = time.time(); down = set(); seen = {}; k = 0
    if not M.gun_ready() and not M.select_gun(): _ev("defend: no gun in hand"); return 0
    try:
        while time.time() - t0 < secs:
            if check: check()
            s = D.wait_state()
            if not s or s["driving"]: break
            ts = threats(esc, pick, radius, s)
            for p in ts: seen[p["id"]] = p
            allp = {p["id"]: p for p in M.peds()}
            for pid, p in seen.items():
                q = allp.get(pid)
                if pid not in down and (q is None or not M.ped_alive(q)): down.add(pid); _ev(f"defend: threat {pid} down")
            if not ts: break
            tgt = ts[0]
            d = math.hypot(tgt["x"] - s["x"], tgt["y"] - s["y"])
            blocker = next((p for p in esc.members(s).values() if _in_line(s, tgt["x"], tgt["y"], p["x"], p["y"])), None)
            if blocker:
                xdo("keyup", "Control_L")
                dx, dy = tgt["x"] - s["x"], tgt["y"] - s["y"]; n = math.hypot(dx, dy) or 1.0
                side = 1 if k % 2 else -1; k += 1
                M.cruise_to(s["x"] - dy / n * 1.4 * side, s["y"] + dx / n * 1.4 * side, tol=0.4, secs=3)
                continue
            M._aim_walk(tgt["x"], tgt["y"], fire=True, walk=d > engage, secs=0.5)
    finally:
        xdo("keyup", "Control_L"); xdo("keyup", "Up")
    return len(down)


# ------------------------------------------------------------------ boarding

def _car_xy(s, car):
    if s and s["driving"]: return (s["x"], s["y"])
    return DI.mission_car_xy(car) or car


def bring_car(world, p, check=None, budget=40):
    """drive the car to a point beside a stalled escortee (the road cell nearest him, else his
    own position less a block toward the car)"""
    s = D.wait_state()
    if not s or not s["driving"]: return s
    d = math.hypot(p["x"] - s["x"], p["y"] - s["y"])
    tx, ty = p["x"] + (s["x"] - p["x"]) / max(d, 1e-3) * 1.6, p["y"] + (s["y"] - p["y"]) / max(d, 1e-3) * 1.6
    cell = M.street_cell_near(world, p["x"], p["y"], radius=4)
    if cell and math.hypot(cell[0] - p["x"], cell[1] - p["y"]) < 3.0: tx, ty = cell[0], cell[1]
    _ev(f"bring the car to {tx:.1f},{ty:.1f} (escortee {p['id']} at {p['x']:.1f},{p['y']:.1f}, {d:.1f} off)")
    s = M.drive3(world, tx, ty, tol=1.0, budget=budget, slow=True, precious=True)
    DI.keys_off(); hold("Down", 0.3); DI.keys_off()
    return s


def wait_board(world, esc, car=None, budget=150, horn=False, move=True, done=None, check=None):
    """keys off in the car until every member is aboard. done(): the job's own "aboard" signal
    (a brief, the arrow moving on). Returns 'aboard', 'dead', 'timeout'"""
    t0 = time.time()
    _ev(f"{esc.name}: waiting for {esc.count} to board (horn {horn}, move {move})")
    best = {}; t_prog = {}; brought = 0; k = 0; t_said = 0.0
    while time.time() - t0 < budget:
        if check: check()
        if done and done():
            esc.adopt_aboard()
            _ev(f"{esc.name}: the job says aboard (tracked {esc.ids})"); return "aboard"
        s = D.wait_state()
        if not s["driving"]:
            s = DI.board(world, car, check=check)
            continue
        if esc.dead(): return "dead"
        if len(esc.ids) < esc.count:
            esc.acquire(secs=0)
            if len(esc.ids) < esc.count: esc.adopt_aboard()
        if esc.ids and esc.aboard(s):
            _ev(f"{esc.name}: aboard at {s['x']:.1f},{s['y']:.1f} ({time.time() - t0:.0f}s)"); return "aboard"
        DI.keys_off()
        if horn and k % 4 == 0: M.horn(1)
        k += 1
        now = time.time()
        for p in esc.on_foot(s):
            d = math.hypot(p["x"] - s["x"], p["y"] - s["y"])
            if d < best.get(p["id"], 1e9) - STALL_GAIN: best[p["id"]] = d; t_prog[p["id"]] = now
            t_prog.setdefault(p["id"], now)
            if now - t_said > 6:
                say(f"escort: {esc.name} ped {p['id']} {d:.1f} from the car, state {p['state']}:{p['sub']} hp {p['hp']}"); t_said = now
            if move and brought < 3 and d > 2.2 and now - t_prog[p["id"]] > _scale(STALL_SECS):
                brought += 1; bring_car(world, p, check=check)
                best.pop(p["id"], None); t_prog[p["id"]] = time.time()
                break
        time.sleep(0.5)
    return "timeout"


# ------------------------------------------------------------------ carrying them

class Lost(Exception):
    pass


def drive(world, box, esc, car=None, check=None, view_switch=None, threat_pick=None,
          car_threat_pick=None, rebound=3, board_budget=90, **kw):
    """deliver_intact.deliver to box with the escort watched: an escortee no longer aboard (two
    reads in a row) stops the drive and waits for him to board again; killers near raise the pace.
    Returns deliver's answer, or 'dead' when an escortee died"""
    saved = (M.SMOOTH_SLOW_CAP, M.CARE_CAP)
    state = {"off": 0, "threat": False, "t_th": 0.0}

    def watched():
        ms = check() if check else (M.mission_state() or {})
        s = D.state()
        if esc.dead(): raise Lost("dead")
        if s and s["driving"]:
            if not esc.aboard(s):
                state["off"] += 1
                if state["off"] >= 3: raise Lost("off")
            else:
                state["off"] = 0
            now = time.time()
            if now - state["t_th"] > 0.8:
                state["t_th"] = now
                tc = threat_cars(car_threat_pick, s=s) if car_threat_pick else []
                tp = threats(esc, threat_pick, s=s) if threat_pick else []
                hp = DI.car_hp()
                hot = bool(tc or tp) and hp >= THREAT_MIN_HP
                if hot != state["threat"]:
                    state["threat"] = hot
                    if hot:
                        who = tc[0] if tc else tp[0]
                        _ev(f"{esc.name}: killers near ({len(tc)} cars, {len(tp)} on foot; nearest m{who.get('model', '-')} "
                            f"{who.get('driver', who.get('gang'))} at {who['x']:.1f},{who['y']:.1f}): pace up to {THREAT_CAP}")
                    else:
                        _ev(f"{esc.name}: clear of the killers")
                if hot:
                    M.SMOOTH_SLOW_CAP = max(M.SMOOTH_SLOW_CAP, THREAT_CAP); M.CARE_CAP = max(M.CARE_CAP, THREAT_CAP)
        return ms

    try:
        for k in range(rebound + 1):
            try:
                return DI.deliver(world, box, car=car, check=watched, view_switch=view_switch, **kw)
            except Lost as e:
                DI.keys_off()
                if str(e) == "dead" or esc.dead(): _ev(f"{esc.name}: an escortee died"); return "dead"
                s = D.wait_state(); mem = esc.members(s)
                _ev(f"{esc.name}: not aboard any more at {s['x']:.1f},{s['y']:.1f} "
                    f"({', '.join(f'{p['id']}@{p['x']:.1f},{p['y']:.1f} car {p['car']}' for p in mem.values()) or 'none in sight'}): stop and wait")
                hold("Down", 0.6); DI.keys_off(); state["off"] = 0
                r = wait_board(world, esc, car=car, budget=board_budget, move=True, check=check)
                if r != "aboard": return r if r == "dead" else f"stuck: {esc.name} did not board again"
        return f"stuck: {esc.name} lost {rebound + 1} times"
    finally:
        M.SMOOTH_SLOW_CAP, M.CARE_CAP = saved


# ------------------------------------------------------------------ leading on foot

def lead(world, esc, goal, tol=1.0, level=None, budget=300, check=None, threat_pick=None, gap=GAP, lost=LOST):
    """walk to goal with the escort following: legs of LEG blocks; wait past `gap`, go back past
    `lost`, defend when threats close in. Returns 'arrived', 'dead', 'timeout'"""
    t0 = time.time(); gx, gy = goal
    _ev(f"{esc.name}: lead to {gx:.1f},{gy:.1f}")
    while time.time() - t0 < budget:
        if check: check()
        s = D.wait_state()
        if esc.dead(): return "dead"
        if s["driving"]: s = M.leave_car()
        if threat_pick and threats(esc, threat_pick, s=s):
            defend(world, esc, threat_pick, secs=30, check=check)
            continue
        d_goal = math.hypot(gx - s["x"], gy - s["y"])
        far = esc.spread(s)
        if d_goal < tol and far < gap: _ev(f"{esc.name}: arrived with the escort ({far:.1f} behind)"); return "arrived"
        if far > lost:
            c = esc.where()
            if c:
                _ev(f"{esc.name}: {far:.1f} behind: back to {c[0]:.1f},{c[1]:.1f}")
                M.walk3(world, c[0], c[1], None, tol=gap - 1.0, budget=60)
            continue
        if far > gap:
            xdo("keyup", "Up"); t1 = time.time()
            while time.time() - t1 < _scale(8) and esc.spread() > gap - 1.0:
                if check: check()
                time.sleep(0.4)
            continue
        # one leg along the route
        path = None
        try:
            path = M.route3(world, int(s["x"]), int(s["y"]), M.ped_level(s), int(gx), int(gy), level)
        except Exception:
            path = None
        if path and len(path) > 1:
            k = min(len(path) - 1, max(1, int(LEG)))
            px, py = path[k][0] + 0.5, path[k][1] + 0.5
            if k == len(path) - 1: px, py = gx, gy
        else:
            n = max(d_goal, 1e-3); step = min(LEG, d_goal)
            px, py = s["x"] + (gx - s["x"]) / n * step, s["y"] + (gy - s["y"]) / n * step
        M.walk3(world, px, py, level, tol=0.6, budget=20)
    return "timeout"
