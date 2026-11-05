# GTA2 RTX Remix — HD Cars Edition

GTA2 path-traced with [NVIDIA RTX Remix](https://github.com/NVIDIAGameWorks/rtx-remix), with hand-made HD cars,
real glass, doors and dents, working lights and new voice packs.

<img width="1751" height="173" alt="gta2 rtx upgraded" src="https://github.com/user-attachments/assets/38adc172-302d-4d7f-b37e-8026d78dd557" />

https://github.com/user-attachments/assets/38f0c67a-ba31-46e7-a305-c5b6cfbde161

<img width="3840" height="2160" alt="Grand Theft Auto 2 2026 11 01 - 12 16 56 07 00_00_15_26 Still002" src="https://github.com/user-attachments/assets/48fe2029-cf81-48f3-a180-14d13b71fd2a" />
<img width="3840" height="2160" alt="Grand Theft Auto 2 2026 11 01 - 12 16 56 07 00_01_02_47 Still003" src="https://github.com/user-attachments/assets/bbcffc85-eaff-49e3-98c0-7bd6405a21e8" />

This project is an upgrade of **[gebdag/gta2-rtx-remix](https://github.com/gebdag/gta2-rtx-remix)**, the
Direct3D 9 renderer that makes GTA2 run on RTX Remix. All the renderer work is theirs; thank you.
Everything on top of it (HD cars, car damage, lights, blood, voices and more) is added here.
Both projects are MIT licensed.

## Install (3 steps)

1. **Install RTX Remix.** Download `Remix_Plus_v1.5.1_x86_games_release.zip` from the **Assets** list at the bottom of the
   [Remix Plus 1.5.1 release page](https://github.com/RemixProjGroup/dxvk-remix/releases/tag/remix-plus-1.5.1) and unzip it into
   your GTA2 folder, next to `gta2.exe`. (Without Remix the game starts, but with no ray tracing.)
2. **Download** the zip from [Releases](../../releases) and **unzip it into your GTA2 folder**. Say yes to replacing files.
3. **Start `gta2.exe`.**

That's it. Press **F4** in game for the settings panel (the game's own **Options** button opens it too).
Installing never touches your player profiles or saves.

**You need:** your own copy of GTA2 (v9.6 is what it was tested on; this project ships no game files), an
RTX-capable GPU with a current NVIDIA driver, and Windows 10 or 11, 64-bit.

**Where to get GTA2:** see [Where to get GTA2](#where-to-get-gta2) below.

**Something wrong?** Check `gta2dx9.log` next to `gta2.exe`, and the troubleshooting list in `gta2dx9_README.txt`
inside the zip.

## Third person and first person

Press **V** in game to cycle three views:

- **Classic** - GTA2's own view from above, exactly as before.
- **Third person** - a chase camera behind you, on foot or at the wheel. The mouse orbits round you and
  swings back behind you on its own; the camera stops short of walls instead of going through them.
- **First person** - from your own eyes, or the driving seat, with mouse look. Your own sprite and your
  car are left out of the picture.

The city is already real 3D geometry under RTX Remix, so the two new views are the same path traced
world from a different place. From the ground the picture is rebuilt to read as a real street while the
top-down view stays the game you know:

- **Sky and air** - a sky dome with sun, clouds and distance haze, faded in and out through the view
  transitions (`[sky]` in `gta2dx9.ini`); the classic view keeps the game's own black surround.
- **HD tiles** - every tile of all three districts at 512 px (Real-ESRGAN plus SD1.5 ControlNet Tile,
  block-compressed with mips, generated from your own copy of the game by `tools/pack_textures_dds.py`,
  see `docs/hd-textures.md`); the game's copy of `gta2.exe` is made large-address-aware for the memory.
- **Cars** - every one of the game's 73 vehicle types has its own 3D model, chosen by the vehicle's model
  number and repainted from its live sprite: 60 are image-to-3D period designs (SDXL concept from the
  sprite and its design brief, TRELLIS, then fitted to the sprite's footprint with the sprite projected
  onto the roof so the top view is the game's own art), the rest parametric 1940s-60s bodies from the
  sprite's CARI data (`docs/car-3d-pipeline.md`, `tools/gen_car_proc.py`). From the driving seat your own
  car's hood frames the road.
- **People** - nine Microsoft Rocketbox avatars (MIT), skinned on the CPU with walk and idle cycles,
  chosen per pedestrian and facing the way they move; the player keeps one look.
- **Objects** - the map's own objects (crates, cones, drums, benches, tyres, the terrace slabs...) and
  rule-placed street furniture (lamps, bins, benches, hydrants) as Poly Haven or procedural models that
  match their sprite's footprint and colour.

Everything comes back to the top-down numbers when the classic view does, and each piece can be switched
off (`car_models3d`, `[sky] enabled`, the Camera tab's models and props toggles).

Everything about the views - the key, distances, heights, fields of view, mouse sensitivity, and how far
beyond its own window the game is asked to populate the streets - is on the **Camera** tab of the F4
menu, and `mode=` / `toggle_key=` under `[camera]` in `gta2dx9.ini` set the view to start in and the key.

Two things to know. GTA2 only creates, draws and removes cars and pedestrians inside the window its own
top-down camera frames; a chase camera sees past that window, so it is widened (×1.8 out of the box,
needs **Spawn offscreen** on, which it is by default) and traffic further away than that does not exist
yet. And the player is found by recognising his structure in `gta2.exe`'s memory rather than by an address:
if `gta2dx9.log` says `view: waiting for the player`, the classic view stays up and the Camera tab says why.

### The asset pipeline

`tools/import_assets.py` turns glTF files into the renderer's own model format (GMSH v2: meshes,
skins, animations) plus TGA textures, from a manifest that says which model stands in for what:

- **cars**: `by_model` maps the game's vehicle model number to a model (`tools/make_car_manifest.py`
  writes it from the car catalog and the generated GLBs; `paint_split` entries get a second
  `_paint` texture so only the body colour is retinted per remap);
- **pedestrians**: a list of skinned characters with `walk` and `idle` animations, chosen per
  pedestrian; **pedestrian**: the player's own;
- **objects**: `"<sprite base>:<frame>"` to a model for the map's objects;
- **props**: `lamp`, `bin`, `bench`, `hydrant`, placed by rule.

`assets/README.md` has the licences and the regeneration commands. The generated car models and
HD tiles contain the game's own artwork, so they are not in the repository: they are rebuilt from
your copy of the game with the tools above (GPU needed for the AI steps), or unpacked from the
archives you built yourself.

### Recording the switch

`tools\record_demo.ps1` records a video of the game starting in the classic view and switching to first
person (or third person) by itself a few seconds into a level, using ffmpeg's desktop duplication, which is
what sees the path traced picture (a plain screen grab of a Remix window is black):

```
powershell -ExecutionPolicy Bypass -File tools\record_demo.ps1 -GameDir "C:\Games\GTA2"
```

It needs [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) on the PATH. The switch itself is
`demo_switch_seconds=` under `[camera]` in `gta2dx9.ini`, which the script sets and puts back.

## What you get

- Third person and first person views, cycled with one key (see above)
- Hand-made HD cars with full PBR maps and real glass (top-down); a 3D period model per vehicle type on the ground
- 512 px HD tiles for every district, a sky with sun and clouds, realistic pedestrians and objects in the ground views
- Doors and dents drawn on the HD cars, wheels, roof domes and gang roof logos
- Taxi, police and emergency lights; blood puddles on the road
- Radio stays in stereo at any distance (the original distance effect is a menu option)
- Voice packs
- Everything from the original project: lights from the game's own events, dynamic time of day
  (Remix Plus only), emissive maps, animated water, full 16:9, and 60 fps with frame generation

## Linux

No Windows needed, for building or for playing. `make` builds both DLLs with the MinGW-w64 cross compiler
and `make check` loads them under Wine; `linux/install.sh` sets up a Wine prefix with the game, the
upstream release and this build, and `linux/run.sh` starts it. Everything, including what RTX Remix
does and does not do under Wine, is in [linux/README.md](linux/README.md).

## Where to get GTA2

GTA2 was officially free for a while: Rockstar gave it away as part of its **Rockstar Classics** series, together with the first
GTA and Wild Metal Country. That free offer has ended. Rockstar later sold it on its own store (until 2013, according to
[Delisted Games](https://delistedgames.com/?p=10001)), and Steam removed its GTA2 page in July 2025 without explanation.

So today there is no official place to get it. The game is still easy to find online if you look for it (searching for
"GTA 2 Rockstar Classics" is a good start), but those copies come from third parties, so use one you trust, or a copy you
already own (the original CD, or an old Rockstar or Steam purchase). This project ships no game files and does not host or
link to downloads of the game.

## Known issues

The tank turret still uses the original low-resolution art, the 5-star FBI cars are blue instead of black,
and a few cars still have odd windows. More in the [release notes](../../releases).

## Autosave

The mod saves your game by itself a moment after a big payout (a mission reward, for example), so a crash costs you less.
This is on by default. To turn it off, press **F4** in game, untick **Save after a big payout** and click **Save**, or
add these two lines to `gta2dx9_settings.ini` in your GTA2 folder:

```
[save]
auto_save=0
```

## Uninstall

Delete the `gta2dx9*` files, `gta2dx9_hd`, `gta2dx9_voice` and `rtx-remix\mods\gta2rtx` and `gta2water`, and run
`uninstall.reg`. The install replaced three of GTA2's own files (`d3ddll.dll`, `Dmavideo.dll`, `DMAGlide.dll`), so to get
the original game back, copy those three from a backup if you made one (optional, before step 2), or reinstall GTA2.

## Building from source

Needs Visual Studio with the C++ x86 toolset.

```bat
package.bat
```

Builds `dll\build\gta2dx9.dll` and `vid\build\gta2dx9_vid.dll` and assembles the release files in `release\`.
The two DLLs can also be built alone with `dll\build.bat` and `vid\build.bat`. The RTX Remix API headers in
`dll\deps\bridge_api` must match the Remix runtime the game uses (see `dll\deps\README.md`).

```
dll/        gta2dx9.dll, the renderer
vid/        gta2dx9_vid.dll, the video device shim
src/        map, style, mesh, camera and D3D9 renderer code used by the DLL
package/    release files: settings, registry files, player README, tuned ini files
tools/      development tools
docs/       research notes
```

Technical notes on the renderer are in `dll/README.md`.

## Legal

MIT licence, see [LICENSE](LICENSE); third-party components are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
This is an unofficial fan project. GTA2 is a trademark and copyright of Rockstar Games / Take-Two Interactive,
and this repository and its releases contain no game files.
