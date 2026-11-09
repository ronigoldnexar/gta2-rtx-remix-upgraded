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
`smoke_seconds`, `sprite_percent`, `car_light`. Setting `GTA2DX9_EXPLOSION_FX=0` in the
environment turns the effect off for one run (for A/B frames).

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
