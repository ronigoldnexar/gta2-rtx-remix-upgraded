#!/usr/bin/env python3
"""BANK ROBBERY! (wil_ye2) with the respray step done by the shake-the-police skill (SKILL-POLICE).

    python3 /work/missions/bank_robbery_sp.py      (inside the container, after to_level.sh)

v2 (SHARED-DOWNSTREAM, 9 Nov): built on missions/bank_robbery_km.py, the runner that reached JOB
COMPLETE in 2 of 3 (kmg17, kmg19): phone, GRAHAM, bank box, the getaway car parked in the eastbound
lane, the guards by skills/kill_marked, the launch and the one hand-placed path from the bank to the
204 bay driven without stops (follow_path). v1 (sp1-sp19) drove the getaway with the shared drive3,
which stops at corners and queues in traffic: busted at the getaway's right-angle turns in 6 of 19
sessions, and its BR stair climb pinned at 193.4,177.2 in 5 of the last 6.

The respray itself is the skill's: where bank_robbery_km would roll into a bay (its lane_in), the
runner calls skills/shake_police.shake instead (nearest shop by the router, police-close fast pick,
break-away from an officer at the door, another shop after a miss), with the job's rolling bay
entry (bank_robbery_km.lane_in) as the skill's `enter` for the two bays it knows, the skill's pulse
creep for any other. It returns when the level is gone or the script moved on (safehouse arrow /
brief 1661, 1662, 1010), and bank_robbery_km goes on to the safehouse.
Marks `shake_police ...`; frames sp_*, km_*, br_*."""
import os, sys, time
sys.path.insert(0, "/work")
sys.path.insert(0, "/work/missions")
import drive_lib as D
import mission_lib as M
from missions import bank_robbery as BR
from missions import bank_robbery_km as KM
from skills import shake_police as SP

STATE = {"world": None, "calls": 0, "result": None, "cleared": False}
_orig_lane_in = KM.lane_in


def safe_up():
    return BR.arrow_near(*BR.SAFE, r=4.0) or (M.mission_state() or {}).get("msg") in ("1661", "1662", "1010")


def enter(shop, secs, done, check):
    """the skill's way into the tunnel: the job's rolling entry for the bays it has measured"""
    key = (shop.x, shop.y)
    if key in KM.BAYS:
        return _orig_lane_in(key, secs=secs, until=done)
    return SP._creep(shop, secs, done, check)


def lane_in(shop, secs=30, until=None, vmax=3.0):
    """bank_robbery_km's bay entry, handed to the skill: shake_police.shake from here"""
    world = STATE["world"]
    if world is None or STATE["cleared"]:
        return _orig_lane_in(shop, secs=secs, until=until, vmax=vmax)
    STATE["calls"] += 1
    M.mark(f"shake_police takes the respray step (call {STATE['calls']}, wanted {SP.wanted()}, at the {shop} bay)")
    M.shot("sp_getaway")
    r = SP.shake(world, check=BR.check, view_switch=BR.view_switch, done=safe_up, tries=4, budget=480,
                 enter=enter, first=shop)
    STATE["result"] = r
    if r == "clear": STATE["cleared"] = True
    M.mark(f"shake_police: {r}")
    return D.wait_state()


KM.lane_in = lane_in

# SP_FROM_BANK=1 (MISSION-GETAWAY): the whole getaway from the bank is the skill's, no hand-placed
# path: right after boarding the GRAHAM with the level up, shake_police.shake picks the shop by the
# router and drives there with chase_path (SP_CHASE_PATH=1) or drive3. A proof that the generic
# pursuit driver handles the getaway's three right-angle turns, for jobs with no hand-placed path.
FROM_BANK = os.environ.get("SP_FROM_BANK", "0") == "1"
_orig_board = KM.board_graham
def board_graham(world, s):
    s = _orig_board(world, s)
    if FROM_BANK and not STATE["cleared"] and STATE["calls"] == 0 and s and s["driving"] and SP.wanted() > 0 \
            and KM.in_graham() is not False:
        STATE["calls"] += 1
        M.mark(f"shake_police takes the whole getaway from the bank (wanted {SP.wanted()}, chase_path {SP.CHASE_PATH})")
        M.shot("sp_from_bank")
        r = SP.shake(world, check=BR.check, view_switch=BR.view_switch, done=safe_up, tries=4, budget=480, enter=enter)
        STATE["result"] = r
        if r == "clear": STATE["cleared"] = True
        M.mark(f"shake_police: {r}; chase_path {SP.CP_STATS}")
        s = D.wait_state()
    return s
KM.board_graham = board_graham
_orig_launch, _orig_follow = KM.launch, KM.follow_path
def launch(*a, **k):
    return D.wait_state() if (FROM_BANK and STATE["cleared"]) else _orig_launch(*a, **k)
def follow_path(*a, **k):
    return D.wait_state() if (FROM_BANK and STATE["cleared"]) else _orig_follow(*a, **k)
KM.launch, KM.follow_path = launch, follow_path

_orig_run = KM.run
def run(world, entry):
    """KM.run with the world kept for the skill and the respray table read off the map first
    (not at the getaway, police at the door)"""
    STATE["world"] = world
    t0 = time.time(); n = len(SP.shops(world))
    D.say(f"police: {n} respray entries in {getattr(world, 'district', '?')} ({time.time() - t0:.1f} s)")
    return _orig_run(world, entry)
KM.run = run

if __name__ == "__main__":
    t0 = time.time()
    KM.main()
    M.mark(f"shake_police result {STATE['result']} ({time.time() - t0:.0f}s); events {len(SP.EVENTS)}")
