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
