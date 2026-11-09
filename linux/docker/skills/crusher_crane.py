#!/usr/bin/env python3
"""Skill: CRUSHER AND CRANE (Wave M, SKILL-CRUSHER; 9 jobs in docs/missions-catalogue.md).

What the scripts ask (assets-src/missions/*.mis): the mission car driven into the crane's yard
(`LOCATE_CHARACTER_BY_CAR` round the yard, or `IS_CHARACTER_IN_MODEL` + a box round the crane's
tower), the player out of it ("Get out ... and let the crane take over"), then the crane lifts it
into the crusher: `IS_CAR_CRUSHED (car)` (COP CAR CRUSH), `GET_CAR_INFO_FROM_CRANE (car, crane)`
(COP CAR SCRAP, the Krishna crane pair), or the car dropped at a crane's SECOND point (SINK OR
SWIM, RUSSIAN SAILORS: a crane with no crusher drops it in the water).

The district files declare every crane (`CRANE_DATA name = (tower x, y) rot  homecrane  FIRST
(x, y) rot`) and crusher (`CRUSHER name = (x, y)`). A crusher is a raised 3 x 3 platform no car
can climb (pt4_wil11 pressed the Cop Car against it with nothing happening). The crane lifts a car
standing under its HOOK, which hangs `HOOK_R` (2.5) blocks from the tower along the crane's own
rotation: Downtown crane1 (174.5,11.5, rot 270) took the Cop Car parked at 177.0,11.5 within 10 s
of the player stepping out (pt4_wil15). Angles as the game uses them for this table: 0 north
(-y), 90 west, 180 south (+y), 270 east (+x), so the hook is tower + R * (-sin r, -cos r).

What lost the step before this module (the shared `mission_play_wil.run_plan` crusher branch): a
`drive3(tol=0.7)` straight at the hook point inside the walled yard, which pressed the car along
the yard's walls (rf4: the Cop Car from carhp 22000 to alight at 175-185 x 14-16). Here:

  * `hook_point(crane)` and `lane(world, hook)`: the hook cell, and the straight open lane into it
    (the longest run of flat ground cells at the hook's level along one of the four axes, the
    crusher and the tower excluded); the approach point is LANE_BACK blocks out along it.
  * `crush(world, crane, ...)`: the whole step. The fragile drive (`deliver_intact.deliver`, with
    its respray and care caps) to the approach point only; then a straight creep up the lane to the
    hook with short pulses, aborted on damage (CREEP_HP_DROP) or no progress; handbrake; out; a walk
    back down the lane (clear of the hook and the crusher); hands off while the crane works, the
    car followed in `view: cars` (its z rises when the hook takes it: 'lifted'). Not taken in
    TAKE_SECS: back in, the next candidate hook point (tower + R +- 0.5, +-20 degrees).
  * `crane_near(district, x, y)` picks the crane for a box from the table below.

Returns "crushed" (the game reacted: done(), the car gone, or the job's end message), "complete",
"failed", "dead", or "stuck: ...". Marks `crusher: ...` in /out/marks.txt and EVENTS; frames
m_<prefix>_hook.png, _out.png, _lifted.png, _crushed.png (chase view when a view hook is set).
"""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
from skills import deliver_intact as DI

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

HOOK_R = 2.5          # blocks from the tower to the hook (pt4_wil15: 174.5 -> 177.0)
LANE_BACK = 4.5       # the approach point, blocks out along the lane from the hook
LANE_MAX = 7          # cells of lane looked at
CREEP_HP_DROP = 1500  # carhp lost during the creep that stops it (a wall)
CREEP_SECS = 40.0     # game seconds of creeping per try
TAKE_SECS = 35.0      # game seconds to wait for the crane after stepping out
HOOK_TOL = 0.55       # the car's centre this near the hook counts as under it
EVENTS = []

# district -> crane name -> (tower x, y, rot, first point or None, crusher at first point)
CRANES = {
    "wil": {"crane1": (174.5, 11.5, 270, (176.5, 9.5), True),
            "crane3": (246.5, 241.5, 90, (244.5, 243.5), True)},
    "bil": {"crane1": (10.5, 149.5, 200, (12.5, 151.5), True),
            "crane3": (173.5, 27.5, 170, (171.5, 25.5), True),
            "crane5": (176.5, 249.5, 200, (178.5, 247.5), True),
            "crane7": (135.5, 5.5, 290, (135.5, 8.5), False),
            "crane8": (13.5, 211.5, 105, None, False)},
    "ste": {"crane1": (4.5, 72.5, 200, (5.5, 75.5), True),
            "crane3": (240.5, 69.5, 170, (240.5, 66.5), True),
            "crane5": (191.5, 228.5, 200, (193.5, 226.5), True),
            "crane7": (250.5, 39.5, 90, None, False),
            "crane8": (197.5, 245.5, 200, (197.5, 248.5), False),
            "crane9": (55.5, 48.5, 90, None, False),
            "crane10": (234.5, 153.5, 0, None, False)},
}
# verified hook points (seen taking a car in game), tried first
KNOWN_HOOK = {("wil", "crane1"): (177.0, 11.5)}


def _ev(what):
    EVENTS.append((time.time(), what)); M.mark(f"crusher: {what}")


def _scale(secs):
    return secs / max(1.0, getattr(D, "SPEED", 1.0))


class Clock:
    """wall seconds that skip a pause: the CPU governor freezes the whole container (this script
    with it) when the host's load passes 20, and the wall clock jumps by the pause (ccc1 lost its
    phone climb to a 16-minute pause after 17 game seconds). Each tick counts at most MAX_TICK s."""
    MAX_TICK = 3.0

    def __init__(self):
        self.t = time.time(); self.acc = 0.0

    def __call__(self):
        now = time.time(); self.acc += min(max(0.0, now - self.t), self.MAX_TICK); self.t = now
        return self.acc


def crane_near(district, x, y):
    """(name, crane) of the crane whose tower is nearest (x, y)"""
    best = None
    for name, c in CRANES.get(district, {}).items():
        d = math.hypot(c[0] - x, c[1] - y)
        if best is None or d < best[0]: best = (d, name, c)
    return (best[1], best[2]) if best else (None, None)


def hook_point(crane, r=HOOK_R, dang=0.0):
    tx, ty, rot = crane[0], crane[1], math.radians(crane[2] + dang)
    return (tx - r * math.sin(rot), ty - r * math.cos(rot))


def _flat(world, x, y, level):
    """flat ground at `level` with nothing built above it: node_kind alone passes the Downtown yard's
    gate posts and fence (row 16, lids at level 3 with air-typed tops), the highest lid does not"""
    cx, cy = int(math.floor(x)), int(math.floor(y))
    nk = M.node_kind(world, cx, cy, level)
    return bool(nk and nk[0] == "flat") and M.top_level(world, cx, cy) <= level + 1


def ground_level(world, x, y, prefer=None):
    """the level of the flat ground under (x, y): `prefer` when that is flat, else the lowest"""
    if prefer is not None and _flat(world, x, y, prefer): return prefer
    for L in range(0, 6):
        if _flat(world, x, y, L): return L
    return None


def _banned(crane, cx, cy):
    """the tower cell and the crusher platform (3 x 3 about the FIRST point when it is a crusher)"""
    if (cx, cy) == (int(crane[0]), int(crane[1])): return True
    if crane[3] and crane[4] and abs(cx - int(crane[3][0])) <= 1 and abs(cy - int(crane[3][1])) <= 1: return True
    return False


def lane(world, crane, hook, level):
    """((dx, dy), n): the axis along which the most flat cells at `level` lead straight out of the
    hook's cell (the car creeps in along it); None when the hook cell itself is not flat ground"""
    hx, hy = int(math.floor(hook[0])), int(math.floor(hook[1]))
    if not _flat(world, hx, hy, level) or _banned(crane, hx, hy): return None
    best = None
    for d in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        n = 0
        for k in range(1, LANE_MAX + 1):
            cx, cy = hx + d[0] * k, hy + d[1] * k
            if _banned(crane, cx, cy) or not _flat(world, cx, cy, level): break
            # the lane is a car's width: the cells either side need not be open, but one of them must
            n += 1
        if best is None or n > best[1]: best = (d, n)
    return best


def lane_offset(world, crane, hook, d, n, level, reach=3):
    """sideways shift (in blocks, along (-dy, dx)) that centres the car in the lane's narrowest
    row: ccc3/ccc4's first creeps scraped the yard gate (cells 177-178 on row 16, gate centre
    178.0) from a mouth at 177.5 and aborted on damage"""
    hx, hy = int(math.floor(hook[0])), int(math.floor(hook[1]))
    px, py = -d[1], d[0]
    best = None
    for k in range(1, n + 1):
        cx, cy = hx + d[0] * k, hy + d[1] * k
        lo = hi = 0
        while lo > -reach and _flat(world, cx + px * (lo - 1), cy + py * (lo - 1), level) and not _banned(crane, cx + px * (lo - 1), cy + py * (lo - 1)): lo -= 1
        while hi < reach and _flat(world, cx + px * (hi + 1), cy + py * (hi + 1), level) and not _banned(crane, cx + px * (hi + 1), cy + py * (hi + 1)): hi += 1
        w = hi - lo
        if best is None or w < best[0]: best = (w, (lo + hi) / 2.0)
    return best[1] if best else 0.0


def candidates(world, district, name, crane, level_hint=None):
    """[(hook x, y, level, lane dir, lane length)], best first"""
    pts = []
    if (district, name) in KNOWN_HOOK: pts.append(KNOWN_HOOK[(district, name)])
    for r, da in ((HOOK_R, 0), (HOOK_R + 0.5, 0), (HOOK_R - 0.5, 0), (HOOK_R, 20), (HOOK_R, -20)):
        pts.append(hook_point(crane, r, da))
    out = []
    for p in pts:
        L = ground_level(world, p[0], p[1], level_hint)
        if L is None: continue
        ln = lane(world, crane, p, L)
        if not ln or ln[1] < 2: continue
        if any(math.hypot(p[0] - q[0], p[1] - q[1]) < 0.4 for q in out): continue
        out.append((p[0], p[1], L, ln[0], ln[1]))
    return out


def car_near(x, y, r=2.0, model=None):
    best = None
    for c in M.cars():
        if model is not None and c["model"] != model: continue
        d = math.hypot(c["x"] - x, c["y"] - y)
        if d <= r and (best is None or d < best[0]): best = (d, c)
    return best[1] if best else None


def car_by_id(cid):
    return next((c for c in M.cars() if c["id"] == cid), None)


def _ended():
    ms = M.mission_state() or {}
    if ms.get("msg") in M.COMPLETE_KEYS: return "complete"
    if ms.get("msg") in M.FAILED_KEYS: return "failed"
    if ms.get("health", 1) == 0 or ms.get("death", 0) != 0: return "dead"
    return None


def creep_lane(hook, d, secs=CREEP_SECS, check=None, done=None):
    """straight up the lane to the hook with short pulses (the nose kept on the hook), stopped
    under it with the handbrake. Returns (state, why): 'under', 'damage', 'stalled', 'time', 'out'"""
    clk = Clock(); hp0 = DI.car_hp(); last = None; still = 0; k = 0; last_hp = [hp0]
    while clk() < _scale(secs):
        s = D.wait_state()
        if not s or not s["driving"]: return s, "out"
        if check: check()
        if done and done(): return s, "done"
        dist = math.hypot(hook[0] - s["x"], hook[1] - s["y"])
        # along the lane: how far short of / past the hook
        along = (s["x"] - hook[0]) * d[0] + (s["y"] - hook[1]) * d[1]
        if dist < HOOK_TOL or (abs(along) < 0.35 and dist < HOOK_TOL + 0.3):
            DI.keys_off(); hold("space", 0.8); hold("Down", 0.12); time.sleep(0.5)
            s2 = D.wait_state()
            if s2 and math.hypot(hook[0] - s2["x"], hook[1] - s2["y"]) < HOOK_TOL + 0.25: return s2, "under"
            continue
        hp = DI.car_hp()
        if M.car_burning():
            # alight: the car loses health by itself (ccc3: 16336 -> 14810 in 9 s of creeping, an abort
            # 5 blocks short); only a crash-sized step counts, and the hook is the quickest way out
            hp0 = max(hp0, hp) if hp0 < 0 else hp0
            if last_hp[0] >= 0 and last_hp[0] - hp > CREEP_HP_DROP: return s, "damage"
        elif hp0 >= 0 and hp >= 0 and hp0 - hp > CREEP_HP_DROP: return s, "damage"
        last_hp[0] = hp
        if along < -0.3:
            # past the hook (rolled on toward the tower): back straight down the lane
            hold("Down", 0.25); time.sleep(0.4); continue
        hx, hy = M.heading(s); dx, dy = hook[0] - s["x"], hook[1] - s["y"]
        a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
        if abs(a) > 0.6 and dist > 0.8:
            # nose off the hook: reverse with the wheel the other way (both swing the nose round)
            xdo("keydown", "Down"); xdo("keydown", "Left" if a > 0 else "Right"); time.sleep(0.5)
            xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right"); time.sleep(0.3)
            continue
        if abs(a) > 0.1: xdo("keydown", "Right" if a > 0 else "Left")
        pulse = 0.18 if dist < 2.0 else 0.28
        xdo("keydown", "Up"); time.sleep(pulse); xdo("keyup", "Up"); xdo("keyup", "Right"); xdo("keyup", "Left")
        hold("space", 0.15); time.sleep(0.35); k += 1
        if last and math.hypot(s["x"] - last[0], s["y"] - last[1]) < 0.05: still += 1
        else: still = 0
        last = (s["x"], s["y"])
        if still >= 6: return s, "stalled"
    return D.wait_state(), "time"


PIN_DROP = 2000       # carhp lost within PIN_SECS while standing: pinned (pressing a car / wall, or shot)
PIN_SECS = 3.0
PIN_V = 0.6           # blocks moved within PIN_SECS that count as standing


class PinWatch:
    """ccc2: drive3 pushed the Cop Car into a stopped Bug at 144.1,35.4 (v 0) for six seconds, carhp
    -1300 a second, from 26550 to alight. A car that stands still while its health falls that fast
    breaks out of the drive (deliver's done()), backs off and drives on"""

    def __init__(self):
        self.hist = []; self.clk = Clock(); self.pinned = 0

    def __call__(self):
        s = D.state(); hp = DI.car_hp()
        if not (s and s["driving"]) or hp < 0: return False
        t = self.clk(); self.hist.append((t, hp, s["x"], s["y"]))
        while self.hist and t - self.hist[0][0] > _scale(PIN_SECS): self.hist.pop(0)
        if len(self.hist) < 3: return False
        t0, hp0, x0, y0 = self.hist[0]
        if hp0 - hp > PIN_DROP and math.hypot(s["x"] - x0, s["y"] - y0) < PIN_V:
            self.hist.clear(); return True
        return False


def unpin(s):
    """back off (wheel the other way) then forward a little: out of a car/wall contact"""
    DI.keys_off()
    xdo("keydown", "Down"); xdo("keydown", "Left"); time.sleep(0.7)
    xdo("keyup", "Left"); time.sleep(0.4); xdo("keyup", "Down")
    hold("space", 0.2); DI.keys_off()


def _approach(world, ap, car=None, check=None, view_switch=None, budget=600, shops=None, rounds=6):
    """the fragile drive to the lane's mouth (deliver_intact with its respray and care caps),
    broken off and resumed whenever the car is pinned (PinWatch)"""
    pin = PinWatch()
    clk = Clock()

    def there():
        s = D.state()
        return bool(s and s["driving"] and math.hypot(ap[0] - s["x"], ap[1] - s["y"]) < 1.6)

    pinned = [False]

    def done():
        if there() or pinned[0]: return True          # latched: deliver re-asks after drive3 returns
        if pin(): pinned[0] = True; return True
        return False

    r = "stuck: no drive"
    for k in range(rounds):
        pinned[0] = False
        r = DI.deliver(world, (ap[0], ap[1], 2.0, 2.0), car=car, approach=None, done=done, check=check,
                       view_switch=view_switch, shops=shops, budget=max(60, budget - clk()), park_wait=0, tries=4,
                       label="the crane lane")
        if r in ("complete", "failed", "dead") or there(): return r
        if not pinned[0]: return r
        s = D.wait_state()
        _ev(f"pinned at {s['x']:.1f},{s['y']:.1f} (carhp {DI.car_hp()}): backing off, on again")
        unpin(s)
    return r


def crush(world, district, crane_name=None, near=None, car=None, done=None, check=None, view_switch=None,
          budget=900, shops=None, shot_prefix="crusher", chase=None, tries=3):
    """the whole crane step (module docstring). near: (x, y) to pick the crane by when no name;
    done(): the job's own 'the crane has it' test; chase(): puts the view in the chase camera for
    the frames; check(): the job's failure guard (raises)."""
    if crane_name is None:
        crane_name, crane = crane_near(district, *(near or (D.wait_state()["x"], D.wait_state()["y"])))
    else:
        crane = CRANES[district][crane_name]
    if not crane: return "stuck: no crane"
    s = D.wait_state()
    cands = candidates(world, district, crane_name, crane, level_hint=M.ped_level(s) if s else None)
    if not cands: return "stuck: no hook point with an open lane"
    _ev(f"{district} {crane_name} tower {crane[0]},{crane[1]} rot {crane[2]}: hook candidates "
        + "; ".join(f"{c[0]:.1f},{c[1]:.1f} L{c[2]} lane {c[3]}x{c[4]}" for c in cands))
    t0 = time.time()

    def reacted():
        if done and done(): return True
        return _ended() is not None

    def shot(tag):
        if chase:
            try: chase()
            except Exception: pass
        M.shot(f"{shot_prefix}_{tag}")

    for i, (hx, hy, L, d, n) in enumerate(cands[:tries]):
        if time.time() - t0 > budget: break
        if check: check()
        if reacted(): break
        back = min(LANE_BACK, n - 0.5)
        off = lane_offset(world, crane, (hx, hy), d, n, L)
        px, py = -d[1], d[0]
        ap = (math.floor(hx) + 0.5 + d[0] * back + px * off, math.floor(hy) + 0.5 + d[1] * back + py * off)
        hook = (hx, hy)
        _ev(f"try {i + 1}: hook {hx:.1f},{hy:.1f}, lane mouth {ap[0]:.1f},{ap[1]:.1f} (carhp {DI.car_hp()})")
        s = D.wait_state()
        if not (s and s["driving"]):
            s = DI.board(world, car, check=check)
            if not (s and s["driving"]): return _ended() or "stuck: not in the car"
        if math.hypot(ap[0] - s["x"], ap[1] - s["y"]) > 1.6 and math.hypot(hook[0] - s["x"], hook[1] - s["y"]) > 2.5:
            r = _approach(world, ap, car=car, check=check, view_switch=view_switch,
                          budget=max(120, budget - (time.time() - t0)), shops=shops)
            if r in ("complete", "failed", "dead"): return r
            s = D.wait_state()
            if not (s and s["driving"]): continue
            if math.hypot(ap[0] - s["x"], ap[1] - s["y"]) > 3.0:
                _ev(f"the lane mouth not reached ({r}; at {s['x']:.1f},{s['y']:.1f})"); continue
        if reacted(): break
        s, why = creep_lane(hook, d, check=check, done=done)
        _ev(f"creep: {why} at {s['x']:.2f},{s['y']:.2f} ({math.hypot(hook[0] - s['x'], hook[1] - s['y']):.2f} from the hook, carhp {DI.car_hp()})" if s else f"creep: {why}")
        if why == "out" or not s: continue
        if why in ("damage", "stalled") and math.hypot(hook[0] - s["x"], hook[1] - s["y"]) > 1.4:
            hold("Down", 0.9); continue
        shot("hook")
        cmodel = (M.mission_state() or {}).get("carmodel")
        DI.keys_off(); hold("space", 0.5)
        s = M.leave_car()
        if s and s["driving"]: s = M.leave_car()
        lc = car_near(hook[0], hook[1], r=2.2, model=cmodel if cmodel and cmodel > 0 else None) or car_near(hook[0], hook[1], r=2.2)
        cid = lc["id"] if lc else None
        z0 = lc["z"] if lc else None
        _ev(f"out of the car under the hook (car id {cid} at {lc['x']:.2f},{lc['y']:.2f} z {lc['z']:.2f})" if lc else "out of the car (car not seen in view: cars)")
        # clear of the hook: back down the lane, past its mouth
        cx = math.floor(hx) + 0.5 + d[0] * min(n, LANE_BACK + 2.0)
        cy = math.floor(hy) + 0.5 + d[1] * min(n, LANE_BACK + 2.0)
        M.walk3(world, cx, cy, L, tol=0.8, budget=_scale(14))
        shot("out")
        clk = Clock(); lifted = False; gone_since = None
        while clk() < _scale(TAKE_SECS):
            if check:
                try: check()
                except Exception:
                    # the job's end (ccc4: the runner's check raised on 1689 before the frame): the
                    # frame of the crusher first, then the job's answer
                    shot("crushed"); _ev(f"the job ended while the crane worked (lifted seen: {lifted})")
                    raise
            if reacted(): break
            c = car_by_id(cid) if cid is not None else None
            if c and z0 is not None and c["z"] > z0 + 0.4 and not lifted:
                lifted = True; _ev(f"lifted: the car at z {c['z']:.2f} ({c['x']:.1f},{c['y']:.1f})"); shot("lifted")
            if cid is not None and c is None:
                if gone_since is None:
                    gone_since = time.time(); _ev("the car is gone from view: cars (crushed or carried off)")
            s = D.wait_state()
            if s and s["driving"]:
                _ev("back in a car while waiting (the game put him in?): out again"); M.leave_car()
            time.sleep(0.5)
        if reacted() or gone_since:
            # the job's end follows the crusher by a few seconds
            clk = Clock()
            while clk() < _scale(15) and not reacted(): time.sleep(0.5)
            shot("crushed")
            _ev(f"crane took the car (lifted seen: {lifted}; {time.time() - t0:.0f}s; outcome {_ended()})")
            return _ended() or "crushed"
        _ev(f"not taken in {TAKE_SECS:.0f} game-s at {hx:.1f},{hy:.1f}: back in, next hook point")
        M.mark(f"crusher: hook point {hx:.1f},{hy:.1f} did nothing")
        s = DI.board(world, car or (hx, hy), check=check)
        if s and s["driving"]: hold("Down", 0.8)
    return _ended() or "stuck: the crane did not take the car"


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--survey":
    # host side, no game: the hook candidates and lanes for every crane
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    game = sys.argv[2] if len(sys.argv) > 2 else "/mnt/gta2/gta2-linux/game"
    M.GAME_DIR = game
    for dist in CRANES:
        class W: pass
        w = W(); w.district = dist
        import gmp
        w.blocks, w.columns = gmp.load(f"{game}/data/{dist}.gmp")
        for name, c in CRANES[dist].items():
            cs = candidates(w, dist, name, c)
            print(dist, name, c[:3], "->", [(round(x, 1), round(y, 1), L, d, n, lane_offset(w, c, (x, y), d, n, L)) for x, y, L, d, n in cs] or "NONE")
