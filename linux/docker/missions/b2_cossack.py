#!/usr/bin/env python3
"""COSSACK CONVERSION! (Industrial file bil, the Hare Krishna yellow phone 233.5,132.5, bil_km1.mis),
played in the street views by MISSIONS-BATCH2 (Wave M) with the horn pick-up and deliver skills.

What the script wants (assets-src/missions/bil_m/bil_km1.mis; texts e.gxt):
  3842 title, 3252 brief; a BOXTRUCK at 165.0,43.5 (the arrow on it) in the Lubyanka warehouse
  yard, six Russian guards with pistols on patrol (they raise the alarm if they see him in the
  zone: 3240, then lights, sirens and three more armed groups, 3241). A machine gun is put at
  227.5,133.5 beside the phone (COLLECT_01).
  In the truck: 3243 and an arrow to 8.5,83.5 (Mad Island docks); out of it 3244 (arrow back on
  the truck). In the 2 x 2 box there with the truck: 3245 "sound the horn"; the horn: 3246, and four
  groups of Russian workers board in turn through the back door (3247 after the second); a group
  wiped out: 3255 + 3730 (failed). All aboard: 3248 and the arrow to 238/239,112 (the Conversion
  House); the truck in IS_CAR_IN_BLOCK (239,112, 2 x 2): the game PARKs it in the garage, four
  converts walk out, 3251 + 3100 JOB COMPLETE, +$60,000. The truck wrecked: 3242 / 3249 + 3730.
The yellow phone wants Hare Krishna respect >= 2 bars: missions/b2_respect.exe sets 60 (marked).
B2_WARP_PHONE=1 (default): the developer scene warp to the street below the phone's terrace
(marked WARP); the 190 blocks from the district start are not this job.

Run (keys script missions/keys_b2_cossack.sh):
  SWAP_LEVEL=bil GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0 \\
  INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' \\
  gamerun/grun.sh <name> 2400 missions/keys_b2_cossack.sh -e DISTRICT=bil -e WARP_OK=0 -e GTA2DX9_SCENE_NO_CAR=1
Frames /out/m_ck_*.png, marks /out/marks.txt, summary /out/ck_result.json.
"""
import math, os, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["DISTRICT"] = "bil"
os.environ["MISSIONS"] = " "
import drive_lib as D
import mission_lib as M
import mission_play_districts as P          # starts the session: level, views, world
from skills import horn_pickup as H
from skills import deliver_intact as DI
from skills import gunfight as G
from missions import b2_common as B

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world
NAME = "bil_km1"
PHONE = (233.5, 132.5)
PHONE_STREET = (238.5, 138.5, 1)
GUN = (227.5, 133.5)                       # the job's own machine gun, on the same terrace as the phone
TRUCK = (165.0, 43.5)
YARD_GATE = (158.5, 43.5)                  # the road along the yard's west side; the truck is 6.5 blocks east
DOCKS = (8.5, 83.5, 2.0, 2.0)
HOUSE = (239.0, 112.0, 2.0, 2.0)
R = B.Result("/out/ck_result.json")
MSG = B.Msgs()
HM = H.Msgs()
FAIL = {"3730", "3242", "3249", "3255"}
H.SOUND_HORN.add("3245")                    # this job's "sound the horn" brief
H.BOARD_SECS = float(os.environ.get("CK_BOARD_SECS", "420"))   # four groups board one after another
H.STALL_SECS = 60.0


class Over(Exception):
    pass


def check():
    keys = MSG.keys()
    if "3100" in keys: raise Over("complete")
    if any(k in FAIL for k in keys): raise Over("failed")
    ms = M.mission_state() or {}
    if ms.get("health", 1) == 0 or ms.get("death", 0) != 0: raise Over("dead")
    if M.LIVES0[0] is not None and ms.get("lives", 99) < M.LIVES0[0]: raise Over("dead (life lost)")
    return ms


def nudge_on(x, y):
    P.nudge_to(x, y, tol=0.12, tries=16)


def phone(entry):
    s = D.wait_state()
    if os.environ.get("B2_WARP_PHONE", "1") == "1" and math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) > 30:
        P.set_view("classic")
        for _ in range(4):
            s2 = M.scene_warp(PHONE_STREET[0], PHONE_STREET[1], PHONE_STREET[2], "B2_WARP_PHONE: the street below the Krishna phone's terrace; the job starts at the phone")
            if s2 and math.hypot(s2["x"] - PHONE_STREET[0], s2["y"] - PHONE_STREET[1]) < 8: break
            time.sleep(2.0)
        P.set_view("third")
        R.ev(f"phone warp to {PHONE_STREET}")
    M.set_avoid_phones(world, keep=PHONE)
    # the terrace (level 2) from the east stair at 239,134; in along row 134 and up from the south
    M.walk3(world, PHONE[0], PHONE[1] + 1.5, 2, tol=0.4, budget=240)
    nudge_on(*PHONE)
    t0 = time.time()
    while time.time() - t0 < 8 and not MSG.saw({"3842", "3252"}): time.sleep(0.5)
    M.set_avoid_phones(world, keep=None)
    return MSG.saw({"3842", "3252"})


def truck_xy():
    return DI.mission_car_xy(TRUCK) or TRUCK


def in_truck():
    s = D.wait_state()
    return bool(s and s["driving"] and s.get("cmodel") == 7)      # BOXTRUCK, the script's model 7


def get_truck():
    """a car to the road beside the yard, out, the last blocks to the truck on foot, in, and away
    west before the guards close in"""
    s = D.wait_state()
    for leg in range(3):
        check()
        if in_truck(): return True
        s = D.wait_state()
        if math.hypot(YARD_GATE[0] - s["x"], YARD_GATE[1] - s["y"]) > 12:
            if not s["driving"]: s = B.any_car(world, toward=YARD_GATE[:2], budget=240, view_switch=P.view_switch)
            if s and s["driving"]:
                P.FP["until"] = 0.0
                s = M.drive3(world, YARD_GATE[0], YARD_GATE[1], tol=2.5, budget=420, view_switch=P.view_switch)
            if s and s["driving"] and not in_truck():
                hold("Down", 0.4); s = M.leave_car(); P.set_view("third")
        check()
        R.ev(f"at the yard ({s['x']:.1f},{s['y']:.1f}); to the truck at {truck_xy()}"); M.shot("ck_yard")
        s = DI.board(world, truck_xy(), budget=90, check=check)
        if in_truck() or MSG.saw({"3243"}): return True
    return in_truck()


def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == NAME)
    M.mark(f"mission {NAME}: COSSACK CONVERSION! (missions/b2_cossack.py, skills/horn_pickup.py, skills/deliver_intact.py)")
    M.mark("developer aid: Hare Krishna respect set to 60 (yellow phone needs 2 bars; a fresh game has 0)")
    B.respect("kris", 60)
    if not phone(entry):
        return f"phone not answered ({MSG.keys()[-5:]})"
    M.LIVES0[0] = (M.mission_state() or {}).get("lives")
    R.d["stage"] = "phone"; R.ev(f"phone answered ({MSG.keys()[-4:]})"); M.shot("ck_phone")
    # the job's machine gun on the same terrace
    M.walk3(world, GUN[0], GUN[1], 2, tol=0.35, budget=90)
    for k in range(6):
        if M.gun_ready(): break
        M.cruise_to(GUN[0] + 0.3 * math.cos(k * 2.1), GUN[1] + 0.3 * math.sin(k * 2.1), tol=0.15, secs=3)
    ms = M.mission_state() or {}
    R.ev(f"gun: {ms.get('weapon')} ammo {ms.get('ammo')}")
    M.walk3(world, PHONE_STREET[0], PHONE_STREET[1], 1, tol=1.0, budget=120)
    # the truck
    R.d["stage"] = "truck"
    if not get_truck(): return "never in the truck"
    R.ev(f"in the truck (carhp {DI.car_hp()}, messages {MSG.keys()[-3:]})"); M.shot("ck_truck")
    # the docks: horn, four groups board
    R.d["stage"] = "docks"
    stop = H.Stop("docks", DOCKS[0], DOCKS[1], DOCKS[2], DOCKS[3], horn_keys={"3246"}, aboard_keys={"3248"},
                  count=20, move=False, pick=lambda p: p["gang"] in ("russian", "russ", "russgang") or "russ" in p["type"])
    r = H.pickup(world, stop, HM, car=None, check=check, view_switch=P.view_switch, budget=1500)
    R.ev(f"docks: {r} (messages {MSG.keys()[-4:]}, carhp {DI.car_hp()})")
    if r != "aboard" and not MSG.saw({"3248"}): return f"docks {r}"
    B.shots("ck_aboard", n=2)
    # the Conversion House
    R.d["stage"] = "house"
    r = H.drop_off(world, HOUSE, HM, car=None, check=check, view_switch=P.view_switch, arrived_keys={"3251", "3100"},
                   budget=1200, label="the Conversion House")
    R.ev(f"house: {r}")
    t0 = time.time()
    while time.time() - t0 < 60: check(); time.sleep(0.5)
    return f"house {r}, no JOB COMPLETE"


def main():
    try:
        r = play()
    except Over as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    finally:
        xdo("keyup", "Control_L")
    if r == "complete": P.set_view("third"); B.shots("ck_complete", n=4, gap=0.5)
    ms = M.mission_state() or {}
    R.ev(f"mission {NAME}: {r} money {ms.get('money')} lives {ms.get('lives')}")
    time.sleep(2.0); M.shot("ck_end")
    R.d["result"] = r; R.d["messages"] = MSG.keys()
    for mod, name in ((H, "horn_events"), (DI, "deliver_events")):
        R.d[name] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in getattr(mod, "EVENTS", [])]
    R.save()
    say("RESULT", NAME, r)
    M.mark(f"done b2_cossack={r}")


if __name__ == "__main__":
    main()
