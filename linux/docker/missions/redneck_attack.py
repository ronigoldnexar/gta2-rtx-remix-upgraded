#!/usr/bin/env python3
"""REDNECK ATTACK! (Residential file ste, ste_sm3.mis): the SRS Scientists' follow-up job, offered on
the yellow phone 206.5,227.5 once LABRAT'S PLAN! (ste_sm1) is passed, played by the on-foot gunfight
skill (gamerun/skills/gunfight.py). MISSIONS-BATCH1, Wave M.

A fresh session cannot get this job without its prerequisite, so this runner plays LABRAT'S PLAN
first (missions/labrats_plan.py, unchanged, in the same session) and then answers the phone again.

The script (assets-src/missions/ste_m/ste_sm3.mis): title 2461, brief 2415; three generators
(POWERGEN at 178.5 / 173.5 / 168.5, 248.5: the field strip south of the road rows 244-246) with
three Scientists with machine guns beside them; the arrow on the middle one until it is on screen
(IS_ITEM_ACCURATELY_ONSCREEN), then brief 2416 and a 120 s timer (3599 frames). Meanwhile three
Rednecks with machine guns walk in (from 177.5,193.5, 124.5,193.5 and 201.5,171.5, GOTO_AREA to
x,244.5) with an arrow each, get rocket launchers on arrival and DESTROY_OBJECT the generators;
each one killed is created again at his start. All three generators dead: 2420, JOB FAILED (2998).
At the timer's end: 2421/2422/2423 by the generators lost (3 / 2 / 1 left: $50,000 / 30,000 /
10,000), JOB COMPLETE (2999).

The defence: the fight held on the field north of the middle generator (anchor 173.5,242.6, on the
Rednecks' way in), hostiles = the marked Rednecks (and any Redneck within the anchor's reach), the
Scientists spared; the gunfight skill in rounds until the job's verdict.

Run (keys script missions/keys_redneck_attack.sh):
  SWAP_LEVEL=ste GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0 gamerun/grun.sh <name> 3000 missions/keys_redneck_attack.sh
Env: RA_SKIP_LP=1 skips LABRAT'S PLAN (only useful in a session where it is already passed).
Frames /out/m_ra_*.png, /out/m_gf_ra*.png; summary /out/ra_result.json (and lp_result.json).
"""
import json, math, os, sys, time
sys.path.insert(0, "/work")
import missions.labrats_plan as LP          # starts the session (mission_play_districts) on import
from missions.labrats_plan import D, M, P, G, world, say, hold, ev

NAME = "ste_sm3"
GENS = [(178.5, 248.5), (173.5, 248.5), (168.5, 248.5)]
ANCHOR = (173.5, 242.6)
APPROACH_ROAD = (173.5, 245.0)
TITLE = {"2461", "2415", "2416"}
RESULT = dict(stage="start", events=[], rounds=[])
STARTED = [False]


def check():
    if not STARTED[0]: return M.mission_state() or {}
    o, ms = G.job_state()
    if o not in ("running", "unknown"): raise LP.Over(o)
    return ms or {}


MARKED = set()
def hostile(p):
    if p["gang"] != "redneck": return False
    if p["id"] in MARKED: return True
    if p["mark"] is not None or math.hypot(p["x"] - ANCHOR[0], p["y"] - ANCHOR[1]) < 12:
        MARKED.add(p["id"]); return True
    return False


def answer_again(entry):
    """after LABRAT'S PLAN: back to the phone; the game offers the follow-up there"""
    t0 = time.time()
    while time.time() - t0 < 12:            # the JOB COMPLETE banner and the save first
        time.sleep(1.0)
    G.arm_job()                              # a fresh message window: LABRAT'S 2999 is behind us
    P.APPROACH[(entry["x"], entry["y"])] = LP.PHONE_WAY
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    for k in range(2):
        ok, key = P.answer(entry)
        ms = M.mission_state() or {}
        RESULT["events"].append(f"phone {k + 1}: {ok} {key} msg {ms.get('msg')}")
        M.mark(f"redneck_attack: phone {k + 1}: {ok} {key} msg {ms.get('msg')}")
        o = M.objective()
        if ms.get("msg") in TITLE or (o and math.hypot(o[0] - GENS[1][0], o[1] - GENS[1][1]) < 3):
            M.set_avoid_phones(world, keep=None); return True
        ax, ay = M.step_off_phone(world, entry); M.cruise_to(ax, ay, tol=0.5, secs=6); time.sleep(3.0)
    M.set_avoid_phones(world, keep=None)
    return False


def to_gens():
    s = D.wait_state()
    if math.hypot(ANCHOR[0] - s["x"], ANCHOR[1] - s["y"]) > 25:
        for k in range(3):
            check(); s = D.wait_state()
            if not s["driving"]: s = M.any_car2(world, budget=120)
            if not (s and s["driving"]): continue
            P.FP["until"] = 0.0
            M.drive3(world, APPROACH_ROAD[0], APPROACH_ROAD[1], tol=3.0, budget=300, view_switch=P.view_switch)
            s = D.wait_state()
            if math.hypot(ANCHOR[0] - s["x"], ANCHOR[1] - s["y"]) < 15: break
    s = D.wait_state()
    if s["driving"]:
        hold("space", 0.4); M.leave_car()
    P.set_view("third")
    M.select_gun(4)
    M.walk3(world, ANCHOR[0], ANCHOR[1], None, tol=0.8, budget=60)
    return D.wait_state()


def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == LP.NAME)
    if os.environ.get("RA_SKIP_LP", "0") != "1":
        LP.STARTED[0] = False
        try:
            r1 = LP.play()
        except (LP.Over, G.JobOver) as e:
            r1 = str(e)
        o, _ = G.job_state()
        if o == "complete": r1 = "complete"
        RESULT["labrats_plan"] = r1
        ev(f"prerequisite LABRAT'S PLAN: {r1}")
        with open("/out/lp_result.json", "w") as f: json.dump(dict(LP.RESULT, result=r1), f, indent=1)
        if r1 != "complete": return f"prerequisite {r1}"
        M.shot("m_ra_lp_done")
    LP.STARTED[0] = False
    if not answer_again(entry): return "phone: no REDNECK ATTACK"
    STARTED[0] = True; M.arm_lives(); G.arm_job()
    RESULT["stage"] = "phone"; M.shot("m_ra_phone")
    if not M.gun_ready() and not M.select_gun(4): LP.gun(budget=240)
    ms = M.mission_state() or {}
    ev(f"REDNECK ATTACK started (msg {ms.get('msg')}, ammo {ms.get('ammo')}, health {ms.get('health')})")
    to_gens(); check()
    RESULT["stage"] = "generators"; M.shot("m_ra_gens")
    t0 = time.time(); k = 0
    while time.time() - t0 < float(os.environ.get("RA_SECS", "600")):
        check(); k += 1
        try:
            r = G.gunfight(world, select=hostile, spare=LP.spare, check=check, secs=90, clear=None,
                           engage=9.0, close=3.0, far=26.0, anchor=ANCHOR, leash=6.0, low=40,
                           police="shoot", shot_prefix=f"gf_ra{k}")
        except G.JobOver as e:            # the skill's jump check (see labrats_plan.fight): the job decides
            o, ms = G.job_state()
            if o not in ("running", "unknown"): raise
            r = f"skill said {e}"
        st = dict(G.STATS); RESULT["rounds"].append(dict(result=r, stats=st))
        ms = M.mission_state() or {}
        ev(f"defence round {k}: {r} {st} (health {ms.get('health')}, ammo {ms.get('ammo')}, msg {ms.get('msg')})")
        M.shot(f"m_ra_round{k}")
        if ms.get("ammo", 0) < 30 and not M.select_gun(4): LP.gun(budget=120)
    return "timeout"


def main():
    try:
        r = play()
    except (LP.Over, G.JobOver) as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    o, ms = G.job_state()
    if o == "complete" and STARTED[0]: r = "complete"
    ms = M.mission_state() or {}
    ev(f"mission {NAME}: {r} money {ms.get('money')} lives {ms.get('lives')} msg {ms.get('msg')}")
    for i in range(3):
        M.shot(f"m_ra_end{i}"); time.sleep(0.6)
    RESULT["result"] = r
    with open("/out/ra_result.json", "w") as f: json.dump(RESULT, f, indent=1)
    say("RESULT", NAME, r)
    M.mark(f"done redneck_attack={r}")


if __name__ == "__main__":
    main()
