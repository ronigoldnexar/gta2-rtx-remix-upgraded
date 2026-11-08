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
