#!/usr/bin/env python3
"""OPERATION Z! (Residential file ste, the Zaibatsu yellow phone 224.5,34.5 L3, ste_zm1.mis): the
truck-and-trailer skill's job runner (gamerun/skills/truck_trailer.py, SKILL-BUS, Wave M).

Why this job: DISTRACTION ACTION! (ste_zh2, the hitched truck) is the red phone's SECOND job; after
a failed MURDER IN THE MALL! (zh1) the phone answers 6173 ("pitiful displays") and never offers zh2
(sessions da2, da3: docs/skill-truck-trailer.md). OPERATION Z is the first job of its phone.

The yellow phone wants Zaibatsu respect >= 2 bars: skills/gang_respect.exe sets 60 (a developer aid,
marked). OZ_WARP_PHONE=1: the developer scene warp to the street by the phone (marked).

What the script wants (assets-src/missions/ste_m/ste_zm1.mis), four cars into the Village garage
(door1 at 211,31 z 3, opens to the south; IS_CAR_IN_BLOCK 211,31,3 2 x 2, then PARK):
  1. the pill Pickup at 6,108.5 (four Rednecks with machine guns beside it, LINE_OF_SIGHT): in it
     2643, out 2644, wrecked 2645 + 2998, parked 2646;
  2. a Stratos-B at 12,173.5 with a Scientist gunman at the wheel (2647 when he sees the player):
     in it 2649, wrecked 2648, parked 2651;
  3. Bean's Limo at 56,70.5 among five cars (2652): in it 2654, wrecked 2653, parked 2656;
  4. any truck cab (TRUKCAB1/2: 2667, the arrow on the transporter TRUKTRNS at 86,224.5 with a Cop
     Car on it); hitched -> 2661, the arrow at the crane 250.5,39.5 (IS_CAR_IN_BLOCK cab 3 x 3); the
     crane lifts the Cop Car off (GET_CAR_INFO_FROM_CRANE) -> 2662, the arrow on the Cop Car; in it
     2665 (arrow 211,33); parked -> 2663, 2999, $50,000. The trailer wrecked 2659, the Cop Car off the
     trailer before the crane 2664 (fails). Out of the cab: 2657 / 2658; trailer off: 2660.
Run:
  GTA2_SPEED=2 FPS=0 GTA2_DIRECT_KEYS=1 SWAP_LEVEL=ste INI_SED='s/^scene_key=.*/scene_key=F11/' \\
    gamerun/grun.sh oz1 3600 missions/keys_operation_z.sh -e GTA2DX9_STATE_EVERY=5 -e DISTRICT=ste \\
    -e WARP_OK=0 -e OZ_WARP_PHONE=1 -e GTA2DX9_SCENE_NO_CAR=1
Env OZ_LEGS=1234 (which legs to play; a later leg can only be played after the earlier ones).
Summary /out/oz_result.json; frames /out/m_oz_*.png.
"""
import json, math, os, subprocess, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["DISTRICT"] = "ste"
os.environ["MISSIONS"] = " "
import drive_lib as D
import mission_lib as M
import mission_play_districts as P
from skills import truck_trailer as T
from skills import deliver_intact as DI

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world

JOB = "ste_zm1"
PHONE = (224.5, 34.5)
GARAGE = (211.0, 31.0, 2.0, 2.0)
PICKUP = (6.0, 108.5)
STRATOS = (12.0, 173.5)
LIMO = (56.0, 70.5)
CABS_PARKED = [(38.5, 26.5), (9.5, 46.5)]       # ste.mis PARKED_CAR_DATA TRUKCAB1
TRAILER = (86.0, 224.5)
CRANE = (250.5, 39.5, 3.0, 3.0)
SHOPS = [((6.5, 183.5), (9.6, 183.5)), ((178.5, 216.5), (181.6, 216.5)),
         ((215.5, 76.5), (218.6, 76.5)), ((94.5, 27.5), (97.6, 27.5))]   # fake_truce.py (SKILL-HORN)
TITLE = "2466"
FAIL = {"2998", "2645", "2648", "2653", "2659", "2664"}
DONE = {"2999", "2663"}
RESULT = dict(stage="start", events=[], legs=[])
MSGS = T.Msgs(start_at_end=False)
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
    if LIVES0[0] is not None and ms.get("lives", LIVES0[0]) < LIVES0[0]: return "dead"
    return None


def check():
    o = over()
    if o: raise Over(o)
    return M.mission_state() or {}


def respect(gang, value):
    try:
        out = subprocess.run(["wine", "/work/skills/gang_respect.exe", gang, str(value)], capture_output=True, text=True, timeout=40).stdout.strip()
    except Exception as e:
        out = f"gang_respect failed: {e}"
    M.mark(f"DEV AID: gang_respect {gang} {value} ({out.splitlines()[-1] if out else ''})")


def seen(key):
    MSGS.poll(); return key in MSGS.seen


def phone():
    respect("zaib", 60)
    entry = next(m for m in world.db["missions"] if m.get("mission") == JOB)
    s = D.wait_state()
    if os.environ.get("OZ_WARP_PHONE", "0") == "1" and math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) > 30:
        near = M.street_cell_near(world, PHONE[0] - 6, PHONE[1] + 4, radius=10)
        if near:
            P.set_view("classic")
            M.scene_warp(near[0], near[1], near[2], "OZ_WARP_PHONE: to the street by the Zaibatsu yellow phone; the job starts at the phone")
            P.set_view("third")
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    k0 = MSGS.mark()
    ok, key = P.answer(entry)
    t0 = time.time()
    while time.time() - t0 < 6 and TITLE not in MSGS.poll()[k0:]: time.sleep(0.3)
    M.set_avoid_phones(world, keep=None); M.shot("oz_phone")
    new = MSGS.seen[k0:]
    if TITLE not in new: return f"phone: no title (messages {new})"
    STARTED[0] = True; LIVES0[0] = (M.mission_state() or {}).get("lives")
    ev(f"phone: OPERATION Z! ({new})")
    return None


def drive_near(x, y, stop=7.0, budget=480):
    """a car (any), to a road cell `stop` blocks short of (x,y)"""
    s = D.wait_state()
    if math.hypot(x - s["x"], y - s["y"]) < stop + 4: return s
    if not s["driving"]:
        st = M.street_cell_near(world, s["x"], s["y"], radius=8)
        if st and world.level(s) > 1: M.walk3(world, st[0], st[1], None, tol=1.0, budget=90)
        s = M.any_car2(world, budget=150)
    if s["driving"]:
        dx, dy = s["x"] - x, s["y"] - y; n = math.hypot(dx, dy) or 1
        c = M.street_cell_near(world, x + dx / n * stop, y + dy / n * stop, radius=6) or (x, y, 1)
        for leg in range(3):
            P.FP["until"] = 0.0
            s = M.drive3(world, c[0], c[1], tol=2.5, budget=budget, view_switch=P.view_switch, until=lambda: bool(over()))
            check()
            if not s["driving"] or math.hypot(c[0] - s["x"], c[1] - s["y"]) < 5: break
            if not s["driving"]: s = M.any_car2(world, budget=90)
    return D.wait_state()


def guards_alive(x, y, r=4.5, remap=5):
    return [p for p in M.peds() if p.get("remap") == remap and M.ped_alive(p) and p["car"] is None
            and math.hypot(p["x"] - x, p["y"] - y) < r]


def clear_guards(x, y, remap=5, secs=150):
    """run the Pickup's Rednecks over from a borrowed car (they shoot on sight; on foot is death)"""
    t0 = time.time()
    while time.time() - t0 < secs:
        check()
        g = guards_alive(x, y, remap=remap)
        if not g: ev("leg 1: the guards are down"); return True
        s = D.wait_state()
        if not s["driving"]:
            s = M.any_car2(world, budget=60)
            if not s["driving"]: continue
        r, k = M.run_over(world, [remap], set(), set(FAIL), (x, y), secs=20, radius=8)
        say(f"leg 1: run_over {r} kills {k}; {len(guards_alive(x, y, remap=remap))} guards left")
    return not guards_alive(x, y, remap=remap)


def take_car(xy, key_in, why):
    o = M.objective()
    cx, cy = (o[0], o[1]) if o and o[3] in (3, 4) and math.hypot(o[0] - xy[0], o[1] - xy[1]) < 8 else xy
    s = D.wait_state()
    if s["driving"]: M.leave_car(); P.set_view("third")
    for k in range(3):
        check()
        s = P.enter_parked(cx, cy, budget=150, why=why)
        if s["driving"] and seen(key_in): break
        if s["driving"] and not seen(key_in):
            time.sleep(1.5)
            if seen(key_in): break
            M.leave_car()
    ok = seen(key_in)
    ev(f"{why}: {'in it' if ok else 'not in it'} (carhp {(M.mission_state() or {}).get('carhp')})")
    return ok


def to_garage(done_key, why):
    ev(f"{why}: to the Village garage")
    r = DI.deliver(world, GARAGE, car=None, check=check, shops=SHOPS, done=lambda: seen(done_key), label="the Village garage")
    t0 = time.time()
    while time.time() - t0 < 30 and not seen(done_key): time.sleep(0.5)
    ev(f"{why}: {r}; parked {seen(done_key)}")
    M.shot(f"oz_{why.split()[0]}_parked")
    return seen(done_key)


def leg1():
    s = drive_near(*PICKUP, stop=9.0)
    clear_guards(*PICKUP)
    if not take_car(PICKUP, "2643", "pickup"): return False
    return to_garage("2646", "pickup leg")


def leg2():
    drive_near(*STRATOS, stop=8.0)
    if not take_car(STRATOS, "2649", "stratos"): return False
    return to_garage("2651", "stratos leg")


def leg3():
    drive_near(*LIMO, stop=8.0)
    if not take_car(LIMO, "2654", "limo"): return False
    return to_garage("2656", "limo leg")


def leg4():
    # a cab: the nearer parked TRUKCAB1, else steal one
    s = D.wait_state()
    cab = min(CABS_PARKED, key=lambda c: math.hypot(c[0] - s["x"], c[1] - s["y"]))
    drive_near(*cab, stop=6.0)
    if D.wait_state()["driving"]: M.leave_car()
    P.set_view("third")
    s = P.enter_parked(cab[0], cab[1], budget=150, why="the parked truck cab")
    if not T.in_cab(s):
        if s["driving"]: M.leave_car()
        s = T.get_cab(world, budget=600, check=lambda: bool(over()))
    if not T.in_cab(): return False
    ev(f"leg 4: in a cab (model {D.wait_state().get('cmodel')}); 2667 {seen('2667')}")
    M.shot("oz_cab")
    # to the transporter, then back onto it
    c = M.street_cell_near(world, TRAILER[0], TRAILER[1] - 8, radius=6) or (TRAILER[0], TRAILER[1] - 8, 1)
    P.FP["until"] = 0.0
    M.drive3(world, c[0], c[1], tol=3.0, budget=480, view_switch=P.view_switch, slow=True, until=lambda: bool(over()))
    check()
    r = T.hook_up(world, trailer=TRAILER, budget=240, check=check, attached=lambda: seen("2661"))
    ev(f"leg 4: hook up {r}")
    M.shot("oz_hitched")
    if not seen("2661"): return False
    lost = lambda: (MSGS.poll() and MSGS.seen[-1] == "2660")
    r = T.crane_drop(world, CRANE, done=lambda: seen("2662"), check=check, budget=900, lost=lost)
    ev(f"leg 4: crane {r}")
    if not seen("2662"): return False
    s = D.wait_state()
    if s["driving"]: M.leave_car()
    o = M.objective()
    cop = (o[0], o[1]) if o else (CRANE[0], CRANE[1])
    if not take_car(cop, "2665", "cop car"): return False
    return to_garage("2663", "cop car leg")


def play():
    r = phone()
    if r: return r
    RESULT["stage"] = "phone"
    legs = os.environ.get("OZ_LEGS", "1234")
    for n, f in (("1", leg1), ("2", leg2), ("3", leg3), ("4", leg4)):
        if n not in legs: continue
        ok = f(); RESULT["legs"].append((n, ok)); check()
        if not ok: return f"leg {n} not done"
        RESULT["stage"] = f"leg{n}"
    return over() or "legs done"


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
    if o and r not in ("complete", "failed", "dead"): r = f"{o} ({r})"
    ev(f"mission {JOB}: {r}")
    time.sleep(2.5); M.shot("oz_end"); time.sleep(2.0); M.shot("oz_end2")
    RESULT["result"] = r; RESULT["messages"] = MSGS.seen[-80:]
    RESULT["truck_events"] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in T.EVENTS]
    RESULT["truck_stats"] = T.STATS
    RESULT["deliver_events"] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in DI.EVENTS]
    with open("/out/oz_result.json", "w") as f: json.dump(RESULT, f, indent=1)
    say("RESULT", r)
    return r


if __name__ == "__main__":
    main()
