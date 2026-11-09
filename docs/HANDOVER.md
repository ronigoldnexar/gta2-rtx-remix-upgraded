# Handover: GTA2 RTX Remix Upgraded, camera-modes branch

For a person or an agent picking this up on another machine, Windows or Linux.
Read this, then `AGENTS.md` (the short version), then the per-topic documents it
points at. Sections 1-9 were written on 6 Nov 2026 (commit `3eebc50`, release
`v1.4-ground-views`); section 0 lists what changed in round 2 (6-8 Nov, release
`v1.5-3d-round2`) and overrides anything older below it.

## 0. Round 2 (6-8 Nov 2026): what changed since v1.4

Everything below is in branch `camera-modes` and was seen in the running game on the
L4 host unless it says otherwise; the per-topic documents have the evidence.

| Area | What changed | Document |
|---|---|---|
| RTX Remix | **Path tracing runs** on an RTX-class GPU (NVIDIA L4, Wine 10 patched, `Dockerfile.remix-gpu*`, `gamerun/remix_l4.sh`); the PBR layer `package/rtx-remix/mods/gta2hd` is keyed by the HD tiles' top-mip hash (verified by a colour probe); car paint as clear-coat with metal trim, lit lamps, night/day presets in `package/rtx.conf`; liveries keep their colours (no paint tint on livery models), clean hood from the driver's seat, night plaza no longer floodlit (REMIX-3). Clock moved in-session by a devtools key. Only `mod.usda` is in git; the DDS ship as `remix_mod_gta2hd.zip` | `docs/remix-gpu-l4.md`, `docs/remix-materials.md` |
| Weapons | The game's weapon is read: `ped+0x170` weapon object (type `+0x1C`, ammo `+0`, reload `+2`), inventory `ped+0x15C` (+0x718 pointers, selected slot int16 +0x788). Per-weapon aim stances with recoil, weapons in hand, muzzle glow, shell cases, first-person view model per weapon | `docs/actions-3d.md` (Weapon field) |
| Vehicles | Car object fields: damage int16 `+0x74` (16000 alight, 25000 hard, 31500 lamps out, 32000 explodes; a burning car gains 1 a frame), stage byte `+0x8C`; `view: mission` logs `cardmg= carhp= carfire=` and the target car's; doors swing, dents from the 16-bit damage (built on a worker thread), burnt wrecks 72-81, tank turret and fire-truck cannon follow the game's turret sprite, siren beacons (cop car, SWAT van, ambulance, fire truck), trains at track height | `docs/actions-3d.md` (Vehicle fields, Police and special vehicles) |
| Actions | Stance/carry keyed off the game's weapon, upper-body layers, burning, falls, lying clips by cause of death, get-up, drowning; every remap ped type as a textured avatar (army green, medics, police kit fixed: Rocketbox `*_color_acu.tga` were never fetched); SWAT/FBI/Zaibatsu sprite sets mapped by body | `docs/actions-3d.md` |
| Police | Wanted level from the ped's cop points (int16 `ped+0x20A`); `[devtools] force_wanted=N` holds a star level for QA; the arrest acted out (hands up, cuffed, walked to the cop car); police shoot at 4 stars, FBI at 5, army with tanks at 6 | `docs/actions-3d.md` (Police) |
| Navigation | Orbit chase camera with capped turn rates (`turn_speed`), camera-relative controls on foot (`nav_map=1`, a DirectInput8 patch; buffered events renumbered so injected keys never drop real ones), eased figure heading; chase framing from the vehicle's body, driver's eye from the model's cab | `docs/navigation.md` |
| Cars | Rounds 4-6 (CAR-QUALITY-4..6): photographic concepts per model with era briefs, bilateral delighting, roof/flank balance, sprite on the roof only, nose check; a nine-term scorer (`tools/score_car_model.py`: surface-sampled roof line per body type, a smear term) re-scored 517 candidates; **all 60 image-to-3D models are now regenerated (no v1 left)**, 13 parametric bodies unchanged; round 8 (CAR-ERA) replaced the five era outliers (047/048 Meteor as 1960s mid-engine coupes, 083 Furore GT as a 275 GTB-style coupe, 064 as a 1960s tractor, 016 Panto as a Mini), open: 003 Pacifier. **TRELLIS on the L4 needs the CUDA extensions rebuilt for sm_89** (`TORCH_CUDA_ARCH_LIST=8.9`, or `"8.9;10.0"` for one venv on both hosts) | `docs/car-3d-pipeline.md` (rounds 4, 5, 6, 8) |
| Props | A real phone booth in every district, traffic-light heads, 3D weapon pickups, tokens, briefcase, mission items, parking meters, containers. **These code-object models are in git** (`assets/models/booth*`, `light_*`, `pickup_*`, ...); only cars and avatars stay out | `docs/asset-audit.md` section 9 |
| Performance | Per-frame log, prop merging and frustum culling, background model warm-up, cheap player locator, step-locked chase camera (PERF-2); car dents/door splits off the render thread (PERF-3); browser play p99 22.8-29.7 ms (under the 33 ms cap). Square 2.6x spawn window in the street views, car bodies to 60 blocks, props 36, fog 18-130 | `docs/performance.md` |
| Map | Lids for lidless ground under decks and deck undersides (second hole class); city sweep: 0 holes in ~3000 frames (rerun in round 2: `docs/qa-report.md` QA3) | `docs/city-sweep.md` |
| Play in a browser | `linux/docker/play.sh plain|remix [port]` (noVNC); the player's container is pinned to CPUs 5-7 and scripted runs to 0-4 | `linux/README.md` |
| Missions | Mission runner v3 reads the game's objective arrows; see "Mission playthrough state" below | `docs/missions.md`, `docs/playthrough-*.md` |
| Tooling | `linux/docker/restage.sh`, `GTA2_DIRECT_KEYS`, `GTA2_SPEED`, `runq.sh` priorities, `tools/pack_release.py` (all archives), `qa_run.sh`/`sweep_run.sh` take `STAGE=` and direct keys | below and `docs/throughput.md` |

Round-2 QA (scenarios, police/army/arrest, the city sweep, archives, fresh-clone check):
`docs/qa-report.md`, section QA3. Highlights video of the round (local, not in git):
`~/gta2-linux/deliverables/gta2_3d_round2_highlights.mp4` (2:59, 1280x720, 30 fps, H.264).

### Rules that cost hours when broken (multi-agent host)

- **Never put a shell variable in an `rm` command** issued through an agent's shell tool
  (`rm -rf "$OUT"`, `rm -f $D/x`): the agent harness's safety check hangs that call forever.
  Delete with literal absolute paths, or from Python (`shutil.rmtree`). Scripts that a
  command runs may use variables (the check reads the command line only).
- **The shared `repo/stage` is rebuilt only with `linux/docker/restage.sh`**: it waits for
  the build lock and all four game slots, then `make stage`. A `make stage` while a run
  uses the stage recopies the models folder and that run draws white figures.
- **Test from a private stage copy**: `cp -al repo/stage ~/gta2-linux/stage_<you>` (hard
  links, instant, safe because `make stage` replaces rather than rewrites files), then
  `STAGE=<that dir>` on `gamerun/grun.sh`, `qa_run.sh`, `sweep_run.sh`.
- **Game runs only through the queue** (`gamerun/grun.sh`, `slot.sh`, `runq.sh`; slots
  1-4 as `flock`s on `/tmp/gta2-game-slot-N.lock`), launched with `nohup` so a dropped
  shell does not kill them; containers are pinned to CPUs 0-4 (`GAME_CPUSET`), the user's
  play container (`gta2-play-<port>`, CPUs 5-7) is never stopped by an agent.
- **`GTA2_DIRECT_KEYS=1` for scripted play in the 3D views**: it sets `nav_map=0` for the
  run, so the arrow keys stay the game's own (tank controls) and a script's turn/walk/aim
  works in third and first person. With the shipped `nav_map=1` the arrows are camera-
  relative and the scripts' turns go wrong. `grun.sh` passes it to the runners;
  `qa_run.sh` and `sweep_run.sh` default it to 1.
- Poll loops under 8 minutes; long sessions at `GTA2_SPEED=2` with `FPS=0` when no video
  is needed.

### Release archives (v1.5-3d-round2)

Built by `python3 tools/pack_release.py <out dir> [linux people cars textures remix]`
from the repository root after `make stage`; each is checked against its source after
packing. Paths inside the zips:

| Archive | Contents (paths in the zip) | Unpack |
|---|---|---|
| `gta2dx9-x86-linux-built.zip` | `gta2dx9-linux-built/` with the two DLLs and their copies (`d3ddll.dll`, `Dmavideo.dll`, `DMAGlide.dll`), `gta2dx9.ini`, `install.reg`, `uninstall.reg`, and `linux/` (the committed tree) | anywhere; the DLL/ini/reg files go beside `gta2.exe` |
| `gta2dx9_models_people.zip` | `assets/models/human_*` (41 Rocketbox avatars, MIT, re-imported in round 2: army/medic/police textures, new action clips) | repository root (then `make stage`), or its `assets/models/` content into `gta2dx9_models/` beside the game |
| `gta2dx9_models_cars.zip` | `assets/models/0NN_*` (the car models; embed the game's sprites) | same as people |
| `textures_hd_dds.zip` | `assets/textures_hd/{wil,bil,ste}/tile_NNNN.dds` (unchanged since v1.4, same CRCs) | repository root, or `gta2dx9_textures_hd/` beside the game |
| `remix_mod_gta2hd.zip` | `gta2hd/mod.usda` + `gta2hd/textures/*.dds` (store-only, ~1.06 GB) | `package/rtx-remix/mods/` in the repo, or `rtx-remix/mods/` beside the game |

The code-object models (booths, lights, pickups, ...) and `assets/models/manifest.json`
are in git; the manifest at the release commit is the one the car and people archives
match. A fresh clone plus the five archives reproduces `stage/` byte for byte
(`docs/qa-report.md`, QA3, "fresh clone").

### Mission playthrough state (8 Nov 2026)

Completed by script in the chase view: Downtown tutorial, GET ZITZAKI, PIZZA CAKE, RADIO
ZA-ZA, WHEELER-DEALING (at `GTA2_SPEED=2`, 16 s to spare), GET ZITZAKI after PIZZA CAKE in
one game (the Yakuza chain); Residential BLOW JOB (once). Not yet: BANK ROBBERY (next
Yakuza job; plan steps for marked characters and point arrows written, untested),
Industrial RUSSIAN SAILORS (furthest: all four dealers aboard; the Z-Type burns on the
long dealer-4 and crane legs), HOT DOG HOMICIDE and DOUBLE-CROSS CRUSH (phones answered,
no runner). Details and the next steps: `docs/playthrough-downtown.md` (part 7),
`docs/playthrough-districts.md` (PLAYTHROUGH-8).

## 1. Goal

Take kirmm3la's GTA2 RTX Remix Upgraded (an in-process Direct3D 9 replacement
renderer for GTA2 9.6, `gta2dx9.dll`) and add:

1. **Three camera modes**, cycled with one key: the classic top-down view (kept
   exactly as the game draws it), a third-person chase camera, and a first-person
   view on foot and at the wheel, with seamless camera moves between them.
2. **A full Linux port**: build without Visual Studio, run under Wine, no display
   GPU needed, and script-driven play for recording and testing.
3. **Modern visuals in the ground views** while the top-down look stays GTA2's:
   HD tiles, a 3D model per vehicle type in GTA2's retro-futuristic 1940s-60s
   style, realistic pedestrians, map objects, a sky, and eventually RTX Remix
   path tracing.

The game itself is never downloaded or redistributed; the user supplies their
own installer. Generated assets that embed the game's artwork stay out of git.

## 2. State: verified, open, untested

### Verified (seen in the running game, recorded)

| Area | What works | Evidence |
|---|---|---|
| Views | V cycles classic / third / first; 1.4 s camera moves (arc, shortest yaw, FOV ease); chase camera avoids walls and pulls in/rises on foot; first person with head bob, mouse look, own sprite hidden on foot, own car's hood in frame at the wheel | `deliverables/gta2_linux_final_demo.mp4`, `docs/qa-report.md` |
| Player locator | Found by structure signature in `gta2.exe` memory, survives entering a car (follows the vehicle whose driver word is the remembered ped), arrest/respawn re-scan | `dll/src/view_modes.cpp` LocatePlayer |
| Driving | Enter (Return), drive in all three views, leave, re-enter | `deliverables/gta2_linux_driving.mp4`, `..._3d_cars_drive_third_then_first_person.mp4` |
| Linux | MinGW cross build, `make check` loads both DLLs under Wine, Docker images, Xvfb + x11grab recording, xdotool input | `linux/README.md` |
| GPU rendering (Linux, headless) | wined3d's OpenGL on an NVIDIA GPU through VirtualGL's EGL backend; present cost 0 ms, frames at the game's 30 fps cap. Verified on B200 (5 Nov) and L4 (6 Nov) | `docs/gpu-rendering.md`, `deliverables/gta2_linux_gpu_render_walk_30fps.mp4` |
| HD tiles | All three districts, 512 px DXT1/DXT5 with mips (Real-ESRGAN x4 twice, SD1.5 ControlNet Tile, per-tile pick), loaded by the renderer; the game's `gta2.exe` copy made large-address-aware | `docs/hd-textures.md` |
| Cars | 73 vehicle types mapped by model number (vehicle +0x84): 60 image-to-3D period models (SDXL concept from the sprite, TRELLIS, fitted to the sprite footprint with the sprite projected on the roof), 13 parametric bodies; live paint tint via a split `_paint` texture; LOD, culling, cache | `docs/car-3d-pipeline.md`, `assets/README.md`, `deliverables/cars_sheet_bev_third_first.png` |
| People | 9 Microsoft Rocketbox avatars (MIT), CPU-skinned, walk/run/idle blends, smoothed position and heading (no snap turns), per-person phase, 0.46 blocks tall (1.25 x a sedan roof), eye 0.43 | `out/ped_motion_sheet.png` (local), `assets/README.md` |
| Objects | OBJI map objects (24 models) as Poly Haven or procedural models by sprite base 5 frame; rule-placed lamps, bins, benches, hydrants | `dll/src/map_objects.cpp`, `tools/gen_objects.py` |
| Sky | Dome with sun, clouds, horizon haze, distance fog, sun-lit shading in the ground views only, faded through transitions | `src/sky.cpp`, `[sky]` in `package/gta2dx9.ini` |
| Ground hole fix | GTA2 columns with `offset > 0` had no floor/base walls in the mesh; now built (`AddImplicitFloors`) | `src/world_mesh.cpp`, commit 892688d |
| Performance | Skinned pedestrians use per-pose dynamic VBs (203 ms -> 0.2 ms of buffer fills); tile and model textures pre-warmed after level load; behind-camera culling | `docs/performance.md` |
| QA | Wall pushing, 360 turns, rapid V, brawl, crashes, exit/re-entry, 8 min soak: 0 faults | `docs/qa-report.md` |

### Open

- **Fixed 6 Nov, evening: the intermittent `mss32.dll+0x12353` crash.** Cause: no audio
  endpoint in the container, so `DirectSoundCreate` failed, Miles opened no digital driver and
  the game later used the dead handle in `AIL_allocate_sample_handle`. Fix: a PulseAudio null sink
  started by `run_game*.sh` (images carry `pulseaudio`); see `linux/README.md`, "Sound on a
  machine with no sound card". If a run ever shows that fault again, check `/tmp/pulse.log` in
  the container and that `game.stdout` (with `WINEDEBUG=+mmdevapi`) selects the `pulse` driver.
  An ALSA null pcm is not a substitute (no clock: the intro movie freezes).

1. *(Superseded: Remix runs on the L4, see section 0.)* On the first host (B200) Vulkan
   had no ray query (device creation returned -7). Mesa lavapipe got the Remix
   server to its first frame and died in its JIT. The second host has an L4
   (Ada, RT cores): rebuild `linux/docker/Dockerfile.wine10-patched` +
   `Dockerfile.runtime-ubuntu2510` + `Dockerfile.remix-gpu` there and retry
   (`linux/docker/run_remix_gpu.sh`). The Remix PBR material mod
   (`package/rtx-remix/mods/gta2hd`, 891 materials) is unverified in Remix.
2. *(Superseded by PERF-2/3 on the GPU, `docs/performance.md`.)* **Driving frame cost** on software GL: 120-200 ms per frame among traffic
   versus the cap on foot; prime suspect is `car_bodies.cpp` re-measuring sprite
   artwork with `LockRect` every frame. See `docs/qa-report.md`
   "Performance while driving". On a GPU it may be invisible; measure first.
3. **Final demo re-record.** `deliverables/gta2_linux_final_demo.mp4` (340 s,
   single take, natural car entry) predates the ground-hole fix and the motion
   and performance passes; the first-person-on-foot segment shows the hole.
   `gamerun/final_demo.py` reproduces the take.
4. *(Superseded: death, respawn and arrest verified, `docs/qa-report.md` QA3 and
   `docs/actions-3d.md`.)*
5. Cosmetic: tall vehicles show a flat cut cowl in first person (solid hulls,
   user clip planes); the sky's sun is fixed (`follow_clock=0`) because the game
   clock starts at 02:00; the Remix materials and the 3D models have not been
   seen under a path tracer; Industrial-district objects and some code-object
   sprites (litter, pickups) are still flat sprites.

### Untested on purpose

Windows: this branch has not been built with MSVC since the Linux work started
(`dll/build.bat` lists every new .cpp; `package.bat` is unchanged). The MinGW
build is what every recording used. Expect small MSVC-only fixes.

## 3. Architecture

`gta2dx9.dll` replaces the game's `d3ddll.dll` (takeover mode: it owns a
topmost present window), rebuilds the world from the GMP map as real 3D
geometry, and draws the game's sprites as 3D quads from the world-space vertex
shadow of the game's own draw stream. The camera modes read the game's objects
from memory (offsets in `dll/src/game_access.h` and `view_modes.cpp`).

| File | Role |
|---|---|
| `src/renderer.cpp/.h` | Device, world batches, tile textures (incl. DDS HD tiles, pre-warm, anisotropy), fog/lighting state, UI layer |
| `src/world_mesh.cpp` | GMP map -> mesh (lids, walls, slopes, flat panels, the seal, implicit floors of offset columns) |
| `src/sky.cpp/.h` | Sky dome, sun, clouds, analytic day/dusk colours |
| `src/gta2_map.cpp`, `src/gta2_style.cpp` | GMP and STY parsing (tiles, sprites, palettes, CARI car info) |
| `src/camera.cpp/.h` | View/projection, yaw/pitch/roll, FOV, near plane |
| `dll/src/world_view.cpp/.h` | Per-frame driver: camera update, view-mode branch, transitions (`ApplyTransition`), sky/fog hooks, HUD camera map, `view: player` log line |
| `dll/src/view_modes.cpp/.h` | `ViewModeSettings`, player locator, chase/first-person solver, input (V, mouse), devtools warps |
| `dll/src/live_geometry.cpp/.h` | Everything drawn from the game's sprite stream: upright peds, pedestrian models + motion smoothing, car dome bodies, lights, smoke, props, culling, stage timers |
| `dll/src/model_store.cpp/.h` | GMSH model loader (v1 flat, v2 skinned), animation blending, pose cache + dynamic buffers, manifest (cars by model, pedestrians, props, objects), paint tint |
| `dll/src/car_bodies.cpp/.h` | Per-vehicle 3D body: model by model number, fallback body extruded from the sprite, cabin for the first-person eye, clip planes |
| `dll/src/map_objects.cpp/.h` | OBJI sprite (base 5) -> model placement |
| `dll/src/compat.cpp/.h` | GCC stand-in for `__try` (vectored handler + context resume), FAULT logging with module offsets |
| `dll/src/settings.cpp`, `debug_overlay.cpp` | Saved settings (`gta2dx9_settings.ini`), the F4 menu incl. the Camera tab |
| `dll/src/dllmain.cpp` | Reads `gta2dx9.ini` (`[camera]`, `[renderer]`, `[sky]`, `[devtools]`), loads models/textures, installs hooks |
| `dll/src/synthetic_lights.cpp`, `remix_lights.cpp`, `remix_api.cpp` | Light sources for Remix from game events (upstream) |
| `linux/` | `install.sh`, `run.sh`, `laa.sh`, `loadcheck.cpp`/`sehcheck.cpp` (`make check`), `docker/` recipes and scripts |
| `tools/` | Asset pipeline (below) |

Ini keys that matter for the new features: `[camera] mode, toggle_key, demo_switch_seconds`;
`[renderer] car_models3d, hd_tile_max, dump_tiles, anisotropy`; `[sky] enabled,
follow_clock, sun_*`; `[devtools] log_keys, warp_key, scene_key, scene_xy`.
All documented inline in `package/gta2dx9.ini`.

## 4. Assets: what is in git, what is not, how to regenerate

Shipped in git: `assets/models/*` except the car models and the avatars (props, objects,
code objects such as booths, lights and pickups: MIT/CC0 or our own procedural models),
`assets/models/manifest.json`, `package/rtx-remix/mods/gta2hd/mod.usda`. Release archives
and their layout: section 0.

**Not in git** (they embed the game's own artwork, which cannot be redistributed;
ship them as release archives or regenerate from the user's game copy):

| Folder | Size | Regenerate with |
|---|---|---|
| `assets/models/human_*` (41 avatars) | ~330 MB | `tools/fetch_rocketbox_pro.sh`, `tools/make_ped_manifest.py`, `tools/army_olive.py`, `tools/gen_ped_clips.py`, then `tools/import_assets.py ../assets-src/manifest.json assets/models --only human_...` (`docs/actions-3d.md`) |
| `assets/models/0NN_*` (73 car models, TGA) | ~425 MB | `tools/make_car_manifest.py <assets-src> --models models_proc --override models3d` then `tools/import_assets.py <assets-src>/manifest.json assets/models` |
| `assets/textures_hd/{wil,bil,ste}` (DDS) | ~550 MB | `dump_tiles=1` run, `tools/upscale_textures.py`, `tools/enhance_textures_sd.py`, `tools/pack_textures_dds.py` (`docs/hd-textures.md`) |
| `package/rtx-remix/mods/gta2hd/textures` (DDS) | ~190 MB | `tools/remix_materials.py` (`docs/remix-materials.md`) |

Source generators (outside the repo on the original machine, under
`~/gta2-linux/assets-src/` and `~/gta2-linux/gen3d/`; copy them along or rebuild):

- Cars: `assets-src/cars/` catalog (`parse_sty.py`, `catalog_build.py` ->
  `catalog.json`, sprites, ESRGAN x4 sprites), `models_proc/` from
  `tools/gen_car_proc.py` (CPU, trimesh), `models3d/` from `gen3d/car_pipeline.py`
  (SDXL + TRELLIS, one GPU with >= 24 GB, ~90 s per car) fitted by
  `tools/make_car_model.py` (`docs/car-3d-pipeline.md` has the install steps).
- People: `assets-src/humans/` (Rocketbox FBX -> glTF with FBX2glTF, animations merged by joint name).
- Objects: `tools/gen_objects.py` (`assets-src/objects/`).

GPU needs: ESRGAN/SD/TRELLIS steps want a CUDA GPU; everything at run time is
plain Direct3D 9 (any GPU, or llvmpipe).

## 5. Build

Windows: Visual Studio x86 toolset, `dll\build.bat` and `vid\build.bat`, or
`package.bat` for the release layout. Untested on this branch since the Linux
work: fix what MSVC reports.

Linux: `apt install mingw-w64 make` then in the repo

```
make -j8 stage      # both DLLs + stage/ with ini, models, HD tiles
make check          # loads the DLLs under Wine (loadcheck, sehcheck)
```

The Makefile has `-MMD` header dependencies; run `make clean` after changing
object layouts if anything behaves oddly. Always build under
`flock /tmp/gta2-build.lock make -j8 stage` when more than one agent works.

## 6. Run

Windows: follow README "Install"; copy `stage/`-equivalent files
(`gta2dx9.dll`, `gta2dx9_vid.dll`, `gta2dx9.ini`, `gta2dx9_models/`,
`gta2dx9_textures_hd/`) into the game folder, run `install.reg`.

Linux, no container: `linux/install.sh <GTA2 installer or folder> <upstream
release zip>` then `linux/run.sh`.

Linux, container (what every recording used). Layout expected by the scripts:

```
~/gta2-linux/
  game/                   the user's GTA2 9.6 files (extracted installer)
  upstream-release/files  kirmm3la's v1.1 release, unzipped
  remix-runtime/x86       Remix Plus 1.5.1 runtime (only for Remix runs)
  repo/                   this repository, with stage/ built
  gamerun/                the scripts in linux/docker/ (copy them here)
  out/<run>/              one folder per run: game.mp4, shot_*.png, gta2dx9.log, keys.log
```

```
docker build -t gta2-remixbox -f repo/linux/docker/Dockerfile.wine9 repo/linux/docker
mkdir -p out/demo && docker run --rm --cpus=8 \
  -v $PWD/gamerun:/work -v $PWD/game:/game:ro -v $PWD/upstream-release/files:/release:ro \
  -v $PWD/repo/stage:/stage:ro -v $PWD/remix-runtime/x86:/remix:ro -v $PWD/out/demo:/out \
  -w /work gta2-remixbox bash /work/run_game.sh win32 240 0 /work/keys_demo_fp2.sh
```

GPU (headless NVIDIA): build `Dockerfile.gpu-gl` on top (image `gta2-gpugl`,
needs the NVIDIA container toolkit), run the same with `--gpus '"device=0"'
-e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility` and `run_game_gpu.sh`.
Note the Xvfb line pins Mesa's EGL vendor (`__EGL_VENDOR_LIBRARY_FILENAMES`):
with the NVIDIA EGL vendor Xvfb's software GLX segfaults; VirtualGL still goes to the GPU.

Remix: `Dockerfile.wine10-patched` -> `Dockerfile.runtime-ubuntu2510` ->
`Dockerfile.remix-gpu`, then `run_remix_gpu.sh`; status in section 2.

`run_game.sh` knobs (env): `INI_EXTRA` (file appended to the ini: only for
sections the ini lacks), `INI_SED` (sed script over the ini, e.g. turn devtools
keys on), `LAA=0`, `SWAP_LEVEL=ste|bil` (another district as level 1),
`DUMP_TILES=1`, `LP_NUM_THREADS`. The last argument is a keys script run
inside the container with `DISPLAY=:99` (xdotool).


### Play it interactively (browser)

`linux/docker/play.sh plain|remix [port]` runs the game in a `gta2-play` container on the
GPU and serves the display with x11vnc + noVNC; open `http://localhost:6080/` (tunnel from
another machine with `ssh -L 6080:localhost:6080 <host>`). `play.sh stop` ends it. Built with
`docker build --build-arg BASE=gta2-gpugl -t gta2-play -f linux/docker/Dockerfile.play linux/docker`
(and `BASE=gta2-remix-gpu3 -t gta2-play-remix`). Details in `linux/README.md`, "Play it in a
browser". Verified on the L4 host: a VNC client's keystrokes reach the game (V switches the view
in `gta2dx9.log`), the level renders in all three views (`out/play_interface_sheet.png`).

## 7. Scripted play

- `drive_lib.py`: `start()` (window, intro, menu, level), `wait_state()` parses the
  renderer's `view: player` line, `goto(x, y)`, `tap`, `hold`, `calibrate_turn()`.
- `demo_fp.py` / `keys_demo_fp2.sh`: walk to the carriageway pavement, V into
  first person, walk, V back. `final_demo.py`: the full continuous take incl. a
  natural car entry. `cars_drive.py`: F10 scene car + Return, drive in each view.
- `qa_*.py` with `qa_run.sh <name> <seconds>`: wall, backforth (incl. rapid V),
  fight, crash, death, long. `qa_lib.py` reads the view back from the log.
- `slot.sh`: at most `GTA2_SLOTS` game containers at once on a small host;
  `/tmp/gta2-gpu.lock` serialises GPU generation jobs.
- Devtools (ini `[devtools]`, off by default): `log_keys=1`, `warp_key=F9`
  (player to the nearest parked car's door), `scene_key=F10` (nearest parked car
  brought to `scene_xy`, player at its door). Enable per run with
  `INI_SED='s/^warp_key=.*/warp_key=F9/; s/^scene_key=.*/scene_key=F10/'`.
- The `view: player` log line (twice a second): `x y z face=fx,fy on foot|driving |
  car nearest x y d (driven) | parked nearest x y d | carhead parkedhead ped
  state sub pend veh | me phys sprite cardrv src`. Ped `state` 2 = walking to a
  car, 3/6 = getting in, 10 = driving, 4/7 = getting out. Status lines:
  `view: classic|third person|first person ...`, `view: waiting for the player`,
  `view: fp eye ... floor ... lid under the eye`, `frame times, avg/worst ms ...`
  every 256 frames, `car models: N textures, X MB` every 900 frames, `FAULT` on a crash.

## 8. Working conventions (what the swarm used)

- One subsystem per agent, by file: cars (`car_bodies.cpp`, car paths of
  `live_geometry.cpp`), people (pedestrian block, `model_store.cpp` skinning),
  world/sky (`renderer.cpp`, `world_mesh.cpp`, `sky.cpp`), camera
  (`view_modes.cpp`, `world_view.cpp`), objects (`map_objects.cpp`). Re-read a
  file right before editing it; never revert another agent's hunk.
- Build only under `flock /tmp/gta2-build.lock make -j8 stage`; no `make clean`
  without the lock. Game runs through `slot.sh`; GPU jobs under `/tmp/gta2-gpu.lock`.
- A run is a folder under `out/`: keep `gta2dx9.log`, shots, a contact sheet
  (`ffmpeg -vf "fps=1/5,scale=480:-1,tile=5x4"`), and `marks.txt` for cuts.
- Report verified (seen in frames/logs) separately from untested. Never claim
  Remix works without path-traced frames.
- Never download the game; never commit or publish anything containing the
  game's artwork (the `.gitignore` patterns above); third-party assets only with
  MIT/CC0-class licences, recorded in `assets/README.md`.
- Coordinator commits; agents report file lists.

## 9. Evidence folders on the original machine

`~/gta2-linux/out/` holds every run (sheets `*_sheet.png`), `~/gta2-linux/deliverables/`
the cut clips and archives (`textures_hd_dds.zip`), `~/gta2-linux/assets-src/` the
generator inputs/outputs, `~/gta2-linux/gen3d/` the TRELLIS environment. They are
not in git; copy what you need.
