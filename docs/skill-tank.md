# Skill: the tank (Wave M, SKILL-TANK, 9 Nov 2026)

Module `gamerun/skills/tank.py` (mirrored in `linux/docker/skills/tank.py`), verified on the Downtown
tank kill frenzy `wil_kf08` with `gamerun/missions/tank_frenzy.py` (`missions/keys_tank_frenzy.sh`).
Builds on the frozen `mission_lib` / `drive_lib` (unchanged) and, for a tank in traffic, on
`skills/steal_car.py`.

## What the jobs ask

`tank` in `docs/missions-catalogue.json`: six phone jobs and six kill frenzies.

| job | the tank step | script facts |
|---|---|---|
| wil_yh2 STOP THE TANK | stop a tank driving at Johnny Zoo's cars | `CREATE_CAR (102.5,166.5) TANK`, bulletproof, locked, arrow on it |
| ste_rm3 TANKS-GIVING | steal the army base's tank, drive it to the RV | `CREATE_CAR (231.5,90.5) TANK` |
| bil_km3 CONVERSION EVASION | destroy three tanks round Z-Lab | tanks at 64.5,241 / 56.5,241 / 59.5,246 |
| bil_zh1 I'D LIKE A TANK PLEASE, BOB! | park a tank at Uno Carb's garage | `IS_CHARACTER_IN_MODEL (p1, TANK)`; a tank created at 15.5,195 |
| bil_zh2 ARMY BASE ALERT | steal the army base's tank, bring it to the garage | `CREATE_CAR (158,246) TANK` and three guard tanks |
| bil_rm3 TANKS A LOT | destroy three Zaibatsu tanks | 218.5,53.5 / 223.5,72.5 / 223.5,87.5 |
| wil_kf07 / wil_kf08 | 35 people / 20 vehicles in 60 s | parked tanks 226.5,238.5 z2 / 3.5,164.5 z3 (`PARKED_CAR_DATA`) |
| ste_kf01 / ste_kf02 | 20 people / 20 vehicles in 120 s | 13,83 z2 / 29,178 z3 |
| bil_kf01 / bil_kf02 | 30 people / 30 vehicles in 120 s | 3,30 z3 / 72,219.5 z2 |

A kill frenzy starts when the player gets in (`THREAD_WAIT_FOR_CHAR_IN_CAR`, then
`START_BASIC_KF_TEMPLATE (..., TANK_GUN)`), counts kills `BY_ANY_WEAPON` made from the `TANK`
(cannon and crushing alike), pays an extra life, and locks the tank against the player once he
leaves it.

## API

| call | does |
|---|---|
| `get_tank(world, spot, budget, check, jack, search)` | into a tank: the parked one at `spot` (x, y, level), else the nearest free tank in the cars window, else (`jack`) the steal-car skill with model 54 (army tanks at six stars, a job's tank) |
| `in_tank(s, ms)`, `tanks(free_only)` | the player at a tank's wheel (`carmodel=54`); the tanks in sight |
| `fight(world, kind, count, secs, check, models, select, marked, reach, cone, stall, roam, burn, shot_prefix)` | fights from the tank: `kind` `cars` or `peds`; returns `done` (count reached by our count), `time`, `out` |
| `drive(world, x, y, ...)` | `mission_lib.drive3` with the tank |
| `leave()` | keys up, out |

How it fights: the hull aims and the turret stays on the hull's line (the turret's own keys are not
known to the scripts, and the renderer logs a turret's aim once per tank); targets within `reach`
are scored by distance plus the turn they need (a marked one first); the trigger is held while the
target is within `cone` of the nose; nothing in reach: drive3 toward the next roam point with
`until` = a target ahead in reach; no motion for `stall` game seconds: back off and turn. At the
start one Left pulse measures whether the hull turns standing (else turns are made rolling).

## Sessions

(filled in below as they run)
