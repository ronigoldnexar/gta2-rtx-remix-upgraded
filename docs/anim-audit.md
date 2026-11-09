# Animation transition audit (ANIM-BLEND-AUDIT, 9 Nov 2026)

A repeatable QA harness for the street views' figures: it walks the player's figure through every
state transition the renderer draws, records where every key joint is drawn on every frame, and
turns that into numbers (foot skate, pops, teleports, sinking, spins) ranked by how bad and how
often, with frames cut at each defect. Then the worst class it found (locomotion pops) was fixed
and measured again with the same harness.

## 1. The harness

| Piece | What it does |
|---|---|
| `GTA2DX9_LOG_JOINTS=1` (`dll/src/live_geometry.cpp`) | A `figj:` log line per frame for the player's figure and everyone within 1.5 blocks: the posed feet, pelvis, head and hands in the world (the same pose the draw uses: pair, layers, overlay, torso twist, ragdoll), the drawn and game positions, heading, ground height, the state words, the clips and every blend weight. Off by default; costs six `ModelNodeWorld` calls per logged figure. |
| `linux/docker/anim_audit.py` (copy in `gamerun/`) | The scenario, run inside a game container: 16 steps (idle, start/stop, tap, turn 90 and 180 on the spot, walk backwards, run into backwards, a 180 while running, a curve, jump, punch standing and running, a forced hit reaction, a forced knock-down and get-up, get in / out of a parked car, out of a moving car, walking into a car's flank). Each step is filmed as a 30 fps burst (`b_<step>.mp4`) and marked in `marks.txt`. `AUDIT_STEPS` picks steps, `AUDIT_X/Y` the spot, `AUDIT_WARP_EACH=1` warps back before every step (same ground and camera each time). |
| `linux/docker/keys_anim_audit.sh`, `linux/docker/anim_audit_grun.sh` | The keys script and a copy of `gamerun/grun.sh` that renders on `$GTA2_GPU` instead of GPU 0. |
| `tools/anim_audit.py` | The analyser (host side, no PIL needed): per step, per clip and per transition tables, a ranked defect list, `--frames` cuts the worst frame (and +-2 frames) of each top defect and of each of the worst transitions out of the bursts, 2x on the player, into `<run>/audit/sheet.png` and `sheet_transitions.png`; `--json` for scripts. |

Run it (one game slot, about 4 minutes of game):

```
cp -al repo/stage ~/gta2-linux/stage_<you>            # or any private stage with your DLL
CPUSET=50-59 STAGE=$PWD/stage_<you> GTA2_DIRECT_KEYS=1 FPS=0 \
  INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/' \
  gamerun/anim_audit_grun.sh <run> 300 keys_anim_audit.sh -e AUDIT_WARP_EACH=1 \
  -e GTA2DX9_SCENE_NO_CAR=1 -e GTA2DX9_LOG_JOINTS=1 -e GTA2DX9_LOG_FIGURES=1 \
  -e GTA2DX9_LOG_PED_FRAMES=1 -e GTA2DX9_FORCE_ACTION_FILE=audit_force.txt
python3 repo/tools/anim_audit.py out/<run> --frames --json out/<run>/audit.json
```

### What is measured (1 block = 3.80 m: the 0.46-block figure is a 1.75 m adult)

| Measure | Definition | Threshold |
|---|---|---|
| skate | a foot within 2.5 cm of its resting ankle height on two frames running, moving over the ground | 2 cm a frame (the quality bar's FEEL-14) |
| pop | a joint that jumps in one frame in the body's own frame (relative to the drawn root and heading): its move over 8 cm and over 3x the median of its moves in the 8 frames around | 8 cm |
| transition spike | at each change of the leading clip, the largest one-frame joint jump within 3 frames over the median move around it | a clean crossfade stays under 8 cm |
| snap | a joint's jerk (second difference) over 20 cm and 2.5x its surroundings: a harsh but not instant blend | 20 cm |
| teleport | the drawn root moving over 0.10 block (38 cm) in a frame while the game did not jump | 38 cm |
| sink / float | the lower foot 4 cm under its resting height / both feet 15 cm over it for 4+ frames (not lying, not at a car door) | |
| spin | the drawn heading turning faster than 600 deg/s | |
| lag | the drawn root over 0.12 block from the game's position | |

Frames where the game itself moved him more than 0.2 block (three sprint frames' worth) are
warps, respawns or frame hitches: the figure snaps or is pulled along by design; they are counted
and left out of the ranking. Clip names in the tables are the leading clip of the drawn mix
(`a>b`: a leads with b at 30 % or more; `a/b`: a leads clearly; `+x`: the action overlay x).

### Caveats

- All numbers are per game frame (the animation's `dt`), so they hold when the host is slow. The
  bursts are wall-clock video: when the game runs below 30 fps, "-2f / +2f" in the sheets is two
  video frames, not two game frames.
- On 9 Nov the shared host's governor (8-CPU settings on the 96-CPU host, reported on issue #10 by
  QA-REGRESSION) pinned game containers to CPUs 0-7 and paused them under load: the game ran at
  2-15 fps and had frame hitches (the game moving him 0.4 block in a frame). The hitch filter
  above exists for that. Pass `CPUSET=` a free range of your own.
- Key presses are wall-clock, so a slow game covers less ground per step: compare runs by the
  per-clip and per-transition tables, not by step rows.
- Collisions with cars and walls (a hand or foot inside a body) are not measured; the
  `bump_car` step only films it.

## 2. What it found (run `aa3`, before the fix: the shared animation code of `16fcaf8` + QB-20)

Ranked by the analyser's score (weight x worst/threshold x (1 + ln count)); "P" is the player.
Frames: `out/aa3/audit/sheet.png`, `out/aa3/audit/sheet_transitions.png` (local, not in git);
the first audit run `aa1` found the same list on a busier spot.

| # | Defect | Where (transition) | Worst | Count | Mechanism | Owner |
|---|---|---|---|---|---|---|
| 1 | Foot skate through every run start | `idle -> run_start`, `walk_start -> run_start` | 21.7 cm/frame | 35 frames | The game is at sprint pace within ~6 frames; the mocap start was played at most 2x its own pace, so the planted feet slid behind the body. | locomotion (fixed below) |
| 2 | A forward start played while walking backwards | `backstep`: `idle -> run_start` with the body moving back | 25.2 cm/frame | 8 | The start fired on any motion, backwards included; its clip ran in real time while he backed away. | locomotion (fixed below) |
| 3 | Pop into a stop | `walk -> run_stop`, `run -> run_stop`, `walk -> walk_stop` | 50.4 cm (right foot) | 8 + 8 + 6 | The stop clip went to full weight on its first frame (phase-matched, but a sprint pose is not a stop pose). | locomotion (fixed below) |
| 4 | Pops when a start/stop/fidget is cut short | `walk_stop -> walk`, `walk_stop -> walk_start`, `run_stop -> walk_start`, `idle -> fidget` | 31-55 cm | 2-6 each | Interrupted (he moved, stopped, turned or acted) the transition clip's weight fell from ~1 to 0 in one frame. | locomotion (fixed below) |
| 5 | Pop in the walk/run/sprint blend | `walk -> run>run_fast`, `run -> walk`, `walk -> run` | 33-52 cm (hands) | 12 | Four clips (idle, walk, run, sprint) drawn as a pair: the walk vanished the frame the sprint weight became non-zero; the idle fade swapped walk for run at runW 0.5; the turn step vanished when he moved. | locomotion (fixed below) |
| 6 | Knock-down slides | forced `fall` (action 4) | 20.8 cm/frame | 17 | The lying clip's own root motion over the ground while the drawn root holds still (forced showcase; the real knock-down has the QB-27 ragdoll). | ped animation / ragdoll |
| 7 | Aim and punch overlays snap in | `idle -> idle+aim`, `run_fast -> run_fast+aim`, `idle -> idle+punch` | 50-54 cm (hands) | 1-3 each | The action layer fades in over 0.05 s (a frame and a half) by design ("a punch, a blow, a shot are quick"); the arm crosses half a metre in one frame. | ANIM-COMBAT / ANIM-WEAPONS |
| 8 | Hit reaction snaps in | `idle -> idle+hit_head` | 35.8 cm | 1-6 | Same 0.05 s fade-in for the hit layer. | ANIM-COMBAT |
| 9 | Exit from a moving car: the crouch carried at car speed | `run+exit_car` (aa1) | 57.5 cm/frame | 2 | The out clip held while the game carries him with the car (quality bar row 1). | ANIM-VEHICLE-ENTRY |
| 10 | Get-in / get-out pops | `walk -> walk>run+enter_car`, `walk+exit_car` | 24-33 cm | 5-11 | The door clips cut in over the walk. | ANIM-VEHICLE-ENTRY |
| 11 | Stops slide a little | `run_stop`, `walk_stop` | 8.3 cm/frame (mean 2.1) | 171 frames | The game stops him at once; the stop's remaining steps cover ground the figure does not (QB-20 noted it). | locomotion |
| 12 | Turning on the spot | `turn_step` | 4.6 cm/frame | few | The foot-step layer under the eased yaw (QB-21): small slide, no turntable spin over 241 deg/s. | locomotion |

Not found: no teleports of the drawn root outside warps and hitches, no sinking through the
ground, no floating, no spins over 600 deg/s outside warps (the drawn yaw is capped at 241 deg/s).

## 3. The fix (rows 1-5): one continuous locomotion mix

`dll/src/model_store.*`: `ModelSetLayers(model, clips, times, weights, n)`, up to six more clips
blended over the pair (each over a copy of the pose so far, by its own weight, before the action
overlay), bound to one model and part of the pose-cache key.

`dll/src/live_geometry.cpp` (`DrawPedFigures`), every weight continuous:

- the moving cycle: walk -> run by runW, the sprint over it by sprintW x runW; the idle over that by
  1 - walkW; the turn step over the idle by turnW;
- the start, stop or fidget over all of it: a start comes out of the mix over its first 0.2 s, a
  stop goes into its clip over its first 0.25 s (real time), a start hands back to the cycle over
  its last 0.25 s of real time;
- a start, stop or fidget cut short fades out from the pose it stopped at over 0.25 s;
- walkW is a linear 0.2 s ramp drawn through a smoothstep (it was an exponential ease whose first
  frame took a third of the change);
- a start fires only on forward motion (walking backwards is the cycle played backwards) and is cut
  if he moves back;
- a start's clip follows the ground he covers up to four times its pace (was twice).

### Measured (run `aa4`, same scenario, same spot, same settings as `aa3`)

Locomotion only (no action overlay, not at a car door); `aa4` and `aa5` were intermediate builds
(`aa5` tried a start played at up to 4x its pace: start skate rose from 6.2 to 18.0 cm a frame, so
that change was dropped).

| Measure (player, locomotion) | `aa3` before | `aa6` after |
|---|---|---|
| Transitions with a one-frame joint jump of 20 cm or more | 49 of 151 (32 %) | 4 of 117 (3 %) |
| Transitions with 30 cm or more | 6 | 2 |
| Mean / worst transition spike | 14.7 / 49.6 cm | 7.7 / 30.2 cm |
| Frames with a planted foot sliding over 2 cm | 10.5 % | 5.4 % |
| Foot skate in the start clips, mean | 6.2 cm a frame | 5.4 cm a frame |
| Faults in the log | 0 | 0 |

| Transition (n, mean / worst spike cm) | `aa3` before | `aa6` after |
|---|---|---|
| walk -> run_stop | 9, 29.7 / 49.6 | 5, 11.0 / 19.0 |
| run -> walk | 14, 26.2 / 49.6 | 17, 7.9 / 13.8 |
| run -> run_stop | 8, 25.5 / 47.5 | (now led by the walk: above) |
| walk -> walk_stop | 6, 17.9 / 23.8 | 12, 8.5 / 17.2 |
| walk_stop -> walk (stop cut short) | 6, 20.1 / 21.4 | none over 8 cm |
| walk_stop -> walk_start, run_stop -> walk_start | 3, up to 23.9 | none over 8 cm |
| walk_start -> run_start | 8, 18.8 / 23.9 | gone (one start) |
| run -> run_fast | 14, 12.5 / 20.8 | 3, 5.8 / 7.5 |
| walk -> run | 6, 20.7 / 22.2 | 9, 12.1 / 20.9 |
| idle -> walk (backwards: was a forward start) | - | 7, 13.1 / 15.6 |
| run_start -> run_fast | - | 5, 18.4 / 30.2 |
| run_fast -> run | 14, 7.6 / 16.5 | 7, 12.4 / 30.2 |
| walking backwards, foot skate p95 (step `backstep`) | 24.7 cm a frame | 14.5 cm a frame (`aa5`) |

Frames: before `out/aa3/audit/sheet_transitions.png`, after `out/aa6/audit/sheet_transitions.png`
(2x crops on the player, -2 / event / +2 video frames). Stills confirm the poses stay whole through
every layered blend (no bind pose, no broken limb from a clip with partial channels such as
`turn_step`); the smoothness itself is what the per-frame numbers above measure.

## 4. What still looks wrong

Ranked, most visible first:

1. **Sprint hand-overs still jump 30 cm once in a while** (`run_start -> run_fast`, `run_fast -> run`,
   5-7 transitions, mean 12-18 cm). The sprint clip enters through sprintW x runW, both eased
   over 0.2 s exponentially (first frame 17 % of the change): a linear ramp like walkW's would
   halve it. Not done for lack of a run to verify it.
2. **The stop settle snaps the cycle** (`run -> run_fast` 51.8 cm in `aa5`, f 3577): when the game
   stops him the cycle runs on to the next passing phase (`settleTo`) faster than the clip, with no
   weight change. Locomotion; untouched.
3. **Starts still slide** (mean 5.4 cm a frame through `run_start`, worst ~20): GTA2 puts him at
   sprint pace within six frames and the mocap start takes a second to get there. Playing it
   faster made it worse (`aa5`). Options: enter the start at the frame whose pace matches his, or a
   short authored push-off clip.
4. **Walking backwards slides** (14.5 cm a frame p95): the run clip played backwards at 1.9 blocks
   a second; its stride does not fit a back-pedal. Needs a back-pedal clip.
5. **Action layers snap in** (aim, punch, hit: 35-54 cm in one frame at 0.05 s fade-in): owned by
   ANIM-COMBAT / ANIM-WEAPONS; the analyser's `+aim`, `+punch`, `+hit_head` rows measure them.
6. **Car door clips** (exit from a moving car carried at car speed, 57 cm a frame; get-in pops
   24-33 cm): ANIM-VEHICLE-ENTRY.
7. **Forced knock-down slides** (the lying clip's root motion, 20 cm a frame) and its get-up
   (`fall -> idle`, 27-29 cm): only in the forced showcase; the real knock-down runs the QB-27
   ragdoll. Not re-measured with a real knock-down.
8. **Crossfades between far-apart poses** (a fidget with a raised hand into a sprint: 0.25 s,
   20 cm a frame) read as quick but continuous; inertial blending would soften them further.

Not verified: other avatars than the player's (the NPC series is logged within 1.5 blocks:
`--npc`), Remix, first person, the frame cost of the layers (one extra clip sample per layer per
posed figure; the pose cache keys on them, weights in eighths). The chase camera lost the player in
some steps after the warp (quality-bar row 2), so a few frame strips show the street, not him; the
numbers do not depend on the camera.
