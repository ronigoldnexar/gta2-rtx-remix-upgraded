#!/usr/bin/env python3
"""COP CAR SCRAP! (Industrial file bil, the Hare Krishna green phone 249.5,201.5 on a level-4 roof,
bil_ke2.mis): steal a model three times (skills/steal_car.py) and hand each car to the Krishna crane
pair (skills/crusher_crane.py). MISSIONS-BATCH3 (Wave M).

What the script wants (assets-src/missions/bil_m/bil_ke2.mis):
  3841 title, 3480 brief (two pickups dropped at 242,197 and 248,205). Three times: in a COPCAR
  away from the yard -> 3482, the arrow at the crane yard 176.5,249.5; out of it away from the yard
  -> 3483; LOCATE_CHARACTER_BY_CAR (176.5,249.5, 7 x 7) in a Cop Car -> 3484 ("let the crane take
  it"); out of the box again 3489. crane5 (tower 176.5,249.5, rot 200) lifts the car and passes it
  to crane6 (180.5,245.5), which drops it in the block 182.5,242.5: GET_CAR_INFO_FROM_CRANE and
  CHECK_CAR_MODEL (COPCAR) -> YEEHA, 3485 after the first, 3486 after the second; another model
  3487. The third: 3488, 3100 (Industrial's JOB COMPLETE), $40,000. No timer; death or arrest end it.

Developer aids, each marked in /out/marks.txt: CCS_WARP_PHONE=1 warps him to the street below the
Krishna roof (the 200-block walk from the district start is not the job); CCS_WANTED=N (default 1)
sets [devtools] force_wanted=N only while no Cop Car is in sight after CCS_TRAFFIC_SECS of looking
in traffic, so the police come with their cars, and back to -1 the moment he sits in one.

Run (keys script missions/keys_cop_car_scrap.sh):
  SWAP_LEVEL=bil GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0 INI_SED='s/^scene_key=.*/scene_key=F11/' \\
  gamerun/grun.sh ccs1 2400 missions/keys_cop_car_scrap.sh -e DISTRICT=bil -e WARP_OK=0 \\
      -e CCS_WARP_PHONE=1 -e GTA2DX9_SCENE_NO_CAR=1 -e GTA2DX9_STATE_EVERY=5
Summary /out/ccs_result.json; frames /out/m_ccs_*.png.
"""
import json, math, os, re, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["DISTRICT"] = "bil"
os.environ["MISSIONS"] = " "
os.environ.setdefault("WARP_OK", "0")
import drive_lib as D
import mission_lib as M
import mission_play_districts as P
from skills import steal_car as SC
from skills import crusher_crane as CC
from skills import deliver_intact as DI
from skills import rooftop_access as RA

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world
RA.D, RA.M, RA.P, RA.world, RA.say = D, M, P, world, say

JOB = "bil_ke2"
PHONE = (249.5, 201.5)
YARD = (176.5, 249.5)
COPCAR = 12
# road points round the Krishna temple: row 187 (x 180-222), column 219-222, row 172, column 198-201
SEARCH = [(220.5, 187.5), (200.5, 187.5), (220.5, 175.5), (210.5, 172.5), (199.5, 200.5), (185.5, 187.5)]
TITLE = {"3841", "3480"}
IN_COP, OUT_COP, AT_YARD = "3482", "3483", "3484"
COUNT_KEYS = ("3485", "3486", "3488")
WRONG = "3487"
DONE = {"3100", "3488"}
FAIL = {"3730", "1125", "2998"}
BUSTED = {"6155", "6158", "6159"}
RESULT = dict(stage="start", events=[], cars=[])
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


def count():
    poll(); return sum(1 for k in COUNT_KEYS if k in SEEN)


def over():
    poll()
    if any(k in DONE for k in SEEN): return "complete"
    if any(k in FAIL for k in SEEN): return "failed"
    if any(k in BUSTED for k in SEEN): return "busted"
    ms = M.mission_state() or {}
    if ms.get("health", 1) == 0 or ms.get("death", 0) != 0: return "dead"
    if LIVES0[0] is not None and ms.get("lives", LIVES0[0]) < LIVES0[0]: return "dead"
    return None


def check():
    o = over()
    if o: raise Over(o)
    return M.mission_state() or {}


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
    s = D.wait_state()
    if os.environ.get("CCS_WARP_PHONE", "0") == "1" and math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) > 30:
        # ccs1: the renderer refused 238.5,192.5 L1 (no road or pavement within six blocks by its test);
        # the nearest road cell to the climb's foot (241,196) is 222,189
        near = (222.5, 189.5, 1)
        P.set_view("classic")
        for k in range(5):
            M.scene_warp(near[0], near[1], near[2], "CCS_WARP_PHONE: the street below the Hare Krishna roof; the climb and the job are played")
            time.sleep(3.0)          # a fresh sample (science_friction sf11: the warp's own read was stale)
            s2 = D.wait_state()
            if s2 and math.hypot(s2["x"] - near[0], s2["y"] - near[1]) < 8: break
            time.sleep(2.0)
        else:
            P.set_view("third"); return False
        P.set_view("third")
        RESULT["events"].append(f"phone warp to {near}")
    info = {}
    for k in range(3):
        g0 = M.frames_rendered()
        ok, ms, info = RA.answer_roof_phone(world, entry, P.answer)
        if ok or seen(TITLE) or info.get("reached"): break
        if D.game_seconds(M.frames_rendered() - g0) > 600: break
    RESULT["phone"] = {kk: v for kk, v in info.items() if kk != "path"}
    t0 = time.time()
    while time.time() - t0 < 6 and not seen(TITLE): time.sleep(0.3)
    if not seen(TITLE): return False
    if "launch" in info:
        lx, ly, ll = info["launch"]
        M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
        M.cruise_to(lx + 0.5, ly + 0.5, tol=0.45, secs=8)
        s, down = RA.descend(world, toward=YARD, budget=300)
        M.set_avoid_phones(world, keep=None)
        RESULT["phone"]["down"] = down
    return True


def in_copcar():
    s = D.wait_state()
    return bool(s and s["driving"]) and (M.mission_state() or {}).get("carmodel") == COPCAR


def get_copcar(k):
    """a Cop Car from traffic; after CCS_TRAFFIC_SECS without one, the police are called"""
    if in_copcar(): return True
    t0 = time.time()
    secs = float(os.environ.get("CCS_TRAFFIC_SECS", "240"))
    # ccs2: down from the roof he stood in the Krishna temple's walled courtyard, with no road within
    # reach; steal_car's ring tour round him found nothing to drive or see for 11 game minutes.
    # To the road (row 187) first, and tour the roads round the temple
    s = D.wait_state()
    if not s["driving"] and min(math.hypot(s["x"] - x, s["y"] - y) for x, y in SEARCH) > 6:
        ev(f"car {k}: to the road at {SEARCH[0]}")
        M.walk3(world, SEARCH[0][0], SEARCH[0][1], None, tol=1.5, budget=120)
    s = SC.steal_car(world, [COPCAR], search=SEARCH, budget=secs, check=lambda: bool(over()), view_switch=P.view_switch)
    check()
    if in_copcar():
        ev(f"car {k}: a Cop Car from traffic after {time.time() - t0:.0f}s"); return True
    n = int(os.environ.get("CCS_WANTED", "1"))
    if n < 0: return False
    set_wanted(n, f"car {k}: no Cop Car in traffic for {secs:.0f}s; the police bring theirs")
    try:
        s = SC.steal_car(world, [COPCAR], search=SEARCH, budget=float(os.environ.get("CCS_STEAL_SECS", "420")),
                         check=lambda: bool(over()), view_switch=P.view_switch)
    finally:
        set_wanted(-1, f"car {k}: off again (in model {(M.mission_state() or {}).get('carmodel')})")
    check()
    ok = in_copcar()
    ev(f"car {k}: {'a Cop Car' if ok else 'no Cop Car'} after {time.time() - t0:.0f}s (wanted {(M.mission_state() or {}).get('wanted')})")
    return ok


def scrap(k):
    n0 = count()
    r = CC.crush(world, "bil", "crane5", car=None, check=check, chase=lambda: P.set_view("third"),
                 done=lambda: count() > n0 or bool(over()), shot_prefix=f"m_ccs_crane{k}", budget=900)
    t1 = time.time()
    while time.time() - t1 < CC._scale(40) and count() <= n0 and not over(): time.sleep(0.5)
    ev(f"car {k}: crush -> {r}; count {count()} (messages {SEEN[-4:]})")
    return count() > n0


def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == JOB)
    M.mark(f"mission {JOB}: COP CAR SCRAP! (missions/cop_car_scrap.py, skills/steal_car.py, skills/crusher_crane.py)")
    poll()
    if not phone(entry):
        return f"phone: no title (messages {SEEN[-5:]}, {RESULT.get('phone')})"
    ms = M.mission_state() or {}
    LIVES0[0] = ms.get("lives"); M.LIVES0[0] = LIVES0[0]
    RESULT["stage"] = "phone"; ev(f"phone answered: COP CAR SCRAP! ({SEEN[-4:]})")
    P.set_view("third"); M.shot("m_ccs_phone")
    tries = 0
    while count() < 3 and tries < 6:
        tries += 1
        k = count() + 1
        check()
        if not get_copcar(k):
            continue
        ms = check()
        RESULT["stage"] = f"cop car {k}"
        ev(f"car {k}: in a Cop Car (carhp {ms.get('carhp')}, wanted {ms.get('wanted')}); to the Krishna crane")
        M.shot(f"m_ccs_copcar{k}")
        ok = scrap(k)
        RESULT["cars"].append(dict(k=k, ok=ok, messages=SEEN[-5:]))
        if ok: M.shot(f"m_ccs_scrapped{k}")
    t0 = time.time()
    while time.time() - t0 < 20 and not seen(DONE): time.sleep(0.5)
    if seen(DONE):
        for i in range(4): M.shot(f"m_ccs_complete_{i}"); time.sleep(0.5)
        return "complete"
    return over() or f"{count()} of 3 scrapped"


def main():
    try:
        r = play()
    except Over as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    set_wanted(-1, "end of the run")
    ms = M.mission_state() or {}
    ev(f"mission {JOB}: {r} ({count()} of 3) money {ms.get('money')} lives {ms.get('lives')} health {ms.get('health')}")
    time.sleep(2.0); M.shot("m_ccs_end")
    RESULT["result"] = r; RESULT["messages"] = SEEN[-60:]; RESULT["steal_stats"] = dict(SC.STATS)
    RESULT["crusher_events"] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in CC.EVENTS]
    with open("/out/ccs_result.json", "w") as f: json.dump(RESULT, f, indent=1)
    say("RESULT", JOB, r)
    M.mark(f"done cop_car_scrap={r}")
    return r


if __name__ == "__main__":
    main()
