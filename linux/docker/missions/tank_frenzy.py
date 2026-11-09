#!/usr/bin/env python3
"""The Downtown tank kill frenzies with the Wave M tank skill (gamerun/skills/tank.py).

    TANK_FRENZY=wil_kf08 python3 /work/missions/tank_frenzy.py     (after to_level.sh)

assets-src/missions/wil.mis:
  wil_kf08  PARKED_CAR_DATA auto50 = (3.50, 164.50, 3.00) 0 180 TANK; THREAD_WAIT_FOR_CHAR_IN_CAR
            -> START_BASIC_KF_TEMPLATE (7111, TANK_GUN); START_BONUS_CHECK (1800, 20, CAR, BY_ANY_WEAPON,
            TANK): destroy 20 vehicles from the tank in 60 s; reward LIVES 1. The tank is locked
            against the player once he leaves it.
  wil_kf07  auto49 = (226.50, 238.50, 2.00) TANK, 7101: 35 people in 60 s (CHAR); the tank stands
            in a closed courtyard (docs/actions-3d.md, Special vehicles).
The frenzy's result is the game's own: an extra life (lives + 1) when passed; its message keys are
logged. The walk to the tank is on foot (by car when it is more than 60 blocks off), no warp.
Frames /out/m_tf_*.png (chase view), marks /out/marks.txt."""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
from skills import tank as TK

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

FRENZIES = {
    "wil_kf08": dict(spot=(3.5, 164.5, 2), kind="cars", count=20, secs=60, start="7111",
                     # the road the tank's yard opens onto (x 8-11 at level 2) and its stretches
                     # the yard opens onto the road x 8-11 (y 148-168) with junctions at y 148-150 and 166-168;
                     # the busier roads (x 19-22, y 190-192) are 35 s of tank driving off (tk5)
                     drop=(9.5, 160.5), roam=[(9.5, 152.0), (9.5, 166.0), (16.0, 167.5), (9.5, 166.0), (9.5, 150.0), (16.0, 149.0)]),
    "wil_kf07": dict(spot=(226.5, 238.5, 1), kind="peds", count=35, secs=60, start="7101", drop=None, roam=None),
}
JOB = os.environ.get("TANK_FRENZY", "wil_kf08")
F = FRENZIES[JOB]

VIEW = ["classic"]
def set_view(name):
    order = ["classic", "third", "first"]
    while VIEW[0] != name:
        tap("v", 0.3); time.sleep(1.7)
        VIEW[0] = order[(order.index(VIEW[0]) + 1) % 3]
    M.CUR_VIEW[0] = name
    M.mark(f"view {name}")


LIVES = [None]
class Over(Exception):
    pass

def outcome():
    ms = M.mission_state()
    if not ms: return "unknown", ms
    if LIVES[0] is not None and ms["lives"] > LIVES[0]: return "passed", ms
    if ms["health"] == 0 or ms["death"] != 0: return "dead", ms
    if LIVES[0] is not None and ms["lives"] < LIVES[0]: return "dead", ms
    return "running", ms

def check():
    o, ms = outcome()
    if o not in ("running", "unknown"): raise Over(o)
    return ms or {}


def main():
    D.start()
    s = D.wait_state(40)
    if not s: sys.exit(1)
    D.calibrate_turn()
    world = M.World("wil")
    M.mark("level")
    M.VIEW_HOOK[0] = set_view
    set_view("third")
    LIVES[0] = (M.mission_state() or {}).get("lives")
    M.mark(f"frenzy {JOB}: {F['kind']} {F['count']} in {F['secs']} s, lives {LIVES[0]} (skill tank)")
    t_m = time.time()
    x, y, L = F["spot"]
    if math.hypot(x - s["x"], y - s["y"]) > 60 and F["drop"]:
        M.mark("by car toward the tank")
        s = M.any_car2(world, budget=120)
        if s and s["driving"]:
            s = M.drive3(world, F["drop"][0], F["drop"][1], tol=2.5, budget=300)
            s = M.leave_car()
    s = TK.get_tank(world, spot=F["spot"], budget=500, jack=False)
    if not s:
        M.mark(f"frenzy {JOB}: no tank"); say("RESULTS", {JOB: "no tank"}); return
    M.shot("tf_in_tank")
    msgs0 = M.message_log()[-3:]
    say("messages on entry:", msgs0)
    r = "running"
    try:
        r = TK.fight(world, kind=F["kind"], count=F["count"] + 2, secs=F["secs"] + 3, check=check,
                     roam=F["roam"], shot_prefix="tf")
    except Over as e:
        r = str(e)
    TK.release()
    t1 = time.time()
    while r not in ("passed", "dead") and time.time() - t1 < 12:
        o, ms = outcome()
        if o != "running": r = o; break
        time.sleep(1.0)
    ms = M.mission_state() or {}
    if r not in ("passed", "dead"): r = "failed" if r in ("done", "time", "running") else r
    M.mark(f"frenzy {JOB}: {r} ({time.time() - t_m:.0f}s) lives {LIVES[0]} -> {ms.get('lives')} msg {ms.get('msg')}")
    say("message log tail:", M.message_log()[-8:])
    M.shot("tf_end"); time.sleep(2.0); M.shot("tf_end2")
    for t, e in TK.EVENTS: say(f"skill event +{t - t_m:.0f}s: {e}")
    say("STATS", TK.STATS)
    say("RESULTS", {JOB: r})
    M.mark(f"done {JOB}={r}")


if __name__ == "__main__":
    main()
