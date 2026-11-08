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

Bounds: 640 particles (the oldest smoke gives way), 1400 skid segments in a ring, 6 flying
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

RESULTS_COST

## Evidence

RESULTS_EVIDENCE

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
