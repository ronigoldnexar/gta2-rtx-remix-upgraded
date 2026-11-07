# Playing Downtown in the street-level views (7 Nov 2026)

The mission runner (`gamerun/mission_play_wil.py` on `gamerun/mission_lib.py`,
mirrored in `linux/docker/`) plays GTA2's Downtown missions from the decompiled
plans (`assets-src/missions/missions.json`) and the renderer's log, in third
person on foot with first-person stretches at the start of every walk and at
the wheel of every drive. Every run is on the L4 GPU image (`run_game_gpu.sh`,
30 fps capture), 20 minutes per run (`SECS=1200`), one fresh game per run.

What changed in the runner for this pass (v2 in `mission_lib.py`):

- **Router**: Dijkstra over (x, y, level) instead of BFS at one level. Slopes
  (stairs, ramps, the phone daises) join one lid level to the next along their
  own axis only (GTA2's `up/down/left/right` slope types name the uphill
  direction on screen; checked on the Yakuza phone dais, where types 3-4 rise
  toward the south). Pavement costs 1, grass 1.4, road 3, so the walker keeps
  off the carriageway where it can.
- **Walker** (`cruise_to`, `walk3`): Up held, heading corrected from the
  half-second samples, instead of stop-turn-step. A 150-cell leg now takes
  about 80 s (it took 5 min before).
- **Driver** (`drive3`): Up held with proportional steering, speed cap, brake
  before corners, back out of stalls, re-route; `slow` mode for missions.
- **Precision**: `nudge_to`/`settle` step onto a point with 8 cm pulses and
  watch the game's message buffer, because `LOCATE_*` boxes are 0.4-0.5 block.
- **Which job started**: two phones stand side by side at every gang site; the
  title message the game shows (`msg` = 1954 RADIO ZA-ZA!, 1955 PIZZA CAKE!
  ...) selects the plan, and the gang's refusals (1097/1103/...) are recognised.

## Runs

| run | missions | result | evidence |
|---|---|---|---|
| `out/pt_wil1` | tutorial, GET ZITZAKI | tutorial: all four gang-zone phones reached (briefs 1619, 1622, 1624 in order), the last 0.5-block box at the spawn missed by 0.3 block; GET ZITZAKI: walker could not climb the phone dais (slopes were routed sideways) | `out/pt_wil1_sheet.png` (phone, Messer, three zone phones), run killed before the video closed |
| `out/pt_wil2` | tutorial, GET ZITZAKI | tutorial again to the last box (not triggered: the box is on the stair foot at the spawn); the Yakuza phone **was climbed** via the dais slope with the directional router, but the Yakuza refused the job ("do not do business with Zaibatsu whores", 1097) because the tutorial thread was still running | `out/pt_wil2/game.mp4` (20 min), `m_*.png` |
| `out/pt_wil3` | GET ZITZAKI, RADIO ZA-ZA (fresh game, no tutorial) | **GET ZITZAKI started** (title + brief 1631), the marked Miura entered (model 37, brief 1636), driven to the hospital box (brief 1638 "sound the horn"), but the driver backed out of the box while un-stalling and horned 3 blocks away ("Get back there and sound the horn!", 1648); the doctor never boarded; at the Funabashi garage the damaged car caught fire: **JOB FAILED** ("I should have guessed you would wreck the car"), the player died in it. Then the Loony phone pair: the walker's nudges answered the neighbouring phone, **PIZZA CAKE! started**; the runner followed the RADIO ZA-ZA plan instead and the second phone said "are you not already on a Loony job" (1103) | `out/pt_wil3_sheet.png`, `out/pt_wil3/game.mp4` (20 min, 0 faults) |

## Part 2 (7 Nov 2026, the arrow-confirmed runner)

### Why the tutorial never finished in part 1, and the fix

The game's pager was the runner's only progress signal, and it lies: `DISPLAY_BRIEF`
texts queue behind each other and the gang-zone information phones put their own
briefs (1619, 1622, 1624) up the moment the player stands on them. So `settle`
took the information phone's brief as "the box was passed" and walked on, while
the tutorial script was still waiting at the 0.5-block `LOCATE_CHARACTER_ON_FOOT`
box. Every later box, the spawn one included, was then meaningless.

The fix reads the game's own objective arrows. The arrow manager lives at
`[0x672F40]+0x1F18`: seventeen slots of 0x7C bytes, type at +0x20, target kind at
+0x40 (1 = a map position, 3/4 = an object, 0 = removed) and the target position
at +0x44/+0x48/+0x4C as 18.14 fixed point (16384 per block). The renderer now logs
`view: arrows slot:type:kind:x,y,z:obj...` twice a second (`world_view.cpp`, under
the `view: mission` line). The base script keeps twelve slots (the gang phone
markers and the three information phones); a mission's own arrow is any slot that
differs from that baseline (`mission_lib.arrows_baseline` / `mission_arrows` /
`objective`). `settle_box` stands inside the exact `LOCATE` box and returns only
when the arrow moves on. Run `out/pt2_wil1` shows the whole tutorial as an arrow
trace: car (kind 3) → 188.5,37.5 → 38.5,38.5 → 31.0,157.0 → 159.5,139.5 → removed,
then GET ZITZAKI: the Miura (kind 3) → the hospital box → the garage box → removed.

Other runner changes (`gamerun/mission_lib.py` v3, `mission_play_wil.py`, mirrored
in `linux/docker/`): stay at the wheel of a mission car until the arrow leaves it;
wait for the mission arrow instead of a fixed 45 s after the phone; drive to phones
and objectives more than 40 blocks away (`any_car2`: the nearest parked car, else
the nearest kerb and the first car that stops); park on the crane's pickup point for
`IS_CAR_CRUSHED` (`wil.mis`: crusher2 = 176.5,9.5); ram the arrow's car for
`IS_CAR_WRECKED` (`ram_target`, the arrow follows the car); step off a phone pair
before starting (standing on the neighbour re-answers it and the game holds him);
a reported developer warp when a phone sits on a terrace the walker cannot climb.

### Runs

| run | missions | result | evidence |
|---|---|---|---|
| `out/pt2_wil1` (40 min, fresh game) | TUTORIAL, GET ZITZAKI, COP CAR CRUSH, WHEELER-DEALING | **TUTORIAL complete** (806 s: car, three zone boxes confirmed by the arrow in 30 s / 16 s / 7 s, the spawn box in 13 s, +$20,000, "Your status is saved"); **GET ZITZAKI complete** (568 s: Miura, hospital box, horn, doctor boards, garage, +$20,000, multiplier 2, $40,042); the two Zaibatsu phones (208.5,57.5 / 59.5) are 200 blocks from the J-Lab and the walker's 360 s budget ran out twice | `out/playthrough_wil2_sheet.png`, `deliverables/gta2_linux_playthrough_downtown_part2.mp4` (1400 s, level start to the second JOB COMPLETE), `out/pt2_wil1/m_*.png`, 0 faults |
| `out/pt2_wil2` (40 min, fresh game) | COP CAR CRUSH, WHEELER-DEALING, PIZZA CAKE | the Zaibatsu phones were reached by car this time but not answered: they stand on the Zaibatsu HQ's level-4 terrace (map 208-211 x 56-60) and the walker got within 1.6 blocks at street level; **PIZZA CAKE started** (phone answered after a drive, brief 1531) but the walk to the explosives (28.5,106.5 z 3) was held for three minutes at the phone pair (each nudge re-answered the neighbouring phone, message 1103) and the runner then walked to the second box without the first | `out/pt2_wil2/m_*.png`, 0 faults |
