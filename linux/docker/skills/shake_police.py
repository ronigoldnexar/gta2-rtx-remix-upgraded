#!/usr/bin/env python3
"""Skill: SHAKE THE POLICE / RESPRAY (SKILL-POLICE, Wave M, 11 jobs in docs/missions-catalogue.md).

`wanted_evasion` jobs: wil_ye2 BANK ROBBERY, wil_yh1 SWAT VAN SWIPE, wil_zm3 BIG BANK JOB, ste_zm3
LAW ENFORCEMENT LARCENY, ste_zh2 DISTRACTION ACTION, ste_rm3 TANKS-GIVING, ste_rh2 PENAL TIES, bil_ke2
COP CAR SCRAP, bil_zh1 I'D LIKE A TANK PLEASE BOB, bil_zh2 ARMY BASE ALERT, bil_rm1 OFFICER DOWN. In the
scripts the pattern is one of three:

  * **clear the level** (BANK ROBBERY: `ALTER_WANTED_LEVEL_NO_DROP (p1, 2)` then a loop on
    `CHECK_HEADS_GREATER`): a NO_DROP level never decays, only a respray (or a bribe) ends it.
    Any respray shop works, not only the one the script's arrow points at;
  * **survive a timed chase** (DISTRACTION ACTION: evade arrest for 60 s): keep moving, away from
    the police, and do not get pulled out of the car;
  * **carry a stolen police vehicle home** (SWAT van, cop car, Special Agent car, tank): the level
    rises on its own; a respray on the way (repairs to carhp 32000) is what keeps the car intact.

A respray shop is a `CAR_SHOP n` object (n a remap number: the drive-in recolours the car to it;
`CAR_SHOP BOMB_SHOP` etc. are the other drive-ins of the same strip). Its cell is a one-column
tunnel under a roof, entered from the road on one side; the strips run along one axis (2 cells
apart) and are entered across it. Going in with at least $5,000 (RESPRAY_COST) sets the wanted
level to 0, repairs the car and takes the money (br7: money 5040 -> 40, carhp 32000; pt8_respray2:
with $20 nothing happens at all).

API (all on top of the frozen mission_lib/drive_lib; nothing there is changed):

| call | does |
|---|---|
| `wanted()` / `police_near(s, car_r, ped_r)` | the level from `view: mission`; police cars (models 12/52/54...) and officers near him |
| `shops(world)` | the district's resprays as `Shop(x, y, level, remap, entry, side)`, entry side read off the map (cached) |
| `pick_shop(world, s, avoid)` | the nearest shop by the car router's path length (crow line as the tie-break / fallback) |
| `respray(world, shop, check, view_switch, done, secs)` | drive to the entry point, creep into the tunnel, wait for the game (wanted 0 / carhp back / money taken / `done()`); out backwards when it did not happen |
| `shake(world, check, view_switch, done, tries, budget, evade_ok)` | the whole skill: resprays nearest-first (another shop after a miss); without the money, or with `evade_ok`, `evade()` until the level drops |
| `evade(world, secs, check, view_switch, until)` | drive legs to road points 25-45 blocks off, chosen away from the police (centroid of the cars/officers seen), until `until()` or the time is up (timed jobs) |

Every step marks `/out/marks.txt` with `police: ...` and appends to `EVENTS`; frames `sp_*`.
Returns of `shake`: "clear" (level 0 or `done()`), "complete" / "failed" / "dead" (the job ended),
"stuck: ..." (a reason).
"""
import math, os, sys, time
from collections import namedtuple
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

SPEED = float(os.environ.get("GTA2_SPEED", "1") or 1)
RESPRAY_COST = int(os.environ.get("SP_RESPRAY_COST", "5000"))
POLICE_MODELS = (12, 52, 54, 79)      # COPCAR, SWATVAN, Special Agent car, army jeep (m79: logged near the base, unverified)
EVENTS = []

# Respray shops: the numeric CAR_SHOP entries of assets-src/missions/{wil,ste,bil}.mis
# (x, y, mis z, remap) and the axis the strip runs along (the drive-ins of one strip are 2 cells
# apart): the tunnel is entered across that axis.
RESPRAYS = {
    "wil": [(204.5, 221.5, 2.0, 10, "x"), (219.5, 34.5, 2.0, 32, "y"), (24.5, 60.5, 3.0, 5, "x"),
            (46.5, 136.5, 2.0, 0, "x"), (86.5, 160.5, 2.0, 9, "x"), (209.5, 121.5, 2.0, 26, "x")],
    "ste": [(6.5, 183.5, 2.0, 0, "y"), (178.5, 216.5, 2.0, 5, "y"), (215.5, 76.5, 2.0, 9, "y"),
            (94.5, 27.5, 2.0, 10, "y")],
    "bil": [(177.5, 14.5, 2.0, 28, "x"), (234.5, 154.5, 2.0, 24, "x"), (30.5, 216.5, 2.0, 2, "x"),
            (64.5, 90.5, 2.0, 0, "x")],
}
# entry sides seen in sessions (br7/br9/gr1: down column 204 from row 216 into 204.5,221.5; the job's
# own 86.5,160.5 from the road at row 163): they override the map reading
KNOWN_SIDE = {("wil", 204.5, 221.5): (0, -1), ("wil", 86.5, 160.5): (0, 1)}
ENTRY_OUT = 2.9          # the entry point, cells out from the shop's centre (br: 218.6 for 221.5)

Shop = namedtuple("Shop", "x y level remap entry side score")
_SHOPS = {}


def _ev(what):
    EVENTS.append((time.time(), what)); M.mark(f"police: {what}")


def wanted(ms=None):
    ms = ms or M.mission_state() or {}
    return ms.get("wanted", 0)


def police_near(s, car_r=22.0, ped_r=16.0):
    """(n police cars, n officers, nearest distance, centroid or None) near the player"""
    nc = no = 0; best = 99.0; sx = sy = 0.0
    for c in M.cars():
        if c["model"] in POLICE_MODELS and c["driver"] != "P":
            d = math.hypot(c["x"] - s["x"], c["y"] - s["y"])
            if d < car_r: nc += 1; best = min(best, d); sx += c["x"]; sy += c["y"]
    for p in M.peds():
        if p["type"] == "cop" and M.ped_alive(p) and p["car"] is None:
            d = math.hypot(p["x"] - s["x"], p["y"] - s["y"])
            if d < ped_r: no += 1; best = min(best, d); sx += p["x"]; sy += p["y"]
    n = nc + no
    return nc, no, best, ((sx / n, sy / n) if n else None)


def _side_score(world, x, y, L, dx, dy, reach=7):
    """how good an entry side is: the cells 2..reach out from the shop along (dx, dy), road 3,
    lot 1.5, pavement 0.5, stopping at a wall face or a cell with nothing to drive on. The shop is
    a three-cell drive-through under a roof (wil 204.5,221.5: lot cells 220-222 with a level-2 roof,
    whose two mouth cells node_kind calls covered): cell 1 out is the roofed mouth and only needs a
    lid with ground under it"""
    cx, cy = int(math.floor(x)), int(math.floor(y)); score = 0.0
    for k in range(1, reach + 1):
        px, py = cx + dx * (k - 1), cy + dy * (k - 1)
        if M.wall_between(world, px, py, L, dx, dy): break
        if k == 1:
            b = M._blk(world, px + dx, py + dy, L)
            if not (b and M._lid(b) and M._gtype(b) in (1, 2, 3)): break
            continue
        kind = M.node_kind(world, px + dx, py + dy, L)
        if not kind: break
        score += {1: 3.0, 3: 1.5, 2: 0.5}.get(kind[1], 0.0)
    return score


SIDE_MIN = 4.0           # a side scoring less than this (a lane or two of pavement) is not used


def shops(world):
    """the district's respray shops, one Shop per usable entry side (a drive-through is entered
    from either end; a side the sessions proved is the only one kept), read off the map once"""
    dist = getattr(world, "district", "wil")
    if dist in _SHOPS: return _SHOPS[dist]
    out = []
    for x, y, z, remap, axis in RESPRAYS.get(dist, []):
        L = max(1, int(round(z)) - 1)
        sides = [(0, -1), (0, 1)] if axis == "x" else [(-1, 0), (1, 0)]
        scored = []
        for dx, dy in sides:
            try: sc = _side_score(world, x, y, L, dx, dy)
            except Exception as e: sc = 0.0; say(f"police: side score failed at {x},{y} ({e})")
            scored.append((sc, (dx, dy)))
        scored.sort(reverse=True)
        if (dist, x, y) in KNOWN_SIDE:
            side = KNOWN_SIDE[(dist, x, y)]
            scored = [(max(SIDE_MIN, dict((s, c) for c, s in scored).get(side, 0.0)), side)]
        use = [(c, s) for c, s in scored if c >= SIDE_MIN] or scored[:1]
        for sc, side in use:
            out.append(Shop(x, y, L, remap, (x + side[0] * ENTRY_OUT, y + side[1] * ENTRY_OUT), side, sc))
    _SHOPS[dist] = out
    return out


def _route_len(world, s, tx, ty):
    try:
        path = M.car_route(world, s, tx, ty)
    except Exception as e:                      # the router is shared and frozen; never let it end the job
        say(f"police: car_route failed ({e})"); path = None
    if path and abs(path[-1][0] - int(tx)) + abs(path[-1][1] - int(ty)) <= 2: return len(path)
    return None


def pick_shop_fast(world, s, avoid=()):
    """the nearest entry by straight line, no router (police at the door: sp7 was arrested while
    the car stood 4.5 s for five router calls)"""
    cands = [sh for sh in shops(world) if (sh.x, sh.y) not in avoid] or shops(world)
    if not cands: return None
    sh = min(cands, key=lambda sh: math.hypot(sh.entry[0] - s["x"], sh.entry[1] - s["y"]))
    say(f"police: nearest respray by straight line {sh.x},{sh.y} entry {sh.entry[0]:.1f},{sh.entry[1]:.1f} (police close)")
    return sh


def pick_shop(world, s, avoid=()):
    """the nearest respray entry by the car router's path (crow line x 1.4 + 20 when the router
    finds none); shops in `avoid` (missed twice this session) skipped while another remains"""
    cands = [sh for sh in shops(world) if (sh.x, sh.y) not in avoid] or shops(world)
    # the router only for the five nearest entries by crow line (each call walks the map)
    cands.sort(key=lambda sh: math.hypot(sh.entry[0] - s["x"], sh.entry[1] - s["y"]))
    best = None
    for sh in cands[:5]:
        crow = math.hypot(sh.entry[0] - s["x"], sh.entry[1] - s["y"])
        n = _route_len(world, s, sh.entry[0], sh.entry[1])
        cost = n if n is not None else crow * 1.4 + 20
        if best is None or cost < best[0]: best = (cost, sh, n, crow)
    if best:
        say(f"police: nearest respray {best[1].x},{best[1].y} (remap {best[1].remap}) entry "
            f"{best[1].entry[0]:.1f},{best[1].entry[1]:.1f} side {best[1].side}: route {best[2]} cells, crow {best[3]:.0f}")
        return best[1]
    return None


COP_CLOSE = 3.5          # an officer on foot this near a slow car pulls the player out (sp2, sp5, sp9: busted;
                         # at 2.3 the break-away came after the arrest had started)
CHASE_SLOW_HP = 20000    # under a chase the fragile pace (slow=True) only below this carhp


def cop_close(s=None, r=COP_CLOSE):
    """an officer on foot (not in a car) within r blocks of the player"""
    s = s or D.wait_state()
    if not s: return False
    for p in M.peds():
        if p["type"] == "cop" and p["car"] is None and M.ped_alive(p):
            if math.hypot(p["x"] - s["x"], p["y"] - s["y"]) < r: return True
    return False


def own_speed():
    """the player's car speed from `view: cars` (driver P), None when not listed"""
    for c in M.cars():
        if c["driver"] == "P": return c["v"]
    return None


def threat_at_door():
    """an officer close while the car is slow (a car rolling past an officer is not boarded)"""
    v = own_speed()
    return (v is None or v < 2.0) and cop_close()


def break_away(world):
    """roll clear of an officer at the door: forward when the way ahead is open, else back out
    with the wheel turned; a moving car is not boarded"""
    s = D.wait_state()
    if not (s and s["driving"]): return s
    try: blocked = M.blocked_ahead(world, s, 1.4)
    except Exception: blocked = False
    if blocked:
        xdo("keydown", "Down"); xdo("keydown", "Left"); time.sleep(0.9 / SPEED)
        xdo("keyup", "Down"); xdo("keyup", "Left")
    else:
        hold("Up", 1.2 / SPEED)
    _ev(f"break away from an officer at {s['x']:.1f},{s['y']:.1f} ({'back' if blocked else 'ahead'})")
    return D.wait_state()


def chase_drive(world, tx, ty, tol, budget, view_switch=None, until=None, check=None):
    """M.drive3 under a chase: the normal pace while carhp >= CHASE_SLOW_HP (the fragile caps made
    sp5's car a 2-blocks/s target), and the drive stopped for a break-away whenever an officer on
    foot comes within COP_CLOSE; resumed until arrived, until(), out of the car or the budget"""
    t0 = time.time(); breaks = 0; s = D.wait_state()
    if s and s["driving"] and threat_at_door(): breaks += 1; s = break_away(world)
    while time.time() - t0 < budget:
        if check: check()
        if until and until(): return s
        s = D.wait_state()
        if not (s and s["driving"]): return s
        if math.hypot(tx - s["x"], ty - s["y"]) <= tol: return s
        hp = (M.mission_state() or {}).get("carhp", 32000)
        M.CAR_AVOID.clear()
        flag = {"cop": False}
        def stop():
            if until is not None and until(): return True
            if threat_at_door(): flag["cop"] = True; return True
            return False
        s = M.drive3(world, tx, ty, tol=tol, budget=max(10, budget - (time.time() - t0)), view_switch=view_switch,
                     slow=hp < CHASE_SLOW_HP, precious=True, until=stop)
        if flag["cop"]:
            # at once, no re-check (sp9: two seconds of log reads after the stop, and the arrest
            # had started by the time the car moved)
            breaks += 1; break_away(world)
            if breaks > 12: _ev("too many officers at the door"); return D.wait_state()
            continue
        return s
    return D.wait_state()


def _creep(shop, secs, done, check):
    """nose into the tunnel cell with short pulses, straightening on it (the pattern of
    bank_robbery.creep_in, 0.8 x 1.0 box); handbrake when inside"""
    x, y = shop.x, shop.y
    w, h = (1.0, 0.8) if shop.side[0] else (0.8, 1.0)
    t0 = time.time(); k = 0
    while time.time() - t0 < secs:
        s = D.wait_state()
        if not s or not s["driving"]: return s
        if check: check()
        if done(): return s
        if abs(s["y"] - y) < max(0.2, h / 2 - 0.15) and abs(s["x"] - x) < max(0.3, w / 2 - 0.15):
            hold("space", 0.3); return s
        hx, hy = M.heading(s); dx, dy = x - s["x"], y - s["y"]
        a = math.atan2(hx * dy - hy * dx, hx * dx + hy * dy)
        if abs(a) > 0.5 and math.hypot(dx, dy) > 0.8:
            xdo("keydown", "Down"); xdo("keydown", "Left" if a > 0 else "Right"); time.sleep(0.6)
            xdo("keyup", "Down"); xdo("keyup", "Left"); xdo("keyup", "Right"); time.sleep(0.3)
            continue
        if abs(a) > 0.1: xdo("keydown", "Right" if a > 0 else "Left")
        # aligned and more than two blocks out: longer pulses (a car crawling in pulses is boarded)
        pulse = 0.5 if (abs(a) < 0.25 and math.hypot(dx, dy) > 2.0) else 0.25
        xdo("keydown", "Up"); time.sleep(pulse); xdo("keyup", "Up"); xdo("keyup", "Right"); xdo("keyup", "Left")
        if cop_close(): continue
        time.sleep(0.4); k += 1
        if k % 6 == 0: hold("Down", 0.8); time.sleep(0.3)
    return D.wait_state()


def respray(world, shop, check=None, view_switch=None, done=None, secs=40, budget=360):
    """one respray: drive to the shop's entry point, creep in, wait for the game. True when the
    shop worked (wanted 0 from > 0, carhp up to >= 30000 from below, the money taken, or done())"""
    ms0 = M.mission_state() or {}
    w0, hp0, m0 = ms0.get("wanted", 0), ms0.get("carhp", -1), ms0.get("money", 0)
    _ev(f"to the respray {shop.x},{shop.y} (remap {shop.remap}; wanted {w0}, carhp {hp0}, money {m0})")
    if m0 < RESPRAY_COST: _ev(f"money {m0} < {RESPRAY_COST}: the shop will not work")

    def worked():
        if done and done(): return True
        ms = M.mission_state() or {}
        if w0 > 0 and ms.get("wanted", w0) == 0: return True
        if 0 <= hp0 < 30000 and ms.get("carhp", -1) >= 30000: return True
        return ms.get("money", m0) <= m0 - RESPRAY_COST + 50

    # tol 1.6: the last turn into the tunnel line is the creep's (sp5 was pressed on the corner of
    # row 216 and column 204, 2.3 from the entry, and pulled out of the car)
    s = chase_drive(world, shop.entry[0], shop.entry[1], 1.6, budget, view_switch=view_switch, until=worked, check=check)
    if check: check()
    if worked(): _ev("the level went on the way in"); return True
    if not (s and s["driving"]): _ev("out of the car on the way"); return False
    s = D.wait_state()
    if math.hypot(shop.entry[0] - s["x"], shop.entry[1] - s["y"]) > 4.0:
        _ev(f"entry not reached ({s['x']:.1f},{s['y']:.1f})"); return False
    _ev(f"into the shop {shop.x},{shop.y} (wanted {wanted()}, police {police_near(s)[:3]})")
    _creep(shop, secs, worked, check)
    M.shot("sp_respray_in")
    t0 = time.time()
    while time.time() - t0 < 20 / SPEED and not worked():
        if check: check()
        time.sleep(0.5)
    ok = worked()
    ms = M.mission_state() or {}
    _ev(f"respray {'done' if ok else 'not done'} at {shop.x},{shop.y}: wanted {ms.get('wanted')}, "
        f"carhp {ms.get('carhp')}, money {ms.get('money')}, msg {ms.get('msg')}")
    if ok:
        M.shot("sp_resprayed")
        hold("Down", 0.4)
    else:
        hold("Down", 1.5); time.sleep(0.4)          # out the way he came
    return ok


def _road_point_away(world, s, away, rmin=25, rmax=45):
    """a road cell rmin..rmax blocks off, as far as possible from `away` (the police), that the
    car router reaches; None when none is found"""
    L = 1; best = None
    base = math.atan2(s["y"] - away[1], s["x"] - away[0]) if away else 0.0
    for k in range(12):
        a = base + (k // 2 + 1) * (0.35 if k % 2 else -0.35) * (1 if k else 0)
        for r in (rmax, (rmin + rmax) / 2, rmin):
            tx, ty = s["x"] + math.cos(a) * r, s["y"] + math.sin(a) * r
            if not (2 <= tx < 254 and 2 <= ty < 254): continue
            kind = M.node_kind(world, int(tx), int(ty), L)
            if not kind or kind[1] != 1: continue
            n = _route_len(world, s, tx, ty)
            if n is None or n > r * 2.2: continue
            gain = math.hypot(tx - away[0], ty - away[1]) if away else r
            if best is None or gain > best[0]: best = (gain, (int(tx) + 0.5, int(ty) + 0.5))
            break
        if best and k >= 3: break
    return best[1] if best else None


def evade(world, secs, check=None, view_switch=None, until=None):
    """keep driving away from the police for `secs` (wall seconds, scaled by GTA2_SPEED) or
    until `until()`: legs of 25-45 blocks to road points on the far side from the police seen.
    Returns "clear" (until() held), "time" (survived the time), "on foot" (pulled out / out)"""
    t0 = time.time(); end = t0 + secs / SPEED; legs = 0
    _ev(f"evading for {secs:.0f} s (wanted {wanted()})")
    while time.time() < end:
        if check: check()
        if until and until(): _ev(f"clear after {time.time() - t0:.0f} s ({legs} legs)"); return "clear"
        s = D.wait_state()
        if not (s and s["driving"]): _ev("on foot while evading"); return "on foot"
        nc, no, dmin, cen = police_near(s, 40.0, 20.0)
        p = _road_point_away(world, s, cen)
        if p is None:
            hold("Up", 1.0); continue
        legs += 1
        _ev(f"leg {legs} to {p[0]:.1f},{p[1]:.1f} (police {nc} cars, {no} officers, nearest {dmin:.0f}, wanted {wanted()})")
        stop = (lambda: (until is not None and until()) or time.time() > end)
        chase_drive(world, p[0], p[1], 3.0, max(10, min(120, end - time.time())), view_switch=view_switch, until=stop, check=check)
        if legs % 3 == 1: M.shot(f"sp_evade{legs}")
    if until and until(): return "clear"
    _ev(f"evaded {secs:.0f} s ({legs} legs, wanted {wanted()})")
    return "time"


def shake(world, check=None, view_switch=None, done=None, tries=4, budget=900, evade_ok=False, evade_secs=90):
    """lose the wanted level: resprays nearest-first (a missed shop is skipped next time); with
    less than RESPRAY_COST, or `evade_ok` after the resprays failed, `evade()` until the level
    drops (a NO_DROP level never does). `done()` is the job's own "cleared" test (its next brief or
    arrow) and counts as clear."""
    t0 = time.time(); missed = []
    def clear():
        if done and done(): return True
        return wanted() == 0
    _ev(f"shake: wanted {wanted()}, money {(M.mission_state() or {}).get('money')}")
    for k in range(tries):
        if check: check()
        if clear(): return "clear"
        if time.time() - t0 > budget: break
        s = D.wait_state()
        if not (s and s["driving"]): return "stuck: on foot"
        money = (M.mission_state() or {}).get("money", 0)
        if money < RESPRAY_COST: _ev(f"no respray (money {money})"); break
        nc, no, dmin, _ = police_near(s, 12.0, 8.0)
        if threat_at_door(): break_away(world); s = D.wait_state()
        sh = pick_shop_fast(world, s, avoid=missed) if dmin < 8.0 else pick_shop(world, s, avoid=missed)
        if sh is None: break
        if respray(world, sh, check=check, view_switch=view_switch, done=done): break
        missed.append((sh.x, sh.y)) if k >= 1 else None   # the first miss gets a second go at the same shop
    # the game may take a moment to move the script on after the respray
    t1 = time.time()
    while time.time() - t1 < 6 / SPEED and not clear():
        if check: check()
        time.sleep(0.5)
    if clear(): _ev(f"clear after {time.time() - t0:.0f} s"); return "clear"
    if evade_ok or (M.mission_state() or {}).get("money", 0) < RESPRAY_COST:
        r = evade(world, evade_secs, check=check, view_switch=view_switch, until=clear)
        if r == "clear": return "clear"
    return f"stuck: wanted {wanted()} after {time.time() - t0:.0f} s"


if __name__ == "__main__":
    # offline check of the shop table against the map (host side: python3 shake_police.py <game data dir>)
    import gmp
    d = sys.argv[1] if len(sys.argv) > 1 else "/tmp/wp/drive_c/Games/GTA2/data"
    class W: pass
    for dist in ("wil", "ste", "bil"):
        w = W(); w.district = dist; w.blocks, w.columns = gmp.load(f"{d}/{dist}.gmp")
        for sh in shops(w):
            print(dist, sh)
