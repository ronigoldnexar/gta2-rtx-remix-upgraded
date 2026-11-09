# Skill: escort / protect (Wave M, SKILL-ESCORT, 9 Nov 2026)

Module `gamerun/skills/escort.py` (mirrored in `linux/docker/skills/escort.py`), verified on
GET GAMA REI! (`wil_ym2`) with `gamerun/missions/get_gama_rei.py` (`keys_get_gama_rei.sh`).
Builds on the frozen `mission_lib` / `drive_lib` and the `deliver_intact` and `steal_car` skill
modules (SKILL-DELIVER, SKILL-STEALCAR); it changes none of them.

## What the 15 jobs ask

`escort_protect` in `docs/missions-catalogue.json`: wil_ye1, wil_ye2, wil_ym2, wil_zm1, wil_zm3,
wil_lm3, ste_sm2, bil_ke1, bil_km1, bil_km3, bil_kh1, bil_ze1, bil_zm2, bil_rh1, bil_rh2. In the
decompiled scripts the pattern is one of two:

- **A passenger.** The script creates a character and gives him `ENTER_CAR_AS_PASSENGER (car)`,
  waits on `IS_CHAR_OBJECTIVE_PASSED`, then on the car reaching a box; `HAS_CHARACTER_DIED`
  fails the job, and the final `PARK` is only issued when `IS_CHARACTER_IN_CAR (chr, car)`.
  Killers are often sent after him (`SET_CHAR_OBJECTIVE (killer, KILL_CHAR_ANY_MEANS, chr)`:
  GET GAMA REI's two Loony Isettas with a machine gun and a pistol).
- **A follower on foot.** The character follows the player and must be led to a point
  (DECONSTRUCTION YARD's Leo, LOCK-OUT's slow Satchmo, ROOFTOP RESCUE's Krishna).

A boarding character only walks to a car that stands still; a moving car or a car pinned against a
wall far from him is never boarded. He is logged by the renderer (`view: peds`, docs/actions-3d.md
"Ped and car log lines"): on foot with his own position, in a car with `m<model>` and the car's
position; a kind-2 arrow on him shows as `a<slot>`.

## API

| call | does |
|---|---|
| `Escort(name, pick, near, radius, count)` | picks the protected people from `view: peds` (predicate on the ped dict, a spawn point and radius, how many) and tracks them by ped id: `acquire(secs)`, `members()`, `aboard(s)`, `on_foot()`, `spread()`, `where()`, `dead()` (seen dead, or vanished from the 24-block window while within 12 blocks of the player) |
| `wait_board(world, esc, car, budget, horn, move, done, check)` | in the car, keys off (optional horn), until every member is in the player's car or `done()`; a member who makes no progress toward the car for `STALL_SECS` (scaled by `GTA2_SPEED`) gets the car brought beside him (`bring_car`, at most 3 times; `move=False` for a job that pins the car in a box) |
| `drive(world, box, esc, car, check, threat_pick, car_threat_pick, ...)` | `deliver_intact.deliver` to the box with two watches folded into the job's check: an escortee off the car on three reads in a row stops the drive and returns to `wait_board`; killers near (a car matching `car_threat_pick` within 14 blocks, or an armed ped matching `threat_pick` within 9 of an escortee) raise the fragile-drive caps to `ESCORT_THREAT_CAP` (3.4) while carhp >= 19000 |
| `lead(world, esc, goal, ...)` | on foot: legs of 3 blocks along `route3`; waits while the follower is more than `GAP` (3.5) behind, walks back to him past `LOST` (11); defends when threats close in |
| `threats(esc, pick)`, `threat_cars(pick)`, `defend(world, esc, pick, secs)` | hostile peds/cars near the escort; `defend` shoots the nearest with the trigger held off while an escortee stands in the line of fire (a side step instead) |

Every step marks `/out/marks.txt` with `escort: ...` and appends to `EVENTS`.

## GET GAMA REI! runner

The yellow phone opens at Yakuza respect 2 (`DO_PHONE_TEMPLATE (..., yakuzagang, 2)`); each green
Yakuza job passed is +1 and each failed one -1 (`CHANGE_GANG_CHAR_RESPECT_AND_UPDATE`). A session
therefore plays BANK ROBBERY (`missions/bank_robbery.py`) and GET ZITZAKI (`missions/get_zitzaki.py`)
first, imported unchanged with their view state shared, up to `GR_GREEN_TRIES` (2) times each, then:

1. any Medicar (model 34) through `steal_car` (search points round both hospitals);
2. `deliver` into `IS_CAR_IN_BLOCK (88.5, 84.5, 3 x 2)` (the arrow is removed there; brief 1374);
3. `wait_board` for Gama Rei (`CREATE_CHAR 92.5,83.5`, remap 13), `done` = brief 1377/1378 or the
   arrow on the safehouse;
4. `drive` to `IS_CAR_IN_BLOCK (35.5, 187.5, 4 x 2)` with the Isettas (model 29) and armed Loonies as
   threats; `PARK (door7)`, JOB COMPLETE 1124, +$40,000.

## Sessions

(filled in below as they run)
