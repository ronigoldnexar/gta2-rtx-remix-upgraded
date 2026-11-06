# Playing GTA2's missions by script

How the game's missions work, read off the game's own data, and the runner
that plays them in the street-level views (`gamerun/mission_lib.py`,
`gamerun/mission_play.py`, mirrored in `linux/docker/`).

## How missions work (verified from the scripts)

- Each district has a base script (`data/wil.SCR`, `bil.scr`, `ste.SCR`;
  82 656 bytes each = 6 000 pointers + 64 KB of code + 5 KB of strings) and
  22-23 mission sub-scripts in `data/<district>/*.SCR`. They decompile
  cleanly with T.M.'s decompiler (Valps fork, built with g++ from
  github.com/Valps/gta2-tm-scr-decompiler; the sources are kept in
  `assets-src/missions/<district>.mis` and `<district>_m/*.mis`).
- The base script declares the player start (`PLAYER_PED`), the phones
  (`OBJ_DATA ... GREEN_PHONE | YELLOW_PHONE | RED_PHONE | PHONE`), the doors,
  gangs, zones, and a `THREAD_WAIT_FOR_ANSWER_PHONE (p1, phone, function)`
  trigger per phone. The function runs `DO_EASY_PHONE_TEMPLATE (brief,
  mission.mis, ...)` or `DO_PHONE_TEMPLATE (brief, mission.mis, followup.mis,
  ..., gang, respect)`: green phones need respect 0 with that gang, yellow 2,
  red 4 (respect is changed by `CHANGE_GANG_CHAR_RESPECT_AND_UPDATE` at the
  end of every job: +1 for a pass, -1 for a fail). A phone is answered by
  standing on it; a done phone is `SET_PHONE_DEAD`.
- Plain `PHONE`s are information phones (`DISPLAY_BRIEF` only), except the
  one at the Downtown spawn (158.5, 138.5), which launches the tutorial
  `wil_tra` (it gives a Messer, a pistol, and sends the player to each gang's
  zone phone and back).
- A mission script is one function: create the mission car/characters,
  `DISPLAY_BRIEF` (pager text, GXT key) and `DISPLAY_MESSAGE` (the big title,
  e.g. 1975 "GET ZITZAKI!"), `POINT_ARROW_AT` a car, character or point, then
  a `WHILE_EXEC` loop that waits for a condition (`IS_CHARACTER_IN_CAR`,
  `LOCATE_CHARACTER_ON_FOOT/BY_CAR/ANY_MEANS (x, y, z, w, h)`,
  `IS_CAR_IN_BLOCK`, `IS_CHAR_PRESSING_HORN`, `IS_CHAR_OBJECTIVE_PASSED`,
  `HAS_PARK_FINISHED`, `IS_CAR_CRUSHED` ...) while its body handles failure
  (car wrecked/sunk, character died, player died or arrested: `DISPLAY_BRIEF_NOW`
  + `DISPLAY_MESSAGE (1125)` "JOB FAILED!" and `RETURN`). Success ends with
  `DISPLAY_MESSAGE (1124)` "JOB COMPLETE!", `ADD_SCORE`, `ADD_MULTIPLIER`,
  `CLEAR_WANTED_LEVEL`, respect +1, the phone set dead, and
  `++savecount<missions passed>`.
- District completion: `DECLARE_FINISH_SCORE (1000000)` (Downtown; the known
  rule that a district ends once the score reaches the target), and the
  final job (`wil_end`, `bil_end`, `ste_end`) launches from the end phone
  when the missions-passed counter reaches 21 (15 phone jobs plus the six
  follow-ups of the yellow and red phones). Saving is at the church
  (`DISPLAY_BRIEF 1607`), for $50,000, after a finished job.
- Text: `data/e.gxt` is a GBL file (`TKEY` = 12-byte entries of offset + 8-char
  key, `TDAT` = UTF-16 strings); parsed to `assets-src/e_gxt.json` (2 595
  strings; mission briefs are keys 1600-1999 and 2xxx per district).

### Mission tables

Built by `tools/missions_db.py` into `assets-src/missions/missions.json`
(per district: start, phones, triggers, and a step plan per mission). Downtown
(`wil`), player start (159.5, 139.5, level 2):

| phone | at | gang | mission | title | respect | reward |
|---|---|---|---|---|---|---|
| green | 44.5,150.5 | Yakuza | wil_ye1 | GET ZITZAKI! | 0 | 20 000 |
| green | 46.5,150.5 | Yakuza | wil_ye2 | BANK ROBBERY! | 0 | 30 000 |
| yellow | 83.5,185.5 | Yakuza | wil_ym1 (+ym3) | HAPPY GAS SMASH! | 2 | |
| yellow | 86.5,185.5 | Yakuza | wil_ym2 (+ym3) | GET GAMA REI! | 2 | 40 000 |
| red | 97.5,245.5 | Yakuza | wil_yh1 (+yh2) | SWAT VAN SWIPE! | 4 | 60 000 |
| green | 208.5,57.5 | Zaibatsu | wil_ze1 | COP CAR CRUSH! | 0 | 20 000 |
| green | 208.5,59.5 | Zaibatsu | wil_ze2 | WHEELER-DEALING! | 0 | 20 000 |
| yellow | 207.5,8.5 | Zaibatsu | wil_zm1 (+zm3) | LICK THOSE LOONIES! | 2 | 40 000 |
| yellow | 209.5,8.5 | Zaibatsu | wil_zm2 (+zm3) | YUTES MUST DIE! | 2 | 40 000 |
| red | 181.5,94.5 | Zaibatsu | wil_zh1 (+zh2) | ARMORED CAR CLASH! | 4 | 60 000 |
| green | 75.5,40.5 | Loonies | wil_le1 | RADIO ZA-ZA! | 0 | 20 000 |
| green | 75.5,41.5 | Loonies | wil_le2 | PIZZA CAKE! | 0 | 20 000 |
| yellow | 10.5,46.5 | Loonies | wil_lm1 (+lm3) | WHO'S MAD? | 2 | 40 000 |
| yellow | 11.5,46.5 | Loonies | wil_lm2 (+lm3) | DESTROY J-LAB! | 2 | 40 000 |
| red | 58.5,20.5 | Loonies | wil_lh1 (+lh2) | TAXI DRIVERS MUST DIE! | 4 | |
| plain | 158.5,138.5 | tutorial | wil_tra | TUTORIAL! | | 20 000 |
| plain | 188.5,37.5 / 38.5,38.5 / 31,157 | info phones | | | | |

Residential (`bil`, start 44.5, 102.0): Krishna (green 249.5,199.5 /
249.5,201.5; yellow 233.5,132.5 / 235.5,132.5; red 216.5,219.5), Zaibatsu
(green 44.5,163.5 / 45.5,161.5; yellow 6.5,183.5 / 9.5,183.5; red 27,249),
Russians (green 187.5,76.5 / 189.5,76.5; yellow 204.5,10.5 / 204.5,13.5; red
144.5,33.5), final phone 234.5,193.5 (`bil_end`, 5 000 000).
Industrial (`ste`, start 113.5, 124.7): Scientists (green 234.5,202.5 /
235.5,202.5; yellow 206.5,227.5 / 206.5,228.5; red 222.5,221.5), Zaibatsu
(green 166.5,19.5 / 166.5,16.5; yellow 224.5,34.5 / 225.5,34.5; red 208.5,25.5),
Rednecks (green 18.5,68.5 / 18.5,67.5; yellow 84.5,30.5 / 84.5,29.5; red
4.5,5.5), final phone 211.5,219.5 (`ste_end`). The full tables with titles and
rewards are in `missions.json` (`tools/missions_db.py ... out.json out.md`
writes them as Markdown too).

## Runtime state (the `view: mission` log line)

`dll/src/world_view.cpp` logs twice a second, between the `view: player`
lines:

    view: mission money=M mult=K lives=L death=D wanted=W health=H cardmg=C carmodel=N msg=KEY frame=F

- `money`: the game's own score getter (`game_save.cpp`, 0x421980 on the
  score keeper `[[0x5EB4FC]+0x38]`); `mult`, `lives`, `death`: score keeper
  +0x6BC, +0x684, +0x44; `wanted`: police manager `[0x66B7A0]+0x654`;
  `health`: ped +0x216 (word); `cardmg`/`carmodel`: the driven car's +0x74
  byte and +0x84; `msg`: the key the game last passed to its message display
  (both `DISPLAY_MESSAGE` and `DISPLAY_BRIEF` fill the buffer at 0x5E9808, so
  it also tells which pager brief is current: 1124 = JOB COMPLETE!, 1125 = JOB
  FAILED!, the mission titles 19xx, briefs 16xx); `frame`: 0x5E8108 (reads a
  constant in 9.6, not a counter: ignore it).
  Offsets from the GTAMP memory-address thread (gtamp.com/forum t=700) and
  the mod's own save module; `money` and `msg` are verified in runs, the
  others are read as published and reported as read.
- The arrow target is not read from memory: the plan already knows where the
  script points the arrow (`POINT_ARROW_AT` coordinates), so the runner
  navigates by the plan. The on-screen arrow stays as the player's cue.

## The runner

`gamerun/mission_lib.py`: `World` (map + plans), `walk_to` (BFS route over
road/pavement/field cells from `gmp.py`, straightened into legs, re-routing
when a leg is not reached), `enter_car_at` (walk to the mission car's cell,
Enter, try the other sides), `drive_to` (road-only route, a heading
controller that holds Up with proportional Left/Right taps, brakes before
sharp corners, reverses when facing away, backs out when stuck), `horn`
(Tab and Space, the special key and jump/handbrake), `answer_phone` (stand
on the phone until the title message appears), `outcome` (1124/1125, money
jump, health 0 / death reason).
`gamerun/mission_play.py <district> <mission...>` plays missions in order:
third person throughout, first person for ~15 s at the start of each drive;
marks in `/out/marks.txt`.

Limits: the driving controller steers from the half-second log samples, so
it drives slowly and brakes early; characters' own objectives (a passenger
getting in, the parking at the door) are waited for by time, not by state;
`IS_CAR_CRUSHED`, mission cars that must be stolen from gang members, kill
objectives and timed jobs are not handled yet; death/arrest restarts from
the phone are detected but the restart is manual in this version.

## Results so far (6 Nov 2026, L4 host)

- Run `out/mission1_stuck`: phone answered (the brief key appeared in the
  message buffer within a second of standing on the phone), the 45 s brief
  wait, the Messer entered by walking to its cell and Enter (model 36 read
  back from the car), then the first car drive wedged the car against the
  plaza corner: the road-only route failed from the courtyard and the fallback
  walking route went over the lawn.
- Run `out/mission2_walker`: on foot instead; the walker left the plaza and
  crossed the carriageway but looped at the junction (143..147, 147..151): a
  standing pedestrian's logged facing is a half turn off, so each stop turned
  the wrong way (the same finding the demo stream made). Fixed in
  `drive_lib.goto` (a short step before every turn) and `enter_car_at` (a
  step before Enter; a ped standing still ignores it).

