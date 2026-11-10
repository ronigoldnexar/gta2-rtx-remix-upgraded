# Getting into and out of a car (ANIM-VEHICLE-ENTRY, 9 Nov 2026)

The first pass (ANIM-VEHICLE-ENTRY, below) was built on `night-skills-2026-11-09` and reached
`camera-modes` with MERGE-RECONCILE-3 (`3ab8cfe`). ANIM-ENTRY-EXIT finished the act on top of it; see the
last section, "ANIM-ENTRY-EXIT: on camera-modes, the door shut after an exit, clean doors".

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

## ANIM-ENTRY-EXIT: on camera-modes, the door shut after an exit, clean doors (9 Nov 2026)

The module was first ported by hand onto `camera-modes` `c8c3dd8` (before MERGE-RECONCILE-3) and run
there (baseline `aee_base1`: 0 pops in 4 episodes, as on night-skills). From 30 fps frames of a van (068)
and a 1950s sedan (013 Minx) seen from behind the door, ahead of it and from the player's chase camera:

| Seen | Cause | Now |
|---|---|---|
| Long black shards hang from the open door to the road and sweep through the figure (on the Minx across his face) | `BuildDoorSplit` takes a triangle into the door by its centroid; the image-to-3D shells' long thin triangles reach the sill, the wheel arch or the road | those triangles stay in the door with their outlying corners pulled onto the door's box (1.5 cm margin, in the car's frame). A first try left them on the body: no shards, but the Minx door (150 -> 106 triangles) had holes and his arm showed through them (`aee_i2front`). Defect `door-split-black-shards-below-open-door` |
| **The whole car vanished for ~15 frames as he walked up to it**, back with the door already open (camera-modes `ceb9ff9` only) | since PERF-4 (car artwork on a worker) the game's door-animation sprite, a new texture every frame, is often not ready or not measurable when first drawn, and `CarBodiesDraw` skipped the car; the plan then lost its car too and the figure vanished at the sill | each car object's last measured body stands in for up to 3 s (`g_lastBuilt`, cleared with the cache); log `its last measured body stands in`. Defect `car-vanishes-during-door-animation` |
| His forearm through the closing door's outer face as he pulls it shut (front view) | the elbow was bent out to the hand's side, i.e. through the door | hands that hold the door from inside bend the elbow in and down, into the cab |
| The door left open after an exit, swinging shut on its own after he walks off | the previous pass dropped the hold (a hand on the open door yanked him back) | **`kShut`** phase: he stands clear of the door's swing, turns a quarter toward the car's front, the hand on the door's side takes its rear edge at handle height and shoves (door at 1.5/s while held, 0.6-1.6 cm contact on the van), lets go once it swings out of reach, the door carries on at 2.2/s to shut; then he steps back onto the game's spot (0.35 s). Position and legs stay the renderer's follow plus an eased offset, so the legs step it. If the game walks him off, everything lets go (0.12 s) |
| His chest, then his face, pass through the open door's rear edge as he rises and as it shuts | the game puts him 0.21 block from the hinge of a 0.25 door: inside its swing | the exit ends at a clear spot (`ClearSpot`: 6 cm outside the hull, 7 cm behind the open door's rear edge, at most 0.09 off the game's spot), moving back along the car before moving out; the shut starts from the same spot (no jump) |
| Turning squarely to the door edge was a 150 degree turn and back; the turning legs read as a walk round the door | | a quarter turn (half way from facing out to facing the car's front) |
| The far hand on the van's door frame above his head (a wave) | grip at 0.34 while still seated | at chest height (0.29 less half the sink), on the rear pillar |
| His hand and forearm through the door's outer face as it starts to open (Minx) | the inside-handle target 6 cm inside the footprint (which takes in the mirrors) is outside a rounded body's skin | hands on the door's inside 2.5 cm deeper (`HandInside`) |
| Getting in, the door's rear edge swept through his chest as he pulled it, and he stepped into the opening through the door's end | the step back with the door was 4.5/5 cm; the path into the opening was a straight line across the 33 degree door's end (the wedge's mouth is ~12 cm) | a bigger step back (6/7 cm) and a curve through the middle of the wedge between door and body |
| A runner reaching the door popped (speed 1.8 -> 1.0 block/s in a frame, 013) | the climb's entry curve capped the incoming speed at 1 block/s | cap 1.8 block/s |
| Hand on the Minx's roof edge floated over its rounded crown | grip at 0.98 of the roof height | 0.93 |

**Carjacking (QB-14, camera-modes only).** The plan now knows a jack (`BoardingIn::jacking`): `jack_pull`
keeps its own timing (the plan no longer overwrites the clip time), the door opens to 45 degrees, the
roof-edge hand is left to the clip (both hands go into the doorway), and the climb waits at the open
door (at most 1.5 s) until the driver is seen thrown out, so the jacker never steps into the opening
through him. Code path only: no jack was filmed in this pass.

**Jack and seat pass (FIX-JACK-SEAT, 9 Nov; feel14, feel13, feel7, pm19).** What the game does (logs of
`feel14_jack`, `pl13_drv`, `js_fix*`): the jacker stands at the door in state 3 sub 6 until the driver is
thrown (state 8 sub 0x11), then climbs in (frames 32-35) and is seated (state 10, his sprite gone). That
hold is the game's own and frame-locked: 1-2 s at 30 fps, 4-10 s in the scripted runs, where the game ran at
6-10 fps during jacks (the sprites pass jumps from ~5 to 30-70 ms, a stall sampler shows the game thread
waiting in wined3d; a performance item, not fixed here). feel14's "never seated" was the probe: `pl13_drive.py`
presses Return the moment it finds itself driving.
- **The hold follows the game** (`boarding.cpp`): the plan waits at the yanked-open door for as long as the
  game keeps him there (driver not yet out, frames < 32, still drawn; 10 s cap), not 1.5 s; with the cap the
  figure sat down in a seat the driver still filled. Meanwhile `jack_pull` tugs (0.95 -> 1.12 -> 0.95, 0.7 s,
  from 0.4 s into the hold) instead of one frozen grip.
- **Catch-up once he is in** (feel13): the first frame the game stops drawing him (the boarding ghost), the
  rest of the climb, the sit and the door pull run at the rate that finishes them in 0.6 s (0.4 s on the move;
  `BoardingOut::rate`, also applied to `jack_pull`). Before, the plan's own 2.1 s left a standing figure
  carried beside a car the game already drove, door open. The climb's ghost starts at t 0.1 (was 0.3).
- **The door on the side he boards**: the approach takes his side from the game's position every frame (the
  game walks him round the back of a truck to the street-side door); car_bodies shuts a door open on the other
  side before opening the boarding's (a kerb-side door, opened by the proximity rule as he came, stayed open
  through the drive-off); the player's own car opens no door for a passer-by matched only by proximity.
- **The victim's way out** (feel7, `BoardingJackVictim`): from his seat (sunk) over the sill at the door
  frame's rear, back along the body between it and the jacker, to 0.14 out and 0.28 behind the open door's
  edge (0-0.55 s), then onto the game's spot by 0.9 s, playing `jacked` throughout.
- **Seated from the start** (pm19): a level that starts him at the wheel (ste) never showed him on foot, so
  nothing was seated; a passer-by's quad without texture stands in (his look is `IdentityForPlayer`). An
  open-top body (`CabOpenTop`, `BoardingPublishOpenTop`) seats him on the cushion (`SitSink`), not sunk to
  clear a roof (head below the seat backs: an empty-looking roadster).
- Probe: `gamerun/js_jack.py` / `keys_js_jack.sh` (JS_JACKS, JS_VMAX, JS_NEAR, JS_WAIT, JS_PARKED; films each
  jack until seated + drive-off + exit; never exits on finding itself driving), `keys_js_pm19.sh` (ste).

**Authored bodies name their seat (VEHICLE-ART-4, 9 Nov; playfeel1).** The seat above comes from the game's
sprite (the CARI window rows, half the half width). That fits the image-to-3D bodies, made from the sprite, but
not an authored carkit body with its own cockpit: in the 036 Schmidt (a tandem bubble car, a central seat under a
0.28-block canopy) the sprite's seat was the rear deck, 0.09 to the side, and the 0.14 sink cap left the hero
standing through the canopy for the whole drive. Now:
- `manifest.json` carries `"driver_seat": [x, y, z, roof]` for the six authored bodies (013, 063, 068, 008, 036,
  056), model frame in blocks: the hip's distance from the centre line, the cushion's top, the hip along the car
  (12 cm ahead of the seat back), the headliner over it. `tools/vehicle_art/seat_anchor.py <models dir> [--write
  <manifest>]` reads the seats off the generators and casts a ray up through the `.mesh` for the headliner; add a
  row there for every new authored body. The model store logs `models: <name>: driver's seat ...`.
- `car_bodies.cpp` passes it through the same fit as the mesh (`BoardingPublishSeat`; log `car bodies: driver's seat
  of <name> (manifest)` beside the sprite's guess). `boarding.cpp` then seats the hips on the cushion (a truck cab's
  0.40 up: a negative sink lifts him), lowered only as far as the head (0.236 over the hips) needs to stay 1.5 cm
  under the headliner, at most 0.22: the hero (0.46-0.47) is tall for the 5 m-a-block cars, so in the 036 his hips
  go 0.09 under the cushion, hidden by the tub. The floor and pedals sit 0.09 under the cushion; the exit rises
  from the drive's seat height instead of popping to the climb's.
- Verified with `gamerun/va4_seats.py` / `keys_va4_seats.sh` (one car, `force_car_model` and `force_own_car_model`
  cycled live through the bodies, third person still, turning and side shots, first person) and
  `va4_enter.py` (enter, drive, exit bursts at a warp spot). Bodies without the entry keep the sprite's seat.

**The open door's inside (VEHICLE-ART-4, 9 Nov; feel19).** An authored body's cabin liner (normals into the
cabin, near-black interior texture) lies in the door's box, so `BuildDoorSplit` swung it out with the door: from
behind, the open door was a flat black slab (068 van: 188 liner triangles a side). Faces in the box whose vertex
normals point into the cabin now go with neither piece while the door is open (log `car bodies: door of <name>,
side <s>: N cabin-liner triangles left out`): the door shows its own skin from inside (the inner copy, painted and
lit as the panel), the opening the cabin behind it. By vertex normals, not winding, so an image-to-3D shell's
faces wound either way stay. Still open: the door's rear edge is the clip outline (saw-toothed on the 068's ribbed
side), and the inside of a door is the outer paint, not a trim panel.

**Verification aids.** `GTA2DX9_BOARDING_CAM=2` holds the camera ahead of the door (front quarter: the
door's swing and the figure behind it are both seen); both cameras now stay through the shut. Probe
`linux/docker/aee_probe.py` + `keys_aee_probe.sh` (mirrored in `gamerun/`) = `entry_probe.py` plus
`ENTRY_XY` (the warp point: 164.5,147.6 the 068 van, 120.5,152.5 the 013 Minx) and `ENTRY_PAUSE`
(seconds to stand still after the exit, so the shut is filmed). `tools/entry_check.py` lists 60 frames
after an exit (the shut).

```
GTA2_GPU=5 CPUSET=50-59 CPUS=3 STAGE=<stage> FPS=0 GTA2_DIRECT_KEYS=1 \
  INI_SED='s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/' \
  gamerun/entry_grun.sh <run> 130 keys_aee_probe.sh -e GTA2DX9_SCENE_NO_CAR=1 -e GTA2DX9_LOG_PED_FRAMES=1 \
  -e GTA2DX9_LOG_FIGURES=1 -e GTA2DX9_BOARDING_CAM=2 -e ENTRY_ORBIT=0 -e ENTRY_PAUSE=2 -e ENTRY_XY=120.5,152.5
python3 tools/entry_check.py out/<run>/gta2dx9.log
```

**Results, final build** (camera-modes `ceb9ff9` + this change; runs `aee_l1van` behind the door,
`aee_l2front` ahead of it, `aee_l3rear` behind it, `aee_l4chase` the player's chase camera; L4, private
stage; 8 entries and 8 exits at real speed, 0 faults): **0 pops, 0 slides, 0 GONE** in 16 episodes (the
first port, before these fixes, had 1 pop: the runner; this base before the stand-in, 4-6 pops and 10-15
slides per run where the car and the plan vanished). Hands at full weight on target: 369 frames, median
0.000 block, 80 % within 2 cm, p95 0.043, max 0.053; feet: 1026 frames, median 0.000, 97 % within 2 cm,
p95 0.016, max 0.039. The car is drawn, in its own colour, on every frame of every door animation (30
stand-in frames logged). Sheets and clip (local, not in git): `~/gta2-linux/deliverables/anim_entry_exit/`
(`exit_sedan_front_30fps.png`, `enter_sedan_rear_30fps.png`, `entry_exit_30fps.mp4`, 22 s).

Frame by frame (30 fps, video frame numbers of the bursts):

- **Exit**, Minx, ahead of the door (`aee_l2front/b_exit_0.mp4`): 18-20 the chase view, 21 the
  verification camera cuts in (not the act); 21-34 the door swings open toward this camera and covers
  him as the door-side leg goes over the sill and down to the road (feet seen under the door from 29);
  35-40 he rises behind the door's rear edge (that edge, saw-toothed where the door is cut from the
  shell, is between the camera and him); 41-45 standing clear of it, the quarter turn; 46-57 the near hand
  shoves the door's edge and lets go, the door swings shut, shut at 58; 58-77 small steps back onto his
  spot, idle. No jump between frames.
- **Entry**, Minx, behind the door (`aee_l3rear/b_enter_0.mp4`): 24-33 running up and slowing, the near
  hand going to the handle; 34-39 hand on the handle, the door swings open; 40-53 a step back with it,
  then into the opening through the wedge, ducking, the far hand to the roof edge, the inner foot over
  the sill (the door's cut edge between this outside camera and him at 48-53 is occlusion: the trace has
  him inside the door line); 54-63 seated, the outer leg in, the door open; 64-73 the hand on the
  armrest pulls it shut; 74 on: shut, nothing outside it. No jump between frames, nothing vanishes in view.
- **Entry**, Minx, ahead of the door (`aee_l2front/b_enter_0.mp4`): 30-45 running up along the car toward
  the camera, reaching; 44-46 the door starts to swing toward the camera; 46-55 into the opening, ducking
  under the roof; 56-63 seated behind the open door (nothing of him through it); 64-77 the door shuts.

**PLAYTEST-FEEL acceptance** (`keys_feel_probe2.sh`, `FEEL_SEGS=enter,exit`, run `aee_feel1`; the parent
`d933eaf` on the same probe: `aee_feel0`): in the exit burst the door swings out (f14-23), he comes out of
the seat at door height (f27-31, never at roof height), stands beside it, shoves it shut (f44-46, shut at
f50) and nothing is left on the ground (to f98). Frame times on the same probe, this change against its
parent: sprites 5.82 vs 6.00 ms, game 2.66 vs 2.72 ms (no cost); 0 faults in both. The seated driver seen
through the windows while driving is a separate order, not done here.

**Still not right (honest list).**
- Hands: the outside handle trails the swinging door by 4-5 cm for ~5 frames (the eased tether), the
  armrest grab is 2-5 cm short for ~3 frames, the van's shove 2.6-3.6 cm short for 5 frames (the edge at
  the arm's limit after the step back). Feet over the sill 2-4 cm off their arc for ~6 frames.
- The van's high cab floor: knees high on the sill for a few frames of the exit, feet in the air for one
  or two (the dark cab hides the floor they rest on).
- Two frames of hairline seams along the door's top edge as it shuts over him (light through the cut),
  and the door's outline is saw-toothed where it is cut out of the one-piece shell (seen when the open
  door's rear edge is in front of him).
- The door-animation fix holds the body measured before the door moved: a car dented or resprayed
  while its door is busy shows it once the door is idle (within ~1 s).
- With the door at 33 degrees the way into a narrow car is tight: the figure passes within about a
  centimetre of the door line; from outside, the door covers him (as it would).
- Not filmed: a jack (code path above), a passenger, trucks and buses (the plan scales with the car,
  `063_truck_cab` and `069_u_jerk_truck` doors were split in the runs but not entered), first person
  (the own figure is hidden).

## FIX-SEATED: the driver drawn at the wheel for the whole drive (9 Nov 2026)

Defect `feel-driver-not-drawn-seated-in-car` (board item 2b): in third person every drive showed an empty
cockpit. ANIM-ENTRY-EXIT (47c8641) drew the figure as a "ghost" of his last sprite only until the door shut
behind him (`BoardingWantsGhost`: `kClimb` until `t > 2.1`, then `ended`); after that the game draws no
sprite for a ped in a car, so nothing was drawn. Three more things kept him out of sight once that was fixed:

- **The game reuses his sprite object.** About a second after he sits down, the player's sprite object is
  handed to a passer-by walking elsewhere (`seatp_fix7`: "player sprite" in state 0, 20 blocks away). A
  seat keyed by that object was reset by the stranger. The seated figure now has a key of its own: the
  object with its low bit set (never a real object; the same `>> 4` seed, so the same look and build).
- **The player's name goes while he drives** (`g_playerObject` is null in a car), and a scene warp or a
  mission start puts him at the wheel with no boarding at all. The renderer keeps his last sprite on foot
  and seats him in the car marked `driven` (`BoardingSeat`), and moves him there if a boarding guessed the
  car parked beside his.
- **The car models are sealed hulls with painted windows.** A seated figure in a closed car could not be
  seen. A closed car with someone seated in it, seen from outside, is now drawn with clip planes in its own
  frame. Everything is opaque except the glasshouse: from 0.60 to 0.90 of the roof height, between the
  windscreen's foot and the rear window (the game's own window rows, `measure.cabinFront/Rear`). That band
  is drawn at 40 % with no depth write, so the figure drawn after the cars shows through it. Open tops
  (`CabOpenTop`) need none. Not under Remix, which ignores clip planes (there the hull stays sealed).
  `[devtools] driver_glass=0` turns it off.

The pose (`boarding.cpp`, mode `kSeated`): hips on the seat (`SeatU`, `SeatZ`), facing the nose, sunk to
`DriveSink` (his head 2.5 cm under the roof's inside, at most 0.14 sink). Both hands go by IK to the wheel's
rim at ten to two: hub 0.085 ahead of the hips and 0.06 under the shoulder, rim 0.032, raked 25 degrees.
The rim turns with the front wheels (`BoardingPublishSteer`, 3:1, at most 100 degrees). The feet go to the
pedals (0.17 ahead) and the head turns into the turn. The enter_car fold eases to 15 % (upright against the
seat back) and the legs never step (the renderer's ground-driven cycle is zeroed while seated). From the
climb's end everything eases in over 0.5 s.

**Hidden in first person** (`g_hiddenObjects[1]`, the car he is in, hidden from his eyes); the cab
(`cab_interior.cpp`) is the view there.

**Let go** when his own sprite comes back. For anyone, that is any pedestrian the game draws getting out
(state 4) or thrown (state 8, a jack) within 0.7 block of the seat; the game may give him a new object for
the exit, and in `seatp_fix9` the old rule left two figures for 2.5 s. The seat is also let go when the
game no longer has him in a vehicle, or when the car is not drawn for 6 frames (first person draws the own
car as a hood copy; the seat comes back from `BoardingSeat` when the chase view returns).

**Verified** (private stage at this commit, 30 fps bursts, `gamerun/seat_probe.py`: the parked Minx at
120.5,152.5, boarding by F9 + Return, parked orbit, drive with turns, first person, exit; and the
PLAYTEST-FEEL probe, `FEEL_SEGS=enter,drive`). The runs on the base stage (HEAD d2bbf01) are `seatp_base1`,
`seat_base1` and `seato_base5`; the fix runs are `seatp_fix10`, `seato_fix10` (`force_car_model=53`, the
open-top roadster) and `seat_fix10`. All have 0 faults.
- Minx, parked, camera orbiting to the side: before, an opaque pale window band with nobody in it; after,
  head, shoulders and an upright torso through the side glass, facing forward (`seatp_fix8` b_parked_orbit 6.5 s).
- Minx drive with turns: seated for the whole drive. In the turns he is seen through the side windows and
  never lags the car. From straight behind only the top of his head shows over the low rear window.
- Roadster: seated in the left (driver's) seat, upright, arms forward to the wheel, solid body. Exit: the
  door opens, he climbs out, and the seat behind him is empty from the exit's first frame.
- Van 068 (feel probe `drive_third`): the windowless rear doors stay opaque, and in the turn he shows
  through the side windows. Before, the van was opaque all round.
- First person: only the cab, no own figure in view.
- Classic view: `tools/vreg/vreg.sh stage` gives the same verdicts on the base and fix stages (29 PASS;
  the bank_chase WARN and raised_w03_high FAIL are on HEAD as well). Diffed byte by byte, `vr_spawn_classic`
  matches except for one randomly coloured game sprite and the animated HUD icon (run-to-run game
  randomness).

**Untested / not right yet.** A jack (the code lets go on a thrown ped at the seat; not filmed).
Passengers (an NPC who boards by the far door sits on that side; not filmed). NPC drivers seen getting in
are seated by the same path (`seat_fix10`: one NPC seated, let go when his car left the view), but traffic
drivers the player never saw get in are still not drawn (no sprite to draw them from). Hands at the wheel
are only checked in the IK contact trace (0.000 error) and through glass; the models' own wheels are not
where `kWheelAhead` puts the rim. When the game stops drawing him 1 frame into the climb (before the ghost
starts at 0.3 s), he appears seated without the climb (pre-existing). Pillars inside the glass band are
40 % translucent too. Remix: no glass band.

## FIX-SEAT-ENTRY-3: the door cut along its outline, a cabin behind it (10 Nov 2026)

pfl16 (every walk-up van entry in third person): the opening door showed a flat black strip with a row
of teeth down its rear edge and along the roof line. Per-frame log (`GTA2DX9_LOG_DOOR=1`: one `door:`
line per frame a door moves: open fraction, target, split ready, sprite art present) showed the
sprite's door art present and the split ready on every frame, so not missing artwork. The teeth were
the split: `BuildDoorSplit` gave the door the clipped part of a side triangle that crosses the door's
outline but left the body that triangle whole, so the hole the swung door left ended in the hull's
triangle edges, with the cabin's near-black liner behind. A second, finer row ran along the door's top
where the roof shoulder's faces were below the 'lateral' normal threshold.

- `door_exact_cut` ([devtools], default 1, live): every outward-facing face crossing the door box is
  cut along it: the inside part goes to the door, the outside part (as convex pieces, one per box
  plane) to the body; a liner's inside part goes to neither. 0 is the old split. The cache key holds the flag.
- `door_interior` ([devtools], default 1, live): behind an open door a dim cabin box (the door's height
  and length, inward-seen walls only, `DrawBandInterior`) and on its far wall the door's own panel,
  mirrored and dimmed, in the body's own textures (no new art, no Remix prim).
- Probe: `gamerun/keys_fse3_door.sh` + `fse3_door_probe.py`: regress camera at fixed poses beside the
  wil van (F9 to its door), `force_car_door` opened per config in `FSE_CFGS` (`door_exact_cut,door_interior`),
  30 fps bursts. Same-session A/B in one run.
- Still short: a 1-2 px dark fringe on the door's top edge (the roof ribs' texture ends on the panel);
  the hero running along the van side before the door opens can still overlap the panel (the game walks
  him on the sprite outline): requested from the boarding plan's owner, not changed here.

## FIX-SEAT-ENTRY-3: the driven car's shadow eased (feel29, 10 Nov 2026)

The driven van's body went lit to shaded (36-44 % luma) in two frames beside walls while the road held.
Live pass toggles in one session (`gamerun/fx3_van.py`): shadows=0 removed every event (max 9 %), AO,
lights and hemisphere did not. The sun-shadow mask is exact per pixel and per frame, and the chase car
sits in the middle of the view: a building's shadow edge over its rear or a turn against a grazing sun
flips the whole face. Now `car_bodies` marks the driven car's pixels in stencil (bit 0x80, the post
target's INTZ stencil, cleared each frame), and after the mask pass `post_fx` keeps a mask history:
off the car it is this frame's mask; on the car it moves 20 % a frame toward it (about 10 frames to
settle). `[visuals] car_shadow_blend=0` (live) is the exact mask for A/B. Plain renderer only (Remix
does its own shadows). Other cars keep the exact mask (they move across the screen; a history would ghost).

## FIX-SEAT-ENTRY-4: the door's top under the roof lip, a readable cabin (pfl18, 10 Nov 2026)

pfl18 (first person, every walk-up van entry and exit): after c0bb1e8 the door's sides were straight,
but from the eye beside the van the swung door's top edge and the hole's top were two complementary rows
of teeth (frames: fixed close pose, regress camera at the wil van's door). Measured offline from the
068 mesh (side faces turned out, in the door's length, area per height band): the side wall's skin runs
evenly to exactly 0.95 of the roof, then a lip (1.7x a band's area) and the corrugated roof's rib end
caps. The door box's top plane sat at 0.95 of the roof plus the 1.5 cm margin (about 2.7 % of the van's
height): the caps in that margin went with the door.

- `door_top_cut` ([devtools], default 1, live; the split cache keys on it): `BuildDoorSplit` measures the
  side wall's area per height band and walks up from 0.6 of the roof while each band carries 60-140 % of
  the wall's median share; where that run reaches 0.90-0.95 of the roof, the box ends at the wall's top
  with no margin (log: `door of <model>, side <s>: top at the side wall's top`). A body whose wall ends
  lower (a curved shoulder) keeps the old box. 0 is FIX-SEAT-ENTRY-3's box.
- The dim cabin behind an open door is lighter by day (it is unlit: the night keeps the dark tone);
  `door_interior=2` is the old tone for A/B.
- `GTA2DX9_LOG_SEAT=1`: a per-frame `seat gate:` line for the driven/own car (eye inside the box, own
  flag, the eye in the car's frame, view), for the first-person cab gate.
- Probes: `gamerun/keys_fse4_door.sh` + `fse4_door_probe.py` (the fse3 fixed-camera probe toggling
  `door_top_cut`), `gamerun/keys_fse4_fp.sh` + `fse4_fp_probe.py` (F9 to the wil van's door in first
  person, Return in and out, 30 fps bursts per `door_top_cut:door_interior` pair in `FSE_TOPS`).
- Still short: the lower doorway still reads near black from the eye at the door (the box's lower walls
  and floor are dark and the post pass darkens the concave box further); the swung door's inner face is
  the outer skin re-wound (no door card, window frame or trim); other bodies with a lip or ribs were not
  filmed; dusk/night and Remix untested.

## FIX-SEAT-ENTRY-4: the first-person seat point kept (tri11, 10 Nov 2026)

tri11 (first person, a sustained reverse): after about 1.5 s of Down the wheel, hands and dash left
the view and stayed gone after the stop, the bonnet filling the lower screen. `GTA2DX9_LOG_SEAT=1`
(run with the camera log) showed the gate fine throughout (eye inside the box, own flag set) but the
eye sinking in the body's frame from 0.40 to 0.10-0.25 of a block and staying there: the car had
reversed into an obstacle and its drawn body stood lifted on it, level, while the camera eye stays at
the game's floor. FIX-FP-ENTRY's seat correction (car_bodies tells the camera how far the posed seat
point is from its raw eye) is meant to lift the eye with the body, but its seat point kept re-learning
from the raw eye whenever the body was level (10 % a frame): the lifted body taught it the low seat and
the correction decayed to nothing in a second (log: 0.485 -> 0.18).

- `fp_seat_freeze` ([devtools], default 1, live): the seat point is learned over the first 30 level
  frames in a car and then kept; the correction may reach 0.5 of a block. 0 is the old learning.
- `force_own_lift` ([devtools], default 0, live): the driven car drawn N/100 block higher, the probe.
- Probe: `gamerun/keys_fse4_lift.sh` (ste, seated by F10/Return retries, first person; lift 0.20 with
  the seat point kept, then `fp_seat_freeze=0`, then no lift; `seat gate:` / `seat pose:` lines).
  The scripted reverse (`keys_fse4_rev.sh`, a copy of keys_fh3_plates with seating retries) reaches
  the obstacle only on some runs (traffic changes the path).
- Still short: the natural repro was not reached again on the fixed build (2 of 5 scripted reverses
  hit the obstacle, both before the fix); a body lifted at the moment of seating still teaches a low
  seat; the cockpit hands are the view model's (FIX-FIGURE-9).
