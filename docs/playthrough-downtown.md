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

## Part 5 (8 Nov 2026): the van falls to a machine gun; WHEELER-DEALING is a driving-pace problem

Sessions `pt5_*` (the previous agent, 7 Nov late evening) and `pt6_*` (this pass), all on the
fast path (`gamerun/grun.sh`, `FPS=0`, devtools F9/F11 for the reported warps), PIZZA CAKE at
`GTA2_SPEED=2`, WHEELER-DEALING at `GTA2_SPEED=1` (its 180 s clock is game time and the
controller reacts in wall time).

### What the logs showed

- **`cardmg` is not the car's damage.** `vehicle+0x74` counts up by 15 every sample and wraps at
  256 (pt5_le2g: 87, 102, 117, 29, 253, 146 ... on one car within two seconds). Nothing in the
  `view: mission` line says how close a car is to burning, and the renderer's flame detector
  (`fire=` on the player line) stayed 0 on cars that were visibly on fire (pt5_ze2d shot_300,
  pt6_bil2 shot_985). The runners cannot see a burning car coming.
- **Ramming kills the player.** PIZZA CAKE completed once by ramming (pt5_le2e: the second
  car that burned beside the van at 2.3 blocks took the van with it), but the same tactic
  killed the player at the wheel in pt5_le2g, pt6_le2b (a head-on contact, then JOB FAILED,
  lives 5 -> 4) and burned car after car on the way. The van drives a fixed circuit of about
  400 blocks (59.5 x 55.6 .. 168.5 x 149.5) at 3-4 blocks/s and outruns a chase.
- **GTA2 has no drive-by**, but the player already carries a machine gun by the van step in
  most runs: every Downtown gang phone has a machine-gun generator beside it (`wil.mis`
  `GENERATOR ... COLLECT_01 1800 1800 30`; the Loonies' at 76.5,39.5 is two blocks from the
  PIZZA CAKE phone). The renderer's `view: mission` line gives `weapon=machine_gun(4) ammo=300`.
- **Walking in the chase view was still happening.** `walk3` handed the 3D view back after
  every walk, so the steps that followed it (`enter_car3`'s door approaches, `settle_box`'s
  nudges, `step_off_phone`) steered with classic-view pulses in the chase view: pt6_ze2a lost
  69 s of WHEELER-DEALING's 180 at its first car, wandering ten blocks off.

### Runner changes (`gamerun/mission_lib.py`, `mission_play_wil.py`, mirrored in `linux/docker/`)

- `mission_state()` parses `weapon`, `wid`, `ammo`; `gun_ready()`; `fetch_gun()` walks (or
  drives) to the nearest machine-gun pickups in turn when the van step starts unarmed.
- **`shoot_target()`** replaces ramming for `IS_CAR_WRECKED` (ramming stays as the fallback
  when there is no ammunition): the arrow track gives the van's circuit; the runner waits on the
  pavement beside the circuit point nearest to it, walks at the van with the trigger held when
  it comes within 12 blocks (the aim is the walking heading: a moving ped's logged facing is
  true, a standing one's can be half a turn off), holds the line of fire across its lane within
  four blocks, steps aside when it comes straight on, fires after it while it is within eight,
  and walks up to it whenever it stands (traffic lights, jams). After two seconds of fire on a
  standing van the burst finishes in the third-person view, so the wreck is recorded in 3D.
- **`ensure_view()`**: every on-foot move (`walk3`, `cruise_to`, the nudges) takes the classic
  view, every `drive3` takes the chase view itself; a walk-then-drive costs one V press.
- Timed jobs (WHEELER-DEALING): the car is left on the road cell with the shortest *walk* to the
  briefcase (`street_cell_walk_nearest`: 7 cells from the south road instead of 32 round the
  block wall from the north road), cap 6.5, lane penalty 0.8 instead of 2.5, corner speed
  1.8 + 0.8 x distance, short V waits (0.7 s), dealers approached four road cells short.
- PIZZA CAKE's two boxes are walked (the car hop between them killed the player in pt6_le2c).
- `run_game_gpu.sh` ends a run when the keys script touches `/out/.keys_done` (both mission
  keys scripts do), so a finished session frees its slot instead of holding it to `SECS`.

### Runs

| session | job | outcome | what happened |
|---|---|---|---|
| pt5_le2a-d, pt5_le2g (previous agent) | PIZZA CAKE | failed / timed out | the van outran the chase (50-130 blocks behind for minutes); with the ambush and run-up the player died at the wheel at a head-on contact (pt5_le2g, lives 5 -> 4, JOB FAILED) |
| pt5_le2e (previous agent) | PIZZA CAKE | **JOB COMPLETE** (1124) | by ramming: the first car burned after nine pushes, the second burned beside the van at 2.3 blocks and its blast wrecked the van |
| pt5_ze2a-d (previous agent) | WHEELER-DEALING | failed | dealer 1 served with 120 s left at best (pt5_ze2d); on the way to dealer 2 the borrowed car burned (shot_300: flames, `fire=0` in the log) and exploded with him inside (lives 5 -> 4, respawn 100 blocks away) |
| **pt6_le2a** | PIZZA CAKE | **JOB COMPLETE** (1124, +$20,000, multiplier 2, 666 s from the phone) | phone, explosives, delivery, countdown escape (health 68); no gun after the walk, so `fetch_gun` drove to the pickup at 11.5,47.5 (machine gun, 600 rounds); the van stood at 58.6,83.4: out of the car eight blocks off, walked at it firing, 110 rounds, wrecked. JOB COMPLETE frame `out/pt6_le2a/m_wil_le2_wrecked.png` (classic, on foot), the chase view two seconds later `m_wil_le2_wrecked_third.png` |
| pt6_le2b | PIZZA CAKE, RADIO ZA-ZA | failed; refused (1104) | the gun pickup at 11.5,47.5 gave nothing that time, the ramming fallback ran, the player died at a contact (lives 5 -> 4); the Loonies then refused RADIO ZA-ZA (1104) after the failed job |
| pt6_le2c | PIZZA CAKE | failed | the borrowed car's hop between the two boxes stalled twice and he died in it (the hop is now walked) |
| pt6_le2d | PIZZA CAKE | refused (1103) | the walker missed the phone, the reported warp put him on the phone pair and the neighbour (RADIO ZA-ZA) answered first; a carjack in front of a cop led to an arrest on the way (fixed: pull away at once when wanted) |
| pt6_le2e | PIZZA CAKE | failed | explosives, delivery and countdown passed (machine gun, 300 rounds, in hand); on the drive to the waiting spot the borrowed car caught fire and burned for 20 s while the runner drove on (`fire=0`), exploded with him inside |
| pt6_ze2a | WHEELER-DEALING | failed (clock) | the first car entry after the briefcase took 69 s: `enter_car3`'s approaches ran in the chase view (fixed: `ensure_view`) |
| pt6_ze2b | WHEELER-DEALING | failed (clock) | car left on the road north of the briefcase: 32 cells of walking each way round the block wall; dealer 1 at 116 s |
| pt6_ze2c | WHEELER-DEALING | failed (clock) | briefcase from the south road (7 cells); dealer 1 served at 77 s (12 s walk to the car, 61 s for the 85-block drive at 1.3-1.6 blocks/s, a three-point turn at the ramp foot 238-243 x 47-59 took 37 s); 103 s left for 380 road cells to dealers 2-4: stopped |
| pt6_le2f | PIZZA CAKE | failed | out of the car at the waiting spot as the van came; it stopped 2.5 blocks off and the runner finished the burst in the chase view: 290 rounds without a wreck (the 3D view turns him; the burst is classic-only again), then the ramming fallback; stopped by hand |
| pt6_le2h | PIZZA CAKE | failed | explosives, delivery and countdown passed unarmed; `fetch_gun` tried three machine-gun generators (11.5,47.5, 41.5,48.5, 90.5,87.5) and found nothing at any, so the ramming fallback ran and the player died at the wheel (lives 5 -> 4) |
| pt6_le2g | PIZZA CAKE | failed | the walker was pinned at 49.1,100.2 on the way to the explosives (the new scene warp refused: "no road or pavement within six blocks") and he died there (lives 5 -> 4) |

### Status after part 5

- **PIZZA CAKE: JOB COMPLETE**, recorded in pt6_le2a (`out/pt6_le2a/m_wil_le2_wrecked.png`, the
  JOB COMPLETE banner over the burning van, classic view while shooting on foot;
  `m_wil_le2_wrecked_third.png`, the chase view two seconds later with the payoff brief) and
  earlier in pt5_le2e by ramming. The gun is the tactic that works: one success in the two
  sessions that reached the van armed with the final aim (le2a), against deaths in every
  ramming session. The generators are not reliable either: pt6_le2a found the machine gun at
  11.5,47.5, pt6_le2h found nothing there or at two more (the one beside the Loonies phone,
  76.5,39.5, armed le2e and le2f on their way in). What still loses the job is not the van: a borrowed car that burns unseen
  (le2e), a pinned walker (le2g), a carjack that ends in an arrest (le2d).
- **WHEELER-DEALING: not completed.** With the briefcase approached from the right road and the
  walks in the classic view, dealer 1 is served 77 s into the 180 s clock (pt6_ze2c). The
  remaining legs are 71 + 112 + 199 road cells (route3, car costs); the driver averages
  1.3-1.6 blocks/s on Downtown's grid (every corner is crawled, a U-turn at a ramp foot costs
  half a minute), so the job needs about twice the driving pace, or a route plan with fewer
  corners, before it can pass.
- **The chain after PIZZA CAKE** (RADIO ZA-ZA, the other Loonies phone at 75.5,40.5) was queued
  behind PIZZA CAKE in every session; it is only offered after a completed Loonies job (1104
  after a failure, pt6_le2b), and no session with the final code completed PIZZA CAKE first.
- **Open, with evidence**: no burning-car signal (`cardmg` is a counter, `fire=` misses most
  car fires); the carjack at a kerb sometimes ends in an arrest or the owner pulling him out; the
  developer scene warp now refuses spots away from a road, so a pinned walker stays pinned.

## Part 6 (8 Nov 2026, PLAYTHROUGH-7): scripted play in the 3D views, the car's health from the game

Sessions `pt7_*`, all on the fast path (`gamerun/grun.sh`, `FPS=0`, devtools F9/F11 for the
reported warps, a private stage `stage_pt7` with this pass's renderer), `GTA2_SPEED=2` except
WHEELER-DEALING (`GTA2_SPEED=1`, its clock is game time and the driver reacts in wall time).

### Two engineering fixes

1. **The car's condition is read from the game** (`docs/actions-3d.md`, "Vehicle fields"):
   the damage is the int16 at `vehicle+0x74` (0..32000), the stage byte `+0x8C` says when it
   burns. The `view: mission` line now carries `cardmg=` (the word), `carhp=` (32000 - damage),
   `carfire=` (0, 1 burning, 2 burning hard) and `tcarhp= tcarfire= tcar=x,y` for the mission's
   target car (the kind-3 arrow's vehicle). A car catches fire at carhp 16000 and then loses a
   point a frame by itself, so it has carhp/30 game seconds before it explodes. Verified against
   frames in `out/pt7_carfields_sheet.png` (run `pt7_carprobe6`).
2. **Scripted play in the 3D views**: `GTA2_DIRECT_KEYS=1` on `grun.sh` sets `nav_map=0` in the
   run's ini (the arrows stay the game's own in the chase and first-person views: Up walks where
   the ped faces, Left/Right turn him, exactly as in the classic view; also the fire key, which
   the camera-relative hook drops, see actions-3d.md "Shooting pass notes") and passes the same
   variable to the runners, where `mission_lib.foot_view()` makes every on-foot move (`walk3`,
   `cruise_to`, the nudges, the gun) run in the third-person view instead of the classic one.
   The player's default (`nav_map=1`) is untouched; without the variable the runners behave as
   before. Every frame of a `GTA2_DIRECT_KEYS=1` session is a 3D one, the JOB COMPLETE frames
   included.

### Runner changes (`gamerun/`, mirrored in `linux/docker/`)

- `drive3` reads `carhp`/`carfire` every step: a hard hit is logged, a mission car
  (`precious=True`) drops to 2.0 blocks/s below carhp 22000, a burning borrowed car is left at
  once, a burning mission car is driven on only while carhp/30 s outlasts the way left (plus
  20 s), otherwise the player bails out clear of it. A car found burning on entry is left and
  never taken again (`BAD_CARS`; pt7_ze2b re-entered its own burning car six times).
- Pinned cars: three stalls within 1.2 blocks put the cells ahead on the car router's avoid list
  (`CAR_AVOID`), five give the drive up (pt7_ze2a hit one wall at 212.7,65.2 twelve times).
- `GTA2DX9_STATE_EVERY=N` (renderer environment) logs the position line every N frames; the
  sessions here use 5 (3 for WHEELER-DEALING), so the controller sees a fast car between corners.
- The phone: "already on a Loony/Zaibatsu/Yakuza job" (1103/1113/1093) is not a refusal: a job
  is running, the one this phone just started (pt7_le2a: PIZZA CAKE's brief 1531, then 1103 as
  the walker stepped on again) or the neighbour's (pt7_le2d: RADIO ZA-ZA's 1954 when the walk
  cut the corner of its cell); the runner names it from the title or the arrow. The game's
  texts were read from `data/e.gxt` (1103: "are you not already on a Loo-Loo-Loony job?").
- The Loonies' phones are walked to (a drive through their turf brings a refusal), and PIZZA
  CAKE fetches the machine gun beside the phone (76.5,39.5) before answering: pt7_le2b went for
  a pickup 60 blocks away after the countdown and was run over by a police car at the kerb.
- Timed jobs (WHEELER-DEALING): no speed cap on straights (`RACE_CAP` 11), braking only into a
  turn (2.6 + 1.2 x distance, from 8 blocks out), turns taken rolling (`M.RACE`), one-second
  car exits, and a car with carhp under 26000 is swapped before the clock starts.

### Runs

| session | job | outcome | what happened |
|---|---|---|---|
| pt7_le2a | PIZZA CAKE (3D walker, first try) | phone mis-read | drove to the phone; the job started (brief 1531) and the walker's step back on gave 1103, taken for a refusal (fixed: 1103 means a job runs) |
| pt7_le2b | PIZZA CAKE, RADIO ZA-ZA | failed; refused 1104 | the whole 187-cell walk to the phone in the chase view in 74 s of wall time; explosives, delivery, countdown escape; then run over by a police car at a kerb waiting for a car to the gun (fixed: gun first) |
| pt7_le2d | PIZZA CAKE | wrong job | the gun beside the phone, then the walk to the phone cut the corner of RADIO ZA-ZA's cell (1954), PIZZA's phone said 1103 (fixed as above) |
| **pt7_le2e** | **PIZZA CAKE, RADIO ZA-ZA** | **both JOB COMPLETE** | gun at 76.5,39.5 (300 rounds), phone, explosives, delivery, countdown; the van stood on its circuit at 138.9,149.5: shot on foot in the third-person view, 96 rounds, **JOB COMPLETE 1124** (+$20,000, multiplier 2) at game-second 503, frame `out/pt7_le2e/m_wil_le2_wrecked.png` (chase view). Then **RADIO ZA-ZA**: phone 1954, by car to Futuro FM (154.5,17.5), explosives by the generator (163.5,13.5), the DJ's door (159.5,5.5), the five-second escape, **JOB COMPLETE** (+$40,000, multiplier 3) at game-second 836, frame `out/pt7_le2e/m_wil_le1_end.png` (chase view) |
| pt7_ze2a | WHEELER-DEALING | stopped | the borrowed car hammered a wall at 212.7,65.2 twelve times on the way to the phone (fixed: pinned cars) |
| pt7_ze2b | WHEELER-DEALING | stopped | briefcase reached (one reported pinned-walker warp beside the box); the car, at carhp 18289 from the drive in, caught fire 17 s into the first dealer leg, the runner left it and re-entered it six times (fixed: `BAD_CARS`, a sound car before the clock) |
| pt7_ze2c | WHEELER-DEALING | failed (clock) | the race driver and the 3-frame position line: dealers 1-3 served 51, 85 and 154 s after the briefcase (pt6_ze2c: dealer 1 at 77 s); 164 road cells left for 26 s |
| pt7_ze2d | same | failed (clock) | dealers at 43, 85, 137 s; dealer 4 reached by car at about 175 s, the walk from the car to him stuck (the car between them), JOB FAILED at 188 s |
| pt7_ze2e | same | failed | dealers 1-2 at 43 and 77 s; walking round the car to its door at dealer 2 he was run over (lives 5 -> 4) |
| pt7_ze2f | same | failed (clock) | dealers at 46, 80, 149 s; the car caught fire on the last leg |
| pt7_ze2g | same | failed | turn speed 3.0 / braking 1.4 (`RACE_TURN_V`, `RACE_BRAKE_K`): dealers at 43 and 85 s, then three hard hits set the car alight on leg 3 (back to 2.6 / 1.2) |
| pt7_ze2h | same | failed | dealer 3 at about 150 s; the U-turn at dealer 3 (the car arrives heading south, leg 4 goes north) set the car alight |
| pt7_ze2i | same | failed (clock, 8 s short) | dealers at 43, 68, 119 s; dealer 4 reached with the clock at 0:08 (`shot_420`), and he walked into the side of his own truck, which stood between him and the dealer on the pavement (fixed: round the car's nose when the dealer is beside it) |
| pt7_ze2j-l | same | failed (clock, 10-25 s short) | the round-the-nose step stuck on a ramp at dealer 2 (now only for a dealer beside the car); the dealer-3 stop round the corner put the car between him and the dealer (now just past him on the same carriageway, leg 4 turning round the median's end); pt7_ze2l: dealers at 43, 77, 128 s, a wall at the last corner (166,117) cost 15 s and the clock ran out a block from dealer 4 |
| pt7_ze2m | same | failed (clock, 2-3 s short) | dealers at 25-36, 68-79 and 119-130 s (the clock starts when the game takes the briefcase, up to 11 s after the runner stands in the box); the last corner (166.9,117.5) stalled the car again and he reached the walk to dealer 4 as the clock ran out |
| pt7_ze2n | same | failed (clock, about 5 s short) | the last stop moved before that corner (167.5,115.8, then the pavement on foot): no stall, the car there at about 177 s, six seconds of walking left for three seconds of clock |
| pt7_ze2o/p/q | same | failed / stopped | 30-40 s lost on the dealer-2 or dealer-3 leg (stalls, a slow car): dealer 3 at 145-170 s |

### Status after part 6

- **PIZZA CAKE: JOB COMPLETE in the chase view** (pt7_le2e), the van shot on foot in third
  person with the game's own keys (96 rounds), frame `out/pt7_le2e/m_wil_le2_wrecked.png`.
- **RADIO ZA-ZA: JOB COMPLETE** in the same session right after it (the Loonies offer it after a
  completed Loonies job), frame `out/pt7_le2e/m_wil_le1_end.png`.
- **WHEELER-DEALING: not completed.** Seventeen sessions; the pace is there (dealers 1-3 in
  119-130 s of the 180, against dealer 1 at 77 s in pt6_ze2c) and four sessions reached the last
  dealer with 0-8 seconds on the clock (pt7_ze2d, ze2i, ze2m, ze2n), but each lost the last few
  seconds to one stall, one wall or one walk blocked by the car itself. The runner's choices for
  the four stops are in `mission_play_wil.py` (`WD_BACK`, `WD_TURN_AVOID`, the dealer-3 and
  dealer-4 stops); what would buy the missing seconds is a faster car taken before the briefcase
  (the borrowed car is whatever stands at the kerb, a truck in pt7_ze2i) or a walk to the
  briefcase box that does not wait for the game's reaction.

## Part 7 (8 Nov 2026, PLAYTHROUGH-8): WHEELER-DEALING complete; GET ZITZAKI after the Loonies

Sessions `pt8_*`, all on the fast path (`gamerun/grun.sh`, `FPS=0`) at **`GTA2_SPEED=2`** and
**`GTA2_DIRECT_KEYS=1`** (every frame a 3D one: driving in the chase view, walking in third
person), devtools F9/F11, `GTA2DX9_STATE_EVERY=3`, private stage `stage_pt8` (the shared
renderer, no DLL change). WHEELER-DEALING ran at speed 2 too: the runners' sleeps scale with
the speed, and the timeouts that are physical (the walker's "stuck" wait, the driver's stall
detection) now divide by it as well (`D.SPEED`), so a 2x session reacts in game time.

### Where the seconds went (pt7_ze2i/m/n/o logs and frames)

The pace on the dealer legs was already there in part 6; each near miss lost 10-38 s at one
place: **the walk from the car to the dealer**. The driver gets out on the car's left, on the
road side, and the dealer stands on the pavement on its right, so the straight walk ran into
the player's own car (`cruise: stuck 2.2 from 214.5,211.5` four times in pt7_ze2o). Worse, at the
third dealer the car stood in lane 216, traffic queued behind it and the walker was boxed in
between the queue and the median (pt7_ze2o: the HUD clock went from 1:08 to 0:41 there,
`shot_385`-`shot_410`). pt7_ze2n reached the fourth dealer one second after the clock ran out,
having lost 15 s at the first dealer the same way.

### Runner changes (`gamerun/`, mirrored in `linux/docker/`)

- **`M.walk_round_car(x, y, car, head)`**: after a stop the car as it stands (the nearest parked
  car and its heading from the renderer line) is a 1.5 x 0.9 footprint; when the straight walk
  to the dealer crosses it, he walks to the corner on his side first (nose or tail, the shorter
  way), then straight to the dealer (`cruise_to`, no router legs, when the line is clear within
  7 blocks). Logged as `walk_round_car: ... round its nose at ...`.
- **The four stops planned on the map, cell by cell** (`WD_STOPS` in `mission_play_wil.py`): the
  car stands in the lane next to the dealer's pavement about two blocks before him, so he is
  ahead of the nose and the walk is round the nose and a step: dealer 1 lane 227 at 80.4
  (he is on the corner pavement 226,82), dealer 2 lane 246 on the ramp at 130.4, dealer 3 lane
  215 at 209.3 (not 216, where the traffic queued), dealer 4 lane 168 at 123.2 beside him,
  reached by way of the junction (169.5,112.6, `WD_VIA`) so the last corner is taken from a
  slow roll instead of the race turn that overshot onto the pavement in pt7.
- **Before the clock**: the drive to the briefcase is at a careful pace (race mode off, cap 5),
  a car that arrives under carhp 25000 is swapped, a drive that is given up (a pinned borrowed
  car) gets another car instead of a walk to the box, and a car that arrives facing away from the
  first leg is turned round before the box (it is driven a few cells along the first leg's
  route and parked there): pt8_ze2a's three-point turn on the clock cost 9 s and pt8_ze2b's race
  into the box cost 10000 carhp, and that car burned on the third dealer's leg.
- **On the clock** (`M.RACE`): no throttle pull-out after a stall and no "wedged in traffic,
  leave the car" (pt8_ze2d walked past "the jam", found no car and came back to the same one):
  the car backs off with the wheel turned so the nose swings toward the route (`back_toward`)
  and re-routes; traffic waits are 0.6 s instead of 2; the last three blocks of a leg at 2.2
  blocks/s (was 1.2) and a handbrake stop (Down rolled the car back a block).
- **The car router keeps off walls and drops** (`EDGE_COST` 0.6 on a road cell with a wall face
  or no ground beside it, `edge_cell`): pt8_ze2d scraped the west railing of the level-3 deck on
  the dealer-2 leg four times (245.1,100.5, -4000 carhp); the route now runs down column 246.
- `drive3` gives up a pinned borrowed car for good (`BAD_CARS`): pt8_bil1 re-took the same
  pinned car four times.

### Runs

| session | job | outcome | what happened |
|---|---|---|---|
| pt8_ze2a | WHEELER-DEALING | failed (clock) | the first session with `walk_round_car`: every dealer walk 2-3 s; lost 9 s to a three-point turn into the pavement leaving the box (240.5,44.1) and 18 s at dealer 4 (the race turn into column 168 overshot onto the pavement, then a 13-cell walk) |
| pt8_ze2b | same | failed | raced to the box (7 wall hits, carhp 31118 -> 20785), the car caught fire on the dealer-3 leg (fixed: careful pace before the clock, swap under 25000) |
| pt8_ze2c | same | stopped | the borrowed car pinned at 206.7,68.6 on the way to the box, the runner walked to the box without a car and the clock started on foot (fixed: another car first) |
| pt8_ze2d | same | stopped | turned round before the clock (236.5,45.5), **dealer 1 26 s after the box**; the dealer-2 leg scraped the deck railing at 245.1,100.5 and "wedged in traffic" sent him out on foot (fixed: `EDGE_COST`, no exits on the clock) |
| pt8_ze2e | same | failed (clock) | no car at the kerb in 90 s, the box on foot, 86 s to dealer 1; then **dealer 2 in 25 s, dealer 3 in 34 s**, the clock ran out beside dealer 4 |
| **pt8_ze2f** | **WHEELER-DEALING** | **JOB COMPLETE** (+$20,000, 16 s left on the HUD clock) | car turned round before the clock and parked at 236.5,47.5; box at game-second 435, dealers at 469, 503, 546 and 597 (34, 34, 43, 51 s), every walk round the nose in 2-3 s, no stall, no wall. Frames: the briefcase `out/pt8_ze2f/m_wil_ze2_at_242_39.png` (clock 2:59), dealer 3 `m_wil_ze2_char_214_211.png` (the walk round the nose; the HUD clock read 2:27, 1:45, 1:09 and 0:16 at the four dealers), **JOB COMPLETE `m_wil_ze2_char_164_125.png`** (chase view, "You drive like the wind, Gecko", clock 0:16), `m_wil_ze2_end.png` |
| **pt8_chain1** | PIZZA CAKE, RADIO ZA-ZA, GET ZITZAKI | **PIZZA CAKE complete**, RADIO ZA-ZA failed, **GET ZITZAKI complete** | PIZZA CAKE: gun, phone, explosives, delivery, countdown, the van shot on foot in third person, **JOB COMPLETE** at game-second 521 (`m_wil_le2_wrecked.png`). RADIO ZA-ZA: answered (1954), on the drive to Futuro FM he was pulled out of the moving car at 128.6,15.1 (on foot at 08:01:43 while driving at 3 blocks/s) and run over on the road (lives 5 -> 4, 1125). **GET ZITZAKI** (Yakuza, 44.5,150.5): the Yakuza took the job after the two Loonies jobs (no refusal), Miura entered, hospital box, horn ("Get back there and sound the horn!" once, re-approached), the doctor aboard, the J-Lab garage box: **JOB COMPLETE** (+$20,000, multiplier 3, $60,186) at game-second 1493, frame `out/pt8_chain1/m_wil_ye1_end.png` (chase view, the Miura in the garage) |

### Status after part 7

- **WHEELER-DEALING: JOB COMPLETE** in the chase view at `GTA2_SPEED=2` (pt8_ze2f, 16 s to
  spare), after 17 sessions short in part 6. The dealer legs now take 25-51 s each and every walk
  2-3 s; what still loses a session is before the clock (no car at the kerb, a pinned borrowed
  car), which the runner now retries.
- **GET ZITZAKI: JOB COMPLETE** in the chase view (pt8_chain1), the Yakuza chain's first job,
  played after PIZZA CAKE in the same game: the Downtown chain continues on the Yakuza phones
  (next: BANK ROBBERY, `wil_ye2`, which needs the two bank guards shot; the plan runner has no
  step for "kill the characters the arrows point at" yet).
- RADIO ZA-ZA failed this time (a carjack and a death on the road), completed in part 6.
- For the next Yakuza job the plan runner got two generic steps (`mission_play_wil.py`, untested
  in game so far): a kill counter while the arrows point at characters walks at the nearest marked
  one with the trigger held until his arrow goes (`M.shoot_chars`: BANK ROBBERY's two bank
  guards), and a wait the runner has no step for while a point arrow is up goes to the arrow
  (`M.follow_arrow`: BANK ROBBERY's respray shop); a passenger step re-enters the marked car first
  when the player is on foot. The respray itself costs money (`playthrough-districts.md`,
  pt8_respray2: no repair with $20); BANK ROBBERY pays $5,000 for it first.

## Part 8 (8 Nov 2026, PLAYTHROUGH-9): targets from the game's own lists, a smoother driver

Sessions `pt9_*`, `GTA2_SPEED=2`, `GTA2_DIRECT_KEYS=1`, `FPS=0`, `GTA2DX9_STATE_EVERY=5`, devtools
F9/F11, private stage `stage_pt9` (the shared renderer plus this pass's `world_view.cpp`).

### Engineering

**Ped and car log lines.** The renderer now logs `view: peds` and `view: cars` every 10 frames:
every ped within 24 blocks (from the game's ped pool at `[0x5E5BBC]`, so peds in cars and peds
behind the camera are there) with his position, gang/remap, occupation, state, health, the car he
is in and the objective arrow that marks him; every car within 30 blocks with its model,
position, heading, speed, carhp, fire, driver and arrow. Format and fields in `actions-3d.md`,
"Ped and car log lines"; parsed by `M.peds()` / `M.cars()`. Verified in play: the RUSSIAN
SAILORS dealer stands in the line as `797:civ/zaibatsu:8:3:46.00,187.00,2.00:7:14:100:-:a12`
(arrow slot 12 marks him; pt9_bil4), the Zaibatsu in Downtown carry remap 8, the cops in their
car show `cop/police:0:24:...:m12`, the mission car shows `a<slot>` in the cars line, and the
player's own car is `P` with a speed in blocks per game second from the frame count.

**The smooth driver** (`drive_lib.py`: `dense_path`, `speed_target`, `lookahead`;
`mission_lib.drive3_smooth`, now what `drive3` runs, `DRIVER=classic` for the old one):

- the car follows the route's own cells (a GTA2 road is one cell per lane), resampled every 0.25
  blocks, with pure pursuit (look-ahead 1.3 blocks at a crawl to 3 at speed) instead of
  straightened legs from corner to corner; a lane point moves 0.38 off a wall or a drop beside its
  cell when the other side is open (`lane_points`), one-cell jogs of the lane-aware router are
  dropped (`unjog`);
- the speed comes from the turns ahead: the sharpest heading change within the braking distance
  sets what the car may carry into it (`v^2 = v_turn^2 + 2 a s`, a right angle at 1.3 blocks/s),
  1.6 on and before a ramp, 1.9 for a fragile car beside a wall, a walk over the last blocks of a
  precise stop;
- traffic from `view: cars`: a car in the lane ahead within the braking distance sets the speed
  (its own plus the gap beyond 1.9 blocks), a crossing car whose path meets ours within 2.5 s
  stops us short, a parked car (no driver) in the lane is routed round at once, a car standing
  for 5 s is routed round, and a third time at the same spot is gridlock (the band ahead off the
  route, back away); no reversing into a car behind (`car_behind`);
- after a hit (carhp down 250 in a sample) the car is held at 1.6 for 3 s and a fragile car's cap
  drops 0.3; a car pressed against something with the throttle on (250 lost on the spot) backs
  off toward the route, and pressing at the goal is arrival;
- peds from `view: peds`: a carjacker on foot near a slow car (robbed drivers, muggers, car
  thieves, the police when wanted) keeps it rolling at 2.4 and holds off the view changes; a
  marked character (a dealer being picked up) in front of the nose stops the car, a car within
  1.3 of him on each axis has arrived, and it never reverses toward him;
- the throttle in short pulses near a slow cap; the keys released before a re-route and before a
  view change (a route of 250 cells takes the router 1-2 s, and with the throttle held the car ran
  on blind: 45 blocks up column 18 in pt9_bil9); the speed taken from the renderer's frame-based
  value (wall time times `GTA2_SPEED` overstated the game time on a loaded host); one shared read
  of the log tail per step (`D.log_tail`: four reads of 60-120 KB made a step 0.3-0.5 s long).

**Wall hits on a fixed route** (`gamerun/drive_bench.py`, `keys_drive_bench.sh`, Downtown: a car
from the kerb, then the measured route from the level-3 ramp at 246.5,130.5 to the WHEELER-DEALING
lane stops 215.5,209.3 and 168.5,123.2; every carhp loss of 250 or more is a hit, a car contact
when another car stood within 2.4 blocks, a wall hit otherwise; `out/<run>/bench.json`, a frame per
hit):

| run | driver | blocks | wall hits | car contacts | hits per 100 blocks | fire | time (game s, wall x 2) |
|---|---|---|---|---|---|---|---|
| pt9_bench_classic1 | drive3 (PLAYTHROUGH-8) | 303.1 | 1 | 8 | 2.97 (walls 0.33) | no | 165 |
| pt9_bench_classic2 | drive3 (PLAYTHROUGH-8) | 324.6 | 3 | 6 | 2.77 (walls 0.92) | no | 215 |
| pt9_bench_smooth1 | first smooth version (no traffic) | 308.5 | 3 | 12 | 4.86 | no | 161 |
| pt9_bench_smooth2 | + traffic ahead | 413.9 | 0 | 3 | 0.72 | no | 350 |
| **pt9_bench_smooth3** | + crossing traffic | **305.1** | **0** | **0** | **0** | no | 202 |
| **pt9_bench_smooth4** | final (all of the above) | **312.0** | **0** | **0** | **0** | no | 167 |

The classic driver's hits were the pavement and building fronts at the corners
(`out/pt9_bench_classic2/m_hit07-09_wall.png`: the pickup up on the pavement against a door) and
traffic it drove into; the final smooth driver drove both 300-block runs without a scrape, as fast
or faster. On the missions the same driver still loses carhp to traffic that hits a car standing in
a queue or a pile-up at a junction (`out/pt9_ste5/shot_095.png`: the Residential junction by the
spawn) and to gang members' and police cars ramming it; those are not wall hits and the bench does
not measure them.

**The car router went round Industrial's pipe bridges.** `node_kind` took a lid one level up as a
solid block over the cell, and Industrial has elevated pipes over its roads (column 75 and column 62:
a field lid at level 2 with no faces, walls at level 3, the lane arrows running under them). Every
road under them was a wall to the router: the RUSSIAN SAILORS dealer-4 leg went round a 358-block
loop (PLAYTHROUGH-8 put it down to the embankment at rows 158-166, which the road at columns 68-71
passes under). A road cell under a lid with no faces at all is now open: dealer 4 from the Power
Cores is 252 blocks (387 before), the whole run (alley, four dealers, crane) about 1030.

### Runner changes (Downtown)

- `M.shoot_chars` aims at the marked characters as `view: peds` has them (only while they stand),
  and a gun in the inventory is selected (X) before any trip to a pickup (`select_gun`: pt9_wil4
  came out of the car with an empty hand and 990 machine-gun rounds and drove 172 blocks to a
  pickup in the middle of the guard fight).
- A counter step waits up to 20 s for character or point arrows after the first arrow (BANK
  ROBBERY: the car's arrow at the bank comes first, the two guards' arrows three seconds later
  with brief 1665; pt9_wil3 took the car arrow and drove to the safehouse with the guards alive).
- The re-approach to a horn box uses the box's own size (`back_to_box`, `creep_in(w, h)`): GET
  ZITZAKI's hospital box is 3 x 1 (`LOCATE_CHARACTER_BY_CAR(p1, 50.5, 178.5, 2.0, 3.0, 1.0)`), and a
  stop within a block of its centre was outside it (pt9_wil1/2: "Get back there and sound the
  horn!" for minutes, the doctor never came).

### Runs (part 8)

Contact sheet of this pass (both district docs): `out/playthrough_9_sheet.png` (bench frames
classic vs smooth, the RUSSIAN SAILORS dealers, BLOW JOB stage 1, GET ZITZAKI complete, the BANK
ROBBERY guards, DOUBLE-CROSS CRUSH, RADIO ZA-ZA).

| session | jobs | outcome | what happened |
|---|---|---|---|
| pt9_wil1 | RADIO ZA-ZA, PIZZA CAKE, GET ZITZAKI, BANK ROBBERY | RADIO ZA-ZA failed, PIZZA CAKE refused (1104), GET ZITZAKI stopped | RADIO ZA-ZA's script sets `MAKE_ALL_CHARS_MUGGERS (ON)`: every ped is a mugger (occupation 40 in `view: peds`); pulled out 3 s into the drive with one 2.7 off (72.4,49.2), then killed. GET ZITZAKI: the 3 x 1 hospital box, re-approached to within a block of its centre for minutes, the doctor never came |
| pt9_wil2 | RADIO ZA-ZA, GET ZITZAKI | failed; stopped | pulled out the same way at 72.7,48.3: the first-person view change at the start of the drive takes 3.4 s standing (fixed: no view change with a jacker within 12 blocks); the hospital box again (fixed: `back_to_box`) |
| **pt9_wil3** | GET ZITZAKI, BANK ROBBERY | **GET ZITZAKI JOB COMPLETE** (501 s, +$20,000); BANK ROBBERY stopped | the Miura into the 3 x 1 box, horn, the doctor aboard (1639), the J-Lab garage: frame `out/pt9_wil3/m_wil_ye1_end.png`. BANK ROBBERY: the counter step took the car's arrow at the bank before the guards' arrows came and drove to the safehouse (fixed: wait for character arrows) |
| **pt9_wil4** | same | **GET ZITZAKI complete** (671 s); BANK ROBBERY stopped | the guards' two arrows taken (`shoot the 2 marked characters`), but out of the car the hand was empty with 990 rounds in the inventory and the runner drove 172 blocks to a pickup; the shooting step ran out of time (fixed: `select_gun`) |
| **pt9_wil5** | same | **GET ZITZAKI complete** (524 s); BANK ROBBERY stopped | 1665 came a minute after the bank box (after 1658, 1659), with the plan already past its counter step (fixed: `kill_if_asked` at every step) |
| **pt9_wil6** | GET ZITZAKI, BANK ROBBERY, RADIO ZA-ZA | **GET ZITZAKI complete** (439 s); BANK ROBBERY failed; RADIO ZA-ZA failed | BANK ROBBERY: brief 1665 caught at the bank, the two guards found in `view: peds` (`1108:crim/police:0:33:185.50,174.50,3.00:...:a12` and `1109:...:a13`, on the bank's level-3 steps) and shot at on foot; the shooting raised wanted level 1 and he was arrested beside the bank (1125, lives unchanged: `HAS_CHAR_BEEN_ARRESTED`). RADIO ZA-ZA: the car took 8800 in one hit at 71.6,35.9 standing near the phone and burned; he died in it (1125) |
| pt9_wil7 | RADIO ZA-ZA | failed | a jam at 77-81,36 a minute into the drive (two hits, back-off), and a mugger 0.9 blocks off pulled him out at 82.6,34.6 while the car stood |

### Status after part 8

- **GET ZITZAKI: JOB COMPLETE four times** (pt9_wil3/4/5/6) with the smooth driver (439-671 s);
  frames `out/pt9_wil3/m_wil_ye1_end.png` (and the same name in wil4/5/6).
- **BANK ROBBERY: not completed.** The runner now gets to the guard fight with the guards in hand
  (their positions and arrow slots from `view: peds`, brief 1665 caught at any step), but shooting
  them at the bank raises the wanted level and the police arrest him on the spot (pt9_wil6). What
  would finish it: shoot from the car or from further off, or leave and come back once the level
  drops; then the respray ($5,000 paid first) and the safehouse.
- **RADIO ZA-ZA: not completed** this pass (three failures): with every ped a mugger, a car that
  stops anywhere is lost; the keep-rolling rule helps only while the lane is open. pt9_wil6's
  car also took 8800 in one hit at a standstill near the phone (a fire bomb or an explosion, not
  identified in the log).
- **The smooth driver** made the fixed 300-block route clean (0 hits in two runs, 2.8-3 hits per
  100 blocks before) and is now the default (`DRIVER=classic` for the old one).

## Part 9 (8 Nov 2026, PLAYTHROUGH-10): BANK ROBBERY complete

Sessions `br*`, fresh games, `GTA2_SPEED=2`, `GTA2_DIRECT_KEYS=1` (every frame a 3D one: driving in
the chase view with a first-person stretch, walking and shooting in third person), `FPS=0`,
`GTA2DX9_STATE_EVERY=5`, devtools F9/F11 (no warp was used), private stage `stage_pt9` (the renderer
with the `view: peds` / `view: cars` lines). The job has a runner of its own,
`gamerun/missions/bank_robbery.py` (mirrored in `linux/docker/missions/`, keys script
`keys_bank_robbery.sh`), on the shared `mission_lib` / `drive_lib`, which were not changed.

### What the script wants (`wil_m/wil_ye2.mis`) and what lost pt9_wil6

The GRAHAM from 52.5,150.5 to the City Bank box 194.5,177.5 (3 x 2, in that car); two guards
(`CRIMINAL_TYPE1` in police clothes, `crim/police` with arrow slots in `view: peds`) appear on the
bank's level-2 entrance walk at 185.5,174.5 / 185.5,175.5 (z 3); when both are dead Hiroshi walks out of
door16 one block, joins the player's group, and the script sets the wanted level to 2 stars with
`ALTER_WANTED_LEVEL_NO_DROP` and pays $5,000 for a respray (1655). It then waits on
`CHECK_HEADS_GREATER(p1, 0)`, so only a respray (or a bribe) ends that stage, and finally wants the
GRAHAM in the safehouse garage (76.5,200.5, 3 x 1). An arrest, a death or a wrecked GRAHAM at any stage
is JOB FAILED.

pt9_wil6 shot from the street (z 2) at guards one level up: the bank's front wall took every round
(ammo stopped falling while he stood firing into it), a passing patrol car saw the gunfire (wanted 1)
and the officers arrested him there. Killing the guards does not raise the level by itself (wanted 0
after both fell in br2, br7, br9); the two stars come from the script.

### The runner (`missions/bank_robbery.py`)

- **The phone on foot** (113 blocks from the spawn, 1-2.5 min): br2's borrowed car was pinned and set
  alight at 57.4,143.6 on the way.
- **The getaway is pre-positioned** before anyone is shot: in the box, as soon as the guards are in
  `view: peds`, the car is turned with short reverse/forward pulses to face west, the way the getaway
  runs (`turn_car_toward`), and he waits in it while any police car or officer is within 22/16 blocks.
  br8 parked facing north; the first metres of the getaway were a turn and a re-route, and a cop pulled
  him out 14 s in (JOB FAILED).
- **The stairs by hand-placed points** (`CLIMB`, plain `cruise_to` legs): the flight on row 177 rises
  west from 193 to 190 and is entered along the south half of the cell; the router's legs pressed him
  against the stone block at its foot for 80 s in br4. Climb now 5-8 s.
- **Shooting along the walk** from its east end (189,175), walking at the nearer marked guard with the
  trigger held while he is over 2.2 blocks off (a standing ped turned with the trigger held lagged:
  br2 fired north for 10 s). Both guards fall in 3-8 s; the trigger is released the moment the marked
  `crim/police` peds are gone (Hiroshi comes out of the door behind them, and the job hangs if he dies).
- **Straight back** by hand-placed points (`DESCEND`), Return beside the car, 0.8 s of throttle at once,
  then the drive: on foot 7-10 s from the last guard to the wheel (br4: 28 s, and the police were at the
  car).
- **The nearer respray.** Any respray clears the level; the job's own shop (86.5,160.5, `CAR_SHOP 9`) only
  adds a $5,000 bonus for its colour. The runner uses the `CAR_SHOP 10` drive-through at 204.5,221.5
  (column 204 under a roof, entered from the road at row 216), 85 blocks from the bank instead of 156:
  30-35 s with two stars behind. The respray costs $5,000 (money 5040 -> 40) and **repairs the car**
  (carhp 31156 -> 32000 in br7), which answers PLAYTHROUGH-8's question: the $20 probe failed for money.
- **The safehouse** from the road at row 203, creeping north into the 3 x 1 box; the game parks the car.
- `drive3` is called with `CAR_AVOID` cleared (stall cells from an earlier leg sent br2's second attempt
  round a 186-block loop by the north); the job's own outcome check (not `M.outcome`, which counts
  +$10,000 as a completion: this job pays $5,000 twice before the end).

### Runs

| session | outcome | what happened |
|---|---|---|
| br1, br3 | no game | br1: the GPU's framebuffer could not be created (VGL FBO incomplete, 20 GB of 23 in use by other runs); br3 was a mistaken launch, killed |
| br2 | failed | phone by a borrowed car that burned; the GRAHAM took 16000 in jams at the column-142/row-169 junction and burned on the way; the guards were shot from the walk (wanted 0), the car burned out before the respray |
| br4 | failed | 80 s on the stairs, 28 s back to the car: the police were beside it, pulled him out (1666, 1125) |
| br5, br6 | lost | the host overload (load 68) killed every container |
| **br7** | **JOB COMPLETE** (282 s from the phone) | guards down 8 s after leaving the car, in the car 9 s later, respray at 204.5,221.5 (car repaired), safehouse; +$20,000 |
| br8 | failed | the car faced north at the bank; a cop pulled him out during the turn 14 s into the getaway (fixed: pre-positioned getaway) |
| **br9** | **JOB COMPLETE** (384 s) | getaway car set facing west at 199.8,178.9; walk reached in 8 s, guards down 3 s later, in the car 10 s after that, respray 31 s, safehouse; +$20,000 |
| br10 | failed | getaway set facing west, guards down, in the car 7 s later (carhp 26963 after the first drive), then 30 blocks down column 178 the lane was blocked at 178.4,208.2 with officers 1-2 blocks off and a gang member beside the car; pulled out while the car was pressed (1125) |

Frames: `out/mission_bank_robbery_sheet.png` (br9: the title at the phone, the GRAHAM at the bank,
the walk, both guards down, the respray, JOB COMPLETE; br7 JOB COMPLETE), and `out/br7/m_br_*.png`,
`out/br9/m_br_*.png` (`m_br_end.png` is the JOB COMPLETE frame in each).

### Status after part 9

- **BANK ROBBERY: JOB COMPLETE in 2 of 3 sessions on the current runner (br7, br9; br8 failed before
  the getaway fix).** Counting the confirmation run br10 (failed in the getaway's traffic), it is 2 of 4 consecutive sessions.** The Yakuza green-phone pair is done (GET ZITZAKI in parts 7-8).
- What still loses it: a standstill in traffic during the 85-block getaway with two stars behind (br10: a blocked lane at 178.4,208.2), a police car passing while the GRAHAM stands at the bank (the runner waits up to
  70 s for none within 22 blocks, then goes anyway), and the jams at the column-142/row-169 junction on
  the first drive (br2: the car burned there; the respray would repair it if it got that far).

## Part 10 (9 Nov 2026, Wave M SKILL-DELIVER): the 'deliver intact' skill, proven on GET ZITZAKI

The Wave M skill module for the 25 catalogue jobs tagged `deliver_intact`:
`gamerun/skills/deliver_intact.py` (mirrored in `linux/docker/skills/`). The proof job has its own runner,
`gamerun/missions/get_zitzaki.py` (keys script `keys_get_zitzaki.sh`). Both car legs of the job, the
Miura to the hospital's 3 x 1 horn box and the doctor to the J-Lab garage (`IS_CAR_IN_BLOCK` 44.5,203.5,
3 x 0.8, then `PARK`), are `deliver_intact.deliver(world, box, ...)` calls. The shared
`mission_lib` / `drive_lib` were not changed.

All sessions: fresh game, plain renderer (shared `repo/stage`), `GTA2_SPEED=1`, `GTA2_DIRECT_KEYS=1`,
`FPS=0`, devtools F9/F11 enabled. No warp was used: the phone on its level-3 dais was reached on foot
every time. Driving was in the chase view, with a 15 s first-person stretch at the start of the first
drive.

### What the skill does

- `deliver(world, box, car=, approach=, done=, check=, shops=, budget=, park_wait=)` runs one leg:
  - It re-boards the mission car whenever he is out of it. The script's arrow goes back to the car,
    target kind 3/4.
  - It drives with the fragile-car guards (`M.drive3(..., slow=True, precious=True)`), clearing the
    avoid list for each leg.
  - It lowers the speed cap in steps as carhp falls (26000/22000/18000 -> 2.6/2.0/1.6).
  - It goes to a respray when the car burns or carhp drops below 17500 and a shop is nearer than the
    goal. A respray repairs the car to carhp 32000 and clears the wanted level. Downtown's two shops
    are built in; other districts pass `shops=`.
  - It approaches a narrow box from its open side and creeps in with short pulses.
  - Once the box is reached it releases every key and waits while the game parks the car.
- `open_side(world, box)` reads the map to find where a car can enter a box. For each side it scores
  the lanes 1-3 cells out from the box edge (road 3, lot 1, pavement 0.5) and stops a lane at a wall
  face or missing ground. Results: the hospital forecourt from the east (54.6,178.5); the J-Lab garage
  from the south (44.5,206.5); the BANK ROBBERY safehouse from the south (76.5,203.6, the same point
  that runner places by hand).
- `box_arrow(box)` is the arrival test, read from the script's arrow: `up` (pointing at the box, not
  there yet), `cleared`, `moved` or `car`. **REMOVE_ARROW does not empty the slot.** It keeps the box
  coordinates and sets the target kind to 0. In dl_zz2 the Miura stood inside the hospital box at
  51.32,178.30 with slot 12 at `12:4:0:50.50,178.50` for 8 s. The skill was waiting for the slot to
  disappear, so it backed out, and it did this eight times. Kind 0 at the box now counts as arrived.

### Sessions

| session | code | outcome | what happened |
|---|---|---|---|
| **dl_zz1** | first version | **JOB COMPLETE** (956 s from level start; +$20,000, multiplier 2) | The phone was reached on foot. The first drive to the hospital took 255 blocks of the router's path, at the smooth driver's normal pace: a bug restored the caps in the wrong order, so `SMOOTH_SLOW_CAP` was 22000 (fixed). The approach point taken from the route's last cells (north of the box) left the car pressed against the forecourt's kerb for two minutes. Once in the box (arrow kind 0) the horn worked and the doctor boarded (1639, carhp 18300). The garage was entered from the south and the game parked the car. |
| dl_zz2 | + open-side approach | stuck (doctor never boarded) | Each of the eight approaches from the east got into the box (51.3,178.3, arrow kind 0). Each time the skill waited for the arrow to disappear and then backed out. Fixed with `box_arrow`. |
| **dl_zz3** | + `box_arrow` | **JOB COMPLETE** (1039 s; +$20,000) | Hospital box from the east, creep, "the game has it" (carhp 29973). Doctor aboard 6 s later. The garage drive was 130 blocks of the shared router's route for a 30-block crow line, with 7 hits; carhp 23650 at the door. Garage from the south, park, 1124. |
| dl_zz4 | same | stuck (doctor never boarded) | The car was in the box with the arrow cleared, then rolled out after a 0.3 s handbrake tap. The skill was still in its 45 s park wait, so the horn came too late. Its 2-block `drive3` back to the approach point then re-planned itself 50 blocks away from 53.1,177.9. Fixed: the creep returns only once the car has stopped inside (handbrake 0.7 s, brake tap, position checked again); within 6 blocks of the box, on its open side, it creeps directly and skips `drive3`; `park_wait=0` for a box that is not a park. |
| dl_zz5 | + those fixes | stuck (ran out of time 8 blocks from the garage) | The hospital part was clean: in the box in 26 s of creep, doctor aboard 6 s later. The garage leg spent its whole 420 s budget in one `drive3` call on the 130-block route, in traffic, with 13 hits. Fixed: one `drive3` call is capped at 240 s (`DRIVE_CALL`) and the leg then re-plans; the garage leg gets 800 s and 8 tries. |
| **dl_zz6** | + `DRIVE_CALL` (latest code) | **JOB COMPLETE** (900 s; +$20,000) | The first drive to the hospital was pushed 30 blocks west by traffic and stopped at the 420 s leg budget. The horn step's re-delivery drove back (two calls). Creep, "the game has it" in 12 s, doctor aboard 6 s later. Garage in 96 s (carhp 24785), park, 1124. |
| **dl_zz7** | same (confirmation) | **JOB COMPLETE** (858 s; +$20,000) | Hospital box from the east (creep 25 s, carhp 28697), doctor aboard 6 s later. Garage in 218 s (carhp 23535), park, 1124. |

**Result: the first three sessions reached JOB COMPLETE 2 of 3 times (dl_zz1, dl_zz3). Over all six
sessions it is 4 of 7 (dl_zz1, dl_zz3, dl_zz6, dl_zz7), and 2 of 2 on the latest code (dl_zz6,
dl_zz7).** Each failure found a defect in the skill, fixed before the next session. The frames are in the chase view:
`out/dl_zz3/m_zz_hospital.png` and `out/dl_zz6/m_zz_*.png`, `m_zz_doctor.png` (the Miura in the forecourt, brief "Bring Doctor
ZitZaki directly to the new J-Lab") and `m_zz_garage.png` (JOB COMPLETE at the garage door). dl_zz1 has
the same names. The frames are not in git.

### Using the skill in another job runner

```python
from skills import deliver_intact as DI
r = DI.deliver(world, (x, y, w, h), car=(cx, cy), check=check, view_switch=view_switch,
               done=None,            # default: the box's arrow cleared/moved, or 1124/1125
               shops=None,           # default: DI.SHOPS[world.district] (only 'wil' is filled in)
               budget=420, park_wait=45, label="the garage")
# r: "delivered" | "complete" | "failed" | "dead" | "stuck: ..."
```

Open items:
- Respray shops for `ste` and `bil` are not listed yet.
- The respray detour has not run in a session yet: no car fell below 17500 on a leg it could save.
- The shared car router still chooses long detours, which the skill cannot change: 255 blocks for a
  60-block crow line to the hospital in dl_zz1, 130 for 30 to the garage (dl_zz3; this one is real: row 194 is solid and the garage driveway is reached from row 211). These detours cost
  most of the car damage.

## Part 11 (9 Nov 2026, Wave M, SKILL-KILLMARK): the kill-marked skill on BANK ROBBERY

The `kill_marked` skill (23 jobs in `missions-catalogue.md`) as one module,
`gamerun/skills/kill_marked.py` (mirrored in `linux/docker/skills/`), on the shared `mission_lib` /
`drive_lib` (unchanged). Proven on BANK ROBBERY (`wil_ye2`), the only green-phone job of a fresh
game whose kill step is marked characters (the two bank guards); the yellow and red jobs need respect
2/4 first. The job glue, `gamerun/missions/bank_robbery_km.py` (keys `keys_bank_robbery_km.sh`), reuses
`missions/bank_robbery.py` unchanged for the phone, the GRAHAM and the bank box, and replaces its
hand-written guard loop with one call:

    K.kill_marked(world, select=is_guard, spare=is_spare, approach=BR.CLIMB, level=2,
                  fire_spots=BR.FIRE_SPOTS, secs=150, check=job_check)

What the skill does for any job: targets are the marked live peds of `view: peds` (the arrow slot on
the ped), filtered by the job's `select`, nearest first and the player's own level first; kind-2 arrows
when no target is in the 24-block peds window (or he sits in a car: the car is shot). Out of the car,
a gun in the hand (`select_gun`, a pickup only with no rounds at all). A target on another level: the
job's hand-placed `approach` points once, then the multi-level router. Far: walk at him, trigger off;
in range (7-8 blocks): walk at him with the trigger held, standing under 2.2 blocks. No damage for 8 s:
the next fire spot, a side step across the line, or closer. A `spare` ped (Hiroshi here) in the line of
fire holds the trigger. The trigger is released the moment the last target falls; the step ends when
the character arrows are gone, or when every target seen is down (an arrow on a spared ped is ignored).
With `GTA2_DIRECT_KEYS=1` the walk and the gun run in the chase view: every fight frame is third person.

The glue also hardens the getaway after the first runs: the GRAHAM is followed by its model in
`view: cars` when it has been taken (km2: the old runner walked to where it had been parked); the
respray is entered rolling with the throttle held from 2.5 blocks before the tunnel (km1: the drive
stopped at the tunnel mouth with officers 1-1.5 blocks off, 1666, arrest); from km5 the getaway car
faces east and runs east on row 180, south down the column-216 avenue and west on row 215 to the
tunnel, off the column-178 avenue where br10 and km4 were caught.

Sessions `km*`, fresh games, `GTA2_SPEED=2`, `GTA2_DIRECT_KEYS=1`, `FPS=0`, plain renderer on a private
stage (hard link of the gated `repo/stage`), devtools F9/F10 (the job runner's reported warp onto the
phone dais was used in km2 and km5).

| session | skill (guards) | job | what happened |
|---|---|---|---|
| km1 | **both down**, 32 s after leaving the car (stairs: the approach missed one point, the router finished the climb) | failed | getaway: the drive stopped at the respray tunnel mouth (205.3,218.0) with officers beside the car; pulled out (1666) and arrested |
| km2 | **both down** 9 game-s after the climb | failed | a gang member 0.5 blocks from the car at the start of the getaway; pulled out at 178.9,183.7 17 s in; the runner walked to the old parking spot |
| km3 | **both down** in 9 game-s | failed | respray rolled in (wanted 2 -> 0, carhp 32000); on the 197-block safehouse drive the GRAHAM was pinned at 96.3,202.1 and took 6 000 in 4 s, burned and was wrecked |
| km4 | **both down** in 26 game-s | failed | getaway west then south: pressed in a jam at 181.3,206.0 with an officer 1.6 blocks off, pulled out and arrested (as br10 at 178.4,208.2) |
| km5 | **both down** in 9 game-s (6 s wall) | failed | back in the car 5 s after the last guard; pulled out 0.3 s after boarding by a passer-by (1666) as the two stars came, then arrested |
| km6 | **both down** in 9 game-s | failed | east getaway, but leg 1 was skipped by a wrong test and the drive came along row 216; the Up-held roll-in could not turn into the one-cell bay, swung into the BOMB bay at 202 (money 5040 -> 41: a car bomb, no respray, wanted still 2) and the turn's reverse pulses backed him into an officer (1666, arrest) |
| km7 | - | no job | the job runner's phone step: after the reported warp onto the dais the phone said 1093 (refused); not counted |
| km8 | **both down** in 9 game-s | failed | ran with KILLMARK-GETAWAY's getaway rework of the glue (lane launch, bay lane-in); out of the car on the second respray try at 197.7,213.5, then 1125 |

Frames (chase view): `out/km1/m_km_bank_engage.png`, `out/km*/m_km_bank_first_down.png` (the first
guard falling), `out/km*/m_br_guards.png` (both guards down on the walk, the player standing over
them); marks and the skill's lines (`kill_marked: ...`) in `out/km*/marks.txt` and `keys.log`.

### Status after part 11

- **The skill: 7 of 7 sessions with both marked guards down** (km1-km6, km8), 6-32 s after leaving the
  car, 25-40 rounds, wanted level 0 at the last kill (the two stars come from the script afterwards),
  Hiroshi never hit, every fight frame in the chase view.
- **The job: 0 of 7 JOB COMPLETE.** Every loss came after the skill returned: the two-star getaway to
  the respray (pull-outs at the car, at the tunnel and in jams; a wrong bay; a wrecked car on the
  safehouse drive). The old runner had 2 of 4 on the same getaway. The acceptance criterion (2 of 3 to
  JOB COMPLETE) is **not met**. The getaway in `bank_robbery_km.py` is now KILLMARK-GETAWAY's (kmg*
  sessions); the wanted-level side belongs to SKILL-POLICE (`skills/shake_police.py`).
- For other jobs: `kill_marked(world, select=..., spare=...)` with no other arguments covers street-level
  targets. Pass `approach`/`level` for targets on a terrace, `count` for a counter step, and `check`
  for the job's own failure test.

## Wave M, SKILL-ROOFTOP (9 Nov 2026): rooftop access on foot, `skills/rooftop_access.py`

32 of the 67 phone, tutorial and final jobs need `rooftop_access`: the phone or an objective is on a
raised terrace or roof. Until now the runners reached those phones with a reported developer scene warp
and warped back down after the answer (parts 3-4; `mission_play_wil.answer`,
`mission_play_districts.answer`). The skill module `gamerun/skills/rooftop_access.py` (mirrored in
`linux/docker/skills/`, keys script `keys_rooftop_access.sh`) climbs up and comes back down on foot with
warps off. It changes none of the shared libraries.

- `launch_cell`: chooses the cell beside the phone to step on from. The cell must be level with the
  phone, have no wall face toward it, and not be a phone itself. It must be reachable with every other
  phone cell avoided, and should be as far from the other phones as possible. The Downtown Zaibatsu pair
  (COP CAR CRUSH 208.5,57.5 and WHEELER-DEALING 208.5,59.5) stands on a one-block rim. The router's
  last cell would be (208,58), between the two phones; the skill steps on from (209,57) instead.
- `climb`: plans with `mission_lib.route3` and splits the route into flights. A flight is a stair, or a
  ramp of up to eight slope pieces stored at one level. Each flight is walked to the first flat cell above
  it, and arrival is checked by the ped's height. If the walker fails the same flight twice, its slope
  cells are added to `BLOCKED` (learned) and the route is planned again. A fall triggers a new plan from
  where he lands.
- `descend`: walks back down to street level along the route toward the plan's first target (the mission
  car), with the same height checks.
- `answer_roof_phone`: climbs to the launch cell, then calls the session's own `answer`. After the
  answer, the player steps back onto the launch cell, never `step_off_phone`. In rf1, `step_off_phone`
  picked (208,56): a dead end on the terrace whose only way out is the phone itself.
- `--survey <game dir> <missions-catalogue.json>` runs on the host and needs no game. **34 of the 36
  rooftop-job phones** (the 32 jobs; the shared yellow follow-ups appear twice) have a stair or ramp
  route from the district start to a launch cell. Typical routes are 130-325 cells with 1-8 flights. The
  two without a route are Industrial's Zaibatsu pair (`bil_ze1`/`bil_ze2`, 44.5,163.5 / 45.5,161.5,
  level 2). Both phones stand on level-2 field cells boxed in by level-3/4 blocks, and the router finds
  no stair into them; this has not been checked in game.

### Sessions (COP CAR CRUSH, `wil_ze1`, fresh game, `GTA2_DIRECT_KEYS=1`, plain renderer, no warp anywhere)

| session | rooftop part | job outcome | what ended the job |
|---|---|---|---|
| rf1 (2x) | terrace reached on foot in 145 game-s; phone answered (brief 1681); the descent failed (dead-end step-off, fixed) | JOB FAILED | the Cop Car caught fire on the crusher leg. The first version also checked the ramp top on a slope piece, which made 5 spurious retries and learned 1 false block (fixed). |
| rf2 | up 3 flights, phone, down 3 flights, back on the street at game-second 145; 0 retries | BUSTED | wanted level 1 in the Cop Car; the driver stopped behind a parked car at 85,74 and a cop arrested him |
| rf3 | up and down clean (a governor pause of 9 wall-minutes = 17 game-s at the last flight) | stopped | run over by traffic crossing to the Cop Car at 208,43.5; hospital respawn |
| rf4 | up and down clean, 6 flights, 1 retry; phone answered at game-second 119 | stopped (car burned) | Shady aboard and the yard box passed. The shared crusher-pad step then pressed the Cop Car around the crusher yard (175-185 x 14-16) from carhp 22000 until it caught fire |
| **rf5** | up 3 flights in 119 game-s, 0 retries; phone at 154 s; back on the street at 188 s | **JOB COMPLETE** (+$20,000, multiplier 2, message 1124, game-second 930, 0 faults) | Cop Car at 196 s, Shady aboard at 435 s. The car caught fire 160 blocks from the yard and was driven on; parked at the pad and crushed. Frame `out/rf5/m_wil_ze1_crusher0.png`: JOB COMPLETE in the chase view |
| rf6 | up and down clean (6 flights, 1 retry), street at game-second 196 | BUSTED | arrested at the Zarelli Cop Station (209.6,43.8) seconds after taking the Cop Car (cop points 600, "punched down while wanted") |
| rf7 | up and down clean, phone at 128 s, street at 171 s | JOB FAILED | Shady aboard at 486 s; the car caught fire 180 blocks from the yard, and the crusher-pad step finished it in the yard (as in rf4) |

Frames (chase view, not in git): `out/rf1/m_rooftop_terrace.png` (on the terrace beside the phone,
with the HUD's "Answer the phone"), `out/rf2/m_wil_ze1_street.png` (back on the street after the
descent), and `m_wil_ze1_*` for the job's steps.

**Rooftop access: 7 of 7 sessions climbed to the terrace phone and answered COP CAR CRUSH (not the
neighbour) without a warp. 6 of 6 came back down on foot after the step-off fix (rf1's descent ran before
it).** Climb time from the level start: 119-137 game seconds; 0-1 flight retries per session; no false
learned blocks after the flight fix.

**Job: 1 of 6 sessions with the final code reached JOB COMPLETE (rf5).** The acceptance bar of 2 of 3 is
not met with the shared plan runner. Every loss came after the roof, in shared steps of
`mission_play_wil.run_plan` and `mission_lib.drive3`:
- the crusher-yard parking step burned the Cop Car (rf4, rf7);
- busted around the stolen Cop Car (rf2, rf6);
- run over crossing to the car (rf3).

Those steps belong to the crusher/crane, police and car-handling streams. SKILL-CRUSHER's
`missions/cop_car_crush.py` now chains this skill with `deliver_intact`, `horn_pickup` and
`crusher_crane` for the same job.

### Using the skill in another job runner

```python
from skills import rooftop_access as RA
RA.D, RA.M, RA.P, RA.world, RA.say = D, M, P, world, D.say    # the session's modules
ok, ms, info = RA.answer_roof_phone(world, entry, P.answer)     # climb, answer; info["launch"] = launch cell
s, down = RA.descend(world, toward=(x, y))                      # back to the street toward the next target
s, ok = RA.climb(world, tx, ty, tl)                             # any raised point (a LOCATE box at z >= 4)
```

Open items: Industrial's Zaibatsu phones (`bil_ze1`/`bil_ze2`) have no router route (check in game); the
CLI hands over only to the Downtown session (`mission_play_districts` for ste/bil needs the same hand-off).

## Wave M, SKILL-CRUSHER (9 Nov 2026): crusher and crane, `skills/crusher_crane.py`

COP CAR CRUSH (`wil_ze1`) played by `missions/cop_car_crush.py`, which chains the Wave M modules:
`rooftop_access` (the Zaibatsu terrace phone on foot), `deliver_intact.board` (the Cop Car),
`horn_pickup.pickup` (Shady at the Avalon station) and `crusher_crane.crush` (the crusher leg and the
crane). Details, API and the hook rule: `docs/skill-crusher.md`.

The crane lifts a car standing under its hook, 2.5 blocks from the tower along the crane's rotation
(Downtown crane1: 177.0,11.5). The module reaches the yard by the fragile drive to a lane mouth only,
then creeps straight up an open lane (south through the yard gate) to the hook, gets out and walks
back down the lane. That replaces the shared crusher-pad step that pressed the car round the yard
walls until it burned (rf4, rf7).

| session | outcome | crane step |
|---|---|---|
| ccc1 | not a test (a 16-minute governor pause spent the climb's wall-time budget) | - |
| ccc2 | failed: the Cop Car pinned against a stopped car at 144,35 on the crusher leg, alight | not reached (pin guard added) |
| **ccc3** | **JOB COMPLETE**, game-s 759 | the car arrived alight (16336); second hook candidate, crushed at once |
| **ccc4** | **JOB COMPLETE**, game-s 879 | gate scraped on the first creep; second candidate, taken in 4 s |
| **ccc5** | **JOB COMPLETE**, game-s 666 | first try, 0.06 from the hook, no damage |

**3 of 3 sessions since the pin guard reached JOB COMPLETE**, all in a fresh game, no warp, chase-view
frames (`out/ccc5/m_ccc_crane_hook.png`, `m_ccc_end.png`; not in git).

## Wave M, SKILL-HORN (9 Nov 2026): horn pick-ups, `skills/horn_pickup.py`

GET ZITZAKI (`wil_ye1`) played by `missions/zitzaki_horn.py`: SKILL-DELIVER's `get_zitzaki.py`
unchanged, with only its horn step replaced by `horn_pickup.pickup`. The stop is the hospital's
3 x 1 strip, entered by `deliver_intact`'s creep. The horn is taken when the script creates the doctor,
and the car stays in the strip while he walks. Details, API and FAKE TRUCE (`ste_se2`, the module's
four-group runner; the Factory Bus burns after group 2): `docs/skill-horn.md`.

| session | horn stop | outcome |
|---|---|---|
| **zh1** | horn on press 1, the doctor aboard in 5 s (1639) | **JOB COMPLETE** 1124 at game-s 811, +$20,000 |
| zh2 | press 1, aboard in 0 s | not complete: the Miura burned on the garage leg; the 900 s run ended |
| zh3 | not reached | stuck: pulled out of the Miura on the hospital leg, the re-board walked to the spawn point |
| **zh4** | press 1, aboard in 0 s | **JOB COMPLETE** at game-s 777 |
| **zh5** | press 2, aboard in 0 s | **JOB COMPLETE** at game-s 896 |

**3 of 5 sessions, 2 of the last 3, reached JOB COMPLETE. The horn stop succeeded every time it was
reached.** Speed 2, fresh game, no warp, frames in the chase view (`out/zh1/m_horn_doctor_horn.png`,
`out/zh4/m_zz_end_third.png`; not in git). The same module is in SKILL-CRUSHER's COP CAR CRUSH (Shady,
ccc3-ccc5, 3 of 3 complete).

## Wave M, ROOFTOP-PROVE (9 Nov 2026): COP CAR CRUSH with the on-foot climb, `skills/rooftop_access.py` fixes

The proof job was COP CAR CRUSH (`wil_ze1`, Zaibatsu HQ level-4 terrace). The runner was
`missions/cop_car_crush.py` (SKILL-CRUSHER's). It calls `skills/rooftop_access` for the phone,
`deliver_intact` for the Cop Car, `horn_pickup` for Shady and `crusher_crane` for the crane. Every
session ran on a fresh game with `GTA2_SPEED=2`, `GTA2_DIRECT_KEYS=1` and `WARP_OK=0`. There was no
warp anywhere. Changes to `skills/rooftop_access.py` (shared runner libraries untouched):

- **Budgets on the game clock** (`GameClock`): the climb's budget is the wall clock, capped at the
  game's own clock (the renderer's frame counter) plus 12 s. A flight whose walk spanned a governor
  pause is not counted as a failed flight (ccc1 lost its whole climb, 991 s, to a 16-minute pause
  after 17 game seconds). In the game: rp1, rp2, ccc4 and rp4 each had a 441-1045 s pause on the first
  flight. Each was marked "spanned a pause ... not counted", and the climb went on.
- **Beside a neighbour phone** (`phone_margin`, `careful_walk`): the only way to the launch cell
  (209,57) runs along x=209, beside WHEELER-DEALING's phone (208.5,59.5). In rp2 the walker's
  sideways unstick on that stretch answered it, and COP CAR CRUSH then said 1113 ("already on a
  Zaibatsu job"). The skill now first tries a route with a 1-cell margin round neighbour phones. When
  there is none, as here, it walks those cells one at a time. Each aim point is 0.15 off-centre away
  from the phone. The session's `cruise_to` runs in bursts shorter than its no-progress limit, so the
  unstick never fires there. After three passes that do not get through, the plain walker takes over.
  A first version steered with its own pulses. It drifted onto the neighbour phone at the corner in
  rp4 and stalled in rp5, so it was replaced.
- **Re-centred before the answer**: after arriving, he drifted to 209.9,58.2 (rp7). The session's
  `answer` walk then went diagonally to the phone, stuck, and its unstick answered the neighbour
  (1113). A careful step back onto the launch cell now precedes the answer, so the step onto the phone
  is straight (rp8: answered, brief 1681).
- **Repeated-flight guard**: standing on a slope top, the planner could report the same flight as
  climbed 25 times in a second (rp2). Now it steps one cell on.

| session | roof (climb, answer, descent) | job | what ended it |
|---|---|---|---|
| rp1 | clean (654 s pause not counted) | stuck | Cop Car pinned at 210.6,43.5 on the Shady drive, burned |
| rp2 | climbed; the unstick answered WHEELER-DEALING | phone: 1113 | fixed (careful walk) |
| rp3 | clean, careful walk 3 cells | stuck | Cop Car burned at 146.5,30.9 on the crusher drive |
| rp4 | pulse-steered careful walk onto the neighbour phone | phone not answered | fixed (cruise_to bursts) |
| **rp5** | clean (fallback walker after the pulse walk stalled) | **JOB COMPLETE** (1124, +$20,000, game-second 1263) | `out/rp5/m_ccc_end.png`: chase view, $20,875, "Here's $20,000 for a job well done" |
| rp6 | clean, final careful walk: 3 cells in 4 s | stuck | Cop Car burned on the Shady and crusher drives (respray not reached) |
| rp7 | clean climb and careful walk; drifted before the answer, the answer walk's unstick hit the neighbour | phone: 1113 | fixed (re-centre) |
| rp8 | clean on the final code: re-centred, answered (1681), back on the street at game-second 213 | stuck | Cop Car burned on the Shady and crusher drives (carhp 32000 -> 14714 on the first) |
| ccc3, ccc4, **ccc5** (SKILL-CRUSHER, same runner and skill) | clean (ccc4 with the pause fix and careful walk, ccc5 with the eased walk) | **JOB COMPLETE** x3 | `out/ccc*/m_ccc_crane_crushed.png`, `m_ccc_end.png` |

**The acceptance bar (JOB COMPLETE in 2 of 3 sessions) is not met by this agent's own sessions:
1 of 8 (rp5).** Across all 11 sessions of this runner since the game-clock fix, it is 4 of 11 (ccc3,
ccc4, ccc5, rp5). ccc3-ccc5 were three in a row, but they are SKILL-CRUSHER's sessions, and rp6-rp8
after them all failed. The roof reached the right job in 8 of the 11. The three misses (rp2, rp4,
rp7) are each fixed above, and the final code (rp8) climbed, answered and came down clean. Every
other failure was the Cop Car catching fire on a drive, in `deliver_intact` / `crusher_crane` (other
streams). At `GTA2_SPEED=2` the burning car lost the job in 4 of the 11 (rp1, rp3, rp6, rp8).
Frames, chase view, not in git:
`out/rp*/m_rooftop_terrace.png` (the terrace beside the phone), `out/rp5/m_ccc_end.png` (JOB COMPLETE).

## Wave M, SKILL-GUNFIGHT (9 Nov 2026): WHO'S MAD? complete with the on-foot gunfight skill

`gamerun/skills/gunfight.py` (mirrored in `linux/docker/skills/`) is the `combat_on_foot` skill: armed
men who move, come in cars and shoot back (22 jobs). It was proven on **WHO'S MAD?** (`wil_lm1`,
Loonies, yellow phone 10.5,46.5) by `gamerun/missions/whos_mad.py` and `keys_whos_mad.sh`. The
details, the skill's options and every session are in `docs/skill-gunfight.md`.

- **The yellow phone needs Loonies respect >= 2 bars, and a fresh game has 0.**
  `skills/gang_respect.exe` (source `gang_respect.c`) sets it to 60 in the game's gang table
  (`[0x5EB898]`, 10 x 0x144 bytes, respect byte at +0x11C, read from the HUD's respect bars). This is
  a developer aid, written to the marks of every session. Nothing else in the job is helped.
- **Neighbouring phone.** The machine-gun generator beside the phone (11.5,47.5) answers the DESTROY
  J-LAB! phone next to it (gf_wm1). The runner takes the gun at 41.5,48.5 and approaches the phone from
  the west.
- **The meeting box (128.5,195.5) is in a walled yard.** gf_wm5 fired 270 rounds into its west wall.
  The skill checks its line of fire on the map, and the fight is held on the open plaza south of the
  yard.
- **The three hitmen** show as `gang/zaibatsu` in VTYPEs (model 70), with arrows only while on screen.
  They circle the block, stop when on screen, and get out to shoot.

| session | outcome |
|---|---|
| gf_wm1-6 | refused (J-Lab phone), stopped (selector), arrested (7075), dead (blind walk), dead (wall), 2 of 3 down; each fixed in turn |
| **gf_wm7** | **JOB COMPLETE** (1124, +$40,000): three down in 17 game-s at health 100; `out/gf_wm7/shot_475.png` |
| **gf_wm8** | **JOB COMPLETE**: three down in 8 game-s at health 100; `out/gf_wm8/m_wm_end.png` |
| gf_wm9 | dead: 60 health lost on a walk to the plaza before the fight loop (fixed: the fight starts at brief 1464, bounded steps) |

**2 of 3 consecutive sessions (gf_wm7-9) reached JOB COMPLETE in the chase view**, with no warp.
