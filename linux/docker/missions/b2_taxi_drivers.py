#!/usr/bin/env python3
"""TAXI DRIVERS MUST DIE! (Downtown file wil, the Loonies' red phone 58.5,20.5, wil_lh1.mis), played in
the street views by MISSIONS-BATCH2 (Wave M) with the steal-car, gunfight and crusher skills.

What the script wants (assets-src/missions/wil_m/wil_lh1.mis; texts e.gxt):
  1973 title, 1741 brief: taxi 1 (CREATE_CAR 132.5,55.5 TAXI, an aggressive criminal driver, the
  arrow on it). In it: 1748, the arrow on the driver; he must die (the player may leave the taxi:
  1750 "get back in", 1751 back in). Dead: 1749 and the arrow to the South Docks crusher yard
  (LOCATE_CHARACTER_BY_CAR 246.5,238.5, 10 x 4); 1754 in the yard; IS_CAR_CRUSHED and the car
  in the RIGHT crusher's block (244.5,243.5, 3 x 1): 1767, else 1755 + 1125.
  Taxi 2 (243.5,181.5): its driver (pistol) and one group member walk to it and drive off; in it:
  1756, kill him and his man (1757/1758 out/in); 1759 the crusher; 1760 in the yard; crushed: 1761.
  Taxi 3 (162.5,149.5): driver and a group of 4 (pistols); 1762; 1764/1763; 1765 the crusher;
  1766 in the yard; crushed: 1752 + 1124 JOB COMPLETE, +$60,000.
  Fails: taxi wrecked 1746 / sunk 1747 / 1742-1744 (taxi 2-3 lost before boarding) -> 1125.
The red phone wants Loonies respect >= 4 bars: missions/b2_respect.exe sets 80 at the start
(developer aid, marked). B2_WARP_PHONE=1 (default) warps him to the street by the Loonies' yard
(marked WARP): the 150 blocks from the district start are not this job.

Run (keys script missions/keys_b2_taxi_drivers.sh):
  GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0 \\
  INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' \\
  gamerun/grun.sh <name> 2400 missions/keys_b2_taxi_drivers.sh -e GTA2DX9_SCENE_NO_CAR=1
Frames /out/m_tx_*.png, marks /out/marks.txt, summary /out/tx_result.json.
"""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
from skills import steal_car as SC
from skills import gunfight as G
from skills import crusher_crane as CC
from skills import deliver_intact as DI
from skills import destroy_vehicle as DV
from missions import b2_common as B
from skills import shake_police as SP

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
JOB = "wil_lh1"
PHONE = (58.5, 20.5)
PHONE_ROAD = (62.5, 14.5, 1)      # the pavement east of the yard (route3: 62,14 -> 62,18 -> 59,19 L2 -> phone)
GUN = (76.5, 39.5)                 # machine-gun pickup in the Loonies' yard (after the phone: the PIZZA CAKE and
                                   # RADIO ZA-ZA phones beside it then only say "busy")
TAXI = SC.model_ids("TAXI")
R = B.Result("/out/tx_result.json")
FAIL = {"1125", "1746", "1747", "1742", "1743", "1744", "1755"}
STEPS = [  # (name, in-the-taxi key, killed key, crushed key)
    dict(name="taxi1", at=(132.5, 55.5), inside={"1748"}, killed={"1749"}, yard={"1754"}, crushed={"1767"}),
    dict(name="taxi2", at=(243.5, 181.5), inside={"1756"}, killed={"1759"}, yard={"1760"}, crushed={"1761"}),
    dict(name="taxi3", at=(162.5, 149.5), inside={"1762"}, killed={"1765"}, yard={"1766"}, crushed={"1752", "1124"}),
]
VIEW = ["classic"]


def set_view(name):
    order = ["classic", "third", "first"]
    while VIEW[0] != name:
        tap("v", 0.3); time.sleep(1.7)
        VIEW[0] = order[(order.index(VIEW[0]) + 1) % 3]
    M.CUR_VIEW[0] = name
    M.mark(f"view {name}")


FP = {"until": 0.0}


def view_switch(s):
    now = time.time()
    if FP["until"] == 0.0:
        set_view("first"); FP["until"] = now + 18; M.mark("first person at the wheel")
    elif FP["until"] > 0 and now > FP["until"]:
        set_view("third"); FP["until"] = -1


def chase():
    set_view("third")


class Over(Exception):
    pass


MSG = None


def check():
    keys = MSG.keys()
    if "1124" in keys: raise Over("complete")
    if any(k in FAIL for k in keys): raise Over("failed")
    ms = M.mission_state() or {}
    if ms.get("health", 1) == 0 or ms.get("death", 0) != 0: raise Over("dead")
    if M.LIVES0[0] is not None and ms.get("lives", 99) < M.LIVES0[0]: raise Over("dead (life lost)")
    return ms


def check_bool():
    try:
        check(); return False
    except Over:
        return True


def marked_taxi():
    return [c for c in M.cars() if c["model"] in TAXI and c["mark"] is not None and c["hp"] > 0]


def taxi_xy(default):
    t = marked_taxi()
    if t: return (t[0]["x"], t[0]["y"])
    a = DV.car_arrows()
    if a: return (a[0][1], a[0][2])
    return default


def in_marked_taxi():
    s = D.wait_state()
    return bool(s and s["driving"] and s.get("cmodel") in TAXI)


def get_taxi(st, budget=900):
    """into the marked taxi: steal_car restricted to the car with the arrow (any other taxi of the
    town is left alone), its search point re-aimed at the arrow every minute"""
    orig = SC.usable
    SC.usable = lambda c, ids: orig(c, ids) and c["mark"] is not None
    try:
        t0 = time.time()
        while time.time() - t0 < budget:
            check()
            if MSG.saw(st["inside"]) and in_marked_taxi(): return True
            xy = taxi_xy(st["at"])
            s = SC.steal_car(world, "TAXI", search=[xy], budget=60, check=check_bool, view_switch=view_switch)
            check()
            t1 = time.time()
            while time.time() - t1 < 3 and not MSG.saw(st["inside"]): time.sleep(0.3)
            if MSG.saw(st["inside"]): return True
            if s and s.get("driving"):
                R.ev("in a taxi but not the marked one: out again"); hold("Down", 0.3); M.leave_car()
        return False
    finally:
        SC.usable = orig


def crew_ids():
    """read while still in the taxi, where the arrow is on the driver (it moves back to the taxi as
    soon as the player steps out, 1750): the marked ped and every ped of his type within 6 blocks"""
    host = set()
    for k in range(10):
        ps = M.peds()
        drv = [p for p in ps if p["mark"] is not None and p["hp"] > 0]
        if drv:
            p = drv[0]; host.add(p["id"])
            for q in ps:
                if q["id"] != p["id"] and q["type"] == p["type"] and q["hp"] > 0 and math.hypot(q["x"] - p["x"], q["y"] - p["y"]) < 6:
                    host.add(q["id"])
            return host, p
        time.sleep(0.3)
    return host, None


def kill_crew(st, host, secs=400):
    """the driver and his group, fought on foot with the gunfight skill; a ped of the driver's type
    that turns up within 5 blocks of a known one is taken into the crew too"""
    types = {p["type"] for p in M.peds() if p["id"] in host}

    def select(p):
        if p["id"] in host: return True
        if p["mark"] is not None and p["car"] is None:
            host.add(p["id"]); return True
        if p["type"] in types and p["hp"] > 0:
            for q in M.peds():
                if q["id"] in host and math.hypot(q["x"] - p["x"], q["y"] - p["y"]) < 5:
                    host.add(p["id"]); R.ev(f"{st['name']}: {p['id']} ({p['type']}) taken as crew"); return True
        return False

    if not M.gun_ready() and not M.select_gun():
        R.ev("no gun in the hand: to the machine-gun pickup")
        s = D.wait_state()
        M.fetch_gun(world, budget=240, near=(s["x"], s["y"]))
    r = G.gunfight(world, select=select, done=lambda: MSG.saw(st["killed"]), check=check, secs=secs,
                   shot_prefix=f"tx_{st['name']}_gf")
    R.ev(f"{st['name']}: gunfight {r} ({G.STATS})")
    return MSG.saw(st["killed"])


def run_down(st, host, secs=300):
    """from the taxi: run the crew down instead of stepping out among them (b2_tx1: out of the taxi
    beside two officers, 100 -> 0 in 1.5 s). First away from any police (evade), then each crew
    member who comes at the car (their objective is to kill the player) is driven at, aiming two
    blocks past him so the car goes through him. Ends on the script's 'killed' message."""
    t0 = time.time(); legs = 0
    while time.time() - t0 < secs / D.SPEED:
        check()
        if MSG.saw(st["killed"]): return True
        s = D.wait_state()
        if not s["driving"]: return False
        nc, no, dmin, cen = SP.police_near(s, 25.0, 16.0)
        if (M.mission_state() or {}).get("wanted", 0) > 0 and nc + no:
            SP.evade(world, 20, check=check, view_switch=view_switch,
                     until=lambda: SP.police_near(D.wait_state(), 30.0, 20.0)[0] + SP.police_near(D.wait_state(), 30.0, 20.0)[1] == 0)
            continue
        crew = [p for p in M.peds() if p["id"] in host and p["hp"] > 0]
        if not crew:
            time.sleep(0.5); continue
        p = min(crew, key=lambda q: math.hypot(q["x"] - s["x"], q["y"] - s["y"]))
        d = math.hypot(p["x"] - s["x"], p["y"] - s["y"])
        if d > 30:
            time.sleep(0.5); continue
        ux, uy = (p["x"] - s["x"]) / max(d, 0.1), (p["y"] - s["y"]) / max(d, 0.1)
        if d < 3.0:
            # too close to build speed: back off a little, then come at him
            hold("Down", 0.6); continue
        legs += 1
        if legs % 4 == 1: R.ev(f"{st['name']}: driving at {p['id']} ({p['type']}) {d:.1f} off")
        M.drive3(world, p["x"] + ux * 2.0, p["y"] + uy * 2.0, tol=1.0, budget=5, view_switch=None,
                 until=lambda: MSG.saw(st["killed"]))
    return MSG.saw(st["killed"])


def phone(entry):
    s = D.wait_state()
    if os.environ.get("B2_WARP_PHONE", "1") == "1" and math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) > 30:
        set_view("classic")
        for _ in range(4):
            s2 = M.scene_warp(PHONE_ROAD[0], PHONE_ROAD[1], PHONE_ROAD[2], "B2_WARP_PHONE: the pavement beside the Loonies' red phone; the job starts at the phone")
            if s2 and math.hypot(s2["x"] - PHONE_ROAD[0], s2["y"] - PHONE_ROAD[1]) < 8: break
            time.sleep(2.0)
        R.ev(f"phone warp to {PHONE_ROAD}")
    M.set_avoid_phones(world, keep=PHONE)
    M.walk3(world, PHONE[0], PHONE[1], None, tol=0.35, budget=240)
    s = D.wait_state()
    if math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) > 0.3:
        for _ in range(16):
            s = D.wait_state(); d = math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"])
            if d < 0.12 or MSG.saw({"1973", "1741"}): break
            a = D.angle_to(s, *PHONE)
            if abs(a) > 0.35:
                key = "Left" if (a > 0) == (D.left_sign > 0) else "Right"
                hold(key, min(abs(a) / max(D.rate, 2.0), 0.3)); time.sleep(0.35); hold("Up", 0.12); time.sleep(0.45); continue
            hold("Up", max(0.08, min(0.4, (d - 0.05) / 1.9))); time.sleep(0.5)
    t0 = time.time()
    while time.time() - t0 < 8 and not MSG.saw({"1973", "1741"}): time.sleep(0.5)
    M.set_avoid_phones(world, keep=None)
    return MSG.saw({"1973", "1741"})


def crusher(st):
    r = CC.crush(world, "wil", "crane3", car=None, check=check, shops=DI.SHOPS["wil"], chase=chase,
                 done=lambda: MSG.saw(st["crushed"]), shot_prefix=f"tx_{st['name']}_crane", budget=900)
    t1 = time.time()
    while time.time() - t1 < CC._scale(25) and not MSG.saw(st["crushed"]):
        check(); time.sleep(0.5)
    R.ev(f"{st['name']}: crush {r} (crushed message seen: {MSG.saw(st['crushed'])})")
    return MSG.saw(st["crushed"])


def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == JOB)
    M.mark(f"mission {JOB}: TAXI DRIVERS MUST DIE! (missions/b2_taxi_drivers.py)")
    M.mark("developer aid: Loonies respect set to 80 (red phone needs 4 bars; a fresh game has 0)")
    B.respect("loon", 80)
    if not phone(entry):
        return f"phone not answered ({MSG.keys()[-5:]})"
    M.LIVES0[0] = (M.mission_state() or {}).get("lives")
    R.d["stage"] = "phone"; R.ev(f"phone answered ({MSG.keys()[-4:]})"); M.shot("tx_phone")
    set_view("third")
    # a machine gun for the drivers' fights, from the yard 25 blocks south-east
    if os.environ.get("B2_TX_GUN", "1") == "1":
        M.fetch_gun(world, budget=200, near=GUN, count=1, walk_only=True)
        R.ev(f"gun: {(M.mission_state() or {}).get('weapon')} ammo {(M.mission_state() or {}).get('ammo')}")
    for st in STEPS:
        R.d["stage"] = st["name"]
        R.ev(f"{st['name']}: to the taxi (arrow {taxi_xy(st['at'])})")
        if not get_taxi(st): return f"{st['name']}: never in the marked taxi"
        R.ev(f"{st['name']}: in the marked taxi ({MSG.keys()[-3:]})"); M.shot(f"tx_{st['name']}_in")
        if not MSG.saw(st["killed"]):
            host, drv = crew_ids()
            R.ev(f"{st['name']}: crew {sorted(host)} (driver {drv['id'] if drv else None} {drv['type'] if drv else ''} at "
                 f"{(round(drv['x'], 1), round(drv['y'], 1)) if drv else None})")
            if not run_down(st, host):
                s = D.wait_state()
                if s["driving"]: hold("Down", 0.4); M.leave_car()
                set_view("third")
                if not kill_crew(st, host): return f"{st['name']}: crew not killed"
        R.ev(f"{st['name']}: crew dead ({MSG.keys()[-3:]})"); M.shot(f"tx_{st['name']}_killed")
        for k in range(3):
            check()
            s = DI.board(world, None, check=check)
            if s and s["driving"]: break
        if not crusher(st): return f"{st['name']}: not crushed"
        B.shots(f"tx_{st['name']}_crushed", n=2)
        if st["name"] != "taxi3":
            # off the crane yard: a car for the next taxi (the steal skill's carrier)
            M.ensure_view("third")
    t0 = time.time()
    while time.time() - t0 < 15: check(); time.sleep(0.5)
    return "no JOB COMPLETE after the third crush"


def main():
    global world, MSG
    D.start()
    s = D.wait_state(40)
    if not s: sys.exit(1)
    D.calibrate_turn()
    world = M.World("wil")
    M.mark("level (wil) TAXI DRIVERS MUST DIE runner")
    M.arrows_baseline()
    M.START[0] = (s["x"], s["y"])
    M.VIEW_HOOK[0] = set_view
    set_view("third")
    MSG = B.Msgs()
    try:
        r = play()
    except Over as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    finally:
        xdo("keyup", "Control_L")
    if r == "complete": set_view("third"); B.shots("tx_complete", n=4, gap=0.5)
    ms = M.mission_state() or {}
    R.ev(f"mission {JOB}: {r} money {ms.get('money')} lives {ms.get('lives')}")
    time.sleep(2.0); M.shot("tx_end")
    R.d["result"] = r; R.d["messages"] = MSG.keys()
    for mod, name in ((CC, "crusher_events"), (DI, "deliver_events"), (DV, "dv_events")):
        R.d[name] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in getattr(mod, "EVENTS", [])]
    R.d["steal_stats"] = dict(SC.STATS)
    R.save()
    say("RESULT", JOB, r)
    M.mark(f"done b2_taxi_drivers={r}")


world = None
if __name__ == "__main__":
    main()
