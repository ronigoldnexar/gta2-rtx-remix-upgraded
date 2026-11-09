#!/usr/bin/env python3
"""SCIENCE FRICTION! (Residential file ste, the Zaibatsu green phone 166.5,19.5 on a level-2 terrace,
ste_ze1.mis): a car-bomb job (gamerun/skills/car_bomb.py), MISSIONS-BATCH3 (Wave M).

What the script wants (assets-src/missions/ste_m/ste_ze1.mis):
  2464 title, 2551 brief; Montana's Pickup (model 41, CREATE_GANG_CAR 24.0,41.5, the arrow on it)
  guarded by four Rednecks (GUARD, AREA_PLAYER_ONLY): two with Molotovs on the roof (24.5,45.5 and
  24.5,40.5, z 4), two machine guns on the street (21.5,46.5 and 21.5,38.5). In the Pickup he is
  given CAR_BOMB; the block IS_CAR_IN_BLOCK (179.5,234.5, 3 x 1) south of the SRS Clone Test
  Center (177-180 x 229-233): 2553 drive there, 2555 parked, 2554 out of the block again, 2557 out
  of the car away from the block, 2558 out of the car in the block un-armed, 2556 armed (fire).
  Wrecked in the block -> SET_DEATHARREST_STATE OFF, EXPLODE_LARGE over the lab at z 5, 4, 3,
  2999, $30,000, 2560. Wrecked anywhere else: 2552 (before arming) / 2559 (after) and 2998.

The block is a field pocket 176-180 x 234-235, walled north (the lab), south (rows 236-237) and
west (column 175): its only way in is the one-cell field lane down column 176 from row 228. The
car comes down the lane heading south and turns east into the pocket (`line`); the escape runs
back west and up the lane to the road on row 228 (fixed `routes`: the computed ones refuse the
lane because it passes the lab's blast points at z 5).

Steps: the phone (skills/rooftop_access climb on foot; SF_WARP_PHONE=1 first warps him to the
L2 road 8 blocks south of it, marked WARP), a borrowed car to the Pickup, the street guards run
over (OPERATION Z's leg-1 way; SF_WARP_CAR=1 warps from the phone to the road south of the Pickup,
marked WARP), the Pickup boarded, then the car-bomb skill (park, arm, run).

Run (keys script missions/keys_science_friction.sh):
  SWAP_LEVEL=ste GTA2_SPEED=1 GTA2_DIRECT_KEYS=1 FPS=0 \\
  INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' \\
  gamerun/grun.sh sf1 1800 missions/keys_science_friction.sh -e DISTRICT=ste -e WARP_OK=0 \\
      -e SF_WARP_PHONE=1 -e SF_WARP_CAR=1 -e GTA2DX9_SCENE_NO_CAR=1 -e CB_DRIVER=old -e GTA2DX9_STATE_EVERY=3
Summary /out/sf_result.json; frames /out/m_sf_*.png; marks /out/marks.txt.
"""
import json, math, os, sys, time
sys.path.insert(0, "/work")
sys.argv = sys.argv[:1]
os.environ["DISTRICT"] = "ste"
os.environ["MISSIONS"] = " "
os.environ.setdefault("WARP_OK", "0")
import drive_lib as D
import mission_lib as M
import mission_play_districts as P          # starts the session: level, views, world
import skills.car_bomb as CB
from skills import rooftop_access as RA
from skills import steal_car as SC

say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo
world = P.world
RA.D, RA.M, RA.P, RA.world, RA.say = D, M, P, world, say
NAME = "ste_ze1"
PHONE = (166.5, 19.5)
PICKUP = (24.0, 41.5)
STAND = (30.5, 54.5, 1)       # the road row 54, 13 blocks south of the Pickup (BLOW JOB came from this side)
TITLE = {"2464", "2551"}
RESULT = dict(stage="start", events=[])

# the escape: back west along the pocket, up the lane (column 176) and west along the road row 228
ESCAPE = [(176.6, 235.0), (176.5, 232.0), (176.5, 228.6), (171.0, 228.6), (165.0, 228.6)]
STAGE = CB.Stage(
    box=(179.5, 234.5, 3.0, 1.0), name="sf", model=41, car=PICKUP,
    keys=dict(drive="2553", parked="2555", left="2554", out="2558", armed="2556", outside="2559", done="2999"),
    blasts=[(178.0, 230.0), (180.0, 230.0), (178.0, 233.0), (180.0, 233.0)],
    line=((176.5, 231.0), (179.4, 234.6)),
    routes={"lane": ESCAPE},
    # only the last approach is given: the router's own way across town kept the Pickup at 23450 for
    # 120 blocks (sf7); sf8's hand-made avenue at x 72 is broken at row ~100, the router went north
    # from it, the car was pinned at 88,22 and burned. Into the lane: column 158-161 south, the jog
    # to 155-158 at row 222, east along row 228
    via=[(v[0], v[1]) for v in json.loads(os.environ["SF_VIA"])] if os.environ.get("SF_VIA") else
        [(159.5, 212.0), (159.5, 219.0), (156.5, 224.0), (162.5, 228.6), (171.5, 228.6)])


def ev(what):
    RESULT["events"].append(f"{time.strftime('%H:%M:%S')} {what}"); M.mark(what); say(what)


def warp_verified(x, y, level, why, tries=5):
    """the scene warp, checked on a fresh position a few seconds later (sf11: the warp's own
    state read was stale under load, he was still at the start and the climb walked him over the
    river); True when he stands within 8 blocks of the point"""
    P.set_view("classic")
    CB.WARPING[0] = True
    ok = False
    try:
        for k in range(tries):
            M.scene_warp(x, y, level, why)
            time.sleep(3.0)
            s = D.wait_state()
            if s and math.hypot(s["x"] - x, s["y"] - y) < 8:
                ok = True; break
            say(f"sf: warp to {x},{y} not taken (at {s['x']:.1f},{s['y']:.1f}); again")
            time.sleep(2.0)
    finally:
        CB.WARPING[0] = False
        P.set_view("third")
    return ok


def phone(entry, job):
    s = D.wait_state()
    if os.environ.get("SF_WARP_PHONE", "0") == "1" and math.hypot(PHONE[0] - s["x"], PHONE[1] - s["y"]) > 30:
        # the north-east is a raised district: its streets are level 2. sf1 warped to the river
        # road at 159.5,34.5 L1; the climb's route crossed 138-140,24 by the water and he drowned
        # twice (respawned at 195,140). The road column 167-168 (L2) passes the phone: warp there
        near = (167.5, 27.5, 2)
        if not warp_verified(*near, "SF_WARP_PHONE: the L2 road 8 blocks south of the Zaibatsu phone; the walk and the job are played"):
            RESULT["phone"] = {"why": "phone warp not taken"}
            return False
        RESULT["events"].append(f"phone warp to {near}")
    for k in range(3):
        ok, ms, info = RA.answer_roof_phone(world, entry, P.answer)
        job.poll()
        if ok or job.saw(TITLE) or info.get("reached"): break
    RESULT["phone"] = {kk: v for kk, v in info.items() if kk != "path"}
    if not (ok or job.saw(TITLE)): return False
    # no RA.descend: the phone's terrace is this district's street level (L2), and the descend
    # toward the Pickup walked him over the river bridge (rows 21-24) where he died (sf2, lives
    # 5 -> 4 at 154.8,21.5): step off the phone back onto the road column 167 and take a car there
    M.set_avoid_phones(world, keep=(entry["x"], entry["y"]))
    M.walk3(world, 167.5, 23.5, None, tol=1.0, budget=30)
    M.set_avoid_phones(world, keep=None)
    return job.saw(TITLE)


# any ordinary traffic car (no bus, truck, tank, train, emergency vehicle): steal_car jacks a moving
# one (never a gang car: sf5 jacked one by the Zaibatsu HQ and their gunmen burned it in 10 s);
# sf4 waited at kerbs five times (90 s each) after its car burned and none stopped
CARRIERS = [i for n, i in SC.MODELS.items() if n not in {"BUS", "TANK", "TRAIN", "TRAINCAB", "TRAINFB", "TRUKCAB1",
            "TRUKCAB2", "TRUKCONT", "TRUKTRNS", "TANKER", "COPCAR", "SWATVAN", "FIRETRUK", "MEDICAR", "APC", "BOXCAR",
            "GTRUCK", "ICECREAM", "HOTDOG", "HOTDOG_D1", "HOTDOG_D2", "HOTDOG_D3", "EDSELFBI", "GUNJEEP",
            "VTYPE", "STRATOSB", "PICKUP"} and not n.startswith("WRECK")]


def get_car(job, budget=150):
    s = D.wait_state()
    if s["driving"]: return s
    s = M.any_car2(world, budget=40)
    if s["driving"]: return s
    ev("no car stopped at the kerb: jacking one from traffic (steal_car)")
    SC.steal_car(world, CARRIERS, budget=budget, check=lambda: bool(job.outcome()), view_switch=P.view_switch)
    job.check()
    return D.wait_state()


def drive_near(x, y, stop, job, budget=480):
    """a borrowed car to a road cell `stop` blocks short of (x, y), on the side he comes from"""
    s = D.wait_state()
    if math.hypot(x - s["x"], y - s["y"]) < stop + 4: return s
    if not s["driving"]:
        # sf3: four any_car2 tries on the quiet road column 167 by the phone (no car stopped in
        # 6 minutes); the main L2 road is rows 28-29 just south of it
        for road in ((170.5, 28.5), (176.5, 28.5), (185.5, 28.5)):
            ev(f"to the main road at {road} for a car")
            M.walk3(world, road[0], road[1], None, tol=1.5, budget=60)
            s = get_car(job, budget=120)
            if s["driving"]: break
    for leg in range(5):
        job.check()
        s = D.wait_state()
        if not s["driving"]:
            s = get_car(job)
            if not s["driving"]: continue
        if (x, y) == PICKUP:
            c = STAND     # the Pickup stands on a field with no road within 6 (sf4 drove at the Pickup itself)
        else:
            dx, dy = s["x"] - x, s["y"] - y; n = math.hypot(dx, dy) or 1
            c = M.street_cell_near(world, x + dx / n * stop, y + dy / n * stop, radius=6) or (x, y, 1)
        ev(f"by car to {c[0]},{c[1]} ({math.hypot(c[0] - s['x'], c[1] - s['y']):.0f} blocks)")
        P.FP["until"] = 0.0
        s = M.drive3(world, c[0], c[1], tol=2.5, budget=budget, view_switch=P.view_switch, until=lambda: bool(job.outcome()))
        job.check()
        if math.hypot(c[0] - s["x"], c[1] - s["y"]) < 5: break
    return D.wait_state()


GUNNERS = ((21.5, 46.5), (21.5, 38.5))      # the two machine guns, GUARD_SPOT at street level


def guards_alive(r=2.8, remap=5):
    """the street gunners still at their posts (GUARD_SPOT keeps them there); any other Redneck
    walking by is not counted (sf7 counted 18 of remap 5 within 7 blocks)"""
    return [p for p in M.peds() if p.get("remap") == remap and M.ped_alive(p) and p["car"] is None
            and p.get("z", 2) < 3.5 and any(math.hypot(p["x"] - gx, p["y"] - gy) < r for gx, gy in GUNNERS)]


def clear_guards(job, secs=float(os.environ.get("SF_GUARD_SECS", "360"))):
    """the two street gunners run over from the borrowed car (OPERATION Z leg 1); the two on the
    roof with Molotovs cannot be reached and are left (sf9: a gunner left standing shot him dead at
    the Pickup's door, so a burned car is replaced and the run goes on)"""
    t0 = time.time()
    while time.time() - t0 < secs:
        job.check()
        g = guards_alive()
        if not g: ev("the street guards are down"); return True
        s = D.wait_state()
        if not s["driving"]:
            s = get_car(job, budget=90)
            if not s["driving"]: continue
        r, k = M.run_over(world, [5], set(), {"2998"}, PICKUP, secs=20, radius=9)
        say(f"sf: run_over {r} kills {k}; {len(guards_alive())} street guards left")
    ev(f"guards: {len(guards_alive())} left after {time.time() - t0:.0f}s; boarding anyway")
    return False


def play():
    entry = next(m for m in world.db["missions"] if m.get("mission") == NAME)
    M.mark(f"mission {NAME}: {entry.get('title', '')} (missions/science_friction.py, skills/car_bomb.py)")
    job = CB.Job(done=("2999",), failed=("2998", "2552", "2559"))
    if not phone(entry, job):
        return f"phone not answered ({RESULT.get('phone')})"
    RESULT["stage"] = "phone"; ev(f"phone answered (messages {job.seen[-4:]})")
    P.set_view("third"); M.shot("m_sf_phone")
    ms = M.mission_state() or {}
    job.lives0 = ms.get("lives"); job.money0 = ms.get("money", 0)
    M.LIVES0[0] = job.lives0
    if os.environ.get("SF_WARP_CAR", "0") == "1":
        # sf3-sf6: the 144-block trip from the Zaibatsu plateau to the Pickup is not the job and lost
        # every session (no traffic on the L2 roads by the phone; a car burned at the 118,39
        # crossing; a jacked Zaibatsu car shot to pieces by their gunmen). Marked WARP; the
        # guards, the Pickup, the drive to the lab, the park, the bomb and the escape are played
        if not warp_verified(*STAND, "SF_WARP_CAR: the road 13 blocks south of Montana's Pickup; the guards, the Pickup and the bomb are played"):
            return "car warp not taken"
        RESULT["events"].append(f"car warp to {STAND}")
    else:
        drive_near(*PICKUP, stop=10.0, job=job)
    s = D.wait_state()
    far = math.hypot(PICKUP[0] - s["x"], PICKUP[1] - s["y"])
    if far > 25:
        # sf3: still 140 blocks off; the guards were outside the 30-block peds window, so
        # clear_guards saw none, and car_bomb.board walked the whole way and he died
        return f"not near the Pickup ({far:.0f} blocks; at {s['x']:.0f},{s['y']:.0f})"
    RESULT["stage"] = "at the Pickup"; M.shot("m_sf_pickup_near")
    if os.environ.get("SF_GUARDS", "1") == "1":
        clear_guards(job)
    # out of the Rednecks' zone (x < 80) at speed before the careful drive: sf12's slow precious
    # drive north through 60-75 x 25-50 took hit after hit (32000 -> 15938, burning 185 blocks
    # short of the lab). East along rows 34-35, the zone's edge at x 80, then the skill's drive
    if os.environ.get("SF_FAST_EXIT", "1") == "1":
        s = CB.board(world, STAGE, check=job.check)
        if s and s.get("driving"):
            M.shot("m_sf_incar")
            ev(f"in the Pickup (carhp {(M.mission_state() or {}).get('carhp')}): fast out of the Rednecks' zone")
            # the old driver (drive3 without the smooth one), not slow: sf13's smooth driver stalled
            # in the Pickup's shelter and backed west into the gunners (32000 -> 2372 in 3 s); the
            # old one left the shelter cleanly in sf7, sf8 and sf12
            saved = M.SMOOTH[0]; M.SMOOTH[0] = False
            try:
                for gx, gy in ((45.5, 34.5), (92.5, 34.5)):
                    M.drive3(world, gx, gy, tol=3.0, budget=90, slow=False, view_switch=P.view_switch,
                             until=lambda: bool(job.outcome()))
                    job.check()
            finally:
                M.SMOOTH[0] = saved
            ev(f"out of the zone at {D.wait_state()['x']:.0f},{D.wait_state()['y']:.0f} (carhp {(M.mission_state() or {}).get('carhp')})")
    r = CB.car_bomb(world, STAGE, job, shot_prefix="m_sf")
    RESULT["bomb"] = r; ev(f"car bomb: {r}")
    if r in ("done", "complete") or job.outcome() == "complete":
        for i in range(4):
            M.shot(f"m_sf_complete_{i}"); time.sleep(0.5)
        return "complete"
    return r


def main():
    try:
        r = play()
    except CB.JobOver as e:
        r = str(e)
    except Exception as e:
        import traceback; traceback.print_exc(); r = f"error {e!r}"
    ms = M.mission_state() or {}
    ev(f"mission {NAME}: {r} money {ms.get('money')} lives {ms.get('lives')} health {ms.get('health')}")
    time.sleep(2.0); M.shot("m_sf_end")
    RESULT["result"] = r; RESULT["stats"] = dict(CB.STATS)
    RESULT["skill_events"] = [f"{time.strftime('%H:%M:%S', time.localtime(t))} {w}" for t, w in CB.EVENTS]
    with open("/out/sf_result.json", "w") as f: json.dump(RESULT, f, indent=1)
    say("RESULT", NAME, r, CB.STATS)
    M.mark(f"done science_friction={r}")
    return r


if __name__ == "__main__":
    main()
