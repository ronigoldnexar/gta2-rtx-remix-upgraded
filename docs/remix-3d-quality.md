# RTX Remix in the 3D views: continuity with the classic view, and the player's shadow (REMIX-3D-QUALITY, 9 Nov 2026)

Follows REMIX-3D-PARITY (`docs/remix-3d-parity.md`, cherry-picked into `camera-modes` with this pass).
That pass audited every Remix feature of the classic view (upstream gebdag/gta2-rtx-remix) against
third and first person and found the 3D views get the same mesh, tile materials, emissives, water
tiles, sky, clock, game and synthetic lights and post. It fixed the one pop, the far lamps. This pass
tries to close the gaps it left, re-measures continuity with a corrected take, and records what failed.

All runs: Downtown, GPU 0 of the 8x L4 host, 1280x720, the play preset (`rtx_play.conf.extra`), the
gta2hd layer (`MODS_HD=1`), a private stage (this branch's DLL). Run folders `out/r3dq_1`..`r3dq_7` are
local, not in git (game art). 0 `FAULT` lines in all seven logs.

## 1. Continuity: the same moment in every view, and the V press (run `r3dq_3`)

The take (`linux/docker/remix3dq_take.py`, REMIX-3D-PARITY's take plus the changes below) stands the
player still at three spots (a roof at 203.5,237.5,4, the plaza at 198.5,188.5, the start) at 10:00,
14:00 and 22:30. At each spot it records classic -> five frames of the camera move -> third -> first ->
five frames of the move back -> classic again. `tools/remix_3d_parity.py out/r3dq_3 1800` makes the
report and sheets: `out/r3dq_3/r3d/side_by_side.png`, `switch_<moment>.png`, `report.md`.

**Take fix: the classic frame waits for the game camera.** In REMIX-3D-PARITY's take, and in this
pass's first run `r3dq_1`, the "classic before" frame of 3 of 4 moments was taken while the game's own
camera was still scrolling to the player after the warp, so it showed another street. `settle_classic()`
now waits until the game camera's centre (`cam[]` +0x98/+0x9C, logged every 64 frames) is within a block
of the player twice in a row. In `r3dq_3` it settled in 6-11 s at all 9 moments, and the game camera was
the same before and after the cycle at all 9 (`report.md`, "same game camera True").

| check (24 V presses, 9 moments) | result |
|---|---|
| objects (BEV-PARITY check 1) | no logged car, ped or player stepped more than 0.4 blocks a frame within 3 s of a V press (a car at speed); 0 teleports |
| black frames in the 2.5 s after V | 0 of 24 |
| classic again vs classic before, night | 0.01 % and 0.61 % of pixels differ by more than 24 (traffic) |
| classic again vs classic before, day | 1.8-17 % (see the clock, below) |
| the move | continuous both ways (`switch_*.png`); the neon's red light on the steps at the start is in the same place in classic, third, first and classic again |

**Why the day pairs differ: the sun moves with the clock "paused".** `r3dq_4` took two classic frames
60 s apart with no key pressed (`out/r3dq_4/r3d/clock_test.png`): a shadow appears on the walkway, and
the 14:00 pair's tree shadow moves. So the daytime differences are the sun moving between the two frames,
not anything the 3D views left behind. The run's settings hold `[timeofday] Paused=1` and the code
reads it as paused (settings.cpp, time_of_day.cpp, weather.cpp `clock_paused=-1`), so the cause is not
found. Filed: `/mnt/gta2/defects/open/remix-sun-moves-with-clock-paused.md` (time of day / weather owner).
Every Remix take that compares "the same moment" by day is affected.

**Identity gap found: trees that only the 3D views have.** On the roof at 203.5,237.5 the 3D views stand
several trees (third and first person, every hour). The classic view at the same moment shows a bare
green roof (`side_by_side.png`, rows am_roof/pm_roof). The plaza's tree is the same. They appear and vanish at the V
press. Filed: `/mnt/gta2/defects/open/3d-only-trees-not-in-classic.md` (props stream #8).

**Inherent, as REMIX-3D-PARITY found:** the auto exposure meters each view's frame, so the brightness
steps after a switch (`report.md` brightness table: up to 44 of 255 in the first frames after V, then
adapting over `darkAdaptTau`/`lightAdaptTau`).

## 2. The player's shadow in first person: attempted, not working, off by default

In the classic view the player's sprite casts a shadow under Remix. In first person on foot his figure is
not drawn (`fpHideOwnBody`), so he casts none. Remix has a mechanism for this (dxvk-remix source:
`rtx_types.cpp` `setupCategoriesForTexture`, `rtx_instance_manager.cpp`, `geometry_resolver.slangh`): an
instance whose colour texture hash is in `rtx.playerModelTextures` gets the player-model ray mask. With
`rtx.playerModel.enableInPrimarySpace=False` (the default) primary rays skip it and
`enablePrimaryShadows=True` keeps its shadow. His avatar is also 14 civilian types' avatar, so its own
textures cannot be tagged.

**What was built** (in the DLL, off by default: `[remix] own_shadow_first_person=0`):
- `model_store.cpp`: `ModelSetPlayerTextures(true)` makes model draws bind a per-texture copy that differs
  in one bit of the first texel. The copy's hash is computed in the DLL as the runtime's own,
  `XXH3_64bits` of mip 0 (`d3d9_common_texture.cpp`; vendored `dll/deps/xxhash/xxhash.h`, BSD-2). It is
  pushed as `rtx.playerModelTextures` through the API.
- `live_geometry.cpp`, `world_view.cpp`: in first person on foot under Remix with the key on, the player's
  sprite is kept, never drawn flat (`Sprite::shadowOnly`), and his figure is drawn with the copies.
- QA switches: `[devtools] own_shadow_first_person=0/1` (A/B in one session), `own_tagged_third=1` (his
  figure drawn with the copies in third person, where body and ground are both in the picture), the log
  line `remix: own figure hash candidates ...`.

**What the runs showed:**
- `r3dq_1`-`r3dq_3`: the runtime accepted the four hashes (`own figure: 4 player-model textures tagged
  (taken)`). In 48 first-person frames with it on, no part of his body appears in the picture. No shadow
  is visible either. At 16:30 he stood in building shade. On the roof the mouse tilt meant to put the ground at his
  feet in frame never moved the camera: one move over 8x `mouse_max_step` is dropped, and the free look
  returns after `FirstReturnDelay`. The 20 px steps of the later take still did not tilt it (cause not
  found). A first-person A/B cannot show the shadow without that tilt.
- `r3dq_4`, `r3dq_6`: third person with `own_tagged_third=1`. **The body stays visible** at every heading
  (`out/r3dq_6/r3d/diag.png`).
- `r3dq_6`, `r3dq_7`: the same four hashes under `rtx.hideInstanceTextures` (through `[devtools]
  remix_config`, "set" in the log) do not hide the body either. Nor do four other schemes logged by the DLL
  for each copy: XXH64, rows bottom-up, red/blue swapped, the empty texture (`out/r3dq_7/r3d/diag.png`). So
  either the runtime does not key these 512x512 A8R8G8B8 uploads by any of those hashes, or a hash set
  changed at run time through the API does not reach the draw-call categories in this runtime build.
- Since IDENTITY-SYSTEM (95e79c9), under Remix a figure's split texture pair is drawn from a merged texture
  (`FigurePairMerged` in `model_store.cpp`) that does not go through `TextureFor`. The player copies then
  cover only the figure's unmerged meshes. A rework has to copy the merged texture too.
- Not done: a positive control. Hiding a texture whose hash is known to match, for example a world tile of
  the gta2hd layer through the same `remix_config` line, would tell those two apart. One Remix session.

**Consequence beyond this feature:** the gta2hd layer's 552 model materials (cars, props, avatars,
`docs/remix-materials.md`) are keyed the same way, by XXH3 of the uploaded rows. They were matched against
the texture files, never seen in a frame by a colour probe as the tiles were. If the positive control shows
the runtime keys model textures differently, those materials are not applied. Filed:
`/mnt/gta2/defects/open/remix-model-texture-hash-unverified.md`.

## 3. Run it

```
# the take (keys_remix3dq.sh, remix3dq_take.py and remix3dq.settings go to gamerun/)
STAGE=<stage> REMIX_GPU=<gpu> gamerun/remix_l4.sh r3dq_3 1800 /work/keys_remix3dq.sh \
  -e MODS_HD=1 -e LEVEL_WAIT=30 -e RTX_EXTRA=/work/rtx_play.conf.extra -e GTA2_DIRECT_KEYS=1 -e SCENE_KEY=F11 \
  -e "INI_SED=s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/" \
  -e "SETTINGS_SED=s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=10/" -e SETTINGS_EXTRA=/work/remix3dq.settings \
  -e GTA2DX9_LOG_LIGHTS_EVERY=2 -e GTA2DX9_PEDS_EVERY=2 -e GTA2DX9_STATE_EVERY=2 \
  -e "R3_SPOTS=roof:203.5,237.5,4;plaza:198.5,188.5,2;start" -e R3_HOURS=am=10.0,pm=14.0,night=22.5 \
  -e R3Q_SHADOW_HOURS=am,pm -e R3Q_HEADINGS=8 -e R3Q_PITCH=600 -e R3_WARM=120
python3 tools/remix_3d_parity.py out/r3dq_3 1800          # frames, sheets, report
python3 tools/remix_3dq_report.py out/r3dq_3 1800          # this take's own marks: shadow, tagged, diag, clock sheets
```

Take options: `R3Q_SHADOW_HOURS` (first-person A/B), `R3Q_TAGGED_HOURS` (third-person tagged A/B),
`R3Q_DIAG_HOURS` + `R3Q_DIAG_SCHEMES=1` + `R3Q_DIAG_WALK` (the hash diagnostic), `R3Q_CLOCK_TEST`
(two classic frames a minute apart, default on), `R3Q_SHADOW_ONLY=1` (skip the continuity moments).
`remix_3d_parity.py` cuts only its own marks; `remix_3dq_report.py` cuts the `_sh_`, `_tg_`, `_dg_` and
`_clk_` marks with its `video_start`/`cut` and writes `shadow_*`, `tagged_*`, `diag_*`, `clock_*` sheets.

