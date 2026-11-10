# Vehicle feel (VEHICLE-FEEL, 8 Nov 2026)

The 3D car bodies in the third- and first-person views now move like a modern game's cars,
without touching GTA2's physics: everything is derived from what the game already gives the
renderer (the car's position and heading frame to frame, its damage word `+0x74`, the map's
ground types). Code: `dll/src/vehicle_fx.cpp/.h` (state, springs, particles, marks, lamp pools),
`dll/src/car_bodies.cpp` (wheel split on the wear worker, the posed draw, lamps). The classic
view is untouched (it keeps the game's flat sprites).

## What a car does

| Effect | Read from | How |
|---|---|---|
| Body roll in turns, pitch under braking and acceleration | position and heading per frame: smoothed velocity, acceleration in the car's frame (forward `aF`, lateral `aL`) | the body (not the wheels) is rotated about a point at 0.3 of the roof height: roll 0.013 rad per block/s² of `aL` (max 0.075 rad, 4.3°), pitch -0.0055 rad per block/s² of `aF` (max 0.065 rad); each on a damped spring (roll 1.5 Hz, pitch 1.7 Hz, damping 0.45) so it settles with a small overshoot when the turn or the stop ends |
| Suspension bounce | kerbs: the map's lid ground type under each wheel (`GroundSampler`, road 1 vs pavement/verge); slopes: vertical acceleration; impacts: the damage word rising, or a velocity jolt over 45 blocks/s² | a kick to that corner (heave, pitch, roll velocities) on a heave spring (2.4 Hz, damping 0.35); front then rear on a kerb |
| Wheels | distance covered along the nose; heading change over that distance | each wheel turns about its own axle by distance / radius; the front pair steers by `atan(wheelbase * dyaw / ds)` (as the sprite-built bodies did) |
| Wheels as parts | the model's own geometry | parametric models (and the wrecks) carry `wheel_*` marker nodes: centre and radius from them. Image-to-3D shells: axles from the CARI wheel rows refined by where the shell touches the road, radius 0.21 of the body height (0.055-0.13 blocks), the outer face from the widest vertex near the axle. Every triangle wholly inside a wheel's disc on the outer part of its side goes to that wheel, the rest is the hull (the door split's method). Built on the wear worker thread (`BuildWheelSplit`, 1-10 ms each, off the render thread), registered with dynamic buffers, one new copy on screen per frame, capped at 64 MB; cars within 22 blocks of the eye (and the player's car) draw hull + wheels, the rest the whole model |
| Brake lamps | the same motion: slowing faster than 2.5 blocks/s² either way, or backing | the tail glows brighten and grow, day or night |
| Reverse lamps | signed speed along the nose below -0.35 blocks/s | two white glows inboard of the tail lamps |
| Head lamps at night | the lamps' own dark test (sun below 6°) | an additive pool on the road ahead of each lit car, 2.6 blocks long, widening to 1.7 blocks; the nearest 10 within 40 blocks; plain renderer only (under Remix the lamps are lights); fog fades it to black, not to haze |
| Exhaust | at night, standing (under 0.3 blocks/s) or a hard launch | a pale puff from the tailpipe every 0.35-0.65 s (0.12 s on a launch) |
| Tyre smoke and skid marks | lateral slip over 0.9 blocks/s, or the heading swinging faster than 1.9 rad/s (GTA2 keeps the velocity close to the heading even in a handbrake turn), hard braking (over 7 blocks/s²), wheelspin at a launch | smoke from the rear wheels (8-30 puffs/s), dark soft-edged marks under the rear wheels (and the front ones when braking), held 25 s then faded over 15 s; these add to the game's own skid strips, which `live_geometry.cpp` still softens |
| Sparks | an impact (see above) or the damage rising while moving: a scrape | 8-30 additive streaks from the body's edge on the side the push came from, gravity and a bounce, 0.2-0.55 s |
| Explosion | the car becoming a wreck (sprites 65-74) within 1.5 s of being seen whole, or its damage reaching 32000 | 22 tumbling shards (its scorched paint, dark metal, glass), 30 sparks, smoke, and one of its own cut wheels flying off (ballistic, spinning, bouncing, then lying on its side for up to 30 s) |
| Wreck pose | the wreck model's `wheel_*` markers (the wheels it kept) | each lost corner drops onto its hub (0.85 of a wheel radius), the kept ones sit on flat tyres (0.25); the body tilts to match |

All effect quads draw from one dynamic vertex buffer and a fixed quad index buffer (four
draws a frame at most, plus the lamp pools). Bounds: 640 particles (the oldest smoke gives way), 1400 skid segments in a ring, 6 flying
parts, 10 lamp pools, per-car state dropped after 20 s unseen. No per-frame allocation after
the first frames.

## Switches

- `GTA2DX9_VEHICLE_FEEL=0` (environment): all of it off, the cars as before.
- `[devtools] vehicle_feel=0|1`: re-read once a second, so one scripted session shows the same
  manoeuvre before and after (`gamerun/vehfeel_take.py`).
- `GTA2DX9_LOG_VEHICLE_FEEL=1`: the player's car's speed, accelerations, roll/pitch/heave, steer,
  lamps, damage and the ground type under each wheel every 3 frames (how the gains were set:
  GTA2 turns pull up to ~6 blocks/s² sideways, its brakes ~15 forward, a launch ~7).
- Log lines: `car bodies: wheel split of <model>: N wheels, radius, axles ...`, `car wheels:`
  (every 900 frames, splits and MB), `vehicle feel: N cars tracked, particles, skid segments,
  flying parts; ms a frame (worst)` (every 900 frames), `vehicle feel: car ... blew up`.

## Cost

The feel's own time (the car updates plus the effects pass, timed inside `car_bodies.cpp`'s cars
stage and logged every 900 frames as `vehicle feel: ... ms a frame`): **0.04-0.38 ms a frame on
average** with 15-20 cars tracked, up to ~70 particles and 450 skid segments (runs `out/vf_5`..`vf_8`).
Wheel splits: 1-10 ms each on the worker thread (never the render thread), 17-19 splits = 8-9 MB
in a drive; the hull + 4 wheels are 5 draws instead of 1 for cars within 22 blocks.

One-off costs, logged as `vehicle feel: slow frame ...` (the breakdown is in the code):
- the effect textures: first made as managed textures, each create cost 85-590 ms on the loaded
  host (wined3d waits for the queued frame); now dynamic default-pool textures, one a frame: the
  first 190 ms once (the first default-pool create of the session), the other four 0.4 ms;
- the first draw from the dynamic quad buffer, ~80 ms once;
- otherwise isolated 10-70 ms "updates" frames, only in runs with `GTA2DX9_LOG_VEHICLE_FEEL=1`
  (a log line every 3 frames) or under host load; with the log off the worst after the first
  second was 6.2 ms (`vf_8`).

The p99 < 33 ms frame budget could not be re-measured cleanly in this pass: the host ran at load
10-17 with three other game runs (driving p50 8.5 ms, p99 286 ms in `vf_6`, the largest phase in
the slow frames being GTA2's own step and present, not the cars stage; cars stage p50 0.39 ms,
p95 2.4 ms). A quiet-host `perf3_run.sh` drive is the check to run next.

## Evidence

- `out/vehicle_feel_sheet.png` (local, not in git): before (`vehicle_feel=0`) | after (`=1`) for the
  same manoeuvres, every traffic car drawn as model 13 (`force_car_model`) so the rows compare;
  rows: turn, brake, kerb runs, night lamp pools and brake lamps, night reverse lamps, night
  idle exhaust, handbrake turn (skid marks), scrapes, blown up. Built by
  `linux/docker/vehfeel_sheet.py` from the frames `vehfeel_take.py` grabs (runs `vf_5` day
  before, `vf_6` day after / night / wreck before, `vf_8` wreck after from its clip).
- `out/vehicle_feel.mp4` (27 s, 1280x720): the day manoeuvres, the night street, and a car
  blowing up (`linux/docker/vehfeel_clip.sh`).
- Seen: skid marks under the wheels on hard braking and handbrake turns, head-lamp pools and
  reverse lamps at night (absent in "before": see the lamp fix below), exhaust puffs at idle,
  the explosion's debris shards and sparks, all 4 wheels cut on every image-to-3D model drawn
  (`wheel split of ...: 4 wheels` for 17 models; 6 on the parametric trucks). Roll and dive are
  a few degrees and read in the clip more than in single chase-camera frames.
- Not caught in a frame: the flying wheel (it needs the wheel split made in the minute before the
  explosion, true for the player's car; the take's explosions killed the player and the camera
  cut away), sparks on a pure scrape (the hits logged sparks; a long wall slide was not driven).

## Lamp fix (follow_clock)

`live_geometry.cpp` tells the lamps it is dark from the sky's fixed sun (`sun_elevation_tenths`);
with `[sky] follow_clock=1` the picture follows the clock, so a night street had unlit cars
(the "before" night rows). `CarBodiesSetLamps` now takes the clock's sun when `follow_clock=1`
(`car_bodies.cpp`, no change in the caller).

## Hooks outside the owned files

- `dll/src/world_view.cpp`: one line, `VehicleFxSetGround(&ground_);` beside `LightsSetGround`
  (plus its include), for the kerb test.
- `dll/build.bat`: `src\vehicle_fx.cpp` in the source list (the Makefile picks it up by wildcard).

## Known limits

- The wheel cut of an image-to-3D shell is a disc of estimated radius: where the shell's tyre is
  larger than the estimate its top stays on the hull; a fender skirt over the wheel is cut with it
  and turns with the wheel. Steered front wheels can show a sliver of the hull's inside at full lock.
- Doors open and the tank/fire-truck turrets draw the whole model (no turning wheels then).
- Kerb bumps come from the map's ground type changing under a wheel (GTA2's pavement is the road's
  height), so a car crossing a dropped kerb at a junction bumps too.
- Skid marks lie on the plane of the car's ground at the time; on a ramp they follow it only
  segment by segment.

## VEHICLE-PHYSICS (9 Nov 2026): load transfer, tyre grip, impacts, progressive damage

The first feel leaned the body by fixed gains on the measured acceleration. This pass replaces
those gains with a small physical model of the same inputs (`dll/src/vehicle_fx.cpp`, the
`live && g_physics` branch of `VehicleFxUpdate`). It is still drawing only: GTA2's handling and
collisions are untouched, so the model can only show what the game's motion implies.
`[devtools] vehicle_physics=0|1` (or `GTA2DX9_VEHICLE_PHYSICS=0`) switches between this pass
and the first feel's springs, for before/after frames.

| Part | Model |
|---|---|
| Chassis per car | track 0.84 x body width, wheelbase from the model's axles, centre of mass at 0.38 of the body height. Ride frequency from body height over width: a low coupe ~1.6 Hz, a sedan ~1.45 Hz, a van ~1.25 Hz (period 1960s springs). Static spring deflection is g / w^2, scaled to blocks at 1.8 m per car width (~0.03 block for a sedan); bump stops at 1.25 x that each way |
| Weight transfer | GTA2's accelerations are taken in "game g" (9 blocks/s^2 = 1 g; its turns pull up to ~8, its brakes 6-15). What the tyres carry is capped softly at the grip limit, so a 15 blocks/s^2 stop does not dive further than a 10 one. Longitudinal transfer is a x h / wheelbase (0.85 of it through the springs: anti-dive and anti-squat). Lateral transfer is a x h / track, 56 % on the front axle, with the roll stiffness 1.2 x the springs (a period front bar). Each corner's load gives its spring compression, and the four compressions give the roll, pitch and heave targets. Ceilings: 6 deg roll and 3 deg pitch from manoeuvres (the quality bar's FEEL-09) |
| Springs | roll at 1.2 x and pitch at 1.1 x the ride frequency, damping 0.6 of critical (a ~10 % overshoot that settles within ~0.4 s to the 10 % band). Damping falls to 0.3 as the damage word rises from 4000 to 20000: a beaten car bounces longer |
| Tyres | a friction circle per tyre. Braking is split by the axle loads plus 5 % front bias, so the fronts lock first; drive is on the rear axle. Cornering force is shared by load. Grip falls 25 % per +100 % load (load sensitivity). A tyre over ~0.95 of its grip marks the road; past it, it slides: per-wheel skid marks, and smoke from the wheel that slides most. The handbrake/slide test from the first feel still drives the rear pair |
| Steering | the front wheels point along the front axle's own velocity (sideways velocity plus the yaw's swing of the nose), so a car whose tail slides out shows counter-steer. With the rear gripping this equals the first feel's atan(wheelbase x yaw rate / speed) |
| Kerbs | the wheel that crosses road <-> pavement lifts for 0.14 s (up to 0.018 block) and its corner passes the step to the body |
| Impacts | the velocity's jump in one step is the impulse per unit mass. The sprung body pitches or rolls by dv x h / k^2 (k the radius of gyration, 0.3 x length or 0.35 x width), with 0.35 of it felt before the springs take it, and gives on its mounts by up to 0.03 block against the push. A jump with no damage counts only if the car lost speed: GTA2's traffic pulling off from a stop jumps 4-7 blocks/s in one step, which vp_1 showed being taken for hits |
| Progressive damage | each hit's damage goes 70 % to the corner that struck (from the push's direction on the body outline) and 15 % to each neighbour; scrapes go to the side leaning on the wall. That corner sags up to half a wheel radius (4000-16000 of corner damage); its wheel cambers up to 8 deg (5000-17000) and wobbles with the spin (a bent rim, from 7000). The engine steams from 7000 of damage (or a hurt front) and its smoke darkens from 13000 to dark grey by 16500, when the game has set the car alight (FIX-FX, 9 Nov: a burning car's plume had stayed pale steam, a flat white-grey column); each puff is thinner the darker it is (0.34 to 0.24), takes the scene's light (a third of it at night, a quarter of the sky's tint) and fades out within 0.6-3 sizes of the eye, so a plume the chase camera drives through stays local haze |
| A wheel off the ground | a corner rising past full droop lifts its wheel with it |

Telemetry: with `GTA2DX9_LOG_VEHICLE_FEEL=1` the player's car also logs `vehicle physics: player car
load= use= slip= carried= shove= lift= camber= corners= wear= ride= defl=` every 3 frames, and
`vehicle physics: impact (player) dv= ... at corner N, damage +d -> D, corners ...` on every hit
(other cars' hits log only with the switch on). `tools/vphys_telemetry.py <run>` cuts it by the
take's marks.

Take: `gamerun/vphys_take.py` (mirrored in `linux/docker/`) with `keys_vphys.sh` and
`vphys_grun.sh`, which is grun.sh on the agent's own GPU. It runs on the scene car by the
Downtown carriageway: a test launch must reach 3 blocks/s or another car is taken; then
launch-and-brake, a hard left, drives at the kerb walls until two logged hits (a frame burst on
each), and for the "after" variant the damage set to 9000, 13000 and 19000.

## FIX-VEHICLES (9 Nov 2026): a body you can see move, the camera feels the hits

PLAYTEST-FEEL (defect `vehicle-body-rigid-no-weight-transfer`) read the body as rigid in the
chase view although the springs above were working: the renderer log of HEAD c69c620 (run
`fv_before1`) shows 3.6 deg of dive on a hard stop and 2.6 deg of roll, but pitched about the
middle a van seen from behind moves its tail by a few pixels. The camera's own impact shake and
the first-person lean existed but were off (`ImpactShake=0`, `FirstLean=0`). This pass keeps the
model (VEHICLE-PHYSICS above) and changes what is drawn and what the camera does:

- **Drawn lean**: the model's pitch times `[renderer] car_body_pitch` (220 %) and roll times
  `car_body_roll` (170 %), at most 7 and 8 degrees drawn (an impact's kick included); the telemetry's
  `roll=` / `pitch=` are now the drawn angles.
- **Pitch centre ahead of the middle** (0.25 of the length): the tail lifts under braking and squats
  on a launch, which is what the chase camera sees.
- **Impact camera shake** at the wheel (`[camera] car_impact_shake`, 100 %): from the speed lost in
  a hit as the body model measures it (`VehicleFxPlayerMotion`, filtered against GTA2's traffic
  jumps), above 0.6 blocks/s; log line `view: car impact N blocks/s lost, camera shake S`.
- **First person rides the body** (`[camera] first_body_ride`, 100 %): the eye takes the drawn
  pitch, roll and heave; the cut cockpit body takes the same share (it was a third, QB-5), so the
  bonnet holds still under the eye while the street tilts.
  FIX-FP-ENTRY (pfeel32): the eye's position also follows the body's whole pose, a kerb's tilt included
  (`docs/actions-3d.md`, "First-person entry, exit and the driver's arms").

Measured (`tools/body_motion_telemetry.py`, peaks in the `feel_probe` drive and crash bursts, same
command as the defect, `fv_before1` HEAD vs `fv_after2`):

| | before | after |
|---|---|---|
| launch squat (tail down) | -1.2 deg | -2.4 deg |
| hard brake dive | +3.6 deg (+5.7 at a hit) | +7.0 deg (cap; +4.4 on a clean stop in `fv_after1` at 170 %) |
| roll in the turns | 2.6 deg | 3.5 deg |
| wall impact | 5.7 deg pitch, no camera shake | 7.0 deg kick, shake 0.8-1.5 (2.5-3.6 blocks/s lost), settled in ~0.3 s |
| first person on braking | eye level | eye dips 2.8 deg, rolls with the body |

Frames: `out/fv_sheets/brake_sheet.png`, `turns_sheet.png`, `crash_sheet.png`, `a_first.png`
(local; built by `tools/body_motion_sheet.py`, each tile labelled with its logged pitch and roll).

### Overlapping bodies (FIX-VEHICLES, defect `car-bodies-interpenetrate-in-traffic`, partial)

- Measured (`car fit:` log line, once per model and sprite): every model's drawn footprint equals the
  game's box (the sprite's length and width) to 0.02 block; the 3D models do not overhang. Overlap on
  screen is the game's own boxes overlapping (GTA2's 2D sprites hide it).
- `car_bodies.cpp` keeps each car's drawn footprint for the next frame; a car whose footprint overlaps
  another on the same level (within 0.45 block in height) is drawn moved by the least separating push
  (2D separating axes), half each, eased over ~3 frames, at most 0.35 block. The player's car seen from
  the seat stays put; train carriages (59-61), truck cabs (63, 64) and trailers (55, 65, 66) stay coupled
  with each other and take no push from other cars. `[renderer] car_separation` (first `[renderer]`
  block), `GTA2DX9_LOG_CAR_OVERLAP=1` logs pairs every 15 frames: the overlap, the game boxes' overlap,
  the push, and what is left on screen.
- Seen in runs `fv_ov_*`: the big overlaps (0.35-0.6 block) were cars under the elevated train (now
  skipped by the height test) and the train's own couplings (0.41, skipped); ordinary traffic overlapped
  by at most 0.03 block in six runs (twice with the car density tripled), pushed apart to <0.01 left.
  The filer's quarter-car overlap in a queue did not recur in those runs: untested on a large overlap.
- Wine reads only the first of two sections with the same name: keys in the second `[renderer]`
  block of gta2dx9.ini (`spawn_offscreen`, `blood`, `gibs`, `ragdoll`, `intro`, ...) fall back to their
  code defaults on Linux (seen here: `car_separation=0` there had no effect).

## VEHICLE-ART-5 (9 Nov 2026): a marker-less shell turns its hubs only

The image-to-3D shells have no `wheel_*` marker nodes. Their wheel circle is a guess from the CARI axle and the
body height, and it rarely sits on the shell's own tyre. Cutting the whole 1.06 r disc out of the shell caused
two faults (pm-van-model-torn-black-shards-under-body, pm2's hanging wheel):
- The arch lips and fender skirts in the disc turned and steered with the wheel: the 027 van's pink crescents,
  the 050's skirt hanging off its rear wheel.
- The tread outside the disc stayed on the sprung hull: black shards beside the wheel.

For a shell (`(shell: hubs only)` in the `wheel split of` log line), only the faces within 0.5 r turn. Those faces
are also kept in the hull, so the hub's ragged edge can never open a hole. They spin about the axle in the hull's
own (sprung) frame, 0.004 block outboard, with no steer, lift or camber. Tyre, arch and skirt are all the
hull's, so nothing tears away from it. Parametric bodies and wrecks (marker nodes) are unchanged.
`[devtools] shell_wheels=0` gives the old whole-disc split for A/B (it is part of the split's cache key).
Same-spot A/B frames: `gamerun/va5_own.py` (the player's own car stopped at the street warp, forced to each
model, regression-camera poses).
Known limits:
- A shell's front wheels no longer visibly steer (fixed by VEHICLE-ART-6, below).
- The kerb-strike lift and the camber of a bent corner are not shown on shells.

## VEHICLE-ART-6 (9 Nov 2026): a shell's front tyres steer again

A shell's wheel is now its hub and its tyre, with no paint. The faces inside 0.98 r of the guessed circle are
split by what their texels are. The importer leaves the base texture see-through where its `_paint` twin is
paint, so the paint share is `1 - alpha`; `ShellTexelsFor` reads it on the worker at 128 x 128 cells.
- **Hub:** the faces within 0.5 r, as before. They spin, and the front pair also steers.
- **Tyre ring:** the faces between 0.5 r and 0.98 r that are not paint (share under 0.35) and are dark
  (luminance under 0.30), or lie within 0.8 r (whitewall, hubcap). The ring steers only and never spins: an
  image-to-3D tyre has no tread to show a spin, and a spun ring swung the dark arch pieces caught in it round
  the wheel. It is drawn only while the wheel is turned.
- **Hull:** the arch lips and fender skirts that crossed the circle are paint, so they stay on the hull. Both
  copies are also kept in the hull, so a turned wheel never opens a hole.

The carkit bodies (063, 013, 068) have no `wheel_*` nodes either, so they take this path as well. The log
line now reads `(shell: tyres and hubs, steered)`.

For A/B, `[devtools] force_steer_deg=N` turns every car's front wheels to N degrees, so you can film a stopped
car (`gamerun/va6_own.py`, a copy of va5_own.py that takes `VA6_SETS="label:key=v,key=v|..."`). Frames: 050,
027, 019 and 063 at 0, +25 and -25 degrees. At 0 degrees nothing is out of place (the 027's spun shard is gone).
At +-25 degrees the front tyre and hub turn and the rear ones stay put.
Limit: on the 027 van a dark arch piece caught in the ring swings out a little with the tyre at full lock.
## FIX-FX-3 (10 Nov 2026): car bodies lit by the world's sun (feel29 van brightness pop)

The driven van's body jumped about 75 % brighter in two frames beside a wall, with the road unchanged
(PLAYTEST-FEEL 29). There is no per-vehicle light sample to smooth. The jump is a mismatch between two lights:
- `car_bodies.cpp` lit every 3D body with a fixed sun of its own (direction 0.38, -0.78, 0.50, about 51
  degrees up, at a different azimuth from the `[sky]` sun).
- The shadow mask (`ps_shadowmask`, docs/visuals-plain.md) takes the *world* sun's share away where the map
  says the sun is hidden. A face turned from the world's sun is "already at ambient" and is not darkened
  (`saturate(ndl * 5)`).

So a van face lit by the car's own sun, but turned slightly from the world's, kept its full light inside a
wall's shadow. A few degrees of steering flipped that test, and the body went from shaded to pale while
the street round it stayed in shadow. Proof, with the shadow pass toggled live in one session (`out/fx3_van_a`):
- all on: largest 2-frame step 36 %;
- `shadows=0`: 8 %;
- the mask itself (`debug=2`, `out/fx3_van_c`): the van's rear face white while the ground beside it was in shadow.

Fix: the body's directional light takes the world's sun direction (`ComputeSkyColours(...).sunDir`, the
clock's sun with `follow_clock=1`), never flatter than 10 degrees (the shadow maps' own floor). The light
levels are unchanged (diffuse 0.78, specular 0.55, ambient 0x5A), so paint and sheen keep their tuning.
Under Remix and with the sky off, the old fixed sun is still used. `GTA2DX9_CAR_WORLD_SUN=0`, or
`[devtools] car_world_sun=0|1` (re-read every 2 s), gives the old sun for A/B frames.

Same-session A/B on the same route (`out/fx3_van_e`, passes o1/n1 both end at 198.5,168.9 heading north;
`gamerun/fx3_van.py`). A leak is the van's luma moving by more than 25 % in 2 frames while the ground
behind it moves by less than 10 % (`tools/fx3_leak.py`):

| pass | sun | van 2-frame step p95 / max | leak events |
|---|---|---|---|
| o1 | old fixed | 16.4 % / 49.2 % (52 -> 99 luma in 6 frames, road round it at 20) | 9 |
| n1 | world | 4.3 % / 12.4 % (a reversal at a wall) | 0 |

A real shadow edge still crosses a moving car in a few frames, as it should; the road ahead and behind
show the same edge (pass n2: the van leaves a building's shadow into sun over 8 frames).
Not changed: the light levels do not follow the time of day (they never did).

## FIX-VEHICLE-FEEL-2 (10 Nov 2026): the lean bounded by the wheels, cut wheels hung from the body

Orders: pmy1 (wheels detached from a tilted body on a kerb), feel10 (a jacked truck cab lurched ~8 degrees on
pull-away), pfeel40 half (b) (brake pitch), pfeel60 (corner roll, car hit), feel8 (wall ram). Code: `vehicle_fx.cpp`
(the pose block at the end of `VehicleFxUpdate`, the roll spring), `car_bodies.cpp` (the parametric wheel draw).
`[devtools] vehicle_feel2=0|1` (default 1, re-read every 2 s) or `GTA2DX9_VEHICLE_FEEL2=0` gives the old pose for
same-session A/B.

- **The body pitches about the middle of the wheelbase**, not a quarter ahead: the nose dips and the tail lifts alike.
  The forward pivot moved the rear axle by ~0.07 block at the 7 degree cap, so the rear wheel hung below the sill.
- **The drawn pose is bounded by the wheels' travel.** It is scaled (roll, pitch and heave together) until no axle
  moves more than the visible suspension travel against its wheel: half a wheel radius (0.022-0.05 block) where the
  wheels are cut (parametric bodies), 0.3 of it (0.015-0.035) where the tyres are part of the mesh (image-to-3D and
  carkit shells, and any car beyond 22 blocks). A tall body (roof over width above 0.95) gets up to 35 % less.
  `VehicleFeel::wheelTravel` carries the bound to the draw.
- **Cut wheels hang from the posed body** (`car_bodies.cpp`, the parametric branch): each wheel takes the body's
  pose, then is eased back toward the road by at most the travel. It rolls and pitches with its arch and stays on
  the road. Shells already drew their hub and tyre in the hull's frame.
- **Tall bodies roll less and slower**: the drawn roll is up to 35 % smaller, the roll mode up to 35 % slower. Outside
  0.35 s after a hit, the drawn roll cannot swing faster than ~43 deg/s (a tall cab ~23).
- `[devtools] force_body_pitch_deg` / `force_body_roll_deg` (0 = off): every live car drawn at that lean, before the
  bound, for fixed-pose frames of a stopped car (`gamerun/va6_own.py` with
  `VA6_SETS='p0:vehicle_feel2=0,force_body_pitch_deg=7,...|p1:vehicle_feel2=1,...'`).
- Telemetry: with `GTA2DX9_LOG_VEHICLE_FEEL=1`, every 90 frames
  `vehicle feel: player car dims L= W= roof= wb= r= rigid= tall= travel= feel2= model roll= pitch=`.

Measured (same session, feel2 0 then 1; `gamerun/vf2_probe.py`, `keys_vf2.sh` with `VF2_AB=vehicle_feel2=0,1`; runs
`vf2_ab1`, `vf2_ab2`; drawn peaks in degrees):

| | feel2=0 (HEAD) | feel2=1 |
|---|---|---|
| truck cab 063, pull-away with steer | roll 8.0 (cap), pitch -7.0 | roll 3.1, pitch 3.4 |
| truck cab 063, right turn | roll -8.0 | roll -2.2 to -3.1 |
| truck cab 063, brake | pitch 7.0, roll 8.0 | pitch 3.0-4.8 |
| small car (L 0.82), first-person brake | pitch 6.5 | pitch 5.6 |
| van 068, hard left | roll 5.4 | roll stays under the 7.2 bound (both feel2=1 passes hit traffic; untested clean) |
| van 068, wall ram | pitch 7.0, shake 1.24 (5.9 blocks/s lost) | not reached (the van was boxed in both feel2=1 passes) |

Frames (fixed poses, run `vf2_lean1`, a stopped car at 7 degrees pitch and 8 degrees roll): on 036 and 056 (cut
wheels) the old pose lifts the tail clear of the rear wheel, leaving a gap under the arch. The new one keeps the
wheel in its arch and on the road. On the 068 van and 063 cab (shells), the old pitch lifts the rear tyre off the
road and the old roll sinks the near tyres into it. Both are much smaller with feel2 on.

Findings that are not the body:
- feel8: in the wall ram the chase camera is pressed onto the van's roof at the wall (`vf2_ab2` `b_ram_0.mp4`
  2.8-5.2 s), so the logged 7 degree kick and the 1.24 camera shake never show the body. That is the camera's
  framing at a wall (FIX-CAMERA).
- pfeel60: the van rolls visibly into the left turn on HEAD (roof line tilted, `vf2_ab2` `b_corner_0.mp4` 4.0-4.4 s).
  The rigid body did not reproduce at this spot.
- pfeel40: the third-person camera ignores the body's pitch (only first person rides it). The hook request is in the
  order for FIX-CAMERA-7B.

Limits: on a shell, an 8 degree roll still sinks the near tyres a little (the tyres are in the mesh). The drawn lean
of shells is about half the old one at its peak.

## FIX-FX-5 (10 Nov 2026): no white squares on the road under a car's nose under Remix

The "two hard-edged white squares on the pavement under the front bumper" (ptrmx20 at 22:00, prxq at dawn, fm8 at
noon) were not puffs, skid marks or a light's glint. They were the game's own lamp deltas (headlight and tail-light
pixels of the 2D car sprite) that `LiveGeometry::AddCarLamps` lays as small quads at the flat sprite's level. Under
Remix those quads become emissive API meshes (`LampMaterialFor`), so under a 3D car model they lay on the paving
just ahead of the nose. Each was a 2x2-texel lamp texture blown up to about 0.05 tile.

How it was attributed, in single Remix sessions at the 018 pose (wil 164.5,147.6, `keys_fm7_own.sh` with `AB_SETS`):
`remix_car_lamps=0`, `tyre_shadows=0`, `remix_lights_off=1`, `remix_puff_mode=2` with `remix_skid_mode=2`, and
`remix_beam_mode=0` all left the squares unchanged. With all our lights out the scene went dark, but the squares still
glowed and lit the road round them (out/ffx5_bs1), so they had to be emissive geometry. A plain-GL twin at the same pose
shows nothing there (out/ffx5_pl1). FIX-FX-2 had already left these quads out under a 3D model in the plain renderer
(the pm6 lamp dashes). It kept them under Remix because they were "the lamp lights' meshes", but the model has its own
lenses and the street-view beams are remix_lights' (FIX-REMIX-NIGHT-8).

Now the quads are left out under a hidden 3D car model under Remix too, in the street views only. Classic is untouched.
`[devtools] remix_flat_lamps=1` brings the old quads back (live, for a same-session A/B). Frames: out/ffx5_fl1
(`own_h22_*_abold` vs `_abnew`, `own_h13_*`).

## FIX-TRAFFIC-1 (10 Nov 2026): traffic that stops and starts - the cap measured, 36 -> 24

The owner (RTX 5090, Remix, twice on 10 Nov): traffic cars "drive along and then brake sharply, over and over
again" and "move in an unstable, jittery way". The census while he played: `cars=21.0 moving=8.5 stopped=12.5
queued=4.0 freestop=8.5`. The operator's reading: `[density] traffic_cap=36` raises the ambient traffic above what
GTA2's pathing was sized for (stock 16).

**The census now says why a car stands** (`dll/src/city_ai.cpp`, the `ai:` line; logging only). `freestop`
(stopped, no car within 1.6 blocks ahead) keeps its meaning and is split by the first cause that fits:
`fs_ped` (someone on foot, the player included, within 2 blocks ahead in its lane), `fs_gap` (a car 1.6-3.5
blocks ahead in its lane: GTA2's `DetectCarAhead` looks 3 blocks ahead, so this is a queue the 1.6-block test
missed, and the cars behind a queued car stand further back), `fs_cross` (a car across its path within 3.5
blocks), `fs_junction` (on, or up to 3 blocks before, a cell whose road arrows run both ways: lights and
give-ways), `fs_mid` (none of these). New: `stops`, `hardstops` (from over 2.5 blocks/s within ~0.5 s) and
`stopstart` (a stop under 2 s after the car got going) count stop events since the last line. Two things the
old line counted that are not traffic: the player's own car (a stopped player car was one "free stop" for as
long as he sat in it; `d=0.0` in the stop log), and cars standing where GTA2 created them (a car object recycled
to a spawn point jumps there at rest). Both are now left out (`fresh=` counts the second).
`GTA2DX9_TRAFFIC_LOG=1` logs one `ai: stop` line per free-stopped car (position, heading, cause, how long,
road arrows, the nearest car) at most every 2 s a car; `GTA2DX9_DENSITY_LEVEL=0..3` pins `density.cpp`'s
frame-rate budget level (on the shared host the controller otherwise moves the cap mid-run: run `ftr1_w36a`
went 36 -> 16 and back three times). `GTA2DX9_TRAFFIC_CAP=<n>` overrides `[density] traffic_cap`.
Tool: `tools/traffic_census.py out/<run>` (per probe segment); probe `gamerun/ftr1_probe.py` +
`keys_ftr1.sh` (mirrored in `linux/docker/`): third person, 3 minutes standing at the level start, then
the nearest parked car (F9) driven by the route planner (or a weaving cruise where it finds no route)
for 2.5 minutes.

**The cap table** (L4 host, HEAD a5df3568 + this census, `GTA2_DIRECT_KEYS=1`, `GTA2DX9_STATE_EVERY=3`,
level pinned at 3, census within 20 blocks, one line a second; mean cars near the player, shares of them):

| District, cap | runs | segment | cars | moving | stopped | freestop | of it: gap / junction / cross / ped / mid | stops per car-min | stop-start per car-min |
|---|---|---|---|---|---|---|---|---|---|
| wil 16 (stock) | ftr1_w16c, w16d | stand | 4.5 | 4.4 | 4% | 0.2 (4%) | 0.1 / 0.0 / 0.0 / 0.0 / 0.0 | 1.7 | 0.56 |
| | | drive | 8.7 | 4.8 | 45% | 3.6 (42%) | 0.9 / 1.9 / 0.2 / 0.1 / 0.5 | 4.8 | 0.98 |
| | | both | 6.3 | 4.6 | 28% | 1.7 (**26%**) | | 3.5 | 0.81 |
| wil 24 | ftr1_w24d | stand | 6.4 | 6.0 | 7% | 0.4 (6%) | 0.3 / 0.0 / 0.0 / 0.0 / 0.1 | 1.7 | 0.05 |
| | | drive | 13.4 | 7.5 | 44% | 5.6 (42%) | 2.2 / 2.4 / 0.4 / 0.2 / 0.4 | 5.5 | 1.28 |
| | | both | 9.6 | 6.7 | 30% | 2.7 (**29%**) | | 4.1 | 0.82 |
| wil 36 | ftr1_w36b, c, d | stand | 10.7 | 7.8 | 27% | 2.5 (23%) | 2.2 / 0.0 / 0.0 / 0.1 / 0.2 | 2.6 | 0.64 |
| | | drive | 20.2 | 9.8 | 51% | 9.1 (45%) | 4.8 / 2.2 / 0.7 / 0.2 / 1.2 | 5.5 | 1.61 |
| | | both | 14.8 | 8.7 | 41% | 5.3 (**36%**) | | 4.3 | 1.21 |
| bil 16 (stock) | ftr1_b16d | stand | 4.8 | 2.7 | 43% | 1.7 (**36%**) | 0.3 / 1.1 / 0.0 / 0.1 / 0.2 | 4.2 | 0.91 |
| bil 24 | ftr1_b24d | stand | 8.6 | 4.3 | 49% | 3.8 (44%) | 1.8 / 1.1 / 0.0 / 0.3 / 0.5 | 5.3 | 1.36 |
| | | drive | 14.0 | 8.9 | 37% | 4.1 (29%) | 1.5 / 1.9 / 0.2 / 0.1 / 0.3 | 5.3 | 1.66 |
| | | both | 10.6 | 6.1 | 43% | 3.9 (**37%**) | | 5.3 | 1.51 |
| bil 36 | ftr1_b36c, d | stand | 11.1 | 3.1 | 72% | 7.1 (64%) | 5.5 / 0.7 / 0.2 / 0.3 / 0.4 | 3.2 | 0.90 |
| | | drive | 27.4 | 5.3 | 81% | 17.8 (65%) | 13.9 / 0.6 / 2.4 / 0.7 / 0.1 | 2.4 | 1.36 |
| | | both | 15.0 | 3.6 | 76% | 9.6 (**65%**) | | 2.8 | 1.10 |

(`ftr1_b36c` ran the census before the recycled-car fix, which changes nothing it reports here: `fresh` stayed
0.0 in every run. The bil route planner found no route from the start in `b16d` and `b36c`, so those have
no drive segment; `b36d` and `b24d` drove the weaving cruise.)

What it shows:

- **Free stops scale with the cap, and they are queues.** At 36 most of the free stops are `fs_gap`: cars
  waiting behind a car GTA2's own probe sees but the census did not (wil stand 2.2 of 2.5, bil drive 13.9 of 17.8),
  then junction waits. A stop with nothing at all ahead (`fs_mid`) is 0.0-1.2 cars at every cap.
- **The roads saturate in Residential.** bil at 36 has more cars near the player than at 24 (11.1 against 8.6
  standing) but *fewer moving* (3.1 against 4.3): the junction by the start (three lanes at a red light at
  ~48,85, `ai: stop` lines) cannot pass them and the queues back up through it (`ftr1_b36d` drive frame
  `qa_drive_04.png`: a bumper-to-bumper jam across a crosswalk). Downtown still flows at 36 (7.8 moving
  standing) but already queues (23% free stops against 4%).
- **Per car, GTA2 brakes the same at every cap.** Stops per car-minute (1.7-5.5) and stop-start cycles
  (0.05-1.6) move with the segment (driving through junctions, or standing by a plaza) much more than with the
  cap, and hard stops are rare (0.0-0.4 per car-minute). The owner's own line, 8.5 free of 21 (40%), is the
  stock cap's driving share at Downtown (42%). What he saw grow with the cap is how many cars stand in queues
  in view, which the stop-start of GTA2's own car AI makes visible: VEHICLE-PHYSICS measured its traffic
  pulling off by 4-7 blocks/s in one step and braking at 6-15 blocks/s^2, and that is the game's handling.
- **Shipped: `traffic_cap=24`** (ini and the DLL default). Free stops within 1.5x of stock over the
  stand + drive: Downtown 29% against 26% (1.1x), Residential 37% against 36% (1.0x; standing alone 44%
  against 36%, 1.2x). It keeps half again as many moving cars round the player as stock (Downtown 6.7 against
  4.6 over stand + drive, Residential 4.3 against 2.7 standing), and in Residential more than 36 did. The frame-rate
  levels now run 16, 18, 21, 24. Industrial (ste) was not measured.

**Kerb clips** (Downtown boulevard pavement, third person, 90 s for the traffic to fill, then 40 s;
`gamerun/ftr1_kerb.py` + `keys_ftr1_kerb.sh`, `GTA2DX9_TRAFFIC_CAP` 36 vs 24, 30 fps video; 20 s cuts made
from `game.mp4`). Census over each clip window:

| Spot | cap | cars near | moving | stopped | freestop (gap / junction / mid) |
|---|---|---|---|---|---|
| 158.5,156.5 facing west (`ftr1_k36a` / `ftr1_k24a`) | 36 | 31.6 | 6.8 | 24.8 | 17.3 = 55% (14.4 / 2.2 / 0.2) |
| | 24 | 18.9 | 8.4 | 10.5 | 9.2 = 48% (4.6 / 3.2 / 0.4) |
| 150.5,156.5 facing west, junction 5-8 blocks ahead (`ftr1_k36b` / `ftr1_k24b`, rebased build) | 36 | 29.6 | 14.3 | 15.3 | 12.7 = 43% (7.1 / 4.9 / 0.2) |
| | 24 | 18.2 | 9.1 | 9.2 | 8.4 = 46% (3.4 / 4.3 / 0.2) |

At the first spot, cap 36 jams the boulevard's west junction (30+ of the 36 cars within 20 blocks, the queue
grows through the clip to 32 stopped). Cap 24 keeps more cars moving with fewer cars present. At the second
spot both caps flow and the shares match. In the frames I opened (sheets of 0/5/10/15 s), no car near the
camera stops with an empty street ahead. The traffic in view is at the far junction, crossing and waiting
at the lights, and the near eastbound lanes are mostly empty at both caps. This framing therefore does not
show close-up flow. A better clip needs a spot facing a busy lane head-on.

Not done: Industrial (ste) unmeasured. One run per cell for wil 24, bil 16 and bil 24, while runs of the
same cell spread widely (wil 36 standing: 12-29% free stops over four runs), so the 24 numbers are a
measurement, not a tight bound. Not seen under Remix or on the owner's box. GTA2's own lurch (traffic
pulling off by 4-7 blocks/s in a step, braking at 6-15 blocks/s^2) is still there at every cap; smoothing
it would mean drawing a car away from where the game has it (a drawn lag along its lane), which is not done
here.

## FIX-LIGHTS-1 (10 Nov 2026): lamp glows on the lenses, head-lamp pools laid on the ground

Street views, plain renderer; the classic view is untouched (it draws the game's own lamp quads; vreg
`spawn_classic` 0 of 144 tiles changed).

### qav46: no lamp wedges under a low body's bumper (`[devtools] car_lamp_lens`)

- What it was: two hard-edged orange parallelograms under the 018 coupe's rear bumper corners at dusk and
  night in the chase view, brighter than the dark tail lenses above them. Not the game's lamp quads: a probe
  (`GTA2DX9_LOG_LAMP_QUADS=1`, one `lamp quad:` line per kind) shows every one of them dropped under a 3D body in
  the street views (hidden body, no dome; FIX-FX-2's rule holds for the whole fleet). They were car_bodies'
  own tail glows (`DrawLamps`), placed at a fixed 30 % of the body's height on the bounding box's end plane:
  on a low body that is the bumper's underside, and the glow showed on the dark underpan box below the
  bumper, cut along that box's straight edges.
- Now: a body with lamp meshes (textures `*lamp_head` / `*lamp_tail`: the authored kit bodies, e.g. 000, 004,
  012, 013, 018, 036, 050, 053) gets its glows on its own lenses: per side, the lamp vertices within 6 % of the
  body's length of that side's outermost end, their mean, taken through the body's fit (log line
  `car bodies: lamp lenses of <model>: ...`). The glow is drawn 0.08 block toward the eye from the lens (same
  place on screen, in front of the curved panel round it). Every glow, measured or not, keeps its whole quad
  above the body's ground line. Brake and reverse glows follow the same lenses (reverse at 55 % of the
  lens's offset).
- Checked (same pose, old/new toggled in one session, night 22:30 and dusk 19:00, 3x crops): 018 (glow on the
  lens, nothing under the bumper), 012 cop car (on the upper round lens, was on the bumper), 068 van, 041
  pickup and 063 truck cab (no lamp meshes: the old spot, now above the ground line; no change seen), 072
  wreck (no glows). No polygon on the road in any new frame.
- Limits: a body without lamp meshes keeps the generic spot (the 068 van's glows sit on its doors, inboard
  of its tall red lenses); seen from behind, a glow's part outside the body's silhouette does not show (a
  soft vertical end at the body's side on the 018).
