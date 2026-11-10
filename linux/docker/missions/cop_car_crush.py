#!/usr/bin/env python3
"""COP CAR CRUSH! (Downtown, Zaibatsu green phone 208.5,57.5 on the HQ's level-4 terrace, wil_ze1):
the proof job of the crusher-and-crane skill (gamerun/skills/crusher_crane.py, SKILL-CRUSHER).

What the script wants (assets-src/missions/wil_m/wil_ze1.mis):
  1982 title, 1681 brief; a COPCAR created at 206.5,38.5 (arrow on it); in it: 1685;
  Shady (CRIMINAL) at 97.5,89.5; LOCATE_CHARACTER_BY_CAR (94.5,95.5, 2 x 2) in the Cop Car -> 1690
  "Use the horn"; IS_CHAR_PRESSING_HORN in the box -> he boards (ENTER_CAR_AS_PASSENGER);
  IS_CHAR_OBJECTIVE_PASSED -> 1694 "Take Shady to the Zaibatsu Car Crusher", arrow 171.5,11.5;
  LOCATE_CHARACTER_BY_CAR (171.5,11.5, 24 x 8) -> 1697 "Get out of the Cop Car and let the crane take
  over"; IS_CAR_CRUSHED -> 1689, 1124 JOB COMPLETE, +$20,000.
  Fails (1125): the Cop Car wrecked (1683) or sunk (1684), Shady dead (1692/1687); death or arrest.

Steps, each a Wave M skill module (none of the shared libraries is changed):
  the phone: skills/rooftop_access (climb on foot, answer, come down; no warp);
  the Cop Car: deliver_intact.board; Shady: horn_pickup.pickup; the crusher leg and the crane:
  skills/crusher_crane.crush (the fragile drive to the lane mouth, the creep up the lane to the
  hook, out, clear, the crane).

    python3 /work/missions/cop_car_crush.py        (inside the container, after to_level.sh)
Env: CCC_WARP_PHONE=1 (the developer scene warp onto the terrace instead of the climb; marked).
Marks /out/marks.txt, frames /out/m_ccc_*.png and /out/m_crusher_*.png, summary /out/ccc_result.json.
"""
import json, math, os, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["MISSIONS"] = " "
os.environ.setdefault("WARP_OK", "0")
os.environ.setdefault("DI_CHASE_LEG", "1")     # MISSIONS-BATCH2: the long Cop Car legs by chase_path (skills/deliver_intact.py)
import drive_lib as D
import mission_lib as M
import mission_play_wil as P          # the session: start, calibration, views, answer
from skills import deliver_intact as DI
from skills import horn_pickup as H
from skills import crusher_crane as CC
from skills import rooftop_access as RA

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world
RA.D, RA.M, RA.P, RA.world, RA.say = D, M, P, world, say

JOB = "wil_ze1"
COPCAR = (206.5, 38.5)
SHADY = H.Stop("shady", 94.5, 95.5, 2.0, 2.0, horn_keys=(), aboard_keys=("1694",), man=(97.5, 89.5))
YARD = (171.5, 11.5, 24.0, 8.0)
FAIL = {"1125", "1683", "1684", "1687", "1692"}
DONE = {"1124", "1689"}
RESULT = dict(stage="start", events=[])
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


def chase():
    P.set_view("third")


def chase_shot(tag):
    chase(); time.sleep(0.6); M.shot(f"ccc_{tag}")


OWN_KEYS = {"1982", "1681"}
OTHER_KEYS = {"1113", "1161", "1983"}      # "already on a job" / the WHEELER-DEALING phone (ccc6: 1161, 1113)


def step_answer(entry):
    """MISSIONS-BATCH2: the answer from the launch cell (one block east of the phone) as small aimed
    steps in the classic view (P.nudge_to: no router, no sideways unstick). mg_ccc5 stuck 1.3 south of
    the phone in walk3 and never answered; mg_ccc6's walk3 unstick wandered onto WHEELER-DEALING's phone
    two cells north (1161, 1113) and started the wrong job. Between steps: back to the launch cell's
    line if he drifts north of y 58.25; step off east and on again when the phone stays silent.
    Falls back to the session's answer (P.answer) after the tries"""
    px, py = entry["x"], entry["y"]
    m0 = MSGS.mark()
    M.arrows_baseline()
    def heard():
        MSGS.poll(); new = MSGS.seen[m0:]
        if any(k in OWN_KEYS for k in new): return "own"
        if any(k in OTHER_KEYS for k in new): return "other"
        return None
    for k in range(4):
        t0 = time.time()
        while time.time() - t0 < CC._scale(10):
            h = heard()
            if h: break
            s = D.wait_state()
            if not s or s["driving"]: break
            if s["y"] > py + 0.75:                     # toward the neighbour (208.5,59.5): back south
                P.nudge_to(s["x"], py, tol=0.2, tries=3); continue
            P.nudge_to(px, py, tol=0.12, tries=4)
            time.sleep(0.4)
        h = heard()
        if h: break
        M.mark(f"step_answer: phone silent after try {k + 1}; off east and on again")
        P.nudge_to(px + 1.15, py, tol=0.2, tries=8); time.sleep(0.6)
    h = heard()
    M.mark(f"step_answer: {h or 'nothing'} (messages {MSGS.seen[m0:]})")
    ms = dict(M.mission_state() or {})
    if h == "own":
        ms["msg"] = next(k for k in MSGS.seen[m0:] if k in OWN_KEYS); return True, ms
    if h == "other": return False, ms
    return P.answer(entry)


def phone(entry):
    if os.environ.get("CCC_WARP_PHONE", "0") == "1":
        os.environ["WARP_OK"] = "1"
        ok, ms = P.answer(entry)
        os.environ["WARP_OK"] = "0"
        return ok, ms, {"warp": True}
    for k in range(3):
        g0 = M.frames_rendered()
        ok, ms, info = RA.answer_roof_phone(world, entry, step_answer if os.environ.get("CCC_STEP_ANSWER", "1") == "1" else P.answer)
        if ok or info.get("reached"): break
        # the climb's budget is wall time: a governor pause (ccc1: 16 min) spends it with the game
        # frozen. Try again while little game time went by
        gs = D.game_seconds(M.frames_rendered() - g0)
        M.mark(f"rooftop: launch cell not reached after {gs:.0f} game-s (try {k + 1}); again")
        if gs > 600: break
    if not ok: return ok, ms, info
    lx, ly, ll = info["launch"]
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    M.cruise_to(lx + 0.5, ly + 0.5, tol=0.45, secs=8)
    s, down = RA.descend(world, toward=COPCAR, budget=300)
    M.set_avoid_phones(world, keep=None)
    info["down"] = down
    return ok, ms, info


def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == JOB)
    M.mark(f"mission {JOB}: COP CAR CRUSH! (missions/cop_car_crush.py, skills/crusher_crane.py)")
    t0 = time.time()
    ok, ms, info = phone(entry)
    MSGS.poll(); chase_shot("phone")
    RESULT["phone"] = {k: v for k, v in info.items() if k != "path"}
    if not ok and "1982" not in MSGS.seen and "1681" not in MSGS.seen: return f"phone not answered ({info})"
    if "1982" not in MSGS.seen and "1681" not in MSGS.seen and not M.objective():
        return f"phone: no title ({MSGS.last()})"
    LIVES0[0] = (M.mission_state() or {}).get("lives")
    RESULT["stage"] = "phone"; ev(f"phone answered after {time.time() - t0:.0f}s (messages {MSGS.last()})")
    # the Cop Car
    s = None
    for k in range(3):
        check()
        s = DI.board(world, COPCAR, check=check)
        if s and s["driving"]: break
    if not (s and s["driving"]): return "could not board the Cop Car"
    ms = check()
    RESULT["copcar"] = dict(model=ms.get("carmodel"), carhp=ms.get("carhp"), wanted=ms.get("wanted"), secs=round(time.time() - t0))
    RESULT["stage"] = "copcar"; ev(f"in the Cop Car (model {ms.get('carmodel')}, carhp {ms.get('carhp')}, wanted {ms.get('wanted')})")
    chase_shot("copcar")
    # Shady
    r = H.pickup(world, SHADY, MSGS, car=None, check=check, shops=DI.SHOPS["wil"])
    if r != "aboard": return f"Shady: {r}"
    RESULT["stage"] = "shady"; ev(f"Shady aboard (carhp {DI.car_hp()}, wanted {(M.mission_state() or {}).get('wanted')})")
    chase_shot("shady")
    # the crusher
    m0 = MSGS.mark()
    r = CC.crush(world, "wil", "crane1", car=None, check=check, shops=DI.SHOPS["wil"], chase=chase,
                 done=lambda: MSGS.since(DONE, m0), shot_prefix="ccc_crane", budget=900)
    RESULT["stage"] = "crane"; RESULT["crush"] = r
    ev(f"crusher_crane.crush: {r} (messages {MSGS.last()})")
    t1 = time.time()
    while time.time() - t1 < CC._scale(20) and not over(): time.sleep(0.5)
    return over() or r


def main():
    MSGS.poll()
    try:
        r = play()
    except Over as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    o = over()
    if o and r not in ("complete", "failed", "dead"): r = f"{o} ({r})"
    ms = M.mission_state() or {}
    ev(f"mission {JOB}: {r} money {ms.get('money')} msg {ms.get('msg')}")
    time.sleep(2.0); chase_shot("end"); time.sleep(2.0); chase_shot("end2")
    RESULT["result"] = r; RESULT["messages"] = MSGS.seen[-60:]
    for mod, name in ((CC, "crusher_events"), (H, "horn_events"), (DI, "deliver_events")):
        RESULT[name] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in mod.EVENTS]
    RESULT["rooftop"] = dict(RA.STATS)
    with open("/out/ccc_result.json", "w") as f: json.dump(RESULT, f, indent=1)
    say("RESULT", r)
    M.mark(f"done {JOB}={r}")


if __name__ == "__main__":
    main()
