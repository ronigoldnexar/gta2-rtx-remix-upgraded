# Skill: car bomb (Wave M, SKILL-CARBOMB, 9 Nov 2026)

Module `gamerun/skills/car_bomb.py` (mirrored in `linux/docker/skills/car_bomb.py`), proof job
BLOW JOB! (`ste_re1`, both stages) with `gamerun/missions/blow_job_cb.py`
(`missions/keys_blow_job_cb.sh`). Built on the frozen `mission_lib` / `drive_lib` and on
`skills/deliver_intact.py` (fragile drive into a box). Neither is changed. The older runner
`missions/blow_job.py` (PLAYTHROUGH-10) is left as it is.

## What the 7 jobs ask

`car_bomb` in `docs/missions-catalogue.md`: wil_ym1 HAPPY GAS SMASH, wil_zm1 LICK THOSE LOONIES,
ste_ze1 SCIENCE FRICTION, ste_re1 BLOW JOB, ste_rm1 GREATEST HITS, ste_rm2 BENSON BURNER, bil_rm2
KARMA ASSASSINS. The decompiled scripts have two ways to start and one way to end:

- **A pre-rigged car.** `CREATE_GANG_CAR ... PICKUP` with the arrow on it, and `GIVE_WEAPON (p1,
  CAR_BOMB)` when he boards it (ste_re1, ste_ze1).
- **A car to rig.** The arrow points at a bomb shop until `HAS_CAR_GOT_WEAPON (car, CAR_BOMB)`.
  wil_ym1's shop is at 84.5,160.5. The shop takes $5,000.
- **Then the same loop in all of them.** `IS_CAR_IN_BLOCK` with him in the car gives a "parked"
  brief (and REMOVE_ARROW); out of the block gives "get back"; out of the car un-armed gives
  "get back in"; `IS_CARBOMB_ACTIVE` after fire gives "armed". A few game seconds later the car
  blows up, and `CHECK_CAR_WRECKED_IN_AREA` decides the result. In the block, the stage is done
  and the script fires its own EXPLODEs along the target: ste_re1 along row 19 at x 47-51 and
  along column 111 at rows 75-78; ste_ze1 over the 4 x 5 block 177-180 x 229-233. Outside the
  block, the job fails (2998).

| job | the car | block (x, y, w x h) | message keys parked / left / out / armed / outside / done |
|---|---|---|---|
| ste_re1 stage 1 | Pickup (41) at 24.0,41.5 | 48.5,20.5, 3 x 1 | 2005 / 2004 / 2008 / 2006 / 2010 / 2012 |
| ste_re1 stage 2 | Pickup at 24.0,44.5 | 111.5,77.5, 3 x 1 (arrow 110.5) | 2016 / 2017 / 2019 / 2018 / 2020 / 2021 + 2999 |
| ste_ze1 | Pickup at 24.0,41.5 (Rednecks guards with Molotovs and machine guns) | 179.5,234.5, 3 x 1 | 2555 / 2554 / 2558 / 2556 / 2559 / 2999 |

## API

| call | does |
|---|---|
| `Stage(box, keys, arrow, blasts, model, car, line, routes, name)` | one bomb: the block, the game's message keys, the script's own blast points, the car's model and spawn, an optional line-up `(approach, creep point)` for a thin block, optional fixed escape routes |
| `Job(done, failed, busted)` | every message key the mission line showed, so a brief that changes fast is not missed. `outcome()` returns complete / failed / busted / dead; `check()` raises `JobOver` |
| `car_bomb(world, stage, job)` | board, park, plan the escape, arm, run, verdict. Returns `done` (the stage's success brief), `complete`, `failed`, `dead`, `busted` or `stuck: ...`. It answers "get back in" and "back to the block" itself (3 tries) |
| `board`, `rig`, `park`, `plan_escape`, `arm`, `run_clear`, `watch`, `lie_low` | each step on its own, for job runners |

How it works:

1. **Board.** It walks to the car at the target-car field `tcar` (the kind-3 arrow's car), else
   the arrow, else the spawn. It counts the car as the mission car only when the arrow leaves
   the car he sits in, and the model matches. A traffic Pickup is not it: pt8_ste2 drove one for
   minutes.
2. **Park.**
   - It drives the shared fragile driver (`slow`, `precious`). `CB_DRIVER=old|smooth` picks the
     driver.
   - A thin block is entered along its length from a line-up point. Other blocks use
     deliver_intact's open-side approach and creep.
   - Once the game says "parked", it pulls the handbrake and releases every key. Down would
     reverse the car out of the block (pt7_ste2).
3. **Plan the escape before arming.**
   - The planning happens while the car stands in the block, so none of it runs inside the fuse.
   - The start is the exit door: the car's right-hand side (y south: right = (-hy, hx)). When that
     cell has no floor, it falls back to the other side, then the ends. BLOW JOB's trailer stands
     on row 19 beside the block.
   - The candidates are routed ring cells 9-13 blocks away (`M.escape_route` with `away`) and
     straight free runs (ahead, door side, diagonals).
   - It rejects any route with a waypoint nearer than the start to the car or to a script blast
     point. It scores the rest by end clearance, the first leg's direction (out of the door side,
     along the heading) and detour.
   - Offline check against the `ste` map: a car facing west in the trailer block runs west-south-west
     across the field to 35.5,23.5. Facing north, it runs east along row 21. At the barricade
     facing east, it runs south down column 109.
4. **Arm.** It fires (Control) until the armed key shows, with Tab at the fourth try. It never
   fires once the "left the block" key has shown, because the bomb would go off outside the
   block (pt7_ste2).
5. **Run.**
   - Return, then Up held from the moment he is on foot, with steering pulses only. No unstick
     moves and no view change: with `GTA2_DIRECT_KEYS=1` the whole escape stays in the chase view.
   - If he came out somewhere other than the planned door, it re-plans from where he stands using
     only the cheap straight runs.
6. **Verdict.** It returns the stage's done key, JOB COMPLETE, the outside key, or a death or
   lost life. Between stages, `lie_low` waits up to 25 game seconds for the blast's wanted level
   to go (pt7_ste1).

Frames: `m_cb_bj<n>_incar/_block/_run/_blast.png`, `m_cb_complete_*.png`. Marks are
`car_bomb: ...` in `/out/marks.txt`. The summary is `/out/cb_result.json`.

## Run

```
SWAP_LEVEL=ste GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0 \
INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' \
gamerun/grun.sh <name> 1500 missions/keys_blow_job_cb.sh -e DISTRICT=ste -e WARP_OK=0 \
    -e CB_WARP_PHONE=1 -e GTA2DX9_SCENE_NO_CAR=1
```

`CB_WARP_PHONE=1` is a developer shortcut for the approach only, the same as SINK OR SWIM's
`SOS_WARP_PHONE`. The scene warp puts him on the street south of the phone, marked `WARP` in the
marks. Everything from the phone on is played.

## Sessions

(filled in as they run)
