#!/usr/bin/env python3
"""HOT DOG HOMICIDE! (Industrial file bil, the Russians' green phone 187.5,76.5 L6, bil_re1.mis): the
proof job of the bus skill (gamerun/skills/bus.py, SKILL-BUS, Wave M).

What the script wants (assets-src/missions/bil_m/bil_re1.mis):
  3854 title, 3400 brief, STOP_CHARS_GETTING_OFF_BUS; nine Russians with machine guns wait at the
  meat plant (182-185, 22-26, z 2);
  IS_CHARACTER_IN_MODEL (p1, BUS) -> 3401 (the bus stored); out of it 3402 / back in 3424;
  IS_BUS_FULL (p1) in the bus -> KILL_ALL_PASSENGERS (the load vanishes), twice; after the second:
  3403, door7 (184,30, bottom) automatic, the arrow at 184,31; the bus wrecked before that: 3423 and
  the count starts again (not a fail);
  IS_CAR_IN_BLOCK (bus, 184,30, 2 x 2) -> PARK (door7), HAS_PARK_FINISHED -> 30 frames, 3404, the
  arrow at 185.5,24.5 z 4 (on top of The Cage);
  LOCATE_CHARACTER_ON_FOOT 1 x 1 there -> 3407: six "drones" groups are walked through the plant and
  killed; he must stay on foot in the 7 x 5 box round it until all six are dead, else 3414 + 3730
  (JOB FAILED);
  then the Hot Dog Van at 194,24 (3415), in it 3416, the arrow at 13,120; IS_CAR_IN_BLOCK (van,
  12,120, 2 x 2) -> PARK (door8, 12,119, opens to the east), the van wrecked 3419 + 3730;
  HAS_PARK_FINISHED -> 3420, 3100 JOB COMPLETE, $40,000.

Run (speed 2, no video):
  GTA2_SPEED=2 FPS=0 GTA2_DIRECT_KEYS=1 SWAP_LEVEL=bil INI_SED='s/^scene_key=.*/scene_key=F11/' \\
    gamerun/grun.sh hd1 2400 missions/keys_hot_dog_homicide.sh -e GTA2DX9_STATE_EVERY=5 -e DISTRICT=bil \\
    -e WARP_OK=0 -e HD_WARP_PHONE=1 -e GTA2DX9_SCENE_NO_CAR=1
HD_WARP_PHONE=1: the developer scene warp to the street by the phone (the walk from the district
start is not the job; marked). HD_RESPECT=0: the Russians' respect set to 0 bars first if it is
below (a failed Russian job in the same session refuses the phone, 3104), marked.
Summary /out/hd_result.json; milestone frames /out/m_hd_*.png, /out/m_bus_*.png.
"""
import json, math, os, subprocess, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["DISTRICT"] = "bil"
os.environ["MISSIONS"] = " "
import drive_lib as D
import mission_lib as M
import mission_play_districts as P
from skills import bus as B
from skills import deliver_intact as DI
from skills.truck_trailer import Msgs

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world

JOB = "bil_re1"
PHONE = (187.5, 76.5)
GARAGE = (184.0, 30.0, 2.0, 2.0)       # IS_CAR_IN_BLOCK (bus, 184, 30, 2, 2); door7 bottom -> from the south
CAGE = (185.5, 24.5, 3)                # z 4 -> lid level 3
CAGE_BOX = (185.5, 24.5, 7.0, 5.0)
VAN = (194.0, 24.0)
DINER = (12.0, 120.0, 2.0, 2.0)        # door8 (12,119) RIGHT: the van comes from the east
SHOPS = []    # the Industrial respray tunnels are not surveyed yet: no respray detours
TITLE = "3854"
FAIL = {"3730", "3414", "3419"}
DONE = {"3100", "3420"}
RESULT = dict(stage="start", events=[], loads=0)
MSGS = Msgs(start_at_end=False)
LIVES0 = [None]
STARTED = [False]


class Over(Exception):
    pass


def ev(what):
    RESULT["events"].append(f"{time.strftime('%H:%M:%S')} {what}"); M.mark(what); say(what)


def over():
    if not STARTED[0]: return None
    MSGS.poll()
    i = max((j for j, k in enumerate(MSGS.seen) if k == TITLE), default=0)
    seen = MSGS.seen[i:]
    if any(k in DONE for k in seen): return "complete"
    if any(k in FAIL for k in seen): return "failed"
    ms = M.mission_state() or {}
    if ms.get("msg") in ("6155", "6159"): return "busted"
    if LIVES0[0] is not None and ms.get("lives", LIVES0[0]) < LIVES0[0]: return "dead"
    return None


def check():
    o = over()
    if o: raise Over(o)
    return M.mission_state() or {}


def respect(gang, value=None):
    args = ["wine", "/work/skills/gang_respect.exe"] + ([gang, str(value)] if value is not None else [])
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=40).stdout.strip()
    except Exception as e:
        out = f"gang_respect failed: {e}"
    for line in out.splitlines(): say(line)
    if value is not None: M.mark(f"DEV AID: gang_respect {gang} {value}")
    return out


def phone():
    entry = next(m for m in world.db["missions"] if m.get("mission") == JOB)
    if os.environ.get("HD_RESPECT", "") != "":
        respect("russ", int(os.environ["HD_RESPECT"]))
    s = D.wait_state()
    if os.environ.get("HD_WARP_PHONE", "0") == "1" and math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) > 40:
        # the east stair (row 75, from 197 up to 190) is the way up (mission_play_districts): warp to
        # the street at its foot
        near = M.street_cell_near(world, 199.5, 75.5, radius=8)
        if near:
            P.set_view("classic")
            M.scene_warp(near[0], near[1], near[2], "HD_WARP_PHONE: to the street by the Russians' stair; the job starts at the phone")
            P.set_view("third"); RESULT["events"].append(f"phone warp to {near}")
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    k0 = MSGS.mark()
    ok, key = P.answer(entry)
    MSGS.poll(); new = MSGS.seen[k0:]
    M.shot("hd_phone")
    M.set_avoid_phones(world, keep=None)
    if TITLE not in new and "3400" not in new:
        return f"phone: no title (ok={ok} key={key} messages {new})"
    STARTED[0] = True
    LIVES0[0] = (M.mission_state() or {}).get("lives")
    ev(f"phone answered: HOT DOG HOMICIDE! (messages {new})")
    return None


# ------------------------------------------------------------------ the loads

LOADS = {"n": 0, "seen_aboard": 0}


def loads_done():
    """the script took the second load: 3403 (or the garage arrow)"""
    MSGS.poll()
    return "3403" in MSGS.seen


def load_taken():
    """IS_BUS_FULL -> KILL_ALL_PASSENGERS: the passengers counted aboard vanish at once. The first
    load has no brief; this test watches the aboard count fall from its peak to 0"""
    n = B.passengers()
    if n > LOADS["seen_aboard"]: LOADS["seen_aboard"] = n
    if LOADS["seen_aboard"] >= 3 and n <= 1:
        LOADS["n"] += 1; RESULT["loads"] = LOADS["n"]
        ev(f"load {LOADS['n']} taken (peak {LOADS['seen_aboard']} aboard, now {n})")
        LOADS["seen_aboard"] = 0
        return True
    return False


def full_test():
    """the second load's brief 3403. The passengers are not in the renderer's peds line once aboard
    (hd3: no ped with car model 11 in 18 minutes), so the first load cannot be seen; the money the
    game pays per passenger is logged by the bus skill instead"""
    return loads_done()


def to_bus_stops():
    r = B.fill(world, full_test, district="bil", check=check, drive=B.bus_drive, budget=1500)
    ev(f"bus stops: {r}; loads {LOADS['n']}; stats {B.STATS}")
    return r


def into_garage():
    ev("to the meat plant's garage (door7)")
    r = DI.deliver(world, GARAGE, car=None, check=check, shops=SHOPS,
                   done=lambda: (MSGS.poll() and "3404" in MSGS.seen))
    ev(f"garage: {r}")
    t0 = time.time()
    while time.time() - t0 < 40 and "3404" not in MSGS.poll(): time.sleep(0.5)
    return "3404" in MSGS.seen


def on_the_cage():
    s = D.wait_state()
    if s["driving"]: M.leave_car()
    P.set_view("third")
    ev("on foot to the top of The Cage (185.5,24.5 z 4)")
    for k in range(3):
        s = M.walk3(world, CAGE[0], CAGE[1], CAGE[2], tol=0.35, budget=200)
        if "3407" in MSGS.poll(): break
        P.nudge_to(CAGE[0], CAGE[1], tol=0.15, tries=10)
        if "3407" in MSGS.poll(): break
    M.shot("hd_cage")
    ok = "3407" in MSGS.seen
    ev(f"cage: {'3407 (on top)' if ok else 'not on it'} at {s['x']:.1f},{s['y']:.1f} z {s['z']:.2f}")
    if not ok: return False
    # stand still in the box until the drones are dead: the hot-dog van's brief 3415
    t0 = time.time(); n = 0
    while time.time() - t0 < 300 / D.SPEED * 2:
        check()
        if "3415" in MSGS.poll(): break
        s = D.wait_state()
        if math.hypot(s["x"] - CAGE[0], s["y"] - CAGE[1]) > 1.5:
            M.cruise_to(CAGE[0], CAGE[1], tol=0.3, secs=4)
        if time.time() - t0 > 6 + 15 * n and n < 6: M.shot(f"hd_cage{n}"); n += 1
        time.sleep(1.0)
    return "3415" in MSGS.seen


def van_to_diner():
    o = M.objective()
    vx, vy = (o[0], o[1]) if o and math.hypot(o[0] - VAN[0], o[1] - VAN[1]) < 6 else VAN
    ev(f"to the Hot Dog Van at {vx:.1f},{vy:.1f}")
    s = P.enter_parked(vx, vy, budget=200, why="the Hot Dog Van")
    if not s["driving"]: return "not in the van"
    M.shot("hd_van")
    r = DI.deliver(world, DINER, car=None, check=check, shops=SHOPS,
                   done=lambda: bool(set(MSGS.poll()) & DONE))
    ev(f"diner: {r}")
    return r


def play():
    r = phone()
    if r: return r
    RESULT["stage"] = "phone"
    t0 = time.time(); buses = 0
    while not loads_done() and time.time() - t0 < 3000 / D.SPEED * 1.0 + 1200:
        # a wrecked or lost bus is not a fail here (3423: the count starts again): another bus
        s = D.wait_state()
        if s["driving"] and not B.in_bus(s): M.leave_car()
        s = B.get_bus(world, budget=1200, check=lambda: bool(over()))
        check()
        if not B.in_bus(): return "no bus"
        buses += 1; RESULT["buses"] = buses
        RESULT["stage"] = "bus"; M.shot(f"hd_bus{buses}")
        r = to_bus_stops()
        check()
        if loads_done(): break
        s = D.wait_state()
        if s["driving"] and M.car_burning(): M.leave_car()
    if not loads_done(): return f"loads: {r}"
    RESULT["stage"] = "loads"
    if not into_garage(): return "bus not parked"
    RESULT["stage"] = "garage"
    if not on_the_cage(): return "the cage"
    RESULT["stage"] = "cage"
    r = van_to_diner()
    RESULT["stage"] = "van"
    return over() or r


def main():
    D.start(); D.wait_state(40)
    MSGS.poll()
    try:
        r = play()
    except Over as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    o = over()
    if o and r not in ("complete", "failed", "dead", "busted"): r = f"{o} ({r})"
    ev(f"mission {JOB}: {r}")
    time.sleep(2.5); M.shot("hd_end"); time.sleep(2.0); M.shot("hd_end2")
    RESULT["result"] = r; RESULT["messages"] = MSGS.seen[-60:]
    RESULT["bus_events"] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in B.EVENTS]
    RESULT["bus_stats"] = B.STATS
    RESULT["deliver_events"] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in DI.EVENTS]
    with open("/out/hd_result.json", "w") as f: json.dump(RESULT, f, indent=1)
    say("RESULT", r)
    return r


if __name__ == "__main__":
    main()
