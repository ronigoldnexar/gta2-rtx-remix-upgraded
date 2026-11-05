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
by the car pipeline in `assets-src/cars/` (parametric period bodies with the game's own sprite
on the roof, `models_proc/`, or image-to-3D reconstructions, `models3d/`); the Nexar fork
generated these from the game's artwork, no third-party car models are redistributed.
`tools/make_car_manifest.py` writes their entries and the `cars.by_model` map, then
`tools/import_assets.py` converts them.

At run time (`dll/src/car_bodies.cpp`, on when `[renderer] car_models3d=1`) the renderer reads
each vehicle's model number from the game, looks it up in `cars.by_model` (`by_sprite` as a
fallback), scales the model to the sprite's footprint and stands it on the road with the
vehicle's own heading; meshes whose texture is marked `_paint` are multiplied by the ratio of
the car's live paint (measured from the sprite the game is drawing, remap included) to the
model's own `paint_rgb`, so every repaint in traffic keeps its colour. A vehicle no model
names is built from its sprite instead: the outline extruded into a body, the windows and
wheels where CARI says, the sprite itself on the roof. Beyond 20 blocks a car keeps its flat
sprite. The classic top-down view never uses any of this.

Limits: keep a car under 12000 vertices (the importer splits larger meshes) and its textures
at 512 (set per entry with `texture_max`); the game is a 32-bit process.
