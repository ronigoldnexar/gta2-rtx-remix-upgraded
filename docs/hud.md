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

The classic view never shows the modern HUD; switching views fades it in and out (0.12 s).

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

## Developer aids

- `GTA2DX9_HUD_TEST=1`: F6 sets the player's health to 15, F8 starts a 75 s clock through the
  game's own call (`0x4C9310`, HUD counters, "add a clock").
- `hud3d:` log lines: the values every two seconds (`money= shown= mult= lives= health=
  wanted= weapon= ammo= car= timer= counter= msg= brief= portrait= icon= arrows= parts=`),
  and the cost every 300 frames.
- `gamerun/hud_sheet_run.py` (`keys_hud_sheet.sh`): the comparison run in Industrial.

## Measured

RESULTS_PLACEHOLDER
