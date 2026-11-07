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

## Part 4 (7 Nov 2026, evening): wall-aware driving

Why the harder jobs died in part 3: `drive3` cut corners. Its waypoints were
the cell path with collinear cells merged (`straighten3`), so a leg could run
diagonally through a building corner or a railing; Up stayed held while the
car was 90 degrees off its waypoint; and a "stall" was answered by a steered
reverse into the next wall. A fragile mission car (the Cop Car, the Miura)
caught fire after eight such hits and the job failed.

What the runner does now (`gamerun/mission_lib.py`, mirrored in `linux/docker/`):

- **Lane-aware road routing**: the road-only Dijkstra adds a cost for entering a
  road cell against its traffic arrows (GMP arrows byte, face order left,
  right, up, down; checked on the Downtown carriageway), so the car keeps to its
  side and meets less oncoming traffic.
- **Line-of-sight waypoints** (`line_clear`, `straighten_los`): a cell stays a
  waypoint only when the straight run to the next kept cell, sampled every 0.2
  block with a car's half width either side, lies on drivable ground and
  crosses no wall face. The police-lot exit for the Cop Car now goes
  206,38 → 208,39 → 208,40 → the road instead of through the wall at 206,39.
- **Speed target with a corner lookahead**: the cap is 3.0 blocks/s in a mission
  car (5.5 otherwise), falls to `1.0 + 0.55 × distance` within four blocks of
  the next real turn, and to 1.2 near the goal; Down pulses bleed speed above
  the target.
- **No throttle past 40 degrees of heading error**: a real turn is driven with
  steer-plus-throttle pulses of 0.22 s after a brake; between 13 and 40 degrees
  the steer is held for a short pulse with throttle only below the target.
- **A throttle stall is traffic first**: when the car does not move for a second
  with Up held it waits two seconds for the queue, then backs off 0.7 s straight
  and pulls out on the side that has road, then re-routes. A mission car is
  never abandoned (the bail-out is for borrowed cars only).
- **The walker** uses the same line-of-sight legs (a body's half width, legs of
  at most six blocks), so a long pavement no longer drifts into a lamp post.
- **Phone terraces**: after a reported warp onto a terrace phone, the runner now
  warps back down to the street before the plan (part 3 lost the Cop Car's
  150 s walk budget on the Zaibatsu terrace rim); the mission car gets a reported
  warp to its door when the walk fails.
- **Countdowns**: the blast escape is routed (`escape_route`: the reachable ring
  cell 7-10 blocks away, walls and drops respected) and run with Up held through
  its legs; the box key is taken only once the mission arrow points at the box.
- **Straight legs stay on the route's own ground** and a car has its own cell
  costs (`CAR_COST`: roads cheap, a lot or a pavement only to get on or off
  them). pt4_wil7's Cop Car was wrecked against the wall at 182,71 after a leg
  cut across a pavement, and the lot exit used to be routed through fields.
- **A three-point turn** when the waypoint is behind the car or close and well
  off the nose (the police lot, a lot exit): reverse with the wheel the other
  way, then the forward branches take over. pt4_wil7 needed 16 stalls to leave
  the lot; pt4_wil15 one.
- **The walker walks in the classic view.** The 3D orbit camera remaps the keys
  (Up walks where the camera looks, Left/Right turn a wanted heading through a
  lagging controller), so the heading-pulse steering calibrated in the classic
  view barely turned him: pt4_wil11 spent 0.45 s Right pulses for 0.5 rad in
  three seconds and walked away from the kerb. `walk3` now switches to the
  classic view for the walk and back to the 3D view after it (the 3D views
  record the driving, the phones and the mission moments). Start-to-Cop-Car fell
  from 14 min (pt4_wil11) to 4 min 25 s of game time (pt4_wil15). A walker
  pinned in a wall corner for two re-routes gets a reported warp a few cells
  down its path.
- **A phone is answered only when the game raises a mission arrow.** The tutorial
  hints 1600-1615 and its gift arrow near the level start (hint 1608: a car and
  a gun at 156.5,142.5) were taken for jobs in pt4_wil9 and pt4_wil12; the arrows
  are re-baselined before each phone, and a phone that does not answer gets a
  second approach. Message 1107 at the Loonies phone ("Loonies don't make deals
  with those boring Zaibatsu people") is a respect refusal: it followed every
  fast drive through Loony turf that ran Loonies over (money +10 per kill shows
  it), so the drive to a phone is capped at 3 blocks/s.
- **The crusher** at 176.5,9.5 is a raised 3x3 platform (level-2 lids with
  diagonal corners in the GMP): the crane's drop point, which no car can climb.
  The car is parked under the crane's hook at 177.0,11.5 instead (a second spot
  176.5,13.5 is tried if nothing happens in 75 s); the crane took the Cop Car
  within ten seconds of the player stepping out (pt4_wil15, JOB COMPLETE).
- **Sessions**: 1800 s recordings (pt4_wil11's 1500 s recording ended 20 s before
  the crusher yard); fast unrecorded sessions (`GTA2_SPEED=2 CPUS=4 FPS=0`) for
  the search, one recorded 1x session for the clip, as the throughput notes say.

### Runs (part 4, 1500 s sessions, four queue slots, devtools keys enabled for the terrace phones)

| session | plan | phone | mission | outcome | what stopped it |
|---|---|---|---|---|---|
| pt4_wil1 | ze1, le2, ze2 | Zaibatsu terrace answered 17:38 (warp landed on the rim) | COP CAR CRUSH | stuck: could not enter the car | the walker burned its budget on the terrace rim (fixed: warp down after a phone warp) |
| pt4_wil1 | | Pizza phone answered 17:45 | PIZZA CAKE | JOB FAILED 17:54 | the countdown escape ran into a wall; dead in the blast |
| pt4_wil2 | ze1, le2, ze2 | answered 18:16 | COP CAR CRUSH | lives 5→4 at 18:21, job lost | the first car borrowed "beside him" sat in a traffic queue, wedged (fixed: wedge → leave the jam on foot) |
| pt4_wil3 | le2, ze2 | neither answered | – | phone not answered ×2 | the devtools warp did nothing: `INI_SED` with `scene_key` was not passed (fixed in the queue line) |
| pt4_wil4 | ze1, ze2 | ze1 warp landed on the phone, no answer; ze2 answered 18:31 | WHEELER-DEALING | ran out | the walker cannot reach the first dealer within the 180 s clock |
| pt4_wil5/6 | le2 / ze1 | warp landed on the phone | – | crashed | `NameError` (`LIVES0`) in the runner; fixed, sessions killed and requeued |
| pt4_wil7 | ze1, le2 | answered 18:56 | COP CAR CRUSH | in the Cop Car 19:01 (brief 1685), out of the lot 19:05, JOB FAILED 19:08 | 16 stalls leaving the lot (route started in a field cell), then a straight leg cut across a pavement into the wall at 182,71; the stalled car was wrecked (brief 1683) and the player died in it |
| pt4_wil8 | le2, ze1 | Pizza warp landed on the phone, no answer (edge trigger); Zaibatsu answered 19:17 | COP CAR CRUSH | ran out at the start of the plan | 12 min lost to a wedged borrowed car and a wandering walker on the Zaibatsu block |
| pt4_wil9 | ze1, le2 | Zaibatsu phone: hint 1608 taken for an answer, no job (fixed: an untitled message needs a mission arrow; the tutorial's hints 1600-1615 are ignored) | – | COP CAR not started; Pizza phone refused (1107) | the walker was never near the Cop Car; three Loonies were run over on the drive to their phone, so the Loonies refused |
| pt4_wil10 | le2, ze1 | Pizza phone answered (step off and back on) | PIZZA CAKE | ran out on the way to the explosives | the walker pinned in a wall corner at 81.9,25.2 for 12 min (fixed: a pinned walker gets a reported warp a few cells down its path) |
| pt4_wil11 | ze1, le2 | answered 20:04 | COP CAR CRUSH | car taken 20:09, out of the lot, station 20:15, horn, Shady aboard, crusher yard 20:20; ran out at the crusher | the crusher at 176.5,9.5 is a raised platform (the crane's drop point): the car was pressed against its wall and then parked 7 blocks away (fixed: park under the crane's hook, two spots in turn). The recording (1500 s) ends 20 s before the yard |
| pt4_wil12 | le2, ze1 | Pizza phone: the tutorial's gift arrow near the start was taken for the job's arrow | – | Pizza phone refused (1107) after one Loony run over; walker pinned twice | fixed: arrows within 8 blocks of the level start are the tutorial's; the arrows are re-baselined before each phone; the drive to a phone is capped at 3 blocks/s |
| pt4_wil13 | le2, ze1 | Pizza phone not answered (two approaches), a death on the way | – | on to COP CAR with 10 min left | first session with the classic-view walker: start to the Loonies phone in 8 min instead of 16 |
| pt4_wil14 | le2, ze1 (fast, 2x, unrecorded) | Pizza phone answered at game-second 290 | PIZZA CAKE | explosives at 360 s, delivery and the countdown survived (brief 1538) at 410 s, then 8 min ramming the van without wrecking it; gave up "running" | the van step is the remaining PIZZA CAKE blocker: `ram_target` does not wreck the criminal's van. Then COP CAR: phone answered (1116) but the walk to the car failed in the time left |
| **pt4_wil15** | ze1, le2 (recorded 1x, 1800 s) | Zaibatsu phone answered at game-second 230 | **COP CAR CRUSH: JOB COMPLETE** at game-second 589 (21:25:58), +$20000, multiplier 2 | car taken 265 s, one stall leaving the lot, station and horn 444 s, Shady aboard, crusher yard 563 s, parked under the hook at 177.0,11.5, crushed within 10 s of stepping out | then PIZZA CAKE: the Loonies phone refused (1104) at game-second 913, after the Cop Car job raised Zaibatsu respect (and a death on the way, lives 5→4): a Loonies job needs a fresh start, not a Zaibatsu job before it |
| pt4_wil16 | ze1, le2 (fast, 2x, unrecorded) | answered | COP CAR CRUSH | horn at 674 s, JOB FAILED 44 s later on the way to the crusher: the car stalled three times at 82.3,85.5 and was wrecked (player dead, lives 5→4) | the remaining Cop Car failure mode: a stalled fragile car in traffic (1 of 2 runs with the final code) |
| pt4_wil16 (le2) | after the failed Cop Car | Pizza phone answered | PIZZA CAKE | explosives, delivery and the countdown survived (health 68), then JOB FAILED 95 s into the ramming: the player died (lives 4→3) | the van step again: the criminal (or the van's blast) kills him while he rams |

**Verified in part 4**: COP CAR CRUSH, JOB COMPLETE once (pt4_wil15, recorded; the
clip is `deliverables/gta2_linux_playthrough_downtown_part3.mp4`, level start to
the crusher), failed once on the way to the crusher with the same code (pt4_wil16,
stalled car wrecked). PIZZA CAKE reaches the van in both fast sessions (explosives,
delivery and the countdown escape all pass) and stops at the ramming. **Untested**:
WHEELER-DEALING with the classic-view walker (only tried in pt4_wil4 with the old
walker, which could not reach the first dealer in 180 s), and every chain after
these three jobs. Nothing was committed.
