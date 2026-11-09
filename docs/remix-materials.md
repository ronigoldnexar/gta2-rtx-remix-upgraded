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

    MOD=gamerun/remix_vis/gta2hd JOBS=3 bash repo/linux/docker/build_remix_mod.sh   # a private copy
    bash repo/linux/docker/build_remix_mod.sh                                         # the package layer
    ZIP=1 bash repo/linux/docker/build_remix_mod.sh                                   # + the release zip
    python3 repo/tools/remix_pbr.py preview <out.png> <tile.dds> ...                 # maps of some tiles

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
