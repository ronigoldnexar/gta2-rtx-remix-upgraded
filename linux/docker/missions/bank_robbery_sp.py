#!/usr/bin/env python3
"""BANK ROBBERY! (wil_ye2) with the shake-the-police skill (SKILL-POLICE, Wave M).

    python3 /work/missions/bank_robbery_sp.py      (inside the container, after to_level.sh)

The job is missions/bank_robbery.py, imported unchanged (phone, GRAHAM, bank, guards, getaway,
safehouse). Only its step 5, the respray the script asks for after Hiroshi is out
(`ALTER_WANTED_LEVEL_NO_DROP (p1, 2)`, then `CHECK_HEADS_GREATER`), is handed to
skills/shake_police.shake: the first time that runner drives toward one of its two hand-placed
shops, the skill takes over (nearest respray by the car router from the district table, entry side
from the map, creep, wait for the game; another shop after a miss) and returns when the level is
gone or the script moved on (the arrow on the safehouse / brief 1661, 1662, 1010). The runner then
sees the safehouse arrow and goes on to step 6 as before.

SP_EVADE_FIRST=<secs> (default 0): drive skills/shake_police.evade for that long before the
respray (the level is NO_DROP here, so this only exercises the evasion legs under a real chase)."""
import os, sys, time
sys.path.insert(0, "/work")
sys.path.insert(0, "/work/missions")
import drive_lib as D
import mission_lib as M
import bank_robbery as BR
from skills import shake_police as SP

TUNNELS = {tuple(t) for _, t in BR.SHOPS}
_orig_drive = BR.drive
STATE = {"taken": False, "result": None}


def safe_up():
    return BR.arrow_near(*BR.SAFE, r=4.0) or (M.mission_state() or {}).get("msg") in ("1661", "1662", "1010")


def drive(world, x, y, tol, budget, **kw):
    if (x, y) not in TUNNELS or STATE["taken"]:
        return _orig_drive(world, x, y, tol, budget, **kw)
    STATE["taken"] = True
    M.mark(f"shake_police takes the respray step (wanted {SP.wanted()}, runner's shop entry {x},{y})")
    M.ensure_view("third"); M.shot("sp_getaway")
    ev = float(os.environ.get("SP_EVADE_FIRST", "0") or 0)
    if ev > 0:
        SP.evade(world, ev, check=BR.check, view_switch=BR.view_switch, until=safe_up)
    r = SP.shake(world, check=BR.check, view_switch=BR.view_switch, done=safe_up, tries=4, budget=600)
    STATE["result"] = r
    M.mark(f"shake_police: {r}")
    s = D.wait_state()
    if r != "clear":
        # hand back: the runner's own loop tries its shops (marked, so the session says so)
        M.mark("shake_police did not clear the level: the runner's own respray loop continues")
        STATE["taken"] = False
    return s


BR.drive = drive

_orig_answer = BR.answer
def answer(world, entry):
    """BR.answer, except that "already on a Yakuza job" (1093) with the script's arrow on the
    GRAHAM is the job this phone just started (sp1: the walker's unstick stepped on the phone
    again after the title, and BR.answer called 1093 a refusal; docs/playthrough-downtown.md)"""
    # from the east: the dais (cells 43-46 x 150-151, level 2) carries GET ZITZAKI's phone at
    # 44.5,150.5 next to this one; sp1/sp3 came round from the west and the walker's unstick moves
    # answered it (brief 1631), then this phone said 1093
    # sp4: from the east foot the walker still went round by the ramp and cut north past it.
    # The ramp is column 43 (rows 150-151, rising south from row 149 to the dais at row 152):
    # up it, east along row 152 (the far side from 44.5,150.5), then north onto 46.5,151.3
    # sp8: a ten-minute governor pause ran out the walk's wall-clock budget and the walker went up
    # its own way again. Now the two dais cells beside GET ZITZAKI's phone are off the router for
    # the approach (every route then runs along row 152), and the walk is retried after a pause
    for c in ((44, 151), (45, 150)): M.AVOID.add(c)
    for k in range(4):
        s = D.wait_state()
        if not s or s["driving"] or (abs(s["x"] - 43.5) < 1.0 and abs(s["y"] - 148.7) < 1.0): break
        M.walk3(world, 43.5, 148.7, 1, tol=0.4, budget=300)
    s = D.wait_state()
    if s and not s["driving"] and abs(s["x"] - 43.5) < 1.5 and abs(s["y"] - 148.7) < 1.5:
        ok = BR.path_walk([(43.5, 149.6), (43.5, 152.4), (46.4, 152.5), (46.5, 151.4)], secs_each=6.0)
        s = D.wait_state()
        M.mark(f"up the phone dais by the ramp and row 152 ({'ok' if ok else 'missed'}), at {s['x']:.1f},{s['y']:.1f} z {s['z']:.1f}")
    r, seen = _orig_answer(world, entry)
    if r == "refused" and seen and seen[-1] == "1093":
        t0 = time.time()
        while time.time() - t0 < 6:
            o = M.objective()
            if o and abs(o[0] - BR.CAR0[0]) < 3.0 and abs(o[1] - BR.CAR0[1]) < 3.0:
                M.mark("phone: 1093 (already on the job) with the arrow on the GRAHAM: answered")
                return "answered", seen
            time.sleep(0.5)
    return r, seen
BR.answer = answer

_orig_run = BR.run
def run(world, entry):
    """BR.run with the respray table read off the map first (not at the getaway, police at the door)"""
    t0 = time.time(); n = len(SP.shops(world))
    D.say(f"police: {n} respray entries in {getattr(world, 'district', '?')} ({time.time() - t0:.1f} s)")
    return _orig_run(world, entry)
BR.run = run

if __name__ == "__main__":
    t0 = time.time()
    BR.main()
    M.mark(f"shake_police result {STATE['result']} ({time.time() - t0:.0f}s); events {len(SP.EVENTS)}")
