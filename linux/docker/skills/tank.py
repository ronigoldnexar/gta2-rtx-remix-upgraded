#!/usr/bin/env python3
"""Skill: the tank (Wave M, `tank`, 6 phone jobs and 6 kill frenzies in docs/missions-catalogue.md).

What the jobs ask of a tank (decompiled scripts, assets-src/missions):
  - get one: a parked tank (the kill frenzies' PARKED_CAR_DATA ... TANK: wil 226.5,238.5 z2 and
    3.5,164.5 z3; ste 13,83 z2 and 29,178 z3; bil 3,30 z3 and 72,219.5 z2; entering it starts the
    frenzy, THREAD_WAIT_FOR_CHAR_IN_CAR), a tank the job creates for the player (ste_rm3 at the
    army base 231.5,90.5; bil_zh1 15.5,195; bil_zh2 158,246), or an army tank in the street (six
    stars bring the army with tanks; a driven tank is jacked like any car);
  - drive it (to a garage or an RV: bil_zh1, bil_zh2, ste_rm3, `deliver_intact` does the parking);
  - fight with it: the cannon (fire key, the turret follows the hull unless turned) at people
    (wil_kf07 35 in 60 s, ste_kf01, bil_kf01) or cars (wil_kf08 20 in 60 s, ste_kf02, bil_kf02),
    or stop tanks the script sends (wil_yh2, bil_rm3, bil_km3: bulletproof tanks; a tank's shell
    is what hurts them).

    from skills import tank as TK
    s = TK.get_tank(world, spot=(3.5, 164.5, 2), budget=400, check=fn)   # parked, or None: nearest / jack
    r = TK.fight(world, kind="cars", count=20, secs=60, check=fn)       # "done", "time", "out", "stuck"
    s = TK.drive(world, x, y)                                           # mission_lib.drive3 with a tank

How it fights (measured in the probes tkp1-tkp3, gamerun/tank_probe.py):
  - the cannon fires ONE shell per press of the fire key (Control_L tapped); held, it fired
    nothing seen in tk1's whole minute. The shell flies along the barrel and bursts on the first
    thing it meets (a wall 4 blocks off in tkp3);
  - the turret stays on the hull's line: no key tried turned it standing (Left, Right, Z, X, Tab,
    Space+Left, fire+Left), and the hull itself turns only while it rolls (Up or Down held with
    the turn; reversing swaps the steering);
  - the entry is slow (up to 10 s seated under load) and ONE Return is pressed per try: a second
    Return during the entry takes the player out again, and a frenzy tank is locked against him
    once he has left it (CHANGE_CAR_LOCK LOCKOUT_PLAYER).
  1. the targets are `view: cars` (any car that is not ours, not a wreck, not a train) or
     `view: peds` (alive, on foot), within `reach` blocks on his level, scored by distance plus
     the turn they need; a marked target (arrow slot) wins over the others (`marked=True`);
  2. the target within `cone` of the nose: a tap, a step closer when far, a step back when it
     is closer than 1.8 blocks (the blast reaches the tank); otherwise a rolling turn at it;
  3. nothing in reach: drive3 toward the next roam point, stopping as soon as a target is in
     reach ahead (drive3's `until`);
  4. no motion for `stall` game seconds without a target on the nose: a reversing turn;
  5. a car counts as destroyed when its hp reaches 0 (or it starts burning, `burn=True`) after it
     was seen alive within reach; the game's own counter is not logged, so the count is ours; the
     kill frenzy's own result is the extra life (lives + 1).
With GTA2_DIRECT_KEYS=1 every frame is a chase-view one (drive3 takes the third-person view).
Frames /out/m_<prefix>_*.png; marks `tank: ...` in /out/marks.txt and in EVENTS.

Run on its own (already in a tank):
    python3 /work/skills/tank.py [cars|peds] [count] [secs]
"""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

TANK = 54                                  # vehicle +0x84, the script's TANK
WRECKS = set(range(72, 82))                # WRECK0..9
TRAINS = {59, 60, 61}
# every tank a script puts down: (x, y, level of the lid it stands on, what)
PARKED = {
    "wil": [(226.5, 238.5, 1, "wil_kf07 people"), (3.5, 164.5, 2, "wil_kf08 cars")],
    "ste": [(13.0, 83.0, 1, "ste_kf01 people"), (29.0, 178.0, 2, "ste_kf02 cars")],
    "bil": [(3.0, 30.0, 2, "bil_kf01 people"), (72.0, 219.5, 1, "bil_kf02 cars")],
}
EVENTS = []
STATS = {"shells": 0, "kills_seen": 0, "turns": 0, "roams": 0, "stalls": 0}


def ev(text):
    EVENTS.append((time.time(), text)); M.mark(f"tank: {text}")


def in_tank(s=None, ms=None):
    s = s or D.wait_state(); ms = ms or M.mission_state() or {}
    return bool(s and s["driving"] and ms.get("carmodel") == TANK)


def tanks(free_only=False):
    """the tanks in the 30-block cars window, nearest first (free_only: nobody at the wheel)"""
    return [c for c in M.cars() if c["model"] == TANK and c["hp"] > 0 and c["driver"] != "P"
            and (not free_only or c["driver"] == "-")]


def heading(s):
    """the hull's heading while driving (carhead), else the ped's facing"""
    if s.get("driving") and (s.get("chx") or s.get("chy")): return s["chx"], s["chy"]
    return s["fx"], s["fy"]


def angle_to(s, tx, ty):
    hx, hy = heading(s)
    dx, dy = tx - s["x"], ty - s["y"]; n = math.hypot(dx, dy)
    if n < 1e-3: return 0.0
    dx, dy = dx / n, dy / n
    return math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)


def release():
    for k in ("Control_L", "Up", "Down", "Left", "Right"): xdo("keyup", k)


# ------------------------------------------------------------------ getting one

ENTERING = (2, 3, 6)   # ped states walking to a door / getting in


def _enter(world, c_or_xy, check=None, budget=120):
    """walk to the tank and get in with ONE Return per try, then wait for the seat. A tank's entry
    takes up to 10 s under load (tkp2: Return at 02:33:37, seated 02:33:47); mission_lib.enter_car3
    polls 5 s and presses Return again, which took the player straight out of the seated tank
    (tkp1, tkp2: in, out 3 s later) and the frenzy's tank is locked against him once he has left it"""
    x, y = (c_or_xy["x"], c_or_xy["y"]) if isinstance(c_or_xy, dict) else c_or_xy[:2]
    t0 = time.time()
    s = M.walk3(world, x, y, None, tol=1.5, budget=max(30, budget * 0.6))
    for k in range(4):
        if check: check()
        s = D.wait_state()
        if s["driving"]: break
        if math.hypot(x - s["x"], y - s["y"]) > 1.6:
            s, _ = M.cruise_to(x, y, tol=1.3, secs=8)
        tap("Return", 0.3)
        t1 = time.time(); seen_entering = False
        while time.time() - t1 < 15.0:
            time.sleep(0.4); s = D.wait_state()
            if s["driving"]: break
            if s.get("state") in ENTERING: seen_entering = True
            elif time.time() - t1 > (6.0 if seen_entering else 3.5): break
        if s["driving"]: break
        ang = (k + 1) * 1.57
        M.cruise_to(x + 1.1 * math.cos(ang), y + 1.1 * math.sin(ang), tol=0.45, secs=8)
        if time.time() - t0 > budget: break
    if s and s["driving"]:
        # the mission line names the car a moment after the player line says driving
        for _ in range(16):
            if (M.mission_state() or {}).get("carmodel", -1) >= 0: break
            time.sleep(0.25)
    if s and s["driving"] and not in_tank(s):
        ev(f"in a model {(M.mission_state() or {}).get('carmodel')}, not a tank: out again")
        s = M.leave_car()
    return s


def get_tank(world, spot=None, budget=600, check=None, jack=True, search=None):
    """into a tank: the parked one at `spot` (x, y, level) when given, else the nearest free tank
    in sight, else (jack=True) any tank by the steal-car skill (army tanks drive at six stars).
    Returns the state when in a tank, else None"""
    t0 = time.time(); s = D.wait_state()
    if in_tank(s): return s
    if s and s["driving"]: s = M.leave_car()
    tries = 0
    while time.time() - t0 < budget and tries < 4:
        tries += 1
        if check: check()
        if spot:
            x, y, L = spot[:3]
            s = D.wait_state()
            d = math.hypot(x - s["x"], y - s["y"])
            ev(f"to the parked tank at {x},{y} (level {L}), {d:.0f} blocks")
            if d > 3.0:
                s = M.walk3(world, x, y, L, tol=2.0, budget=max(60, budget - (time.time() - t0)))
            near = [c for c in tanks() if math.hypot(c["x"] - x, c["y"] - y) < 4.0]
            s = _enter(world, near[0] if near else (x, y), check)
        else:
            free = tanks(free_only=True)
            if free:
                ev(f"to the free tank {free[0]['id']} at {free[0]['x']:.1f},{free[0]['y']:.1f}")
                s = _enter(world, free[0], check)
            elif jack:
                from skills import steal_car as SC
                ev("no free tank in sight: the steal-car skill for a TANK")
                s = SC.steal_car(world, [TANK], search=search, budget=max(60, budget - (time.time() - t0)), check=check)
            else:
                return None
        if in_tank(s):
            ev(f"in the tank at {s['x']:.1f},{s['y']:.1f} after {time.time() - t0:.0f}s")
            return s
    return None


def drive(world, tx, ty, tol=2.0, budget=240, until=None, view_switch=None):
    """drive the tank (mission_lib.drive3; a tank is slow and heavy, pushing traffic aside)"""
    return M.drive3(world, tx, ty, tol=tol, budget=budget, view_switch=view_switch, until=until)


def leave():
    release(); return M.leave_car()


# ------------------------------------------------------------------ fighting

BLOCKED = {}   # target id -> wall time until which it is skipped (shells did not reach it)


def car_targets(s, models=None, select=None, reach=10.0, marked=False):
    """live cars in reach on his level; a burning car is no target (it is done: tk2 spent 50 s and
    100 shells on a pile of burning wrecks in the line of fire)"""
    out = []; now = time.time()
    for c in M.cars():
        if c["driver"] == "P" or c["hp"] <= 0 or c["fire"] > 0 or c["model"] in WRECKS or c["model"] in TRAINS: continue
        if BLOCKED.get(c["id"], 0) > now: continue
        if models is not None and c["model"] not in models: continue
        if marked and c["mark"] is None: continue
        if select and not select(c): continue
        d = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
        if d < 0.9 or d > reach or abs(c["z"] - s["z"]) > 1.2: continue
        out.append((d, c))
    return out


def ped_targets(s, select=None, reach=10.0, marked=False):
    out = []; now = time.time()
    for p in M.peds():
        if not M.ped_alive(p) or p["car"] is not None: continue
        if BLOCKED.get(p["id"], 0) > now: continue
        if marked and p["mark"] is None: continue
        if select and not select(p): continue
        d = math.hypot(p["x"] - s["x"], p["y"] - s["y"])
        if d < 0.6 or d > reach or abs(p["z"] - s["z"]) > 1.2: continue
        out.append((d, p))
    return out


def cone_at(d, cone):
    """the aim tolerance at distance d: half a car's width either side, at least `cone`"""
    return max(cone, min(0.7, math.atan2(0.7, max(d, 0.5))))


def pick(s, cands, turn_cost=8.0):
    """the target with the least distance + turn_cost x |turn| (a tank turns slowly: tk3 spent
    87 turn pulses and fired 30 shells in its minute), less a bonus for each other car within
    1.6 blocks of it (one blast takes its neighbours: queues at a junction)"""
    best = None
    for d, t in cands:
        a = abs(angle_to(s, t["x"], t["y"]))
        crowd = sum(1 for _, o in cands if o is not t and math.hypot(o["x"] - t["x"], o["y"] - t["y"]) < 1.6)
        score = d + turn_cost * a - 1.5 * crowd - (8.0 if t.get("mark") is not None else 0.0)
        if best is None or score < best[0]: best = (score, d, a, t)
    return best


def shot_async(name):
    """a frame without stopping the fight (M.shot blocks ~2 s under load)"""
    import threading
    threading.Thread(target=M.shot, args=(name,), daemon=True).start()


FIRE_GAP = 0.35   # wall seconds between taps
MISS_TAPS = 4     # taps at one target without its hp dropping before it is skipped
BLOCK_SECS = 6.0  # game seconds a skipped target stays skipped


def fire_tap():
    tap("Control_L", 0.1); STATS["shells"] = STATS.get("shells", 0) + 1


def turn_at(s, tx, ty, slice_s=0.45, creep=True, back=False):
    """one turn pulse of the hull at (tx,ty) with Up (or Down, `back`) held through it: a tank
    does not turn standing. Reversing swaps the steering, so the turn key is swapped too"""
    a = angle_to(s, tx, ty)
    key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
    if back: key = "Right" if key == "Left" else "Left"
    drive_key = "Down" if back else "Up"
    if creep: xdo("keydown", drive_key)
    xdo("keydown", key); time.sleep(min(slice_s, max(0.12, abs(a) / 1.0))); xdo("keyup", key)
    if creep: xdo("keyup", drive_key)
    STATS["turns"] += 1
    return a


JACKER_TYPES = ("cop", "swat", "fbi", "army", "soldier")


def jackers(s, within=3.0):
    """the nearest police / army ped on foot within `within` blocks (they drag the player out of a
    tank that stands), or None"""
    best = None
    for p in M.peds():
        if p["car"] is not None or not M.ped_alive(p): continue
        if not any(p["type"].startswith(k) for k in JACKER_TYPES): continue
        d = math.hypot(p["x"] - s["x"], p["y"] - s["y"])
        if d < within and abs(p["z"] - s["z"]) < 1.2 and (best is None or d < best[0]): best = (d, p)
    return best[1] if best else None


def roam_points(world, s, r=18):
    pts = []
    for ang in range(0, 360, 45):
        c = M.street_cell_near(world, s["x"] + r * math.cos(math.radians(ang)), s["y"] + r * math.sin(math.radians(ang)), radius=6)
        if c and abs(c[2] - M.ped_level(s)) <= 1: pts.append((c[0], c[1]))
    return pts


def fight(world, kind="cars", count=20, secs=60.0, check=None, models=None, select=None, marked=False,
          reach=13.0, cone=0.20, stall=3.0, roam=None, burn=True, shot_prefix="tk", turn_max=1.2):
    """fight from the tank until `count` targets are destroyed (by our count), `secs` game seconds
    pass, or check() raises. kind: "cars" or "peds". roam: road points patrolled in turn (default a
    ring of road cells round where the fight starts). A target off the nose by more than
    `turn_max` is not turned to: the patrol brings the next one into the cone (tk3, tk4: 87 and 97
    rolling turn pulses, 30 and 34 shells, 8 cars each)"""
    s = D.wait_state()
    if not in_tank(s): ev("fight: not in a tank"); return "out"
    M.ensure_view("third")
    t0 = time.time(); roam = list(roam or roam_points(world, s)); ri = [0]
    st = dict(kills=0, seen={}, counted=set(), shots=0, aim=[None, 0, 0])
    last_move = [time.time(), s["x"], s["y"]]
    ev(f"fight {kind}: {count} in {secs:.0f}s, reach {reach}, {len(roam)} roam points")

    def over():
        return (time.time() - t0) * D.SPEED >= secs or st["kills"] >= count

    def cands_of(s):
        return car_targets(s, models, select, reach, marked) if kind == "cars" else ped_targets(s, select, reach, marked)

    def tally(s):
        """a target seen alive in reach that is now hp 0 / burning / dead"""
        for t in (M.cars() if kind == "cars" else M.peds()):
            if t["id"] in st["counted"]: continue
            d = math.hypot(t["x"] - s["x"], t["y"] - s["y"])
            if kind == "cars":
                if t["driver"] == "P" or t["model"] in TRAINS: continue
                dead = t["hp"] <= 0 or (burn and t["fire"] > 0)
            else:
                dead = not M.ped_alive(t)
            if not dead:
                if d <= reach + 2: st["seen"][t["id"]] = time.time()
            elif t["id"] in st["seen"] and d <= reach + 4:
                st["counted"].add(t["id"]); st["kills"] += 1; STATS["kills_seen"] += 1
                ev(f"{kind[:-1]} {t['id']} destroyed ({st['kills']}/{count}) {d:.1f} blocks off")
                if st["kills"] in (1, count // 2, count): shot_async(f"{shot_prefix}_kill{st['kills']}")

    def shoot_if_aimed(s, b):
        """a tap when the chosen target is on the nose; a target that the taps do not hurt (a wreck
        or a wall in the line of fire) is skipped a while. True when a shell went"""
        if not b: return False
        _, d, a, t = b
        if a >= cone_at(d, cone): return False
        a0 = st["aim"]
        if a0[0] != t["id"]: st["aim"] = [t["id"], t["hp"], 0]
        elif t["hp"] < a0[1]: st["aim"] = [t["id"], t["hp"], 0]
        st["aim"][2] += 1
        if st["aim"][2] > MISS_TAPS:
            BLOCKED[t["id"]] = time.time() + BLOCK_SECS / D.SPEED; STATS["blocked"] = STATS.get("blocked", 0) + 1
            st["aim"] = [None, 0, 0]; return False
        fire_tap()
        if st["shots"] == 0: shot_async(f"{shot_prefix}_fire")
        st["shots"] += 1
        return True

    def hook():
        """drive3's `until` while patrolling: tally, fire at whatever crosses the nose, stop the leg
        when the fight is over or a target sits close to the nose ahead"""
        s2 = D.wait_state()
        if not s2 or not s2["driving"]: return True
        tally(s2)
        if over(): return True
        b2 = pick(s2, cands_of(s2))
        shoot_if_aimed(s2, b2)
        return False

    try:
        while not over():
            if check: check()
            s = D.wait_state(); ms = M.mission_state() or {}
            if not in_tank(s, ms): ev("out of the tank"); return "out"
            tally(s)
            cop = jackers(s)
            if cop:
                # police on foot beside a standing tank pull the player out (tk6: wanted 1, two
                # cops a block off, out and shot at 04:24:33, the frenzy over): keep rolling
                STATS["evasions"] = STATS.get("evasions", 0) + 1
                if STATS["evasions"] % 10 == 1: ev(f"{cop['type']} {cop['id']} on foot {math.hypot(cop['x'] - s['x'], cop['y'] - s['y']):.1f} off: rolling")
                a = angle_to(s, cop["x"], cop["y"])
                back = abs(a) > 1.8          # behind: back over him
                turn_at(s, cop["x"], cop["y"], slice_s=0.5, creep=True, back=back)
                continue
            b = pick(s, cands_of(s))
            if shoot_if_aimed(s, b):
                d = b[1]
                if d > reach * 0.7: hold("Up", 0.25)
                elif d < 1.8: hold("Down", 0.3)       # point blank: the blast reaches the tank
                else: time.sleep(FIRE_GAP)
            elif b and b[2] < turn_max and b[1] < reach * 0.8:
                # the hull turns only while it rolls (tk1, tkp3: Left/Right standing turned neither
                # the hull nor the turret); back up while turning when the target is close
                turn_at(s, b[3]["x"], b[3]["y"], creep=True, back=b[1] < 3.0)
            else:
                tx, ty = roam[ri[0] % len(roam)]
                if math.hypot(tx - s["x"], ty - s["y"]) < 4.0:
                    ri[0] += 1; tx, ty = roam[ri[0] % len(roam)]
                STATS["roams"] += 1
                left = secs - (time.time() - t0) * D.SPEED
                drive(world, tx, ty, tol=3.0, budget=max(4.0, min(25.0, left / D.SPEED)), until=hook)
                M.ensure_view("third")
            s = D.wait_state()
            if math.hypot(s["x"] - last_move[1], s["y"] - last_move[2]) > 0.4:
                last_move[:] = [time.time(), s["x"], s["y"]]
            elif (time.time() - last_move[0]) * D.SPEED > stall:
                STATS["stalls"] += 1; ev(f"stalled at {s['x']:.1f},{s['y']:.1f}: backing off")
                k = "Left" if STATS["stalls"] % 2 else "Right"
                xdo("keydown", "Down"); hold(k, 0.6); time.sleep(0.4); xdo("keyup", "Down")
                last_move[:] = [time.time(), s["x"], s["y"]]
    finally:
        release()
    r = "done" if st["kills"] >= count else "time"
    ev(f"fight {kind} ends: {r}, {st['kills']} counted in {(time.time() - t0) * D.SPEED:.0f} game s ({STATS['shells']} shells)")
    M.shot(f"{shot_prefix}_end")
    return r


def main():
    D.start(); D.calibrate_turn()
    world = M.World(os.environ.get("TANK_DISTRICT", "wil"))
    kind = sys.argv[1] if len(sys.argv) > 1 else "cars"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    secs = float(sys.argv[3]) if len(sys.argv) > 3 else 60
    s = get_tank(world, budget=300)
    if s: say("RESULT", fight(world, kind, count, secs), STATS)
    else: say("RESULT no tank")


if __name__ == "__main__":
    main()
