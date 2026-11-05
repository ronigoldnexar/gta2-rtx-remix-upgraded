# Running GTA2 RTX Upgraded on Linux in a container

Everything the project was run and recorded with on a headless Linux machine
(no Windows, no GPU with a display). Two images:

- `Dockerfile.wine9`: Ubuntu 25.04 with the distribution's Wine 9 (64 and 32-bit),
  Xvfb, Mesa (llvmpipe/lavapipe), ffmpeg, xdotool. Runs the game with the mod
  through Wine's own Direct3D 9: the 3D city, the cars and all three camera
  views, without RTX Remix.
- `Dockerfile.wine10-patched`: builds Wine 10.0 from source with
  `foreign-window-vulkan.patch` and the new WoW64 mode. The patch lets a process
  create a Vulkan surface on another process's window, which the RTX Remix
  bridge (a 32-bit client in the game, a 64-bit server that renders) needs and
  which Wine refuses out of the box. With it the Remix server comes up on Mesa's
  software Vulkan (lavapipe, which has the ray tracing extensions), creates its
  device and swap chain on the game's window, and starts its path tracer. On a
  CPU driver its first frame has not completed in our runs; see the project's
  notes for where that stands.

`run_game.sh` sets up a prefix, installs the game, the upstream release and this
build, starts the game on a virtual display, records it and takes screenshots;
`drive.py` plays it from the renderer's log (position, facing, nearest car) with
`gmp.py` reading the map for a walking route; `keys_video.sh` is the key script
of the recorded demonstration. `run_remix_test.sh` with `d3d9test.cpp` is the
small Direct3D 9 scene used to prove the bridge under Wine.

Mount points the scripts expect: `/game` (your GTA2 folder), `/release` (the
unzipped upstream release), `/stage` (this repository's `stage/` after `make`),
`/remix` (the unzipped Remix Plus x86 release), `/work` (this folder), `/out`.
