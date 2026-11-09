# The modern HUD (street views)

GTA2's HUD is a set of small 4:3 sprites placed at fixed pixels. Over the top-down view
that is the game; over a 3D street it reads as dated. In third and first person the
renderer now draws a HUD of its own from the same game values, and drops the game's
sprites for those parts. The classic view is untouched: the game's own HUD, as always.

"GTA 6 built on GTA 2": a clean, minimal layout, but the GTA2 flavour kept - a heavy
condensed italic with a black edge (as GTA2's score), GTA2's warm white, yellow and red,
the game's own weapon icon and the speaker's own portrait.

## Switching

`[hud]` in `gta2dx9.ini`:

| Key | Default | Meaning |
|---|---|---|
| `modern` | 1 | 1: the modern HUD in third/first person; 0: the game's own HUD there too |
| `minimap` | 1 | the mini-map |
| `scale_pct` | 100 | size, 50..200 (sized for the window's height) |
| `toggle_key` | (none) | a key that switches modern/classic while playing, e.g. `F7` |

The classic view never shows the modern HUD; switching views fades it in and out (about a third of a second); the pause screen hides it.

## What it shows and where each value comes from

| Element | Place | Game value |
|---|---|---|
| Money, ticking to the new value, "+$n" pop on a gain | top right | score keeper's GetMoney (`game_save.cpp`) |
| Multiplier chip, lives | under the money | score keeper `[[0x5EB4FC]+0x38]` +0x6BC, +0x684 |
| Wanted: six stars, the earned ones filled and pulsing | under that | ped cop points int16 `+0x20A` (stars at 600/1600/3000/5000/8000/12000) |
| Weapon card: the game's own icon, name, ammo (red under 5) | top right | ped weapon object `+0x170` (type `+0x1C`, ammo `+0`, shown /10; -1 = INF); the icon is the largest quad of the game's HUD part 1, redrawn |
| Clock (mm:ss, blinks red under 10 s) and counter | top centre | HUD object `[0x672F40]+0x7E8`: four 12-byte slots, `+0` clock in ticks (30 a second, < 0 none), `+4` pointer to a counter's value |
| Mini-map turned with the camera, player arrow, north | bottom left | the level's columns (top lid by ground type: road, pavement, field, roofs by height) |
| Objective blips (yellow, pulsing; a chevron on the rim when off the map) and phones (cyan) | on the map | HUD arrow slots `[0x672F40]+0x1F18` (17 of 0x7C: type `+0x20`, target `+0x44/+0x48` 18.14 fixed); types 1-4 are phones |
| Health bar (flash on a hit, red screen-edge pulse at 30 or less) | under the map | ped `+0x216` (100 full) |
| Car condition bar (orange from 16000, when the car burns) | beside health | car damage int16 `+0x74` (32000 explodes) |
| Phone chip ("PHONE RINGING, n blocks" / "ANSWER THE PHONE") | right | nearest phone arrow within 10 blocks, on foot |
| Brief card: the speaker's portrait, the words, `#`-marked words in yellow | bottom centre | the message key at `0x5E9808`, looked up in the player's `data\e.gxt` (TKEY/TDAT); the portrait is the largest quad of the game's HUD part 10, redrawn |

Armour: no armour field of GTA2's is known yet, so no armour bar is drawn.

## Which of the game's HUD parts are dropped

`hud_pass.cpp` already tells the 19 calls of the game's HUD draw apart. With the modern HUD
on screen, the overlay drops parts 1 (score, lives, multiplier, weapon), 4 (the row of icons
centred at the top: the wanted heads), 6 (hearts), 11 (clocks and counters) and 10 (the
talking head) - the last only when the brief's text was found in `e.gxt`, so an unknown
message keeps the game's own box. Everything else stays the game's: the arrows and markers
over targets (world-anchored), the zone name, the big messages ("JOB COMPLETE"), the pause
screen, the respect bars.

The hook: one line at the top of `Overlay::PushTriangleFan` (`dll/src/overlay.cpp`, marked
`MODERN HUD`), which is where every 2D draw of the game is classified as HUD and by part.
`src/renderer.cpp` is not touched (the sprite classification is in the overlay, not there).
The draw call: one line in `WorldView::RenderFrame` (`dll/src/world_view.cpp`), after the 2D
layer and before the F4 menu.

## How it is drawn

Dear ImGui draw lists in a context of its own (the F4 menu keeps the other), through the
same DX9 backend, inside the frame's scene. Text is Barlow Condensed (ExtraBold Italic for
numbers, Bold Italic for labels, SemiBold for the briefs), rasterised at the exact pixel
size the window needs and re-baked when its height changes, so it is sharp at 720p and 4K
alike (not SDF: exact-size rasterisation). Shapes (stars, bars, map, chevrons) are
anti-aliased vectors.

Font: **Barlow Condensed** by Jeremy Tribby, SIL Open Font License 1.1
(`assets/fonts/OFL-BarlowCondensed.txt`). Subset to Latin-1 with fontTools
(`assets/fonts/*-hud.ttf`) and embedded in the DLL by `tools/gen_hud_font.py`
(`dll/src/hud3d_font.inc`), so nothing extra has to be staged.

## Aiming: reticle, target, hit markers and the aim camera (QB-6)

GTA2 has no aim: a bullet leaves the gun along the way the pedestrian faces. The street views
now show that line and what is on it.

- **Reticle** (`hud3d.cpp`, `UpdateAimHud` / `DrawAimLayer`): on foot with a gun in his hands
  (`ViewAim().armed`: a weapon object, not down, not in a car door) and the modern HUD up. Four
  ticks round a dot, white; it sits on the first person standing on the line of fire, or where
  the line meets a wall (binary search with the camera's own block query, `ViewLineBlocked`),
  or 8 blocks out. A shot opens the ticks for a quarter of a second.
- **Target**: the nearest person on the line, inside a corridor of 0.32 block + 0.03 per block
  of range (the game's bullets were measured landing up to 0.45 block off the line at 4 blocks),
  within the weapon's reach (10 blocks for pistols and machine guns, 6 shotgun and thrown, 3
  flamethrower and electro gun, 12 rocket), within 1.2 levels of height, not behind a wall.
  With one the reticle turns red, sits on his chest and red corner brackets frame him.
- **Shots** are the game's own word (`view_modes.cpp`, `UpdateAim`): the gun's ammunition word
  dropped, or its reload timer restarted (a kill frenzy's ammunition never drops), with the
  same weapon object in his hands.
- **Hit markers**: a person's health word (`ped+0x216`, read in the sprite pass and published
  by `LiveAimPeds()`) drops within a second of a shot while he is near the line of fire: a
  white X round the reticle for 0.25 s, a larger red X for 0.45 s when he goes down (health 0),
  and a small cross over him in the world. A fall with no health change (a car, a shove) is not
  a hit.
- **Aim camera** (third person, `view_modes.cpp`): armed, the chase eases 35 % of the way to the
  aim framing; for 2.5 s after a shot it is fully there: 30 % closer, 35 % lower, 0.30 block
  further over the right shoulder, looking 1.6 blocks further down range, 8 degrees narrower,
  and the yaw swings behind his facing (the line of fire) on a 0.3 s spring unless the mouse
  moved in the last `tp_return_delay`. Each shot kicks the view up 0.3 degrees, back in 0.1 s.
  First person needs none of it: the view is his facing, the reticle sits near the middle.
- Projection: `LiveWorldToScreen` uses the view-projection of the frame's `LiveGeometry::Draw`.

Developer aids: `GTA2DX9_LOG_AIM=1` logs, three times a second, the nearest person in the open
(game coordinates), the reticle's pixel and whether a target is highlighted (`aim: near`);
every 10 s after the first shot an `aim: shots= with_target= hits= on_highlighted= kills=
reticle_frames=` total, and each hit (`aim: hit`). `[devtools] set_player_ammo=N` keeps the gun
in his hands loaded for scripted shooting. Probe: `gamerun/aim_probe.py` (`keys_aim_probe.sh`;
`GTA2_DIRECT_KEYS=1`, scene key F11, `set_player_ammo=300` added by `INI_SED`): picks up the
COLLECT_02 machine gun, turns to the nearest person from the `aim: near` line and fires bursts in
third and first person with a screenshot every ~0.1 s.

## Developer aids

- `GTA2DX9_HUD_TEST=1`: the `[hud]` keys `modern`, `test_health` and `test_clock` are re-read
  from the ini once a second, so a script switches the HUD and pokes the game by editing the
  file (no key the game might take): `test_health=N` sets the player's health to N,
  raising `test_clock` starts a 75 s clock through the game's own call (`0x4C9310`, HUD
  counters, "add a clock"). Test-only; never in the shipped ini.
- `hud3d:` log lines: the values every two seconds (`money= shown= mult= lives= health=
  wanted= weapon= ammo= car= timer= counter= msg= brief= portrait= icon= arrows= parts=`),
  and the cost every 300 frames.
- `linux/docker/hud_sheet_run.py` (`keys_hud_sheet.sh`; Downtown: on foot, weapon, clock, low
  health, driving, wanted) and `hud_sheet_bil.py` (`keys_hud_sheet_bil.sh`; Industrial: the
  opening brief, the walk to the Zaibatsu phones, the phone answered), both with
  `INI_EXTRA=/work/hud_test.ini.extra -e GTA2DX9_HUD_TEST=1` on `grun.sh`;
  `hud_sheet.py <png> <run> [<run>...]` builds the sheet.

## Measured

Runs `hud6` (Downtown) and `hud7` (Industrial), 8 Nov 2026, L4 host, 1280x720, wined3d on the GPU
through VirtualGL, the DLL built from `camera-modes` plus this change only. Sheet:
`out/hud_modern_sheet.png` (local, not in git): the same moments, the game's own HUD left and
the modern one right, 1.4 s apart (the `[hud] modern` switch is re-read once a second).

- Values agree with the game's: money/multiplier/lives against the `view: mission` line; the
  machine gun's ammo 300 shown as 30, as the game's icon reads; the 75 s clock counted down at
  30 ticks a second (2203 -> 2128 in 2.5 s) and ran out to none; wanted 3 drew three stars and
  the game's part 4 (its cop heads) only then, which is how part 4 was confirmed as the wanted
  row; the car bar followed the damage word (1632 after a knock).
- The weapon icon is the game's own sprite (49x40 game pixels), the portrait the game's own
  (50x58/60). Briefs: Industrial's opening brief (key 3230) in `hud7`, Downtown's information
  phone brief (1607, picked-out words in yellow) in an earlier run on the same code; the
  phone prompt ("PHONE RINGING, 4-6 blocks", the cyan blip) on the walk to the Zaibatsu
  phones. The scripted walker did not get up onto the phones' terrace, so a job brief after
  answering is not on the sheet.
- Cost of the modern HUD on the render thread (the `hud3d:` 300-frame averages): 0.35-0.6 ms a
  frame on foot, 0.9-1.4 ms with the clock and the low-health edge pulse on screen (four
  full-screen gradients). Single frames up to tens of ms showed up in the same windows as
  the whole frame's hitches on a loaded host (load 10-14); the first frame bakes the fonts and
  builds the mini-map (a 256x256 texture, once per level).
- Mini-map orientation checked against the street ahead at a crossroads (driving north) and a
  boulevard with a median (wanted, on foot).
- 0 FAULT lines in either run.

Not covered: a counter (`+4` of a counter slot; no job with an on-screen counter was played),
armour (no field known), Remix (drawn after the UI composite, like the F4 menu; not seen under
the path tracer), resolutions other than 720p (the fonts re-bake on a height change; untested
on screen).

## Pickup labels and score pops (QB-50, 8 Nov 2026)

QUALITY-BAR row 50. Code: `DrawWorldLayer` in `dll/src/hud3d.cpp`, drawn on ImGui's background
list (under the panels) from `Draw`; the pickups and the projection come from
`dll/src/map_objects.cpp` (`MapObjectPickups()`, `MapObjectsProject()`, `MapObjectsEye()`), read
back from the device's view and projection when the street views drew the objects.

- **Labels.** Over every floating pickup (the manifest's `spin` objects) between 0.45 and 7 blocks
  from the eye: its name on a dark pill with a cyan underline, full strength to 4 blocks, fading
  out to 7 and in from 0.45 (so the one under his feet does not cover the view), shrinking a
  little with distance. Names come from the model: `pickup_machine_gun` -> MACHINE GUN, the
  silenced machine gun and dual pistols spelled out, the briefcase BRIEFCASE, every power-up
  token POWER-UP (which power-up a token's colour stands for is not mapped), the three unnamed
  items PICKUP. Labels are not tested against walls: one behind a building within 7 blocks still
  shows.
- **Pops.** A money gain floats `+$n` (yellow) up from the player's chest; a weapon picked up (the
  ammo of the weapon in hand rising, or a new weapon in hand within 0.6 s of passing within 1.2
  blocks of a pickup) floats its name (green) up from that pickup. Both rise half a block with a
  small punch on arrival and fade over 1.6 s. In first person a pop that would start within
  0.8 block of the eye starts 1.2 blocks ahead of it instead. The game's own 2D texts (the
  weapon name, the score digits over a victim) still show.
- `GTA2DX9_PICKUP_LABELS=0` turns the layer off. Log every 2 s: `hud3d: world layer: pickups
  drawn=N (nearest D from the eye) labelled=L (peak, frames with a label) pops money= weapon=`.

Measured (`qb49_after4`, 8 Nov 2026, plain renderer, probe `gamerun/qb49_probe.py`, see
`docs/navigation.md` "Near fade"): the machine gun at map 166.5,140.5 labelled MACHINE GUN at
4.15 blocks in third person and at 1.9 in first person, 60 of 60 HUD frames with a label in
each 2 s window; the rocket launcher (154.5,129.5) labelled ROCKET LAUNCHER, and on collecting
it the green ROCKET LAUNCHER pop rose from the pickup's spot beside the game's own text.
Untested: the money pop in play (no kill or paid event in the probe; it is the same drawing path
as the weapon pop), a token's label in play (none near the probe's spots), Remix.

## Objective markers in the street views (defect pt-2d-arrows-float-over-3d-figure, 9 Nov 2026)

The game's target arrows (its 17 HUD arrow slots, parts 2 and 13) are flat sprites laid out round
the player for the top-down camera; in third person they hovered on the figure's chest and in first
person they sat mid-screen. With `[hud] objective_markers=1` (the default) the modern HUD swallows
those two parts in the street views and draws each live slot through the 3D camera instead
(`DrawObjectiveMarkers`, dll/src/hud3d.cpp): a diamond over the target with its distance in metres
(a block is two metres) when it is on screen, pushed above the figure's screen box when it would sit
on him, or a chevron on an ellipse inside the screen edge pointing round the camera toward it when
off screen or behind. Kind 5 (a place to go: the job's own and the gang arrows) is yellow and always
shown; other kinds (a phone, a car, a person) are cyan and shown within 20 blocks. `objective_markers=0`
keeps the game's sprites. The classic view always draws the game's own arrows, byte for byte.
Verified in out/tri_hud1 (s_04_third_walk, s_11_first_walk, s_01_classic_walk).
