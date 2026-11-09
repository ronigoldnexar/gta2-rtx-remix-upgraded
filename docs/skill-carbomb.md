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
SWAP_LEVEL=ste GTA2_SPEED=1 GTA2_DIRECT_KEYS=1 FPS=0 \
INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' \
gamerun/grun.sh <name> 2400 missions/keys_blow_job_cb.sh -e DISTRICT=ste -e WARP_OK=0 \
    -e CB_WARP_PHONE=1 -e GTA2DX9_SCENE_NO_CAR=1 -e CB_DRIVER=old -e GTA2DX9_STATE_EVERY=3
```

`CB_WARP_PHONE=1` is a developer shortcut for the approach only, the same as SINK OR SWIM's
`SOS_WARP_PHONE`. The scene warp puts him on the street south of the phone, marked `WARP` in the
marks. Everything from the phone on is played.

## Sessions

All sessions used the shared `repo/stage`, the plain renderer, `GTA2_DIRECT_KEYS=1` (every frame
in the chase view) and `FPS=0`. cb1-cb7 ran at `GTA2_SPEED=2`, cb8 on at `GTA2_SPEED=1`.

| session | reached | ended because | fixed in |
|---|---|---|---|
| cb1 | level | the scene warp was pressed in the chase view and ignored; stopped by me | runner: classic view for the warp |
| cb2 | phone not answered | warped to 15.5,85.5, answer()'s waypoint 18.5,100 walked him back south, the walker stuck at 5,114 | runner: one approach point only |
| cb3, cb4, cb5 | level | warp refused: the renderer wants a road or pavement cell within 6 blocks by its own test (18.5,72.5 and 13.5,72.5 refused); stopped by me | runner: warp to cb2's 15.5,85.5, walk to 18.5,72.5 |
| cb6 | phone (34 s), Pickup boarded | shared smooth driver: carhp 32000 -> 17000 on the road way; the drive ended north of the trailer and the straight creep pushed into it | skill: creep only from the line-up point |
| cb7 (`CB_DRIVER=old`) | **stage 1 parked (2005), armed (2006) on the first press, blown in the block (2012, +$95)** | he got out on the trailer side (car facing west-north-west, door north) and his facing took him north-west; dead 0.8 blocks from the script's EXPLODE at 51,19.5, 2.1 s wall (about 4 game s) after arming | skill: escape model (turn and run until the fuse ends), straight and dogleg runs fanned round the heading, re-plan from where he lands; runner: line up from the west (car faces east, door south) |
| cb8 | Pickup to column 60 | the router's road way cut the corner from column 61 into row 22 and pinned the car on the wall column 58 (rows 25-27) until it burned | skill: `via` points; never board a car burning under carhp 4000 |
| cb9, cb10 | **at the line-up point with carhp 28500-26700** | the car arrived facing north with the block due east; the pulse creep (reverse-and-steer, then a forward arc) took it away; stopped by me | skill: the shared driver takes the last 5 blocks, stopping at "parked" |
| cb11 | **stage 1 done and survived**: via points (carhp 30532 at the block), parked, armed, ran 11.7 blocks east, 2012 at 222 game s; wanted level gone in 8 s | walking to the second Pickup he was arrested (an 86-block jump, lives unchanged) and the job ended; the runner did not notice and tried 13 doors at the empty spawn | skill: a jump over 25 blocks on foot ends the job (`busted`); `board` needs the game's target car |
| **cb12** | **JOB COMPLETE.** Stage 1: four via points (carhp 28075 at the block), parked facing north, armed, right-door run east 10.8 blocks, 2012 at 213 game s. Wanted level 1 gone in under 25 s; second Pickup boarded at 307 s and driven along 10 via points (31161 at column 105), parked at the barricade (110.31,77.47), armed (2018). **2021 then 2999 Mission Complete, +$30,000, multiplier 2, saved (`svdone`) at 521 game s**; frame `m_m_cb_complete_0.png` shows the payoff brief over the chase view | 2 s after the payoff the barricade blast threw him (z 7) and he died (lives 5 -> 4): the right-hand door was blocked at the barricade, he came out on the left, and the route planned for the right door took him round the car's tail | skill: plans for both doors before arming, picked by the side he lands on; via points followed from the nearest one |
| cb13 | phone, Pickup | my via fix took the via point nearest to the spawn (the last one) and skipped the road way; the Pickup burned | skill: nearest via point only within 8 blocks |
| cb14 | stage 1 parked and armed | he spun on the spot beside the bomb for 2.5 s (0.35 s turn pulses decided on a position line logged every 0.5 s) and the blast killed him | skill: 0.12 s turn pulses and a fresh sample after each; runs with `GTA2DX9_STATE_EVERY=3` |
| cb15 | **stage 1 done and survived** | at the escape's end (the junction 61,23) he lost 100 health in 2 s during the lie-low with wanted level 1, which ended the job; the walk to the second Pickup did not notice | skill: escapes not ending on a road, off the road after the run, board walks in chunks with the job's check |
| cb16 | **stage 1 done and survived**; second Pickup driven to the barricade | the via points up column 61 and round the junction 61,23 cost 14000 carhp; the car burned and the skill refused to re-board it at 2787 | runner: drop those two points; skill: refuse only under carhp 900 |
| cb17 | **stage 1 done and survived** | beaten to death during the lie-low at the escape's end by two cops on foot (wanted 1, health in steps of 10) | skill: `evade()`: toward the next car, away from cops within 7 blocks, instead of standing still |
| **cb18** | **JOB COMPLETE, survived.** Stage 1 parked/armed/done at 247 game s; evade toward the second Pickup; boarded at 290 s; 10 via points (30391 carhp at the barricade); out on the left side, ran the left-door route north; **2999 Mission Complete at 478 game s, +$30,000, saved, lives 5, health 96**; frame `m_m_cb_complete_0.png` | - | (final code) |
| cb19 | **stage 1 done and survived** | during `evade()` two cops caught him (health 100 -> 20) and arrested him (6158, a 123-block jump); the skill missed the arrest and tried doors at the empty spawn | skill: 6158 busted and 6156 dead end the job (detection only, play unchanged) |
| **cb20** | **JOB COMPLETE, survived.** Stage 1 done at 222 game s, evade, second Pickup driven along the via points (a hit on the way: 16484 at the barricade), parked, armed, out on the left side, ran north; **2999 at 503 game s, +$30,000, saved, lives 5, health 72**; frame `m_m_cb_complete_0.png` | - | - |

### Result

**Acceptance: 2 of 3 sessions with the final code (cb18, cb19, cb20) reached JOB COMPLETE**
(cb18 and cb20, both survived; cb19 was arrested after stage 1). With cb12 (earlier code, Mission
Complete and saved, then killed by the barricade blast) the skill has paid out BLOW JOB three
times. Every frame of these sessions is a chase-view frame (`GTA2_DIRECT_KEYS=1`).

What is verified, and what is not:
- Verified in the game: pre-rigged car jobs (board by `tcar`, park in a thin block via a line-up,
  arm, both-door escape, the script's blast points avoided, the verdict from the message keys)
  on both BLOW JOB stages.
- Not yet run: `rig()` (the bomb-shop jobs wil_ym1, wil_zm1, ste_rm2), SCIENCE FRICTION ste_ze1
  (same loop, keys in the table above; the Pickup at 24,41.5 is guarded by hostile Rednecks
  there), GREATEST HITS, KARMA ASSASSINS.
- Weak points: the wanted level after a blast. Cops on foot catch him on the walk to the next car
  (cb11 and cb19 arrested, cb15 and cb17 beaten), and `evade()` reduces this but does not remove
  it. The shared driver's damage on long legs is the other: the via points are per job.
- The phone approach is a developer warp (`CB_WARP_PHONE=1`, marked `WARP` in marks.txt). The
  runs used `GTA2_SPEED=1`, `CB_DRIVER=old` (drive3 without the smooth driver) and
  `GTA2DX9_STATE_EVERY=3` (a position line every 3 frames, needed by the escape's steering).
