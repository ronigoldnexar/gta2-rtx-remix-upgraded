#!/usr/bin/env python3
"""FAKE TRUCE! (Residential file ste, the SRS Scientists' green phone 235.5,202.5, ste_se2.mis):
the proof job of the horn pick-up skill (gamerun/skills/horn_pickup.py, SKILL-HORN).

What the script wants (assets-src/missions/ste_m/ste_se2.mis):
  2958 title, 2300 "Collect the old Factory Bus"; the BUS at 227.5,214.5 (arrow on it);
  in the bus: 2301, the arrow on the first group's leader;
  four groups of six (a leader with a machine gun + ADD_GROUP_TO_CHARACTER 5), one at a time:
    Rednecks 16.5,71.5 and 9.5,43.5 (z 2), Zaibatsu 197.5,25.5 and 228.5,34.5 (z 3);
    each: LOCATE_CHARACTER_BY_CAR (p1, x, y, z, 8, 4) in the bus -> 2278 "Sound the horn";
    IS_CHAR_PRESSING_HORN -> 2304/2306/2308/2310 and ENTER_CAR_AS_PASSENGER; IS_GROUP_IN_CAR ->
    KILL_ALL_PASSENGERS (the bus empties: they are "locked in" off screen) and the next group's
    brief 2305/2307/2309, after the fourth 2311;
  fewer than 2 of the waiting group alive: 2314 + 2998; the bus wrecked before the end: 2302 + 2998;
  2311: to 215.5,226.5 (LOCATE_CHARACTER_BY_CAR 8 x 3) -> 2312, the arrow removed; out of the bus:
  it is locked, a scientist (pistol) destroys it; IS_CAR_WRECKED -> 2315, 2999, $30,000.

Run inside the container (keys script missions/keys_fake_truce.sh, SWAP_LEVEL=ste):
    python3 /work/missions/fake_truce.py
Env: FT_WARP_PHONE=1 (the developer scene warp to the street by the phone when the player starts
far from it; marked; needs scene_key and GTA2DX9_SCENE_NO_CAR=1), FT_DRIVER=calm|smooth.
Marks /out/marks.txt, milestone frames /out/m_ft_*.png and /out/m_horn_*.png, summary
/out/ft_result.json.
"""
import json, math, os, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["DISTRICT"] = "ste"
os.environ["MISSIONS"] = " "
import drive_lib as D
import mission_lib as M
import mission_play_districts as P
from skills import deliver_intact as DI
from skills import horn_pickup as H

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world

JOB = "ste_se2"
PHONE = (235.5, 202.5)
BUS = (227.5, 214.5)
BUS_MODEL = None            # read from the game when he is in it
STOPS = [
    H.Stop("rednecks1", 16.5, 71.5, 8.0, 4.0, horn_keys=["2304"], aboard_keys=["2305"], count=6),
    H.Stop("rednecks2", 9.5, 43.5, 8.0, 4.0, horn_keys=["2306"], aboard_keys=["2307"], count=6),
    H.Stop("zaibatsu1", 197.5, 25.5, 8.0, 4.0, horn_keys=["2308"], aboard_keys=["2309"], count=6),
    H.Stop("zaibatsu2", 228.5, 34.5, 8.0, 4.0, horn_keys=["2310"], aboard_keys=["2311"], count=6),
]
DROP = (215.5, 226.5, 8.0, 3.0)
# the Residential respray shops (ste.mis CAR_SHOP with a number: the drive-through tunnels run
# east-west through the shop cell; entered from the east)
SHOPS = [((6.5, 183.5), (9.6, 183.5)), ((178.5, 216.5), (181.6, 216.5)),
         ((215.5, 76.5), (218.6, 76.5)), ((94.5, 27.5), (97.6, 27.5))]
FAIL = {"2998", "2302", "2314"}
DONE = {"2999", "2315"}
RESULT = dict(stage="start", events=[], pickups=0)
MSGS = H.Msgs(start_at_end=False)
LIVES0 = [None]


class Over(Exception):
    pass


def over():
    MSGS.poll()
    if any(k in DONE for k in MSGS.seen): return "complete"
    if any(k in FAIL for k in MSGS.seen): return "failed"
    ms = M.mission_state() or {}
    if ms.get("health", 1) == 0 or ms.get("death", 0) != 0: return "dead"
    if LIVES0[0] is not None and ms.get("lives", LIVES0[0]) < LIVES0[0]: return "dead"
    return None


def check():
    o = over()
    if o: raise Over(o)
    return M.mission_state() or {}


def ev(what):
    RESULT["events"].append(f"{time.strftime('%H:%M:%S')} {what}"); M.mark(what)


def bus_xy():
    ms = M.mission_state() or {}
    tc = ms.get("tcar")
    if tc and tc[0] > 0: return (tc[0], tc[1])
    o = M.objective()
    if o and o[3] in (3, 4): return (o[0], o[1])
    return BUS


DRIVER = os.environ.get("FT_DRIVER", "hybrid")  # ft1 smooth: bus burned 370 blocks short of group 3; ft2 calm: wedged
SMOOTH = M.drive3             # the shared driver, kept before russian_sailors replaces it on import
STALL_GAME_S = 20.0           # hybrid: no 1.5 blocks of progress in this many game seconds -> smooth burst
STATS = {"bursts": 0}


def hybrid_drive(world_, tx, ty, tol=2.0, budget=240, view_switch=None, slow=False, precious=False, until=None):
    """calm_drive (no blind reversing, waits in queues: less damage) with a way out: ft2 wedged the
    12-block-long bus against a kerb at 138.7,205.5 for 3 minutes with a car behind it, calm refusing
    every reverse. When calm makes no progress for STALL_GAME_S, the shared smooth driver takes a
    short burst (it reverses), then calm again"""
    t0 = time.time()
    s = D.wait_state()
    while time.time() - t0 < budget:
        if not (s and s["driving"]): return s
        if math.hypot(tx - s["x"], ty - s["y"]) <= tol or (until and until()): return s
        hist = [(time.time(), s["x"], s["y"])]

        def stalled():
            if until and until(): return True
            q = D.state()
            if not q: return False
            now = time.time(); hist.append((now, q["x"], q["y"]))
            while len(hist) > 2 and now - hist[1][0] > STALL_GAME_S / D.SPEED: hist.pop(0)
            if now - hist[0][0] < STALL_GAME_S / D.SPEED: return False
            return max(math.hypot(q["x"] - h[1], q["y"] - h[2]) for h in hist) < 1.5

        s = RS.calm_drive(world_, tx, ty, tol=tol, budget=max(20, budget - (time.time() - t0)), view_switch=view_switch,
                          slow=slow, precious=precious, until=stalled)
        if not (s and s["driving"]): return s
        if math.hypot(tx - s["x"], ty - s["y"]) <= tol or (until and until()): return s
        if time.time() - t0 >= budget: return s
        STATS["bursts"] += 1
        x0, y0 = s["x"], s["y"]
        say(f"hybrid: calm made no progress at {x0:.1f},{y0:.1f}: smooth burst {STATS['bursts']}")
        M.mark(f"hybrid driver: smooth burst at {x0:.1f},{y0:.1f}")

        def away():
            q = D.state()
            return (until and until()) or bool(q and math.hypot(q["x"] - x0, q["y"] - y0) > 5.0)

        s = SMOOTH(world_, tx, ty, tol=tol, budget=25, view_switch=view_switch, slow=slow, precious=precious, until=away)
    return s


if DRIVER in ("calm", "hybrid"):
    try:
        import missions.russian_sailors as RS
        RS.world = world
        M.drive3 = RS.calm_drive if DRIVER == "calm" else hybrid_drive      # this process only
        say(f"driver: {DRIVER}")
    except Exception as e:
        M.drive3 = SMOOTH; say(f"calm_drive not available ({e}); the shared driver")


def game_alive():
    for attempt in range(4):
        s0 = D.wait_state()
        hold("Left", 0.5); time.sleep(0.8); s1 = D.wait_state()
        if s0 and s1 and abs(s0["fx"] * s1["fy"] - s0["fy"] * s1["fx"]) + abs(s0["x"] - s1["x"]) + abs(s0["y"] - s1["y"]) > 0.02:
            return True
        say(f"start: the game does not move (attempt {attempt + 1}); Return"); tap("Return", 0.3); time.sleep(3.0)
    return False


def get_bus():
    for k in range(4):
        check()
        s = D.wait_state()
        if s["driving"] and math.hypot(s["x"] - bus_xy()[0], s["y"] - bus_xy()[1]) < 3.0: return s
        if s["driving"]: M.leave_car(); continue
        bx, by = bus_xy()
        ev(f"to the bus at {bx:.1f},{by:.1f}")
        s = P.enter_parked(bx, by, budget=150, why="the Factory Bus")
        if s and s["driving"]: return s
    return D.wait_state()


def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == JOB)
    wrong = {k for k, m in P.TITLES.items() if m.get("mission") != JOB}
    M.mark(f"mission {JOB}: FAKE TRUCE! (missions/fake_truce.py, skills/horn_pickup.py)")
    s = D.wait_state()
    if os.environ.get("FT_WARP_PHONE", "0") == "1" and math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) > 40:
        # the 145-block trip from the district start to this phone is not the job (SOS sessions:
        # 14 minutes); the developer scene warp to the street 8 blocks from the phone, marked
        near = M.street_cell_near(world, PHONE[0] - 8, PHONE[1] + 3, radius=8)
        if near:
            P.set_view("classic"); M.scene_warp(near[0], near[1], near[2], "FT_WARP_PHONE: to the street by the SRS phone; the job starts at the phone")
            P.set_view("third"); RESULT["events"].append(f"phone warp to {near}")
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    ok, key = P.answer(entry)
    MSGS.poll(); M.shot("ft_phone")
    if not ok and "2958" not in MSGS.seen and "2300" not in MSGS.seen: return "phone not answered"
    if set(MSGS.seen) & wrong: return f"wrong job started ({sorted(set(MSGS.seen) & wrong)})"
    RESULT["stage"] = "phone"; ev(f"phone answered (messages {MSGS.last()})")
    LIVES0[0] = (M.mission_state() or {}).get("lives")
    ax, ay = M.step_off_phone(world, entry)
    M.set_avoid_phones(world, keep=None)
    M.cruise_to(ax, ay, tol=0.5, secs=10)
    # the bus
    t0 = time.time()
    s = get_bus()
    if not s["driving"]: return "could not board the bus"
    ms = check()
    RESULT["bus"] = dict(model=ms.get("carmodel"), carhp=ms.get("carhp"), secs=round(time.time() - t0))
    P.set_view("third"); time.sleep(1.0); M.shot("ft_bus")
    ev(f"in the bus (model {ms.get('carmodel')}, carhp {ms.get('carhp')}) after {time.time() - t0:.0f}s")
    RESULT["stage"] = "bus"
    car = bus_xy

    def on_stop(i, st):
        RESULT["pickups"] = i + 1; RESULT["stage"] = st.name
        ev(f"group {i + 1} ({st.name}) aboard; carhp {DI.car_hp()}")

    n, r = H.pickups(world, STOPS, MSGS, car=None, check=check, view_switch=None, shops=SHOPS, on_stop=on_stop)
    if r != "aboard": return f"group {n + 1}: {r}"
    # the drop-off: out of the bus there, clear of it; the scientist blows it up
    r = H.drop_off(world, DROP, MSGS, check=check, shops=SHOPS, arrived_keys=["2312"], get_out=True, clear=8.0,
                   label="the SRS Research Center")
    RESULT["stage"] = "dropoff"
    if r in ("complete", "failed", "dead"): return r
    if r != "delivered": return f"drop-off: {r}"
    t1 = time.time(); n = 0
    while time.time() - t1 < 150:
        o = over()
        if o: return o
        if time.time() - t1 > 4 + 6 * n and n < 4: M.shot(f"ft_bus_burn{n}"); n += 1
        s = D.wait_state()
        if s["driving"]: M.leave_car(); H.walk_clear(world, dist=8.0, away=DROP[:2])
        time.sleep(1.0)
    return over() or "timeout: the bus not destroyed"


def main():
    D.start(); D.wait_state(40)
    if not game_alive(): return "frozen at start"
    MSGS.poll()
    try:
        r = play()
    except Over as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    o = over()
    if o and r not in ("complete", "failed", "dead"): r = f"{o} ({r})"
    ev(f"mission {JOB}: {r}")
    time.sleep(2.5); M.shot("ft_end"); time.sleep(2.0); M.shot("ft_end2")
    RESULT["result"] = r; RESULT["messages"] = MSGS.seen[-50:]
    RESULT["horn_events"] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in H.EVENTS]
    RESULT["deliver_events"] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in DI.EVENTS]
    with open("/out/ft_result.json", "w") as f: json.dump(RESULT, f, indent=1)
    say("RESULT", r)
    return r


if __name__ == "__main__":
    main()
