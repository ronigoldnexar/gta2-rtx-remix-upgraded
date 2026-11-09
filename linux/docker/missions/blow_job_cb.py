#!/usr/bin/env python3
"""BLOW JOB! (Residential file ste, the Rednecks' green phone 18.5,68.5, ste_re1.mis): the proof
job of the car-bomb skill (gamerun/skills/car_bomb.py, SKILL-CARBOMB). Both stages are played by
the skill; this runner only describes them and gets to the phone.

The script (assets-src/missions/ste_m/ste_re1.mis): a rigged Pickup (model 41, CREATE_GANG_CAR
24.0,41.5, the arrow on it); into IS_CAR_IN_BLOCK(48.5,20.5, 3 x 1) by Fat Boy Jim's trailer: 2003
drive there, 2005 parked, 2004 out of the block again, 2008 out of the car un-armed, 2006 armed;
wrecked in the block -> the script blows up the trailer (EXPLODEs along row 19, x 47-51) and 2012
with a second Pickup at 24.0,44.5; the barricade IS_CAR_IN_BLOCK(111.5,77.5, 3 x 1) (arrow
110.5,77.5): 2014, 2016 parked, 2017 out, 2019, 2018 armed; wrecked there -> EXPLODEs along column
111 rows 75-78, 2021, $30,000, 2999. Wrecked outside a block: 2010 / 2020 and 2998.

Run (keys script missions/keys_blow_job_cb.sh):
  SWAP_LEVEL=ste GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0 \
  INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' \
  gamerun/grun.sh <name> 1500 missions/keys_blow_job_cb.sh -e DISTRICT=ste -e WARP_OK=0 \
      -e CB_WARP_PHONE=1 -e GTA2DX9_SCENE_NO_CAR=1
CB_WARP_PHONE=1: the developer scene warp puts him on the street south of the phone (the
110-block trip from the district start is the shared runner's, not this skill's; marked WARP in
marks.txt). CB_DRIVER=old|smooth picks the shared driver. Summary in /out/cb_result.json.
"""
import json, math, os, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["DISTRICT"] = "ste"
os.environ["MISSIONS"] = " "
import drive_lib as D
import mission_lib as M
import mission_play_districts as P          # starts the session: level, views, world
import skills.car_bomb as CB

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world
NAME = "ste_re1"
PHONE = (18.5, 68.5)
RESULT = dict(stage="start", events=[])

STAGE1 = CB.Stage(
    box=(48.5, 20.5, 3.0, 1.0), name="bj1", model=41, car=(24.0, 41.5),
    keys=dict(drive="2003", parked="2005", left="2004", out="2008", armed="2006", outside="2010", done="2012"),
    blasts=[(47.0, 19.0), (48.0, 19.3), (49.0, 19.6), (51.0, 19.5)],
    # PLAYTHROUGH-8: the trailer block is entered along row 20 from the east
    line=((53.5, 20.6), (49.0, 20.5)))
STAGE2 = CB.Stage(
    box=(111.5, 77.5, 3.0, 1.0), arrow=(110.5, 77.5), name="bj2", model=41, car=(24.0, 44.5),
    keys=dict(drive="2014", parked="2016", left="2017", out="2019", armed="2018", outside="2020", done="2021"),
    blasts=[(111.5, 75.5), (111.5, 76.5), (111.5, 77.5), (111.5, 78.5)],
    # the barricade stands in cell 111: in from the west along row 77
    line=((106.5, 77.5), (110.3, 77.5)))
if os.environ.get("CB_ROUTES") == "fixed":     # blow_job.py's hand-made routes, for comparison
    STAGE1.routes = {"west": [(44.0, 21.7), (37.0, 22.2), (31.0, 22.4)], "east": [(53.5, 21.8), (59.0, 22.3), (63.5, 22.5)]}
    STAGE2.routes = {"north": [(107.5, 74.5), (106.6, 68.0), (106.6, 64.5)], "south": [(107.5, 80.5), (106.6, 86.0), (106.6, 89.5)]}


def ev(what):
    RESULT["events"].append(f"{time.strftime('%H:%M:%S')} {what}"); M.mark(what)


def shots(prefix, n=3, gap=0.6):
    for i in range(n):
        M.shot(f"{prefix}_{i}"); time.sleep(gap)


def to_phone(entry):
    s = D.wait_state()
    if os.environ.get("CB_WARP_PHONE", "0") == "1" and math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) > 30:
        # the phone is fenced and approached from the south (the shared runner's waypoints
        # 18.5,100 -> 18.5,78): the warp puts him on the street there
        near = M.street_cell_near(world, 18.5, 82.0, radius=8)
        if near:
            M.scene_warp(near[0], near[1], near[2], "CB_WARP_PHONE: the street south of the Rednecks' phone; the job starts at the phone")
            RESULT["events"].append(f"phone warp to {near}")
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    ok, key = P.answer(entry)
    M.set_avoid_phones(world, keep=None)
    return ok, key


def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == NAME)
    M.mark(f"mission {NAME}: {entry.get('title', '')} (missions/blow_job_cb.py, skills/car_bomb.py)")
    job = CB.Job(done=("2999", "2021"))
    ok, key = to_phone(entry)
    job.poll()
    say("answered:", ok, key, job.seen[-4:]); M.shot("m_cb_phone")
    started = P.TITLES.get(key)
    if not ok and not job.saw({"2671", "2001"}):
        return "phone not answered"
    if started and started.get("mission") != NAME:
        return f"wrong phone ({started['mission']})"
    RESULT["stage"] = "phone"; ev(f"phone answered (messages {job.seen[-4:]})")
    ax, ay = M.step_off_phone(world, entry)
    M.cruise_to(ax, ay, tol=0.5, secs=10)
    ms = M.mission_state() or {}
    job.lives0 = ms.get("lives"); job.money0 = ms.get("money", 0)
    M.LIVES0[0] = job.lives0
    r = CB.car_bomb(world, STAGE1, job, shot_prefix="m_cb_bj1")
    RESULT["stage1"] = r; ev(f"stage 1: {r}")
    if r == "complete": return r
    if r != "done": return f"stage 1 {r}"
    RESULT["stage"] = "stage1"
    shots("m_cb_bj1_after", n=2)
    CB.lie_low(float(os.environ.get("CB_LIE_LOW", "25")))
    r = CB.car_bomb(world, STAGE2, job, shot_prefix="m_cb_bj2")
    RESULT["stage2"] = r; ev(f"stage 2: {r}")
    if r in ("done", "complete") or job.outcome() == "complete":
        shots("m_cb_complete", n=4, gap=0.5)
        return "complete"
    return f"stage 2 {r}"


def main():
    try:
        r = play()
    except CB.JobOver as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    ms = M.mission_state() or {}
    ev(f"mission {NAME}: {r} money {ms.get('money')} lives {ms.get('lives')}")
    time.sleep(2.0); M.shot("m_cb_end")
    RESULT["result"] = r; RESULT["stats"] = dict(CB.STATS)
    RESULT["skill_events"] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in CB.EVENTS]
    with open("/out/cb_result.json", "w") as f: json.dump(RESULT, f, indent=1)
    say("RESULT", NAME, r, CB.STATS)
    M.mark(f"done blow_job_cb={r}")
    return r


if __name__ == "__main__":
    main()
