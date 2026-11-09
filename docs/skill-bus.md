# Skill: bus (Wave M, SKILL-BUS, 9 Nov 2026)

Module `gamerun/skills/bus.py` (mirrored in `linux/docker/skills/bus.py`). Proof runner
`gamerun/missions/hot_dog_homicide.py` with keys script `missions/keys_hot_dog_homicide.sh`
(mirrored in `linux/docker/missions/`). Built on the frozen `mission_lib` / `drive_lib`,
`skills/steal_car.py`, `skills/deliver_intact.py` and `missions/russian_sailors.calm_drive`. None
of those are changed.

**Status: no bus job has reached JOB COMPLETE. The acceptance (2 of 3 sessions) is not met.** The
runner gets the phone, a bus and the bus to every stop. It does not get passengers aboard: the
first load (`IS_BUS_FULL`) never came in 10 sessions. The cause is not known; it is below.

## What the 4 jobs ask

| job | bus | what the bus is for |
|---|---|---|
| bil_re1 HOT DOG HOMICIDE! (green 187.5,76.5 L6) | any `BUS` (model 11) from traffic (none is parked in `bil.mis`) | filled twice at bus stops (`IS_BUS_FULL (p1)`, then `KILL_ALL_PASSENGERS`), then into the meat plant garage (184,30) |
| ste_se2 FAKE TRUCE! (green 235.5,202.5) | the Factory Bus at 227.5,214.5 | four horn pick-ups: `skills/horn_pickup.py` (SKILL-HORN) |
| bil_km3 CONVERSION EVASION! (yellow, follow-up) | a Krishna Karma Bus (`KRSNABUS`) | Krishna board, to the Vedic Temple |
| bil_zm3 GANG WAR! (yellow, follow-up) | a Krishna Karma Bus | 50 Russians run over |

HOT DOG HOMICIDE in detail (`assets-src/missions/bil_m/bil_re1.mis`): 3854 title, 3400 brief,
`STOP_CHARS_GETTING_OFF_BUS (p1, ON)`. In a BUS: 3401 ("Find yourself a Bus Stop and pick up
passengers. I will let you know when you have enough"). Each full load is taken off silently, and
after the second one comes 3403 and the arrow at the garage. A wrecked bus restarts the count
(3423); that is not a fail. Then `PARK` at door7, 3404, on foot to the top of The Cage (185.5,24.5
z 4, `LOCATE_CHARACTER_ON_FOOT` 1 x 1, then a 7 x 5 box) until six groups of "drones" are dead.
Then the Hot Dog Van at 194,24 goes to the Kovski Diner (12,120, door8 opens to the east): 3420,
3100 JOB COMPLETE, $40,000.

## API

| call | does |
|---|---|
| `bus_stops(district)` | the map's bus-stop zones (`ZONE` chunk type 7): Industrial `busstop1` 109,52, `busstop2` 18,133, `busstop3` 69,214, `busstop4` 225,142; Residential `bus_stop01..07` |
| `stop_point(world, stop)` | the road cell beside the stop's pavement cell, and the travel direction that puts the stop on the bus's right |
| `get_bus(world, ...)` | `steal_car` on the bus models in 300 s attempts. The tour patrols a 28-block stretch of the route through `busstop1` three times (`BUS_SEARCH_FIRST`), then the other stops. A bus held for a moment only during a jack does not count |
| `bus_drive(...)` | `calm_drive`, plus a 12 s smooth burst when it makes no progress for 30 game s. The burst stops at the first hit of 1500 carhp |
| `creep_to(x, y)` | throttle pulses steered at a point, at walking pace |
| `serve_stop(world, stop, full)` | lane driver to 7 blocks short of the stop. Then a lane change along the kerb line, level with the people waiting (occupation 8 in the peds line). Then stop, horn, and wait while the money rises, up to `dwell` (70 game s). Halfway through with nobody aboard: one lane out, 2.5 blocks on, horn, wait again |
| `fill(world, full)` | stop after stop, never the same one twice running, until `full()` |

## What the sessions showed

- **Finding a bus.** Buses are rare in Industrial traffic. hd1 toured at random for 10 minutes and
  saw none (`TRUKCAB1` was seen 3106 times). Every bus taken was on the busstop1 stretch: 109,53
  (hd2), 100.6,53 (hd3), 96.4,53 (hd4), 94.9,53 (hd6), 84.5,53 (hd9) and 120.5,53 (hd10), within
  2-3 minutes of reaching it. Touring the far stops first cost 10-17 minutes (hd5, hd8).
- **The stop.** The lane driver ends one lane out from the kerb (frames `m_bus_busstop2.png`
  hd2, `m_bus_busstop3.png` hd5). The kerb-line creep puts the bus at the kerb beside the
  shelter (hd6 frame `m_bus_busstop1.png`).
- **Boarding: not solved.** People who walk to a stop and wait there are occupation 8, state 7/14,
  in the `view: peds` line (hd9: ped 1387 walked along the kerb to 109.8,52.5 and stood). None of
  them boarded:
  - in hd6/hd9 the bus stood at the kerb beside them for 70 game s with four horns;
  - in hd10 it tried the kerb first and then one lane out.
  The only boarding seen was in hd2: at busstop2 three people were listed in a car of model 11
  beside the bus, and the money went 80 -> 130. That was with the bus a lane out after a stalled,
  reversing minute by busstop1. It did not happen again. The money also rose by 10 a few times
  while driving (hd9, hd10). With no passenger counter readable (passengers are not in the peds
  line once aboard), the first load cannot be seen. Only 3403 after the second load is a signal.
- **The bus is fragile in queues.** In hd4 a 25 s smooth burst out of a queue at busstop1 took it
  from 31000 to 13800 carhp and set it alight (the burst is now short, and stops at the first hit).
  In hd9 the bus burned on the way to busstop4 under `calm_drive`.

Next step: find the rule the game uses to board waiting peds onto the player's bus. That is a
read of `gta2.exe`, or a probe that logs the waiting peds' state while the bus approaches each
of the four stops from both directions. Until then the later stages (garage, Cage, van) are
written but untested.

## Sessions

Settings: `SWAP_LEVEL=bil GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0`, shared `repo/stage`, plain
renderer, `-e DISTRICT=bil -e WARP_OK=0 -e HD_WARP_PHONE=1 -e GTA2DX9_SCENE_NO_CAR=1`,
`scene_key=F11`. The phone was reached on foot in every session (the warp's street cell was
already within 40 blocks of the walker's route; phone answered 3400/3854 in 119-188 game s).

| session | bus | stops | stopped because |
|---|---|---|---|
| hd1 | none in 10 min (random tour) | - | stopped by me: the tour now patrols the bus stops |
| hd2 | 115 s, busstop1 | busstop1 (0 aboard), busstop2 (**3 aboard, money +50 on arrival**), busstop3 | stopped by me: the bus stops a lane out |
| hd3 | 144 s | busstop1, busstop2 at the kerb (overshot 1.5 blocks) | stopped by me |
| hd4 | 147 s | busstop1 (1 waiting, none on) | the bus burned in a queue (smooth burst) |
| hd5 | 589 s (busstop3) | busstop3 (2 waiting, a lane out) | stopped by me: kerb creep rewritten |
| hd6 | 179 s | busstop1 at the kerb beside the shelter, 70 s, 1 waiting, none on | stopped by me: horn added |
| hd7 | - | - | steal_car walked at an unreachable standing bus for 5 min (short attempts added) |
| hd8 | none in 17 min (far stops first) | - | stopped by me: busstop1 patrolled first |
| hd9 | 2 attempts, then 84.5,53.5 | busstop1/2/3 with horns, 1/0/0 waiting, none on | the bus burned on the way to busstop4; stopped |
| hd10 | 2 buses (the first kept only for a moment) | busstop1 kerb then lane out, 2 waiting, none on | stopped by me |

JOB COMPLETE: 0 of 10.
