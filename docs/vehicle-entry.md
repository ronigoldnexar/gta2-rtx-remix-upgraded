# Getting into and out of a car (ANIM-VEHICLE-ENTRY, 9 Nov 2026)

Objective: entering and exiting vehicles play the complete action in the street views (third person):
door open, body in, settle, and the reverse, with hands and feet on the car, and no disappearing,
teleporting or sliding.

## What the game does, and what was wrong

The game boards a ped in coarse steps (log `GTA2DX9_LOG_FIGURES=1`, `docs/actions-3d.md`): it runs him to
the door (state 3, sprite frames 8-23), backs him 0.15 off it and moves him 0.3 in (state 3 sub 6,
frames 24-35, 0.8 s), then stops drawing him. Leaving, it puts him beside the door already outside the
body (state 4 sub 7, 0.9 s) and slides him 0.3 out in 5 cm steps. Drawn as is (baseline run, shared
stage of 8 Nov):

- getting in, the figure vanished at the sill (0.31 block from the car's centre line, outside a van's
  side) in one frame, while the door was still open;
- getting out, the figure appeared outside a shut door: the door only started to open on that frame,
  and its split (the door cut out of the body) was built on a worker thread, so it opened two frames
  later still; the exit clip faded in from the standing idle (stand, crouch, stand);
- no hand or foot touched the car: the clips are upper-body layers over walking legs.

## What is drawn now (`dll/src/boarding.cpp`, `boarding.h`)

A plan per boarding ped in the car's own frame (`u` across, outward on the door's side; `z` along,
forward; so a moving car carries it), driven by the game's state words and drawn by the renderer:

| t (s) | getting in | getting out |
|---|---|---|
| approach | walking to the door (the game), the hinge-side hand reaches for the handle within 0.3 block; the door stays shut until the hand is on it | - |
| 0.00-0.25 | to the handle (Hermite: leaves with the speed he arrived at) | seated (sunk by the seat height), door hand on the inside handle |
| 0.15-0.50 | door pulled open to 33 deg, the hand on the handle following it, a step back with it | door pushed open to 45 deg (the push lets go past a third open) |
| 0.45-0.85 | lets go; round the door's end into the opening; inner foot over the sill onto the floor | door-side foot over the sill to the road (arc), turning out; the other hand on the door frame |
| 0.85-1.25 | sits (sink by the vehicle's floor height), inner foot into the footwell, other hand on the roof edge (a van: the door frame), outer foot planted then in | rising off the sill onto the game's position (filtered, it moves in steps), second foot down |
| 1.25-2.10 | door hand on the armrest (40 % along the door), leaning out of the doorway for it; pulls it shut (1.45-1.8); figure kept inside the panel | free at 0.86 s once the game's exit state ends, handed back to the renderer with its velocity; the door swings shut on its own |

- **Ghost**: after the game stops drawing him, the renderer keeps drawing the ped from his last sprite
  until the plan ends (door shut, figure seated inside), so nothing vanishes in view. The player's ghost
  keeps his avatar and clothes (it is `ownPed`; the CROWD look and the model choice follow it).
- **Door**: driven by the plan (`BoardingDoor` in `car_bodies.cpp`: side, target, rate). The driven
  car's door splits for both sides are built ahead (`BoardingWarmDoors`), so the exit's door moves on
  its first frame.
- **Contact**: two-bone IK in `model_store` (`ModelSetLimbTarget`, limbs L/R hand, L/R foot, model
  space, pole per limb, the end joint keeps the clip's orientation, part of the pose-cache key). Hands:
  door handle, inside handle, armrest, roof edge / door frame; feet: sill arc, footwell, road. Reach is
  real: arm 0.124 block to the wrist, shoulder 0.34 up, leg 0.208, hip 0.234 (measured on the
  avatars, log `limb ik:`). A **tether** keeps the body within an arm of a held point (eased 0.12 s),
  and a **reach assist** moves the body toward what a hand could not reach last frame
  (`ModelLimbResidual` fed back through `BoardingReportResidual`, at most 6 cm).
- Sizes follow the vehicle: seat at half the half-width, footwell 0.62 / 0.32 of it, the door's inner
  trim `0.12 * halfW + 0.035` inside the footprint (which includes the mirrors), floor
  `clamp(0.18 * roof, 0.035, 0.10)`, sink `0.234 - (floor + 0.10)`.
- Not planned (left to the clips, as before): an exit from a car moving faster than 0.6 block/s (a dive
  is another act), and boarding without a car model that can open a door (the sprite-built bodies).
- `GTA2DX9_BOARDING=0` turns the module off (the previous behaviour).

## Verification

Probe `linux/docker/entry_probe.py` + `keys_entry_probe.sh` (mirrored in `gamerun/`): two rounds of exit
and entry of a parked van, Downtown, 30 fps x11grab bursts. Checker `tools/entry_check.py <log>`:
frame-by-frame drawn position, step, sink, phase, door and hand/foot contact error, and flags POP
(speed change > 0.9 block/s in one frame, or > 0.09 block in one frame), SLIDE (crouch/exit clip at full
weight moving > 0.3 block/s with no plan), GONE (figure no longer drawn), NOREACH (a driven hand or foot
> 0.02 block from its target at full weight). Side view for the frames: `GTA2DX9_BOARDING_CAM=1`
(verification only, off by default: the camera is held beside the door the player is using).

```
CPUSET=60-63 CPUS=3 STAGE=<stage> FPS=0 GTA2_DIRECT_KEYS=1 \
  INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/' \
  gamerun/grun.sh ent_v10 120 keys_entry_probe.sh -e GTA2DX9_SCENE_NO_CAR=1 -e GTA2DX9_LOG_PED_FRAMES=1 \
  -e GTA2DX9_LOG_FIGURES=1 -e GTA2DX9_BOARDING_CAM=1 -e ENTRY_ORBIT=0
python3 tools/entry_check.py out/ent_v10/gta2dx9.log
```

Results, final build (run `out/ent_v10`, 2 exits + 2 entries, all at real speed, no faults):

| | baseline (`out/ent_base`) | now |
|---|---|---|
| pops (checker) | entry: figure gone at the sill outside the van, in one frame; exit: appears beside a shut door | 0 in 4 episodes |
| slides | exit: crouch/upright figure carried by the game's steps | 0 |
| hands at full weight on target | none (no contact) | 85 frames: median 0.002 block, 82 % within 0.02, p95 0.046, max 0.057 |
| feet at full weight on target | none | 256 frames: median 0.000, 95 % within 0.02, max 0.041 |
| avatar | - | one model throughout (`human_male_01`, 181 contact lines) |

Frame-by-frame (30 fps, side camera; sheets `out/ent_v10/deliver/sheet_exit_30fps.png`,
`sheet_enter_30fps.png`, `sheet_enter_30fps_b.png`, clip `vehicle_entry_exit_30fps.mp4`, local):

- Exit (video frame 20 = first frame of the game's exit state): 20-21 door still shown shut (the capture
  lags the plan by a frame or two; the log has the door at 0.10, 0.20 there), no hand through the panel;
  22-25 door open, figure seated in the opening, door-side leg swinging out; 26-31 other hand up on the
  door frame, foot down to the road; 32-37 rising off the sill, second leg over it; 38-40 standing; 41-55
  walking clear. No frame-to-frame jump.
- Entry (sheet frame 0 = video 24): 0-6 walking up, hand reaching the handle; 7-16 hand on the handle,
  door swinging open, stepping back with it; 17-27 round the door into the opening; 28-41 seated
  inside, door open; then (second sheet) the door swings shut over 7 frames with him inside, last seen
  through the closing gap. No frame-to-frame jump; nothing vanishes in view.

## What still looks wrong (honest list)

- The hand on the outside handle trails it by 4-5 cm for about 5 frames while the door swings open
  (the tether is eased so it never yanks the body); the hand grabbing the armrest is 2-5 cm short for
  3 frames; the door-side foot crossing the sill is 2-4 cm off its arc for about 7 frames.
- On the van (high cab floor) he sits with his knees high on the sill for a few frames of the exit:
  reads as "perched". The door-side foot is in the air for a frame or two mid-swing.
- At the end of the exit the feet cross for two frames as the second foot lands.
- The leaving figure does not shut the door: it swings shut by itself after he walks off (the push
  was dropped: a hand holding the open door yanked the body back).
- The hand on a van's door frame reads a little like a wave from behind.
- Only the van was filmed from the side; sedans and trucks use the same plan scaled by the car's size,
  but were not filmed in this pass. First person was not judged (the own figure is hidden).
- Jacking a driver and boarding a moving car are not changed beyond the plan's door and climb (QB-14's
  jack clip is on `camera-modes`, not on this branch).
- The checker's GONE at the end of each entry is the plan ending with the door shut and the figure
  inside the body: verified in the frames, not by a visibility test.
