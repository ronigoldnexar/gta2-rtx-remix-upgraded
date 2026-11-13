# GTA2 RTX Upgraded on Linux

Everything in this folder is for running and building the mod without Windows.

## Building (no Visual Studio)

The two DLLs build with the MinGW-w64 cross compiler. The Windows build
(`dll\build.bat`, `vid\build.bat`) is unchanged; the same sources build both ways.

```
# Debian / Ubuntu
sudo apt install g++-mingw-w64-i686 make
# Fedora
sudo dnf install mingw32-gcc-c++ make        # then: make CROSS=i686-w64-mingw32-
# Arch
sudo pacman -S mingw-w64-gcc make

make            # dll/build/gta2dx9.dll, vid/build/gta2dx9_vid.dll, staged in stage/
make check      # ... and loads both under Wine, resolving every export GTA2 asks for
```

`stage/` holds exactly what a release zip's DLL part does: the renderer under its
two names, the video device under its three, `gta2dx9.ini` and the registry files.

What the port of the source needed, for the record: Visual C++'s `__try`/`__except`
and its inline-assembly thunks have no GCC equivalent on 32-bit x86, so
`dll/src/compat.h` gives both compilers one spelling (`GTA2_TRY`, and the thunks
written twice, MSVC and GAS, side by side), `dll/src/plugin_slot.S` is the GAS copy
of the plugin block, and the Makefile links with a static runtime so the DLL
depends on nothing that is not beside `gta2.exe`.

## Running (Wine)

GTA2 is a 32-bit Windows game, so it runs under Wine, and the mod is a Direct3D 9
renderer, which Wine provides (its own, or DXVK over Vulkan, which is faster and
more faithful).

```
sudo apt install wine wine32         # or your distribution's 32-bit-capable Wine
linux/install.sh --game ~/GTA2 --release ~/Downloads/GTA2_RTX_Upgraded_v1.1.zip --dxvk
linux/run.sh --log
```

`install.sh` makes a 32-bit prefix (default `~/.local/share/gta2`), copies your game
folder into it, unzips the upstream release over that (the HD cars, voice packs
and Remix mods), puts this build's DLLs over that, writes the registry keys
(`rendername`, `videoname`, `lighting`), and with `--dxvk` fetches DXVK's `d3d9.dll`
into the prefix. Your own game folder is never written to. `run.sh` starts the
game in a Wine virtual desktop (`GTA2_DESKTOP=2560x1440 linux/run.sh` to change
it, `GTA2_DESKTOP= linux/run.sh` for none); `--log` tails `gta2dx9.log`.
`install.sh` also sets Wine's `HKCU\Software\Wine\Direct3D\VideoMemorySize` to 4096 MB: with Wine's
default budget a 2560x1440 frame left 0 MB of texture memory, and the modern HUD and the city map were
not drawn (docs/citymap.md, "Drawing"). An existing prefix: `wine reg add 'HKCU\Software\Wine\Direct3D'
/v VideoMemorySize /t REG_SZ /d 4096 /f`.

**Sound on a machine with no sound card** (containers, headless servers): give Wine a
clocked null audio endpoint before starting the game, or it can crash seconds into a
level:

```
sudo apt install pulseaudio
export XDG_RUNTIME_DIR=/tmp/xdg-runtime; mkdir -p $XDG_RUNTIME_DIR
pulseaudio --daemonize=yes --exit-idle-time=-1 --disallow-exit --load="module-null-sink sink_name=null"
```

Without any audio endpoint Wine's `DirectSoundCreate` fails, the game's Miles Sound
System (`mss32.dll`) opens no digital driver, and the game goes on using the dead
driver handle; `AIL_allocate_sample_handle` then reads through it and page-faults
(`mss32.dll+0x12353`, intermittent: one run in seventy on a plain host, most Remix
runs). With the null sink Wine picks `winepulse`, DirectSound initialises, Miles
creates its buffers and the audio path is the normal one. An ALSA `pcm.!default
{ type null }` is not a substitute: that device has no clock and the intro movie
freezes on it. The Docker images carry PulseAudio and the run scripts start the
sink themselves (`GTA2_AUDIO=none` to skip).

Press **V** in a level to cycle the classic, third-person and first-person views,
**F4** for the settings panel. `tools/record_demo.sh` records the switch with ffmpeg.

## What you get without RTX Remix

The renderer draws the same 3D city, the cars with their domes, doors, lamps
and tyres, the sprites stood in the world, the day/night clock and all three
camera views through plain Direct3D 9. What needs Remix is the path tracing
itself and the materials: the HD cars' PBR maps, the emissive lamps and the
animated water are Remix replacement assets and are not applied by Direct3D 9.
So on Wine without Remix the picture is the mod's geometry and camera work with
the game's own artwork and fixed-function lighting.

## High-resolution tiles (512 px, block-compressed)

`gta2dx9_textures_hd/<style>/tile_NNNN.dds` beside the game replaces the 64 px tile
artwork with 512 px mipmapped DXT textures made with Real-ESRGAN and Stable Diffusion
(docs/hd-textures.md has the pipeline and the memory figures). `make stage` and
`linux/install.sh` ship the folder when `assets/textures_hd/` exists; the set for the
first two districts is the release asset `textures_hd_dds.zip`. The installer also marks
the installed copy of `gta2.exe` large-address-aware (`linux/laa.sh`, 4 GB of address
space for the textures and the 3D models; the original file is never changed).

## What was verified on a Linux machine with no Windows and no display GPU

GTA2 9.6 with this mod runs under Wine 9 and Wine 10 (both in Docker, on Xvfb, Mesa software
rendering): the opening, the front end, the levels, all three camera views, recorded. See
`linux/docker/`. `video.py` plays the game by itself from the renderer's log.

## Rendering on a headless NVIDIA GPU (no display, no Vulkan needed)

Verified on a B200 (5 Nov 2026) and on an L4 (6 Nov 2026, driver 580.178.04). On the L4 host the
container runtime also injects `libnvidia-egl-gbm`, which makes Xvfb's own software GLX segfault
when glvnd picks the NVIDIA EGL vendor; `run_game_gpu.sh` therefore starts Xvfb with
`__EGL_VENDOR_LIBRARY_FILENAMES` pinned to Mesa's vendor file, and VirtualGL still renders on the GPU.
For continuing the work elsewhere see `docs/HANDOVER.md`.

Without a display GPU, wined3d draws through Mesa's llvmpipe and the street-level views cost
about 100 ms a frame at 1280x720 (8-10 fps). The same frame on an NVIDIA GPU is free: the
renderer's own stages are 1-4 ms and `present` reads 0.0 ms, so the game sits on its 30 fps cap.
This works on a compute-only machine (the B200s here expose no Vulkan at all) because NVIDIA's
OpenGL can run on a headless EGL device, and VirtualGL redirects the X11 GL calls of a 32-bit
Wine process onto it:

```
cd linux/docker && docker build -f Dockerfile.gpu-gl -t gta2-gpugl .   # game image + NVIDIA GL (amd64 + i386) + VirtualGL 3.1.5
docker run --rm --gpus '"device=0"' -e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility \
    -v $PWD/gamerun:/work -v $PWD/game:/game:ro -v $PWD/upstream-release/files:/release:ro \
    -v $PWD/repo/stage:/stage:ro -v $PWD/remix-runtime/x86:/remix:ro -v $PWD/out/gpu:/out -w /work \
    gta2-gpugl bash /work/run_game_gpu.sh win32 250 0 /work/keys_demo_fp2.sh
```

On a host where anything calls `docker update` on a running container (here `cpu_governor.sh`
moves the cpuset every minute), also pass the NVIDIA nodes as devices:
`$(linux/docker/nv_devices.sh 0)` next to `--gpus`. On cgroup v2 `docker update` rebuilds the
device filter from Docker's own `--device` list, which does not hold the nodes the NVIDIA hook
added; the driver's next open of `/dev/nvidiaN` then fails with EPERM (GL loses the device, Remix
dies with "DxvkCommandList: Failed to create fence"). All launchers in `linux/docker` do this, and
`cpu_governor.sh` leaves the cpuset of a `--gpus` container without the nodes alone.

`run_game_gpu.sh` is `run_game.sh` with the llvmpipe override removed, `vglrun -d egl0 wine
gta2.exe` (env `VGL_DISPLAY` picks another EGL device; `eglinfo -e` lists them), and an `FPS`
env for the capture rate (30 for smooth clips). Requirements: the NVIDIA container toolkit
(`docker info` lists the `nvidia` runtime), and the 32-bit NVIDIA GL libraries at **exactly the
host driver version** (the Dockerfile fetches Ubuntu's `libnvidia-gl-580-server` 580.178.04 for
i386 and amd64; set `NV_VER`/`NV_POOL` for another driver). Wine 9's 32-bit `gta2.exe` uses
32-bit GL, so the i386 package and VirtualGL's `virtualgl32` are both needed. The adapter the
game sees is still wined3d's faked "GeForce GTX 470"; the proof is `GL_RENDERER NVIDIA
B200/PCIe/SSE2` from an EGL test inside the image and `present 0.0 ms` in `gta2dx9.log`.

RTX Remix is a different matter: it needs Vulkan with ray tracing, which the B200s do not
expose but an L4 (or any RTX card) does; see below.

## RTX Remix under Wine: what was found, what is blocked, how to run it on a real GPU

RTX Remix is a Windows runtime. For a 32-bit game it is a bridge: the `d3d9.dll`
beside the game is a 32-bit client that forwards every call to a 64-bit server
process (`NvRemixBridge.exe`), which renders in Vulkan and presents into the
game's window. Three things stood between it and a frame on this machine, two of
them solved:

1. **Wine refuses the server a surface on the game's window**, because the window
   belongs to the other process. `linux/docker/foreign-window-vulkan.patch`
   (one hunk in `winex11.drv`, built by `Dockerfile.wine10-patched`) parents the
   client window to the owner's published X window instead. Verified: the
   server creates its device and swap chain on the game's window.
2. **`vkCreateDeferredOperationKHR` fails on Mesa's lavapipe**, and the runtime
   treats that as fatal (`[Check failed] ... dxvk_raytracing.cpp:326`, an `int3`
   in `.trex/d3d9.dll` at image offset `0x3f65db`). `rtx.pipeline.useDeferredOperations = False`
   does not avoid the call; patching that one byte to `nop` (see
   `linux/docker/run_game.sh`, `d3d9_trex_patched.dll`) lets it carry on to
   building the ray tracing pipelines. Verified by the server log.
3. **lavapipe's JIT-compiled Remix shaders crash** the server's worker threads
   (kernel log: `NvRemixBridge.e: segfault at 2f0 ip <anonymous> ...` and
   `ip 0000000000000000`, i.e. null dereferences and null calls inside generated
   code) about a minute and a half after device creation, with ray queries and
   with ray tracing pipelines, with one bounce and no denoiser, on Mesa 25.0,
   25.2 and git main (Nov 2026). This is a limitation of the CPU driver, and the
   point where the CPU driver stops. On a ray-tracing GPU this step simply works
   (next section).

The Remix option set used for the attempts is `linux/docker/rtx.conf.extra`
(appended to the mod's `rtx.conf`), and `bridge.conf.extra` turns the bridge's
timeouts off so a slow first frame is not mistaken for a hang.

### On a machine with a ray tracing GPU: verified on an NVIDIA L4 (6 Nov 2026)

With a GPU that exposes Vulkan ray tracing the chain above produces path-traced
frames. Verified on a GCE host with one NVIDIA L4 (Ada, driver 580.178.04):
`vulkaninfo` in the container lists `VK_KHR_ray_tracing_pipeline`, `VK_KHR_ray_query`,
`VK_KHR_acceleration_structure` and `VK_KHR_deferred_host_operations`; the Remix
server creates its device on the L4, reports Opacity Micromap and Shader Execution
Reordering support, picks its ray-query modes, compiles its shaders (about three
minutes the first time) and renders the front end and the game world through the
bridge in all three views. The NVIDIA B200s of the earlier machine were the one
GPU family this cannot work on: a device with `VK_KHR_ray_query` cannot be created
there at all (`vkCreateDevice` returns -7; the ray-query test in
`out/remix_l4/rayquery_l4_test.txt` returns 0 on the L4).

How to run it (`linux/docker/Dockerfile.remix-gpu`, image `gta2-remix-gpu`):

- The image installs the matching `libnvidia-gl-580-server` package itself,
  because the container runtime on some hosts injects only the compute
  libraries; change `NV_VER` to the host's driver version.
- The Vulkan ICD is `/usr/share/vulkan/icd.d/nvidia_icd.json` (`ICD_JSON` to
  override). Xvfb must keep its own GLX on Mesa:
  `__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json Xvfb ...`,
  otherwise the NVIDIA EGL vendor segfaults it. `gamerun/run_game_remix_gpu.sh`
  does both; `gamerun/remix_l4.sh <name> <seconds> [keys] [-e ...]` is the
  host-side launcher used here.
- Remix's welcome dialog takes imgui focus and swallows the game's keys; it is
  dismissed by keyboard (its own navigation) or pre-dismissed by seeding
  `AppData/Local/NVIDIA/RTXRemix/user_settings/<hash>.conf` with
  `neverShowFirstUseGuide = True` (`gamerun/remix_user_settings/`).
- Single-frame `ffmpeg x11grab` captures of the Remix window come out black;
  the continuous recording is fine, so stills are cut from `game.mp4`.
- The game's clock starts at 02:00, so Remix's atmospheric sky is night unless
  `[timeofday] start_hhmm` is changed (the showcase runs use 1600, paused).
- No DLSS or frame generation under Wine (NGX is not available), and the Neural
  Radiance Cache SDK fails to initialise; Remix falls back to its sampled
  indirect lighting. At 1280x720 the present stage costs about 20-30 ms on the L4.

## Play it in a browser

For a person at a keyboard rather than a keys script: `linux/docker/play.sh` starts the
game in a container on the machine's NVIDIA GPU and serves its display to a browser
tab through x11vnc and noVNC (image `gta2-play`, built from `Dockerfile.play` on top of
`gta2-gpugl`; `gta2-play-remix` on top of the Remix image for path tracing).

    linux/docker/play.sh plain          # the mod's own D3D9 picture on the GPU, port 6080
    linux/docker/play.sh remix          # RTX Remix path tracing (about 3 min of shader warm-up first)
    linux/docker/play.sh plain 6090     # another port
    linux/docker/play.sh status | stop

Then open `http://localhost:6080/`. From another machine, tunnel first:
`ssh -L 6080:localhost:6080 <host>`. The landing page lists the keys (arrows, Ctrl
fire, Enter enter/leave a car, Tab weapon, **V** cycles classic / third person /
first person, mouse look in the ground views, F4 the mod panel, Esc pause) and a
Play button that opens noVNC with auto-connect. The game appears after ~40 s
(plain); press Enter through the front end to start. Options: `PLAY_PASSWORD=...`
(VNC password, also put into the Play link), `PLAY_DEVTOOLS=1` (F9/F11 warps),
`SWAP_LEVEL=bil|ste`, `GPU=<index>`, `CPUS=<n>`. The container keeps running until
`play.sh stop`; the renderer log is mirrored to `out/play-<port>/gta2dx9.log`.
Sound: the game's audio plays in the page too. Play starts it (the click is what
browsers require); the bar at the top right mutes it and sets the volume, and shows
the codec and the sound's delay. It is Opus over a websocket on the same port
(`play_audio.py`, see `docs/HANDOVER.md`, "Play it interactively"); `PLAY_AUDIO=0`
turns it off. Check it without a browser: `docker cp linux/docker/play_audio_probe.py
gta2-play-<port>:/tmp/ && docker exec gta2-play-<port> python3 /tmp/play_audio_probe.py <port> 10`
(packets/s, sequence gaps, Opus decode errors, transit and level on `/audio` and `/audio-pcm`;
exit 0 = sound flows); `play_audio_test.py` is the full browser test (playwright + Chromium). Limits: the picture is JPEG-compressed, so it is for trying the game,
not for recording. On your own Linux box with a GPU, the native
route is `linux/install.sh` + `linux/run.sh` (no container).

## Checking a build without the game

`make check` builds `linux/loadcheck.exe` and `linux/sehcheck.exe` and runs them under Wine. The second proves the GCC stand-in for `__try` catches a real fault and re-arms. The first, run from `stage/`,
it loads both DLLs the way `gta2.exe` does (`LoadLibrary`, then `GetProcAddress`
for every name the game resolves), checks that the plugin block covers
`+0x485E0`, and exits non-zero if anything is missing. The GitHub Actions
workflow runs the same on Ubuntu for every push, beside the MSVC build.

`make check` order: `tools/check_ini_sections.py` on `package/gta2dx9.ini` (always runs), then the two Wine checks. On a host without Wine (`wine` not on the PATH; override with `WINE=`) both check tools are still built (so a link break shows) and the Wine steps print a `SKIP:` line instead of failing. `sehcheck.cpp` supplies its own `gta2dx9::Log` and `FrameLogNote` stand-ins because it links `compat.cpp` alone; if `compat.cpp` starts calling another DLL function, add a stand-in there. Run it as `flock /tmp/gta2-build.lock nice -n 10 make -j8 check` in a private worktree. `linux/docker/restage.sh` runs it on the candidate worktree and refuses the stage if it fails.
