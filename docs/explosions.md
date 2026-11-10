# Explosions and fire in the street views (QB-19)

Quality-bar row 19 (`docs/quality-bar.md`): "Explosions, fire, debris". A modern game shows
a volumetric fireball, a light flash on the surroundings, a shock wave, flying parts, a lingering
smoke column and a charred wreck. Before this pass the street views stood the game's 2D blast
sprite up as one billboard (the cardboard look). Wreck models, flying wheels and car debris already
existed (`vehicle_fx.cpp`, VEHICLE-FEEL), and so did burning-car flames and smoke
(`live_geometry.cpp`, `[fire]`).

## What a blast draws now (`dll/src/explosion_fx.cpp`)

The sprite loop in `live_geometry.cpp` already spots a blast: an effect sprite bigger than
`[fire] fire_max_size_percent`, which is where the burnt mark on the ground (`NoteScorch`) comes
from. That same spot now also calls `ExplosionFxNote`. A spot seen again within 1.6 s of its first
sighting, or within 0.5 s of its last, counts as the same blast. The game shows the sprite on
and off while it plays, and without this window one blast was counted as two. Each blast spawns:

| part | how |
|---|---|
| fireball | 44 billows thrown out over the upper hemisphere with heavy drag, plus 8 that stay at the core and burn longer. Each is camera-facing and additive, uses one of 4 procedural billow shapes (noise-edged, soft to the rim), and grows with an ease-out. Its colour runs from white-hot through yellow, orange and red to nothing over 0.8-1.6 s. |
| fireball to smoke | each billow, 40 % into its life, leaves a smoke billow (alpha-blended, top-lit shading in the texture so a flat quad reads as a lump). The billow starts warm, lit by the fire inside it, and cools to grey as it rises. |
| smoke column | for `smoke_seconds` (10) the spot keeps sending billows up, 10 per second falling to 3. They live 4-6.5 s and grow to about 3.4 x their size at birth. The fresh ones carry the fire's glow for the first 2 s. |
| flash | a glow billboard over the blast that lasts about 0.1 s, then a weaker glow for about 1.4 s |
| ground light | an additive radial pool of orange light about 7 tiles across, on the ground under the blast. It follows the same curve as the flash. |
| car light | a D3D point light (orange, range 5 tiles) on the car models (`car_bodies.cpp`) while the flash lasts. Plain renderer only: under RTX Remix the additive billows are emissive particles and light the street themselves. |
| shock wave | an additive ring that races over the ground to about 5 tiles in 0.55 s, plus 28 dust billows thrown out radially along the road |
| sparks, burning bits | 44 streaks and 12 slower orange bits on ballistic arcs (gravity 3 tiles/s^2). Each bounces once on the ground. |

The game's own blast sprite stays underneath, dimmed to `sprite_percent` (35 %).

Near the eye (FIX-FX, 9 Nov; first person at the wheel of a car that blows up): the flash, the
ground light and the shock ring scale with the eye's nearness to the blast (to 0.25, 0.55 and 0.475 of
their level at its heart), the game's big effect sprites stood up round the eye fade to a fifth
inside 1.2 of their size, and the car light is bounded at 0.7 (a flash of 2-3 on top of the sun
washed a car body to flat cream). The ring texture is 256 texels with no hard step in its fill.
The burning-car flames and the fire and tyre smoke (`live_geometry.cpp`) face the camera in the
street views and fade inside half to two of their sizes from the eye: laid flat, as the top-down view
wants them, a puff at eye height was a screen-wide grey veil and a risen flame an orange plate in
the sky. The classic view keeps them flat.

Draw cost: five `DrawIndexedPrimitiveUP` batches a frame (ground glow, ring, smoke, fire, glow),
with vertices built on the CPU in world space. The particle cap is 1600; one car blast peaks at
about 280 live particles. The textures are procedural and built once per device. It all runs in the
street views only (`g_uprightPeds && g_fxUpright`). The classic top-down view is unchanged.

## Settings

`[explosions]` in `package/gta2dx9.ini`: `enabled`, `size_percent`, `flash_percent`,
`smoke_seconds`, `sprite_percent`, `car_light`, `eye_budget_percent` (FIX-FX-3, below). Setting `GTA2DX9_EXPLOSION_FX=0` in the
environment turns the effect off for one run (for A/B frames).

**A blast on demand for QA (FIX-FX-4):** `[devtools] force_blast=1` (then 2, 3, ...: any change to a
number above 0 acts once) blows up one car through the game's own damage routine, with the player
alive; `force_burn=N` only sets it alight. Recipe:
`GTA2_DIRECT_KEYS=1 FPS=30 INI_SED='s/^scene_key=.*/scene_key=F10/' STAGE=<stage> gamerun/grun.sh <name> 160 keys_fx4_blast.sh -e GTA2DX9_STATE_EVERY=3 -e VIEW=third|first [-e BURN=1] [-e DIST=4]`
(runner `linux/docker/keys_fx4_blast.sh` + `fx4_blast.py`: F10 car, out, facing along the street, the
view, the trigger, `qa_d_blast_*` shots, `game.mp4` at 30 fps; ends with a `RESULT blasts a->b lives x->y`
line). Details in "FIX-FX-4" below.

## Verification (8 Nov 2026, private stage, L4 host)

Scenario `gamerun/qb19_blast.py` (keys `keys_qb19_blast.sh`), run as
`grun.sh <name> 420 keys_qb19_blast.sh -e GTA2DX9_PROBE_CARDMG=31300 -e GTA2DX9_LOG_CAR_WORDS=1`
with `GTA2_DIRECT_KEYS=1` and the devtools scene key. The player jacks a passing car. The probe sets
its damage to 31300, the next knock sets it alight, and it goes up with the chase camera on it.
Screenshots are taken every ~0.4 s from the knock onwards.

- Run `qb19_fx2`: log `explosions: blast at 161.6,2.27,105.6 ... 136 particles`, one blast per
  car, no `FAULT`. Frames over 0-4 s after the blast show:
  - an orange, soft-edged fireball with sparks and burning bits in flight;
  - the fireball rolling into a dark column that rises over the roofs, with fire glowing at its base;
  - the ground lit orange around the wreck;
  - the shock ring on the road (seen in the earlier run `qb19_fx1`, 0.9 s after the blast).
- First tuning pass (`qb19_fx1`): too many overlapping additive billows burned the fireball out to
  white, and the smoke billows had hard lobed rims ("black flowers"). The second pass lowered the
  billows' brightness, softened the billow rim, and made the smoke greyer and larger with a slower
  fade-in.
- Before (`GTA2DX9_EXPLOSION_FX=0`, same scenario, run `qb19_off`): the blast is the game's blocky
  orange-white sprite stood up as a flat billboard over the car, with hard pixel edges, no smoke
  column and no light on the road. The A/B sheet is `out/qb19_ab_sheet.png` (local, not in git
  because it contains game art). Top row: before, frames 0.0-2.8 s. Bottom row: after, same
  timing.

What is not verified:
- Under RTX Remix: no path-traced frames of this yet.
- With `[visuals]` (bloom) on.
- First person.
- Grenade and rocket blasts: they go through the same detection but were not shot in frame.
- Night (the ground light should read best there).

## Open

- Fixed (FIX-FX-2, pm10, 9 Nov): the small dark lobed scraps ("black and white flowers") were
  `vehicle_fx.cpp`'s blast debris: one radially symmetric seven-pointed shard texture, unlit, in
  the car's paint x 0.35-0.6 or near-black. Proved by a run with this module off
  (`GTA2DX9_EXPLOSION_FX=0`: the flowers stayed) and the game's base-8 sprites hidden (they stayed).
  The debris is now a 2x2 atlas of irregular shards (panel, trim strip, splinter, torn corner),
  a third the size, lit by the scene's light with a glint as it turns, 30 % of it glowing hot for
  its first second. The game's own translucent/additive artwork (flags 0x2180/0x2280: the blast's
  ring of fire on the ground, number 342) had been drawn as an opaque, point-sampled cut-out (a red
  disc with a black stepped rim); in the street views it now keeps the game's blend, smoothed
  (`live_geometry.cpp` GamePuff; `GTA2DX9_GAME_BLEND=0` turns it off). `GTA2DX9_LOG_FX=1` also logs
  the game's draw flags per sprite number (`fx flags:`).
- The ground light is a decal on the road only. Walls are lit only when `[visuals]` lights are on,
  which needs a provider hook in `visuals.cpp` (VISUALS-PLAIN owns that file).
  `ExplosionFxLight()` already returns the light it would need.

## FIX-FX-3 (10 Nov 2026): the first-person / death-camera blast wash, attributed and budgeted

Work order `fire-fx-first-person-blast-wash-and-no-fire-light` (item: the road visible, over 40 % of
the frame not flash, at a first-person blast). FIX-FX-2 left it partial: its worst blast frames were
0.52-0.69 of the frame flash (lum > 200, or hot orange) in 7 of 8 runs, with the cause unattributed.

**Attribution.** `GTA2DX9_BLAST_PROBE=1` logs every frame while a blast is under 1.5 s old:
- the eye's distance to it;
- each additive part's full-frame equivalent (its level x min(1, (size / eye distance)^2), summed over
  the batch): fireball billows, spark streaks, flash glow, ground light, shock ring (and smoke);
- from `visuals.cpp`, the fire lights within reach of the eye (day-weighted).

In the first runs (`out/fx3_bp_1`, HEAD + the probe):
- at the wheel, eye 0.6-0.8 blocks from the blast: billows 1.6-1.75 frames, sparks up to 1.8, ring 0.25,
  glow and ground light about 0.2 each;
- at the death camera, eye about 2.6 blocks: ground light 0.6, glow 0.27, billows 0.2-0.3;
- the fire lights: one blaze, day-weighted 0.06-0.27 round the eye.

So the wash is the additive FX themselves, not the light pass. The fireball's billows and the spark
streaks dominate, and the streaks were not held down near the eye at all: they are long yellow-white
bars radiating across the whole frame in FIX-FX-2's failing frames (`out/fx2_t_fp`, `fx2_q_fp`,
`fx2_x_fp` `qa_d_blast_00`).

**Fix** (`explosion_fx.cpp`):
- Spark streaks fade as the eye comes within their length (`nearFade` on the streak, as the billows have).
- An additive budget round the eye: the parts' full-frame equivalents are summed every frame. Over
  `eye_budget_percent` (default 50, i.e. half a frame), the colours of all additive batches (ground
  light, ring, billows, glow and sparks) are scaled down together, so the blast keeps its shape and hue.
  The probe line ends with `additive <sum> x <scale>`.
- Typical scales: 0.12-0.24 with the eye at the wheel, about 0.46 with it 1.3-1.5 blocks off (a chase
  camera pulled in beside the car, `out/fx3_burn3b`: the fireball, shards and ring still read), and
  about 0.45-0.5 at 2.7 blocks (a death camera, `out/fx3_bp_1` sums). So a close third-person blast is
  dimmer than FIX-FX-2's pm10 frames; how far off a blast must be to escape the budget is not
  measured. The ground light's share is counted as if it faced the eye, which overstates it for a low
  eye; the budget was tuned with that measure.

Seven first-person runs (`gamerun/fixfx2_burn.py`, `VIEW=first`, the same script as FIX-FX-2's) are tabled
on the work order. The evaluator is `tools/fx3_blast_eval.py`: the frames shot within 1.6 s of the
blast's log line, and the worst share of flash among them.

## FIX-FX-4 (10 Nov 2026): a deterministic blast for QA

Triage could not film a blast: `set_car_damage` writes the damage word of the car he drives, so
31990 killed him at once (he is its driver), and a lower value burned without blowing up unless a
knock happened to land. Four attempts failed (work orders `fire-fx-first-person-blast-wash-...`,
`pm10-third-wasted-...`).

**How it works** (`explosion_fx.cpp`, `DevtoolsBlast` and `ExplosionFxGameTick`):
- Every 15 street-view frames the `[devtools]` keys `force_blast`, `force_burn`, `force_blast_car` and
  `force_blast_dist` are re-read (documented in `package/gta2dx9.ini`). The values at load are the
  baseline, so a key left set does not fire at start.
- On a change, a car is picked from the game's vehicle list:
  - never the one he drives, never one under 2.5 or over 30 blocks from him, no wreck, the same level;
  - `near` (default): the car nearest the point `force_blast_dist` (tenths of a block, default 40)
    ahead of him along the camera's view, preferring the cars within 40 degrees of the view, so it is
    in frame in third and first person;
  - `own`: the last car he drove in a street view.
- At the next `gbh_BeginScene` (the game's logic for the frame is done, its draw has not started)
  the car's damage word (+0x74) is set to 31999 (blast) or 15999 (burn), then the game's damage
  routine `FUN_00427180` (thiscall: car, amount 1, hit point) is called. That one-point hit walks the
  game's own sequence: alight at 16000 (`FUN_004226C0`), the second fire at 25000, lamps out at
  31500, the explosion `FUN_00426FA0` at 32000. The game's blast sprite, sound, wreck model and
  splash damage follow, so this module, `vehicle_fx.cpp`'s debris and the wreck draw all see a
  real blast.
- **The hit argument is a world point**, x/y/z in 16.14 fixed: the car's own placement is passed.
  An offset (0.5, 0.5) there put the fire's sprite at the map corner, and the game faulted in its
  draw-grid insert `FUN_004479D0` a few frames later (runs `fx4_bl_t2`, `fx4_bl_t4`; the second was
  already called from `gbh_BeginScene`, so the timing was not the cause).
- Log: `devtools: force_blast N: car <p> model M at x,y,z, D blocks from the player ... (queued ...)`,
  then `devtools: force_blast on car <p> at the frame's start: ... damage a -> 32001`.

**Verified** (private stage, wil, GPU-GL, 30 fps). Each run below logged its blast (`vehicle feel:
... blew up`, `explosions: blast at`), had no `FAULT`, and kept the player's lives at 5 -> 5 and his
health at 100:
- `fx4_bl_t7`, third person: the car 5.1 blocks ahead, the fireball in the middle of the frame
  behind the van he left;
- `fx4_bl_f8`, first person: a van 3.2 blocks ahead;
- `fx4_bl_f9`, first person (see the work orders for its frames).

`fx4_bu_t5` (`BURN=1`): damage 0 -> 16000, the car alight, no fault in the 40 s after.

**A blast was noted twice** by this module, 1.7-2.0 s apart at the same spot (`fx4_bl_t6`..`t12`):
a second fireball over the wreck. The game's sprite at the very spot (within half a block) up to 3 s
after a blast's first sight is now the same blast (`ExplosionFxNote`). In `fx4_v_f1` the second line is
1.5 blocks off: a neighbouring car caught in the chain. A late blast line about 12 s on, with a
0.85-tile sprite, is not attributed yet.

### FIX-FX-4: smoke cut by walls, and the ink-blot smoke ball (work orders fire-fx 3d, pm10 FX half)

Frames opened from the trigger's takes (`fx4_bl_t10`, `fx4_v_t1`, `fx4_v_t2`) showed two faults:
- **Billows cut by buildings.** A smoke billow beside a building cut into its facade and roof. Its
  front part showed as a dark block with straight vertical and horizontal edges (`fx4_bl_t10`,
  `qa_d_blast_059`).
  - Fix: every billow (smoke and fire) is drawn pulled toward the eye by 0.6 of its size, scaled to
    cover the same part of the view, so it clears any wall within that reach behind it.
  - Not done inside 0.6 sizes of the eye, where the near fade already acts.
- **Ink-blot smoke.** The fireball's own smoke (grey 0.16-0.26, opacity 0.62) clumped into one
  near-black disc over the white-hot core once its fire light had faded (1.2 s): the "black ink
  blob" of pm10 (`fx4_v_t1` `qa_d_blast_037`, `fx4_v_t2`).
  - Fix: that smoke is now grey 0.27-0.37, a little brown, opacity 0.50, and fire-lit for 2 s.
  - The column rising off the wreck stays dark: burning cars give black smoke.

### FIX-FX-4: red chips at a shooter's feet (work order pmw10, every automatic burst)

Flat, pure-red (241,0,0) parallelograms lay on the paving at the hero's feet during a burst, in third and
first person, with the silenced machine gun, the machine gun and the pistol. Attribution (runs `fx4_mg_1`,
`fx4_mg_dbg2`, `fx4_mg_hide3`, `fx4_mg_hide4`, probe `linux/docker/keys_fx4_mg.sh`):
- `GTA2DX9_LOG_SPRITE_KINDS=1` listed, during the burst, a 2x3-texel `base 4 number 15` sprite drawn flat
  at ground level at his position.
- Its mean colour is `cf0000`, pure red.
- Left out by a private switch, the red was gone from every frame.
- Leaving out code objects 8/432-435 instead (4x4 texels, brass-coloured flecks) changed nothing.
- The bullets 8/503-505 reach the effect list and are drawn as the streaks at gun height.
- Gibs are off by default and `synthetic_lights.cpp` draws no geometry, so neither suspect named in the
  report was involved.

**Fix** (`live_geometry.cpp`, beside FIX-FX-2's game-blend block): code object 4/15 is left out in the
street views. The shot's debris there is `ShotFxMuzzle`'s brass case from the ejection port. The classic
view draws it as before.

**Verified** (`fx4_mg_fix5` against `fx4_mg_1`, same probe, the plaza, bursts from the side, facing the
camera and in first person): frames with saturated red in the ground half of the picture went from 25 of
66 to 0 of 66. The brass cases and muzzle flashes are unchanged.
