# Skill: truck and trailer (Wave M, SKILL-BUS, 9 Nov 2026)

Module `gamerun/skills/truck_trailer.py` (mirrored in `linux/docker/skills/truck_trailer.py`).
Runners: `gamerun/missions/distraction_action.py` (DISTRACTION ACTION!, `ste_zh2`) and
`gamerun/missions/operation_z.py` (OPERATION Z!, `ste_zm1`), keys scripts
`missions/keys_distraction_action.sh` and `missions/keys_operation_z.sh` (all mirrored in
`linux/docker/missions/`). Built on the frozen `mission_lib` / `drive_lib`, `skills/steal_car.py`
and `skills/deliver_intact.py`. None of those are changed.

**Status: no truck job has reached JOB COMPLETE. The acceptance (2 of 3 sessions) is not met.**
See "Sessions" below.

## What the 4 jobs ask

`truck_trailer` in `docs/missions-catalogue.json`: ste_zm1, ste_rm2, ste_zh2, bil_ze2. From the
decompiled scripts:

| job | cab | trailer | what has to happen with the rig | before it |
|---|---|---|---|---|
| ste_zm1 OPERATION Z! (yellow 224.5,34.5) | any `TRUKCAB1/2` (two are parked in `ste.mis`: 38.5,26.5 and 9.5,46.5) | transporter `TRUKTRNS` at 86,224.5, a Cop Car on it | hitch (2661), cab into the crane box 250.5,39.5 (3 x 3), the crane takes the Cop Car off (2662), Cop Car into the Village garage 211,31 | three cars into the same garage (a Pickup guarded by four machine guns, a Stratos-B with an armed driver, a Limo) |
| ste_rm2 BENSON BURNER! (yellow 84.5,29.5) | any cab (`SET_RECYCLE_MODEL_WANTED (TRUKCAB1)`) | Dwight T's transporter at 11.5,30.5 | hitch, crane9 (55.5,48.5) loads the Benson, tow to 234.5,151.5 | the Benson to the bomb shop (needs $5,000 cash) |
| ste_zh2 DISTRACTION ACTION! (red 208.5,25.5) | the hitched `TRUKCAB1 + TRUKTRNS` with the FBI car, inside the cop station yard (96.5,117.5) | comes hitched | in the cab: 60 s on the clock at three stars; the rig wrecked (2971) or unhitched (2973) fails | the rooftop generator at 82.5,116.5 z 6 destroyed |
| bil_ze2 GRAND THEFT AUTO! (green 45.5,161.5) | any cab | `TRUKTRNS` with a Cop Car at 40.5,65.5 | hitch, crane8, the Cop Car to the Power Cores | three other cars, one on an island reached over rooftops |

The script tests: `IS_CHARACTER_IN_MODEL (p1, TRUKCAB1|TRUKCAB2)` (any cab), `IS_TRAILER_ATTACHED`,
`IS_CAR_IN_BLOCK (cab, crane box)`, `GET_CAR_INFO_FROM_CRANE` / `IS_CAR_ON_TRAILER`, and
`IS_CAR_WRECKED (trailer)` (a fail in every job). The trailer is a car of its own in the renderer's
`view: cars` line: `TRUKTRNS` 66, `TRUKCONT` 65, `TANKER` 55; cabs `TRUKCAB1` 63, `TRUKCAB2` 64.
In Industrial traffic `TRUKCAB1` is common: 3106 sightings in hd1's 10 minutes, the fourth most
frequent model.

## API

| call | does |
|---|---|
| `rig(s)` | `(cab, trailer)` from the cars line: the player's cab and the trailer whose centre sits behind it at the hitch distance (1.2-5.0 blocks, behind the cab's axis) |
| `hitched(s)` | the trailer is behind the cab now and, while the cab moved, it moved too (the last 3 game seconds) |
| `get_cab(world, ...)` | into any cab: `skills/steal_car` on the cab models (parked ones walked to, traffic ambushed) |
| `hook_up(world, trailer, attached=...)` | line up 5.5 blocks ahead of the trailer's front on its axis, then reverse in short pulses, steering the cab's rear onto the hitch, until `attached()` (the script's brief) or the geometry test |
| `tow(world, x, y, lost=...)` | the shared driver with every carhp treated as "care" (speed cap `TRUCK_TOW_CAP`, 2.2 blocks / game s); `lost()` ends it ("lost") |
| `evade(world, done, ...)` | keep the rig rolling round a loop of road waypoints until `done()`: never stops (a standing cab at three stars gets jacked) |
| `crane_drop(world, box, done)` | into the crane box, all keys off, wait for `done()` (the crane's lift) |
| `Msgs` | every mission message key in order, polled from the log (shared with the bus runner) |

`hook_up`, `tow` with a real trailer, `evade` and `crane_drop` **have not been exercised in the
game yet**: no session reached a cab.

## DISTRACTION ACTION! (ste_zh2): blocked by the phone

The red phone runs `DO_PHONE_TEMPLATE (2818, ste_zh1.mis, ste_zh2.mis, savecount60, ..., zaibgang, 4)`.
With the Zaibatsu respect set to 100 by `skills/gang_respect.exe` (a developer aid, marked), the
phone starts the first job, MURDER IN THE MALL! (zh1, title 2469: 100 Scientists by a foot weapon).
zh1 ends only with 100 kills, a death or an arrest. The runner's `DA_SKIP_ZH1=1` ends it on purpose
(`[devtools] force_wanted=4`, standing in the street) to see whether the phone then offers zh2:

| session | what happened |
|---|---|
| da1 | warp to the street by the phone, phone answered: 2469 (zh1). One star on the phone terrace: no officer came up in 3 minutes (stopped by me) |
| da2 | down to the street, two then four stars: shot dead (lives 5 -> 4), zh1 over. Respect back to 100, the phone again: **6173 "How do you expect to rise up the Zaibatsu ranks with such pitiful displays, Gecko?"**, no job |
| da3 | zh1 again; the four-star wait ran out on a wall clock while the container was paused by the governor (zh1 still running). Seven more answers: 2813 "You are already doing a job" once, then nothing |
| da4 | the walker lost its way on the catwalk to the phone terrace (lives 5 -> 4 in a fall); stopped by me |

So in these sessions a failed zh1 did not open zh2 on the same phone: the job looks reachable only
by passing zh1 first. The runner is kept (generator, truck, 60 s evade written, untested).

## OPERATION Z! (ste_zm1)

The yellow phone's first job, so it needs no skipped job. Runner written (`operation_z.py`: four
legs, each one car into the Village garage with `deliver_intact`; leg 1 runs the four Rednecks over
from a borrowed car before the Pickup is taken; leg 4 the parked cab, the transporter at 86,224.5,
`hook_up`, `crane_drop` at 250.5,39.5, the Cop Car to the garage). **Not run yet.**

## Sessions

Settings: `SWAP_LEVEL=ste GTA2_SPEED=2 GTA2_DIRECT_KEYS=1 FPS=0`, shared `repo/stage`, plain
renderer, `-e DISTRICT=ste -e WARP_OK=0 -e DA_WARP_PHONE=1 -e DA_SKIP_ZH1=1 -e GTA2DX9_SCENE_NO_CAR=1`,
`scene_key=F11`. Sessions da1-da4 above. JOB COMPLETE: 0 of 4.
