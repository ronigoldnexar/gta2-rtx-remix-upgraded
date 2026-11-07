# RTX Remix on the NVIDIA L4 (6 Nov 2026)

## Result so far
- **Vulkan ray tracing is present**: `vulkaninfo` inside the GPU container lists
  VK_KHR_ray_tracing_pipeline, VK_KHR_ray_query, VK_KHR_acceleration_structure,
  VK_KHR_deferred_host_operations, VK_KHR_pipeline_library on the L4 (driver 580.178.04,
  Vulkan 1.4.312). `out/remix_l4/rayquery_l4_test.txt`: a device with all of them enabled is
  created (`vkCreateDevice ... = 0`). On the B200 the same request returned -7.
- **The Remix server runs on the L4** (run `out/remix_l4_2`): `remix-dxvk.log` reports
  `Device name: NVIDIA L4`, Neural Radiance Cache supported, Opacity Micromap supported,
  Shader Execution Reordering supported, "NVIDIA architecture detected, setting default
  raytrace modes to Trace Ray (Indirect Integrate) and Ray Query (GBuffer, Direct Integrate)".
  Shaders compile ("Compiling shaders (N remaining)" overlay), the game intro, the front end
  and the game world are presented through Remix: `out/remix_l4_2/game.mp4`,
  `out/remix_l4_2_sheet.png`, `out/remix_l4_first_path_traced_frame.png` (the Industrial
  district in the game's attract demo with Remix's lighting, under the welcome dialog).
  The session ran 8 minutes with no crash; `gta2.exe exited 0`.
- NGX (DLSS) is unavailable under Wine as expected (`NVSDK_NGX_Result_FAIL_FeatureNotSupported`);
  the Neural Radiance Cache SDK could not initialise; neither stops rendering.

## What had to change on this host
- The container runtime injects only the compute libraries here, so the Remix image installs
  the matching `libnvidia-gl-580-server` (amd64) itself: `repo/linux/docker/Dockerfile.remix-gpu`
  (image `gta2-remix-gpu`, built on the patched Wine 10 runtime `gta2-wine2510`).
- The ICD path is `/usr/share/vulkan/icd.d/nvidia_icd.json` (script default updated).
- Xvfb must keep its own GLX on Mesa (`__EGL_VENDOR_LIBRARY_FILENAMES=.../50_mesa.json`),
  otherwise the NVIDIA EGL vendor segfaults it.
- Launcher: `gamerun/remix_l4.sh <name> <seconds> [keys] [docker -e ...]` (slot-locked, --cpus=4).

## Runs 3-7: the three views path traced
- Run 3 (`out/remix_l4_3`): the welcome dialog dismissed by keyboard; Remix wrote
  `neverShowFirstUseGuide = True` to its user settings, now seeded by `gamerun/remix_user_settings/`
  so later runs start without the dialog. The level loaded while the startup shader prewarm was
  still running, so the view switches happened on a black screen.
- Run 5 (`out/remix_l4_5`, 3D models off, night): classic, third person and first person all
  render through Remix: `out/remix_l4_5_level_classic.png` (the JESUS SAVES neon throwing red
  light with soft shadows), `out/remix_l4_5_third.png`.
- Run 6 (`out/remix_l4_6`, 3D models and the gta2hd material mod on): no fault, 172 models and
  the 2 673 material textures loaded; first daylight first-person frame `out/remix_l4_6_first_24.png`.
  The game clock override through the ini did not apply (the upstream `gta2dx9_settings.ini`
  overrides it); fixed in run 7 with `SETTINGS_SED`.
- Run 7 (`out/remix_l4_7`, 16:00 paused, models + material mod): all three views in daylight,
  pedestrians as the Rocketbox avatars under path tracing, present 24 ms avg at 1280x720.
  Clip: `deliverables/gta2_linux_rtx_remix_path_traced.mp4` (116 s, cut from the recording);
  sheet: `deliverables/rtx_remix_path_traced_sheet.png` (classic vs first person).

## The black stretches: cause and fix (REMIX-POLISH, 6 Nov evening)

**Cause: not the renderer, not the camera, not the capture.** Three scripted runs with
per-segment black-frame counts (`gamerun/blackframes.py`, 2 fps samples of the recording)
showed the blanking follows *keyboard input*, in every view: idle segments 0 %, a harmless
key (Scroll Lock) tapped once a second 73-85 %, the same key held 95-100 %, Up held 92-96 %,
idle again 8-30 % (the decay). The classic view blanked just as much as the street views;
earlier runs only showed it in the ground views because those were the segments with keys
held (`out/remix_diag2`, `out/remix_diag3`). `xev` on the present window during a key hold
shows a `ConfigureNotify`/`VisibilityFullyObscured` pair every 2.6 s: another top-level
window is raised over it. That window is the runtime's **"new GUI input" overlay**
(`RemixGuiInputSink`, `rtx.useNewGuiInputMethod = True` by default): a `WS_EX_LAYERED`
popup with alpha 0 that the runtime re-raises (`show()`) on every window message it sees,
which with the bridge's DirectInput forwarding is every key event. On Windows the layered
window is invisible; on Xvfb without a compositing manager Wine can only map it as an
opaque black window.

**Fix: a compositor on the Xvfb screen.** `gamerun/run_game_remix_gpu.sh` now starts
`xcompmgr -n` before Wine (`COMPOSITOR=1`, the default when it is installed; image
`gta2-remix-gpu2`, `linux/docker/Dockerfile.remix-gpu2`); with compositing the layered
window really is transparent. Result (`out/remix_comp1`, same key-hold script): **0 black
frames in every segment**, front end included. `rtx.useNewGuiInputMethod = False` also
removes the window but crashes the game a few seconds in (binkw32/page fault, two runs),
so it is not used.

| run | third person | first person | notes |
|---|---|---|---|
| remix_l4_7 (before) | 62 % black | 53 % | the first clip |
| remix_l4_8 (before, models off) | 44 % | 48 % | |
| remix_mat_on (before) | 70 % | 66 % | |
| remix_comp1 (compositor) | 0 % (keys held) | 0 % | all segments 0 % |
| remix_clip5 (compositor, the clip) | 0 % | 0 % | 92 s clip, 0 FAULT |

Two script fixes came out of the same runs: the key scripts now press Return until the
log shows Downtown loaded (`remix_keys_lib.sh: to_level`; the attract demo plays
Residential first, so "player found" alone is not the signal), and a Remix run is only
valid when the game did not hit the intermittent `mss32.dll+0x12353` fault a few seconds
after start (2 of 5 runs with `NO_HD=1`; retry).

**Material mod and the HD tiles.** The runtime hashes what the game uploads. With the HD
DDS tiles installed the renderer uploads 512 px block-compressed textures, so the
`gta2hd` layer (keyed by the 64 px tile hashes) cannot match and the walls are the DDS
albedo with the legacy flat material. With `NO_HD=1` the game uploads the 64 px tiles and
the layer supplies 256 px albedo + normal + roughness instead. The layer was rebuilt for all
three districts straight from the style files (`gamerun/build_remix_mod.sh`:
`tools/dump_style_tiles.py --all` → the current 512 px DDS as albedo → `remix_materials.py`;
2 590 materials, 560 MB, `package/rtx-remix/mods/gta2hd_new`, not committed).

**Deliverables (run `out/remix_clip5`, image `gta2-remix-gpu2`, `keys_remix_clip.sh`, 14:00 game
clock):** `deliverables/gta2_linux_rtx_remix_path_traced.mp4` (92 s, 1280x720: classic →
third person → first person on foot → classic, sun shadows, Rocketbox pedestrians, 0 black
frames in the level, 0 faults) and `deliverables/rtx_remix_path_traced_sheet.png` (classic vs
first person on the same plaza). Cut with `gamerun/remix_sheet.py`.

## Open
- **Black stretches of 1-7 s in the ground views** (run 7: about half of the third/first-person
  segment, none in classic). They coincide with the renderer's sprite stage at 49 ms average
  under the bridge (every model draw crosses to the server) and with Remix's
  "[RTX Opacity Micromap] Out of memory budget" messages, but run 8 (same script, 3D models
  off, 13:00) has the same share of black frames (74 of 179 sampled at 2 fps in the third and
  first-person segments) and no memory-budget messages, so the models and the memory budget are
  ruled out. The classic view never goes black in any run. What remains to check (renderer
  side, not touched here): what the ground views submit that the classic view does not, in the
  order Remix sees it, since Remix blanks a frame when it cannot pick a main camera
  ("Trying to raytrace but not detecting a valid camera" appears once per level load) or
  when the camera it picks changes projection between draw calls ("CameraManager: FOV of a
  camera changed between frames"); candidates are the sky dome (drawn depth-off before the
  world; it is meant to be skipped under Remix), the HUD camera map / UI pass projections, and
  the per-frame `rtx.enableMotionBlur` push on view switches. Single-frame x11grab captures of
  the Remix window are always black, so a capture-side race is also possible; the continuous
  recording is the only capture that works here, and the Remix F12 screenshot path was not
  exercised.
- Stills in the ground views are available (`out/remix_l4_7_first_36.png`,
  `out/remix_l4_6_first_24.png`, `out/remix_l4_5_third.png`, the strips
  `out/remix_l4_7_third_strip.png`), but the clip
  `deliverables/gta2_linux_rtx_remix_path_traced.mp4` contains the black stretches.
- The shader prewarm is about three minutes per run because the prefix is rebuilt each run;
  `gta2.dxvk-cache` is now saved to `gamerun/remix_cache/` and restored, the Remix pipeline
  cache (`rtx.pipelineCache.persist`) did not appear beside the exe in these runs.
- Not verified: whether the gta2hd material overrides are actually applied to tiles (the
  mod loads, 2 673 textures, no hash-match statistics are logged by the runtime); DLSS/NGX
  (unavailable under Wine); the Industrial/Residential districts.
- The Remix welcome dialog holds imgui focus; mouse clicks from xdotool do not reach it and the
  game's keys are swallowed while it is up (run 2 stayed in the attract demo). Run 3 dismisses it
  by keyboard navigation.
- Single-frame `ffmpeg x11grab` captures of the Remix window come out black; the continuous
  recording works, so frames are cut from `game.mp4`.
- Not yet done: the three views under Remix, the gta2hd material mod check, the recording.

## Material layer with the HD tiles: hash found, layer applied (6 Nov, evening)

The runtime hashes the **top mip's block bytes** of an uploaded DXT texture
(`tools/remix_hash_probe.py`, run `out/remix_probe1`: a magenta flat material under that
hash and a cyan one under the whole-chain hash; everything came up magenta). A USD
capture (Ctrl+Shift+Q) is refused while a replacement layer is loaded, so the colour probe
is the verification. `package/rtx-remix/mods/gta2hd` was rebuilt keyed by that hash from
the 512 px DDS sets of all three districts, with normal/roughness maps and glossy
car-paint materials (`docs/remix-materials.md`). Run with `MODS_HD=1` (and
`MODS_HD_SRC=<folder>` to try another layer); `out/remix_materials_sheet.png` shows the
same three views as legacy flat material, with the layer, and with the magenta probe.
Sheet columns: `out/remix_legacy1` (no layer), `out/remix_pbr2` (layer; the same key
script with `LEVEL_WAIT=60`, because the runtime takes about 26 s longer on the "GET READY"
screen while it reads the layer's 8 261 textures), `out/remix_probe1` (probe). Frame cost
with the layer is unchanged (renderer stages and present within noise of the no-layer run);
`[RTX Opacity Micromap] Out of memory budget` appears once per run with and without it.
Exposure was left at the runtime's auto-exposure defaults: the 14:00 plaza frames are neither
clipped nor flat in either run, so no `rtx.conf` tone change was made (untuned, by eye only).

## The showcase: lights, night, presets (7 Nov, REMIX-SHOWCASE)

What the renderer already gave Remix (upstream work, all of it active under the bridge on
the L4): the map's own lamps as sphere lights with the file's colour and reach, classified
street / neon / white / traffic / vehicle and gated by daylight (`dll/src/remix_lights.cpp`);
headlights, brake lights, sirens, muzzle flashes, fire and explosions as synthetic lights read
off the game's particle and vehicle lists (`synthetic_lights.cpp`); the sun and sky through
Remix Plus's atmosphere, driven every frame from the `[timeofday]` clock with the real solar
geometry (`time_of_day.cpp`: `rtx.atmosphere.sunElevation/sunRotation`, clouds on or off from
`ClearSky`). The renderer's own sky dome is left out whenever the runtime has an atmosphere.

**Added for the street views.** GTA2 lists a lamp only while it is inside the top-down window
it draws, so from the ground a street was lit for a dozen blocks and dark beyond. The map's
steady lamps (LGHT, blinkers left to the game) are now decoded at level load
(`LightsSetMapLightRecords`) and, in the third- and first-person views, the ones within 36
tiles of the eye that the game did not list this frame are submitted as extra lights, nearest
first up to 120 (`LightsSubmitMapLampsNear`, called from `WorldView::RenderFrame` before the
reconcile). They go through the same position matching, buried-lamp lift and daylight gate as
the game's own. Verified in the log of a plain GPU run (`out/farlamp2`: "far lamps 120 within
36 tiles of eye 159.5,2.4,116.4 (game listed 24 map lamps)"); the Remix night frames are below.

**Emissive signs.** `tools/remix_emissive.py` adds an emissive mask to the material layer for
the neon and lit-sign tiles (a curated list per style in the script, chosen from
`out/neon_candidates_<style>.png`: HOTEL, MOTEL, JESUS SAVES, BAR, DINER, OPEN, GIRLS, the gang
roundels and the rest: 80 tiles, 64 of them with a material in the current layer), from the
upscaled tile's bright saturated strokes; `remix_materials.write_usda` writes
`enable_emission` + `emissive_intensity` (30) for a material with a mask. The layer was
rebuilt against the current HD tiles first (736 tiles had been regenerated after the previous
build, so their materials no longer matched: `gamerun/build_remix_mod.sh` → `remix_emissive.py`
→ `remix_model_materials.py`, in that order; `write_usda` now leaves the car-paint prims to the
model tool).

**Presets.** `gamerun/rtx_showcase.conf.extra` (`RTX_EXTRA=/work/rtx_showcase.conf.extra`):
moderate bloom (0.6, threshold 0.6), aerial perspective with local-light glow, a light height
fog (visibility 8 km, near fade 40 m), the real night sky (stars and moon), matte defaults for
untagged materials (roughness 0.75, metallic 0.05). Day and night are the clock:
`SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=21.5/'` for a fixed night,
`Paused=0` with `StartHour=16.8` for a take that runs from late afternoon into the night (one
game minute per second), `ClearSky=0` for Remix Plus's volumetric clouds.

**Runs.**
- `out/remix_night1` (21:30, paused, clear, layer on, 0 faults): classic, third and first
  person at the spawn plaza lit by the JESUS SAVES neon and the lamp posts, stars overhead,
  people lit by the neon (`out/remix_night1_views.png`, `out/remix_night1_strip.png`). This
  run still had the stale layer and the first far-lamp build; it verifies the night look and
  the game's own lights under path tracing.
- `out/remix_master1` (16:48 start, clock running, clouds): the take died at the switch to
  third person: a `FAULT` in `map_objects.cpp`'s once-per-model "object fit" log
  (`msvcrt` reading 0x6A6: `model.name` through a dangling `Model&`, the model store's vector
  having grown), then the Wine crash dialog. The dusk classic frames before it show the low
  sun's long shadows and the cars' headlights on the carriageway
  (`out/remix_master1_views.png`). The showcase runs use a private build with that log
  disabled (`STAGE=` in `remix_l4.sh`); the fix belongs to the map-objects owner.
- `out/remix_master2` (private build, devtools keys on, 16:48 start, clock running, clouds,
  layer with the emissive signs, 0 faults): the whole take through Remix in one piece:
  classic at dusk with the low sun's shadows, third person, first person along the carriageway,
  a car that stopped at the kerb entered the natural way (model 69, 68 `driving` lines), the
  chase view, the driver's seat, classic while driving, out of the car, third person on foot,
  the tutorial phone, with the night falling across it: by the drive the lamps are lit along
  the whole street (184-189 lights submitted a frame, of which 97-101 are the far lamps:
  "far lamps 101 within 36 tiles of eye ... (game listed 35 map lamps)"), the cars show their
  headlights, the MOTEL and other signs glow, stars overhead.
  `deliverables/gta2_linux_rtx_remix_master_demo.mp4` (450 s, from the level start),
  `deliverables/rtx_remix_day_night_sheet.png` (classic / third / first person, early and late
  in the take), strips `out/remix_master2_strip.png`, `out/remix_master2_views.png`.

**Open after this pass.**
- From the driver's seat the own car's hull shows as a bright cut surface at the bottom of the
  frame (`out/remix_master2_views.png`, top right): Remix does not honour the D3D9 user clip
  planes `car_bodies.cpp` uses to show only the hood, so under Remix the whole body is path
  traced from inside. The fix is the car-bodies owner's: clip the own car's triangles on the
  CPU (drop those above the eye plane) when `RemixApiAvailable()`, or skip the own body under
  Remix.
- The night is lifted by the auto-exposure to an overcast-evening brightness
  (`rtx.autoExposure.halo.maxEv` 4 by default); `maxEv` 2-2.5 or a negative
  `compensationNightStops` would keep it darker and let the lamps read as pools. Not tried
  (each check is a 15-minute run on the shared GPU).
- Not seen in a frame: police light bars flashing (no police car passed), fire/explosion lights
  (no crash), the car-paint prims' gloss at night, the volumetric clouds against the sun (the
  take starts after sunset; `ClearSky=0` was on).
- The `object fit` log fault above is in the shared tree (`map_objects.cpp`, committed as work in
  progress); until it is fixed, Remix takes use `STAGE=/tmp/remix_tree/stage`, a copy of the
  tree with that log disabled, built by this pass.

**How to run it again.** `STAGE=<stage dir> gamerun/remix_l4.sh <name> 840 /work/keys_remix_master.sh
-e MODS_HD=1 -e LEVEL_WAIT=45 -e RTX_EXTRA=/work/rtx_showcase.conf.extra
-e INI_SED='s/^warp_key=.*/warp_key=F9/; s/^scene_key=.*/scene_key=F10/'
-e SETTINGS_SED='s/^Paused=.*/Paused=0/; s/^StartHour=.*/StartHour=16.8/; s/^ClearSky=.*/ClearSky=0/'`,
then `gamerun/remix_daynight_sheet.py out/<name> 840 <sheet.png> <clip.mp4>`. A fixed night:
`keys_remix_night.sh` with `Paused=1`, `StartHour=21.5`.
