# BEV parity check (Wave C)

The owner's bar: the classic top-down view stays one key away, and the game's own mechanics are
untouched by the 3D views. This tool checks both from a real game session. It compares the
classic bird's-eye view (BEV) against the 3D views: same world state, same mechanics, no drift.
The evidence is frames from both views of the same moment, the renderer's log, and the live
`gta2.exe` code read from outside the game.

Agent BEV-PARITY, 9 Nov 2026. Runs `out/bev_parity1` to `bev_parity4` (local, not in git).

## Run it

```
# one session (about 4 min of game time; queued on the game slots)
GTA2_DIRECT_KEYS=1 FPS=0 SHOTS_EVERY=30 INI_SED='s/^scene_key=.*/scene_key=F10/' STAGE=<private stage> \
  gamerun/grun.sh bev_parityN 300 keys_bev_parity.sh \
  -e SETTINGS_EXTRA=/work/bev_parity.settings -e BEV_TRANSITION=12 -e BEV_SCENE_KEY=F10 \
  -e GTA2DX9_PEDS_EVERY=2 -e GTA2DX9_STATE_EVERY=2 --cap-add SYS_PTRACE
# the report (any python3 with numpy and Pillow)
python3 tools/bev_parity.py out/bev_parityN [report.md] [sheet.png]
```

| File | Role |
|---|---|
| `linux/docker/keys_bev_parity.sh` -> `gamerun/` | keys script: `to_level.sh`, then the runner |
| `linux/docker/bev_parity.py` | runner in the container: switch moments, the same walk in every view, memory probes; events with times and log offsets in `/out/bev_events.json` |
| `linux/docker/bev_mem.py` | memory probe: reads the running `gta2.exe` through `/proc/<pid>/mem` (needs `--cap-add SYS_PTRACE`). Diffs every code byte against the exe on disk and follows the two view-rectangle operands to the values the game uses |
| `linux/docker/bev_parity.settings` | `[camera] TransitionSeconds=12` for the run, so the first 3D frame after V is still at the classic camera |
| `tools/bev_parity.py` | analyser: report `.md`/`.json` and a contact sheet (classic, 3D at the classic camera, third, first, classic again, \|classic - 3D\|) with every logged object circled |

The DLL is not changed. Everything the tool reads is already in the log: `view: player`,
`view: cars`/`view: peds` (every 2 frames with the env above), and `cam[N]` (the game's continuous
camera extent, every 64 frames). The memory probe reads the game from outside, so it does not rely
on the renderer to report on itself.

## What "the same moment" means here

GTA2's pause cannot be reached by key in these runs. `p`, `Pause` and `Escape` all left the world
running (`bev_parity1`, keys.log). So the tool does not freeze the world. It takes the classic frame,
taps V, and takes the next frame 0.65-1.25 s later. The camera move to third person is stretched to
12 s (smoothstep), so in that frame the camera has moved 1-2% of the way and is still the classic
camera, while everything drawn is the 3D view's content: models, avatars, props, sky pass.

Each object (player, cars, peds) is then compared at its own logged position for each frame's time,
interpolated between log samples, and projected with the game's camera extent: px = centre +
(world - centre) x 720 / extent height, with a perspective term for height. The player stands
still throughout. The frame time comes from the ffmpeg start plus 0.1 s, accurate to about 0.1 s.

## Checks

| # | Check | Pass when |
|---|---|---|
| 1 | No object jumps at any view switch (classic->third->first->classic, twice) | no logged object steps more than 0.6 blocks/frame within 3 s of a switch |
| 2 | Classic view one key away | after the full cycle the game's camera extent is identical, the frame is within 1 px, and terrain (objects masked) differs by >24 on <1% of pixels |
| 3 | 3D world registered on the classic frame | phase-correlation shift <= 4 px (the camera move has started) |
| 4 | 3D bodies centred where the sprites are | median centroid offset of drawn pixels (3D body vs sprite, each about its own logged position) <= 0.15 tiles |
| 5 | 3D bodies cover as much of the top-down frame as the sprites | 3D/sprite drawn-pixel ratio 0.5-2, per kind (player, ped, car) |
| 6 | Car paint | median colour of each car's drawn pixels within 60 RGB of the sprite's |
| 7 | Same input, same mechanics | the same keys (Up 2 s, Left 0.5, Up 1.5, Right 0.5) with the game's own controls (`GTA2_DIRECT_KEYS=1`) in classic, third, first, classic: free walking speed per game frame within 3%, turn rate per frame within 10%, game frames per wall second >= 90% of classic |
| 8 | `gta2.exe` code | every patched site attributed to a DLL source (table `PATCH_OWNERS`); the same set in every view |
| 9 | The game's spawn/cull window | classic: the shipped rectangle widened only to the 16:9 frame (`spawn_offscreen=1`). 3D views: reported as a NOTE (by design) |

The NOTE rows ("3D bodies that look like the game's sprite from above") are gradient correlation
between sprite and model. They show which bodies resemble their sprite. They are not a verdict,
because a model never looks exactly like its sprite.

## Findings (runs `bev_parity3` and `bev_parity4`, Downtown, the road at 164.5,149.5 and the walk from there)

Verified in the running game. Each finding is backed by frames from both views of the same moment
and by the report in the run folder.

**Mechanics: untouched by the views.**
- Walking speed per game frame is 0.0625 blocks (1/16) in classic, third and first person, in both
  runs: 0.0625/0.0625/0.0625/0.0625 in run 3, and 0.0623/0.0626/0.0635/0.0627 in run 4. Against a
  wall it halves (about 0.031) in every view alike.
- The turn rate is 12.1-12.8 deg/frame in every view (within 4.2%; the spread is sampling, two
  samples a turn).
- No object jumped at any of the 12 switches: 23-40 objects tracked each time, largest step 0.24
  blocks/frame, which is a car at speed.
- `gta2.exe` has 34 patched code sites, the same 34 in all 10 snapshots per run (classic, third,
  first, classic again, twice). All are attributed: 17 audio (`voice_over.cpp`), 7 presentation
  (`hud_pass.cpp`: HUD parts, arrows, the stage-end message whose script still advances), 5 movie
  (`intro_movie.cpp`), 2 observers that resume the game's own code (`gibs.cpp`), 1 front end
  (Options -> F4 panel), and 2 view-rectangle operands (`world_view.cpp`). None of them changes
  when you press V. Only the values behind the view-rectangle operands do.
- **The one mechanics difference is by design.** While a 3D view is up, the game's spawn/cull
  window is 2.6x wider (`[camera] GameViewScale`) and square: 31.25 x 41.66 tiles against
  12.02 x 6.76 in classic, read from the game's memory and its log. Cars and peds are created and
  removed over that larger area. The live ped count stayed the same (median 11-13 in every view),
  so the game's population cap still rules. In classic the window is the shipped one, widened only
  to the 16:9 frame (x1.333 width, x0.75 aspect), which is `spawn_offscreen=1`.
- Controls in the 3D views with the shipped `nav_map=1` are camera-relative: the renderer presses
  the game's turn keys for you. That is a control mapping, not a rule change. The walk above uses
  the game's own keys, so it measures the game's stepping.

**The classic view is one key away.** After classic->third->first->classic the game's camera
extent was identical to the logged precision in all 4 moments. 3 of 4 came back pixel-exact on
the terrain (0.00-0.77% of pixels differ by >24, all at moving traffic). `bev_parity3` moment A
came back 1 px off vertically (2.5% of terrain pixels at edges): a sub-pixel camera settle, not
reproduced in run 4. Open.

**Same world in both views.**
- Terrain registers on the classic frame (shift 0-3 px; mean |diff| 0.2-9 on 0-255, the higher
  values where the camera move had begun 0.65 s earlier).
- The 3D bodies sit where the game's sprites are. Drawn-pixel centroids are 0.025-0.077 tiles
  apart (median per moment), worst 0.155.
- Cars cover the same area from above as their sprites (ratio 0.96-0.98). Peds cover 0.64-1.35.

**Defects found (open, for the streams named):**
1. **Car paint does not always match the game's colour** (cars stream, #2). In `bev_parity3`
   moment B, 3 of 4 cars on the road had the wrong colour in the 3D view at the same moment:
   - model 63 (`063_truck_cab`): sprite orange (121,90,43), 3D near black (38,45,42)
   - model 68 (`068_van`): sprite green (108,152,127), 3D olive (56,51,36)
   - model 50 (`050_b_type`): sprite light grey-blue, 3D olive grey

   The same model 63 matched in `bev_parity4` (115,112,65 vs 109,98,58), and moment A of run 4
   matched 4 of 4. So this is per car (its remap/paint), not per model. Frames:
   `out/bev_parity3/bev_B0_classic.png` against `bev_B1_3d_at_classic_camera.png`.
2. **The player's figure is small from above** (people stream). The 3D avatar covers 0.34x the
   sprite's pixels in run 3 B and 0.63x in run 4 B. Other peds are at 0.64-1.35. From the classic
   camera you see a small head where the game draws a full figure. Its sun shadow falls about 1.2
   tiles away (`bev_parity2`, A frames).
3. **The modern HUD minimap fades in** over the lower-left corner in the first 3D frame. This is
   expected, and the tool masks it out.
4. Under host load (load 71 during `bev_parity4`), the third-person walk ran at 26.2 game fps
   against 29.8 in classic. The per-frame mechanics were unchanged, but the game ran 12% slower in
   wall time for that stretch. Other runs: 29.4-30.0 in every view. Recheck on a quiet host before
   calling it a 3D cost (see `docs/performance.md`).

## Limits

- The world is not frozen, so the two frames of a moment are 0.65-1.25 s apart. Objects are
  compared at their own logged positions for each frame, with about 0.1 s of frame-time
  uncertainty. A car at 0.2 blocks/frame moves about 0.6 tiles in that time, so moving cars give
  noisy colour and position numbers.
- Peds and cars are logged only within 24 and 30 blocks of the player (the nearest 28 and 20).
  Objects outside that are not masked or checked.
- Sprite-vs-model resemblance (NCC) is a NOTE: sprites and models are meant to differ.
- The check covers on-foot play in one district. Driving (the 3D car under the player) and the
  other districts are not in these runs: use `SWAP_LEVEL` and a driving moment next.
- The memory probe needs `--cap-add SYS_PTRACE` on the container. Without it the memory rows fail
  with a permission error, and the rest of the report still runs.
