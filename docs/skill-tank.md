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
| `fight(world, kind, count, secs, check, models, select, marked, reach, cone, stall, roam, burn, shot_prefix, turn_max)` | fights from the tank: `kind` `cars` or `peds`; returns `done` (count reached by our count), `time`, `out` |
| `drive(world, x, y, ...)` | `mission_lib.drive3` with the tank |
| `leave()` | keys up, out |

What the tank does (probes `tkp1`-`tkp3`, `gamerun/tank_probe.py`, top-down frames; the scene warp
is used in the probes only):

- **Fire:** one shell per press of the fire key (Control_L tapped). Held, it fired nothing seen
  (`tk1`: a whole minute held, nothing wrecked). The shell flies along the barrel and bursts on the
  first thing it meets (a wall 4 blocks off, `tkp3` `m_tp_base_s0..3`). In a kill frenzy the
  mission line's `ammo` reads -1 (unlimited), so shells can't be counted from it.
- **Turret:** stays on the hull's line. No key turned it standing: Left, Right, Z, X, Tab,
  Space+Left, fire+Left (`tkp3`).
- **Hull:** turns only while it rolls (Up or Down held with Left/Right; reversing swaps the
  steering), about 0.6 rad per game second at full drive (`tk4` log). It drives about one block per
  second (`tk5`: 25 blocks in 25 s).
- **Entry:** slow (up to 10 s to the seat under load). A second Return during it takes the player
  out of the seated tank (`tkp1`, `tkp2`: `mission_lib.enter_car3` polls 5 s and presses again).
  The frenzy tank is then locked against him (`CHANGE_CAR_LOCK LOCKOUT_PLAYER`), which ends the
  frenzy. `tank._enter` presses Return once per try and waits up to 15 s.

How it fights: the targets are scored by distance, plus 8 x the turn they need, less 1.5 per
neighbour within 1.6 blocks (a blast takes the queue with it); a marked target comes first. It taps
when the target is within `max(cone, atan(0.7/d))` of the nose, steps closer beyond 0.7 x reach,
and backs off inside 1.8 blocks. Burning cars are no targets (`tk2` spent 50 s and about 100
shells on a pile of burning wrecks in the line of fire). A target whose hp does not drop after 4
taps is skipped for 6 game seconds (a wreck or wall in between). A target more than `turn_max`
off the nose gets no rolling turn. With no target in reach it patrols the roam points with drive3,
tapping at whatever crosses the nose (drive3's `until` hook). No motion for `stall` game seconds
gives a reversing turn. Kills are counted when a car seen alive in reach goes to hp 0 or catches
fire. That count matched the game's own frenzy counter in `tk3` (HUD 12 left = 8 destroyed).

## Sessions

`wil_kf08` (destroy 20 vehicles from the tank in 60 s). Fresh game, on foot (or by car) from the
level start to the tank, no warp; `GTA2_SPEED=1 FPS=15 GTA2_DIRECT_KEYS=1 gamerun/grun.sh <run> 700
missions/keys_tank_frenzy.sh -e TANK_FRENZY=wil_kf08`.

| run | fight code | in the tank | counted | shells | result | what it taught |
|---|---|---|---|---|---|---|
| tk1 | fire held, standing turns | yes (walk 190 cells after a stalled drive) | 0 | ? | FRENZY FAILED | a held trigger fires nothing; Left/Right standing don't turn the hull |
| tk2 | taps | yes | 4 | 118 | failed | burning wrecks soaked the shells for 50 s |
| tk3 | taps, burning cars excluded, miss-skip | yes | 8 (HUD agrees) | 30 | failed | 87 rolling turn pulses: turning eats the minute |
| tk4 | + distance cone, turn cost 8, crowd bonus, reach 13 | yes | 8 | 34 | failed | 97 turns; the hull turns ~0.6 rad/s |
| tk5 | patrol to the busy roads, fire on the move | yes | 3 | 7 | failed | the tank is too slow to reach the traffic within the clock |
| tk6 | tk4's turning (turn_max 1.2) + a short patrol by the yard | yes | 4 | 6 | out: busted | wanted 1 from the wrecks; two cops a block off pulled him out of the standing tank and shot him (04:24:33) |
| tk7 | + police defence: a cop/army ped on foot within 3 blocks keeps the tank rolling at him | yes | 9 | 22 | failed | best so far; no bust |

Status (after tk7): the skill gets a tank (every frenzy session tk1-tk5 got in; probes tkp1/tkp2 lost theirs to the double Return before the one-Return entry), drives
it, and fights with it (up to 9 cars in the minute by our count; the count matched the game's HUD counter in tk3). The frenzy's
20 in 60 s has **not** been passed, so no session reached its extra life. The phone jobs need
respect and the other districts, and were not attempted.

What would raise the rate (not done): the traffic by the yard (road x 8-11) gives about one target
in reach every 6-7 s, and the busier roads are out of reach within the clock. Waiting at the
junction y 148-150 facing the oncoming lane (no turning) and firing into the queue that forms behind
the first wreck is the next thing to try. The turret keys, if GTA2 has any, would remove the
turning cost. ste_kf02 and bil_kf02 give 120 s for 20 and 30 cars, so they are likelier passes for
this skill as it is (other districts: `SWAP_LEVEL`).
