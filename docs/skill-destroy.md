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
2. a far target: by car (a borrowed car that burns is left at once, pt6_le2e), out of it
   `leave_at` (14) blocks off; a moving target that loops a circuit is waited for on the pavement
   beside the arrow track's nearest point;
3. in range (`engage` 11): walk at it with the trigger held, aiming `0.35 x speed` (at most 1.2)
   blocks ahead of a moving car, stop `stand_off` (4) short; a car coming straight on (lateral
   offset under 1.3 within 4.5 blocks) gets a step out of its lane;
4. a burning target (`fire` > 0 or hp under 16000) is kept `blast` (4.5) blocks away: its
   explosion kills a player beside it;
5. no damage for `stall` (6) game seconds while firing: a side step across the line, every third
   time closer;
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

(filled in below as they run)
