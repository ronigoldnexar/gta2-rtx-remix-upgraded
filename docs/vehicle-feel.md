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
