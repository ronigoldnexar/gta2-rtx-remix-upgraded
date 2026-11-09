# Skill: horn pick-up (Wave M, SKILL-HORN, 9 Nov 2026)

Module `gamerun/skills/horn_pickup.py` (mirrored in `linux/docker/skills/horn_pickup.py`), verified on
FAKE TRUCE! (`ste_se2`, the SRS Scientists' green phone 235.5,202.5) with
`gamerun/missions/fake_truce.py` (`missions/keys_fake_truce.sh`, mirrored in `linux/docker/missions/`).
It builds on the frozen `mission_lib` / `drive_lib` and the `deliver_intact` skill module
(SKILL-DELIVER), and changes none of them.

## What the 13 jobs ask

`horn_pickup` in `docs/missions-catalogue.json`: wil_ye1, wil_ym1, wil_ze1, wil_zm1, wil_zm2, wil_zm3,
wil_lm3, ste_se1, ste_se2, ste_sm2, ste_sh1, bil_km1, bil_re2. The decompiled scripts all use one
three-step pattern:

1. A character (often a group, `ADD_GROUP_TO_CHARACTER (chr, n)`) waits on foot with the arrow on him.
   The player must be in the mission car inside a box round him (`LOCATE_CHARACTER_BY_CAR (p1, x, y, z,
   w, h)` or `LOCATE_ANOTHER_CHARACTER_BY_CAR`). The script then says "Sound the horn" (Residential
   2278, Downtown 1638, Industrial 3526).
2. `IS_CHAR_PRESSING_HORN (p1)` answers with a brief and `ENTER_CAR_AS_PASSENGER`. A counter blocks a
   second horn at the same stop. So the car must already stand where he can walk to it when the horn
   sounds, and must stand still: a moving car is never boarded.
3. `IS_GROUP_IN_CAR` / `IS_CHAR_IN_CAR` moves the job on to the next stop's brief and arrow, or to the
   drop-off. On the way the job fails if the car is wrecked or sunk, or if he (or too many of his
   group, `CHECK_NUMBER_ALIVE_IN_GROUP`) dies. A car that stops on him kills him (pt8_bil2).

## API

| call | does |
|---|---|
| `Msgs()` | follows the mission line's message keys in order (`poll`, `mark()`, `since(keys, mark)`, `last()`), so the same "Sound the horn" key at four stops is told apart and sub-second briefs are not missed |
| `Stop(name, x, y, w, h, horn_keys, aboard_keys, aboard, man, count, pick)` | one pick-up: the locate box (centre, full sizes), the brief that says the horn was taken, the brief (or a test) that says they are aboard, where he stands (the kind-2 arrow on him overrides), the group size, a ped predicate for the log |
| `stand_point(world, stop, s, avoid)` | where the car stops: inside the box with `BOX_MARGIN` (0.7) in, flat ground at his level, `STAND_MIN`..`STAND_MAX` (2.2-4.2) blocks from him, a road cell preferred, nearest the car |
| `pickup(world, stop, msgs, car, check, view_switch, shops)` | the whole stop. A long leg uses `deliver_intact.deliver` (fragile pacing, respray) to the box's edge. Then a slow drive to the stand point, a full stop, and the horn until the script takes it (`horn_keys`). Then hands off while they board. A group that makes no progress for `STALL_SECS` (22 s at speed 1) gets the car moved to another stand point (at most 3 times, without the horn, which is taken only once). If he is out of the car, he gets back in |
| `pickups(world, stops, msgs, ...)` | every stop in turn; `(n done, last answer)` |
| `drop_off(world, box, msgs, arrived_keys, get_out, clear)` | `deliver_intact.deliver` into the drop-off. Optionally gets out and walks `clear` blocks away from the box |
| `walk_clear(world, dist, away)` | on foot, to a street point away from a spot |

Answers are strings: "aboard", "delivered", "complete", "failed", "dead", "timeout: ...",
"stuck: ...". Every step marks `/out/marks.txt` with `horn: ...` and appends to `EVENTS`.
Milestone frames: `m_horn_<stop>_box.png`, `_horn.png`, `_aboard.png`, `m_horn_dropoff.png`.

## FAKE TRUCE! runner

From `assets-src/missions/ste_m/ste_se2.mis`:

1. The phone (2958 title, 2300). With `FT_WARP_PHONE=1`, the developer scene warp first puts the
   player on the street 8 blocks from the phone (marked in the run). The 145-block trip from the
   district start is not part of the job.
2. The Factory Bus at 227.5,214.5 (`P.enter_parked`), then 2301.
3. Four groups of six (a leader with a machine gun and five followers), one after another. Each box is
   `LOCATE_CHARACTER_BY_CAR 8 x 4`. Rednecks at 16.5,71.5 (horn brief 2304, next 2305) and 9.5,43.5
   (a walled yard entered from the east, 2306/2307). Zaibatsu on the raised level-2 roads at
   197.5,25.5 (2308/2309) and 228.5,34.5 (2310/2311). After `IS_GROUP_IN_CAR` the script runs
   `KILL_ALL_PASSENGERS`, so the bus is empty again for the next group.
4. To 215.5,226.5 (`LOCATE_CHARACTER_BY_CAR 8 x 3`), brief 2312. The player gets out and walks clear.
   The script locks the bus and a scientist destroys it: 2315, 2999 JOB COMPLETE, $30,000.

Fails: 2314 (fewer than 2 of the waiting group alive), 2302 (the bus wrecked), 2998.
Residential respray shops (numbered `CAR_SHOP` entries in `ste.mis`, east-west drive-through tunnels
entered from the east) go to `deliver_intact` as `shops`.

Run (speed 2, no video, screenshots every 5 s):

```
GTA2_SPEED=2 FPS=0 GTA2_DIRECT_KEYS=1 SWAP_LEVEL=ste INI_SED='s/^scene_key=.*/scene_key=F11/' \
  gamerun/grun.sh ft1 1900 missions/keys_fake_truce.sh -e GTA2DX9_STATE_EVERY=5 -e DISTRICT=ste \
  -e WARP_OK=0 -e FT_WARP_PHONE=1 -e GTA2DX9_SCENE_NO_CAR=1
```

Summary in `out/<run>/ft_result.json` (stage, pickups, messages, horn and deliver events).

## GET ZITZAKI! with the module

`gamerun/missions/zitzaki_horn.py` (`missions/keys_zitzaki_horn.sh`) imports SKILL-DELIVER's
`missions/get_zitzaki.py` unchanged and replaces only its horn step, in that process, with
`horn_pickup.pickup`. The Stop is the hospital's 3 x 1 strip at 50.5,178.5 (`narrow`, so the module
enters it with `deliver_intact`'s open-side creep). The script answers the horn with no brief: it
creates Dr ZitZaki (remap 13) at 47.5,178.5, so `horned` tests for him in the peds line. `aboard` is
`get_zitzaki.doctor_aboard` (brief 1639 or the arrow on the garage). `move=False`, because leaving the
strip makes the script say 1648 and the doctor stops.

```
GTA2_SPEED=2 FPS=0 GTA2_DIRECT_KEYS=1 INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' \
  gamerun/grun.sh zh1 900 missions/keys_zitzaki_horn.sh
```

## Sessions

All at `GTA2_SPEED=2`, no video, screenshots every 5 s, the shared `repo/stage`. Host load was high
throughout (load average 20-125 on 8 CPUs; the queue's load hold was on for part of it), so game time
ran well below 2x.

| run | job | horn stops | result | notes |
|---|---|---|---|---|
| ft1 | FAKE TRUCE (smooth driver) | rednecks 1: in the box, horn taken on press 1 (2304), all six aboard in 1 s (2305). Rednecks 2 (the walled yard): press 1 (2306), aboard in 1 s (2307) | bus burned before group 3 | the Factory Bus (model 11) lost 32000 -> 16000 in about 380 blocks of traffic (gridlock queues, kerbs); it caught fire at 11.6,58.2 on the 370-block leg to the Zaibatsu, with 159 s of fire for 186 blocks. A respray costs $5,000 and the player has $1 (`playthrough-districts.md`, pt8_respray2). Frame `m_horn_rednecks2_horn.png`: chase view, the bus in the Redneck yard, the gang walking to its door |
| ft2 | FAKE TRUCE (calm driver from `russian_sailors.py`) | none reached | stopped | calm refused every reverse for 3 min with the long bus against a kerb at 138.7,205.5 and a car behind it |
| ft3 | FAKE TRUCE (hybrid: calm, a smooth burst after 20 game s without progress) | none reached | bus burned before group 1 | 20 smooth bursts. Damage was rams while standing in queues (calm 6800) and the bursts (5000) |
| **zh1** | GET ZITZAKI | doctor: the 3 x 1 strip by creep, horn taken on press 1, doctor aboard in 5 s (1639) | **JOB COMPLETE** (1124, +$20,000, 811 game s) | frames `m_horn_doctor_horn.png` (the 1638 "sound the horn" brief, the doctor walking out, chase view), `m_zz_end_third.png` (JOB COMPLETE) |
| zh2 | GET ZITZAKI | doctor: horn on press 1, aboard in 0 s (1639) | not complete: the run's 900 s ran out | the Miura caught fire on `deliver_intact`'s garage leg, 115 blocks out (that leg is SKILL-DELIVER's) |
| zh3 | GET ZITZAKI | not reached | stuck before the horn | he was pulled out of the Miura on the hospital leg; `deliver_intact.board` walked to the car's spawn point (74.5,163.5) for the rest of the run (SKILL-DELIVER's leg). The module gave up cleanly ("timeout: the box not reached") |
| **zh4** | GET ZITZAKI | doctor: in the strip at once, horn on press 1, aboard in 0 s | **JOB COMPLETE** (1124, +$20,000, 777 game s) | the Miura reached the garage alight (14078) |
| **zh5** | GET ZITZAKI | doctor: horn on press 2, aboard in 0 s | **JOB COMPLETE** (1124, +$20,000, 896 game s) | |

The same module on a third job, from SKILL-CRUSHER's COP CAR CRUSH runner (`missions/cop_car_crush.py`,
`docs/skill-crusher.md`). Shady at the Avalon station: `Stop("shady", 94.5, 95.5, 2, 2,
aboard_keys=1694, man=97.5,89.5)`. He stands 7 blocks from his 2 x 2 box, so `stand_point` finds no
point 2.2-4.2 from him and the module falls back to the box's edge (94.5,95.8). With no horn brief to
wait for, it presses three times. Shady was aboard in ccc3, ccc4 and ccc5 (3 presses, 0 s), and all
three reached JOB COMPLETE.

## Result

- **The horn stop itself: all 9 stops the car reached ended with everyone aboard.** FAKE TRUCE: 2 groups of six. GET
  ZITZAKI: 4 (zh1, zh2, zh4, zh5). COP CAR CRUSH: 3. The horn was taken within 1-3 presses and they
  were aboard within 5 s of it every time.
- **GET ZITZAKI with the module: JOB COMPLETE in zh1, zh4 and zh5 (3 of 5; 2 of the last 3).** The
  two failures were in the drive legs before and after the stop (SKILL-DELIVER's `get_zitzaki.py`
  legs: a fire on the garage leg, a re-board to the wrong place).
- **COP CAR CRUSH with the module (SKILL-CRUSHER): JOB COMPLETE 3 of 3 (ccc3-ccc5).**
- **FAKE TRUCE: not complete.** The Factory Bus does not survive about 800 blocks of the Residential
  traffic with the shared drivers. Fixing that needs a driver that keeps a long vehicle out of queues
  and off kerbs, or $5,000 for a respray.

Frames (not in git): `out/zh1/m_horn_doctor_horn.png` (the 1638 brief, the doctor walking out),
`out/zh1/m_zz_end_third.png` and `out/zh4/m_zz_end_third.png` (JOB COMPLETE), `out/zh4/m_horn_doctor_aboard.png`
(1639), `out/ft1/m_horn_rednecks2_horn.png` (the Rednecks walking to the bus).

Known limits: `stand_point` needs flat ground 2.2-4.2 blocks from the man inside the box, so for a man
outside a small box (COP CAR CRUSH) it falls back to the box edge. The horn is pressed blind (3 times)
when the job gives neither a brief nor a `horned()` test. The group-stall move is untested in game:
no group stalled.
