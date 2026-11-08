# RTX Remix materials for the world tiles (Linux build)

**6 Nov 2026, verified on an NVIDIA L4:** the layer applies under RTX Remix with the
HD tiles installed. What the runtime hashes for a block-compressed tile was settled by a
probe run (`tools/remix_hash_probe.py`): it paints a flat magenta material under
XXH3-64 of the **top mip's block bytes** and cyan under the hash of the whole mip chain;
the game came up magenta everywhere (`out/remix_probe1`, frames in
`out/remix_materials_sheet.png`). So for an HD tile (`assets/textures_hd/<style>/tile_NNNN.dds`,
DXT1/DXT5, 512 px, 10 mips, uploaded by `src/renderer.cpp CreateDdsTexture` through a
system-memory staging texture and `UpdateTexture`) the material name is
`mat_<xxh3_64(level 0 blocks)>`; the mip chain, the DDS header and the staging/default
pool do not enter. For the 64 px tiles and every model texture (single-level A8R8G8B8,
`dll/src/model_store.cpp TextureFor`) it is `xxh3_64(BGRA texels, rows top-down)` as before.

The shipped layer is now `package/rtx-remix/mods/gta2hd` built in the DDS-keyed mode:

    python3 tools/remix_materials.py - package/rtx-remix/mods/gta2hd \
        --dds-tiles assets/textures_hd/wil assets/textures_hd/bil assets/textures_hd/ste \
        --size 256 --exclude <upstream mod .usda files>
    python3 tools/remix_model_materials.py assets/models package/rtx-remix/mods/gta2hd

2 649 tile materials (the DDS itself is the albedo, no re-encode; 256 px octahedral BC5
normal and BC4 roughness from its pixels) plus 314 car-paint materials
(`<car>_N_paint.tga` as BC3 albedo, metallic 0.6, roughness 0.3, so paint reads as glossy
metal; the renderer's per-car tint is a texture factor, which Remix keeps). 973 MB on
disk; shipped as the release archive `remix_mod_gta2hd.zip`, not in git. The older 64 px
keyed layer only applies when the HD tiles are absent (`NO_HD=1`).

Not tuned by measurement: the roughness heuristic (below), the paint constants, and the
runtime's exposure (see `docs/remix-gpu-l4.md`).


## Cars, alpha state, roughness with the HD tiles, rebuilding (REMIX-POLISH, 8 Nov 2026)

**Roughness applies with the HD tiles (verified).** The colour probe above proved the
albedo hash; this pass checked a second input. `gamerun/remix_probe_rough/` is the shipped
layer with every tile prim's roughness texture replaced by `reflection_roughness_constant
= 0.03` (textures linked, not copied); run `out/remix_pol_rough` (`MODS_HD_SRC=/work/remix_probe_rough`,
14:00, HD tiles installed, same key script as the day take; the probe's `mod.usda` is the shipped one with each tile prim's `reflectionroughness_texture` block and `reflection_roughness_constant = 0.8` replaced by `= 0.03`, and `textures` a symlink to `/package/rtx-remix/mods/gta2hd/textures`; not committed) shows the walls and kerbs of
the spawn plaza as glossy mirrors reflecting the sky and the neon, where the shipped
layer (`out/remix_pol_day3`) shows them matte: the layer's material inputs, not only its
albedo, reach the HD tiles. The hashes did not need regenerating: all 846 / 930 / 876 HD
tiles of wil / bil / ste in the current stage have a prim in the layer (checked with
`remix_materials.dds_hash`). Frames: `out/remix_hd_roughness_probe.png`.

**Alpha state.** Every prim used to say `use_legacy_alpha_state = 0`, whose MDL defaults
are "alpha test: always, no blend": the 665 HD tiles with cutout alpha (fences, railings,
gratings, tree edges) were path traced as opaque. Tile prims now keep the game's alpha
state (`= 1`, `remix_materials.py MATERIAL`); the shipped `mod.usda` was patched in place.

**Car paint, trim and lamps** (`tools/remix_model_materials.py`, rewritten). The 3D car
models are drawn twice per car (car_bodies.cpp: the `_paint` half and the rest, each
alpha-tested at 128, same mesh, same transform). Under Remix the second draw is taken as a
duplicate of the first, so with each half's own alpha only one half of the car was path
traced (run `out/remix_pol_day2`: cars in pieces, a different half from frame to frame).
Both prims of a split pair therefore carry one opaque whole-car material, built from
copies (the baked TGAs are not touched):

* albedo: the two halves merged (paint texels from `_paint`, the rest from `_N`);
* paint texels: clear coat approximated as a smooth dielectric with some flake,
  metallic 0.2, roughness 0.12 (AperturePBR has no second specular lobe; this gives the
  sharp sky/lamp reflections over the coloured paint of a coat, where the old 0.6 / 0.3
  turned the paint into dark tinted metal);
* the rest, per texel from its colour: bright neutral texels in a busy neighbourhood
  chrome (1.0 / 0.16: bumpers, strips, hubcaps, grilles), mid-grey busy texels brushed
  metal (0.7 / 0.32), dark blue-grey glass (0 / 0.05), near-black rubber (0 / 0.6),
  anything else painted body with the coat;
* saturated red texels (tail and brake lamps) an emissive mask in their own colour,
  intensity 6, so the lamps glow at night.

Lone textures (the 13 parametric cars' part textures: chrome, lamp, tyre ...) get the same
per-texel maps and keep the game's alpha. 60 split pairs, 113 lone trim and 92 lone paint
textures, 34 prims with lamp emission. `--preview <dir>` writes the albedo / metallic /
roughness / emissive maps per texture. The renderer's per-car paint tint (a texture-stage
factor) is not reproduced by a replacement material, so under the layer every car of a
model shows the model's own paint colour (untested whether Remix applies the factor).

**Rebuilding and shipping the layer.** `gamerun/build_remix_mod.sh` (`linux/docker/`) runs
the three passes in the order that keeps each one's prims: tiles (`remix_materials.py
--dds-tiles`, rewrites `mod.usda`), sign emission (`remix_emissive.py`, rewrites it again),
cars (`remix_model_materials.py`, replaces only its own prims; re-run it alone after the
car models change). `ZIP=1` packs `deliverables/remix_mod_gta2hd.zip` (mod.usda +
textures/, ~1 GB, store-only) for the release page; the DDS embed the game's art, so the
textures stay out of git and only `mod.usda` (hashes and constants) is committed.

## Liveries, the driver's seat, the night lights (REMIX-3, 8 Nov 2026)

Nine Remix sessions on the L4 (`out/remix3_a` .. `remix3_i`), Downtown, clock paused, all
on a private stage (`stage_remix3`: the committed tree plus these changes, the current
models). The clock is moved inside one session with a new devtools key, so a car or a
street is seen by day, at dusk and at night in the same take. Sheets (local):
`out/remix3_cars_sheet.png`, `out/remix3_driver_sheet.png`, `out/remix3_lights_sheet.png`.

**Cop car and taxi in another car's colours: the paint tint, and a devtools artefact.**
The renderer's per-car paint tint *is* applied under Remix (`rtx.enableMultiStageTextureFactorBlending`
is on by default; the tint is the stage-1 texture factor). The tint is the sprite's measured
paint over the model's own, so with `force_car_model` every model was drawn in the colour
of the parked car whose sprite it stood on (REMIX-POLISH's `remix_pol_day3`: cop and taxi
in the same brown). `car_bodies.cpp` now leaves the tint off (no stage at all) for the
livery models (`LiveryModel`: bank van 4, bus 11, cop 12, fire truck 17, army jeep 22,
hot-dog and ice-cream vans 23-27/85, medicar 34, taxis 51/56, SWAT 52, tank 54, trains
59-61, TV van 67, special agent 84, karma bus 86) and for a model forced by the devtools.
Seen in `remix3_b/e/g/i`: the cop car navy and white with its door badge, the taxi
yellow with its chequer, the medicar white with red stripes and crosses, the bus cream
and red, the fire truck red, by day, at dusk and at night. Ordinary cars keep their tint
(the game's remaps).

**Car material layer rebuilt** (`build_remix_mod.sh`, all three passes, so the prims of
the 33 replaced CAR-QUALITY-4 models' old textures are gone: 2 649 tile prims, 64 of
them with sign emission, and 215 car prims, 2 864 in all). The tail-lamp emission used to take every saturated red texel;
on the new models that is the medicar's crosses and stripes and the bus's red band (1 138
and 1 490 texels would have glowed at night). `remix_model_materials.py` now takes only
compact red islands (at most 0.25 % of the texture, no longer than 4:1, at least 35 %
filled) at the car's ends (the texels the mesh's triangles in the last 14 % of the length,
facing along it, cover: `end_masks`, a UV rasterisation of the `.mesh`): medicar 93
texels, bus 228, cop 0; 22 prims with lamp emission. Most generated models have no red
tail-lamp texels at all, so at night the lamps are the `[Car lamps]` lights (head and
tail lamps as small coloured lights, `remix3_g/i`).

**The driver's seat.** Remix ignores user clip planes, so the own car is drawn from a
CPU-cut hood copy (`HoodModelFor`, there before this pass). It kept every face with
|normal y| > 0.35 below the eye and ahead of the windscreen, which included the faces that
look *down* (the hood's underside, the floor pan and underbody ahead of the seat); the path
tracer draws back faces, so from the seat they were black shreds across the view
(`remix3_b`, a Schmidt). The copy now keeps the faces the eye sees from their front
(vertex normal towards the eye, in the car's frame, so the fit's mirror does not matter)
and not looking down by more than a little: from the Schmidt's seat a black hood with its
chrome headlamps and ornament, by night and by day, while moving (`remix3_e/g`). The fire
truck's short hood lies below the view from its cab: nothing of the body shows, nothing
broken (`remix3_c/h`, by day and at night). The cache key now includes the eye's x.

**The floodlit night: the game's D3D9 directional light.** The night plaza at 198,188 read
as daylight with hard parallel shadows (a lamp post's shadow across the square, a fence
casting a crisp shadow at 22:30 in `remix3_f`). Not a lamp of ours: with every one of our lights off
(`remix_lights_off`) the plaza was unchanged (`remix3_d`); not the atmosphere's sun or moon
light, the moonlight or the exposure cap (pushed live, `remix3_e`: no change); not the
runtime's fallback light (it only appears in a frame with no lights at all, and then it
does flood a scene: `remix3_c`, lights off). It is the D3D9 directional light the renderer
sets for its fixed-function shading (`car_bodies.cpp` for the car bodies, `src/renderer.cpp`
for the world in the street views): Remix converts it to a distant light at full strength,
the same direction by day and by night. With `rtx.ignoreGameDirectionalLights = True` set at
start (`remix3_g`, `remix3_i`) the plaza is a night street: dark paving, lamp pools, the neon
and the windows; by day the atmosphere's sun alone gives the same sunny street
(`remix3_h/i`). `rtx.fallbackLightMode = 0` goes with it (by day, with every lamp gated off,
a frame can have no lights and would get the fallback's second sun). Both are in
`package/rtx.conf` and `linux/docker/rtx_showcase.conf.extra`. Note: these two options, pushed
live through the Remix API, changed nothing in a running session; only set at start do
they apply. The attribution between the two rests on the fallback's rule (no lights at all),
not on a run with one of them alone.

**The other lights** (`remix3_a`, `remix3_d`, `remix3_i`): traffic-light lenses throw red,
amber and green pools at night and at dusk; the JESUS SAVES neon and the lit windows read
at night without blowing out; machine-gun shots light the paving round the shooter;
a rocket into a parked van gives the fireball, its light on the square and the scorch
(before the light fix, so the square is still floodlit there); dusk (18:00) is a violet sky
with the lamps coming on. The siren beacons (`force_sirens=1` on cop car, medicar, fire
truck) light the roof and the road, but each bulb is seen as a white flare beside the light
bar: a 3 cm bulb with the beam's power clips every channel. Drawing the bulb at 9 cm with
the radiance cut by the area gained (same power) did not visibly change it (`remix3_i`), so
that change was not kept; the siren defaults are `synthetic_lights.cpp`'s.

**Devtools added** (`[devtools]`, re-read once a second, `remix_lights.cpp`):
`set_hour_tenths=N` sets the clock to N/10 h when the value changes; `remix_config=key=value|...`
pushes runtime options (see the note above: not every option applies live);
`remix_lights_off=1` withholds all our lights. `GTA2DX9_LOG_REMIX_LIGHTS=1` logs, every 256
frames, the ten lights (cones excluded) that light the ground under the eye most.

**Take.** `linux/docker/remix_showcase.py` plays the REMIX-3 parts when `PART` is set
(`cars`, `nightcars`, `sedan`, `lights3`, `truck3`, `exposure`, `debuglights`, `fb`, `ab2`, ...),
e.g. `STAGE=<stage> gamerun/remix_l4.sh remix3_i 1150 /work/keys_remix_showcase.sh -e MODS_HD=1
-e LEVEL_WAIT=60 -e RTX_EXTRA=/work/rtx_showcase.conf.extra -e INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/'
-e SCENE_KEY=F11 -e SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=14/'
-e EFFECTS_SED='/^\[Car lamps\]/,/^\[/{s/^Enabled=0/Enabled=1/;s/^Daylight=0/Daylight=1/}'
-e DUSK=18.0 -e PART=cars,sedan,lights3 -e CAR_MODELS=12,56,34,11,17,18,31`; the fire truck
needs its own session (`-e GTA2DX9_SCENE_MODELS=17 -e PART=truck3`: every scene warp then goes
to it). Frames: `remix_frames.py dump out/<run> <secs> <dir> <label regex>`.

**Release archive.** `deliverables/remix_mod_gta2hd.zip`, 1 055 593 417 bytes (1.06 GB,
store-only: `mod.usda` + 8 508 textures), from the rebuilt layer. `build_remix_mod.sh`'s
`ZIP=1` step now writes it by absolute path (the 8 Nov rebuild's `$OLDPWD` path wrote none;
the archive here was packed by hand with the same command).

**Not verified.** A police chase under Remix: three stars kept by `force_wanted` brought no
police within 45 s in two sessions, so the light bars were seen only on parked cars with
`force_sirens`; the booth's lit PHONE sign and glass were not framed close enough to judge
(the booth is in `remix3_i`'s frame, small); the muzzle flash itself (its light on the paving
is seen, the flash sprite not caught in a frame); the explosion and fire after the light fix;
clear-coat reflections are visible on the roofs by day but were not compared with the
REMIX-POLISH constants; Industrial and Residential were not rerun.

This note records what NVIDIA offers for turning GTA2's 64x64 tiles into PBR
materials, why none of it runs on this Linux/B200 machine, and what
`tools/remix_materials.py` produces instead: a complete Remix material layer,
`package/rtx-remix/mods/gta2hd`, built from the same inputs the Toolkit would
use and in the formats the runtime reads directly. It has **not** been rendered
under Remix: the runtime needs an RTX GPU with a Vulkan ray-tracing driver, and
this machine's B200s expose no Vulkan graphics, and the CPU Vulkan driver
(lavapipe) crashes inside the runtime's ray-tracing pipeline creation (the
Remix stream's report has the details). Everything else below is verified on disk.

## 1. What NVIDIA provides, and where it runs

| Piece | What it does | Where it runs | Source |
|---|---|---|---|
| RTX Remix Runtime (dxvk-remix + bridge) | Replaces the game's D3D9 renderer with a path tracer; swaps textures and materials by hash at draw time | Windows 10/11, "any RTX GPU", RTX 4070 recommended; runs under Wine/Proton with the bridge (this project's `gta2-wine` image), but the path tracer needs hardware Vulkan ray tracing | [Requirements](https://docs.omniverse.nvidia.com/kit/docs/rtx_remix/latest/docs/introduction/intro-requirements.html) |
| RTX Remix Toolkit | Omniverse Kit application: capture import, material editing, asset ingestion, packaging | Windows only (Omniverse Kit app; the requirements page lists Windows 10/11 and no Linux build) | same page |
| **AI Texture Tools** | Upscaling, PBR map generation (normal, roughness, metallic), style transfer, mesh processing | Inside the Toolkit, executed by **ComfyUI** through the "RTX Remix Node Pack"; ComfyUI needs an NVIDIA GPU with 8 GB VRAM or more (12 GB recommended) and may run on a separate machine, "e.g. a dedicated GPU server"; template workflows download models from Hugging Face on first run | [Using AI Tools](https://docs.omniverse.nvidia.com/kit/docs/rtx_remix/latest/docs/howto/learning-aitools.html) |
| Ingestion (GUI and `lightspeed.app.trex.ingestcraft.cli.bat`) | Converts PNG/JPG/DDS/EXR/... into the runtime's `.rtex.dds` files with full mip chains and writes the USD material layer | Part of the Toolkit install, so Windows | [Ingesting Assets](https://docs.omniverse.nvidia.com/kit/docs/rtx_remix/latest/docs/howto/learning-ingestion.html) |
| Material replacement | A USD layer that overrides `/RootNode/Looks/mat_<hash>/Shader` with an `AperturePBR_Opacity` or `AperturePBR_Translucent` MDL and texture inputs; hashes come from rendering the textures in a test level and capturing | Edited in the Toolkit or by hand in `.usda` | [Materials](https://docs.omniverse.nvidia.com/kit/docs/rtx_remix/latest/docs/howto/learning-materials.html) |

Conclusion for this machine: the only NVIDIA piece that could run here is
ComfyUI as the AI Texture Tools' remote backend (the Toolkit would still sit on a
Windows PC with an RTX card and talk to it). Nothing in the Toolkit runs on
Linux, and nothing in the AI Texture Tools runs without it. So the mod below is
built by a Linux script that does the same job: the hash, the maps, the DDS
files and the USD layer. On an RTX Windows (or Proton) machine the output drops
straight into `rtx-remix/mods/` with no ingestion step, because the files are
already in the runtime's formats.

## 2. The format, as used by the shipped mod and this one

* **Hash.** The runtime identifies a texture by XXH3-64 of the texel bytes it
  receives from the game. Our renderer uploads each world tile as a 64x64
  A8R8G8B8 texture, so the hash is `xxh3_64(ARGB little-endian texels, rows
  top-down)`, printed as 16 upper-case hex digits. `gta2dx9.ini: dump_tiles=1`
  writes those exact texels to `gta2dx9_tiles/tile_NNNN.tga`, which is the input
  of the script. Check: tile 608 (water) hashes to `A8B83A83052A85C0`, the hash
  the repo's existing water material targets; all 891 distinct tiles of the
  downtown dump hash to 891 distinct materials (two tiles are pixel-identical).
* **Layer.** `mod.usda`: `over "RootNode" { over "Looks" { over "mat_<HASH>" {
  over "Shader" { ... } } } }`, one prim per hash, `AperturePBR_Opacity.mdl`,
  `inputs:diffuse_texture` (sRGB), `inputs:normalmap_texture` (raw),
  `inputs:reflectionroughness_texture` (raw), metallic constant 0. Same shape as
  the mod's `gta2rtx` layer and `tools/make_water_mod.py`.
* **Textures.** `textures/<HASH>.a.rtex.dds` albedo, BC3 (DXT5) with the game's
  own cutout alpha; `<HASH>.n.rtex.dds` normal, BC5U storing the normal as
  **unsigned octahedral** in R/G, the encoding the runtime decodes (the Toolkit
  converts tangent-space normals to it on ingestion); `<HASH>.r.rtex.dds`
  roughness, BC4U. All with full mip chains down to 1x1. 256x256 each (ESRGAN x4
  of the 64x64 originals); `--size 512` works but only upsamples further.
  BC7 for albedo would be marginally better; there is no BC7 encoder here and
  BC3 is what the runtime's own DirectX 9 games ship.

## 3. How the maps are made (`tools/remix_materials.py`)

1. Albedo: the Real-ESRGAN x4 tile from `assets/textures_hd/<district>/`
   (`tools/upscale_textures.py`), optionally replaced per tile by the Stable
   Diffusion ControlNet-tile refinement (`--sd upscale/sd/out_chain`). The
   cutout alpha is resampled nearest from the 64x64 original so sprite edges
   stay exactly the game's.
2. Normal: height field = band-passed luminance of the albedo (fine detail
   minus large-scale shading, so a brick course becomes a ridge and a painted
   stripe does not become a step), Sobel slopes, DirectX tangent space,
   then octahedral-encoded per mip (normals renormalised before encoding).
3. Roughness: 0.2..0.98 from local contrast (busier = rougher) and brightness
   (bright, flat = smoother). A heuristic, not a measurement; it is what the
   AI Texture Tools would otherwise guess from the same single image.
4. `mod.usda` is regenerated from every `*.a.rtex.dds` in `textures/`, so
   several districts can be merged into one mod by running once per district
   with the same output folder (each district needs its own tile dump).
5. `--exclude <other mod.usd[a]>` skips hashes another layer already
   overrides (the water material, the lamp emissives); `--validate-only`
   re-hashes the dump and checks every prim, texture reference and brace.

Pure numpy/Pillow/xxhash; 892 tiles take about 45 s on one CPU core.

```
python3 tools/remix_materials.py <dump>/gta2dx9_tiles package/rtx-remix/mods/gta2hd \
    --hd assets/textures_hd/bil [--sd <sd tiles>] [--exclude <other>/mod.usda]
python3 tools/remix_materials.py <dump>/gta2dx9_tiles package/rtx-remix/mods/gta2hd --validate-only
```

## 4. What was built and checked

* `package/rtx-remix/mods/gta2hd`: 891 materials, 2673 DDS files, 196 MB
  (downtown district, `bil`; the residential `wil` HD set exists but no tile
  dump of that district was captured, so it has no hashes yet).
* Validator: 891 prims, all unique, all 2673 referenced files present, all
  891 hashes present in the dump, braces balanced.
* Every DDS decodes with Pillow (independent decoder): 9 mips each, albedo
  PSNR 35 dB against the ESRGAN source with the alpha bit-exact, octahedral
  normal round-trip error 0.007 mean / 0.05 max, roughness in range.
* Contact sheet of originals, albedo, normal and roughness for eight tiles:
  `upscale/pbr/gta2hd_contact_sheet.png` (outside the repo).

## 5. Not verified, and what it takes

* A Remix frame with these materials. Needs a machine with an RTX GPU
  (Windows, or Linux with Proton plus the bridge the way this project's
  `gta2-wine` image runs it) and the NVIDIA driver's Vulkan ray-tracing
  extensions. Install: copy `package/rtx-remix/mods/gta2hd` next to
  `mods/gta2rtx`, start the game through the bridge, open the Remix menu
  (Alt+X) and confirm the materials are listed as replaced. If a tile shows
  unreplaced, its upload bytes differ from the dump (e.g. a different
  `gta2dx9.ini` texture filter); re-dump on that machine and rerun.
* Whether the runtime applies a normal `encoding` flag by file naming
  (Toolkit output uses `_OTH_` in file names) or purely by format; the
  water layer in this repo relies on BC5U octahedral by format, this one too.
* Fidelity: the albedo is an upscale of the 1999 art, not photographed PBR. The
  AI Texture Tools would produce the same class of result from the same input;
  a true "AAA" look needs new materials (the Poly Haven CC0 sets already in
  `assets/`) assigned per tile class, which the layer format supports: replace
  the three textures for a hash with any 2K set.

## 6. No per-view switch under Remix

Remix replaces materials per texture hash at draw time; it does not know which
camera mode the renderer is in. This layer therefore applies in the top-down
view as well, at higher resolution but the same art, which keeps the GTA2 look
from above. A different look per view would need the renderer to upload
different tile texels per mode (then the hashes differ and two layers can
target them); that is a renderer change, not a Remix one, and is not done.
