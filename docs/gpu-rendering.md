# GPU rendering for the game under Wine (headless NVIDIA B200), 5 Nov 2026

## Result: works. wined3d's OpenGL runs on the B200 through VirtualGL's EGL back end.

- EGL device test inside the image (`gta2-gpugl`, `--gpus device=7`): device 0 = `EGL 1.5 NVIDIA`,
  `GL_RENDERER NVIDIA B200/PCIe/SSE2`, `GL_VERSION 4.6.0 NVIDIA 580.178.04` (compatibility context,
  pbuffer). Device 1 is Mesa zink over the NVIDIA Vulkan ICD (also the B200), device 2 llvmpipe.
- The game (32-bit `gta2.exe`, Wine 9.0) launched as `vglrun -d egl0 wine gta2.exe` on Xvfb :99:
  VirtualGL 32-bit faker loads, "Opening EGL device egl0", frames read back by PBO. Three runs
  (`out/gpu_test1`, `out/gpu_demo`, `out/gpu_drive`), 0 FAULT, all view switches logged, driving verified
  (427 `driving` lines in `gpu_drive`).
- The faked adapter name wined3d reports to the game is unchanged ("GeForce GTX 470"); the proof the GPU is
  used is the `present` column below and `nvidia-smi` showing the Wine process on the GPU.

## Frame times (renderer's 256-frame summaries, avg/worst ms; 30 fps cap = `wait` ~30)

| view | llvmpipe (docs/performance.md, after the buffer-fill fix) | B200 via VirtualGL |
|---|---|---|
| classic | present 0-30 (host load) | world 0.6/1.2, sprites 0.1/0.2, present 0.0/0.0, wait 30.2/30.9 |
| first person walking (walk demo) | present ~100 (8-10 fps) | world 0.9/1.5, sprites 1.2-1.9/5.9, present 0.0/0.0, wait 27.8/29.2 |
| third person driving | present 126/98 | world 1.0/2.0, sprites 1.8-2.1/8.8, present 0.0-0.4/44.5, wait 26.7/29.1 |
| first person at the wheel | present ~100 | world 0.6/1.5, sprites 0.3/1.1, present 0.0/0.0, wait 29.3/30.2 |

Every window sits on the 30 fps cap (the cap is the game's own step, so it cannot go higher without
speeding up the game). The one spike is the first ground-view frame (present 305 ms once in the walk
demo, 120 ms in the driving run: the first upload of the HD tiles/models to the GPU), then nothing.
Host CPU load during these runs was 250+ from other streams' containers.

## Clip

`deliverables/gta2_linux_gpu_render_walk_30fps.mp4` (1280x720, captured at 30 fps, 70 s): classic by the
carriageway, V into first person, the walk, V back to classic, rendered on the GPU. Contact sheets:
`out/gpu_demo_sheet.png`, `out/gpu_drive_sheet.png` (driving in all three views on the GPU).

## How

- `repo/linux/docker/Dockerfile.gpu-gl`: FROM gta2-remixbox + Ubuntu's `libnvidia-gl-580-server`
  580.178.04 for **amd64 and i386** (must equal the host kernel driver; fetched from the noble pool
  because the image is plucky and its 580.95 packages would not match), `libnvidia-common-580-server`,
  VirtualGL 3.1.5 (`virtualgl` + `virtualgl32`), glvnd/EGL/GBM for both bitnesses, the NVIDIA EGL
  vendor json. Built as `gta2-gpugl`.
- `gamerun/run_game_gpu.sh` (copy in `repo/linux/docker/`): `run_game.sh` minus the llvmpipe override,
  plus `vglrun -d $VGL_DISPLAY` (default `egl0`) and `FPS` for the capture rate. The shared
  `run_game.sh` is untouched.
- Run: `docker run --gpus '"device=N"' -e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility ...
  gta2-gpugl bash /work/run_game_gpu.sh win32 <secs> 0 /work/<keys>.sh`. Documented in
  `repo/linux/README.md` ("Rendering on a headless NVIDIA GPU").

## What did not need trying

Headless Xorg with the nvidia driver was not needed; VirtualGL's EGL back end handled the 32-bit Wine
process directly. RTX Remix is unaffected: it needs Vulkan ray tracing, which these GPUs do not expose
(zink's Vulkan 1.4 over the NVIDIA ICD exists here, so a Vulkan ICD is present after all for the
container runtime path; whether Remix's required RT extensions are there was not re-tested in this task).

## Caveats

- The "near-ground void" seen in first person at eye 0.43 is present on the GPU too (walk demo frames):
  it is not a llvmpipe artefact.
- x11grab reads the Xvfb framebuffer, which VirtualGL fills by readback; at 1280x720 that costs nothing
  measurable here (present 0.0).
- Capture at 30 fps works; the game cannot exceed 30 fps by design of its own step.
