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

## What was verified on a Linux machine with no Windows and no display GPU

GTA2 9.6 with this mod runs under Wine 9 and Wine 10 (both in Docker, on Xvfb, Mesa software
rendering): the opening, the front end, the levels, all three camera views, recorded. See
`linux/docker/`. `video.py` plays the game by itself from the renderer's log.

## RTX Remix under Wine: the bridge runs, its path tracer does not finish a frame on a CPU driver

RTX Remix is a Windows runtime. For a 32-bit game it is a bridge: the
`d3d9.dll` beside the game is a 32-bit client that forwards every call to a
64-bit server process (`NvRemixBridge.exe`), which does the path tracing in
Vulkan. People have run that bridge under Proton and Wine with NVIDIA's
proprietary driver, and the pieces are all ordinary Windows programs, but it has
not been tried with this mod and nothing in this repository can promise it
works. If you want to try:

1. Use a **64-bit** prefix with WoW64 (the bridge needs both halves), not the
   32-bit one `install.sh` makes: `WINEARCH=win64 linux/install.sh ...`.
2. Unzip the Remix Plus release the README names next to `gta2.exe`, as on
   Windows, so that its `d3d9.dll` and `.trex\` folder are in the game folder.
3. NVIDIA's driver, with Vulkan ray tracing (an RTX GPU), and
   `PROTON_ENABLE_NVAPI=1` or `WINE_HIDE_NVIDIA_GPU=0` depending on the Wine
   build, so the runtime sees an NVIDIA GPU.
4. Watch `rtx-remix/logs/` and `gta2dx9.log`: the renderer logs whether it got
   a Remix API and the bridge logs whether it reached the server.

If the bridge fails, the renderer carries on without it, as it does on Windows
without Remix.

What was found here: Wine refuses the bridge server a Vulkan surface on the game's
window because the window belongs to the other (32-bit) process;
`linux/docker/foreign-window-vulkan.patch` fixes that in `winex11.drv`, and with it
the server creates its device and swap chain and starts the path tracer. On Mesa's
lavapipe (the only Vulkan this machine had) the server then dies silently while
compiling its ray tracing shaders, on Mesa 25.0 and 25.2, with ray queries and with
ray tracing pipelines. With a real Vulkan GPU driver (NVIDIA's proprietary driver,
RADV) that step is the one to watch.

## Checking a build without the game

`make check` builds `linux/loadcheck.exe` and `linux/sehcheck.exe` and runs them under Wine. The second proves the GCC stand-in for `__try` catches a real fault and re-arms. The first, run from `stage/`,
it loads both DLLs the way `gta2.exe` does (`LoadLibrary`, then `GetProcAddress`
for every name the game resolves), checks that the plugin block covers
`+0x485E0`, and exits non-zero if anything is missing. The GitHub Actions
workflow runs the same on Ubuntu for every push, beside the MSVC build.
