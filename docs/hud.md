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
| Mini-map: a disc turned with the camera, player arrow, north on the rim (FIX-HUD-4) | bottom left | the level's columns (top lid by ground type: road, pavement, field, roofs by height), drawn as vectors |
| Gang respect: three meters, the gang's emblem and a split track (FIX-HUD-4) | top left | gang pool `[0x5EB898]`, 0x144 a gang: name `+2`, the player's respect int8 `+0x11C` (-100..100, a bar is 20) |
| Objective blips (yellow, pulsing; a chevron on the rim when off the map) and phones (cyan) | on the map | HUD arrow slots `[0x672F40]+0x1F18` (17 of 0x7C: type `+0x20`, target `+0x44/+0x48` 18.14 fixed); types 1-4 are phones |
| Health bar (flash on a hit, red screen-edge pulse at 30 or less) | under the map | ped `+0x216` (100 full) |
| Car condition bar (orange from 16000, when the car burns) | beside health | car damage int16 `+0x74` (32000 explodes) |
| Phone chip ("PHONE RINGING, n blocks" / "ANSWER THE PHONE") | right | nearest phone arrow within 10 blocks, on foot |
| Brief card: the speaker's portrait, the words, `#`-marked words in yellow | bottom centre | the message key at `0x5E9808` (the game's last text lookup) when the game's subtitle block first shows, bound to that block's glyphs (see below), looked up in the player's `data\e.gxt` (TKEY/TDAT); the portrait is the largest quad of the game's HUD part 10, redrawn |

Armour: no armour field of GTA2's is known yet, so no armour bar is drawn.

## Which of the game's HUD parts are dropped

`hud_pass.cpp` already tells the 19 calls of the game's HUD draw apart. With the modern HUD
on screen, the overlay drops parts 1 (score, lives, multiplier, weapon), 4 (the row of icons
centred at the top: the wanted heads), 5 (the gang respect bars, FIX-HUD-4, when the gang pool read), 6 (hearts), 11 (clocks and counters) and 10 (the
talking head) - the last only when the brief's text was found in `e.gxt`, so an unknown
message keeps the game's own box.

One renderer at every frame (FIX-HUD, 9 Nov 2026):

- The subtitle (pm15-third-two-subtitle-renderers-overlap-pixel-font-over-minimap). `0x5E9808` is the
  game's *last text lookup*, not the subtitle on screen: a second into Industrial's opening brief (3230)
  it reads `svscore` (the save point's text) while 3230 is still up, so the old numeric-key test handed
  part 10 back to the game mid-brief and both subtitles drew. Now the block's first eight glyphs (their
  texture coordinates, small quads of part 10) are a signature, bound to the buffer's key the first frame
  that signature appears; later frames with the same signature keep that key whatever the buffer says.
  A key already bound to another signature is a stale lookup: that block stays the game's (with the
  mini-map lifted). On a block's first frame part 10 is swallowed if the buffer's key is in the gxt, so
  the game's text never shows for a frame first. Log: `hud3d: brief: a new subtitle block (n glyphs)
  bound to key 'k'`, and `brief=1(k)` on the two-second line.
- The view switch (pm7-classic-to-third-switch-shows-both-huds-overlaid). The game's parts of a frame
  are swallowed or not by the state at the end of the frame before, so the modern HUD no longer fades
  in: it appears at full strength the frame after the switch (the switch frame shows the game's HUD
  only), and on the way back it is drawn the last frame its parts were swallowed and gone the next.
- The weapon block (pm9-third-ammo-panel-translucent-box-bleeds-into-scene) has no glass card: ammo,
  name and the game's icon (with a dark offset copy as its shadow) right-aligned under the lives in
  the money's shadowed type.
- The top plates (pm2-fp-location-banners-stack-and-clip-at-top, `overlay.cpp` Flush,
  `Hud3dTopPlates`). In the street views the zone name (part 7) and the car's name (part 8), which the
  game puts in one slot, are stacked: the car's name under the zone plate (eased when the zone plate
  goes; a zone plate the game has faded under alpha 48 keeps no room). In first person in a closed car both
  drop out from under the cockpit's roof lining: `CabHeaderScreenBottom` (cab_interior.cpp) projects the
  lining's lower edge through the view the cab is drawn with, so the plates follow the cab class and the car's
  pitch (Z-Type ~85 of 480, Medicar ~11-50), scissored there so a sliding plate passes under the lining. An
  open top (CabOpenTop) has sky there: the plates keep the game's slot. Log: `hud: top plates ...` on each
  change. The classic view keeps the game's placement.
- Street-view swallowing is decided at the end of the frame before; the switch dissolve (`switch_dissolve_percent`)
  holds the modern HUD off (`Hud3dHoldForSwitch`, world_view.cpp) because the kept classic frame carries the
  game's HUD: the game's live HUD sits under its own copy, and the modern HUD cuts in when the dissolve ends. Everything else stays the game's: the arrows and markers
over targets (world-anchored), the zone name (placed, see the plates above), the big messages ("JOB COMPLETE"), the pause
screen.

During a WASTED or BUSTED beat in a street view (FIX-HUD-2, 9 Nov 2026; pm9-fp-wasted-death-cam / pm10-third-wasted) the HUD is
none at all: the modern HUD fades fully out (a job-complete beat still leaves 8%), and the game's corner parts 1, 4, 5 (the
respect bars), 6 and 11 are swallowed whether or not the modern HUD is active. He is usually no longer readable as the player
then (`player not found`), so the modern HUD went inactive and the game's weapon, ammo and respect bars came back, half under
the letterbox bars. The beat's own title, wash and bars are drawn by `DrawBeat`; part 15 (the game's message) was already swallowed.

FIX-HUD-3 (10 Nov 2026; pmq10-third-busted-caption, pm10-third-wasted): the beat's title is drawn in the classic view's
colour and weight: opaque, a vertical yellow-to-orange fill (255,241,66 at the top of the ink, 255,122,40 at its foot,
measured on the game's own BUSTED!) in an indigo outline (72,56,138) with a dark drop shadow, in the upper third where
classic sets it (below the top bar), at full strength 0.12 s after the message (it had faded in over 0.4 s in the beat's
cast colour, so the playtest caught BUSTED! at 15 % as a dark navy stamp on the grass at his feet), over the fade to black,
and out with the cut. The rule under it keeps the beat's cast. While the bars slide in or out, every panel the modern
HUD draws (money, stars, lives, weapon, mini-map, subtitle) is moved inside the letterbox picture by the bars' height
(top half down, bottom half up, clip rects with them), so nothing is cut by a bar as it fades (`BeatBarPx`, `Draw`).

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
  In third person (FIX-HUD-3, 10 Nov 2026; pmx9-bil-third-aim-reticle-drawn-on-hero-back) it is
  drawn only while he aims: from a shot to 1.2 s after it (the figure raises the gun for about a
  second after each shot and carries it at low ready otherwise), in within 0.04 s, out over 0.12 s.
  It is never drawn over him: his figure's box is
  projected each frame (feet to 0.50 block, 0.07 block either side) and a reticle inside it (plus 4 px) is not drawn (a wall just ahead of
  him put the line's end on his back from the chase camera). Log every 5 s: `aim: reticle frames
  (third person, armed) shown= hidden_idle= hidden_on_hero=`. First person is unchanged.
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
- **The game's score pop in the street views (FIX-HUD-2, 9 Nov 2026; pm50-bil-third-score-pop-100-giant-translucent-green-billboard-over-street,
  feel4-reward-text-balloons-over-truck-in-third).** The green digits the game zooms up over a kill or a payout are not a HUD part
  and not a world sprite: the object code at `0x004B9424` draws each digit (font sprite `0xA3` + digit, translucent, scaled by the
  pop's +0x34, faded by +0x36) through the shared screen-sprite routine `FUN_004CBA50` (return `0x004CBDA0`, also used by the
  front end and HUD parts 2/13), laid out on the game's top-down camera. In 0.4 s a digit grows from ~50 to over 300 of 480
  game pixels (run fh2_jack_b5, probe `GTA2DX9_LOG_SCREEN_QUADS=1`): over a 3D view that was a screen-filling translucent
  green slab not even placed on the car. `hud_pass.cpp` points that one call at a stub that raises a flag (`HudPassTakeScorePop`);
  `Overlay::Quad` asks `Hud3dScorePop`: in a street view with the modern HUD up the digit is dropped (the `+$n` pop above rises
  from the car instead), in a street view with the game's HUD (`modern=0`, a pause, a death beat) it is held to a tenth of the
  screen's height about the screen's middle line; the classic view draws it as the game does. Log: `hud3d: score pop in a
  street view: n glyph quads dropped ..., m held ...` (at most once a second); `hud pass: installed (... score pop told apart)`.
  Other callers of the routine (front end 0x453705/0x453753, 0x4582EE, the HUD's markers) are untouched.
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

While the game draws its own talking head and subtitle (part 10, bottom left, whenever the brief's text is
not ours to show) the mini-map and the bar under it slide up 84 px out of that band and back when it is
gone (defect pm-hud-minimap-covers-subtitle-and-portrait: the panel ate the first word and the portrait).
Verified in out/tri_hud2 (s_02_trans_to_third, s_03_third, s_10_first; classic s_17 unchanged).

### Hardening (BLOCKER-objective-arrow-magenta-outline-on-player-both-modes, 9 Nov 2026)

The blocker's evidence (`DEMO_live_gameplay_20261109.mp4`, t=125 s and t=165 s: a pink/magenta
arrow outline on the figure's chest, a green and a violet chevron at fixed screen spots) is the
game's own target arrows: part 13 sprites, the pink job arrow and the green/violet gang arrows.
That capture ran at 12:00 on the 8 Nov stage, before af1dc60 (its log has no `hud3d:` line).
On a stage with af1dc60 the sprites were still drawn whenever the modern HUD was not active
(`modern=0`, the pause screen, a frame the HUD's values could not be read), because the swallowing
was gated on it. Now:

- Parts 2 and 13 are swallowed whenever a street view's camera is up and `objective_markers=1`,
  whatever the modern HUD's state; never in the classic view (`CurrentViewMode()` is checked live,
  so the first classic frame after leaving a street view already has the game's arrows).
- The markers are drawn on their own fade, also with `modern=0`.
- The on-screen marker is a filled, shaded pin (lit left half, shaded right half, a highlight on the
  head, a drop shadow) pointing down at the target, bobbing slowly, sized by distance (larger near),
  with the distance above it. It faces the camera by construction (screen space).
- It never sits on a wall: if a wall (a side face with the game's collision bit, `ViewLineWalled`)
  is between the eye and the spot over the target, the pin is lifted over the target a block at a
  time until the line clears (up to 9 blocks: a beacon over the roofs); if nothing clears it (a
  far target behind the block) it is shown by the edge chevron instead, as an off-screen one. In third person the whole pin is pushed above the figure's screen box.
- The edge chevron is shaded the same way.
- Every two seconds in a street view the log has `hud3d: markers: view= modern= slots= frames:
  arrows= pins= lifted= blocked= edges=; game arrow sprites swallowed=`.

Verified (FIX-MARKERS, private stage = f4b5544 + this change, GPU runs at 1280x720, 0 FAULT in every run):
`out/fixm_final` (warped to 190.5,95.5 near a ringing phone): third person, the yellow job pin "116m"
lifted over the low wall into the sky; first person, the cyan pin on the phone; the game's arrow sprites
swallowed every street-view frame. `out/fixm_pass2` (keys_pt_pass.sh at the spawn, walk and drive):
the job target 104 blocks off behind the church is shown by edge chevrons only, nothing on the figure or
a wall. `out/fixm_off1` (`modern=0`): the game's HUD kept, its target arrows gone, chevrons drawn.
Classic: `vr_spawn_classic.png` of `out/vreg_fixm_fix` and `out/vreg_fixm_base` (HEAD without the
change) are the same file (0 pixels differ), with the game's pink/green/violet arrows in it; the vreg
FAIL set (spawn_third, spawn_first, portrait, lights23/m37 chase) is the same on the baseline (goldens
older than af1dc60 and the FIX-CAMERA boom). The sheet is `out/fixm_final/fixm_evidence.png`.
Untested: a mission target close by in plain view on foot (only the phone object was), Remix.

## FIX-HUD-4: the round mini-map and the respect meters (owner playtest, 10 Nov 2026)

The owner played on an RTX 5090 under Remix at 2560x1440 and asked for two things: "increase the
resolution of the nice map located in the bottom-left corner, and change its shape from square to
circular" and "the three bars in the top-left corner appear to have too low a resolution relative to
the overall look" (`OWNER-PLAYTEST-10nov-seven-findings` items 6 and 7).

**The mini-map** was a 256x256 texture, one texel per map cell, magnified about 7.6x at 720p (15x at
1440p) with bilinear filtering: every cell a soft square, the roads' edges blurred. Now (`BuildMap`,
`DrawMapDisc`, `ClipDisc` in `dll/src/hud3d.cpp`):

- Once per level each cell gets a tone (the old picture's classes: road, pavement, low roofs, field,
  roofs and decks lighter by height; a field one green at any height); one-cell speckle (a cell with no
  side neighbour of its own tone and five of eight neighbours of one other tone, never a road) is merged
  into its surroundings; each tone's cells are merged into maximal rectangles (Downtown: 4780 over the
  commonest tone, which is the disc's fill). No texture is kept (the 256 KB managed texture is gone).
- Each frame the rectangles near the player are turned with the camera and drawn as screen-space
  polygons with ImGui's one-pixel anti-aliased edges, each grown by 0.6 px so neighbours overlap (no
  seam); those that cross the rim are cut exactly to the circle (`ClipDisc`: the polygon's inside edges
  and the rim between where it leaves and comes back, a 96th of a turn a step). Every edge is resolved at
  the output resolution: there is no texel density to run out of at 1440p or 4K.
- The disc is 200 units across (200 px at 720p, 400 at 1440p) at the old square's scale (260 units over
  34 blocks on foot, 64 in a car: 7.6 px a block at 720p, 15.3 at 1440p); the player sits 18 % of the
  radius below the centre, so more of the street ahead shows. A thin warm rim over a dark one, north as
  a chip on the rim, the player arrow outlined. Objective blips off the disc sit on the rim as a yellow
  chevron along the line from the player to the target; phones off the disc are not drawn; the pulse
  ring is not drawn where it would cross the rim. The lift over the game's own subtitle (above) moves the
  whole disc and the bars under it.
- Colours: the HUD's ImGui backend raises every vertex colour to the power 2.2 (a Remix sRGB patch in
  `imgui_impl_dx9.cpp`: kGreen 92,204,96 shows as 27,156,29 under plain GL and under Remix alike), while
  the old map was a texture and was shown as written; the tones go in as their 1/2.2 power, so the disc
  shows the old map's colours.
- Cost: that same backend patch called `powf` three times a vertex each frame; it is a 256-entry table of
  the same values now (the bytes sent are unchanged), which took the submit of the HUD from 0.83 to
  0.14 ms a frame with the disc's ~2600 vertices. The whole modern HUD: 0.52-0.54 ms a frame on foot
  (base 0.30, run on the same host; `hud3d: modern HUD ... ms` lines), of which the disc's geometry is
  ~0.11 ms (`hud3d: respect meters ... ms a frame: map respect render` every two seconds).

**The three bars top left** are the game's gang respect meters (HUD part 5, `FUN_004C74F0`: the
gang's emblem sprite, a gradient tube with a marker and the phone tabs under it, about 77x16 game
pixels, scaled 1.5x at 720p and 3x at 1440p), which the modern HUD had left to the game. With the modern
HUD up, part 5 is now swallowed (only once ours were drawn: if the gang pool cannot be read the game's
stay) and `DrawRespect` draws each gang the game lists, in the pool's order (Downtown: Yakuza,
Zaibatsu, Loonies, as the game stacks them):

- the emblem: the Yakuza's yen sign and the Zaibatsu's Z in the money's heavy italic with its black edge,
  the Loonies' winking smiley as vector circles and strokes (Rednecks R, SRS S, Krishna K, Russians RM;
  an unknown name a ? in a colour by the gang's colour byte `+0x138`);
- a pill track split at its middle (respect 0) into five bars a side (a bar is 20 respect, as the
  game's), filled from the middle out in the gang's colour (Yakuza violet, Zaibatsu teal, Loonies green)
  to the right, red to the left (they hate you), with a bright cap at the fill's end;
- three pips under the track at 0, 2 and 4 bars, green, yellow and red: the respect the green, yellow and
  red phones ask for (`docs/missions.md`), lit once reached.

The weapon icon and the speaker's portrait are still the game's own sprites (redrawn, scaled): the
last two pieces of game art in the modern HUD.

Developer aids: `GTA2DX9_HUD_TEST=1` re-reads `[hud] test_respect=a,b,c` (the player's respect with the
first three gangs in use, set once per change); `GTA2DX9_HUD_GANG_DUMP=1` logs each gang record's bytes
once. Probe: `gamerun/keys_fh4_hud.sh` (wil spawn: classic, third still/turned/walked, first still/turned,
classic; respect poked to 60,-40,100 then 20,0,-100) with
`INI_SED='s/^\[hud\]/[hud]\ntest_respect=0,0,0/' -e GTA2DX9_HUD_TEST=1`; `SCREEN_W=2560 SCREEN_H=1440` for 1440p.
