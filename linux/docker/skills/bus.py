#!/usr/bin/env python3
"""Skill: BUS (Wave M, SKILL-BUS; catalogue skill `bus`, 4 jobs).

The four jobs (docs/missions-catalogue.md): bil_re1 HOT DOG HOMICIDE! (any BUS from traffic, filled
twice at bus stops: `IS_BUS_FULL (p1)` then `KILL_ALL_PASSENGERS`, into the meat plant's garage),
ste_se2 FAKE TRUCE! (the Factory Bus, four horn pick-ups: skills/horn_pickup.py does the stops),
bil_km3 CONVERSION EVASION! and bil_zm3 GANG WAR! (a Krishna Karma Bus, KRSNABUS, stolen and driven:
passengers by the horn, or 50 Russians run over). What they share and this module does:

  * finding a bus: none is parked in either district's script; `get_bus` takes a standing or passing
    one with skills/steal_car (the model enum: BUS 11, KRSNABUS by name), or walks into a mission bus;
  * driving it: a bus is 2.4 blocks long and turns wide; the shared smooth driver clips kerbs and
    burns it (FAKE TRUCE ft1). `bus_drive` is calm_drive (missions/russian_sailors.py: no blind
    reversing, waits in queues) with a smooth-driver burst when it makes no progress for 20 game s;
  * bus stops: the map's ZONE chunk type 7 (`busstop1..4` in bil, `bus_stop01..07` in ste), one
    pavement cell each. `stop_point` is the road cell beside it on the near lane; `serve_stop` pulls
    in slowly, stops with the doors at the stop and waits while people board (peds whose car is the
    bus, from the renderer's `view: peds` line, and the money: the game pays per passenger);
  * `fill(world, full)`: stop after stop (nearest first, never the same one twice running) until
    `full()` says the script took the load (IS_BUS_FULL has no brief of its own on the first load:
    the runner passes a test such as "the passengers vanished" or the next brief).
Every step marks /out/marks.txt with "bus: ..." and appends to EVENTS.
"""
import math, os, struct, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

BUS_MODELS = {11}
# where buses were taken in the runs (hd2, hd3, hd4, hd6: 109,53 / 100,53 / 96,53 / 95,53 within 2-3 min
# of the tour reaching busstop1; hd8 toured the other stops for 17 minutes and saw none)
BUS_SEARCH_FIRST = {"bil": "busstop1"}                 # BUS; KRSNABUS is not in the published 0-84 enum the logs confirm
EVENTS = []
STATS = {"stops": 0, "boarded": 0, "money": 0, "bursts": 0, "dwell_s": 0.0}
GAME_DIR = os.environ.get("GAME_DIR", "/game")


def ev(what):
    EVENTS.append((time.time(), what)); M.mark(f"bus: {what}"); say(f"bus: {what}")


# ------------------------------------------------------------------ bus stops from the map

def bus_stops(district):
    """[(name, x, y)] the map's bus-stop zones (ZONE chunk type 7), cell centres"""
    path = f"{GAME_DIR}/data/{district}.gmp"
    data = open(path, "rb").read(); off = 6; ch = {}
    while off + 8 <= len(data):
        tag = data[off:off + 4]; size = struct.unpack_from("<I", data, off + 4)[0]
        ch[tag.decode("latin1")] = (off + 8, size); off += 8 + size
    o, sz = ch["ZONE"]; z = data[o:o + sz]; p = 0; out = []
    while p + 6 <= len(z):
        t, x, y, w, h, nl = struct.unpack_from("<6B", z, p); name = z[p + 6:p + 6 + nl].decode("latin1"); p += 6 + nl
        if t == 7: out.append((name, x + w / 2.0, y + h / 2.0))
    return out


def stop_point(world, stop):
    """(x, y, (dx, dy)): the road cell beside the stop's pavement cell where the bus stands, and the
    direction of travel along the kerb (traffic keeps right: the stop is on the bus's right side)"""
    name, sx, sy = stop
    cx, cy = int(sx), int(sy)
    best = None
    for r in (1, 2):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            x, y = cx + dx * r, cy + dy * r
            for lvl in (1, 2):
                if M.walkable(world.blocks, world.columns, x, y, lvl, (1,)):
                    if best is None or r < best[0]: best = (r, x + 0.5, y + 0.5, dx, dy)
        if best: break
    if not best: return (sx, sy, (1, 0))
    r, x, y, dx, dy = best
    # the stop lies at (-dx,-dy) from the road cell; driving with it on the right: the travel
    # direction is the stop direction turned 90 degrees anticlockwise (y south)
    ox, oy = -dx, -dy
    tx, ty = oy, -ox
    return (x, y, (tx, ty))


# ------------------------------------------------------------------ the bus

def in_bus(s=None, models=None):
    s = s or D.wait_state()
    return bool(s and s["driving"] and s.get("cmodel", -1) in (models or BUS_MODELS))


def get_bus(world, models=None, budget=900, check=None, drive=None, search=None):
    """into a bus: skills/steal_car on the bus models (standing ones walked to, passing ones
    ambushed, a tour of `search` points when none is in sight)"""
    s = D.wait_state()
    if in_bus(s, models): return s
    from skills import steal_car as SC
    if search is None:
        # buses run between the bus stops (hd1: 10 minutes of a random tour in Industrial saw none;
        # the two buses in the pt9 logs were 8 blocks from busstop1 and near busstop3): the tour is
        # the road cells beside the stops, nearest first
        stops = sorted(bus_stops(world.district), key=lambda st: math.hypot(st[1] - s["x"], st[2] - s["y"]))
        first = [n for n in os.environ.get("BUS_SEARCH_FIRST", BUS_SEARCH_FIRST.get(world.district, "")).split(",") if n]
        stops.sort(key=lambda st: first.index(st[0]) if st[0] in first else len(first))
        search = []
        for st in stops:
            x, y, (tx, ty) = stop_point(world, st)
            if st[0] in first:
                # a stretch of the route through the stop, both ways: buses pass here every few minutes
                # (hd9: once round the stretch, then the tour left for the far stops and lost the bus
                # it had seen: three rounds)
                for rep in range(3):
                    for d in (-14, 0, 14, 0):
                        c = M.street_cell_near(world, x + tx * d, y + ty * d, radius=3)
                        if c: search.append((c[0], c[1]))
            else:
                search.append((x, y))
        ev(f"bus search tour: {[st[0] for st in stops]}")
    ev(f"looking for a bus (models {sorted(models or BUS_MODELS)})")
    # hd7: steal_car spent 5+ minutes walking at a standing bus 3.5 blocks off that it could not
    # reach (another car at its doors). Short attempts; after a failed one the tour starts at the
    # next stop, away from that bus
    t0 = time.time(); k = 0; r = None
    while time.time() - t0 < budget:
        if check and check(): return D.wait_state()
        tour = search[k % len(search):] + search[:k % len(search)]
        r = SC.steal_car(world, sorted(models or BUS_MODELS), search=tour, budget=min(300, budget - (time.time() - t0)),
                         drive=drive, check=check)
        if r and in_bus(r, models):
            # hd10: "in a bus" for one sample mid-jack, then the bus drove off with its driver: confirm
            time.sleep(2.0)
            if in_bus(None, models): break
            ev("the bus was not kept (in it for a moment only)")
        k += 1
        s = D.wait_state()
        ev(f"no bus in this attempt (at {s['x']:.1f},{s['y']:.1f}); next tour from {tour[1 % len(tour)]}")
        if s["driving"] and not in_bus(s, models): pass
        nx, ny = tour[1 % len(tour)]
        if not s["driving"]:
            s = M.any_car2(world, budget=60)
        if s["driving"]:
            M.drive3(world, nx, ny, tol=4.0, budget=150)
    r = D.wait_state()
    if r and in_bus(r, models): ev(f"in a bus at {r['x']:.1f},{r['y']:.1f} (carhp {(M.mission_state() or {}).get('carhp')})")
    return r


SMOOTH = M.drive3
_CALM = [None]


def _calm():
    if _CALM[0] is None:
        try:
            import missions.russian_sailors as RS
            _CALM[0] = RS
        except Exception as e:
            say("bus: calm_drive not available", e); _CALM[0] = False
    return _CALM[0]


def bus_drive(world, tx, ty, tol=2.0, budget=240, view_switch=None, slow=False, precious=False, until=None,
              stall_s=30.0):
    """calm_drive with a smooth burst when it makes no 1.5 blocks of progress in `stall_s` game s"""
    RS = _calm()
    if not RS:
        return SMOOTH(world, tx, ty, tol=tol, budget=budget, view_switch=view_switch, slow=slow, precious=precious, until=until)
    RS.world = world
    t0 = time.time(); s = D.wait_state()
    while time.time() - t0 < budget:
        if not (s and s["driving"]): return s
        if math.hypot(tx - s["x"], ty - s["y"]) <= tol or (until and until()): return s
        hist = [(time.time(), s["x"], s["y"])]

        def stalled():
            if until and until(): return True
            q = D.state()
            if not q: return False
            now = time.time(); hist.append((now, q["x"], q["y"]))
            while len(hist) > 2 and now - hist[1][0] > stall_s / D.SPEED: hist.pop(0)
            if now - hist[0][0] < stall_s / D.SPEED: return False
            return max(math.hypot(q["x"] - h[1], q["y"] - h[2]) for h in hist) < 1.5

        s = RS.calm_drive(world, tx, ty, tol=tol, budget=max(20, budget - (time.time() - t0)), view_switch=view_switch,
                          slow=slow, precious=precious, until=stalled)
        if not (s and s["driving"]): return s
        if math.hypot(tx - s["x"], ty - s["y"]) <= tol or (until and until()): return s
        if time.time() - t0 >= budget: return s
        STATS["bursts"] += 1
        x0, y0 = s["x"], s["y"]
        M.mark(f"bus: calm stalled at {x0:.1f},{y0:.1f}: smooth burst {STATS['bursts']}")

        def away():
            q = D.state()
            return (until and until()) or bool(q and math.hypot(q["x"] - x0, q["y"] - y0) > 5.0)
        # hd4: a 25 s smooth burst out of a queue at a stop rammed the bus from 31000 to 13800 carhp:
        # bursts are short and slow, and stop at the first hit
        hp0 = (M.mission_state() or {}).get("carhp", 32000)

        def away_or_hit():
            hp = (M.mission_state() or {}).get("carhp", hp0)
            return away() or hp < hp0 - 1500
        s = SMOOTH(world, tx, ty, tol=tol, budget=12, view_switch=view_switch, slow=True, precious=True, until=away_or_hit)
    return s


# ------------------------------------------------------------------ passengers

def passengers(s=None, models=None):
    """peds the renderer lists inside a bus within 2.5 blocks of the player (the player may be one)"""
    s = s or D.wait_state()
    if not s: return 0
    ms = models or BUS_MODELS
    n = 0
    for p in M.peds():
        if p.get("car") in ms and math.hypot(p["x"] - s["x"], p["y"] - s["y"]) < 2.5:
            n += 1
    return n


def waiting_near(stop, r=3.0):
    """standing peds within r of the stop cell (people at the stop)"""
    _, x, y = stop
    return [p for p in M.peds() if p.get("car") is None and M.ped_alive(p) and math.hypot(p["x"] - x, p["y"] - y) < r]


# ------------------------------------------------------------------ serving a stop

def keys_off():
    for k in ("Up", "Down", "Left", "Right", "Control_L"): xdo("keyup", k)


def creep_to(x, y, secs=8.0):
    """short throttle pulses steered at (x,y) (a bus at walking pace), until within 0.5 or the time"""
    t0 = time.time()
    s = D.wait_state()
    while s and s["driving"] and time.time() - t0 < secs / D.SPEED * 1.5:
        d = math.hypot(x - s["x"], y - s["y"])
        if d < 0.5: break
        a = D.angle_to(dict(s, fx=s["chx"] or s["fx"], fy=s["chy"] or s["fy"]), x, y)
        if abs(a) > 1.6: break                       # behind: not worth a turn here
        xdo("keydown", "Up")
        if abs(a) > 0.08:
            key = "Right" if a > 0 else "Left"
            xdo("keydown", key); time.sleep(min(0.25, abs(a) * 0.5)); xdo("keyup", key)
        time.sleep(0.15); xdo("keyup", "Up"); time.sleep(0.25)
        s = D.wait_state()
    keys_off()
    return s


def serve_stop(world, stop, full=None, dwell=70.0, check=None, view_switch=None, drive=None, label=None):
    """drive to the stop's road cell (an approach point 5 blocks before it along the travel
    direction first), stop there, hold still while people board. Returns 'full', 'served'
    (dwell over), or 'short' (not reached)"""
    drive = drive or bus_drive
    x, y, (tx, ty) = stop_point(world, stop)
    tx_dir = (tx, ty)
    ax, ay = x - tx * 5.0, y - ty * 5.0
    cell = M.street_cell_near(world, ax, ay, radius=3)
    name = label or stop[0]
    s = D.wait_state()
    if cell and math.hypot(cell[0] - s["x"], cell[1] - s["y"]) > 3.0 and math.hypot(x - s["x"], y - s["y"]) > 6.0:
        s = drive(world, cell[0], cell[1], tol=2.5, budget=300, view_switch=view_switch, slow=True, precious=True,
                  until=(lambda: bool(full and full())))
        if full and full(): return "full"
    ox, oy = -tx_dir[1], tx_dir[0]          # towards the stop (right of the travel direction)
    # hd2-hd5: the lane driver ends a lane out from the kerb (in hd5 a whole lane between the bus and
    # the two people at the stop; nobody boarded in 70 s), and a creep at a point straight beside
    # the bus never steers (90 degrees off). So: the lane driver to 7 blocks short of the stop, then
    # a creep along the kerb line (0.45 in from the stop's road cell centre towards the stop) at
    # 4.5, 2.5 and 0 blocks short of where the people wait, a lane change at walking pace
    wx, wy = x, y
    wait = [p for p in M.peds() if p.get("occ") == 8 and math.hypot(p["x"] - stop[1], p["y"] - stop[2]) < 3.5]
    if wait:
        mx = sum(p["x"] for p in wait) / len(wait); my = sum(p["y"] for p in wait) / len(wait)
        along = max(-1.5, min(1.5, (mx - x) * tx_dir[0] + (my - y) * tx_dir[1]))
        wx, wy = x + tx_dir[0] * along, y + tx_dir[1] * along
    s = D.wait_state()
    lx, ly = wx - tx_dir[0] * 7.0, wy - tx_dir[1] * 7.0
    if math.hypot(lx - s["x"], ly - s["y"]) > 2.0 and (s["x"] - wx) * tx_dir[0] + (s["y"] - wy) * tx_dir[1] < -7.0:
        s = drive(world, lx, ly, tol=1.5, budget=90, view_switch=view_switch, slow=True, precious=True,
                  until=(lambda: bool(full and full())))
    for back in (4.5, 2.5, 0.0):
        kx, ky = wx + ox * 0.45 - tx_dir[0] * back, wy + oy * 0.45 - tx_dir[1] * back
        s = creep_to(kx, ky, secs=6)
    keys_off(); hold("space", 0.6)
    s = D.wait_state()
    d = math.hypot(x - s["x"], y - s["y"]) if s else 99
    if d > 3.5:
        ev(f"{name}: not reached ({d:.1f} blocks off)"); return "short"
    STATS["stops"] += 1
    ms0 = M.mission_state() or {}
    money0 = ms0.get("money", 0); n0 = passengers(s)
    wait = waiting_near(stop, 4.0)
    ev(f"{name}: stopped {d:.1f} from the stop at {x:.1f},{y:.1f}; {len(wait)} waiting, {n0} aboard, money {money0}")
    M.shot(f"bus_{name}")
    # hd6: the bus at the kerb beside the shelter for 70 s, nobody boarded; the only boarding seen
    # (hd2) came while the stalled driver stood by busstop1 sounding the horn at a queue. The horn:
    M.horn(2); horns = 1
    t0 = time.time(); last_gain = time.time(); best_n = n0; m_last = money0; nudged = False
    while time.time() - t0 < (dwell * 3) / D.SPEED:
        if check: check()
        if full and full():
            ev(f"{name}: full after {time.time() - t0:.0f}s"); return "full"
        s = D.wait_state()
        if not (s and s["driving"]): return "out"
        n = passengers(s); m = (M.mission_state() or {}).get("money", 0)
        if n > best_n or m > m_last:
            best_n = max(best_n, n); m_last = max(m, m_last); last_gain = time.time()
        if time.time() - last_gain > dwell / D.SPEED and time.time() - t0 > dwell / D.SPEED: break
        if time.time() - t0 > horns * 15 / D.SPEED and horns < 4:
            M.horn(1); horns += 1
        if not nudged and time.time() - t0 > (dwell / 2) / D.SPEED and best_n == n0 and m_last == money0:
            # nobody on at the kerb (hd6, hd9: people waiting a block off, no boarding in 70 s; the one
            # boarding seen, hd2, was with the bus a lane out): one lane out, 2 blocks on, wait again
            nudged = True
            wait = [p for p in M.peds() if p.get("occ") == 8 and math.hypot(p["x"] - s["x"], p["y"] - s["y"]) < 5]
            creep_to(s["x"] + tx_dir[0] * 2.5 - ox * 0.9, s["y"] + tx_dir[1] * 2.5 - oy * 0.9, secs=5)
            keys_off(); hold("space", 0.4); M.horn(1)
            q = D.wait_state()
            ev(f"{name}: {len(wait)} waiting; moved a lane out to {q['x']:.1f},{q['y']:.1f}")
            M.shot(f"bus_{name}_laneout")
        time.sleep(0.5)
    gained = best_n - n0; STATS["boarded"] += max(0, gained); STATS["money"] += max(0, m_last - money0)
    STATS["dwell_s"] += (time.time() - t0) * D.SPEED
    ev(f"{name}: left after {(time.time() - t0) * D.SPEED:.0f} game s ({horns} horns); aboard {best_n} (+{gained}), money +{m_last - money0}")
    return "served"


def fill(world, full, district=None, stops=None, check=None, view_switch=None, drive=None, budget=1200, order=None):
    """stop after stop until full(): the nearest stop not served last, `order` (names) first if given"""
    stops = stops or bus_stops(district or world.district)
    t0 = time.time(); last = None; served = {}
    while time.time() - t0 < budget:
        if full(): return "full"
        if check: check()
        s = D.wait_state()
        if not in_bus(s): return "out of the bus"
        cands = [st for st in stops if st[0] != last]
        if order:
            pref = [st for n in order for st in cands if st[0] == n and served.get(n, 0) == 0]
            if pref: cands = pref
        cands.sort(key=lambda st: (served.get(st[0], 0), math.hypot(st[1] - s["x"], st[2] - s["y"])))
        st = cands[0]
        r = serve_stop(world, st, full=full, check=check, view_switch=view_switch, drive=drive)
        served[st[0]] = served.get(st[0], 0) + 1; last = st[0]
        if r == "full": return "full"
        if r == "out": return "out of the bus"
    return "timeout"
