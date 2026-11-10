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
For model textures this was confirmed in path-traced frames on 9 Nov (REMIX-HASH-VERIFY section below);
figure bodies under Remix are drawn from baked copies that no prim names.

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

**The harness default carries them too (FIX-REMIX-RETURN, 10 Nov).** `gamerun/remix_l4.sh`
without `RTX_EXTRA` appends `rtx_gpu.conf.extra` to the upstream release's rtx.conf, which
had neither line, so its takes showed the light above: street views floodlit at night (centre
luma 62-66 against 34-49 as shipped) and the classic view daylit for ~6 s after every V back
from them (luma 125-129 against 55, hard roof shadows), until Remix let the unseen distant
light go. That was filed as a classic regression (pt-remix-classic-daylight-flash); with
`rtx_play.conf.extra` or the two lines added to `rtx_gpu.conf.extra` (now there) the same
HEAD DLL keeps the return at night (every shot within 12 % of the classic before the visit).
Our own lights retire on time: the lamp pools on the presentation-classic frame, the far lamps
over the next ~1.5 s with the sky blend. Judge any Remix look on a config that has both lines.

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

**After car round 6 (QA-RELEASE, 8 Nov 2026).** The round-6 car textures changed the hashes of 19
models' materials, so `remix_model_materials.py assets/models package/rtx-remix/mods/gta2hd` was re-run
alone (1.5 min): 8 630 textures, every one referenced by `mod.usda`, none missing. The release archive is
now packed by `tools/pack_release.py <out> remix` (same layout, `gta2hd/` store-only):
`remix_mod_gta2hd.zip`, 1 084 585 827 bytes. Not yet seen under Remix with the new cars.

**Not verified.** A police chase under Remix: three stars kept by `force_wanted` brought no
police within 45 s in two sessions, so the light bars were seen only on parked cars with
`force_sirens`; the booth's lit PHONE sign and glass were not framed close enough to judge
(the booth is in `remix3_i`'s frame, small); the muzzle flash itself (its light on the paving
is seen, the flash sprite not caught in a frame); the explosion and fire after the light fix;
clear-coat reflections are visible on the roofs by day but were not compared with the
REMIX-POLISH constants; Industrial and Residential were not rerun.

## Post stack and time-of-day presets (REMIX-POST, 8 Nov 2026)

**Status: configuration only, not yet seen in a frame.** Every Remix session on the L4 after
the 8 Nov afternoon host overload failed before the level: `remix_post1`, `remix_post2` with
"Unable to create a Vulkan instance: VK_ERROR_INITIALIZATION_FAILED"; `remix_post3` (fresh
stage) got the device, then "DxvkCommandList: Failed to create fence" at the front end;
other agents' `vis_base`, `vis_base2` and `vis_t3` failed the same two ways. The kernel log has
`NVRM ... Out of memory [NV_ERR_NO_MEMORY] ... system_mem.c` at the start of those runs; GL
runs on the same GPU still work. Native `vulkaninfo` in the same container still lists the L4.
A GPU reset or a reboot is probably needed (not done: the GL runs share the card). So there
is no before/after sheet yet (`out/remix_post_sheet.png` is not made). The take that makes it
is ready (below). What is known for certain comes from the runtime's own option table
(`out/remix_optdoc/RtxOptions.md`) and its log, and is in the presets now. Look values that
need a frame stay at the runtime defaults or are in opt-in overlays marked as not yet checked.

**What the option table and the log say** (this Remix Plus build, `remix-runtime/x86`):

* **Seven lines of the old showcase preset do nothing.** `rtx.atmosphere.aerialPerspective`,
  `aerialPerspectiveLocalLights`, `fogVisibilityMeters`, `fogNearFadeMeters`, `fogAnisotropy`,
  `nightSkyStars`, `realMoonEnabled` are not options of this build: the runtime echoes them
  while reading rtx.conf and then ignores them. The haze and fog the
  7 Nov notes describe never came from them. In this build, fog is `rtx.volumetrics.*`
  (froxel volumetrics: `transmittanceMeasurementDistanceMeters`, `transmittanceColor`,
  `anisotropy`, `fogSunVisibilityGain`) and the air is `rtx.atmosphere.aerosolDensity`.
* **Motion blur, chromatic aberration and vignette are on by default** (`rtx.postfx.enableMotionBlur`,
  `enableChromaticAberration`, `enableVignette`, all True). The renderer's own switch
  (`view_modes.cpp` pushes `rtx.enableMotionBlur` for `g_settings.motionBlur`) uses a name this
  build does not have, so the game's motion-blur setting has never controlled it (and with
  the default `motionBlur=0` nothing is pushed). Fixing that name belongs to the view-modes owner:
  it should be `rtx.postfx.enableMotionBlur`.
* **The quality preset is Low.** `rtx.graphicsPreset` defaults to 5 (Auto) and the runtime
  logs "NVIDIA Turing architecture detected, setting default graphics settings to Low" on the
  L4 (an Ada card). Every Remix frame so far was rendered at the Low preset.
* **No anti-aliasing.** `rtx.upscalerType = 0` (rtx_gpu.conf.extra) is "None": no DLSS (NGX fails
  under Wine) and no TAA either. The build has TAA-U (`rtx.taauPreset`), XeSS (`libxess.dll`
  ships) and FSR (`amd_fidelityfx_vk.dll`); upstream's enum is None 0, DLSS 1, NIS 2, TAA-U 3,
  XeSS 4, and TaauPreset 4 is full resolution. The enum is not printed by this build, so
  `upscalerType = 3` still has to be confirmed in a frame.
* **No depth of field.** There is no DOF option in this build, so the showcase preset has none.
* Tonemappers (`rtx.tonemap.tonemapOperator`): 0 none, 1 Hill ACES, 2 Narkowicz ACES, 3 Hable,
  4 AgX (`agx.look` 0/1 Golden/2 Punchy, `agx.saturation`), 5 Lottes, 6 PsychoV17 (default),
  7 Gran Turismo 7, 8 Neutwo. A grade after it: `rtx.tonemap.colorGradingEnabled`, `contrast`,
  `saturation`, `colorBalance`.
* Weather: `rtx.weather.precipitation.intensity` (0 by default) makes rain particles. The
  `rtx.weather.preset.<name>.*` tables (clear, hazy, foggy, rainstorm, ...) have no selector
  option in this build.
* Live: options pushed with `[devtools] remix_config` apply in a running session for exposure
  (REMIX-3's `ab2`), but the lights options did not (`docs/remix-materials.md`, REMIX-3).
  `remix_post.py` pushes every look option live and keeps the start-only ones (quality preset,
  upscaler, light options) for the start of a session.

**The presets** (`linux/docker/`). Two base sets, each self-contained (each includes what
`rtx_gpu.conf.extra` sets), plus optional time-of-day overlays appended after a base:

| option | old showcase | play (`rtx_play.conf.extra`) | showcase (`rtx_showcase.conf.extra`) | basis |
|---|---|---|---|---|
| rtx.graphicsPreset | 5 Auto (= Low on the L4) | 2 Medium | 1 High | log; frame cost not measured |
| rtx.upscalerType / taauPreset | 0 none | 3 TAA-U / 4 full res | same | upstream enum, to confirm |
| rtx.sharpening.sharpness | 0 | 0.2 | 0.2 | RCAS after TAA-U |
| rtx.dlssPreset | 1 | 0 | 0 | no NGX under Wine |
| rtx.postfx.enableMotionBlur | True (default) | False | True, exposureFraction 0.25, 8 samples, emissives unblurred | option table |
| rtx.postfx.enableChromaticAberration | True (default) | False | False | option table |
| rtx.postfx.enableVignette | True (default) 0.6 | False | True, 0.35 / radius 0.85 / softness 0.35 | option table |
| rtx.autoExposure.darkAdaptTau / lightAdaptTau | 2.0 / 0.5 s | 2.5 / 0.8 s | same | against pumping |
| rtx.autoExposure.maxExposure | 2.5 | 2.5 | 2.5 | REMIX-POLISH |
| rtx.bloom.steps / luminanceThreshold / burnIntensity | 5 / 0.8 / 0.5 | 6 / 0.9 / 0.55 | same | wider halo on neon and lamps only |
| rtx.tonemap.* | default | default (AgX Punchy listed as the candidate) | same | needs a frame |
| rtx.atmosphere.nightSkyBrightness | 0.008 | 0.008 | 0.008 | unchanged |
| the 7 dead atmosphere lines | set | removed | removed | option table |

Time-of-day overlays (`rtx_tod_<name>.conf.extra`; each sets the same keys, so one can replace
another live; not yet seen in a frame). Hours are the game clock at latitude 40, equinox
(`[timeofday]`): sun about 50 deg at 12:30, 7 deg at 17:24, -4 deg at 18:21 (lamps on from 18:00).

| key | noon 12:30 | golden 17:24 | dusk 18:21 | night 22:30 | wet (night) |
|---|---|---|---|---|---|
| rtx.atmosphere.aerosolDensity (default 1.1) | 0.7 | 1.3 | 1.4 | 1.2 | 1.6 |
| rtx.atmosphere.sunsetSaturation (1) | 1.0 | 1.35 | 1.4 | 1.0 | 1.0 |
| rtx.atmosphere.sunShadowSoftnessDeg (0) | 0.4 | 0.6 | 0.6 | 0.4 | 0.4 |
| rtx.atmosphere.nightSkyBrightness (0.002) | 0.008 | 0.008 | 0.012 | 0.008 | 0.008 |
| rtx.volumetrics.transmittanceMeasurementDistanceMeters (500) | 2000 | 600 | 250 | 180 | 140 |
| rtx.volumetrics.transmittanceColor (0.995) | 0.995 | 0.97, 0.96, 0.95 | 0.93, 0.94, 0.97 | 0.92, 0.93, 0.96 | 0.91, 0.92, 0.95 |
| rtx.volumetrics.anisotropy (0.05) | 0.3 | 0.6 | 0.5 | 0.55 | 0.55 |
| rtx.volumetrics.fogSunVisibilityGain (1) | 1 | 4 | 2 | 1 | 1 |
| rtx.opaqueMaterial.roughnessScale / Bias (1 / 0) | 1 / 0 | 1 / 0 | 1 / 0 | 1 / 0 | 0.45 / -0.05 |
| rtx.weather.precipitation.intensity (0) | 0 | 0 | 0 | 0 | 0.5 |

The wet preset's roughness is global (walls and cars get glossier too). A road-only wet look
needs the road tiles' own roughness maps, which belong to VISUALS-REMIX (`docs/remix-materials.md`,
"Full PBR maps for the HD tiles"). `package/rtx.conf` (what players get) now turns the three
default-on post effects off and slows the exposure (2.5 / 0.8 s). It sets nothing that depends
on the card.

**Using them.** `RTX_EXTRA=/work/rtx_play.conf.extra` (or `rtx_showcase.conf.extra`) on
`gamerun/remix_l4.sh`; for a fixed hour `cat gamerun/rtx_play.conf.extra gamerun/rtx_tod_night.conf.extra
> gamerun/<name>.conf.extra` and pass that. The play page (`gamerun/play_game.sh`, not this
stream's file) appends `rtx_gpu.conf.extra` and then `gamerun/rtx_showcase.conf.extra`; it should
append `rtx_play.conf.extra` instead (no motion blur, no vignette; the clock runs, so no
time-of-day overlay). The `gamerun/` copy of `rtx_showcase.conf.extra` was left as it was,
because other streams' before/after takes use it this evening. The new showcase file is in the repo
and in `gamerun/rtx_post_showcase.conf.extra`.

**The take** (ready, run it once the L4 renders again): `linux/docker/remix_post.py` with
`keys_remix_post.sh`. The session starts with the old config. At three spots (the street at
171,123 in first person facing the traffic lights; the plaza at 198.5,188.5 and the spawn at
159.5,139.5 in the chase view) and five hours it pushes the before set and then the play + overlay set
live (`[devtools] remix_config`, in lines under 512 characters, 6 s for the exposure to
settle). It also runs tonemapper and fog variants (`explore`), the showcase motion blur
while turning (`motion`), and last TAA-U and the quality presets with frame times (`aa`, then the
play preset at every hour). The before values come from `gamerun/rtx_post_before.conf.extra`
(`package/rtx.conf` + `rtx_gpu.conf.extra` + the old showcase file, concatenated), with
the runtime defaults for keys it does not set from `remix_post_defaults.json` (taken from
RtxOptions.md):

    cat repo/package/rtx.conf gamerun/rtx_gpu.conf.extra <old rtx_showcase.conf.extra> > gamerun/rtx_post_before.conf.extra
    STAGE=<private stage> gamerun/remix_l4.sh remix_post 1150 /work/keys_remix_post.sh -e MODS_HD=1 -e LEVEL_WAIT=60 \
      -e RTX_EXTRA=/work/rtx_showcase.conf.extra -e POST_SHOW=/work/rtx_post_showcase.conf.extra \
      -e INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' -e SCENE_KEY=F11 \
      -e SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/' \
      -e EFFECTS_SED='/^\[Car lamps\]/,/^\[/{s/^Enabled=0/Enabled=1/;s/^Daylight=0/Daylight=1/}'
    python3 gamerun/remix_frames.py dump out/remix_post 1150 out/remix_post/frames '^(ab_|x_|mo_|aa_|fin_)'

The sheet is then the `ab_<spot>_<hour>_before/after` frames, one row per hour (`remix_frames.py sheet`).
Use `setsid` around `remix_l4.sh` when you start it from a shell that may end: the first launch here
lost its `flock` parent and left an orphan run-queue ticket without the GPU lock.

## Verification in game on the 8x L4 host (REMIX-VERIFY, 9 Nov 2026)

Remix first had to run on the new host at all (two launcher faults; see `docs/remix-gpu-l4.md`,
"What had to change on the 8x L4 host"). Then three sessions ran on GPU 0, image
`gta2-remix-gpu2`, private stage = `repo/stage` of 8 Nov 20:24, with the `gta2hd` layer from
`package/rtx-remix/mods/gta2hd` (12 694 textures, 3 201 materials).

**Presets (REMIX-POST): verified in frame.** Runs: `out/rv_post` (the whole take) and
`out/rv_post_ab` (`POST_PARTS=ab`, after the fix below). Sheets: `out/rv_post_ab/sheet_ab_{street,plaza,spawn}.png`
(rows = noon, golden, dusk, night, wet; left = old config, right = play + time-of-day overlay),
`out/rv_post/sheet_tm.png` (tonemappers), and `out/rv_post/sheet_aa.png` (anti-aliasing and quality).
- The first take's before/after part is invalid. `remix_post.py` reset only the keys that a
  preset file sets, and no preset sets `rtx.tonemap.*` or the froxel distance. So the explore
  part's last step (colour grading on, contrast 1.08, saturation 1.15) stayed live through
  every A/B frame: the dusk, night and wet rows were near-black, and before looked the same as
  after. Fixed (`691e5f3`); `rv_post_ab` is the valid A/B.
- Play preset vs the old showcase config: no regression at any hour or spot. In stills the two
  are close; the play preset's changes are motion ones (no motion blur, vignette or chromatic
  aberration, slower exposure) plus TAA-U. TAA-U at full resolution (`upscalerType 3`,
  `taauPreset 4`) and sharpening 0.2 render without artifacts (`sheet_aa`).
- Overlays: **wet** visibly works (lamp and headlight reflections on the street and plaza
  paving). **noon / dusk / night** are near-neutral against the old look. **golden** is too
  weak: the sky stays blue-grey, with no warm cast. It needs a stronger overlay (sunset
  saturation, a lower sun, a warmer transmittance) before it is used.
- Tonemappers at the street spot (explore part, before the leaked grade): PsychoV17 (the default)
  and AgX Punchy are both readable at noon and night. AgX Punchy is brighter and more
  saturated at night, with a yellow cast. GT7 and PsychoV17 + grade crush the night to black;
  do not use them. The default stays.
- **The 8082 Remix page now appends `rtx_play.conf.extra`** (`play_game.sh`, `PLAY_RTX_PRESET`
  overrides it; `1b48278`). No time-of-day overlay is used, because the page's clock runs.
  Not yet seen on the page itself: no Remix play container was started.

**Model and tile PBR layer (REMIX-CARPROPS-PBR / VISUALS-REMIX): seen in frame.** Run
`out/rv_pbr` (`pbr_verify_run.sh`, `PBR_TAKE=1`, showcase settings). Sheets:
`out/rv_pbr/sheet_cars_day.png`, `sheet_props_day.png`, `sheet_night.png`.
- Cars take the new materials. The cop car's paint shows clear-coat sky reflections on the roof
  and hood with chrome trim, car 036 reads as bare metal, and the taxi and fire truck keep
  their paint. As predicted above, the taxi's white chequer strip comes out as speckled
  chrome; it needs a class override.
- Paving tiles show relief (slabs, grout, cracks) with no visible seam at tile borders in
  stills. Swimming under camera motion is not judged: stills only.
- At night (22:30, showcase): facades are lamp-lit, cars and pedestrians are readable, and
  headlights are on.
- An emissive object in a doorway near 206,199 (lime green) throws strong light on the
  wall at 14:00. It is probably an over-bright `__lit` emission; not identified.
- Frame cost (frame log, third and first person, 10 986 in-level frames, while the host's
  other scripted runs loaded CPUs 0-4): whole-minus-wait p50 42.3 / p90 60.0 / p99 81.2 ms.
  Present (the path tracer's GPU time) is only p50 9.0 / p99 51 ms. The biggest stage is
  `peds` (p50 12.9 / p90 33 ms), so the frame is CPU-bound on the skinned pedestrians, not on
  the 1 674 displaced materials. The displacement-off comparison (`rtx_nodisp.conf.extra`)
  was not run. The booth, traffic-light and plaza night frames fell after the end of the
  recording.
- Not done: 512 vs 256 px normals, a measured `displace_in` scale, and the
  `mod_wet.usda` layer.

## Police light bars: coloured bulbs and sane siren lights (LIGHTBAR, 8 Nov 2026) - UNVERIFIED IN FRAME

**Status: code committed, builds cleanly (both translation units, and the full DLL on 094930e), NOT yet
seen in a Remix frame.** The two takes (`out/lightbar_a`, `out/lightbar_a2`) died before the level:
the first at "Unable to create a Vulkan device" during the host overload, the second was stopped
for the GPU reset and the move to the new host. No before/after sheet exists yet.

**What REMIX-3's white flare was (from `remix3_i`'s frames and log).** Not the siren lights: with
`force_sirens` on a parked car the synthetic siren lights never fired (they only follow the game's
lamp bits 15..18 at vehicle+0x08, which a parked car does not have: `siren 0` in the log's totals
through the whole sweep). The flare was `car_bodies.cpp DrawBeacons`' additive glow quads (core
0.07 + halo 0.18, crossed). Their red/blue lives in the vertex colour, which Remix drops
(`rtx.ignoreAllVertexColorBakedLighting = True` in `package/rtx.conf`), and the additive blend is
translated to emissive (`rtx.enableEmissiveBlendModeTranslation`), so each lit bulb was the white
glow texture as an emissive disc. That is why the 9 cm bulb change made no difference.

**Changes.**
* `car_bodies.cpp DrawBeacons` (beacon hunks only): under Remix (`RemixApiAvailable()`) each lit
  bulb is drawn with its colour baked into the texture (`BeaconGlowTexture`, one per colour, a
  lens-shaped disc) and a white vertex colour, core only (0.045, three orthogonal quads so it is not
  edge-on from the side), no flat 0.36 halo. Each bulb also queues a light
  (`SyntheticQueueBeacon(vehicle, slot, worldPos, colour, lit)`) every frame, lit or dark, so
  `force_sirens` and real sirens both light the car and the road. The plain renderer is unchanged.
  Colours by model: cop car 12 / SWAT 52 red + blue, ambulance 34 red + white, fire truck 17
  red + amber; the bulbs alternate exactly as before (the game's bits; a 2.5 Hz phase when all are
  lit or forced).
* `synthetic_lights.cpp/.h`: the queued beacons become lights in the next frame's
  `SyntheticLightsUpdate` (a frame late; `LightsBeginExtra` clears anything submitted during the
  draw); a car with queued beacons skips the sprite-based `SubmitSirens`, so lights are not doubled.
  Both paths now share `EmitBeacon`: per lamp a coloured glow sphere at the bulb and one rotating
  spot, both lifted clear of the roof by their own radius, both fading over 120 ms when the lamp
  goes dark (Flash=0 by default: follow the game's lamps, not a private 1.63 Hz timer).
* New defaults (`[Sirens]`, radiance = value x RadianceScale 20 x Reach / 3; the old bulb-area
  compensation `SirenBrightness` is gone):

| | before | now |
|---|---|---|
| beam | Intensity 43.1 x (0.15/0.029)^2 at Reach 12: ~92 000 radiance, 0.029 bulb | Intensity 10, Reach 4: ~270, 0.07 bulb, 22 deg cone, pitch 12 |
| glow | ~1 100 radiance, 0.02 bulb | Glow 3, GlowRadius 3: 60, 0.06 bulb (about a street lamp's power) |
| red / blue | 1 0.06 0.04 / 0.08 0.22 1 | 1 0.02 0.01 / 0.02 0.07 1 (off-channels low enough not to clip white), BlueBoost 1.5 |
| white / amber | - | 1 0.93 0.82 / 1 0.42 0.03 (new keys `White=`, `Amber=`) |

* `GTA2DX9_EFFECTS_LIVE=1`: the effects ini is re-read when its file changes (checked once a
  second), so one take can try several `[Sirens]` settings.
* Take: `linux/docker/keys_lightbar.sh` runs
  `lightbar_take.py` (scene car as 12, 34, 17 with `force_sirens=1`, orbited with bursts of marks so
  both colours are caught, at 22:30 then 14:00; optional live `[Sirens]` VARIANTS on the cop car).

**Acceptance test (to run on the new host).** One Remix session from a private stage of committed
HEAD (`STAGE=<stage> gamerun/remix_l4.sh lightbar_a 600 /work/keys_lightbar.sh -e MODS_HD=1
-e LEVEL_WAIT=60 -e RTX_EXTRA=/work/rtx_showcase.conf.extra
-e INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' -e SCENE_KEY=F11
-e SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=14/' -e GTA2DX9_EFFECTS_LIVE=1
-e 'VARIANTS=Glow=1.5|Intensity=5;Glow=6|Intensity=20;Glow=2|GlowBulb=0.1' -e 'VARIANT_RESET=Glow=3|Intensity=10|GlowBulb=0.06'`),
frames with `remix_frames.py dump out/lightbar_a 600 <dir> 'night_|day_|var'`. Pass when: (1) at
night the cop car's bulbs read red and blue (no white core wider than the bulb), alternating
between bursts; (2) red/blue light is visible on the roof and the road around the car, not white;
(3) by day the bulbs are still coloured and visible; (4) ambulance red/white and fire truck
red/amber likewise; (5) `gta2dx9.log`'s synthetic totals show `siren` > 0 and `with beams` >= 1
during the sweep. Then pick the variant that reads best, set it as the default in
`synthetic_lights.cpp`, and build `out/lightbar_sheet.png` against REMIX-3's `remix3_i`
night frames (before, night) and a before-day take on `stage_remix3`.

**LIGHTBAR-2 (8 Nov 2026, 8x L4 host): criterion 5 verified, criteria 1-4 blocked on Remix.**
* Remix take `lightbar2_a` (private stage of `7cc5131`, the command above) died at the front end with
  "DxvkCommandList: Failed to create fence", the same host-wide failure REMIX-VERIFY is bisecting
  (it hits every Remix run on GPU 0 at the moment). No Remix frame, so criteria 1-4 are still untested.
* Plain-renderer take `lightbar2_plain` (same stage, `gamerun/grun.sh` with `keys_lightbar_plain.sh`,
  which runs `lightbar_take.py` without Remix; `SyntheticLightsUpdate` runs either way). `force_sirens`
  lit the beacons on every cop car in view (`car bodies: beacons on model 12 ... forced`). The
  synthetic totals over 17 s went `siren 36030 -> 44362 -> 47688`, with 9, 11 and 6 cars getting
  queued beacons in the sampled frames. `cars with roof lamps lit 0` means the sprite path
  (`SubmitSirens`) added nothing, so no light was doubled. No `FAULT`. Without Remix the queued lights
  are dropped every frame (`LightsReconcile` clears `g_extra`), so nothing piles up.
* Still to do once Remix runs again: rerun the acceptance command above as it is.

**LIGHTBAR-2B (9 Nov 2026): first Remix frames of the beacons; criteria 2-4 partly seen, 1 and the variants still open.**
* Take `lightbar2b_a`: the acceptance command above, unchanged, on `STAGE=stage_lightbar2` (`7cc5131`), launched
  through `remix_l4.sh` with the `--device` fix from `68bec1e`. No fence failure: the game window
  (`GTA2` 1280x720 in `xwininfo`, `game window ... after 2 s` in `keys.log`) came up, the level loaded, and
  `lightbar_take.py` ran to `lightbar done`. The container's own `shot_*.png` and the frames cut from
  `game.mp4` are path-traced (soft sun shadows, the Remix shader-compile overlay early on).
* **Shader compilation took the whole night and variant part.** Remix compiled shaders from the front end
  until just after `variants reset` ("Compiling shaders (1 remaining)" is still up at `night_var2`), so the
  frames for the night cop car, ambulance and fire truck and the three `[Sirens]` variants are black. The first
  lit frames are the cop car at night with the defaults, just after the take switches to 14:00 (`day_car_012_0`:
  the hour takes a few frames to apply).
* What those frames show (sheet `out/lightbar2b_sheet.png`):
  (2) at night, red and blue pools on the road and pavement around the cop cars, and a red glow on the
  kerb and the hydrant. The light is coloured, not white. The bulbs are small red and blue points on the roofs.
  (3) by day the cop car's bar reads blue on the roof. (4) by day the ambulance's red bulb reads red
  (a disc somewhat larger than the bulb), and the fire truck's amber is hard to make out in daylight. Criterion 1's
  alternation and the variant choice need the night part with warm shaders.
* The container stopped after the recording, before its log-copy step, so this take has no `gta2dx9.log`.
  Criterion 5 stays verified from `lightbar2_plain`.
* Next: rerun with `-e LEVEL_WAIT=330` (and a 900 s session) so the night part starts after shader compilation,
  then pick the variant. The defaults stay as committed.

## Showcase pass: path-traced frames across districts and hours (REMIX-SHOWCASE, 9 Nov 2026)

**What this is.** Four RTX Remix sessions on the L4 (GPU 0, `gamerun/remix_l4.sh`, the **play preset**
`rtx_play.conf.extra` at start: Medium, TAA-U at full resolution, sharpening 0.2, no motion blur,
vignette or chromatic aberration). Each hour's time-of-day overlay (`rtx_tod_<hour>.conf.extra`) is pushed
live over the play preset, as REMIX-POST describes. Stage: hard-link copy of the shared `repo/stage`
(committed HEAD `5545d72` when the sessions ran). Every frame below is path traced: sampled soft shadows,
emissive neon lighting the walls, wet reflections. The 29 chosen frames (1280x720, cut from each run's
`game.mp4`) are in `out/remix_showcase/`, with the contact sheet `out/remix_showcase_sheet.png`.
Neither is in git (game art). All the frames of a run are in `out/rshow_<run>/frames/`, with per-hour sheets
in `out/rshow_<run>/sheets/`.

| run | district | start config | hours (game clock) | spots |
|---|---|---|---|---|
| `rshow_wil` | Downtown | play, `Paused=1 StartHour=12.5 ClearSky=1`, car lamps by day (`EFFECTS_SED`) | 12:30, 17:24, 18:21, 22:30, wet 22:30 | spawn 159.5,139.5; plaza 198.5,188.5; street 171,123 |
| `rshow_ste` | Residential (`SWAP_LEVEL=ste`) | as `rshow_wil` | same (cut short in the wet part, see below) | spawn; 107.5,67.5 (Rednecks); 126.5,127.5 |
| `rshow_bil` | Industrial (`SWAP_LEVEL=bil`) | as `rshow_wil` but `ClearSky=0` (clouds on) | same | spawn; 126.5,119.5; 100.5,132.5 |
| `rshow_day` | Downtown | play, `Paused=1 StartHour=14`, no other settings overrides (lightbar2b_a's sunny set-up) | 14:00, 16:48, 22:30 | as `rshow_wil` |

**What the frames show** (numbers are the files in `out/remix_showcase/`):

* **Neon and emissive signs as light sources** (01, 02, 09, 10, 11, 17, 20, 21, 27). The JESUS SAVES sign in
  Downtown and the LOVE FASHION signs in Industrial light the walls, the stairs and the paving in their own colour.
  The red booth sign at the Downtown spawn throws a red pool across the square (01). The signs stay readable and
  do not blow out, both at night and in daylight (17).
* **Wet streets** (`rtx_tod_wet`: roughness scale 0.45, rain 0.5) are the strongest set: lamp and window
  reflections in the paving and the road (06-08), red neon smeared on the wet flagstones (09, 20, 21), the
  cop car's paint reflecting the street lamps (23).
* **Night** (`rtx_tod_night`): window glow on the Downtown facades with the street receding into dark (03, 04),
  car headlamps and lamp pools (05, 26, 29), traffic-light lenses lighting the pavement (`rshow_wil` warm-up).
* **Golden hour** (`rtx_tod_golden`, 17:24, clouds on, Industrial) is the best daytime look: low warm sun on the
  brick, back-lit clouds, a long-shadowed street in first person (14-16).
* **Daylight and PBR paint** (12, 13, 17-19): sun with hard shadows across the Downtown plaza at 14:00. The cop
  car's clear-coat with its white livery, and the old saloon's chrome and white-wall tyres, under an overcast
  noon in Industrial.
* **Beacons** (24, 25): with `force_sirens=1` the cop car's bar shows separate red and blue bulbs and the
  ambulance red and white, lighting the road round the car at night. This adds to LIGHTBAR-2B: the night part now
  ran with warm shaders, so criterion 1 (coloured bulbs, no white core at night) is **seen** on the cop car and
  the ambulance in Industrial. The alternation between frames is visible in `out/rshow_bil/frames/*night_car_012_*`.
  The fire truck (`*night_car_017_*`) shows its red bulb, but the car is in shadow and the amber cannot be told
  apart in those frames.
* **Post presets.** The play preset is what every frame uses. The showcase preset (`rtx_post_showcase.conf.extra`:
  vignette 0.35, motion blur while turning) was pushed live at night in `rshow_wil` and `rshow_bil`
  (`*_show_*` frames). Its vignette is visible, but the motion blur is not visible in the 15 fps recording. It adds
  nothing a still frame shows, so no showcase-preset frame is in the chosen set.
* **Frame cost** (the runs' own `frame times` lines, GPU 0 shared with GL game runs, Medium preset):
  present 10-21 ms average, about 45 ms a frame in total with the game's sprite and UI passes, worst 60 ms.
  This was not measured on a free GPU. No `FAULT` in any run.

**Found on the way (not fixed: not this stream's files):**

* **Flat, sunless daytime in sessions started with the REMIX-3/REMIX-POST settings.** Every 12:30 and 17:24 frame
  of `rshow_wil` and `rshow_ste` is shadowless and blue-grey, at the plaza as well as in narrow streets. The
  same holds for REMIX-VERIFY's `rv_post_ab` noon frames (before and after alike). The sun probe added to the take
  (`probe_*` marks: 12:30, 14:00 and 15:30, with no live push and with each push) shows it before any live push.
  So **the time-of-day overlays are not the cause**, and neither is the quality preset (`rv_post_ab` ran at Low).
  `ClearSky=1` is not the cause either: the settings default is already a clear sky (`lightbar2b_a` and
  `rshow_day` log "clouds off" and have the sun). The one setting that the sunless runs share and the sunny ones
  (`lightbar2b_a`, `rshow_day`) lack is `EFFECTS_SED` (car lamps on by day). That is a correlation over five runs,
  not a bisected cause. In `rshow_day` too, several daytime frames are in building shadow or caught mid-way
  through a view change. Next step for the lighting owner: one session with and one without `EFFECTS_SED`,
  same spot, 14:00. With clouds on (`rshow_bil`) the overcast sky lights the street brightly either way, which is
  why Industrial's day frames are usable.
* **The day starts too late for "dusk".** At 18:21 (`rtx_tod_dusk`) the sky is already night in every district,
  so the dusk overlay reads as an early night. An earlier hour (e.g. 17:50) should give the violet dusk; not tried.
* **The first-person switch sometimes fails right after a warp** ("set_view: could not reach first from
  classic", 2-5 times a run). The frame is then the classic camera's high view (aerial city frames in
  `rshow_day/sheets/noon.png`). The take keeps going. Owner: navigation/camera (`qa_lib.set_view`).
* **`remix_keys_lib.sh to_level` only recognises Downtown's map line** (`map wil.gmp is played`). With
  `SWAP_LEVEL` it pressed Return for four minutes after the level was up (`rshow_ste`). `keys_remix_showcase2.sh`
  overrides it with a version that waits for the swapped district's map line.
* **Residential under Remix**: several wall tiles look low resolution next to Downtown and Industrial (the mural
  at the spawn, the Rednecks block). That set is the weakest of the three districts. Not investigated.
* **Do not edit a key script while a run executes it.** bash reads scripts as it goes; overwriting
  `keys_remix_showcase2.sh` in place during `rshow_ste` made the rest of that run execute garbage. Replace a
  script with `mv` (new inode), never in place.

**Not verified / not done:** the fire truck's amber beacons; a police chase (beacons only via `force_sirens` on a
parked car); 1440p capture (the runner records 1280x720 at 15 fps, CRF 20); frame cost on a free GPU; the cause
of the sunless runs (above). Residential's wet part and the showcase-preset part were cut off by the session
length (the governor paused `rshow_ste` and `rshow_day` for up to 8 minutes, and a paused run keeps its wall-clock
deadline).

**Reproducing.** `linux/docker/remix_showcase2.py` (the take), `keys_remix_showcase2.sh` (to the level, then
the take), and the launchers `remix_showcase2_launch.sh` / `remix_showcase2_launch_day.sh` (copy all four to
`gamerun/`; the launchers are `gamerun/rshow_launch.sh` / `rshow_launch_day.sh` there):

    CLEARSKY=0 gamerun/rshow_launch.sh rshow_bil 1700 bil bil "start;b24:126.5,119.5,2;b09:100.5,132.5,2"
    gamerun/rshow_launch_day.sh rshow_day 1500 "" wilday "start;plaza:198.5,188.5,2;street:171,123,2" \
      -e SHOW_CAR_XY=164.5,149.5 -e SHOW_HOURS=noon=14.0,golden=16.8 -e SHOW_TODS=noon,golden,night
    python3 gamerun/remix_frames.py dump out/<run> <game.mp4 duration> out/<run>/frames '^(s_|probe_)'

The take: a 240 s warm-up that cycles views and hours (shader compilation ends about 150 s into it; the
`warm_*` frames show it), the sun probe, then for each hour and spot first person and the chase view, then the
scene car as cop car / ambulance / fire truck with `force_sirens` at night and by day, then the showcase
preset at night. Env: `SHOW_SPOTS`, `SHOW_TODS`, `SHOW_HOURS`, `SHOW_CARS`, `SHOW_CAR_XY`, `SHOW_WARM`,
`SHOW_PROBE`. The take ends well before the session does. Once the `end remix showcase2` mark appears, stop the
recorder inside the container (`pkill -INT -f x11grab`) and copy `gta2dx9.log` out; that frees the GPU early.

## Advanced preset: ReSTIR GI, longer paths, sharper sampling (REMIX-ADVANCED, 9 Nov 2026)

**The finding.** The runtime's default indirect integrator (`rtx.integrateIndirectMode = 2`, the Neural
Radiance Cache) does not start under Wine: `remix-dxvk.log` has `[RTX Neural Radiance Cache] Could not
initialize SDK API ... Switching to importance sampled indirect illumination mode`, then `Integrate Indirect
Mode: Importance Sampled - activated` about 9 s after `Neural Radiance Cache - activated` (seen in
`rshow_wil` and again in `radv_before`). Importance sampled is the runtime's *reference* mode, "not
recommended for general use as it provides the noisiest output" (RtxOptions.md). So **every Remix frame
before this pass had the noisiest GI the runtime has**, and the denoiser smeared it: the play and showcase
presets never set the integrator. `rtx.graphicsPreset` 2 (Medium) does not change that.

**The preset** (`linux/docker/rtx_advanced.conf.extra`, self-contained like `rtx_play.conf.extra`; copy to
`gamerun/` and start with `RTX_EXTRA=/work/rtx_advanced.conf.extra`):

| option | play | advanced | why |
|---|---|---|---|
| rtx.graphicsPreset | 2 Medium | 4 Custom | the values below are not overwritten by a preset table |
| rtx.integrateIndirectMode | (2 NRC -> falls back to 0) | **1 ReSTIR GI** | reservoir reuse of indirect paths, temporal + spatial |
| rtx.pathMaxBounces / pathMinBounces | 4 / 1 (defaults) | 6 / 1 | longer bounce light in streets and under arcades |
| rtx.russianRoulette1stBounceMinContinueProbability | 0.6 | 0.8 | the first bounce is rarely cut |
| rtx.di.initialSampleCount / spatialSamples / disocclusionSamples | 4 / 2 / 4 | 8 / 4 / 6 | ~2 000 map lamps + neon + car lamps: the right light wins per pixel |
| rtx.denoiseDirectAndIndirectLightingSeparately | (default True) | True (explicit) | high-quality NRD path |
| rtx.enableUnorderedEmissiveParticlesInIndirectRays | False | True | fire and flashes light the street in bounces |
| rtx.displacement.enableIndirectLighting / enableReSTIRGI | default | True (explicit) | parallax relief kept in bounce light |
| rtx.volumetrics.froxelGridResolutionScale / initialRISSampleCount | 8 / 32 | 4 / 48 | twice the froxel resolution: lamp cones, sun shafts, neon halos |
| rtx.atmosphere.sunShadowSoftnessDeg | 0 | 0 (physical disc; the time-of-day overlays set their own) | |
| rtx.nativeMipBias | 0 | -0.5 | slightly sharper textures under TAA-U at full resolution |
| post (exposure, bloom, no blur/CA/vignette, materials, lights) | | as play | |

**Before/after at matched spots** (two sessions on GPU 0, the same take `linux/docker/remix_adv.py` with
`keys_remix_adv.sh`, launcher `remix_adv_launch.sh`; Downtown, start 12:30 paused, the five time-of-day
overlays pushed live, spawn / plaza 198.5,188.5 / street 171,123, first person and chase view; frames by mark
name from `game.mp4`; stage `stage_remixadv` = hard-link copy of `repo/stage` (DLL of 8 Nov 18:53), so both
sessions ran the same DLL and only the start preset differs). Sessions `out/radv_before` (play preset) and
`out/radv_after` (advanced); paired sheets `out/radv_ab/ab_<hour>.png` and the 1:1 crop
`out/radv_ab/crop_wet_plaza.png` (local, not in git: game art).

* **Seen better with the advanced preset:** the wet plaza (chase view, nearly the same camera): the paving keeps
  its parallax relief and separate lamp glints on each wet flagstone, the van's tail lamps reflect as defined
  red streaks and its tyres read; with the play preset the same surface is a smeared, blurred sheen (the
  denoiser averaging importance-sampled noise). At night the street lamp pool on the road (street spot) and the
  facade facing the plaza read with soft bounce light. Red neon at the spawn spills less flatly over the stairs.
* **Not matched well:** the warp leaves the player's heading as the previous spot left it, so several pairs
  (noon plaza first person, noon start) look in different directions; only the wet/night plaza chase views and
  the night start first-person view are near-identical cameras. A heading-locked warp would fix the take.
* **Not judged:** noon. The after session's first noon block came out sunless (below: a separate bug, not the
  preset); its later noon frames at the plaza (`gi_after_noon_*`) have full sun and hard shadows.
* The live switch of `rtx.integrateIndirectMode` (pushed through `[devtools] remix_config`) is accepted
  ("(set)") but the runtime logs no new "Integrate Indirect Mode" line, and the camera drifted between the
  captures, so the in-session A/B (`gi_*` frames) proves nothing: set the integrator at start.

**Frame cost** (`GTA2DX9_FRAME_LOG`, 20 s still + 10 s turning in the chase view at the plaza, cost = frame
minus the 30 fps cap's wait; `linux/docker/remix_adv_frametimes.py out/radv_before out/radv_after`). GPU 0 was
shared with other agents' GL game containers and, in parts, another Remix session, so the numbers carry a few
ms of noise either way:

| window | play p50 / p90 / p99 ms | advanced p50 / p90 / p99 ms |
|---|---|---|
| noon, still | 46.8 / 73.6 / 109.0 | 49.2 / 70.7 / 91.1 |
| noon, turning | 48.0 / 74.1 / 106.6 | 45.2 / 61.4 / 78.9 |
| night, still | 47.0 / 72.8 / 110.2 | 58.5 / 76.8 / 92.3 |
| night, turning | 45.2 / 63.8 / 85.7 | 61.6 / 77.5 / 87.4 |

By day the cost is the same within the noise; at night (many lights, ReSTIR GI reusing them) the median is
about 12-16 ms higher (~17 fps against ~21), the tail no worse. Both are GPU bound: the CPU waits in Present by
day and in the pedestrian draw at night (the first stall point after the frame is queued), not in our code
(game 1.1 ms, world 0.4 ms). On the L4 neither preset holds 30 fps at 1280x720; the advanced preset is the
better picture at the same frame rate by day and ~20 % slower at night. Recommendation: advanced for
showcase captures and stills now; for play, keep the play preset until a free-GPU measurement, but add
`rtx.integrateIndirectMode = 1` to it (the GI fix alone is the largest part of the quality gain; its cost was
not measured separately).

**Sunless daytime: still open, two causes ruled out.** REMIX-SHOWCASE's flat, shadowless noon frames
appear in these sessions too, intermittently, with the same DLL and either preset: the after session's
whole first noon block (09:34-09:35) is lit by the sky alone, the same spot 5 minutes later
(`gi_after_noon_*`) has full sun; the before session's warm-up noon frames `warm_5/10_noon` are flat, its
take frames sunny. Two hypotheses were tested and **refuted**:

1. *The sun push made at the front end is lost at the level load* (with `Paused=1` the angle never moves
   again). The time-of-day push happens before the level in every run (`time of day: driving ...` before
   `remix lights: district`), sunny ones included, and `radv_after` shows full sun after 180 s at 12:30
   with no clock change.
2. *A clock jump from night straight to day drops the sun.* The jump test (`ADV_JUMP=1`: 22:30 -> 13:00
   three times at the plaza, frames 4 s and 10 s later) with the stock DLL (`out/radv_jump_old`) has sun
   within 4 s after both real jumps; a DLL that re-pushes the angle every 2 s with a 0.01 deg dither
   (`out/radv_jump_fix`) is no better (sunless start and first jump, sun from the second). The change was
   not committed.

What the flat frames share: they come in the first minutes of a session (shader permutations or the
light tables may still be building, the runtime's "Compiling shaders" box is not always on screen) or right
after a long live push of overlay options. Next step: log `rtx.atmosphere.sunElevation` as the runtime
reports it (devtools read-back) next to the frame, and run a 10-minute still at 13:00 to see whether the
sun appears by itself. Side finding: the take's `set_hour_tenths` writes 1.2 s apart are sometimes merged
by the devtools ini reader (the 13.2 "nudge" and one 22.5 never reached the clock: `devtools: clock set to`
lines), so a take must wait about 2 s between clock writes.

**Not done / still open:** a free-GPU frame-cost measurement; the play preset with only
`integrateIndirectMode = 1` (cost of the GI fix alone); a heading-locked warp for exact camera matches;
the taxi chequer-as-chrome material (`tools/remix_model_pbr.py` `car_trim_maps`: the chequer bands are
bright, neutral, busy and fill < 60 % of their window, so they pass the chrome test; a structure-tensor
isotropy test caught only part of them offline, not shipped); 1440p capture.

## The sunless daytime: the clouds' shadow outlived the clouds (FIX-REMIX-2, 9 Nov 2026)

Defect `pt-remix-daytime-no-sun-no-shadows` (and the "sunless daytime" of REMIX-SHOWCASE and
REMIX-ADVANCED above). **Cause:** the time-of-day code switches Remix's clouds off
(`rtx.atmosphere.cloudEnabled = False`, `[timeofday] ClearSky`), but the clouds' shadow on the
ground is a separate term, the voxel grid of the cloud deck that the sun's light samples
(`rtx.atmosphere.cloudVoxelShadowsEnable`, strength `rtx.atmosphere.cloudShadowStrength`). It
kept the runtime's default deck (coverage 0.29, drifting with the wind) and shaded the sun with
it. Whether a frame had sun depended on where the sun stood and how far the invisible deck had
drifted: 08:00 and 13:00 starts had sun, 12:00 set in-session did not, and the same plaza went
from flat to sunny within minutes. **Fix:** with a clear sky the DLL also pushes
`rtx.atmosphere.cloudShadowStrength = 0` (and 1 when clouds are wanted), every few seconds with
the clouds switch (`UpdateSky`, `time_of_day.cpp`); `package/rtx.conf` sets 0 from the start.

Evidence (Downtown, `gamerun/playtest_remix.sh`, start 05:30, clock paused):
- `out/fr2_probe2`: 12:00 set in-session flat; 08:00 sunny; 12:30 flat; a live
  `skyLutCacheKeySplitEnable=False` and a later jump showed the sun once, but
  `out/fr2_split1` (that option from the start, the filer's command) is sunless at noon: refuted.
- `out/fr2_cloud1` (stock DLL, 120.5,152.5): noon flat (`fr/011`), then one live push of
  `cloudShadowStrength=0`: full sun, lit facades against shaded ones, hard shadows (`fr/013`);
  the later pushes (`cloudVoxelShadowsEnable=False`, `cloudCoverageMean=0`) and a jump to 12:30
  keep it.
- `out/fr2_fix1_wil` (the fix, the filer's command): every 12:00 frame at the three points,
  third and first person, is sunlit with shadows from the tree, the lamp posts, the van, the
  gantry and the buildings on a light-grey road.
- Night: `out/fr2_night1` (stock DLL, 23:30) gives the same picture with the shadow term at 1 and
  at 0 (mean luminance 0.162/0.161 at the plaza, 0.242/0.242 at the junction), and the fixed run's
  23:30 frames sit at the same levels. The night is unchanged by this.

## Day and night looks: exposure cap and sky fill by the clock (FIX-REMIX-2, 9 Nov 2026)

Defect `pt-remix-day-shade-black-no-sky-bounce`: by day, streets in building shade were near
black (0.04-0.07 mean luminance in Industrial at 10:00), because the play preset's exposure cap
(`rtx.autoExposure.maxExposure = 2.5`, set for the night) also held by day and the sky's diffuse
fill is weak next to the sun. The DLL now pushes a day and a night look when the sun crosses the
horizon (0 deg, 0.5 deg hysteresis; `UpdateDayLook`, `time_of_day.cpp`; log line `time of day:
day look (sun 50.0 deg): exposure cap 6.00, sky fill 3.00`):

| sun | `rtx.autoExposure.maxExposure` | `rtx.atmosphere.skyIndirectRadianceScale` | ini (`[timeofday]`, tenths) |
|---|---|---|---|
| above the horizon (day) | 6.0 | 3.0 | `remix_day_max_exposure_tenths=60`, `remix_day_sky_fill_tenths=30` |
| below (dusk, night) | 2.5 (the REMIX-3 night) | 1.0 (runtime default) | `remix_night_max_exposure_tenths=25`, `remix_night_sky_fill_tenths=10` |

0 leaves an option to rtx.conf. Both options apply live (`out/fr2_shade1`, Industrial 168.5,119.5
at 10:00, frame mean luminance: 0.053 as shipped, 0.083 with sky fill 3, 0.090 with cap 8, 0.137
with fill 3 and cap 6). The time-of-day overlays (`rtx_tod_*.conf.extra`) stay as they were.

## Covered pockets at night: the player's fill light (FIX-REMIX-2, 9 Nov 2026)

Defect `pt-remix-enclosed-spot-pitch-black-no-ambient`: the Zaibatsu phone terrace (bil 64,189.5, a
mission phone) is a covered pocket that no lamp, sky or moon reaches, and GTA2's constant ambient (every
surface lit) has no path-traced equivalent, so at 22:30 the 3D views were black but for the HUD. A
live probe (`out/fr2_pocket1`) ruled out the global knobs: exposure cap 5, surface moonlight x4, night
sky x5 and sky fill 4 each moved the pocket's lower half from 0.037 to at most 0.046, while an open
street responded normally. The strongest-lights log shows 159 lamps within reach and none getting in;
the phone there is not a booth model (no `code_phone` drawn), so a booth light would not help.
**Fix:** under Remix, from the lamps' on hour to their off hour, a dim warm sphere 0.6 tiles above the
player (`PlayerFillSubmit`, `live_geometry.cpp`; light source "player fill"), at
`[timeofday] remix_player_fill_percent=25` of a map lamp (0 = off).

Runs (the filer's command, `bil "17.5,22.5"`, four points): `out/fr2_pk_base1` (the sun and day-look
fixes, no fill) against `out/fr2_pk_fix3` (fill 25 %). The pocket at 22:30, lower-half mean luminance
0.043 -> 0.079 (minimum 0.039 -> 0.069): walls, paving and the bench readable in third and first person.
The other points stay night streets (22:30 lower-half means 0.119/0.102/0.337 -> 0.110/0.147/0.271,
within the camera-heading noise of these runs). Frames are matched to the marks by the runner's
`shot_*.png` timestamps: in `fr2_pk_fix3` the encoder dropped frames and `game.mp4` time drifted from
the wall clock, so `remix_frames.py dump` picked the wrong frames there.

## The player fill off the hero's head: hair at dusk and night (FIX-REMIX-IDENTITY, 9 Nov 2026)

Defect `pt-remix-hero-hair-turns-to-bald-scalp-at-dusk-and-night`: in third person under Remix the hero's short
dark hair read as a bare, skin-toned scalp at 19:30 and 23:00 and as hair at 13:00. **Cause:** not the hair's
material (the head texture `human_male_adult_11_m001_head.tga`, layer prim `mat_EE56F5A8CF593B96`: hair albedo
22,13,7, roughness 0.84, the same at every hour) but the night fill above (7081d2b): 0.6 tiles above the feet is
0.14 above the hero's crown (he is 0.46 tall), so from the lamps' hour on the crown took ~18x the ground's
irradiance and the dark hair's specular sheen came out as a bright skin-coloured cap. **Fix**
(`PlayerFillSubmit`): in the street views the sphere slides from that spot toward the eye by up to 0.9 tiles (the
chase camera's boom is collision-solved, so that segment is open space in the pocket). First person (the eye
within 0.5 tiles of the old spot; the crown is not in view) and the classic view keep the old spot: with the
sphere at the eye the first-person hands were twice as bright at night (`rid_hairC`, lower-band p99 luma 80 -> 159). `GTA2DX9_FILL_TOWARD_EYE=<tiles>` (0 = the old spot) for A/B; the log
says `remix: player fill: 0.90 tiles toward the eye ...`.

Runs (GPU 4, Ultra preset `rtx_premix_max.conf.extra`, wil 110.5,120.5 heading 0, hours 13/19.5/23, same DLL):
`out/rid_hairA` (`GTA2DX9_FILL_TOWARD_EYE=0`) against `out/rid_hairC` (default). Crown / skin luminance on
the same head (hand-placed patches on the `third_0` frames; bald reads >= 1):

| | 13:00 | 19:30 | 23:00 |
|---|---|---|---|
| old spot (`rid_hairA`) | 0.26 | 1.15 | 2.45 |
| toward the eye (`rid_hairC`) | 0.28 | 0.59 | 0.52 |

The covered pocket the fill was made for (bil 64,189.5 at 22:30, the same DLL, `out/rid_pk_t0` with
`GTA2DX9_FILL_TOWARD_EYE=0` against `out/rid_pk_t09`): third-person lower-half mean luminance over four headings
0.070 -> 0.076 (min 0.065 -> 0.068); first person keeps the old spot (0.075). The classic view at the bil spawn at
22:30 with the fill lit (the runs' `level_classic` frames, before any warp): mean |difference| 0.71 / 255, p99 6,
mean luma 6.51 against 6.53, path-tracing noise. Plain renderer: vreg `spawn_classic` 0 px (`out/rid_vreg1`;
its four street FAILs are the same on `qr3_afb3cb6_1`, the base without this change).
**Still short:** at night the hair now reads as hair, a dark cap darker than the face (crown / skin 0.5-0.6 against
0.28 at noon): the crown still takes more of the night light than the face does. The hero is also lit by the
world only now, so in the darker spots he is a dark silhouette (by design, as the street around him).

## Industrial at night: wide coloured map lights as warm white (FIX-REMIX-2, 9 Nov 2026)

Defect `pt-remix-industrial-night-mono-colour-and-black`: Industrial (ste) lights its yards and plazas
with saturated map lights of 3-8 tiles' reach (`ste.gmp` LGHT: `#008000` r=8 at ground level round the
22.5,214.5 plaza, `#0080FF` r=4 and `#80FFFF` r=2-4 at the 43.5,100.5 lamp). The classic renderer only
tints sprites near them; a path tracer floods the whole plaza in one hue (night-vision green, cyan).
**Fix** (`Describe`, `remix_lights.cpp`): a neon-class map light (saturated, not red-led sodium) with a
reach of `wideNeonRadius` (3 tiles) or more is lit warm white (1.0, 0.80, 0.58) at its own luminance;
smaller neon keeps its colour, locally; a user override's colour still wins.

Runs (the filer's command, `ste "10,18.5,22"`, three points): `out/fr2_fix2_ste` (sun and day-look fixes)
against `out/fr2_ind_fix1` (also the player fill of 7081d2b and this change), frames matched by
`shot_*.png` timestamps. The plaza at 18:30 is warm-lit paving, kerbs, manhole and hydrant in their own
colours (was one green); the 43.5,100.5 lamp is a warm lamp on readable brick (dominant lit hue 180 ->
30 deg, Downtown's lamps are 30); the alley at 168.5,119.5 rose from 0.007 to 0.054 mean luminance
(darkest frame 0.033: shapes against the sky readable, not quite the 0.04 floor). Day frames unchanged
in hue.

## One classic light state per game time: the round trip, the twilight, the paused clock (FIX-REMIX-3, 9 Nov 2026)

Defects `pt-remix-classic-lit-state-flips-after-3d-roundtrip` and `remix-sun-moves-with-clock-paused`.

**The round trip.** The classic view came back from the 3D views brighter at the same spot and the same game time
(`out/fr3_lab1`, Wil spawn at 04:00, no walking: mean luma 15.4 before the first V, 31.8 after). Toggling Remix's
conversion of the game's D3D9 lights live (`rtx.ignoreGameDirectionalLights` / `PointLights` / `SpotLights` through
`[devtools] remix_config`) changed nothing, so it was not a fixed-function light left on. The log showed the light
set: 28 lights before the first V, 60-62 in classic after it. `FitLampsToPosts` (`remix_lights.cpp`) fits each game
lamp to its drawn post and adds a pool light under it (gain 4). It runs once the first street frame has placed the
posts, and the posts stay placed, so from the first V on the classic view had every lamp plus its pool. It now runs
only while the picture presents the street views (`StreetPresentation()`): the classic view keeps the game's own lamps
at every visit, as before the first V. Same spot, before and after the round trip:

| run | game time | classic before / after the V round trip (mean luma) | shadow-mask pixels differing |
|---|---|---|---|
| `out/fr3_lab1` (before the fix) | 04:00 running | 15.4 / 31.8 | - |
| `out/fr3_night1` | 02:00 paused | 27.3 / 26.3 (0.96) | 2.9 % (walking peds) |
| `out/fr3_noon3` | 12:00 paused | 125.5 / 127.7 (1.02) | 2.6 % |
| `out/fr3_rx4` (the filers' take, then a second trip where the walk ended) | 05:15 running | 69.9 / 69.9 (1.00) | 0.3 % |

The classic light set is back to 28 lights after the trip (`out/fr3_night1` log); the street views keep their 45
pools. The filers' own pair (`view_0_classic` / `view_3_classic_again` of `keys_remix_gpu.sh`) cannot be equal: the
walk in the 3D views ends in another place (the open plaza by JESUS SAVES), and with the shipped clock (02:00, a game
minute per real second) the sun has risen from -14.6 to -8.5 deg between the two frames. Remix's atmosphere already
casts long sun shadows at about -8 deg, before the clock's 06:00 sunrise (`out/fr3_rx4`, log `time of day: sun pushed`).

The first-person view model also left D3D9 light 0 enabled after drawing the hands (`live_geometry.cpp`); it is now
switched off again. With the player unarmed that path did not run in these takes.

**The twilight.** The day and night looks (exposure cap 2.5 -> 6.0, sky fill 1.0 -> 3.0, previous section) switched
in one frame when the sun crossed 0 deg: with the shipped clock that is a 2.4x jump in the whole picture a few minutes
into every level. They now ramp (smoothstep) over 6 deg either side of `dayLookAboveDeg`, pushed in 2 % steps, logged
as `time of day: night|twilight|day look (sun E deg, day T): exposure cap X, sky fill Y` at the ends and every quarter
of the ramp. Untested in a frame across the ramp (the takes above start at night or at a held noon).

**Pushes, logged.** Every sun push is logged (`time of day: sun pushed: elevation E, rotation R (clock HH.HH,
paused|running)`, at most one per 2 deg or 30 s). The whole preset (sun, look, clouds) is pushed again at the ini load
and when a level's world has loaded (`time of day: level loaded: the preset is pushed again`), whatever the view.

**The paused clock** (`remix-sun-moves-with-clock-paused`). With `[timeofday] Paused=1` the sun stays put: in
`out/fr3_noon3` (12:00) and `out/fr3_night1` (02:00) the log has one sun push, no other, and the same classic frame 60 s
apart differs on 0.5 % / 1.2 % of shadow-mask pixels (moving peds and cars), mean luma 125.5 / 125.6 and 27.3 / 25.9.
The filer's `r3dq_4` take (a roof at 10:00, with a `[devtools] set_hour_tenths` set, then 14:00) was not re-run; its
log had no pushes logged, so it cannot tell whether its clock moved. Run it again with this build's log to settle it.

## Street-lamp pools under the posts (FIX-REMIX, 9 Nov 2026)

Defect `pt-remix-lamp-posts-cast-no-light`: at night every lamp-post lantern glowed and nothing
under it was lit. The map puts the lamp at the bulb, and the post DrawProps stands under it
(`LampPostScale`, `model_store.cpp`) has its lantern there: glass, dish under it, roof over it,
all drawn opaque through D3D9, so to Remix the 0.15-tile lamp sphere sat boxed in (the glass is
0.08 tiles across on a 1.8-tile post).

`FitLampsToPosts` (`remix_lights.cpp`), for every map lamp with a post under it (game-listed and
far lamps alike): the lamp's own sphere shrinks to fit inside the glass, its power kept (radiance
times the area ratio), so the lantern still glows; and a second sphere, 0.05 tiles or less,
hangs just under the dish (`LampPostHead` measures the lantern from the model) with 4x a default
lamp's power (`kLampPoolGain`), gated by the clock like the lamp. It lights the post from above,
the pavement and the road. Where DrawProps has moved the post off the lamp to the kerb or a wall
(`MapLampPosts`, FIX-PROPS), the lamp itself is put out and the glow and the pool go to the moved
lantern. Log: `lamp post: lantern glass ...` once, and `N lamp pools under
posts` on the far-lamps line.

Runs (`gamerun/playtest_remix.sh`, Downtown, 21:30, junction 120.5,152.5 and plaza 164.5,149.5):
`out/fxr_lamp_before` (HEAD 43eebf0: lit lanterns, dark paving), `out/fxr_lamp_after` (pool at 1x:
post lit, paving barely), `out/fxr_lamp_after2` (4x: pools on the median, kerb and road around the
posts; `cmp/cmp_0.png`). Not done: the orange facade lights (map lamps half a tile from a wall,
no post) still wash the corner facades with no fixture drawn; the script's camera headings differ
between runs, so the before/after pairs are the same mark, not the same framing.

### The pools shine down: the night facades (FIX-REMIX-NIGHT, 9 Nov 2026)

pt-remix-night-facades-glow-brighter-than-lamp-lit-street: at 19:30-22:30 every facade was an even warm tan, brighter than the street the
lamps stood in. Live A/B in one session (`[devtools] remix_lights_probe=<mask>`: bit i puts the game's light class i out, 5 the far lamps,
6 the lamp pools, 7 the lanterns on posts; out/rn_night2, rn_night4): taking out the sky fill, the moon/sun distant light, the airglow, the
neon and white classes, the far lamps or the lanterns changed little; taking out the street class or just the **pools** left the street
dark. The pool was a bare sphere at 4x a lamp's power; with posts every few tiles and many stood against a wall it lit the facades up to the
eaves as hard as the road, and auto-exposure turned the sum into one even wash.

The pool is now a spot pointing straight down (`[lights] PoolConeDegrees`, gta2dx9_settings.ini, default 70 = half-angle, softness 0.5;
0 = the old sphere; F4 menu "Lamp pool cone"; `[devtools] remix_pool_cone=N` live), like a street luminaire's cut-off optic: it lights
the pavement and the foot of the wall around its post, not the facade above. Measured at hour 22.5, wil spawn, first person facing the
facades (out/rn_night5 t_fp3_*, mean luma 0-255): old sphere facades 88 / 82, pavement under the lamp 86, open road 55; cone 70 facades
32 / 33, pavement under the lamp 84, open road 28; cone 55 darker everywhere (the pool shrinks). Street-class lamps with no post (33 near
the spawn) were tried at 20 % of their power: no measurable change, so they were left as they are. Day: the street class is gated off by the
sun, so noon frames do not change. Classic: the pools only exist while the street views are presented (FitLampsToPosts), so the classic
Remix light set is the game's own, as before.

Still short of a shipping night: the facades are now evenly dim rather than evenly bright (a far wall is lit by the bounce of many pools,
not by a lamp of its own), the street has no lit windows or shopfronts to give the walls life, and the pool edge on the road is soft but
wide; a real street at night has distinct pools with dark gaps between posts, which needs fewer, better-placed lamps than the map gives.

## Water under Remix: one smooth water material for the basin, the apron and the seal (FIX-REMIX, 9 Nov 2026)

Defect `pt-remix-water-matte-no-reflection`: the harbour was a flat matte teal and the open sea a flat
navy plane with a hard seam between them. The gta2hd layer classified the HD water tiles (608-619, the
game's animated water; 11 HD files per district, 34 distinct top-mip hashes) like any city surface:
roughness 0.8 with a roughness map from their busy wave highlights. The navy "sea" was the renderer's
black seal quad under the world (`SealTileIndex`, 64 px of 0xFF000000, Remix hash `A00D8B41035A6C7F`),
reaching 512 blocks past the map.

`tools/remix_water.py <mod> --hd assets/textures_hd/{wil,ste,bil}` marks those hashes `"water": true` in
`pbr.json`, writes one tileable ripple normal map (`textures/water_ripple.n.rtex.dds`, 512 px BC5
octahedral, seeded, procedural: no game art) and rewrites the water prims in `mod.usda` and
`mod_wet.usda` in place (they also hold the car and sign prims, which a regeneration would drop):
the tile's own albedo, the ripple normal, roughness 0.08, metallic 0. The seal gets the same material
with the water tiles' mean colour as a constant. `remix_materials.py write_usda` emits the same water
prim for hashes marked `water`, so a regenerated layer keeps them. The ripple file lives beside the
other mod textures (not in git, packed by `tools/pack_release.py remix`); rerun the tool to recreate it.
Since FIX-WORLD's apron (d2bbf01) the street views continue each map edge as the border's water tile,
which takes the water material by hash.

Runs (`gamerun/playtest_remix.sh <name> 560 wil "18.2,13" "203.5,237.5,4"`, the roof west of the basin;
the after runs add `-v <mod>:/fxmod:ro -e MODS_HD_SRC=/fxmod/gta2hd`): `out/fxr_water_before` (matte basin,
navy plane, seam), `out/fxr_water_after` (sky and quay reflected, Fresnel brightening to the horizon at
18:12 and 13:00, basin and sea one surface; side by side in `cmp/`), `out/fxr_water_after2` (the same on
top of the apron). Left: a thin dotted line where the map's water meets what lies past the edge.

## Full PBR maps for the HD tiles (VISUALS-REMIX, 8 Nov 2026)

Why the Remix picture read as dated next to the upstream GTA2 RTX Remix videos: every
tile had its albedo, a 256 px normal from a band-passed Sobel of that albedo (one noisy
relief, mortar and grain alike) and a roughness from local contrast alone; no metallic,
no height, no emission beyond the curated signs. This pass gives every HD tile of the
three districts the full map set, from `tools/remix_pbr.py` (new; numpy only):

| map | file | size / format | what it is |
|---|---|---|---|
| albedo | `<hash>.a.rtex.dds` | the game's own 512 px DXT1/DXT5, copied | unchanged (the hash is its top mip) |
| normal | `.n.rtex.dds` | 512 px BC5 octahedral, 10 mips (was 256 px) | slope of a two-band height: *structure* (difference of Gaussians at ~1/40 of the tile, normalised by local contrast, through tanh: brick faces become plateaus, mortar and panel seams grooves) x a strong weight plus *grain* (the fine texture inside a face) x a weak one. Saturated paint (signs, road markings) gets a quarter of the structure relief. |
| roughness | `.r.rtex.dds` | 256 px BC4 | a class per texel (asphalt 0.86, stone/concrete 0.78, brick 0.84, wood 0.70, vegetation 0.92, painted/sign 0.42, smooth plaster 0.55, metal 0.38, bright metal edges 0.20, near-black 0.60), plus local grain (busier = rougher) and grime (darker than its surroundings = rougher) |
| metallic | `.m.rtex.dds` | 256 px BC4, only where there is metal | neutral texels in strongly oriented, finely periodic patches (corrugated sheet, gratings, girders, pipes, rails; a patch, not a lone edge, and at least 4 % of the tile) 0.45, their bright thin highlights 0.75 |
| height | `.h.rtex.dds` + `displace_in` | 256 px BC4 with a **max** mip chain (what the runtime's quadtree POM reads) | the structure band (1 = surface, 0 = deepest) on relief tiles: no sign paint, at least 60 % surface, enough structure; `displace_in` 0.006 + 0.012 x the tile's structure amplitude (pbr.json) |
| wet roughness | `.w.rtex.dds` | 256 px BC4, ground-like tiles only | half the roughness, puddles (0.025) in the low areas of a tile-seeded noise field and in the joints: referenced only by the rain variant `mod_wet.usda` |
| emission | `.e.rtex.dds` | unchanged | the curated neon and lit signs (`remix_emissive.py`) |

**Night windows are not generated.** `analyse(windows=True)` finds dark, smooth, framed
rectangles and lights about half of them; on a random sample of 180 tiles every tile it
lit was a false positive (blue-grey wall panels, roof plates, a cornice shadow), and a
glowing wall at night is worse than a dark window, so it is off and documented as such.
Lit windows would need a curated list like the signs'.

Wiring: `remix_materials.py --dds-tiles ... --pbr full` (the default; `--pbr basic` is the
older two maps) runs the tiles in a process pool (`--jobs`), writes `pbr.json` (per hash:
displace_in, wet, class shares) beside `mod.usda`; `write_usda` adds `metallic_texture`,
`height_texture` + `displace_in` and the emission to a prim when the file exists, so the
sign pass keeps them; `--wet-layer` writes `mod_wet.usda` from the finished layer (cars
included). Alpha: the prims keep `use_legacy_alpha_state = 1` (REMIX-POLISH's cutout fix),
and a cut-out texel's luminance is filled from its visible neighbours before the bands
are taken, so a fence's edge is not a cliff in the normal map.

Regenerating (from `~/gta2-linux`, ~15 min of CPU at JOBS=3 on an idle machine; under the
usual load of game runs it took far longer, see below):

    bash /tmp/wt-<you>/linux/docker/build_remix_mod.sh          # your worktree's package layer
    MOD=/tmp/<dir>/gta2hd bash /tmp/wt-<you>/linux/docker/build_remix_mod.sh   # a scratch copy
    ZIP=1 bash /tmp/wt-<you>/linux/docker/build_remix_mod.sh    # + the release zip
    PACKAGE=/tmp/wt-<you>/package gamerun/playtest_remix.sh ...  # take it under Remix
    python3 repo/tools/remix_pbr.py preview <out.png> <tile.dds> ...                 # maps of some tiles

**Never into the shared checkout (FIX-REMIX-MATERIALS-6, 10 Nov).** The layer files
(`pbr.json`, `mod.usda`, `mod_wet.usda`, `model_prims.txt`) appeared uncommitted in the shared
`repo/package/rtx-remix/mods/gta2hd` three times (04:13, 06:27, 06:40), each identical to the
fixer's worktree copy, and blocked two restages. Cause: every Remix launcher
(`playtest_remix.sh`, `remix_l4.sh`, `rn_remix.sh`, `fr2_remix.sh`, `playtest_remix2.sh`,
`playtest_remix_ptveh.sh`) mounted the shared `repo/package` as `/package`, so a layer built in a
worktree could only be taken under Remix by copying it there; and `build_remix_mod.sh`
defaulted `MOD` (and its tools) to `repo/`. Now the launchers mount `${PACKAGE:-repo/package}`,
and `build_remix_mod.sh` takes its tools and default `MOD` from the checkout that holds it,
refuses a `MOD` inside the shared checkout, and (the `gamerun/` copy, outside git) refuses to
run without an explicit `MOD`. Check `git -C repo status --short` after any layer step.

The car and prop materials are REMIX-CARPROPS-PBR's (`remix_model_materials.py`), the
post stack and presets REMIX-POST's (`package/rtx.conf`, `rtx_showcase.conf.extra`).

**Built (8 Nov, 17:26; all 2 649 tile prims of wil/bil/ste, every one with the new maps):**
2 649 normals (512 px BC5, 1 047 MB), 2 649 roughness (256 px BC4), 1 674 height maps
with `displace_in` 0.006-0.018 (63 % of the tiles: brick, block, cobble, panel and relief
facades; signs and flat paint left out), 500 tiles with a metallic map (630 metallic maps
in all with the car pass), 864 wet roughness maps (ground-like tiles), 64 sign emission
maps (unchanged); the car/prop pass (REMIX-CARPROPS-PBR's tool as of 17:26) added 552
model prims. 3 201 prims, 11 830 texture references, none missing, in both `mod.usda`
and `mod_wet.usda`; every map decodes with Pillow at its size. Bytes on disk by map:
albedo 713 MB, normal 1 047, roughness 170, height 73, metallic 44, wet 38, emission 28:
**2.0 GB** (was 1.1 GB; the 512 px normals are most of the growth; `SIZE=256` halves
the normals to 262 MB if the size matters more than the close-up relief).
`deliverables/remix_mod_gta2hd.zip` (`tools/pack_release.py <out> remix`, store-only,
now with `mod_wet.usda` and `pbr.json`): **2 123 427 523 bytes** (was 1 084 585 827).
The previous layer is kept outside the repo (`~/gta2-linux/trash_vis/gta2hd_before_visuals`)
for a rollback. Map sheet (offline, raking-light preview of old vs new normal, roughness,
wet roughness, metallic, height for eight tiles of the three districts):
`out/visuals_remix_maps_sheet.png` (`remix_pbr.py preview`).

**Not verified under Remix.** The take for it is ready (`linux/docker/vremix_run.sh <name>
[layer folder]` → `remix_vis_take.py`: the spawn plaza and two warp spots, first person
round and chase view, 14:00 and 22:00, the same headings in every run, so the old and
new layers compare frame for frame), but on 8 Nov from 16:24 to 18:45 no Remix session on
the L4 got past the front end, for this stream or REMIX-POST: the runtime either could not
create its Vulkan instance (`VK_ERROR_INITIALIZATION_FAILED`, runs `vis_base`, `vis_base2`,
REMIX-POST's) or failed with "DxvkCommandList: Failed to create fence" while compiling
shaders (`vis_base` retry, `vis_new` with this layer); the kernel log has NVIDIA
`NV_ERR_NO_MEMORY` allocation failures at 15:25 and 17:40 from the host overload. The
failures came before the level and before the layer's textures are read, with the old
layer as well as the new one, so they say nothing about the maps. Still to check on a
working session: that the height maps parallax-displace without swimming or edge
artifacts at tile seams (the tiles wrap, but the neighbouring tile does not continue the
relief), the `displace_in` scale (taken as the Toolkit's "depth / UV width" ratio; not
measured), the cost of 1 674 POM materials on the L4, that the metallic patches read as
metal and not as shiny stone, and the rain layer (`MODS_HD_SRC` at a folder whose
`mod.usda` is `mod_wet.usda`).


## Model PBR maps: cars, props, code objects, avatars (REMIX-CARPROPS-PBR, 8 Nov 2026)

Every texture a manifest model's mesh names (73 cars, the props, code objects, pickups,
tokens, weapons and the 41 Rocketbox avatars) now has a full AperturePBR material in the
gta2hd layer, keyed like before by the XXH3-64 of its uploaded texels:
`tools/remix_model_pbr.py` (new) makes the maps, `tools/remix_model_materials.py`
(rewritten) writes the DDS files and the prims. `build_remix_mod.sh` needs no new step:
its existing `remix_model_materials.py "$MODELS" "$MOD"` call now does all of it (the
sources are found at `assets-src` beside the repo; `--src` overrides, `--jobs N` runs a
pool, `--preview DIR` writes the maps of each texture as a PNG strip, `--report JSON`
lists what was written). It replaces only its own prims (the hashes in
`<mod>/model_prims.txt`, plus the older car prims), and unlinks a file before rewriting it,
so a layer whose textures are hard links to another is safe to build into.

**Formats (checked against the runtime's MDL, `dxvk-remix/src/mdl/Base`).**
`AperturePBR_Normal.mdl` decodes the default `encoding = octahedral` exactly like
`tangent_space_dx` (x along the tangent u, y along +v, no green flip; `tangent_space_ogl`
negates y): so the normals are written in DirectX orientation (y down the image) as
unsigned octahedral BC5, the convention `remix_materials.py` already used for the tiles.
Roughness and metallic are separate single-channel linear textures
(`reflectionroughness_texture`, `metallic_texture`, BC4); AperturePBR has no packed ORM
input, so a glTF metallicRoughness (G, B) or a Poly Haven ARM (R ao, G rough, B metal) is
split. A map that is flat over the visible texels becomes the `_constant` input instead
of a file. Emission: `emissive_mask_texture` (sRGB colour, BC3) x `emissive_intensity`.
All with full mip chains, at the texture's own size (most are 512 px).

**Where each map comes from, best first.**

1. *The source material* (`assets-src`, the glTF the importer read). Its normal map, its
   metallicRoughness or ARM texture, its roughness / metallic factors and its
   emissiveFactor. The procedural cars, code objects, pickups and weapons are authored per
   material (chrome 0.12 / 1.0, grille 0.3 / 0.9, tyre 0.85 / 0, lamp 0.2 with a warm
   emissiveFactor, tail lamp red, the siren lenses blue and red), Poly Haven (street lamp,
   hydrant, trash can, bench) and six object packs have real maps. A picture shared by
   several materials gets a material id per texel by rasterising each material's
   triangles in UV space (smallest on top): the street lamp's bulb texels glow, its body
   does not. The Rocketbox avatars' FBX2glTF export has 1x1 placeholder normals, so their
   `_normal` and `_specular` maps were fetched from the Microsoft-Rocketbox repository (MIT,
   beside the colour maps in `assets-src/humans/rocketbox/<name>/`); roughness from the
   specular (0.88 - 0.55 x spec, 0.3..0.92), metallic only on the pistol's bright steel.
   **Normal-map handedness is measured, not assumed**: a real height field's slopes are
   curl-free, so d/dv(n_x/n_z) correlates with +d/du(n_y/n_z) in DirectX orientation and
   with the negative in OpenGL. Poly Haven `nor_gl` maps come out OpenGL (-0.36), the
   Rocketbox maps OpenGL too (-0.20 .. -0.56, flipped), the object-pack drum DirectX
   (+0.17, kept).
2. *Derived from the albedo, detail-aware* (the image-to-3D car atlases, code objects,
   props without maps): a scale-normalised Hessian line and blob detector at three scales
   (0.8, 1.5, 2.6 texels at 512 px), not a Sobel of the albedo. A thin dark line (panel
   gap, door and shut lines, grille slot) is a valley of the luminance: one large positive
   eigenvalue and one small -> a groove; a thin bright line (chrome strip, rib, grille bar)
   -> a bead; a small round spot with both eigenvalues large and of one sign (rivet, bolt
   head) -> a dome or a dimple. A colour step (paint against trim, a livery edge) has a
   large gradient where it curves, and the detector subtracts 0.6 x the scale-normalised
   gradient, so a livery edge does not become a step in the surface. Responses are
   divided by the local contrast (a faint seam on dark paint counts like a crisp one on
   white), a grain band at 0.15 adds surface texture, transparent atlas background is
   filled by normalised convolution first, and the slopes fade to flat within two texels
   of an island's edge (no seams). Strength 5 on the car atlases, 3.5 on props, 1.0 on
   `__lit` and `__glass`; textures under 32 px get none (flat colour swatches).
3. *Per-texel classes* where the source has nothing per texel (the baked car atlases:
   their glTF says 0.38 / 0.55 for the whole car): REMIX-POLISH's classes (chrome, brushed
   metal, glass, rubber, painted body with the clear coat 0.2 / 0.12), with two changes: a
   large bright neutral field (a livery's white doors, a van's sides: more than 60 % of a
   15 px window) is white paint, not chrome, and busy rubber (tread) is rougher (0.6-0.9);
   avatars without a specular map: skin 0.5, cloth 0.78.

**Emission.** Tail and brake lamps (REMIX-3's compact red islands at the car's ends) and,
new, head lamps on the baked cars: compact, very bright (luminance > 0.8), white-to-warm
islands at the ends that are smoother than the chrome around them, intensity 3; the
proc cars' lamp / tail / siren materials (emissiveFactor, intensity 6); every `__lit`
companion model (the booth's PHONE sign and rim, the traffic-light lenses, intensity 8;
the pickups' and tokens' rings and the ringing handset, 3); the street lamp's bulb (12).
No model has a dashboard material and no atlas has a recognisable lit dashboard, so no
dashboard glows. Split pairs keep REMIX-POLISH's rule (both prims one opaque whole-model
material); for an avatar the `_paint` half is the clothing and keeps the cloth roughness
(a gang member's tint is a texture factor, so under Remix a tinted pedestrian's merged
material takes the tint on the skin as well: untested).

**Built** (into the package layer; VISUALS-REMIX's 17:26 build ran this tool and its
prims are in commit 6559ad5's `mod.usda`): 552 model prims (was 253), all 552 hashes
match a texture in `assets/models` (no stale prim):

| | prims | normal | roughness map | metallic map | emissive |
|---|---|---|---|---|---|
| cars (73 models) | 215 | 209 | 124 | 120 | 67 |
| props | 71 | 64 | 62 | 4 | 1 |
| code objects, pickups, tokens, weapons, traffic lights | 92 | 25 | 24 | 0 | 40 |
| avatars (41 Rocketbox + the starter character) | 174 | 174 | 173 | 3 | 0 |
| all | 552 | 472 | 383 (169 constant) | 127 (425 constant) | 108 |

Size: albedo 121 MB, normal 121 MB, roughness 54, metallic 22, emissive 22: **340 MB**
for the model materials, against 135 MB for the 253 car prims before: **+205 MB**, of
which the normals are 121 MB (they are at the textures' own 512 px; at 256 px they would
be 30 MB). Offline sheet (maps, and the albedo lit by one raking light before / after,
with 2x crops of three car atlases): `out/remix_carprops_pbr_sheet.png`
(`linux/docker/remix_carprops_sheet.py`).

Known weak spots of the derived maps: the image-to-3D atlases bake shading and
reflections into the colour, so the class rules see some of them as material (the taxi's
white chequer squares are bright, neutral and busy and come out chrome); the dark
shadowed areas of a dark car read as rubber; a Hessian groove follows every dark
line, including baked shadow lines.

**Verification take** (`linux/docker/pbr_verify_run.sh <name> [layer]`, `keys_remix_pbr.sh`):
VISUALS-REMIX's fixed spots (`remix_vis_take.py`) and, with `PBR_TAKE=1`,
`remix_pbr_take.py`: the scene car dressed as the cop car, the taxi, the Schmidt and the
fire truck, orbited and from the driver's side, the nearest pedestrian from a step away,
the booth and the traffic lights walked up to, the plaza's lamp posts, at 14:00 and
22:30; the per-frame log is on (`GTA2DX9_FRAME_LOG`), and `pbr_frame_cost.py` compares
the frame cost of runs step by step (`rtx_nodisp.conf.extra` = the showcase settings with
`rtx.displacement.mode = 0`, for the cost of the parallax materials). **Not yet run to
the end**: the first session (`pbr_new`, 19:05) was stopped for the coordinator's GPU
reset after the host-wide "Failed to create fence" failures.


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

## CAR-PBR: Remix maps for the regenerated cars (9 Nov 2026)

ASSET-VEHICLES rounds 9-11 replaced the textures of 003, 004, 005, 019, 021, 022, 029, 052, 069 and 071, so their
XXH3 hashes changed and the 8 Nov maps (REMIX-CARPROPS-PBR) no longer matched. Regenerated with the existing tools,
no code change: `remix_model_materials.py repo/assets/models <layer> --jobs 4` (needs numpy, PIL, xxhash: host
`python3` has none, `/mnt/gta2/ab_work/venv/bin/python` has them), under `flock /tmp/gta2-gen.lock taskset -c 0-4
nice -n 10`, then `remix_materials.py - <layer> --wet-layer`. It touches only its own prims (hashes in
`model_prims.txt`); model_prims went 552 -> 656 (the layer was also missing the later avatars). Each of the ten has two
prims (atlas `_0` and `_0_paint`; the mesh names only `_0`), all new hashes, all with normal, roughness, metallic and
emissive maps (class-derived: the image-to-3D atlases have no source materials).
**Hard-link hazard**: a `cp -al` copy of a layer shares `mod.usda`, `mod_wet.usda`, `model_prims.txt` and `pbr.json`
inodes and the tool rewrites them in place; copy those four for real first (the DDS files are unlinked before writing).
The copy must be on the same filesystem as the repo.

**Verified** (real Remix frames, GPU 2, `stage_av11`, `linux/docker/keys_remix_carpbr.sh` + `remix_carpbr_take.py`, layer
mounted with `-e MODS_HD=1 -e MODS_HD_SRC=<mount>`): the layer installed (3305 materials) and the cars 003, 071, 022,
004 (day, third person) and all five 003, 019, 071, 022, 004 (night) render with lit, textured bodies, no black or
flat-matte body; the 071 and 004 paint shows specular highlights. Sheets: `out/carpbr/carpbr_{day,night}_sheet.png`.
**Not proven**: the old-layer run (`carpbr_ab.png`) showed bodiless wheels for 003/004/019 in some frames and the new run
did not, but the runs differ in timing and car order, so that is not an isolated effect of the maps; no close
reflection crop was taken; 019 had no day third-person frame (the view switch missed). 005, 021, 029, 052, 069 have maps
but were not filmed. The maps are not in the shared `package/` layer (release-archive material); the layer used is a
private copy. Known unrelated defect: the avatars' police and security pistols share one texture with and without a metallic
map, so `1AA4B8C5FD5FD552.m.rtex.dds` can be missing (layer validation reports it).

### CAR-PBR merged into the shared layer (REMIX-LAYER-INTEGRATE, 9 Nov 2026)

The ten cars' prims and maps (20 prims: `_0` atlas and `_0_paint` for 003 004 005 019 021 022 029 052 069 071; 92 map files)
were copied from the private layer into `package/rtx-remix/mods/gta2hd` with the new `tools/remix_layer_merge.py <src> <dst>
<hashes.txt>`: it copies only the listed hashes' DDS files (unlinking the target first), replaces or inserts those `mat_<h>`
prims in `mod.usda` and `mod_wet.usda` (model prims are identical in both), adds the hashes to `model_prims.txt`, and writes
the text files through a temp file + rename. It deliberately does not re-run `remix_model_materials.py` on the shared layer:
that rewrites every model prim and would have added the avatar prims of other agents. `pbr.json` holds tile entries only, so
it needed no change. Result: `git diff` of the three tracked files is additions only (the station glass, lights and sky prims
of FIX-REMIX / FIX-REMIX-2 are byte-identical); `remix_materials.validate` reports 3222 prims, 0 problems; the old-hash prims
of these cars stay in the layer (inert; no manifest model references them). The DDS maps are not in git (release archive only).


## Model-material hashes verified in path-traced frames (REMIX-HASH-VERIFY, 9 Nov 2026)

**Result: the model prims match the runtime for every texture the renderer draws as it is loaded.** The
car, prop, code-object and weapon prims (including CAR-PBR's maps) apply. Figures don't: under Remix the
renderer draws avatar bodies with textures it bakes per identity, and those hashes are in no layer.

**Scheme (now confirmed in frame).** A model texture (`dll/src/model_store.cpp BaseTextureFor`: one level,
`D3DFMT_A8R8G8B8`, managed pool, the TGA's rows written top-down) is keyed `mat_<XXH3-64 of its BGRA texels,
rows top-down>`, as `remix_materials.remix_hash` computes it. No re-key was needed.

**Positive control, one session** (`out/rhv_probe1`, GPU 0, stage of 16:55, 0 faults; sheet
`out/rhv_sheets/probe_sheet.png`). `tools/remix_model_hash_probe.py <stage> <probe dir>` writes a flat-colour layer,
installed as gta2hd (`MODS_HD_SRC`):
- cyan: every HD tile, top-mip hash (the 6 Nov scheme);
- magenta: every model TGA in the stage under the layer's scheme;
- yellow, green, orange: the same texels hashed rows bottom-up, R/B swapped, and alpha forced to 255.

The take is `keys_remix_carpbr.sh`: cars 003 and 019 at 14:00, orbit and first person. What the frames show:
- Every street, wall and roof is cyan.
- Cars 003 and 019, the lamp posts, hydrants, signs and parked cars are magenta. Car 019's paint half is
  magenta times its blue tint, so the paint prim matches too and Remix keeps the texture factor.
- No yellow, green or orange anywhere.
- Pedestrians have magenta heads. Their bodies keep their own clothing colours.

**Prim edits change the car (A/B)** (`out/rhv_ab1`, the shared layer with three prims edited; sheet
`out/rhv_sheets/ab_sheet.png`, crop `ab_019_chrome_crop.png`):
- Car 019's `_0` atlas prim set to metallic 1, roughness 0.05: the body renders as a mirror, with sky and
  street reflected in it.
- Car 003's two prims removed: the car falls back to the game texture, dark and flat, where the shared layer
  (`out/carpbr_new1`, same take) draws it olive with its maps.
- Car 019's paint prim with no `diffuse_texture`: it still shows the orange paint, but that could be the paint
  tint over a default albedo. Whether Remix falls back to the game texture is **not settled**.

**Why figures miss** (and why REMIX-3D-QUALITY's five schemes all "failed"). With `IdentityBakeTints()` (on
under Remix) the renderer draws a split body through `FigurePairMerged` (rest plus paint texels, the record's
zone tints baked in) and zone or tint parts through `BakedTint`. Each is a new texture with its own hash, one
per avatar and tint, and no layer prim names it. Heads, hair and other unsplit parts are drawn as loaded, so
they match. REMIX-3D-QUALITY's tagged texture copies fed those merges, so most of the copied textures never
reached a draw. Their hash list could not hide the figure under any scheme. Filed as
`remix-figure-baked-textures-miss-layer-prims`, with the options.

**Coverage gap, filled.** The shared layer had no prims for 170 textures that today's `assets/models`
manifest models use and the stage loads byte-identically: cars 016, 047, 048, 064 and 083 (both halves),
`street_lamp_0`, mailboxes, stop/one-way signs, five weapons, the first-person cup arms, the bus shelter,
and 144 avatar textures. They were built with `remix_model_materials.py repo/assets/models <scratch>`, then
merged with `remix_layer_merge.py <scratch> package/rtx-remix/mods/gta2hd <170 hashes>`. The merge only
adds: 3392 prims, `validate` reports 0 problems, and the 526 new DDS maps are in the release layer's
`textures/`, not in git.

Not merged:
- the CAR-PBR determinism pair `1AA4B8C5FD5FD552` and `DC748E21E2E1BBBE` (a map exists for one of the two
  texture owners);
- textures that differ between `assets/models` and the stage: 008, 036 and 056 proc parts the stage does not
  load yet;
- the 92 stale model prims, which are inert and left in place.

In game (`out/rhv_merged1`, the merged layer, 3392 materials installed, 0 faults, no missing-texture errors in
`remix-dxvk.log`; sheet `out/rhv_sheets/merged_sheet.png`):
- Cars 047 and 083 (new prims) render textured and lit.
- Car 019, with its shared prims and the same take, shows matte orange paint. This is the reference for the mirror body
  in `rhv_ab1`.

The new prims' hashes follow the scheme the probe proved. There was no per-prim A/B for them.

To check the gap again: `remix_model_materials.py <models> <scratch> --report r.json`,
then diff the report's hashes against `mod.usda`.

## Material classes: road paint, paving, foliage, car paint, trees (REMIX-MATERIALS, 9 Nov 2026)

Five path-traced material defects had one root: every tile got the same treatment from its albedo, and the cars a coat
too smooth for their maps. The fixes change only what the gta2hd layer draws for a texture (albedo and maps); every
Remix hash stays the game's, the renderer is not touched, and the plain classic view cannot change.

**Tile classes from the map** (`remix_materials.py --gmp-dir game/data`, `tile_classes`). A tile used mostly as the lid of
road blocks (ground type 1) is `road`, mostly as the lid of pavement or field blocks `pave`, the rest (walls) as before.
`remix_pbr.analyse(..., ground=)`:

| class | structure / grain relief | parallax height | paint |
|---|---|---|---|
| road (186 tiles of the three districts) | 0.2 / 0.5 | none | texels 0.12 brighter than the asphalt (white or yellow) flat, roughness -0.08 |
| pave (955) | 0.45 / 0.7 | none | as before |
| walls | 1 / 1 | as before (bricks, facades) | as before |

The **road lids' Remix albedo is the re-authored paint** (`assets/textures_hd/roads/<style>/`, FIX-PROPS/QB-24): the
renderer binds that set in the plain street views only, so under Remix the plain tile's hash still keys the material
but the clean paint is what is drawn (56 tiles; `pbr.json` notes `"albedo": "roads/<style>/tile_NNNN.dds"`). Causes, as
seen offline (map sheet: albedo and raking-light normal, old vs new) and in frame: the crosswalk's albedo was the
upscalers' zebra noise, its normal a relief of that noise and its prim had a parallax height map on it (the "clay");
the wil plaza paving (436/440/443, the "rail track" of pt-remix-rail-track-tile-extreme-normal-relief, which is brick
paving, not rails) had parallax 0.014-0.016 on a lid seen at grazing angles. No lid has a parallax height now; walls keep it.

**Foliage** (`remix_pbr.VEG_LIFT`, `veg_albedo`). The hedge tile (bil 854 = ste 470) has opaque leaves at sRGB (6,14,4),
median luminance 2/255: path traced, black speckle (FIX-REMIX-2's finding; the cutout already worked). The layer's albedo
of 19 curated foliage tiles (hedges, bushes, lawns, the cut-out shrub sprites, mossy walls) is lifted affinely in sRGB
luminance to a mean of 0.30 (floor 0.14, gain capped at 4), keeping each texel's own chroma where it has one and a
leaf green where it is near black; alpha bit-exact, except on the two **hedge-block** tiles (bil 854, ste 470,
`VEG_SOLID`): at dusk their cutout holes looked into the block's unlit inside and stayed black (17 % of the top under
0.03 at 17:30 with the lift alone), so those two are drawn opaque, the holes a darker leaf (sRGB 0.16-0.26). The detector `veg_dark()` alone also takes Industrial's green-painted
metal panels (ste 320-381), window frames (ste 90/91) and pipework (bil 580), which is why the list is curated.

**Car paint** (`remix_model_pbr.py`): clear coat roughness 0.12 -> 0.28, chrome 0.16 -> 0.24, the image-to-3D atlases'
derived normal strength 5 -> 2.5. The 1-3 px white dashes on every car by day were sun glints on a near-mirror coat over
a noisy derived normal. Regenerated for the 246 car prims (`--pattern '^\d{3}_.*\.tga$'`).

**Trees** (`tools/gen_trees.py canopy_shell`): the canopy was three crossed vertical cards through the axis plus two
near-horizontal cards across the whole crown; from the side the horizontal cards and their shadows were the two straight
black bands. Now 14 smaller cards on an ellipsoid shell, each facing out, plus two inner crossed cards (128 triangles,
was 84); the leaf and bark textures are byte-identical, so their Remix prims still match. `assets/models/tree_0N.mesh`
re-imported with `import_assets.py`.

**Building into the shared layer** without rewriting other agents' prims:

    P=/mnt/gta2/ab_work/venv/bin/python     # numpy, PIL, xxhash
    $P repo/tools/remix_materials.py - <scratch>/gta2hd --dds-tiles repo/assets/textures_hd/{wil,bil,ste} --size 512 \
        --map-size 256 --jobs 4 --gmp-dir game/data --only-classed --force --exclude <upstream mod usda files>
    $P repo/tools/remix_materials.py - <scratch>/gta2hd --wet-layer
    $P repo/tools/remix_layer_merge.py <scratch>/gta2hd <layer> <tile hashes> --tiles     # skips water / sign / facade prims
    $P repo/tools/remix_model_materials.py repo/assets/models <scratch>/cars --pattern '^\d{3}_.*\.tga$' --report r.json
    $P repo/tools/remix_layer_merge.py <scratch>/cars <layer> <car hashes>

(77 s and 48 s of CPU under the gen lock.) `remix_layer_merge.py --tiles` also carries the `.h`/`.w` maps and the
`pbr.json` entries and leaves `model_prims.txt` alone. `build_remix_mod.sh` gets the same result for a full rebuild once
it passes `--gmp-dir game/data` (it does now). The DDS maps embed the game's art: release archive `remix_mod_gta2hd.zip` only.

## Car textures changed by FIX-CAR-IDENTITY-2 (9 Nov 2026): prims to rebuild

For REMIX-MATERIALS (this stream does not rebuild the layer). These textures in `assets/models` changed, so their prims in
`gta2hd` (keyed by the old hashes) no longer apply until rebuilt and merged (`remix_model_materials.py`, then
`remix_layer_merge.py`):

- `004_g4_bank_van_0.tga`, `004_g4_bank_van_0_paint.tga`: re-split (the bank van is a painted car now; it had no prim before either)
- `012_cop_car_0.tga`, `012_cop_car_0_paint.tga`: the top repainted white from the sprite (`tools/car_livery_project.py`)
- `034_medicar_0.tga`, `034_medicar_0_paint.tga`: the top and the tail repainted cream from the sprite

Details: `docs/identity-system.md` section 6.

FIX-CAR-IDENTITY-3 (9 Nov 2026): these six and `057_t_rex_0`, `067_tv_van_0`, `014_eddy_0` (and their `_paint` twins,
re-split) now have prims in `gta2hd`: 12 inserted with `remix_layer_merge.py`, additions only. Not yet seen path traced.
Recipe: `docs/identity-system.md` section 8.5.

## Car paint under path tracing: stale prims, a real clear coat, no false head lamps (FIX-REMIX-MATERIALS-2, 10 Nov 2026)

pt-remix-noon-car-paint-matte-clay-no-specular-no-sky-reflection and pt-remix-third-aniston-bd4-pale-car-black-ragged-patchwork
had one root cause, and it was not the coat's roughness.

**Cause: the car textures had moved on and their prims had not.** The re-split of 9 Nov 20:38 (FIX-CAR-IDENTITY-2,
`car_paint_resplit.py`) and the authored cars after it rewrote the `_0` atlas and its `_0_paint` twin of 42 of the 83
cars (018 Shark, 002 Aniston BD4, 019 GT-A1 among them). Each got a new XXH3 hash, and the layer's prims stayed keyed on
the old ones. Under Remix such a car is path traced with the runtime's default material, and its two draws (paint half
and rest, the same mesh, each alpha-tested) are taken as one duplicate draw, so only one half shows (REMIX-POLISH's
finding above). The result was a uniform matte grey-white "clay" body with ragged black window and arch holes (the Shark),
or a pale shell with whole panels missing (the BD4, the GT-A1). The plain renderer draws the same BD4 as one clean
pale silver car (`qa_frm2_plain`, same poses), so it was the layer, not the renderer's paint mask. By 10 Nov 00:20,
after VEHICLE-ART-7, 174 of the 420 car textures the meshes draw had no prim.

**Fix.** All car prims were rebuilt from the current `assets/models` (266 prims, `remix_model_materials.py --pattern
'^\d{3}_.*\.tga$'` into a scratch layer, then `remix_layer_merge.py`: 262 replaced, 270 inserted counting both usda files,
none removed; `model_prims` 799 -> 934). Re-check after any car-art change with the new
`tools/remix_car_prim_check.py` (exit 1 and the missing hashes; 0 missing now). The other changes, all in `remix_model_pbr.py`:

| | was (211bd69) | now |
|---|---|---|
| car paint (texels of the `_paint` half) | roughness 0.28, metallic 0.2 | roughness 0.18, metallic 0.05: a dielectric clear coat over the colour |
| derived normal on the paint texels | full strength (2.5 on the atlases) | x0.3 (`PAINT_NORMAL_DAMP`): the panel lines stay as soft lines, the atlas grain goes |
| chrome | 1.0 / 0.24 | 1.0 / 0.20 |
| baked head lamps | any compact very bright neutral island at the car's ends | the island must also be 0.22 brighter than the visible texels around it (`HEADLAMP_CONTRAST`), and pale cars (median luminance of the lit end texels > 0.55, `HEADLAMP_PALE_BODY`) get none |

The firefly order (pt-remix-car-paint-firefly-sparkle) blamed the glints on a near-mirror coat over the derived normal's
grain. With the grain damped on paint the coat can be smooth again: no white dash glints were seen on any body in the
takes below. The head-lamp gate is new because the first build of this pass made the BD4's nose glow as hard white
islands at 21:30. The detector had taken fragments of its white body between the baked grime lines for lamps. Cars
that keep baked head lamps: 012, 014, 034, 037, 051, 057, 064, 069, 071, 082, 083. Every car still has the `[Car lamps]`
lights at night.

**Verified in path-traced frames** (GPU 2, private stage = HEAD DLL, `rtx_play.conf.extra`). The take is
`gamerun/frm2_remix.sh` with `KEYS=keys_frm2_own.sh` / `frm2_own.py`: the player's own car is stopped at one spot,
forced to 018/002/019/012 with their identity paints, and filmed from six fixed regression-camera poses at 13:00 and 21:30.
The same poses were taken with the old layer (`frm2_own_before`), the final layer (`frm2_own_final`) and the plain renderer
(`qa_frm2_plain`, `keys_qa_frm2own.sh`). On the old layer the Shark is flat pale clay with ragged black windows and the
BD4 and GT-A1 have ragged holes. On the new layer:
- **Shark:** a whole car in its identity grey-green. Roof mean (141,147,134), where the old layer gave a washed-out
  (169,171,157). A soft sun highlight follows the roof and bonnet curvature, the sky reflects on the roof, and the bumpers
  and hubs are chrome.
- **BD4:** whole and pale, with a chrome grille and wheels. At 21:30 it is a smooth, glossy pale body with soft
  reflections of the lamps and no white or black islands.
- **GT-A1:** whole, glossy red, with a sun highlight on the bonnet bubble.
- **Shark top view at 13:00, highlight to body (luma p99/p50):** roof 1.09 -> 1.37, bonnet 1.17 -> 1.70 (p99 = 255 on the
  bonnet).

The classic view does not read the layer: vreg on the same stage gives 31/31 PASS, `spawn_classic` 0 tiles. Under Remix,
the 13:00 classic frames at wil 120.5,152.5 with the old and the new layer are the same picture. They differ only by a
1-pixel camera offset and the traffic.

**Still short of a shipping frame.** These are faults of the art, not of the material:
- The image-to-3D atlases bake grime and reflection blotches into the colour. The BD4's front and the GT-A1's flanks show
  dark mottling that a clear coat cannot hide.
- Glass is the atlas's dark texels made smooth (0.05). It reflects the sky but shows no interior, and the 018 windows
  are opaque.
- The paint hue under Remix follows the identity tint (the stage-1 texture factor). No `identity_parity` delta-E was measured.
- 018's mesh no longer names its old `_1_paint` / `_3_paint` parts, and those files are stale leftovers of another
  size (VEHICLE-ART).
- The layer's DDS changed: the release archive `remix_mod_gta2hd.zip` needs repacking (RELEASE-PACK).

## The cars' smoke under Remix: dithered cut-outs (FIX-REMIX-NIGHT, 9 Nov 2026)

pt-remix-night-smoke-puff-opaque-clay-lump: the "clay lump" was vehicle_fx's tyre smoke / exhaust / steam puff (its 5-lobed edge), not
the game's sprites or the burning-car smoke. The puff is alpha-blended with its opacity (0.2-0.34) in the vertex colour and a soft texture
alpha of 1 at the core. Under this Remix runtime a blended texel's colour comes out scaled by its texture alpha: the puffs were dark rings of
grain round a lit core, a hard tan lump under a lamp. Same-session A/B (`[devtools] spawn_smoke=1` puts a puff column a block east of the
player; `remix_puff_levels=0` draws it the old way; out/rn_night4..9): the opacity moved into the texture gave soft but black puffs at noon
and night, whether the textures were in `rtx.particleTextures` or not, with `approximateParticleLighting`, `enableEmissiveBlendModeTranslation`
or `enableStochasticAlphaBlend` on or off, and with up-facing vertex normals. Opaque texels are lit correctly.

So under Remix (vehicle_fx.cpp, `remix` path only) a puff is a dithered cut-out: 8 opacity steps x 4 noise seeds of a 128 px texture whose
covered share of texels is the opacity, drawn alpha-tested with up-facing normals; the seed cycles per frame and per puff so the grain moves
and the temporal filter averages it. The plain renderer's draw is unchanged. Verified (Ultra, path traced, out/rn_night9 t_S_*): at noon white
smoke with the kerb and fence through it, at 22:30 dim, lamp-tinted smoke, no silhouette; the old path in the same session: dark opaque rings.

Still short of shipping: in a still frame the puff is visibly grainy (sand rather than vapour), denser than real tyre smoke where many puffs
stack, and it has no self-shadowing or soft volume; the AAA answer is Remix's own volumetric/particle system fed with an emitter, not
billboards. The burning-car smoke (live_geometry.cpp) and the blast smoke (explosion_fx.cpp) take the same blended path and were not changed.

### The puff's grey under Remix (FIX-FX-5, 10 Nov 2026)

A burning car's smoke at night under Remix was a cloud of pale blue-white flakes (out/ffx5_fi1, a forced burn of a
parked 068 van at wil 198.5,188.5 at 22:00). vehicle_fx emits a burning engine's smoke at grey 0.2 and tyre smoke, steam
and exhaust at 0.7-0.9, but on the wisp path that grey was only in the vertex colour, and this runtime drops vertex colour
(`rtx.ignoreAllVertexColorBakedLighting`). The wisp textures now come in three grey tones baked into the texels:
light (x1.0, the old shade, so tyre smoke, steam and exhaust are unchanged), mid (x0.55) and dark (x0.26). A puff takes the
nearest tone. That is 96 textures (8 steps x 4 seeds x 3 tones of 128 px), made one a frame at first use.
`[devtools] remix_puff_tones=0` makes every puff light again (live). Same session A/B, run twice: out/ffx5_fi2
`fire_*_burn_t0` / `t0b` (pale flakes) vs `t1` / `t1b` (a dark grey plume). Still short of a volume: the plume is cut-out
flakes, not a soft column.

### Car lamps: a hot core in a dimmer lens (FIX-FX-5, 10 Nov 2026)

FIX-REMIX-NIGHT-8 noted that car lamps under Remix are flat white emissive discs. A lamp's emissive mask was its texels'
colour times one gain over the whole island: 3 for the baked head lamps, 6 for the red lamps and the glTF-emissive lenses
(the 068 van's head lamps and indicators). At night the whole disc clips to white. `tools/remix_model_pbr.py` now gives
every lamp island of a car texture (`lens_profile`) a smooth falloff from 1 at its centroid to `HEADLAMP_RIM` (0.30) at its
rim, and warms the core's colour toward white. Islands over `LENS_MAX_TEXELS` (600: lit panels, sign fields) and sign
textures stay flat. The prims are unchanged (same max gain, same file names); only 33 `.e.rtex.dds` files change.
A control regeneration with the profile off matches the shared layer byte for byte. Bundle: `layer_deploy/FIX-FX-5`
(deploy.sh + files.txt, VEHICLE-ART-17 format). Same-pose Remix takes at 22:00 on the parked 068 van, old layer
out/ffx5_ln0 vs new out/ffx5_ln1 (`fire_lamp_before`, `fire_eye_before`): the indicator goes from a flat amber block to a
hot pale core with orange-red edges. The head lamp goes from a fully clipped white disc with bloom to a lens with a dimmer
rim at the bezel. Still short: the head lamp's core is not much hotter than its body (the mottled albedo shows through),
and the authored carkit cars' head-lamp lens (one shared texture, 920CF946BF67669A) has no emissive at all; their night
look is the remix_lights beam only.

## Painted walls, murals, road lids, cut-outs and leaves (FIX-REMIX-MATERIALS-3, 10 Nov 2026)

Five path-traced defects filed against what the gta2hd layer draws for a texture (two fixed, one partly, two found
to be something else); no renderer change, every
Remix hash stays the game's, the plain views cannot change.

**New tile classes** (`remix_materials.tile_classes`, `remix_pbr.analyse(ground=)`), next to road/pave:

| class | tiles | normal relief (structure / grain) | parallax | albedo | roughness |
|---|---|---|---|---|---|
| flat: painted walls | 18: `remix_pbr.FLAT_WALL` (ste 160-178: the tan/grey plank and rendered facades, arches, shutters) | 0.12 / 0.35 | none | the DDS | as before |
| mural | 29: `remix_pbr.MURAL_WALL` (ste 355 graffiti, 759-762 rose-window mosaics, wil 175) plus every wall tile `mural_like()` finds (12 % saturated texels over three hue bins: murals, painted signs; the 21 signs with an emission prim keep that prim) | 0.12 / 0.35 inside the painted region (texels within ~16 px of saturated paint, soft edge), 1 / 1 on the wall around it | none | the DDS | as before |
| cut: other cut-out wall tiles (fences, railings, grilles) | 371 | as before | none | re-encoded with **coverage-preserving mips** (`cutout_mips`) | as before |
| road (changed) | 140 | 0.2 / 0.5 | none | **debanded** (`remix_pbr.deband`) where no re-authored road paint exists | asphalt >= 0.86, paint >= 0.62 |
| pave (changed) | 965 | 0.45 / 0.7 | none | the DDS | >= 0.74 except metal/chrome/glass |

* **Facade strata, mural wax** (pt-remix-building-arched-facade-carved-wood-strata-relief, pt-remix-graffiti-mural-wax-blob-relief).
  The structure band of the height is normalised by its local contrast (`Hs = tanh(1.4 d / loc)`), which is right for
  brick (every joint a groove of the same depth) and wrong for a painted wall: the upscaler's faint wavy plank lines and
  the painted shadow under an arch became full grooves and plateaus (tile 160: normal tilt p90 18 deg, p99 34 deg; the
  arch 161 had a parallax height 0.012 as well), and on the mosaics every white patch a raised blob (759/760 p90 44 deg,
  parallax 0.018). As flat: p90 6-10 deg, no height. On the mosaic tiles only the painted region is flattened, so the stone
  courses and the pilaster round the window keep their relief.
* **Road lids** (pt-remix-plaza-paving-posterised-patches-sky-streak-reflection). The "plaza slab" at ste 113.5,124.7 is
  the road (806/814/821/831, road class), pale teal under the morning sun. Its albedo is the upscaler's posterised
  contour bands (no re-authored road paint exists for these tiles); `deband` soft-thresholds the mid band (1.5-24 texels):
  steps under 0.018 go, over 0.05 (kerb, lane line, crack) stay, then a faint grain. The road texels were tinted, so in no
  roughness class (0.69-0.75): now asphalt-rough.
* **Cut-outs** (pt-remix-third-distant-fence-and-railing-tops-shredded-horizontal-streaks): the DDS mips are box-filtered,
  so a 2-texel bar next to a hole averages under the alpha test's 128 and drops out at distance (tile ste 987: 22 % of
  texels pass at 512 px, 12.5 % at 8 px, 0 at 4 px), and its colour is darkened by the holes. `cutout_mips` averages
  colour over the opaque texels only and scales each level's alpha so the passing share stays the top level's.
* **Leaves: tried, not kept** (pt-remix-dusk-tree-crowns-large-black-wedge-slabs-grey-spike). The trees' leaf atlases
  `tree_0N_1.tga` have **no prim** in the layer (re-imported after it was built; 23 prop textures in all: the leaves,
  bus shelter, phone booths, mailbox, stop sign; `remix_car_prim_check.py`-style scan), so the cards are the runtime's
  default material. A leaf prim with a thin-walled subsurface transmittance (leaf-green transmittance and scattering
  albedo, anisotropy 0.35) and coverage mips, filmed at bil 140,246 17:30 (`fm3_bil_before2` vs `fm3_bil_after`):
  the crowns came out darker and brown-rimmed (the low sun through the cards), with the same black wedges. The wedges
  are geometry: the two inner crossed cards of `gen_trees.canopy_shell` in the shade of the outer shell, and an outer
  card seen edge-on is the thin grey "spike". Not shipped; the fix is the canopy mesh (fewer, smaller inner cards, or
  normals bent up-and-out from the crown centre), owner of `tools/gen_trees.py`. The 23 prop prims were not shipped
  either (not seen in frame).
* **Hedge "two hues"** in the same report: two different map tiles, not a lid/side split. The hedge block is bil 854
  (lid and sides, the opaque lifted leaf of REMIX-MATERIALS); the tall dark blocks next to it are 695 (lid) / 696 (sides),
  an ivy wall with its own grey-green texture. Left as authored.

**Seen path traced** (GPU 3, `playtest_remix.sh`, REMIX_NVCACHE=1, layer from `MODS_HD_SRC`; before = the shipped
layer of b96a530 on a 126258a stage, after = this layer on the 490b588 stage, `-e GTA2DX9_SCENE_NO_CAR=1`):
* ste 75.5,150.5 at 12:30 and 23:00, third and first person (`fm3_ste_before` vs `fm3_ste_after5`): the arched plank
  facade reads as flat painted planks with shallow arch reveals; the wavy strata and black crack lines are gone, at night
  too. Faint plank lines of the albedo remain (they are painted).
* ste 113.5,124.7 at 09:00: the rose-window mosaic is flat glazed paint, no raised white lumps; the stone courses and the
  pilaster round it keep their relief. The road slab beside it has lost the contour-map patches and the ghost lettering;
  the hatched strip is matte. Still visible: tone steps from one road tile to the next (the upscaled tiles' own low band).
* Classic under Remix: the classic camera and geometry are the game's (no renderer change); the layer applies in every
  view, so from above the same road tiles are smoother. The classic frames of the two takes are not the same picture
  (the camera scrolls after the warp; the DLLs differ), so no pixel comparison was made.
* Two takes on the 126258a DLLs froze at the ste spawn (game thread blocked on the CRT heap lock inside gta2dx9.dll;
  filed as `remix-ste-start-game-thread-heap-deadlock-freeze`); a parked car near the spawn sends the scene warp to its
  door unless `GTA2DX9_SCENE_NO_CAR=1`.
* The "firefly clouds over the road" (pt-remix-first-white-firefly-speck-clouds-hang-over-road-day-and-night) are not a
  material: they trail moving cars in the air, the exhaust puffs drawn as dithered cut-outs (`vehicle_fx.cpp`), handed to
  the smoke path's owner. The firefly filter threshold was not changed.
* The car textures re-authored after b96a530 (018, 038, 039, 042, 051, 058, 082) had no prims again; rebuilt and merged
  (`remix_car_prim_check.py`: 506 textures, 0 without a prim at commit time).

`remix_layer_merge.py` replaces all prims in one pass (it was one regex pass over the whole layer per hash: minutes
for a thousand tiles, now 2 s). Rebuild (into a scratch layer, then merge):

    P=/mnt/gta2/ab_work/venv/bin/python
    $P repo/tools/remix_materials.py - <scratch>/gta2hd --dds-tiles repo/assets/textures_hd/{wil,bil,ste} --size 512 \
        --map-size 256 --jobs 5 --gmp-dir game/data --only-classed --classes road,pave,flat,cut,lift --force --exclude <upstream usda>
    $P repo/tools/remix_materials.py - <scratch>/gta2hd --wet-layer
    $P repo/tools/remix_layer_merge.py <scratch>/gta2hd <layer> <hashes of scratch pbr.json> --tiles

## Smooth ground lids, iron railings, leaf atlases (FIX-REMIX-MATERIALS-4, 10 Nov 2026)

Three changes to what the gta2hd layer draws; no renderer change, every Remix hash stays the game's, the plain views
cannot change (the classic view under Remix draws the same layer, so its lids gain the same grain from above).

**Smooth ground lids get a scan's micro-surface** (ptrmx17-remix-ste-sidewalk-featureless-custard-plane-no-tile-no-normal).
The ste "sidewalk" at 193.5,60.5 and 160.5,45.5 is tile **ste 516** (1 372 lids in the district): in the game's 64 px art an
olive-to-sand verge with no joints, and its HD upscale is a smooth gradient (grain RMS 0.002 against a median 0.02 over the
966 pave lids). `analyse()` had nothing to build relief or roughness variation from, so path traced it was one painted plane.
The prim existed (no missing hash). 174 pave lids with grain RMS under ~0.010 (wil 29, bil 35, ste 110: paving, asphalt,
concrete and lawn tiles) are listed in `tools/remix_micro_tiles.json` with the photo pass's material class
(`photoreal_tiles.py` labels + `photo_label_fixes.json`) and an amplitude (1 at grain RMS 0.004, 0 at 0.012).
`remix_pbr.micro_surface` takes that class's ambientCG scan (CC0, `photoreal_tiles.py fetch`, at its real size on a 4 m
block): the colour's luminance high-pass as grain and its 6-50 cm band as grime into the albedo (luminance only, x
exp(0.09 ga g - 0.08 grime)), the displacement high-pass as height into the normal (`MICRO_GAIN` 0.28: tilt p50/p90 ~9/20 deg
on 516, was 1/6), and both into the roughness (grime rougher, worn tops smoother; 0.63-0.98 instead of a flat 0.74-0.94).
No joints are invented: the art has none. Build with `--cc0 <ambientCG dir>` (`--classes micro`).

**Railings are painted iron** (ptrmx17-remix-ste-iron-fence-slats-read-as-chrome-mirror-and-clay-by-side). The ste fence
(sides **ste 52**, finial tops ste 47) was classed per texel as oriented metal and chrome (the upscaler bakes a bright
cylinder highlight down each bar): metallic map 0.45/0.75, roughness 0.11-0.38, so in shade the slats mirrored the sky and
in sun the baked highlight read as cream clay. Class **iron** (`remix_pbr.IRON_RAIL`, 17 tiles curated from a sheet of the
cut-outs the detector calls metal: wil 217 623; bil 25 382 421 422 623 850 859 869; ste 47 52 77 408 457 510 909 987):
no metallic map (painted iron is a dielectric), roughness 0.52-0.72 from the paint's grain, albedo luminance compressed round
sRGB 0.17 (`iron_albedo`: the baked highlight goes, the hue kept at 60 %), coverage-preserving mips. Signs, siding and the
white lattice trellises keep their old maps.

**Leaf atlases have a prim.** `tree_01_1` / `tree_02_1` / `tree_03_1.tga` had none (runtime default material): now the
model-material tool's lone prim (roughness map ~0.85, metallic 0, derived leaf normal, the game's alpha test) with
coverage-preserving albedo mips. It does not cure the dusk crowns: see below.

**Seen path traced** (GPU 3, `playtest_remix.sh`, REMIX_NVCACHE=1, private stage = shared stage + c4fc56a DLLs,
`-e GTA2DX9_SCENE_NO_CAR=1`; before = the shipped layer of 4ae2112 via `MODS_HD_SRC`, after = it with these prims merged):
see the FIX-REMIX-MATERIALS-4 journal line for the run names and what each frame shows.

**Still short / not mine:**
* The **dusk tree crowns** (pt-remix-dusk-tree-crowns) keep their hard dark wedges with the leaf prim (bil 140,246 17:30):
  the leaf texels are not dark (opaque sRGB mean 0.23-0.28; a luminance lift moved it by 0.02), so the black is the canopy
  cards shading each other: geometry, `tools/gen_trees.py canopy_shell` (props #8).
* The **far rooftop railing** of pt-remix-third-distant-fence (bil 140,246 17:30, the filer's heading): reproduced on the
  4ae2112 layer and on this one, horizontal cream/dark ribbons with torn ends. The coverage-preserving mips (in both) do not
  clear it; what is torn is a thin alpha-tested structure a few pixels high at grazing angle (sub-pixel alpha test and the
  denoiser), not the mips.

## The paint tint under Remix, glass prims, prim coverage (FIX-REMIX-MATERIALS-5, 10 Nov 2026)

**Every repainted car was too dark and brown under path tracing: Remix drops the tint stage's 2X.** The plain renderer
multiplies a car's `_paint` texels by its identity tint with stage 1 `MODULATE2X` of a texture factor of tint / 2
(`model_store.cpp`). RTX Remix applies that factor to its albedo without the 2X (and as a colour), so a tint of
0.41,0.54,0.71 (the 000 Romero in 84,109,144) became a near-black charcoal and the 063 cab's 121,63,48 a desaturated
brown (pt-remix-first-truck-classic-red-orange-cab-third-brown-maroon). Measured in one Remix session with a live
`[devtools] remix_tint_mode` (0 the plain factor, 1 tint x 255, 2 tint^2.2 / 2), own car forced to 000/063 with the
identity paints, `gamerun/fm5_own.py` side and three-quarter poses at 13:00 (`out/fm5_tint3`, plain twin `fm5_plain2`):
truck cab median hue 13 deg plain, 26 deg (brown) in mode 0, 13 deg in mode 1, 51 deg in mode 2; Romero door 216 deg
plain, 45 deg (grey-brown) in mode 0, 207 deg in mode 1. Mode 1 is the default under Remix (only there: the plain
renderer's factor is unchanged, the classic view draws no car models). A tint over 1 (a paint brighter than the model's
own) clips at 255 under Remix. `models: Remix car paint <texture>: texture factor` lines name the path per paint texture.

**Glass.** A carkit body's translucent glass (`<car>_glass.tga`, alpha ~0.45, drawn blended; VEHICLE-ART-11's 063) and a
prop's `__glass` panes (bus shelter, phone booth, alpha ~0.15) now get an `AperturePBR_Translucent` prim (thin-walled,
IOR 1.5, transmittance = texel colour over the alpha, 0.35-0.92) from `remix_model_materials.py` instead of an opaque
diffuse prim: a low-alpha blended quad path traces dark (memory note on blend colour x alpha). Every car `_glass` texture
is drawn blended (alpha 0.41-0.81), so all 19 (8 distinct hashes) take the class; their old opaque prims were replaced.
Seen in `out/fm5_truck1`: a taxi's windows dark tinted glass with sky reflections, the 063 cab's lit interior visible
through its windscreen.

**Prim coverage** (`remix_car_prim_check.py --pattern '.*'` over every manifest model): 1140 textures of 279 models,
33 without a prim before (063's re-authored `_0` atlas and its new glass; 31 prop, pickup and weapon textures re-imported
at 00:11: bus shelter, phone booth and its ring/lit/glass companions, mailbox, stop sign, pistol pickups, machine gun),
0 after. Cars alone: 584 textures of 83 models, 2 missing before, 0 after. After VEHICLE-ART-12 (010 Bulwark authored,
063 tanks re-detailed, 018 re-textured) 1155 textures, 9 missing, rebuilt and merged: 0.

**The chalk-white car (ptrx6): Remix kept the untinted half.** Both halves of a split car carry one merged whole-car
material (the paint texels near-white, tinted per car), and Remix keeps one of the two identical draws. It is usually
the paint half (tinted), but not always: in `out/fm5_parts_before` the forced 010 at 22:00 was chalk white in one pose
(the rest half kept: no tint) and red in the next. Under Remix the rest-half draw now takes the same tint factor
(`[devtools] remix_tint_rest`, default 1), so either draw is the car's paint. `out/fm5_rest1` (010/000/018 at 22:00 and
17:30, rest tint off/on per pose): identical frames, no regression; the white case did not occur in that session.

**Authored car parts (ptrmx20's flat pale hood stripe).** The carkit cars name a texture per part (`<car>_chrome.tga`,
`_tyre_tread`, `_underbody`, `_lamp_tail` ...) and their glTF materials carry no measured factors, so every part had
metallic 0 / roughness ~0.48 (264 textures, 71 hashes): the 018 Shark's chrome bonnet crease, bumpers, spears and hubs
path traced as flat pale-grey plastic. `remix_model_pbr.CAR_PART_CLASSES` sets them by name: chrome 1.0/0.14, bright
steel 1.0/0.24, wheel steel 0.9/0.32, dark iron 0.6/0.5, tyre tread 0/0.92, rubber 0/0.82, dark underbody/interior
0/0.62, seat 0/0.7, whitewall 0/0.5, lamp lenses 0/0.06 (no emission changed). Colour probe `out/fm5_probe1` (a layer
copy with the 018 chrome albedo magenta, whitewall green): bumper, flank spear, door handle and hubs magenta, the
whitewalls green, so the part prims key.

**Coverage after the 06:00 imports, and the plaza slab.** A `_underpan` texture added to every car, a re-textured
underbody and the new molotov weapon left 83 textures (5 hashes) without a prim; rebuilt (`underpan` joins the dark
underbody part class): 1220 textures of 279 models, 0 missing. The ste plaza slab at the filer's spot is lids
806/814/831: 831 took the CC0 asphalt micro-surface in 03e03d4, 806 has its own grain, 814 was featureless (grain RMS
0.0026 against 0.02-0.026), so a smooth square sat in the cracked slab; 814 joins `remix_micro_tiles.json` with 831's
class (asphalt, 0.9), and so does 806 (the rounded-corner slab: a smooth, banded interior, robust grain 0.0045).

**Mural residual at arm's length (pt-remix-graffiti-mural-wax-blob-relief).** A fixed regress-camera take facing the
rose window at ste 113.5,124.7, 09:00 (`gamerun/fm5_cam.py`, `out/fm5_ste1` before, `out/fm5_ste3` after): the
coloured pieces were already flat, but the cream pieces of tile 760 kept a lumpy skin. The upscaler painted bumps and
shadows into them, and the normals derived from that paint (12 % / 35 % in the mural region) raised them. Now
`remix_pbr.mural_albedo` pulls a pale piece's luminance towards the smooth luminance of the pale texels around it
(40 % of the detail kept, grout and coloured pieces untouched, layer albedo only), and the mural region's relief is
`MURAL_GAIN` 5 % / 15 %. After: flat cream paint; the stone course below keeps its relief. Left: the stain cluster
painted into the art still reads as a crust; colour edges are stair-stepped (upscaler art).


**One asphalt per road: undashed lids borrow the dashed lids' re-authored asphalt (FIX-REMIX-MATERIALS-6,
ptrmx26-remix-wil-day-third-road-lids-alternate-...-checkerboard).** The re-authored road paint
(`assets/textures_hd/roads/<style>`, the road lids' Remix albedo) exists only for the lids with markings: wil 20 of 38
road lids, bil 14 of 59, ste 22 of 43. A wil street is a 3 x 3 repeat of 275/277 (no dashes: the upscaler's smooth
blue-grey plane, grain 0.002) and 276/278 (dashes: cracked, mottled green asphalt, grain 0.026), so under Remix it
path-traced as alternating rows of two materials. Now `remix_materials.road_donors` gives each road lid without
re-authored art a donor (the re-authored lid of its style whose plain tile is closest in asphalt colour at 64 px,
paint and kerbs masked; used under a 0.07 difference: 18 wil, 45 bil, 18 ste lids), and
`remix_pbr.road_detail_albedo` builds the layer albedo: the lid keeps its own paint, kerbs and low frequencies,
shifted to the donor's mean asphalt colour, and takes the donor's detail (cracks, mottling: the ratio to its masked
blur, sigma 40 texels at 512 px; the donor's dashes are filled from its own detail a quarter tile away, so no halo).
`pbr.json` records `"albedo": "donor:roads/<style>/tile_NNNN.dds"`. A scan micro-surface (the pave fix) was tried
first and rejected: at the amplitude that matched the grain it read as dark cobbles beside the smooth dashed lid
(out/fm6_wil1). Every road lid now also takes the rain (`groundish` for ground "road": wet roughness on 140 road
prims, was 17 of these 81). bil 751's kerb stones lost a false metallic map. Layer only: the HD tiles (the keys)
are untouched; the plain renderer draws no layer. Under Remix the classic view's road lids take the same albedo.
Verified at the filer's pose (wil 164.5,149.5, 12:00 third and first, private HEAD stage, GPU 6): `out/fm6_wil3`
shot_270 against the filer's ptrmx26_wil shot_270: one cracked asphalt across the lids, a faint tone step left at
one lid edge. A first micro-surface attempt is `out/fm6_wil1` (rejected).

**Building into the worktree.** The shared checkout holds the layer's textures (ignored, 2.4 GB); a worktree has
none. Copy them once (`cp -r repo/package/rtx-remix/mods/gta2hd/textures /tmp/wt-<you>/package/rtx-remix/mods/gta2hd/`,
a real copy: the tools write textures in place and a hard link would write through), build classes into a scratch
layer and merge (`remix_materials.py - /tmp/scratch --dds-tiles ... --gmp-dir game/data --only-classed --classes road
--force`, `--wet-layer`, `remix_layer_merge.py /tmp/scratch <worktree layer> hashes.txt --tiles`), take it with
`PACKAGE=/tmp/wt-<you>/package gamerun/playtest_remix.sh ...`. Python with numpy, PIL and xxhash:
`/mnt/gta2/ab_work/venv/bin/python` (the vreg venv lacks xxhash).

**The police station's windows are glass to the path tracer (FIX-REMIX-MATERIALS-6, ptrmx30-remix-wil-day-third-stone-facade-
window-bays-...).** wil 704/705 (the arched bays at 198.5,178.5) have had their own repainted Remix maps since f6a819c
(`tools/fix_window_glass.py pbr`: `<hash>.<map>g.rtex.dds`), but those went through the map maker as a plain wall tile:
`analyse()` runs without `windows=True` (night windows are off: false positives), so the repainted pane was a matte
picture of glass, roughness 0.55-0.72 with the stone's relief, and path traced as a flat smeared grey slab. Now
`analyse(glass_mask=...)` takes curated panes: glass roughness (0.05), no structure or grain relief, and in the height
map the pane is set back behind its frame (the stone keeps its displacement); `pbr_tile` passes a 10th job element
and `fix_window_glass.py pbr` hands over its own pane mask. After (`out/fm6_sta1` shot_270 vs the filer's ptrmx30_wil
shot_270, 12:00 third): dark glass reflecting the street and sky, recessed behind the stone, no smear. Not mine: the
garbled "l n d l" marks on 705's sill and the pilaster blotches are in the HD tile itself (upscaler art, FIX-WORLD-10's
photo-set re-make; under Remix the layer albedo is that art). Other facade windows keep the plain wall class (a
curated list, like the iron rails, is the way to add more).

**Layer textures are not in git.** The play page mounts the shared `repo/package` and its ignored `textures/` folder;
a commit changes `mod.usda` / `mod_wet.usda` / `pbr.json`, but the DDS a commit refers to reach the play page only when
they are copied into that folder. Since this shift fixers never write the shared checkout: they leave the changed
DDS in `/mnt/gta2/gta2-linux/layer_deploy/<agent>/textures/` with a `deploy.sh` (unlink-first copy, as the merge tool
does) for the coordinator to run when the commit reaches the shared tree.

## The floor-pan slab under parked cars (FIX-REMIX-MATERIALS-7, 10 Nov 2026)

**ptrmx31** (bil car park at 155.5,141.5 z 4, third person): a hard-edged flat plate under and beyond the parked black
fastback, grey-green at 15:30 and brown at 06:30, with the axle and exhaust brass-gold at dawn.

**What it is.** A colour probe (a hard-linked copy of the shipped layer with only the shared `_underpan` prim's albedo
magenta and `_underbody` green, `PACKAGE=` on `gamerun/playtest_remix.sh`, out/fm7_bil1) turned the whole plate
magenta: it is VEHICLE-ART-13/14's floor pan. The car there is model 71 (Rumbler, `view: cars ... m71:155.50,141.50`).
The pan itself is not larger than the body in model space (all 64 pans inside their bodies' x/z extents), but it hangs
15-20 cm over the road (071: 0.39 of its flat area 15-20 cm up) and runs to within ~5 % of the bumpers; car bodies
draw with no culling, so from the raised third-person camera the pan's UPPER side shows past a shell's higher valance
by parallax. The plain renderer lights that back face from below, so there it reads as the car's shadow (plain twin
out/qa_fm7_plain1 at the same spot: no board); the path tracer lit it from the sky (the grey board) and from the
near-horizontal dawn sun (the brown board, and the "gold" axle, tank and exhaust boxes of the pan atlas). The 071's
metallic map is neutral (F0 151,151,153 on 2.8 % of texels): not a chrome tint.

**Fix (Remix-only, dll/src/car_bodies.cpp `PanSplitFor` / `RemixHullDraw`, from `drawHull`).** Under Remix each car
model with an `_underpan` mesh is split once into the body without the pan and the pan alone (derived models, like the
turret split); the pan is drawn opaque (Remix never culls alpha-tested draws) with `D3DCULL_CW`, which under
`rtx.enableCulling` (primary rays only) hides its upper side from the camera while it still shades the road in the
shadow rays. `[devtools] remix_underpan`: 3 default (cull CW), 2 cull CCW, 1 one draw as before, 0 no pan (live, same
session). The plain renderer and the classic view never reach the branch (`RemixApiAvailable()`).

Same-session A/B, own car forced to 071 at wil 198.5,188.4, fixed regress-camera poses, 06:30 and 15:30
(`gamerun/fm7_own.py` + `keys_fm7_own.sh` via `frm2_remix.sh`, `AB_SETS=u1:remix_underpan=1|u0:...|u2:...|u3:...`,
out/fm7_ab1): u1 and u2 show the hard grey slab past the rear bumper and along the sill; u3 has none, only a soft
shade on the paving under the car; u0 has no slab and less shade. Geometry note for VEHICLE-ART-15 beside its order:
pans whose lowest parts reach the tyre contact plane (067, 048, 035, 003, 001, 045, ... 071 at -0.5 cm) and a flat
pan that runs to the bumpers are still seen from low cameras on both renderers.

**Prims for VEHICLE-ART-15's authored cars (FIX-REMIX-MATERIALS-7).** 012 Cop Car, 013 Minx (kit re-author), 027 Ice-Cream
Van, 069 U-Jerk Truck (43 hashes) and 000 Romero (3): `remix_model_materials.py --pattern '^(012|013|027|069)_.*'` into a
scratch layer, `remix_layer_merge.py` with only the missing hashes (additions only); `remix_car_prim_check.py --pattern
'.*'` 0 missing. Path traced from three poses at 06:30 and 15:30 (out/fm7_v2): whole bodies, the police livery, whitewalls,
neutral chrome. 027 went back to its image-to-3D shell after (VEHICLE-ART-15 26726ea); its kit prims are inert until it returns.
The 124 DDS are in `layer_deploy/FIX-REMIX-MATERIALS-7/`.

**Split-pair tint under Remix takes the rest half too.** Both prims of a car's split pair carry one merged opaque albedo
(the duplicate-draw rule above), and the paint tint is the draw's stage-1 factor, so Remix multiplies the WHOLE merged
surface: the 071 Rumbler's white stripes (rest half) go as dark as its green paint (no stripes under Remix, stripes in the
plain view). A paint-path fix (note beside the pmzz order); not changed here.

## Sun-lit road exposure (FIX-REMIX-MATERIALS-7, prx1)

The road's layer albedo is already dark asphalt (linear 0.065-0.08, MATERIALS-6). Same-pose takes at bil 150.5,130.5,
09:00 and 13:00, third and first person (`playtest_remix.sh ... -e GTA2DX9_SCENE_NO_CAR=1`), road boxes measured in the
same frames (sun-lit patch / shade):

| run | change | 09:00 sun | 09:00 shade |
|---|---|---|---|
| fm7_prx_a | shipped (PsychoV, day cap 6.0, Yf target 0.18) | 203,207,177 | 113,127,116 |
| fm7_prx_b | AgX Punchy 1.15 | 203,209,184 | 149,167,158 (milky, flat: rejected) |
| fm7_prx_c | `remix_day_max_exposure_tenths=40` | 200,204,173 | 111,125,114 (the cap does not bind here) |
| fm7_prx_d | `rtx.autoExposure.targetAdaptedYf = 0.13` | 186,190,158 | 97,110,99 |

The runtime meters the geometric-mean Yf to 0.18; a street frame is mostly asphalt and shade, so the exposure climbed
until sun-lit road read cream. 0.13 is in `linux/docker/rtx_play.conf.extra` (the host's play page reads the workspace
copy `gamerun/rtx_play.conf.extra`: installed by the deploy bundle). 21:00 at the same point stays a night (cap-bound).
Left: the warm 09:00 sun still tints the sun-lit asphalt (B 158 vs R 186); the filer's 234,230,212 frame (more shade in
view) would land near 215; untested on wil/ste and in rain.

## Glowing red cars were a layer without its textures; emission only on lamp parts (FIX-REMIX-MATERIALS-8, 10 Nov 2026)

**prx4** (red and orange trucks, vans and a bike path-traced as flat cream-peach silhouettes casting a red pool on the road,
day and night) was the filer's harness, not the shipped layer. Its take passed `PACKAGE=<a git worktree>/package`, and the
layer's DDS are git-ignored, so the runner installed the layer with **0 textures** (`run.log`: `gta2hd material mod
installed ... (0 textures, 3694 materials)`). Remix then drew every world tile a flat default grey, and every prim with
`enable_emission = 1` emitted over its whole surface, because its emissive mask had not loaded. Those prims are the
image-to-3D atlases with baked tail lamps: 063_truck_cab_0, 068_van_0 and 036's body paint. Their real masks light
0.1-0.3 % of the texels.

Proof on one private HEAD stage. The own car was forced to 063 (paint 121,63,48) and 068 (200,60,50), filmed from fixed
regress-camera poses at 13:00 and 22:00 with `gamerun/fm7_own.py` via `frm2_remix.sh`:
- With the shared layer (14352 DDS, `fm8_ab1`), both are shaded paint with chrome and dark wheels. At night they are
  lit only by the lamp post.
- With the same layer minus its `textures/` folder (`fm8_notex`), both are flat cream-peach emitters with a red bloom on
  the floor, in a grey world: the filer's frames.

Take Remix A/Bs with `PACKAGE=` the shared `repo/package` or a hard-linked copy of it, never a bare worktree package. A
guard in the runner for "0 textures" is the harness owner's to add.

**The paint factor keeps no 2X.** A probe build added `remix_tint_mode` 9 (no stage-1 factor) beside the shipped mode 1
(not committed). At paint 207,207,207 on the 063 (tint ~1), modes 1 and 9 render the same brightness, so Remix multiplies
by the sRGB-decoded factor without MODULATE2X's doubling. Mode 1 therefore never pushes a paint's albedo over 1.

**Emission only on parts that are lamps.** `remix_model_pbr.car_trim_maps`' red-island tail-lamp detector is meant for the
image-to-3D atlases (`<car>_N.tga`, `<car>_N_paint.tga`). It also ran on the carkit cars' named part textures, so
VEHICLE-ART-16's 027 waffle-cone texture came out 11 % emissive at intensity 6, and the paint box had emission switched on
over a black mask. That box would glow whole if its mask ever failed to load, exactly as in prx4.

Now an authored part texture (`authored_part()`: `<NNN>_<car>_<part>.tga`, not an atlas) emits only when its name matches
`EMIT_NAME` (lamp, lens, sign, bulb, ...). The audit of the shipped layer found no non-lamp authored part with emission.

**Prims for VEHICLE-ART-16** (014 Eddy, 027 Ice-Cream Van kit re-add, 046 Stinger, 062 Trance-Am) and the electro gun:
31 textures, 25 hashes. Built with `remix_model_materials.py --pattern '^(014|027|046|062)_.*|^weapon_electro_gun.*'`
into a scratch layer, whose `mod_wet.usda` must be a copy of its new `mod.usda` or the merge skips the wet layer, then
merged with `remix_layer_merge.py` (missing hashes only). `remix_car_prim_check.py --pattern '.*'`: 1352 textures of
279 models, 0 missing. The 67 new DDS are in `layer_deploy/FIX-REMIX-MATERIALS-8/`.

**Car glass prims missing (prxq, prx6).** The three prims VEHICLE-GLASS-2 handed over for the Remix pane and cabin
textures (`0x00E7B4E949140568`, `0x52573041E54EEEB7`, `0x92AE80C504938232`, docs/car-glass.md 5.1) never reached the
layer. Every generated car's panes therefore path-trace with the legacy material of the pale fixed pane texture: flat
pale cards with no reflection or interior. FIX-REMIX-GLASS lands them (prx6).

**The atom sign plates (prx2, the material half; FIX-REMIX-NIGHT-7 did the night floodlight in 63f3b23).** wil tiles 62
and 63 (prims `7E4E69870C5A49E8`, `AF5F853C37E57832`; the photo set is off under Remix) are flat rooftop sign plates.
They had been classed as plain wall tiles: a matte pale-silver plate (about 200,205,215, roughness 0.8) that the street
exposure clipped to a cream decal at noon, and no light of their own at night.

`tools/remix_sign_plates.py <layer> <hd tile.dds> ... --apply` now gives each plate:
- painted sheet metal: albedo pulled down to 150 at the plate's brightest texels, metallic 0.55, roughness 0.38;
- an emissive mask on the saturated strokes (the yellow orbits, 14 % of the texels) in their own colour at intensity 4.

Fixed regress cameras at wil 167.0,21.0 and 169.0,24.0 looking at the disc, 12:00 and 20:00, with
`[devtools] remix_sign_flood_pct` 0/100 in each session (`gamerun/fm8_sign.py`). Before = shared layer (`fm8_sign0`),
after = candidate layer (`fm8_sign1`):
- **Noon:** a silver plate carrying the sky's gradients, with vivid yellow orbits instead of a cream clip.
- **20:00:** the orbits glow as yellow neon whether or not the floodlight is on. With it on, the plate shows faintly
  behind them. The two do not overpower each other, so the floodlight's strength was left alone.

Under Remix the classic view sees the same prims from above. The plain renderer draws no layer.

Tile 61 (FUTURO RADIO) is not changed. The blur of the disc art is the 512 px HD tile's own resolution (a world-art item).
Deploy the bundle together with this commit: until the plates' `.e.rtex.dds` exist, their emission has no mask and the
whole plate would glow.

## The green "lawn" is a steel roof: class corr (FIX-REMIX-MATERIALS-9, 10 Nov 2026)

prxr1 filed the green slabs at wil 203.5,237.5 as a lawn that read as a corrugated roof, with dark grooves and shadow stripes
across it. The slab is wil tile **108**, and it is a roof. Its 901 lids sit at levels 4-6 (none at street level), many on
roof slopes (45° and ramp slopes), inside grey parapet rims on the industrial sheds. Its tile neighbours 107-124 are roof
panels, and no map tree block (slopes 49-52) stands on it. GTA2 types it "field", as it does many roofs, so REMIX-MATERIALS
put it in `VEG_LIFT` and lifted it to a bright lawn green. The trees and lamp on the slab are the renderer's rule props, not
the map's own trees.

The 64 px art is a box-profile sheet: 11 ribs across the 4 m tile (about 36 cm pitch), dark 2-3 px bands between
3-4 px pans, with rust drips under the fixings. The upscaler drew each band as a pair of thin black lines. `analyse()` then
made those lines grooves in the normal (tilt p90 29°), so path traced the roof was a field of black hairlines, each with a
dark groove beside it. The plain street views draw the photo set's `photo/wil/tile_0108.dds`, which is the same corrugated
green sheet with dark lines: that look is the world seat's.

**Class `corr`** (`remix_pbr.CORRUGATED`: wil 108 and its edge tile 121; 111 and 123 are mostly black gutter and stay as they
were). `remix_pbr.corrugated()` builds the layer's maps:
- **Albedo:** a horizontal grey closing (19 texels, capped at 1.15x the local paint) fills the hairlines, the column profile
  of the baked rib shading is divided out, and half of the upscaler's 2-12 texel leaf-vein smudge band is removed. The
  drips and grime stay. The lawn lift is gone, so the albedo is the art's own darker paint green.
- **Normal:** the ribs are geometry. They are raised trapezoids wherever the art has its dark bands, read from the HD
  tile's smoothed column profile, with flanks of about 40° over about 6 texels (`CORR_GAIN`). The paint keeps only a faint
  grain.
- **Roughness and metal:** satin painted steel (0.40-0.72, rougher in grime) and no metal map (paint is a dielectric).

Build and merge:

    $P tools/remix_materials.py - <scratch>/gta2hd --dds-tiles repo/assets/textures_hd/wil --size 512 --map-size 256 \
        --gmp-dir game/data --only-classed --classes corr --force
    $P tools/remix_materials.py - <scratch>/gta2hd --wet-layer
    $P tools/remix_layer_merge.py <scratch>/gta2hd <layer> <hashes> --tiles      # A2E4F888C9C6C552, 3D5D2D88FD953D80

`mod.usda` is unchanged by this. `pbr.json` gets `ground: corr` for both hashes. The six DDS are in
`layer_deploy/FIX-REMIX-MATERIALS-9/`.

**Seen path traced** (GPU 4, `playtest_remix.sh` at the filer's point, REMIX_NVCACHE=1, `GTA2DX9_SCENE_NO_CAR=1`). Before
is `fm9_corr0` (the shared layer); after is `fm9_corr1` (`MODS_HD_SRC` = the shared layer with these prims merged):
- **10:00, third person, same pose:** before, bright lawn green crossed by dark hairlines, each with a groove shadow, plus pale
  leaf-worm smudges. After, a clean painted sheet with soft ribs and paint mottling: no hairlines, no smudges, no stripes.
- **17:00:** the after take's camera faced the ridge, not the before take's heading. It shows a pitched roof reading as
  box-profile steel, with the sunlit rib flanks catching the low sun.

Still short: the trees and lamp standing on a shed roof (rule props on a field-typed roof lid, props seat). The art's
own rib pitch is uneven (5-6 px at 64 px), which an authored roof would not be.

## Police-station facade: the sill pseudo-lettering and the transom blobs (FIX-REMIX-MATERIALS-9, ptrmx30 layer half)

The arcade wall at wil 198.5,178.5 is wil 704 (arch heads) over 705 (lower halves and sills), the building's south face at
y = 178. FIX-REMIX-MATERIALS-6 made its panes glass (`fix_window_glass.py pbr`, the `.<map>g` maps). Two things in the
Remix albedo were still the upscaler's: the "l d l" pseudo-lettering on every sill block and the "| |" marks on the lower
band (705), and one teal glyph blob per bay at the transom that the pane repaint missed (704). The plain views draw the
photo set, whose sills are clean, but its stone is darker and greener than the HD tile's, so pasting it in would seam
against the neighbouring HD tiles.

`fix_window_glass.py pbr <tile> <mod> --deglyph` (`deglyph()`), applied after the pane repaint:
- **Strokes:** thin dark strokes are what a 13-texel grey closing lifts by more than 0.025. Strokes reaching 48 texels in
  extent are mortar lines, block edges and cornices, and stay. The rest are filled from the closing.
- **Blobs:** a small bright blob on the glass (centre inside a pane's box, below its arch head, under 120 texels) is filled
  from a grey opening, and added to the pane mask, so the path tracer sees glass there and not a matte stone patch.

The stone keeps the HD tile's own tone. Rebuild, for the two hashes 27C431EAEC34DB64 (704) and E9521A60228584F9 (705),
into the layer's `textures/` as new `.<map>g` files (mod.usda already points at them):

    $P tools/fix_window_glass.py pbr repo/assets/textures_hd/wil/tile_0704.dds <layer> --deglyph
    $P tools/fix_window_glass.py pbr repo/assets/textures_hd/wil/tile_0705.dds <layer> --deglyph

**Seen path traced** with fixed cameras on the south face (`keys_fm8_sign.sh`, `CAMS=wall:203.5 182.5 2.5 203.5 178.0 2.9 55;
sill:202.2 180.2 2.3 202.6 178.0 2.45 45;...`, 12:00). Before is `fm9_p30a` (the shared layer), after is `fm9_p30c`:
- **Sills and lower band:** the pseudo-lettering on the sills and the band marks are gone; the stone and mortar are
  unchanged.
- **Transom blobs:** gone in `fm9_p30d`. Two earlier builds failed: in `fm9_p30b` (blob not yet in the glass mask) they
  were grey ghosts; in `fm9_p30c` (a colour test also took teal-tinted stone) the pilaster edges turned to glass and showed
  bright chips. A blob now joins the glass only when at least 60 % of a 4-texel ring round it is pane.

Still short: the HD tile's stone is the upscaler's soft, blotchy render, and the panes are a painted glass gradient with
no interior behind them. An authored facade with modelled reveals is the AAA answer.

## Near-black shaded walls: de-lit wall albedo (FIX-REMIX-MATERIALS-9, prx10)

prx10 filed ste walls in sun-shade at luma 11-19 beside a shaded road at 70. I identified the cause with a colour probe at
the filer's point (130.5,60.5, 16:30): `gamerun/fm9_probe`, the shared layer with all 229 ste tiles of the area given one
flat sRGB 0.5 albedo. In that frame the shaded wall read 86 and the shaded road 72, so vertical faces do get the sky and the
bounce. The light state is fine; the walls' albedo is the cause.

The game's wall art is drawn for an unlit screen, with its shading baked in:
- the ste plank and rendered facades (`FLAT_WALL` 160-178) average linear albedo 0.05-0.07, where painted timber and
  render are 0.2-0.4;
- ste 556, the slate rubble wall under the elevated railway, averages 0.068 (dark slate is 0.10-0.12), and its relief and
  parallax height were made from the albedo's baked dark crevices (normal tilt p50 24°).

`remix_pbr.delit_albedo` scales a tile's linear albedo up to a floor, keeping the texture's own contrast and hue, at most
3x, with highlights soft-clipped at 0.6. Classes:

| class | tiles | floor | relief | metal |
|---|---|---|---|---|
| flat | the 18 `FLAT_WALL` tiles | 0.15 | as before (0.12 / 0.35) | none (the de-lit 167 tripped the detector on its window frames) |
| delit | `DELIT_WALL`: ste 556 | 0.13 | `GROUND_GAIN["delit"]` 0.35 / 0.5, no parallax height | none |

The list is curated, like `VEG_LIFT`: of 967 opaque wall tiles, 267 sit under linear 0.08, and dark glass, black iron, sign
plates and soot are meant to be dark. Build: `remix_materials.py ... --dds-tiles repo/assets/textures_hd/ste --only-classed
--classes flat,delit`, then `remix_layer_merge.py --tiles`.

**Seen path traced** with fixed cameras west of the filer's point (`keys_fm8_sign.sh`, warp 128.5,62.5;
`CAMS=plank:127.5 60.5 2.6 131.0 59.5 2.7 60;slate:127.0 66.0 2.4 131.0 65.0 2.4 60;wide:123.5 62.5 2.8 131.0 62.0 2.6 65`,
9:00 and 16:30). Before is `fm9_p10c`, after is `fm9_p10d`. Median luma (`fm9/p10_measure.py`):

| frame | wall before | wall after | road (shade or sun) |
|---|---|---|---|
| 16:30 slate wall in shade | 21.5 | 66.8 | 66 (shade) |
| 9:00 slate wall | 37.6 | 87.3 | 240 (sun) |
| 9:00 plank arcade in shade | 58.5 | 91.1 | 64-67 |
| 16:30 wide, slate at the right | 10.0 | 28.1 | 66-67 |

Before, the slate read as a black cut-out. After, it is grey-blue rubble with its stones readable in shade, and the planks
are a lighter tan. The wide frame's slate region also takes in the dark lattice and the deck's shadow.

Still short:
- **The black slab:** a near-black slab with dithered edges hangs close to the slate camera, the "black parallelogram" of the
  report. It is not one of these wall tiles; most likely it is the dark iron lattice (ste 563, a cut-out at sRGB 0.09) seen
  at grazing angle. Not treated.
- **Other dark walls:** every other dark wall tile in the three districts keeps its baked albedo.
- **The verified layer:** the take's layer still had a metal map on tile 167, which the final build drops.
