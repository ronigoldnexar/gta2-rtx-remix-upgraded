#!/usr/bin/env python3
"""SWAT VAN SWIPE! (Downtown, the Yakuza red phone 97.5,245.5 on a roof, wil_yh1.mis): steal a model
(skills/steal_car.py) and deliver it (skills/deliver_intact.py) under a wanted level. MISSIONS-BATCH3.

What the script wants (assets-src/missions/wil_m/wil_yh1.mis):
  1980 title, 1341 brief; IS_CHARACTER_IN_MODEL (p1, SWATVAN) -> 1342 and the arrow on Johnny Zoo's
  garage 43.5,249.5 (STORE_CAR_CHARACTER_IS_IN, door10 targeted at that van); out of a SWAT van
  1343 (arrow removed); the van IS_CAR_IN_BLOCK (43.5,249.5, 3 x 1) -> PARK (the game drives it
  into the garage); HAS_PARK_FINISHED -> 1350, 1124, $60,000. The van wrecked during the park ->
  1125. No timer; death or arrest end it.

A SWAT van (model 52) only comes with the police at three stars. Developer aids, each marked in
/out/marks.txt: missions/mb3_respect.exe sets the Yakuza (gang 0) respect to 100 (the red phone wants 4 bars;
a fresh session has 0); [devtools] force_wanted=3 keeps his wanted level at three stars so the
police send a SWAT van without a massacre first, and is set back to -1 (off) the moment he sits in
the van (the game's own wanted level stays and decays as it would); SVS_WARP_PHONE=1 warps him to
the street below the phone's roof (the 100-block trip from the district start is not the job).

Steps: the phone (skills/rooftop_access: one flight up, answer, down), a borrowed car to a road
near the garage (SVS_WAIT, default 62.5,245.5), three stars, steal_car (SWATVAN), stars off,
deliver_intact into the garage block, then the game's own PARK.

Run (keys script missions/keys_swat_van_swipe.sh):
  GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0 INI_SED='s/^scene_key=.*/scene_key=F11/' \\
  gamerun/grun.sh svs1 1500 missions/keys_swat_van_swipe.sh -e WARP_OK=0 -e SVS_WARP_PHONE=1 \\
      -e GTA2DX9_SCENE_NO_CAR=1 -e GTA2DX9_STATE_EVERY=5
Summary /out/svs_result.json; frames /out/m_svs_*.png.
"""
import json, math, os, re, subprocess, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["MISSIONS"] = " "
os.environ.setdefault("WARP_OK", "0")
import drive_lib as D
import mission_lib as M
import mission_play_wil as P          # the Downtown session: start, views, answer
from skills import steal_car as SC
from skills import deliver_intact as DI
from skills import rooftop_access as RA

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world
RA.D, RA.M, RA.P, RA.world, RA.say = D, M, P, world, say

JOB = "wil_yh1"
PHONE = (97.5, 245.5)
GARAGE = (43.5, 249.5, 3.0, 1.0)
WAIT = tuple(float(v) for v in os.environ.get("SVS_WAIT", "62.5,245.5").split(","))
SWATVAN = 52
TITLE = {"1980", "1341"}
IN_VAN, OUT_VAN = "1342", "1343"
DONE = {"1124", "1350"}
FAIL = {"1125"}
BUSTED = {"6155", "6158", "6159"}
RESULT = dict(stage="start", events=[])
SEEN = []
LOG_OFF = [0]
LIVES0 = [None]


class Over(Exception):
    pass


def ev(what):
    RESULT["events"].append(f"{time.strftime('%H:%M:%S')} {what}"); M.mark(what); say(what)


def poll():
    try:
        with open(D.LOG, "rb") as f:
            f.seek(LOG_OFF[0]); data = f.read(); LOG_OFF[0] += len(data)
    except OSError:
        return SEEN
    for k in re.findall(r"view: mission [^\n]*?msg=(\S+)", data.decode("latin-1")):
        if not SEEN or SEEN[-1] != k: SEEN.append(k)
    return SEEN


def seen(keys, since=0):
    poll(); return any(k in keys for k in SEEN[since:])


def over():
    poll()
    if any(k in DONE for k in SEEN): return "complete"
    if any(k in FAIL for k in SEEN): return "failed"
    if any(k in BUSTED for k in SEEN): return "busted"
    ms = M.mission_state() or {}
    if ms.get("health", 1) == 0 or ms.get("death", 0) != 0: return "dead"
    if LIVES0[0] is not None and ms.get("lives", LIVES0[0]) < LIVES0[0]: return "dead"
    # svs3: arrested by the SWAT troops (a 52-block jump to the station, no message key seen): a
    # jump of more than 25 blocks on foot within 6 s is a respawn (car_bomb.Job's rule)
    s = D.wait_state(2)
    if s and not WARPING[0]:
        lx = LAST_XY[0]
        if lx and not s["driving"] and not lx[2] and time.time() - lx[3] < 6.0 and math.hypot(s["x"] - lx[0], s["y"] - lx[1]) > 25:
            return "busted"
        LAST_XY[0] = (s["x"], s["y"], s["driving"], time.time())
    return None


LAST_XY = [None]
WARPING = [False]


def check():
    o = over()
    if o: raise Over(o)
    return M.mission_state() or {}


def respect(gang, value):
    """missions/mb3_respect.exe (gang_respect.c with an index accepted, after MISSIONS-BATCH2's
    b2_respect.c): gang 0 reads back with an unprintable name, so svs1's "yaku" matched nothing
    and the red phone refused (1092). The Yakuza are gang 0 in Downtown (the first SET_GANG_INFO)"""
    out = ""
    for args in ([], [str(gang), str(value)], []):
        try:
            r = subprocess.run(["wine", "/work/missions/mb3_respect.exe"] + args, capture_output=True, text=True, timeout=40).stdout.strip()
        except Exception as e:
            r = f"mb3_respect failed: {e}"
        say(f"mb3_respect {args}: {r}"); out = r
    M.mark(f"DEV AID: gang respect {gang} {value} ({' | '.join(out.splitlines()[-4:]) if out else ''})")


def set_wanted(n, why):
    try:
        t = open(M.INI, encoding="latin-1").read()
        if re.search(r"(?m)^force_wanted=", t):
            t = re.sub(r"(?m)^force_wanted=.*$", f"force_wanted={n}", t)
        else:
            t = re.sub(r"(?m)^\[devtools\]\s*$", f"[devtools]\nforce_wanted={n}", t, count=1)
        open(M.INI, "w", encoding="latin-1").write(t)
    except OSError as e:
        say("set_wanted:", e)
    M.mark(f"DEV AID: force_wanted={n} ({why})")


def phone(entry):
    respect(os.environ.get("SVS_GANG", "0"), 100)
    s = D.wait_state()
    if os.environ.get("SVS_WARP_PHONE", "0") == "1" and math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) > 30:
        near = (100.5, 241.5, 1)          # the street below the phone's roof: one flight up (route survey)
        P.set_view("classic")
        WARPING[0] = True
        for k in range(4):
            s2 = M.scene_warp(near[0], near[1], near[2], "SVS_WARP_PHONE: the street below the Yakuza red phone's roof; the climb and the job are played")
            if s2 and math.hypot(s2["x"] - near[0], s2["y"] - near[1]) < 8: break
            time.sleep(2.0)
        WARPING[0] = False; LAST_XY[0] = None
        P.set_view("third")
        RESULT["events"].append(f"phone warp to {near}")
    info = {}
    for k in range(3):
        ok, ms, info = RA.answer_roof_phone(world, entry, P.answer)
        if ok or seen(TITLE) or info.get("reached"): break
    RESULT["phone"] = {kk: v for kk, v in info.items() if kk != "path"}
    t0 = time.time()
    while time.time() - t0 < 6 and not seen(TITLE): time.sleep(0.3)
    if not seen(TITLE): return False
    if "launch" in info:
        lx, ly, ll = info["launch"]
        M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
        M.cruise_to(lx + 0.5, ly + 0.5, tol=0.45, secs=8)
        s, down = RA.descend(world, toward=WAIT, budget=300)
        M.set_avoid_phones(world, keep=None)
        RESULT["phone"]["down"] = down
    return True


def to_wait():
    """a borrowed car to the waiting road near the garage"""
    for leg in range(3):
        check()
        s = D.wait_state()
        if math.hypot(WAIT[0] - s["x"], WAIT[1] - s["y"]) < 6: return s
        if not s["driving"]:
            s = M.any_car2(world, budget=120)
            if not s["driving"]:
                M.walk3(world, WAIT[0], WAIT[1], None, tol=4.0, budget=120); continue
        ev(f"by car to the waiting road {WAIT} ({math.hypot(WAIT[0] - s['x'], WAIT[1] - s['y']):.0f} blocks)")
        P.FP["until"] = 0.0
        M.drive3(world, WAIT[0], WAIT[1], tol=4.0, budget=300, view_switch=P.view_switch, until=lambda: bool(over()))
    return D.wait_state()


def get_van():
    # svs2: three stars for 7 game minutes brought cop cars only (the HUD showed the three heads);
    # the catalogue has SWAT vans from four. The search stays at the waiting road: touring by car
    # 150 s legs (svs2) outran the response
    n = int(os.environ.get("SVS_WANTED", "4"))
    set_wanted(n, f"{n} stars so the police send a SWAT van")
    s = None
    # svs3: the van came at four stars (id 179 at 89.5,241.5, then empty at 62,246.5), but the stars
    # held by force_wanted kept the troops on him and he was arrested walking to its door. The aid
    # is dropped the moment a SWAT van is listed; the game's own level then decays as it would
    import threading
    seen_van = threading.Event()
    def watch():
        t0 = time.time()
        while not seen_van.is_set() and time.time() - t0 < 900:
            if any(c["model"] == SWATVAN for c in M.cars()):
                seen_van.set()
                c = next(c for c in M.cars() if c["model"] == SWATVAN)
                set_wanted(-1, f"a SWAT van is listed at {c['x']:.1f},{c['y']:.1f} (driver {c['driver']}): the aid off")
                return
            time.sleep(0.5)
    threading.Thread(target=watch, daemon=True).start()
    try:
        s = SC.steal_car(world, [SWATVAN], search=[WAIT, (WAIT[0] + 6, WAIT[1])],
                         budget=float(os.environ.get("SVS_STEAL_SECS", "600")), check=lambda: bool(over()),
                         view_switch=P.view_switch)
    finally:
        seen_van.set()
        ms = M.mission_state() or {}
        set_wanted(-1, f"off again (in model {ms.get('carmodel')}, wanted {ms.get('wanted')})")
    check()
    ok = bool(s and s.get("driving")) and (M.mission_state() or {}).get("carmodel") == SWATVAN
    t0 = time.time()
    while ok and time.time() - t0 < 4 and not seen({IN_VAN}): time.sleep(0.3)
    return ok


def deliver():
    since = len(poll())
    done = lambda: seen(DONE) or bool(over())
    r = DI.deliver(world, GARAGE, car=None, check=check, done=done, view_switch=P.view_switch,
                   label="Johnny Zoo's garage", budget=600, park_wait=45)
    t0 = time.time()
    while time.time() - t0 < 40 and not seen(DONE) and not over(): time.sleep(0.5)
    return r


def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == JOB)
    M.mark(f"mission {JOB}: SWAT VAN SWIPE! (missions/swat_van_swipe.py, skills/steal_car.py, skills/deliver_intact.py)")
    poll()
    if not phone(entry):
        return f"phone: no title (messages {SEEN[-5:]}, {RESULT.get('phone')})"
    ms = M.mission_state() or {}
    LIVES0[0] = ms.get("lives"); M.LIVES0[0] = LIVES0[0]
    RESULT["stage"] = "phone"; ev(f"phone answered: SWAT VAN SWIPE! ({SEEN[-4:]})")
    P.set_view("third"); M.shot("m_svs_phone")
    to_wait()
    RESULT["stage"] = "waiting road"
    for k in range(3):
        if get_van(): break
        check()
        ev(f"no SWAT van (try {k + 1})")
    else:
        return "no SWAT van"
    ms = check()
    RESULT["stage"] = "in the van"
    ev(f"in the SWAT van (carhp {ms.get('carhp')}, wanted {ms.get('wanted')}, messages {SEEN[-3:]})")
    M.shot("m_svs_invan")
    for k in range(3):
        r = deliver()
        ev(f"deliver: {r}")
        if seen(DONE) or over(): break
        s = D.wait_state()
        if not s["driving"] or (M.mission_state() or {}).get("carmodel") != SWATVAN:
            # pulled out of the van by the police or out to unstick: back in it (or another)
            s = DI.board(world, None, check=check)
            if not (s and s.get("driving")):
                if not get_van(): return "lost the van"
    if seen(DONE):
        for i in range(4): M.shot(f"m_svs_complete_{i}"); time.sleep(0.5)
        return "complete"
    return over() or "not delivered"


def main():
    try:
        r = play()
    except Over as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    set_wanted(-1, "end of the run")
    ms = M.mission_state() or {}
    ev(f"mission {JOB}: {r} money {ms.get('money')} lives {ms.get('lives')} health {ms.get('health')} wanted {ms.get('wanted')}")
    time.sleep(2.0); M.shot("m_svs_end")
    RESULT["result"] = r; RESULT["messages"] = SEEN[-40:]; RESULT["steal_stats"] = dict(SC.STATS)
    with open("/out/svs_result.json", "w") as f: json.dump(RESULT, f, indent=1)
    say("RESULT", JOB, r)
    M.mark(f"done swat_van_swipe={r}")
    return r


if __name__ == "__main__":
    main()
