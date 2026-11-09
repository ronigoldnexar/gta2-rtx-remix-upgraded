# Skill: crusher and crane (Wave M, SKILL-CRUSHER, 9 Nov 2026)

Module `gamerun/skills/crusher_crane.py` (mirrored in `linux/docker/skills/crusher_crane.py`),
verified on COP CAR CRUSH! (`wil_ze1`) with `gamerun/missions/cop_car_crush.py`
(`missions/keys_cop_car_crush.sh`, mirrored in `linux/docker/missions/`). It builds on the frozen
`mission_lib` / `drive_lib` and on the Wave M modules `deliver_intact`, `horn_pickup` and
`rooftop_access`, and changes none of them.

## What the 9 jobs ask

`crusher_crane` in `docs/missions-catalogue.json`: wil_ze1 COP CAR CRUSH, wil_zm2 YUTES MUST DIE,
wil_lh1 TAXI DRIVERS MUST DIE, ste_se1 SINK OR SWIM, ste_zm1 OPERATION Z, ste_rm2 BENSON BURNER,
bil_ke2 COP CAR SCRAP, bil_ze2 GRAND THEFT AUTO, bil_re2 MMM, RUSSIAN SAILORS. In the decompiled
scripts the step is: the mission car into the crane's yard (`LOCATE_CHARACTER_BY_CAR` round the yard,
or `IS_CHARACTER_IN_MODEL` plus a box round the tower), the player out of it ("let the crane take
over"), then one of

- `IS_CAR_CRUSHED (car)`: the crane drops the car on the crusher (COP CAR CRUSH, TAXI DRIVERS);
- `GET_CAR_INFO_FROM_CRANE (car, crane)`: the Krishna crane pair passes the car on and the script
  checks its model (COP CAR SCRAP, three Cop Cars);
- an `IS_CAR_IN_BLOCK` box at a crane with no crusher, which drops the car in the water (SINK OR SWIM
  crane8, RUSSIAN SAILORS crane7).

The district files declare every crane (`CRANE_DATA name = (tower x, y) rot  homecrane  FIRST (x, y)
rot`) and crusher (`CRUSHER name = (x, y)`); the module carries that table (`CRANES`).

## Where the crane takes a car

A crusher is a raised 3 x 3 platform that no car can climb (pt4_wil11 pressed the Cop Car against it
and nothing happened). The crane lifts a car standing under its **hook**, which hangs `HOOK_R` = 2.5
blocks from the tower along the crane's own rotation, with the game's angles 0 north (-y), 90 west,
180 south (+y), 270 east (+x): hook = tower + 2.5 x (-sin r, -cos r). Downtown crane1 (174.5,11.5,
rot 270) gives 177.0,11.5, the point where pt4_wil15's Cop Car was taken within 10 s. Residential
crane8 (197.5,245.5, rot 200) gives 198.4,247.8, inside SINK OR SWIM's `IS_CAR_IN_BLOCK
(197.5,247.5, 3 x 3)`, so the rule agrees with a second script. The other cranes' hook points are
derived the same way and **not seen in game**.

What lost this step before (the shared `mission_play_wil.run_plan` crusher branch): `drive3(tol=0.7)`
straight at the hook point inside the walled yard. In rf4 that pressed the Cop Car along the yard
walls (175-185 x 14-16) from carhp 22000 until it caught fire.

## API

| call | does |
|---|---|
| `crane_near(district, x, y)` | `(name, crane)` of the crane whose tower is nearest |
| `hook_point(crane, r, dang)` | the hook point (above), optionally at another radius or angle |
| `lane(world, crane, hook, level)` | `((dx, dy), n)`: the axis with the most flat cells leading straight out of the hook cell at its level (the tower cell and the crusher platform excluded); the car creeps in along it |
| `candidates(world, district, name, crane)` | hook points to try, best first: the verified one (`KNOWN_HOOK`), then R, R +- 0.5, +-20 degrees; only points with flat ground and a lane of 2+ cells |
| `creep_lane(hook, d)` | straight up the lane with short pulses, nose kept on the hook; handbrake under it (`HOOK_TOL` 0.55). Stops on `CREEP_HP_DROP` (1500) carhp lost (a wall) or no progress for six pulses |
| `crush(world, district, crane_name, near, car, done, check, view_switch, budget, shops, shot_prefix, chase, tries)` | the whole step: `deliver_intact.deliver` (fragile pacing, respray) to the lane mouth only (`LANE_BACK` 4.5 blocks out), the creep, handbrake, out, a walk back down the lane past its mouth, then hands off for `TAKE_SECS` (35 game-s) while the car is followed in `view: cars` (z rising = `lifted`; gone from the list = taken). Not taken: back in, the next candidate. Returns `crushed`, `complete`, `failed`, `dead` or `stuck: ...` |
| `Clock` | wall seconds that skip a governor pause (each tick counts at most 3 s): the container, and this script with it, is frozen while the host's load is high |

Host survey, no game needed: `PYTHONPATH=gamerun python3 gamerun/skills/crusher_crane.py --survey
<game dir>` prints every crane's hook candidates and lanes. Downtown crane1: 177.0,11.5 L1, lane south
(0, +1) 7 cells, through the yard gate at 177-178 x 16 to the road on row 18. Residential crane1
(4.5,72.5) has no candidate with an open lane.

Marks `crusher: ...` in `/out/marks.txt` and `EVENTS`; frames `m_<prefix>_hook.png` (under the hook),
`_out.png` (on foot, clear), `_lifted.png`, `_crushed.png`, in the chase view when `chase` is given.

## COP CAR CRUSH runner

`missions/cop_car_crush.py`, fresh game, warps off:

1. the phone on the Zaibatsu HQ terrace (208.5,57.5, level 4) with `rooftop_access.answer_roof_phone`
   and `descend` (retried when a governor pause used up the climb's wall-time budget);
2. the Cop Car at 206.5,38.5 (`deliver_intact.board`), brief 1685;
3. Shady at the Avalon station: `horn_pickup.pickup` with the 2 x 2 box at 94.5,95.5 and
   `aboard_keys` 1694;
4. `crusher_crane.crush(world, "wil", "crane1")`: the yard (box 171.5,11.5, 24 x 8, brief 1697), the
   hook at 177.0,11.5, the crane; `IS_CAR_CRUSHED`, 1689, JOB COMPLETE 1124, +$20,000.

Fails: 1125 with 1683 (Cop Car wrecked), 1684 (sunk), 1687/1692 (Shady dead); death or arrest.

Run (speed 2, no video, screenshots every 5 s):

```
STAGE=<private stage> GTA2_SPEED=2 FPS=0 GTA2_DIRECT_KEYS=1 \
  INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' \
  gamerun/grun.sh ccc2 1800 missions/keys_cop_car_crush.sh -e GTA2DX9_STATE_EVERY=5
```

Summary in `out/<run>/ccc_result.json` (stage, events of the three skills, messages).

## Sessions

| session | phone | Cop Car / Shady | crane | outcome |
|---|---|---|---|---|
| ccc1 | the climb's 600 s wall budget spent during a 16-minute governor pause (17 game-s played) | - | - | not a test of the skill; the phone retry was added |
| ccc2 | on foot, 3 flights up and down, answered at game-s 160 | Cop Car 179 s; Shady aboard 367 s (3 horn presses), carhp 27919 | not reached: on the crusher leg `drive3` pushed the Cop Car into a stopped Bug at 144.1,35.4 at speed 0 for six seconds, carhp -1300 a second, alight | failed (stuck: the burning car left). `PinWatch` added: standing still while losing 2000+ carhp in 3 s breaks off the drive, backs off and drives on |
| **ccc3** | answered | Shady aboard 521 s, carhp 22136 | lane mouth reached at carhp 16336 (alight); the first creep aborted 5 blocks short on the burn's own damage (fixed: a burning car only aborts on a crash-sized step); second candidate 177.5,11.5: under the hook at 177.47,11.76 (0.26 off), out; the crane lifted it onto the crusher (z 3.00 at 176.5,9.5) at once | **JOB COMPLETE** 1124 at game-s 759, +$20,000, multiplier 2 |
| **ccc4** | answered (a 1199-wall-s climb through a governor pause, 144 game-s) | Shady aboard 623 s, carhp 25814 | the lane mouth at 177.5,16.0 scraped the yard gate (first creep aborted on 1522 carhp lost, 5 blocks short); second candidate: under the hook at 177.54,11.86, out; the car gone from `view: cars` 4 s later | **JOB COMPLETE** at game-s 879 (1689, 1124, money 20642). The runner's check raised on 1689 before the crusher frame (fixed). Lane mouth now centred on the lane's narrowest row (`lane_offset`), and `_flat` takes the highest lid so the gate posts count as walls |
| **ccc5** | answered at 80 s | Shady aboard 418 s, carhp 29591 | lane mouth 178.0,16.0 (the gate's centre); first creep under the hook at 177.03,11.55 (0.06 off) with no damage; out; the crane took it at once | **JOB COMPLETE** 1124 at game-s 666, money 20650, 0 faults |

**Result: 3 of 3 sessions with the pin guard (ccc3, ccc4, ccc5) reached JOB COMPLETE on COP CAR CRUSH,
the crane step itself 3 of 3; ccc5 on the final code took the hook at the first try.** 0 FAULT lines in
the three logs. Frames (chase view, not in git): `out/ccc3/m_ccc_crane_hook.png` (the burning Cop Car
under the hook, crusher and tower beside it), `out/ccc5/m_ccc_crane_hook.png`,
`out/ccc5/m_ccc_crane_crushed.png` and `m_ccc_end.png` (JOB COMPLETE with the crusher working behind).
The chase camera after the walk clear stands pressed against the yard's gate posts (the walk ends past
the gate), so the `_out` / `_crushed` frames are close behind the player.

Not verified: the hook rule on any crane but Downtown crane1 (the other eight jobs' cranes are derived
from the same rule and the map, and Residential crane8's point agrees with SINK OR SWIM's box); the
Krishna pair's `GET_CAR_INFO_FROM_CRANE` hand-over (COP CAR SCRAP); the module's PinWatch firing in
a session (it did not trigger in ccc3-ccc5). The sessions ran with the `gamerun/skills` copies of
`rooftop_access`, `deliver_intact` and `horn_pickup` as they were on 9 Nov 02:00-03:40 UTC.
