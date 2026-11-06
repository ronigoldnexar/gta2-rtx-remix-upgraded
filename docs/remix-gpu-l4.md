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
