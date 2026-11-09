# Skill: destroy a vehicle (Wave M, SKILL-DESTROY, 9 Nov 2026)

Module `gamerun/skills/destroy_vehicle.py` (mirrored in `linux/docker/skills/destroy_vehicle.py`),
verified on PIZZA CAKE! (`wil_le2`) with `gamerun/missions/pizza_cake.py`
(`missions/keys_pizza_cake.sh`). Builds on the frozen `mission_lib` / `drive_lib`; it changes
neither (it uses `cars()`, `mission_arrows()`, `arrow_track` / `ambush_point` / `stand_point`,
`_aim_walk`, `fetch_gun`, `ram_target` as they are).

## What the 13 jobs ask

`destroy_vehicle` in `docs/missions-catalogue.json`: wil_yh2 STOP THE TANK, wil_zm3 BIG BANK JOB,
wil_zh1 ARMORED CAR CLASH, wil_le2 PIZZA CAKE, wil_end THE FINAL JOB, ste_sh1 TAXI TRAITOR TEST,
ste_zm1 OPERATION Z, ste_rh1 GANG CAR BANG, bil_ke1 DECONSTRUCTION YARD, bil_km3 CONVERSION
EVASION, bil_rm1 OFFICER DOWN, bil_rm2 KARMA ASSASSINS, bil_rm3 TANKS A LOT. In the decompiled
scripts the step is one of three:

- **A marked car.** `POINT_ARROW_AT (arrow, car)` and `WHILE_EXEC (NOT IS_CAR_WRECKED (car))`
  (PIZZA CAKE's van, ARMORED CAR CLASH's two Yakuza cars, OFFICER DOWN's cop cars / SWAT van /
  agent cars, the tanks of STOP THE TANK and TANKS A LOT). The renderer logs the car with its arrow
  slot (`view: cars ... :a<slot>`) and its health (`hp` = 32000 - damage, 0 for a wreck), and the
  first kind-3 arrow's car again as `tcarhp= tcarfire= tcar=x,y` in the `view: mission` line
  (docs/actions-3d.md "Vehicle fields").
- **A count of a model.** GANG CAR BANG's 5 Meteors and 5 Z-Types, the kill frenzies'
  `CAR` / `COPCAR` counters: no arrow; any car of the model counts.
- **A car that only one weapon hurts.** KARMA ASSASSINS' armoured bus (car bomb only), the tanks
  (rockets or a hijack). The skill's gun loop sees no damage there (`stall`); those jobs need
  the job's own weapon first.

## API

| call | does |
|---|---|
| `destroy(world, select, models, count, check, secs, engage, stand_off, blast, leave_at, stall, view_switch, shot_prefix, ram, money0)` | wrecks `count` targets: the marked cars (or, with `models`, any car of those models) picked by `select(c)` on the `view: cars` dict. Returns `done`, `no gun`, `timeout` or `stuck`; `check()` raises the job's own exception when the job ends |
| `targets(select, models)` | the live target cars in the 30-block window, nearest first |
| `car_arrows()` | `(slot, x, y)` of the vehicle arrows (kind 3): where a marked car is beyond the window |
| `Track` | per-car samples by renderer id: `motion(id)` (heading and speed in blocks per game second), `hp_drop_since` |
| `job_state()`, `default_check()`, `JobOver` | the job's outcome from the game's own messages (1124/1125 and twins, death, a lost life) |

How it fights:

1. a gun in the hand (`select_gun`; a pickup fetched with no rounds at all); ramming
   (`mission_lib.ram_target`) only when there is no gun anywhere (PIZZA CAKE parts 4-5: every
   ramming session but one burned our own car or killed the player at the wheel);
2. a far target is pursued (`pursue_leg`): by car from a parked car within 25 blocks (never a
   kerb wait for a passing car: dv_pc2 was run over at the kerb), in 15-second legs aimed a little
   ahead of its current position, each stopped early by `drive3(until=...)` when the police want
   us or a target stands within `leave_at` (14) or is within 8 blocks; out of the car there. A
   borrowed car that burns is left at once (pt6_le2e). 30-second legs blind to the wanted level
   got the player pulled out and arrested twice (dv_pc5, dv_pc7), so at the wheel a wanted level
   means out and on foot;
3. on foot (wanted, or no car): within 45 blocks walk at it; farther, wait at its favourite stop:
   `dwell_spot` reads the arrow track and picks the cell where it stood longest (traffic lights,
   a junction), weighted by distance; kept until it has not come within 20 blocks for
   `SPOT_KEEP` (300) game seconds; `mission_lib.ambush_point` (fast samples only) is the
   fallback. Waiting alone found the Pizza van in 1 of 4 sessions (dv_pc4, dv_pc6-8): it roams the
   whole town at about 1.5 blocks per game second over 30 s, standing about half of the time;
4. in range (`engage` 11): walk at it with the trigger held, aiming `0.35 x speed` (at most 1.2)
   blocks ahead of a moving car, stop `stand_off` (4) short; a car coming straight on (lateral
   offset under 1.3 within 4.5 blocks) gets a step out of its lane; a burning target is kept
   `blast` (4.5) blocks off only under `BLAST_HP` (4000): dv_pc4 backed off at 16000 and its
   rounds from 5 blocks did a sixteenth of the damage of those from 3-4;
5. no damage for `stall` (10) game seconds while firing: closer while it stands (a side step
   otherwise); out of rounds with the target alight and standing: watch it burn out from
   `BURN_WATCH` (6) blocks (it loses about 50 hp a game second by itself), else to a pickup;
6. a wreck is `hp` 0 in `view: cars`, or the car gone from the window while it was within 18
   blocks and no arrow is left away from its last position; for marked targets the step also ends
   when every vehicle arrow is gone after one was seen.

With `GTA2_DIRECT_KEYS=1` the walker and the gun run in the chase view (`mission_lib.foot_view`),
so every frame of the fight is a third-person one. Frames: `m_<prefix>_engage.png`,
`_burning.png`, `_wreck1.png`; marks `destroy_vehicle: ...` in `/out/marks.txt`, also in `EVENTS`.

## PIZZA CAKE runner

`missions/pizza_cake.py`, fresh game, all on foot to the job (the Loonies refuse a job after a
drive through their turf):

1. the machine gun at the pickup beside the Loonies' phones (76.5,39.5), before the phone;
2. the phone (75.5,41.5; title 1955, brief 1531), keeping off the RADIO ZA-ZA phone beside it;
3. the explosives box 28.5,106.5 (z 3, 1 x 1), then Pizza Cake 13.5,105.5; the five-second fuse
   run along `escape_route`;
4. brief 1538: the van (created at 125.5,149.5 with a criminal driver, an arrow on it):
   `destroy(world, count=1)`; JOB COMPLETE 1124, +$20,000.

Run: `GTA2_SPEED=2 FPS=0 GTA2_DIRECT_KEYS=1 INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' gamerun/grun.sh <name> 1300 missions/keys_pizza_cake.sh`.

## Sessions

All on `repo/stage` at 2x (`GTA2_SPEED=2`, `FPS=0`, screenshots every 5 s plus the milestone
frames), `GTA2_DIRECT_KEYS=1`: every frame of the job is in the chase view. Fresh game each time.

| session | outcome | what happened (fix) |
|---|---|---|
| dv_pc1 | phone: RADIO ZA-ZA started | the 4-cell walk from the gun pickup to the phone was straightened across RADIO ZA-ZA's phone at 75.5,40.5 (title 1954). Fix: approach from 76.5,42.5 and nudge |
| dv_pc2 | JOB FAILED (dead) | phone, explosives, delivery, fuse all passed; `any_car2` waited at the kerb at 4.5,103.5 and a car at 4 blocks/s ran him over. Fix: no kerb waits in the skill |
| dv_pc3 | phone: RADIO ZA-ZA started | `fetch_gun`'s search circle round the pickup stepped onto the neighbour phone before the job. Fix: the gun after the phone (then that phone only says 1103) |
| dv_pc4 | timeout | waited at the track, the van came and stood; 300 rounds took it 32000 -> 12136 (alight), but from 4.5-5.6 blocks (the blast rule backed off at 16000) most missed; out of rounds, walked off to a pickup. Fix: blast distance only under 4000; out of rounds by a burning target, watch it burn |
| dv_pc5 | JOB FAILED (arrested) | the van chased by car for 8 minutes; a bump near a cop, wanted 1, pulled out of the car |
| dv_pc6 | timeout | the van stood 7.7 blocks off (32000 -> 25600), the stall rule side-stepped after 2 s and it drove off; the ambush spots were chosen 100 blocks away. Fix: `dwell_spot`, stall 10 s and closer while it stands |
| dv_pc7 | JOB FAILED (arrested) | a 30 s car leg to the waiting spot, wanted 1 after a bump, pulled out by a cop. Fix: walk under 90 blocks, out of the car when wanted |
| dv_pc8 | timeout | on foot only: the van roamed the east side (x 168, y 149) and never came within 26 blocks in 40 game minutes. Fix: the pursuit by car in short legs stopped by the wanted level |
| **dv_pc9** | **JOB COMPLETE** (1124, +$20,000, 365 s from the phone) | in a parked car 16 blocks from the fuse spot, five 15 s legs after the van; out 10 blocks from it as it slowed at 146,149.5, walked at it firing (282 rounds), wrecked at 3.7 blocks. Frames `m_pc_van_engage.png`, `m_pc_van_burning.png` (firing at the van, chase view), `m_pc_end.png` (JOB COMPLETE banner and the payoff brief, chase view) |
| **dv_pc10** | **JOB COMPLETE** (193 s from the phone) | no parked car near; walking at the arrow, the van stopped at the junction 59.5,134.1, 12 blocks off: 100 rounds from 2.7-12 blocks took it 32000 -> 2345 in 5 s and it blew up. Chase-view frames as above |
| **dv_pc11** (1x, recorded, `game.mp4`) | **JOB COMPLETE** (309 s from the phone) | a parked car 44 blocks from the van, one pursuit leg, out 13 blocks off as it stood at 59.5,115; 17 s of fire, the skill logged the wreck itself (`wrecked 243 (m68) at 59.5,115.1`) a second before JOB COMPLETE. `m_pc_end.png`: the van's explosion behind the banner, chase view |

**Result: with the final code (`pursue_leg`, dv_pc9-11) PIZZA CAKE reached JOB COMPLETE in 3 of 3
sessions, every frame of the job in the chase view.** Not yet run on the other 12 jobs: the
module's model-count mode (`models=`, GANG CAR BANG, the frenzies) and multi-target counts
(ARMORED CAR CLASH, OFFICER DOWN) are untested in a game; armoured targets (tanks, KARMA
ASSASSINS' bus) need the job's own weapon first (the stall rule will see no damage).
