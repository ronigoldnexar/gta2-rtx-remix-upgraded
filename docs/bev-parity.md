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

## BEV purity at the switch (BEV-PURITY, 9 Nov 2026)

The owner saw the character turn lighter in the top-down picture at the moment V was pressed.
Measured with `gamerun/keys_bevpurity.sh`: a lossless 30 fps recording across the press, and the
mean and the dark-pixel count (luminance < 60) of an 80x70 box around the player.

- **Cause.** On the first frame of the move out of the classic view, the camera is still the
  classic camera, but the frame is drawn the street view's way. The player's dark sprite becomes
  the 3D figure seen from straight above, the ground switches to the photo tiles and the HUD
  switches to the modern one. The whole frame changed by a mean of 14.2/255 in one frame. The
  box's dark pixels went from 262 to 20, the box mean from 126.0 to 131.3.
- **Not `[visuals]`.** The same step appears with `[visuals] enabled=0` (14.18, 262 -> 18). The
  post chain is gated on the transition weight (`PostFx::BeginScene`: `frame.blend > 0.002`, and
  `Renderer::SetWorldShading` returns early without fog). That weight is 0 whenever the classic
  view is settled, so no post pass ever runs on a settled classic frame.
- **Fix: a dissolve from the last classic frame.** The renderer copies every settled classic frame
  (`Renderer::KeepFrame`, one StretchRect of the back buffer; the presented frame is not
  touched). The move then opens on that copy, drawn unblended and point-sampled over the street
  view's frame. It dissolves out over the first `[camera] switch_dissolve_percent` (45) of the
  move. Measured in-process (`GTA2DX9_DISSOLVE_VERIFY=1`): the first frame of the move is the
  last classic frame with **0 pixels different**. The box now changes gradually (262 -> 256 ->
  222 -> 146) as the eye starts to come down. The first changed frame differs from the classic
  frame by a mean of 0.58/255, not 14.2.
- **Acceptance: the classic view with `[visuals]` on and off.** Standing classic sessions of 30 s
  at 5 fps (150 frame pairs per district, the new DLL). Compared on the pixels that never change
  in either run, which excludes moving peds, cars and animated tiles:

  | district | static pixels | hash, visuals 1 | hash, visuals 0 | static pixels differing, worst pair |
  |---|---|---|---|---|
  | wil | 90.73 % | 606dbaf9c00b6847 | 606dbaf9c00b6847 | 0 |
  | bil | 93.69 % | 3b5e8a126039c00c | 3b5e8a126039c00c | 0 |
  | ste | 54.82 % | b95848b7670a5871 | b95848b7670a5871 | 0 |

  Every pixel that differs between the runs is on a moving object. In bil, 7 of 150 whole frames
  are bit-identical (no ped happened to differ). The new DLL against the live one (`ac0e16a`),
  wil classic, visuals on: 99.47 % static, the same hash, 0 pixels differing.
- **Limits.** Plain renderer only: under RTX Remix the back buffer does not hold the path-traced
  picture, so `KeepFrame` keeps nothing and the move cuts as before. While the dissolve runs,
  the frozen classic frame and the moving street view show as a double exposure for about 0.6 s.
  The 3D figure from above is still lighter than the sprite. That is the player-identity defect
  (`/mnt/gta2/IDENTITY_MECHANISM.md`), which the dissolve hides but does not fix. The way back
  into the classic view draws the classic presentation from the V press on, and has no step at
  arrival.

## The switch as one camera move (FIX-SMOOTH-SWITCH, 9 Nov 2026)

The owner rejected the dissolve above ("an animation effect I don't want; I want a smooth camera
transition"), and the cut it replaced. `[camera] switch_dissolve_percent` is now 0 (a fallback
only; `tools/merge_stage_ini.py` treats a stage's old 45 as a retired default, not an override).

- **Measured first** (dissolve 0, build 51918f7, wil 159.5,139.5, lossless 30 fps over two V
  cycles, `gamerun/keys_ss.sh`, 4 CPUs): the identity work had not removed the jump. On the frame
  after a later press, with the camera barely started, the whole frame changed by 12.1/255 and the
  80x70 player box went from 262 to 689 dark pixels: the sprite became a small figure in a black
  contact-shadow blob, the ground went to the photo tiles, the mini-map and a second score block
  appeared. The way back (first person -> classic) jumped 55/255 on its first frame: the classic
  presentation came back at once (props and the street-only wall fill gone, the game's HUD), and
  the path's building lift put the camera 0.75 blocks up in one frame.
- **What the picture shows follows the camera, not the key** (`StreetPresentation`,
  world_view.h). V only starts the move. The content that is one thing or the other (the game's
  sprites or the figures and models, props, the street-only fill, the eye caps, the modern HUD,
  car bodies with height) changes over at half the move's eased progress, where the camera moves
  fastest; both directions. The ground's material cross-fades from the plain HD tile to its
  photo copy on the same triangles over 0.3..0.7 of the progress (`Renderer::SetStreetView`,
  two texture stages; no screen overlay, so nothing is doubled). Contact shadows fade in after
  the change-over. The game's objective arrows are hidden while the camera moves (they are laid
  out for the classic camera). Sky, fog, sun and far lamps were already eased.
- **The path.** The lift out of buildings is eased (look-ahead along the path, at most 3
  blocks/s, from 0 at the start) instead of added in quarter-block steps per cell. The height
  goes geometrically between the two ends (the picture changes with the height's ratio), so the
  climb out of first person no longer tears past a wall a metre away. The chase camera's wall
  clearance (`eyecol::Clear`) is applied only within 3 blocks of the destination and blended in
  by the distance: over the whole move it snapped the camera next to the destination whenever a
  rail crossed the line to it (a two-frame close-up of the stairs in the middle of the first move).
- **Result** (build of this change, run `ss_n4_c4`): a later classic -> third press, whole-frame
  change per frame 0.04, 8.8, 13.3, 15.8, 16.8, 17.5, 17.7 ... 16.4 ... 20-28 as the camera nears
  the player, easing to 11.5; no spike at the press or at the change-over. Player box at the
  press 261, 251, 253, 258, 264 dark pixels (was 262 -> 689), then the camera moves off the sprite.
  The first press: moving frames 10-21/255, box 262/257/279, no jump; the TUTORIAL banner stays
  one HUD element (no ghost). The way back starts on the pose last shown and rises continuously;
  its largest frame changes (40-52) are the eye cresting the courtyard roof, a real occlusion
  change, not a cut.
- **Classic unchanged.** Settled classic, 30 s at 5 fps, static pixels, old DLL (51918f7) vs new:
  wil 0 pixels differ (visuals on, and off), new visuals on vs off 0 in wil, bil and ste. bil and
  ste first showed 12 and 1 pixels on the player sprite between old and new; the old DLL run on
  the same assets as the new one gives 0 (bil), so those came from a car-model restage between the
  two stage copies, not from this change.
- **Still short.** The first V of a session still holds the picture three times (0.4, 0.43, 0.23 s
  at 4 CPUs) while sprites and models upload: assigned/first-v-press-freezes-game-up-to-9s-world-upload
  (FIX-PERF-VSWITCH). The figures and models still appear in one frame at the change-over (during
  the fastest part of the move, not cross-faded). The way back from first person climbs a wall face
  at street level.

## Transition artefacts: rapid V, road paint, lamp masts (FIX-TRANSITION-ART, 10 Nov 2026)

Defects pmab5-wil (zebra stripes turn to noise in the tilted frames on the way back to classic) and
pmab5-bil (two giant black masts fill the frame during the switch beside a lamp-lined median). Both
were filmed during six rapid V taps; both also showed in single switches.

- **Measured first** (build fbea4df, `gamerun/keys_fta.sh` at wil 143.5,149.5 and bil 193.4,153.6, a
  warm-up V cycle first, then a lossless 30 fps ffv1 capture of a slow cycle, six taps 0.45 s apart and a
  second slow cycle; `gamerun/rec_grun.sh` with the NVIDIA shader cache, one run at a time on GPU 0):
  - A V pressed while a move was still under way started the next move with its progress `s` at the
    old move's *start* (0 or 1), not where the camera was. The whole presentation flipped in one frame:
    the log showed `tile set street ... material mix 1.000` straight after `classic ... mix 0.000`. The
    game's flat sprites, its HUD and the plain tiles were drawn over a tilted camera, or the figures,
    props and photo tiles snapped in with the eye still high. That is the tilted "classic" frame in both
    defect pictures.
  - The worm noise is the classic HD zebra art itself (`textures_hd/<style>` tiles 256, 264, 672, ...:
    the upscaler drew each stripe as black-and-white worms). It is there in the settled classic view
    too, at classic size (a stripe-hole score of 10.4k px at the wil crossing). The plain set took over
    at s 0.5, where the camera is still tilted and low, so the worms were drawn magnified (18.9k px). The
    street views' re-authored road tiles (`textures_hd/roads`) are clean. Mip chains are complete
    (512, 10 levels): this is not a sampling problem.
  - The masts are the map's own tall street lights (FIX-WORLD-10's round world-mesh poles, five
    levels tall at the bil median; the classic presentation's flat pole cards), drawn whole beside a
    lens that sweeps past them at their own height. The street-prop lamp (1.8 high) was never the cause.
- **Changes** (all limited to camera moves: a settled view draws exactly what it drew):
  1. *Carry the progress.* A new move starts from the `s` last shown (`g_moveS0`) and eases to the
     destination's. The sky blend follows the same `s`. Between two street views `s` stays 1, as
     before. `GTA2DX9_MOVE_S_CARRY=0`: A/B.
  2. *Road paint near classic.* The tiles whose street copy is a re-authored road tile take their own
     material mix, `ramp(0, 0.2, s)` instead of `ramp(0.3, 0.7, s)` (`Renderer::SetStreetView` roadMix,
     `TileMix`). The clean paint holds until the camera is nearly overhead at classic height. The
     classic art then cross-fades in over the move's last ~0.35 s, at the size the settled view shows
     it. `GTA2DX9_ROAD_MIX_EARLY=0`: A/B.
  3. *Fade street lights near the lens during a move.* The mesh records every pole segment, lamp arm
     and classic pole card with its index range (`WorldMesh::streetPoles`). The renderer groups them per
     light and, while the camera moves, fades a light out over about six frames when it stands nearer
     the lens than the hero, its post enters the middle of the frame (x 20-80 %, y 10-90 %; anything
     covering over 15 % of the frame's height by itself counts anywhere), and either its nearest part
     is wider than 4.5 % of the frame's height or width × the share of the frame its post runs across
     is over 0.003. (Without the middle-of-frame test, the spawn's lamp beside the chase camera faded
     during the last frames of the move into third person: vreg `spawn_third` lost it.) It draws the batch around a
     faded light and the fading ones blended after the opaque world, then fades them back once they no
     longer qualify or the move ends. It never runs on a Remix device (draw ranges are hashed) and never
     in a settled classic view. `GTA2DX9_MOVE_POLE_FADE=0`: A/B. The street props (lamp, sign, meter,
     bin, bench, hydrant, mailbox) get the same rule in `DrawProps`; a prop it hides takes its contact
     shadow with it (`GTA2DX9_MOVE_PROP_FADE=0`; `GTA2DX9_MOVE_OCC_LOG=1` logs the candidates).
  4. *No first-person hands from a high eye.* With the progress carried over, a move into first person
     could start from an eye 3-4 blocks up, and FIX-FIGURE-10's "his figure is off the picture → draw
     the hands" rule drew them at the bottom of an overhead frame. That rule now needs the eye within
     1.6 blocks of his feet (`GTA2DX9_MOVE_FP_HIDE_REACH`, 0 = no limit).
- **Result** (build of this change, runs `fta_fin_n9_wil`, `fta_fin_n9_bil`; baseline
  `fta_fin_base_wil/bil` = fbea4df): see the per-move table in the commit's issue comment. In short:
  in wil no frame of any move shows more stripe noise than settled classic shows of itself, against
  16-19k px for the baseline. Rapid V never flips the presentation (each change-over at mix 0.48-0.57).
  In bil the two 5-level poles are logged and faded on every move, and no frame is covered by a mast.
- **Still short.** The settled classic zebra tiles are the noisy upscale. Fixing them changes the
  classic view's pixels and orphans their Remix material hashes, so that needs the owner's decision
  (filed separately). The classic cards' edge-on hairline (FIX-WORLD-10) still shows as a dotted
  vertical in the classic half of a tilted move. Thin, far poles still read as long dark lines in the
  classic half, as any tall pole does from that angle. A faded light comes back over ~0.2 s after a
  move into a street view ends. Rapid V still turns the camera's yaw by up to ~90 degrees in a frame or
  two at the first tap (MoveTurnCap, camera stream), and a developer warp hides the hero (test set-up).

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
