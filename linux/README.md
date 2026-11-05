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

`run_game_gpu.sh` is `run_game.sh` with the llvmpipe override removed, `vglrun -d egl0 wine
gta2.exe` (env `VGL_DISPLAY` picks another EGL device; `eglinfo -e` lists them), and an `FPS`
env for the capture rate (30 for smooth clips). Requirements: the NVIDIA container toolkit
(`docker info` lists the `nvidia` runtime), and the 32-bit NVIDIA GL libraries at **exactly the
host driver version** (the Dockerfile fetches Ubuntu's `libnvidia-gl-580-server` 580.178.04 for
i386 and amd64; set `NV_VER`/`NV_POOL` for another driver). Wine 9's 32-bit `gta2.exe` uses
32-bit GL, so the i386 package and VirtualGL's `virtualgl32` are both needed. The adapter the
game sees is still wined3d's faked "GeForce GTX 470"; the proof is `GL_RENDERER NVIDIA
B200/PCIe/SSE2` from an EGL test inside the image and `present 0.0 ms` in `gta2dx9.log`.

RTX Remix is a different matter: it needs Vulkan with ray tracing, which these GPUs do not
expose; see below.

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
   point where this repository stops: **no path-traced frame was produced on
   this machine**, whose eight B200s expose no Vulkan at all.

The Remix option set used for the attempts is `linux/docker/rtx.conf.extra`
(appended to the mod's `rtx.conf`), and `bridge.conf.extra` turns the bridge's
timeouts off so a slow first frame is not mistaken for a hang.

### On a machine with a ray tracing GPU (untested here)

`linux/docker/Dockerfile.remix-gpu` builds on the patched Wine runtime, adds the
NVIDIA Vulkan ICD and expects the driver's libraries from the container toolkit;
`linux/docker/run_remix_gpu.sh` runs the game with Remix, presenting to the
host's own display. Requirements: Linux with Docker and the NVIDIA container
toolkit, an RTX 20xx or newer with a driver that exposes Vulkan ray tracing
(535+), or an RDNA2+ AMD card with RADV (`--amd`). Everything that was verified
on the CPU driver (bridge, surface, device, pipeline building) applies; what a
real driver changes is only step 3 above. The first run compiles shaders for a
few minutes.

## Checking a build without the game

`make check` builds `linux/loadcheck.exe` and `linux/sehcheck.exe` and runs them under Wine. The second proves the GCC stand-in for `__try` catches a real fault and re-arms. The first, run from `stage/`,
it loads both DLLs the way `gta2.exe` does (`LoadLibrary`, then `GetProcAddress`
for every name the game resolves), checks that the plugin block covers
`+0x485E0`, and exits non-zero if anything is missing. The GitHub Actions
workflow runs the same on Ubuntu for every push, beside the MSVC build.
