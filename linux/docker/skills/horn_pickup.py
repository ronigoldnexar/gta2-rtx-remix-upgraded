#!/usr/bin/env python3
"""Skill: HORN PICK-UP (Wave M, SKILL-HORN; 13 jobs carry `horn_pickup` in docs/missions-catalogue.md:
wil_ye1, wil_ym1, wil_ze1, wil_zm1, wil_zm2, wil_zm3, wil_lm3, ste_se1, ste_se2, ste_sm2, ste_sh1,
bil_km1, bil_re2).

What the job scripts ask (assets-src/missions/*/*.mis), always the same three-step pattern:
  1. a character (often a group: `ADD_GROUP_TO_CHARACTER (chr, n)`) waits on foot (`WAIT_ON_FOOT`)
     with the arrow on him; the player must be IN THE MISSION CAR inside a box round him
     (`LOCATE_CHARACTER_BY_CAR (p1, x, y, z, w, h)` / `LOCATE_ANOTHER_CHARACTER_BY_CAR (p1, chr, w, h)`);
     the script then says "Sound the horn" (Residential 2278, Downtown 1638, Industrial 3526);
  2. `IS_CHAR_PRESSING_HORN (p1)` (often only checked while `IS_CHARACTER_IN_CAR (p1, car)`) answers
     with a brief and `SET_CHAR_OBJECTIVE (chr, ENTER_CAR_AS_PASSENGER, car)`: the horn is taken
     ONCE per stop (a counter blocks a second one), so the car must already stand where he can walk
     to it, and a moving car is never boarded;
  3. `IS_GROUP_IN_CAR (chr)` / `IS_CHAR_IN_CAR` / `IS_CHAR_OBJECTIVE_PASSED` moves the job on: the next
     stop's brief and arrow, or the drop-off. Fails on the way: the car wrecked or sunk, the man (or
     too many of his group, `CHECK_NUMBER_ALIVE_IN_GROUP`) dead - a car stopped ON him kills him.

What this module gives a job runner (gamerun/missions/<job>.py), on the frozen mission_lib /
drive_lib and the deliver_intact skill:
  * `Msgs`: a follower of the mission line's message keys (`view: mission ... msg=`), every key in
    order (briefs change inside a second: 2304 "here they come" then 2305 "next stop"), with
    `mark()` / `since(keys, mark)` so the same "Sound the horn" key at four stops is told apart;
  * `Stop(name, x, y, w, h, ...)`: one pick-up: the locate box, where the man stands, the briefs that
    say the horn was taken (`horn_keys`) and that they are all aboard (`aboard_keys`), how many
    board, a ped predicate for logging the group;
  * `stand_point(world, stop, s)`: where the car stops: inside the box with a margin, on flat
    ground at his level (a road cell preferred), STAND_MIN..STAND_MAX blocks from him (never on his
    feet: pt8_bil2 ran a dealer over), nearest to the car's approach;
  * `pickup(world, stop, msgs, car=..., check=...)`: the whole stop: drive in (deliver_intact's
    fragile drive with its respray and health pacing; done when the script's horn brief or the box
    is reached), stop dead, horn until the script takes it, then hands off while they walk and board;
    a group that makes no progress for STALL_SECS gets the car moved to another stand point round
    him (a horn after the first does nothing, so no horn then); out of the car (pulled out, bailed)
    -> back in and to the box; returns "aboard", "failed", "dead", "complete", "timeout", "stuck: ...";
  * `drop_off(world, box, msgs, ...)`: drive into a drop-off box (deliver_intact) and, if the job
    wants it, get out and walk clear (FAKE TRUCE locks the bus and blows it up with the gang inside).

Every step marks /out/marks.txt with `horn: ...` and appends to EVENTS for the job's doc.
"""
import math, os, re, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
from skills import deliver_intact as DI

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

SOUND_HORN = {"2278", "1638", "3526"}  # "Sound the horn" (Residential, Downtown, Industrial)
STAND_MIN = 2.2       # blocks from the man: never on his feet, never on his group
STAND_MAX = 4.2       # ... and near enough that the walk to the door is short
CREEP_NEAR = 3.0      # after the drive, a box centre nearer than this is crept into straight (sd_ccc4)
WANDER = 4.0          # the stand-point drive is stopped when it gets this much farther from the box (sd_ccc2)
BOX_MARGIN = 0.7      # a stand point is this far inside the locate box's edge
HORN_SECS = 40.0      # horn this long (wall s at speed 1) for the script to take it
BOARD_SECS = 150.0    # wait this long for them to board (wall s at speed 1)
STALL_SECS = 22.0     # no progress toward the car for this long -> move the car (wall s at speed 1)
STALL_GAIN = 0.7      # blocks of progress that count
MOVES = 3             # car moves per stop
GROUP_R = 5.0         # his group stands within this of him
EVENTS = []


def _ev(what):
    EVENTS.append((time.time(), what)); M.mark(f"horn: {what}")


def _scale(secs):
    return secs / max(1.0, getattr(D, "SPEED", 1.0))


# ------------------------------------------------------------------ the game's words

class Msgs:
    """every message key the mission line showed, in order (polled from the log, so keys that last
    under a second are not missed). mark() -> an index; since(keys, mark) -> seen after it"""
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


# ------------------------------------------------------------------ a stop

class Stop:
    """one pick-up. x, y, w, h: the script's locate box (centre, full sizes); man: where he stands
    (default the box centre; the arrow on him overrides it when it is near); horn_keys: the brief(s)
    the horn is answered with; aboard_keys: the brief(s) that follow when they are all aboard (or
    aboard(): a test of the runner's own); horned(): the runner's own "the horn was taken" test (a
    script that answers with no brief: GET ZITZAKI creates the doctor); count: how many board (his
    group + 1); pick(p): a ped predicate for the group's log lines; move: the car may be moved to
    another stand point while they walk (False when the script wants it to stay in a box: GET
    ZITZAKI's 3 x 1 says 1648 and stops the doctor when the car leaves); need_box_brief: wait a
    moment for the script's "Sound the horn" before the first press"""

    def __init__(self, name, x, y, w, h, horn_keys=(), aboard_keys=(), aboard=None, man=None, count=1,
                 pick=None, need_box_brief=True, horned=None, move=True):
        self.name, self.x, self.y, self.w, self.h = name, x, y, w, h
        self.horn_keys, self.aboard_keys, self.aboard_fn = set(horn_keys), set(aboard_keys), aboard
        self.horned_fn, self.move = horned, move
        self.man = man or (x, y)
        self.count, self.pick, self.need_box_brief = count, pick, need_box_brief

    @property
    def narrow(self):
        """a strip the car must be IN (a 3 x 1): deliver_intact's open-side approach and creep"""
        return min(self.w, self.h) < 1.6

    @property
    def box(self):
        return (self.x, self.y, self.w, self.h)


def man_xy(stop):
    """where he is now: the kind-2 arrow (on a character) near the stop, else the script's point"""
    o = M.objective()
    if o and o[3] == 2 and math.hypot(o[0] - stop.man[0], o[1] - stop.man[1]) < 6: return (o[0], o[1])
    return stop.man


def group(stop, near=None):
    """the peds round him (pick() or any non-player), nearest first"""
    cx, cy = near or man_xy(stop)
    out = []
    for p in M.peds():
        if p["id"] == 1 or not M.ped_alive(p): continue
        if stop.pick and not stop.pick(p): continue
        d = math.hypot(p["x"] - cx, p["y"] - cy)
        if d <= GROUP_R or p.get("mark") is not None: out.append((d, p))
    return [p for d, p in sorted(out, key=lambda t: t[0])]


def stand_point(world, stop, s, avoid=(), lo=STAND_MIN, hi=STAND_MAX):
    """a point inside the box (BOX_MARGIN in), flat at his level, lo..hi from him, a road cell
    preferred, nearest to the car; `avoid`: points tried already (kept 2 blocks off)"""
    mx, my = man_xy(stop)
    L = next((L for L in range(1, 6) if M.node_kind(world, int(mx), int(my), L)), 1)
    hx, hy = stop.w / 2 - BOX_MARGIN, stop.h / 2 - BOX_MARGIN
    best = None
    steps = 12
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            px, py = stop.x + i * max(hx, 0.1) / steps, stop.y + j * max(hy, 0.1) / steps
            d = math.hypot(px - mx, py - my)
            if d < lo or d > hi: continue
            if any(math.hypot(px - a[0], py - a[1]) < 2.0 for a in avoid): continue
            nk = M.node_kind(world, int(px), int(py), L)
            if not nk or nk[0] != "flat" or nk[1] not in (1, 2, 3): continue
            # the car's centre on a road cell, its neighbours along the road open (a long bus)
            c = math.hypot(px - s["x"], py - s["y"]) + {1: 0.0, 2: 5.0, 3: 7.0}[nk[1]] + 1.5 * abs(d - (lo + 0.6))
            if best is None or c < best[0]: best = (c, px, py)
    return (best[1], best[2]) if best else None


# ------------------------------------------------------------------ in and out of the car

def in_car(s):
    return bool(s and s["driving"])


def near(pt, r):
    """the player (car) within r of pt now"""
    s = D.state()
    return bool(s and math.hypot(pt[0] - s["x"], pt[1] - s["y"]) < r)


def back_in(world, car=None, check=None):
    """out of the mission car (pulled out, bailed, a door try): back in it (the arrow is on it)"""
    s = D.wait_state()
    if in_car(s): return s
    _ev(f"out of the car at {s['x']:.1f},{s['y']:.1f}: back in")
    return DI.board(world, car, check=check)


def _drive_to(world, pt, until, check=None, budget=420, view_switch=None):
    """the fragile drive to a point (care caps by the car's health, as deliver_intact paces it)"""
    hp = DI.car_hp(); cap = DI._care_cap(hp)
    saved = (M.CARE_HP, M.CARE_CAP, M.SMOOTH_SLOW_CAP)
    try:
        if cap: M.SMOOTH_SLOW_CAP = cap; M.CARE_HP = 32001; M.CARE_CAP = cap
        M.CAR_AVOID.clear()
        return M.drive3(world, pt[0], pt[1], tol=0.9, budget=budget, view_switch=view_switch, slow=True,
                        precious=True, until=until)
    finally:
        M.CARE_HP, M.CARE_CAP, M.SMOOTH_SLOW_CAP = saved
        if check: check()


def stop_dead(secs=0.4):
    """keys off and a short brake: the script's boarding needs a car standing still"""
    DI.keys_off(); hold("space", secs); DI.keys_off()


# ------------------------------------------------------------------ the stop

def pickup(world, stop, msgs, car=None, check=None, view_switch=None, shops=None, budget=900):
    """the whole stop (module docstring). Returns 'aboard' or the job's end / a reason"""
    t0 = time.time()
    m0 = msgs.mark()

    def aboard():
        if stop.aboard_fn and stop.aboard_fn(): return True
        return bool(stop.aboard_keys) and msgs.since(stop.aboard_keys, m0)

    def horned():
        if stop.horned_fn and stop.horned_fn(): return True
        return bool(stop.horn_keys) and msgs.since(stop.horn_keys, m0)

    def told():
        """the script knows he is in the box: its horn brief since this stop began"""
        return msgs.since(SOUND_HORN, m0)

    def in_box():
        s = D.state()
        return bool(s and in_car(s) and M.inside_box(s, stop.x, stop.y, stop.w, stop.h))

    def ended():
        ms = M.mission_state() or {}
        if ms.get("msg") in M.COMPLETE_KEYS: return "complete"
        if ms.get("msg") in M.FAILED_KEYS: return "failed"
        return None

    s = D.wait_state()
    _ev(f"{stop.name}: box {stop.x},{stop.y} ({stop.w} x {stop.h}), he stands at {man_xy(stop)[0]:.1f},{man_xy(stop)[1]:.1f}; "
        f"car at {s['x']:.1f},{s['y']:.1f}, carhp {DI.car_hp()}, {math.hypot(stop.x - s['x'], stop.y - s['y']):.0f} blocks")
    tried = []; lost = 0
    # ---- 1. into the box, stopped at a stand point
    for leg in range(6):
        if check: check()
        if ended(): return ended()
        if aboard(): return "aboard"
        if time.time() - t0 > budget: return "timeout: the box not reached"
        s = back_in(world, car, check=check)
        if not in_car(s):
            lost += 1
            if lost >= 2: return "stuck: cannot get back into the mission car (burned or gone)"
            continue
        far = math.hypot(stop.x - s["x"], stop.y - s["y"])
        if stop.narrow:
            r = DI.deliver(world, stop.box, car=car, check=check, view_switch=view_switch, shops=shops,
                           budget=max(120, budget - (time.time() - t0)), tries=4, park_wait=0,
                           done=lambda: horned() or aboard() or in_box(), label=f"{stop.name}'s box")
            if r in ("complete", "failed", "dead"): return r
            stop_dead(); s = D.wait_state()
            if in_car(s) and (M.inside_box(s, stop.x, stop.y, stop.w, stop.h) or horned() or aboard()): break
            hold("Down", 0.8); continue
        if far > 14:
            # the long leg: deliver_intact's fragile drive (respray when the car is hurt and a shop
            # is near) to the box's edge on the side the car comes from
            sp = stand_point(world, stop, s) or (stop.x, stop.y)
            ap = (stop.x + (s["x"] - stop.x) / far * (max(stop.w, stop.h) / 2 + 3.0),
                  stop.y + (s["y"] - stop.y) / far * (max(stop.w, stop.h) / 2 + 3.0))
            r = DI.deliver(world, (ap[0], ap[1], 3.0, 3.0), car=car, check=check, view_switch=view_switch,
                           shops=shops, budget=max(120, budget - (time.time() - t0)), tries=3, park_wait=0,
                           done=lambda: told() or horned() or aboard() or near(ap, 4.0),
                           label=f"{stop.name}'s street")
            if r in ("complete", "failed", "dead"): return r
            continue
        sp = stand_point(world, stop, s, avoid=tried)
        if not sp:
            _ev(f"{stop.name}: no stand point in the box; the box centre's edge"); sp = (stop.x, stop.y + stop.h / 2 - BOX_MARGIN)
        _ev(f"{stop.name}: stand point {sp[0]:.1f},{sp[1]:.1f} ({math.hypot(sp[0] - man_xy(stop)[0], sp[1] - man_xy(stop)[1]):.1f} from him)")
        # the drive (the router knows the alley walls round a box), stopped when it wanders: sd_ccc2,
        # 4 blocks from Shady's box, stalled at once, re-routed 95 blocks round and pressed the Cop
        # Car on walls and traffic from 26283 to a fire
        d0 = math.hypot(stop.x - s["x"], stop.y - s["y"])
        def wandered():
            q = D.state()
            return bool(q) and math.hypot(stop.x - q["x"], stop.y - q["y"]) > max(d0 + WANDER, 8.0)
        s = _drive_to(world, sp, until=lambda: horned() or aboard() or (in_box() and near(sp, 1.2)) or wandered(),
                      check=check, budget=90, view_switch=view_switch)
        stop_dead()
        s = D.wait_state()
        if in_car(s) and (M.inside_box(s, stop.x, stop.y, stop.w, stop.h) or told() or horned()): break
        if in_car(s) and wandered(): _ev(f"{stop.name}: the drive wandered off to {s['x']:.1f},{s['y']:.1f}: stopped")
        if in_car(s) and math.hypot(stop.x - s["x"], stop.y - s["y"]) < CREEP_NEAR:
            # the last short way straight in (deliver_intact's pulses, no router): sd_ccc4 stopped
            # 0.04 outside the box edge and the six legs ran out in 4 s, each drive "arrived" at
            # once; the creep's target is the locate box itself (it handbrakes inside with a margin)
            s = DI.creep_into((stop.x, stop.y, stop.w, stop.h), secs=_scale(20),
                              done=lambda: horned() or aboard(), check=check)
            stop_dead(); s = D.wait_state()
            if in_car(s) and (M.inside_box(s, stop.x, stop.y, stop.w, stop.h) or told() or horned() or aboard()):
                _ev(f"{stop.name}: crept the last {math.hypot(stop.x - s['x'], stop.y - s['y']):.1f} into the box"); break
            _ev(f"{stop.name}: the creep missed (at {s['x']:.2f},{s['y']:.2f})")
        tried.append(sp)
    else:
        return "stuck: the box not reached"
    M.shot(f"horn_{stop.name}_box")
    _ev(f"{stop.name}: in the box at {s['x']:.1f},{s['y']:.1f} after {time.time() - t0:.0f}s (told {told()}, carhp {DI.car_hp()})")

    # ---- 2. the horn, until the script takes it
    t1 = time.time(); k = 0
    while not (horned() or aboard()):
        if check: check()
        if ended(): return ended()
        if time.time() - t1 > _scale(HORN_SECS) * 2:
            return f"stuck: the horn not taken ({msgs.last()})"
        s = D.wait_state()
        if not in_car(s):
            s = back_in(world, car, check=check); continue
        if not M.inside_box(s, stop.x, stop.y, stop.w, stop.h) and (stop.narrow or not told()):
            _ev(f"{stop.name}: out of the box at {s['x']:.1f},{s['y']:.1f}: in again")
            if stop.narrow:
                DI.deliver(world, stop.box, car=car, check=check, view_switch=view_switch, budget=120, tries=2,
                           park_wait=0, done=lambda: horned() or aboard() or in_box(), label=f"{stop.name}'s box")
            else:
                sp = stand_point(world, stop, s) or (stop.x, stop.y)
                _drive_to(world, sp, until=in_box, check=check, budget=40, view_switch=view_switch)
            stop_dead()
            continue
        if stop.need_box_brief and not told() and time.time() - t1 < 4:
            time.sleep(0.5); continue          # the script reads the box once a frame; give it a moment
        M.horn(1); k += 1
        time.sleep(0.8)
        if not stop.horn_keys and not stop.horned_fn and k >= 3: break   # nothing to wait for: three presses
    _ev(f"{stop.name}: horn taken after {k} presses ({msgs.last()})")
    DI.keys_off()
    time.sleep(1.0); M.shot(f"horn_{stop.name}_horn")

    # ---- 3. hands off while they board
    t2 = time.time(); best = 1e9; t_prog = time.time(); moves = 0; t_said = 0.0
    seen_ids = set()
    while not aboard():
        if check: check()
        if ended(): return ended()
        if time.time() - t2 > _scale(BOARD_SECS): return f"timeout: not aboard ({msgs.last()})"
        s = D.wait_state()
        if not in_car(s):
            s = back_in(world, car, check=check); stop_dead(); continue
        if stop.narrow and not M.inside_box(s, stop.x, stop.y, stop.w, stop.h):
            _ev(f"{stop.name}: out of the box while they walk ({s['x']:.2f},{s['y']:.2f}): in again")
            DI.deliver(world, stop.box, car=car, check=check, view_switch=view_switch, budget=90, tries=2,
                       park_wait=0, done=lambda: aboard() or in_box(), label=f"{stop.name}'s box")
            stop_dead(); continue
        DI.keys_off()
        g = [p for p in group(stop, near=(s["x"], s["y"])) if p["car"] is None]
        g = [p for p in g if math.hypot(p["x"] - s["x"], p["y"] - s["y"]) < 14]
        for p in g: seen_ids.add(p["id"])
        if g:
            far = max(math.hypot(p["x"] - s["x"], p["y"] - s["y"]) for p in g)
            tot = sum(math.hypot(p["x"] - s["x"], p["y"] - s["y"]) for p in g)
            now = time.time()
            if tot < best - STALL_GAIN: best = tot; t_prog = now
            if now - t_said > _scale(8):
                say(f"horn: {stop.name}: {len(g)} on foot, farthest {far:.1f} from the car, states "
                    f"{' '.join(f'{p['state']}:{p['sub']}' for p in g[:6])}"); t_said = now
            if stop.move and now - t_prog > _scale(STALL_SECS) and moves < MOVES and far > 2.5:
                # they do not come: another stand point round him (the car may block their path, or
                # stand where the door is against a wall)
                moves += 1
                tried.append((s["x"], s["y"]))
                sp = stand_point(world, stop, s, avoid=tried) or stand_point(world, stop, s, avoid=tried, lo=1.6, hi=5.5)
                if sp:
                    _ev(f"{stop.name}: no progress for {now - t_prog:.0f}s ({len(g)} on foot, farthest {far:.1f}): car to {sp[0]:.1f},{sp[1]:.1f}")
                    saved = M.SMOOTH_SLOW_CAP; M.SMOOTH_SLOW_CAP = min(saved, 1.6)
                    try:
                        M.CAR_AVOID.clear()
                        M.drive3(world, sp[0], sp[1], tol=0.8, budget=30, view_switch=view_switch, slow=True, precious=True,
                                 until=aboard)
                    finally:
                        M.SMOOTH_SLOW_CAP = saved
                    stop_dead()
                best = 1e9; t_prog = time.time()
        time.sleep(0.6)
    _ev(f"{stop.name}: aboard after {time.time() - t2:.0f}s ({len(seen_ids)} seen walking; {msgs.last()}; carhp {DI.car_hp()})")
    time.sleep(0.8); M.shot(f"horn_{stop.name}_aboard")
    return "aboard"


def pickups(world, stops, msgs, car=None, check=None, view_switch=None, shops=None, on_stop=None):
    """every stop in turn; (n done, last answer)"""
    for i, st in enumerate(stops):
        r = pickup(world, st, msgs, car=car, check=check, view_switch=view_switch, shops=shops)
        if r != "aboard": return i, r
        if on_stop: on_stop(i, st)
    return len(stops), "aboard"


# ------------------------------------------------------------------ the drop-off

def walk_clear(world, dist=7.0, away=None, secs=12):
    """on foot: to a street point dist blocks off (away from `away` when given)"""
    s = D.wait_state()
    if away:
        dx, dy = s["x"] - away[0], s["y"] - away[1]; n = math.hypot(dx, dy) or 1.0
        tx, ty = s["x"] + dx / n * dist, s["y"] + dy / n * dist
        c = M.street_cell_near(world, tx, ty, radius=6)
        if c: tx, ty = c[0], c[1]
    else:
        tx, ty = M.escape_point(world, s["x"], s["y"], 1, dist=dist)
    _ev(f"clear of the car: to {tx:.1f},{ty:.1f}")
    return M.walk3(world, tx, ty, tol=1.0, budget=secs)


def drop_off(world, box, msgs, car=None, check=None, view_switch=None, shops=None, arrived_keys=(),
             get_out=False, clear=7.0, budget=900, label="the drop-off"):
    """deliver_intact into box; done when one of arrived_keys shows (or deliver's own test). get_out:
    out of the car and clear of it once there. Returns deliver's answer"""
    m0 = msgs.mark()
    done = (lambda: msgs.since(arrived_keys, m0)) if arrived_keys else None
    r = DI.deliver(world, box, car=car, done=done, check=check, view_switch=view_switch, shops=shops,
                   budget=budget, park_wait=0 if get_out else 45, label=label)
    _ev(f"{label}: {r} ({msgs.last()}; carhp {DI.car_hp()})")
    if r == "delivered" and get_out:
        DI.keys_off(); M.shot("horn_dropoff")
        s = M.leave_car()
        walk_clear(world, dist=clear, away=(box[0], box[1]))
    return r
