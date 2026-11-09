# assets/

`manifest.json` is the import manifest (paths are relative to the folder it was run from, which
held the source kits: Poly Haven models, CC0; the Rocketbox avatars; the generated cars). The
Kenney starter-kit vehicles that once stood in for every car are gone. `models/` is what `tools/import_assets.py` produced from it and what the build ships as
`gta2dx9_models/` beside the game. Regenerate with:

    python3 tools/import_assets.py <folder with the kits>/manifest.json assets/models

## Pedestrians: Microsoft Rocketbox avatars (MIT)

The `human_*` models are adults from the Microsoft Rocketbox avatar library
(github.com/microsoft/Microsoft-Rocketbox, MIT licence, Copyright (c) Microsoft Corporation):

| model | Rocketbox avatar | textures |
|---|---|---|
| human_male_01 | Male_Adult_01 | m002_body/head/opacity |
| human_male_04 | Male_Adult_04 | m006_body/head/opacity |
| human_male_07 | Male_Adult_07 | m013_body/head/opacity |
| human_male_10 | Male_Adult_10 | m024_body/head/opacity |
| human_male_13 | Male_Adult_13 | m010_body/head |
| human_female_01 | Female_Adult_01 | f001_body/head/opacity |
| human_female_03 | Female_Adult_03 | f003_body/head/opacity |
| human_female_05 | Female_Adult_05 | f005_body/head/opacity |
| human_female_08 | Female_Adult_08 | f008_body/head/opacity |

Since 6 Nov 2026 there are 41 avatars (`assets-src/humans/make_ped_manifest.py` writes their
manifest entries from whatever `assets-src/humans/rocketbox/` holds; `fetch_rocketbox_pro.sh
<Adults|Professions> <name>...` fetches more). The extra ones, all from the same MIT library:
Adults Male 02/05/08/11/16 and Female 02/06/10/13 (civilians); Professions Police_Male_01-03 and
Police_Female_01, Military_Male_01/02 and Military_Female_01, Fire_Male_01/02 and Fire_Female_01,
Medical_Male_01/02 and Medical_Female_01/02, Business_Male_01-03 and Business_Female_01,
Construction_Male_01/02, Security_Male_01, Sports_Male_01 and Sports_Female_01 (`human_<folder>`
in lower case). Since 9 Nov 2026 (ASSET-PEDS, `docs/ped-identity.md`) 59, also from the same MIT
library: Adults Male 06/09/12/18/20 and Female 04/12/17; Professions Police_Male_04,
Security_Female_01, Business_Male_04-07, Medical_Male_04, Sports_Male_04, Fire_Male_03 and
Construction_Male_05.

### Pedestrian types

GTA2 tells its pedestrians apart only by the remap palette of the one shared sprite set: DMA's
own table (`assets-src/humans/pedtypes/ped_types.json`, from the GTA2 scripting documentation)
has 0-3 police, 4 army, 5-6 rednecks, 7 scientist, 8 Zaibatsu, 9 Hare Krishna, 10 Russian
mafia, 11 Loony, 12 Elvis, 13 Yakuza, 14 fireman, 16 medic, 17 mugger, 22 prisoner, 25 the
player and the rest civilian outfits by colour. The renderer recovers the remap from the physical
palette the game registered the ped's texture with (the style's PALX for the PALB `ped_remap`
slots, `Style::PedRemapPalette`), and the manifest's `ped_types` says which avatars each remap
draws. Since ASSET-PEDS (9 Nov 2026, `docs/ped-identity.md`) every type wears its sprite's own
outfit: `tools/ped_sprite_outfits.py` reads each remap's shirt, forearm, trouser, shin, hair and
skin colours from the style's palettes (`assets-src/humans/pedtypes/outfits.json`), the avatar is
chosen for the sprite's silhouette (short sleeves, shorts, a shaved head, a uniform, a suit), and
the importer's `ped_zones` splits a casual avatar's clothes into a top and a bottom zone (by the
bone weights of each UV island) made neutral grey, which the renderer tints to the manifest's
`ped_outfits` (top, bottom and, where the sprite says so, hair). Uniforms and suits that already
match (police, army, Zaibatsu, Yakuza, SWAT) keep their own textures. The SWAT/FBI sprite set
(`EMERG_GRAPHIC`, no remap) is drawn as type 53 (tactical kit), the Zaibatsu set (`GANG_GRAPHIC`)
as remap 8.

Each has the library's `walk_neutral` and `idle_breathe` animations merged in by joint name (the
skeleton is the same Bip01 rig in every avatar; the walk's root motion is stripped and its ground
travel per cycle recorded as `stride`, so the feet match the ground covered). The FBX files were
converted to glTF with FBX2glTF 0.9.7 (BSD-3-Clause, github.com/facebookincubator/FBX2glTF);
`assets-src/humans/fetch_rocketbox.sh` fetches and converts an avatar. The source kit lives in
`assets-src/humans/` next to this repository, not in it. Textures are reduced to 512 px to keep
the 32-bit game's memory modest (about 3 MB per avatar). The models are skinned (GMSH v2: per-
vertex joints and weights, skins with inverse bind matrices) and posed on the CPU by
`dll/src/model_store.cpp`; they face +Z. The manifest's `pedestrians` list is the set a pedestrian
is drawn from, chosen by a hash of his game object so he keeps his look.

## Cars: one model per GTA2 vehicle, repainted from the live sprite

GTA2 draws 83 vehicle models (the style file's CARI chunk; `assets-src/cars/catalog.json`
lists them with their sprites, wheel and window rows and the paint of every remap). Each
vehicle gets a 3D model of its own under `NNN_name` (`000_romero`, `056_taxi`, ...), generated
by the car pipeline in `assets-src/cars/`: image-to-3D reconstructions of period-correct
designs (`models3d/`, one baked texture each) first, and parametric period bodies with the
game's own sprite on the roof (`models_proc/`) for the models the first set lacks; the Nexar
fork generated these from the game's artwork, no third-party car models are redistributed.
`tools/make_car_manifest.py` writes their entries and the `cars.by_model` map (the AI set as
`paint_split` entries, the parametric set with `paint_materials`), then
`tools/import_assets.py` converts them. For a `paint_split` model the importer finds the
paint in the baked texture by hue and saturation against the car's default sprite paint,
writes it as a second `_paint` texture (alpha-masked) and emits the mesh twice, so only the
paint is recoloured in the game; `paint_rgb` stays the default sprite's paint, which makes
the live tint 1 for an unpainted car and the game's own remap ratio otherwise.

At run time (`dll/src/car_bodies.cpp`, `[renderer] car_models3d`, on by default) the renderer reads
each vehicle's model number from the game, looks it up in `cars.by_model` (`by_sprite` as a
fallback), scales the model to the sprite's footprint and stands it on the road with the
vehicle's own heading; meshes whose texture is marked `_paint` are multiplied by the ratio of
the car's live paint (measured from the sprite the game is drawing, remap included) to the
model's own `paint_rgb`, so every repaint in traffic keeps its colour. A vehicle no model
names is built from its sprite instead: the outline extruded into a body, the windows and
wheels where CARI says, the sprite itself on the roof. Beyond 20 blocks a car keeps its flat
sprite. In first person at the wheel the player's own car is drawn too, clipped just below
the driver's eye (the models are solid hulls), so the hood and cowl frame the road. The
classic top-down view never uses any of this. Memory: the log line `car models: N textures,
X MB` every 900 frames reports the managed-pool use (about 1 MB per car texture at 512).

Limits: keep a car under 12000 vertices (the importer splits larger meshes) and its textures
at 512 (set per entry with `texture_max`); the game is a 32-bit process.

## Map objects: the game's own objects as models

GTA2's scripts place objects from the style file's OBJI table (24 models, 90 sprite frames:
benches, tyres, cones, crates, a football, oil drums, sandbags, sawhorse barriers, the yellow
bonus crates...). The street-level views draw them as models whose top-down look is the sprite
itself; the classic view keeps the sprites. `tools/gen_objects.py` makes them from
`assets-src/objects/` (every object sprite exported from the style with
`assets-src/cars/parse_sty.py`, plus Real-ESRGAN x4 copies) and writes `assets-src/objects/models/`,
a status file, a contact sheet and the manifest's `objects` map
(`"<sprite base>:<frame>": model`; map objects are sprite base 5). Frames that are flat things
on the ground (litter, newspapers, oil, splintered wood, hubcaps) are left as the game's sprites.

| model | frames | body | source |
|---|---|---|---|
| obj_bench | 0-7 | park bench, tinted to the sprite's green | Poly Haven `painted_wooden_bench` (CC0) |
| obj_tyre | 8-17 | tyre lying flat | Poly Haven `old_tyre` (CC0) |
| obj_girder | 21 | riveted steel plate | procedural, sprite on top |
| obj_planter | 24-27 | clay planter, bush and flowers | Poly Haven `planter_pot_clay` (CC0) + procedural foliage |
| obj_cone, obj_cone_lying | 28, 29-31 | traffic cone, standing / knocked over | procedural |
| obj_crate | 32-33 | pine crate, plank sides with nails | procedural, sprite on top |
| obj_football | 38-42 | football | procedural |
| obj_box | 43-47 | cardboard box | procedural, sprite on top |
| obj_extinguisher | 48-54 | fire extinguisher on its side | procedural |
| obj_drum, obj_drum_lying | 67, 68-70 | steel oil drum, upright / on its side | Poly Haven `barrel_03` (CC0) |
| obj_sandbag | 71-75 | sack, tinted to the sprite | Poly Haven `cement_bag` (CC0) |
| obj_barrier | 76-83 | road-works sawhorse, striped | procedural |
| obj_crate_yellow | 88 | yellow hazard crate with black straps | procedural, sprite on top |

Poly Haven models are CC0 (`assets-src/polyhaven/LICENSE.txt`), fetched 1k with
`assets-src/polyhaven/fetch_polyhaven.py`, scaled to blocks (2 m = 1 block), reoriented with the
long axis along +Z and the origin at the footprint centre on the ground; where the sprite's paint
differs from the model's, the texture is multiplied toward the sprite's dominant colour
(`MATCH` in the generator). At run time (`dll/src/map_objects.cpp`) a sprite whose base and
frame are in `objects` is not drawn as a quad; the model is scaled so its long axis spans the
quad's longer edge, turned to the quad, and stood on the quad's plane. Every new object sprite
seen (base, frame, size) is logged once as `object sprite: ...`, which is how the map is extended.

### Slim street props (rule props: lamp, hydrant, bin)

The rule-placed street furniture is drawn by the dozen (`DrawProps` in `dll/src/live_geometry.cpp`:
a post under every map lamp, up to ~35 lamps in a street view), so its three Poly Haven (CC0)
scans are rebuilt by `tools/gen_objects.py` (`SLIM_PROPS`: `build_hydrant`, `build_bin`,
`build_lamp`) as low-poly surfaces of revolution about their own axes, with the scan's colour and
relief baked into one 512 px atlas, and written to `objects/models/<name>.glb`, which the import
manifest's `street_lamp`, `fire_hydrant` and `trash_can` entries point at:

| model | scan | before (drawn triangles) | after | textures |
|---|---|---|---|---|
| street_lamp | `street_lamp_01` | 30 610 | 1 656 (post lathe, cross-bar lathe, 4 lantern posts, bulb on the atlas; the scan's glass kept) | `street_lamp_0` atlas, `street_lamp_1` glass |
| fire_hydrant | `fire_hydrant` (no `_aged` variant) | 43 000 | 1 184 | `fire_hydrant_0` atlas |
| trash_can | `metal_trash_can` (no `_rust` variant) | 6 400 | 772 | `trash_can_0` atlas |

Regenerate: `gen_objects.py <assets-src> <assets-src>/objects/models --props-sheet <png>` (the
`gen3d` venv), then `import_assets.py <assets-src>/manifest.json assets/models --only
street_lamp,fire_hydrant,trash_can`. The atlases are CC0-derived (no game art) and committed.
Evidence and the in-game count: `docs/props-slim.md`.

### Pedestrian action clips

Besides the walk, run and idles, every avatar carries `getin`/`getout` (Rocketbox `m_crouch_in`/
`m_crouch_out`, MIT, root motion stripped) and five procedural clips written by
`tools/gen_ped_clips.py` into `assets-src/humans/clips/ped_clips.json` (`punch`, `aim`, `handsup`,
`fall` held lying, `hit`): key poses as rotations about the avatar's own axes over the idle's
first frame, resolved into joint rotations on the Biped skeleton, merged by joint name through the
manifest's `animations_json`. The renderer picks the clip from the game's own animation frame and
state words (`assets-src/humans/ped_states.json` lists the frame ranges and how each was measured).

## Park trees (procedural, no third-party content)

`tree_01..03` are generated by `tools/gen_trees.py` (trimesh + PIL in the `gen3d` venv): a
tapered trunk with four branches, a canopy of three crossed vertical cards and two tilted
horizontal ones, bark and leaf-cluster sheets drawn procedurally (512 px, alpha cutout; 84
triangles each). The manifest's `props` map names them `tree1`..`tree3`; `DrawProps`
(dll/src/live_geometry.cpp) stands one on every fourth grass cell whose four neighbours are
grass at the same height (a lawn, never a verge, a grass-topped roof or a plaza), 2.0 to 3.2
blocks tall by a hash of the cell. Grass is any style tile that is green-dominant with little
blue (`SetGrassTiles`, computed at level load in world_view.cpp; the water tiles are excluded).
Regenerate: `gen3d/venv/bin/python tools/gen_trees.py ../assets-src/trees` then import with the
manifest. Note the `props` block is now read generically, so any new role works.

## Street furniture, docks, rooftops (tools/gen_env2.py)

Procedural, no third-party content: `sign_stop`, `sign_oneway`, `bus_shelter`, `parking_meter`,
`mailbox`, `container_1..4`, `crane`, `roof_ac`, `roof_vent`, `water_tower`, `rail` (one block of
elevated track with its side girders). GTA2's palette (dark teal steel, mustard, rust, chrome).
Placed by rule in `DrawProps` (dll/src/live_geometry.cpp): stop signs on one corner of a
junction, one-way signs and parking meters along the kerb, mailboxes against buildings,
shelters beside the map's bus-stop zones, containers and cranes along quays (a lid with
water beside it), rail on the track tiles reached from the "trak" zones (style tiles 572 in
Industrial, 553/562/563/565 in Residential; Downtown has no elevated rail), roof units and
water towers on flat roofs above the street. Sizes are at the figures' scale (an adult 0.46 block, so
1 m is about 0.26 block; the mailbox is 0.305 block, see docs/prop-collision.md); never name a material
`body` or `paint` here (import_assets.py treats it as car paint and keeps its first `_paint` copy). Regenerate:

    python3 tools/gen_env2.py ../assets-src/env2 --sheet out/env2_models_sheet.png
    python3 tools/import_assets.py ../assets-src/manifest.json assets/models --only sign_stop,sign_oneway,bus_shelter,parking_meter,mailbox,container_1,container_2,container_3,container_4,crane,roof_ac,roof_vent,water_tower,rail

Window glow (`[renderer] window_glow`, src/renderer.cpp `MakeWindowGlow`): wall tiles whose
dark, cool-toned panes cover a twelfth to two thirds of the tile get a warm room-light
texture added over them in the street views when the sun is low (nothing at noon, never in
the classic view); some panes stay dark. Found from the tile pixels at level load, no files.

## Regenerated models and their textures

`tools/import_assets.py` writes a model's textures beside its mesh and used to keep an
existing TGA for ever. A model regenerated with its materials in another order (the pay
phone after `gen_code_objects.py` changed; the three re-made cars) was then drawn with
the old pictures on the new meshes: the phone came out as a blue slab with the sprite on
its end. A texture is now rewritten whenever the glb is newer than it; 99 models were
re-imported that way on 7 Nov.

## Fonts (modern HUD)

`assets/fonts/BarlowCondensed-{ExtraBoldItalic,BoldItalic,SemiBold}-hud.ttf`: Barlow
Condensed by Jeremy Tribby (github.com/jpt/barlow, fetched from github.com/google/fonts),
SIL Open Font License 1.1 (`assets/fonts/OFL-BarlowCondensed.txt`; no Reserved Font Name),
subset to Latin-1 with fontTools. Embedded in the DLL by `tools/gen_hud_font.py`
(`dll/src/hud3d_font.inc`); see `docs/hud.md`.

### Mocap locomotion (QB-20, 9 Nov 2026)
Walks, runs, fast runs, starts, stops, idles and fidgets from the Rocketbox animation library
(github.com/microsoft/Microsoft-Rocketbox, `Assets/Animations`, MIT, Copyright (c) Microsoft Corporation),
fetched into `assets-src/humans/rocketbox/anim_loco/`, men's clips on the male avatars and women's on the
female ones, retargeted on import (rotations and root motion only; `tools/locomotion_meta.py`). See
docs/actions-3d.md "QB-20/21/39".

## Photo-material tiles (ASSET-BUILDINGS)

`tools/photoreal_tiles.py` adds the surface of real photo-scanned materials to the HD tiles
(`assets/textures_hd/photo/<style>/`, not in git: it embeds the game's art and ships in the
textures archive). Materials from ambientCG (ambientcg.com), CC0 1.0: Plaster001,
PaintedPlaster017, Concrete031, Concrete034, Concrete044A, PaintedMetal004, PaintedMetal009,
Metal012, Wood067, Marble012, Asphalt026B, Ground054, Grass004, Gravel022 (2K JPG colour and
displacement; fetched by `photoreal_tiles.py fetch`). The material classes come from
Qwen3-VL-8B-Instruct (Apache-2.0), run offline. See docs/photoreal-tiles.md.
After a `build`, `tools/railing_metal_tiles.py assets/textures_hd assets/textures_hd/photo` rewrites the
near-black Downtown spear fence (wil 635) as dark grey painted iron (pm5; no third-party input).
