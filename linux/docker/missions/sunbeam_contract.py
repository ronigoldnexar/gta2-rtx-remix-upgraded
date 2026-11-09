#!/usr/bin/env python3
"""SUNBEAM CONTRACT! (Industrial file bil, the Hare Krishna yellow phone 235.5,132.5 on a level-2/3 terrace,
bil_km2.mis): meet a convert, draw out the Russian assassins, kill all three. MISSIONS-BATCH4-2 (Wave M),
on skills/gunfight.py and the BATCH2 helpers (b2_common).

The script (assets-src/missions/bil_m/bil_km2.mis): title 3843, brief 3148 and an arrow on a Krishna convert
at 224,186.5 (stand within 2: he joins his group, 3120 and the arrow to 202.5,34.5, the Russian zone).
In the Russian zone (IS_CHAR_IN_GANGZONE) the job watches the player's Russian respect: at -1 an assassin
with a pistol is created at 218.5,51.5 (3126), at -3 one with a Molotov at 123.5,77.5 (3127), at exactly -5
one with a shotgun at 145,77 (3128); each is told to KILL the player. Each death 3129/3130; all three dead:
3141, 3100 JOB COMPLETE, $60,000. Death or arrest ends it. No timer.

Developer aids, each marked in /out/marks.txt: Hare Krishna respect 60 (the yellow phone wants 2 bars), and
the player's Russian respect lowered to -1, -3, -5 in the zone in turn, one assassin at a time, in place of
killing Russians until the game lowers it (the script's own trigger, the number of kills it takes is
not the job). The phone's street is reached by the scene warp as COSSACK CONVERSION did (SC_WARP_PHONE=0 to walk
the 200 blocks), and SC_WARP_ZONE=1 does the same to the Russian zone (used for tuning the fight); the terrace is
climbed on foot. Everything else is played.

Run (keys script missions/keys_sunbeam_contract.sh):
  SWAP_LEVEL=bil GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0 \\
  INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' \\
  gamerun/grun.sh <name> 2400 missions/keys_sunbeam_contract.sh -e DISTRICT=bil -e WARP_OK=0 -e GTA2DX9_SCENE_NO_CAR=1
Frames /out/m_sb_*.png and /out/m_gf_*.png, marks /out/marks.txt, summary /out/sb_result.json.
"""
import math, os, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["DISTRICT"] = "bil"
os.environ["MISSIONS"] = " "
import drive_lib as D
import mission_lib as M
import mission_play_districts as P          # starts the session: level, views, world
from skills import gunfight as G
from missions import b2_common as B

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world
NAME = "bil_km2"
PHONE = (235.5, 132.5)
PHONE_STREET = (238.5, 138.5, 1)
GUN = (227.5, 133.5)                       # the job's own machine gun on the terrace
CONVERT = (224.0, 186.5)
ZONE = (202.5, 34.5)
R = B.Result("/out/sb_result.json")
MSG = B.Msgs()
TITLE = {"3843", "3148"}
DONE_KEYS = {"3100", "3141"}
FAIL = {"3730", "3149"}          # 3149: the convert died (mb43_s6: the run went on 25 minutes to the zone without him; no assassin was ever made)
BUSTED = {"6155", "6158", "6159", "4209", "4207", "4208"}     # 4207/4208: arrested (mb43_a2: respawned at the police station, 135 blocks away, no gun)
# (respect to set, message the job shows when that assassin is created)
STAGES = [(-1, "3126", "pistol", "3129"), (-3, "3127", "molotov", "3130"), (-5, "3128", "shotgun", "3141")]
# the death messages 3129, 3130; the script shows nothing for the third (its second "= 2" test should be 3), so the
# last fight ends on JOB COMPLETE (3141, 3100)
ASSASSINS = set()
ANCHOR = ZONE
ENGAGE = float(os.environ.get("SC_ENGAGE", "18"))    # BATCH4-3: shoot the marked Buicks from 15-20 blocks (the shotgun man kills at 10-20)


class Over(Exception):
    pass


def check():
    keys = MSG.keys()
    if any(k in DONE_KEYS for k in keys): raise Over("complete")
    if any(k in FAIL for k in keys): raise Over("failed")
    if any(k in BUSTED for k in keys): raise Over("busted")
    ms = M.mission_state() or {}
    if ms.get("health", 1) == 0 or ms.get("death", 0) != 0: raise Over("dead")
    if M.LIVES0[0] is not None and ms.get("lives", 99) < M.LIVES0[0]: raise Over("dead (life lost)")
    return ms


def phone(entry):
    s = D.wait_state()
    if os.environ.get("SC_WARP_PHONE", "1") == "1" and math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) > 30:
        P.set_view("classic")
        for _ in range(4):
            s2 = M.scene_warp(PHONE_STREET[0], PHONE_STREET[1], PHONE_STREET[2], "SC_WARP_PHONE: the street below the Krishna phone's terrace; the climb and the job are played")
            if s2 and math.hypot(s2["x"] - PHONE_STREET[0], s2["y"] - PHONE_STREET[1]) < 8: break
            time.sleep(2.0)
        P.set_view("third")
        R.ev(f"phone warp to {PHONE_STREET}")
    M.set_avoid_phones(world, keep=PHONE)
    M.walk3(world, PHONE[0], PHONE[1] + 1.5, 2, tol=0.4, budget=240)
    P.nudge_to(PHONE[0], PHONE[1], tol=0.12, tries=16)
    t0 = time.time()
    while time.time() - t0 < 8 and not MSG.saw(TITLE): time.sleep(0.5)
    M.set_avoid_phones(world, keep=None)
    return MSG.saw(TITLE)


def to_point(x, y, label, tol=2.0, park=5.0):
    """a car to the nearest road to (x, y), out, the rest on foot into the box. BATCH4-3 (mb43_s1): a hit on a cop ended
    the drive 270 blocks short and the 270-block walk got nowhere; so a new car and a new drive, up to 5 times"""
    for attempt in range(5):
        s = D.wait_state()
        if math.hypot(x - s["x"], y - s["y"]) < max(14, park): break
        if not s["driving"]:
            s = B.any_car(world, toward=(x, y), budget=240, view_switch=P.view_switch)
        check()
        if s and s["driving"]:
            P.FP["until"] = 0.0
            s = M.drive3(world, x, y, tol=park, budget=420, view_switch=P.view_switch)
            check()
            s = D.wait_state()
            if s["driving"] and math.hypot(x - s["x"], y - s["y"]) < max(14, park + 2):
                hold("Down", 0.4); s = M.leave_car(); P.set_view("third")
            elif s["driving"]:
                R.ev(f"{label}: drive ended {math.hypot(x - s['x'], y - s['y']):.0f} blocks short, in the car (attempt {attempt})")
        else:
            R.ev(f"{label}: no car (attempt {attempt})")
        s = D.wait_state(); d = math.hypot(x - s["x"], y - s["y"])
        if d >= 14: R.ev(f"{label}: {d:.0f} blocks short at {s['x']:.1f},{s['y']:.1f} (attempt {attempt})")
        # mb43_s3: gridlock 37 blocks short (a standing car in the lane, 3 drives of 420 s): the rest on foot
        if d < max(60, park + 20): break      # mb43_s4: after a burned car the steal-car chase took the player 150 blocks the wrong way
    s = D.wait_state()
    if s["driving"]:
        hold("Down", 0.4); M.leave_car(); P.set_view("third")
    M.walk3(world, x, y, None, tol=0.8, budget=150)
    check()
    R.ev(f"{label}: at {D.wait_state()['x']:.1f},{D.wait_state()['y']:.1f}")


SPAWNS = [(218.5, 51.5), (123.5, 77.5), (145.0, 77.0)]      # where the script creates the three assassins
T_TRIGGER = [None]
PRE = set()          # every ped seen before the trigger: not an assassin


def hostile(p):
    """an assassin: gang/russian created at a spawn point after the trigger (sc4/sc5: Russian civilians also drive
    Buicks and the car-rider rule shot two of them, a wanted level and an arrest) or carrying a job arrow; once picked he stays picked"""
    if "russ" not in str(p["gang"]).lower(): return False
    # (the spawn rule only in the 15 s after the trigger: sc6 took Russian civilians driving past the spawn point)
    if T_TRIGGER[0] and time.time() - T_TRIGGER[0] < 15 and p["id"] not in ASSASSINS and p["id"] not in PRE and \
            any(math.hypot(p["x"] - x, p["y"] - y) < 6.0 for x, y in SPAWNS):
        ASSASSINS.add(p["id"])
    if p["mark"] is not None: ASSASSINS.add(p["id"])
    return p["id"] in ASSASSINS


def fight(label, dead_key, secs):
    [hostile(p) for p in M.peds()]
    M.mark(f"gunfight skill: {label}")
    r = G.gunfight(world, select=hostile, check=check, secs=secs, done=lambda: MSG.saw({dead_key}), engage=ENGAGE, far=34.0, close=2.5, close_car=ENGAGE - 3.0, low=45, hunt=999.0, anchor=ANCHOR, leash=3.0,
                   shot_prefix="gf_sb")
    ms = M.mission_state() or {}
    R.ev(f"gunfight {label}: {r} {dict(G.STATS)} (health {ms.get('health')}, msg {ms.get('msg')})")
    return r


def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == NAME)
    M.mark(f"mission {NAME}: SUNBEAM CONTRACT! (missions/sunbeam_contract.py, skills/gunfight.py)")
    M.mark("developer aid: Hare Krishna respect set to 60 (yellow phone needs 2 bars; a fresh game has 0)")
    B.respect("0", 60)         # Industrial: gang 0 is the Krishna (name unreadable), 1 Zaibatsu, 2 Russians
    if not phone(entry):
        return f"phone not answered ({MSG.keys()[-5:]})"
    M.LIVES0[0] = (M.mission_state() or {}).get("lives"); M.arm_lives(); G.arm_job()
    R.d["stage"] = "phone"; R.ev(f"phone answered ({MSG.keys()[-4:]})"); M.shot("sb_phone")
    M.walk3(world, GUN[0], GUN[1], 2, tol=0.35, budget=90)
    for k in range(6):
        if M.gun_ready(): break
        M.cruise_to(GUN[0] + 0.3 * math.cos(k * 2.1), GUN[1] + 0.3 * math.sin(k * 2.1), tol=0.15, secs=3)
    ms = M.mission_state() or {}
    R.ev(f"gun: {ms.get('weapon')} ammo {ms.get('ammo')}")
    M.walk3(world, PHONE_STREET[0], PHONE_STREET[1], 1, tol=1.0, budget=120)
    check()
    # the convert
    R.d["stage"] = "convert"
    # mb43_a2/a1/s6: a car pulled up at the convert ran him (or his Krishna group) down: 3149 / 4208, the job lost; so out at 16 blocks, the rest on foot
    to_point(CONVERT[0], CONVERT[1], "the convert", park=16.0)
    t0 = time.time()
    while time.time() - t0 < 12 and not MSG.saw({"3120"}):
        P.nudge_to(CONVERT[0], CONVERT[1], tol=0.5, tries=2); check()
    # sc15: the convert had walked off (no 3120 in 12 s): to the nearest Krishna on foot, then he joins
    for k in range(6):
        if MSG.saw({"3120"}): break
        s = D.wait_state()
        kr = [p for p in M.peds() if p["gang"] == "krishna" and M.ped_alive(p)]
        if kr:
            c = min(kr, key=lambda p: math.hypot(p["x"] - s["x"], p["y"] - s["y"]))
            R.ev(f"convert: not joined yet; to the Krishna at {c['x']:.1f},{c['y']:.1f}")
            M.walk3(world, c["x"], c["y"], None, tol=1.0, budget=40)
        time.sleep(2.0); check()
    if not MSG.saw({"3120"}): return f"the convert never joined ({MSG.keys()[-4:]})"
    R.ev(f"convert: messages {MSG.keys()[-3:]}"); M.shot("sb_convert")
    # the Russian zone
    R.d["stage"] = "zone"
    if os.environ.get("SC_WARP_ZONE", "0") == "1":
        P.set_view("classic")
        for _ in range(4):
            s2 = M.scene_warp(ZONE[0], ZONE[1] + 2.0, 1, "SC_WARP_ZONE: the Russian zone's arrow (the 170-block drive is not the fight)")
            if s2 and math.hypot(s2["x"] - ZONE[0], s2["y"] - ZONE[1] - 2.0) < 8: break
            time.sleep(2.0)
        P.set_view("third")
        R.ev("zone warp")
    # mb43_a1/s3: the lane at 165,35 (37 blocks short) is gridlocked: the car burned there and killed the player; the drive stops at 40 blocks and the rest is on foot
    to_point(ZONE[0], ZONE[1], "the Russian zone arrow", park=40.0)
    s = D.wait_state()
    if math.hypot(ZONE[0] - s["x"], ZONE[1] - s["y"]) > 12: return f"never reached the zone (at {s['x']:.0f},{s['y']:.0f})"
    t0 = time.time()
    while time.time() - t0 < 20 and not MSG.saw({"3122"}): check(); time.sleep(0.5)
    R.ev(f"in the zone: {MSG.saw({'3122'})} (messages {MSG.keys()[-3:]})"); M.shot("sb_zone")
    M.select_gun()
    ms = M.mission_state() or {}
    R.ev(f"before the fight: health {ms.get('health')} weapon {ms.get('weapon')} ammo {ms.get('ammo')} wanted {ms.get('wanted')}")
    # the respect byte is in bars of 20 (sc3: -1 did nothing, -20 tripped the -1 bar check). sc7: the molotov and
    # shotgun assassins, created 80-100 blocks west (123.5,77.5 and 145,77), never reached the zone in 10 minutes
    # (the job slows their cars to 0.4 off screen): one poke to -5 bars brings all three out at once, the pistol
    # man comes to the zone and the other two are met where they were made
    R.d["stage"] = "assassins"
    PRE.update(p["id"] for p in M.peds()); T_TRIGGER[0] = time.time()
    # sc8: -100 straight away trips the -1 bar assassin only (3126); each bar in turn trips its own (sc7)
    for val, key, gun, dead_key in STAGES:
        M.mark(f"DEV AID: Russian respect set to {val * 20} in the zone (the job's trigger for the {gun} assassin)")
        B.respect("2", val * 20)
        t0 = time.time()
        while time.time() - t0 < 8 and not MSG.saw({key}): check(); time.sleep(0.5)
    R.ev(f"assassin triggers: {[k for k in ('3126', '3127', '3128') if MSG.saw({k})]}")
    # sc9/sc11/sc14: the molotov and shotgun men come to the zone only some of the time (sc9: in one Buick at 180,34
    # within a minute as the player drove west; sc11: not in 10 minutes standing still; sc14: the shotgun man killed
    # the player on a 100-block walk to the spawn points, outside any fight). So a patrol on the zone's street,
    # on foot, in the fight, 60 s at each point in turn, until JOB COMPLETE (the script shows nothing for the third death)
    R.d["stage"] = "fight"
    legs = [ZONE, (190.5, 34.5), (213.5, 34.5), (202.5, 34.5), (190.5, 34.5), (213.5, 34.5)]
    # mb43_s5: only the pistol man came in 8 minutes (s2: all three in 30 s); after six idle legs the patrol goes
    # to the molotov and shotgun men's own spawn points (the first-person-fight lesson: they stand there if their car is stuck)
    legs += [(190.5, 34.5), (160.5, 34.5), (145.0, 60.0), (145.0, 77.0), (123.5, 77.5), (145.0, 77.0), (160.5, 34.5), (190.5, 34.5)]
    for k in range(int(os.environ.get("SC_LEGS", "16"))):
        global ANCHOR
        ANCHOR = legs[k % len(legs)]
        r = fight(f"assassins leg {k}", "3141", float(os.environ.get("SC_SECS", "60")))
        R.ev(f"leg {k} at {ANCHOR}: fight {r}; messages {MSG.keys()[-4:]}")
        check()
    t0 = time.time()
    while time.time() - t0 < 40: check(); time.sleep(0.5)
    return "no JOB COMPLETE"


def main():
    try:
        r = play()
    except (Over, G.JobOver) as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    finally:
        xdo("keyup", "Control_L")
    if r == "complete": P.set_view("third"); B.shots("sb_complete", n=4, gap=0.5)
    ms = M.mission_state() or {}
    R.ev(f"mission {NAME}: {r} money {ms.get('money')} lives {ms.get('lives')}")
    time.sleep(2.0); M.shot("sb_end")
    R.d["result"] = r; R.d["messages"] = MSG.keys(); R.save()
    say("RESULT", NAME, r)
    M.mark(f"done sunbeam_contract={r}")


if __name__ == "__main__":
    main()
