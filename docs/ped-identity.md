# Pedestrians as the GTA2 originals (ASSET-PEDS, 9 Nov 2026)

Goal: every pedestrian type in the street views is a photoreal person, yet you can still tell
which GTA2 type it is from the sprite. That means the same gang, the same clothing colours,
the same sleeves and shorts, the same hair where the sprite shows it, and a uniform where the
game has one. This builds on CROWD (`56eaab5`: own builds, heads that follow the player).

## What GTA2 actually says about a ped

All the remapped types share one sprite body (frames 0-157 of the ped sprites). DMA's types are
53 remap palettes of that body. The SWAT/FBI and Zaibatsu types instead use their own sprite
sets: `EMERG_GRAPHIC` (frames 316-473) and `GANG_GRAPHIC` (158-315). The body's palette
indices map to body parts, which I found by colour-coding the indices on the full-body frames:

| indices | part |
|---|---|
| 74-86 | torso (shirt) |
| 224-232 | forearms (a sleeve, or bare skin = short sleeves) |
| 206-212 | thighs (trousers) |
| 215-223 | shins (trousers, or bare skin = shorts) |
| 240-247 | hair (skin-coloured = shaved: Krishna) |
| 176-182 | skin |
| 192-196 | shoes |

`tools/ped_sprite_outfits.py <wil.sty> assets-src/humans/pedtypes/outfits.json` reads every
remap's colour per part. Each colour is the pixel-count-weighted mean over the 158 frames. The
script also sets three flags: `short_sleeves`, `shorts` and `bald`. The gang and police palettes
are very dark in the style (police torso [14,23,28]). `make_ped_manifest.py`'s `lift()` raises
near-black colours just enough for the hue to read, and adds 10% to every colour, because the
sprite means include the sprite's own shading.

## How an avatar wears it

- **Avatars.** There are 59 Rocketbox avatars (MIT). This pass added 18; they are listed in
  `assets/README.md`. Each type's avatars are picked for the sprite's silhouette:
  - Krishnas are shaved-head men (Business_Male_04/07).
  - Medics wear green scrubs (Medical_Male_04).
  - Russians wear a red henley.
  - Loonies wear a tracksuit.
  - Prisoners wear coveralls; the construction avatars' hard hats are dropped with the new
    importer option `materials_exclude`.
  - The player (remap 25, black) is Male_Adult_11.
  - Remap 26, the "naked dummy", wears swimwear.
  - SWAT/FBI wear tactical kit: the body is drawn as type 53.
  - Civilians draw from three pools by silhouette: long sleeves, short sleeves, shorts.
- **Clothing zones** (`tools/import_assets.py`, entry key `ped_zones`):
  - Each body triangle gets a zone from the bone class that carries most of its weight:
    spine, arms and hands are the top; pelvis, thighs and calves are the bottom; feet and head
    are left alone.
  - The zone is then voted per UV island (one garment piece), so shirt tails and lab-coat
    skirts stay with the top.
  - Skin texels use the classic RGB rule, and must also sit within 0.06 rg-chromaticity of the
    avatar's own face. Without that second test, red shirts read as skin.
  - The clothing texels go to a `_paint` copy made neutral grey. The shading is kept with its
    contrast eased by `zone_contrast` (0.75), and each zone's mean is 128 (`zone_ref`).
  - The top and bottom triangles become their own meshes, marked `#pt` / `#pb` in the node
    name. Each keeps only the vertices it uses.
  - The import report gives each zone's original colour (`zone_rgb_t/_b`) and the hair cards'
    mean colour (`zone_rgb_h`).
- **Outfits** (`ped_outfits` in the manifest): per remap, nine numbers: top RGB, bottom RGB and
  hair RGB (0 means keep the avatar's own). Hair is only given where the sprite shows a
  non-default hair colour: red or blonde rednecks, the blonde, ginger and grey civilians.
- **Renderer** (`dll/src/model_store.cpp`, `PedZoneTints` / `ModelSetZoneTints`):
  - For a zoned avatar whose type has `"tint": 1`, the `#pt` meshes are multiplied by
    top / 128 and the `#pb` meshes by bottom / 128, using the same fixed-function `TFACTOR`
    `MODULATE2X` stage as the cars' repaint. The hair cards (`_opacity`) are multiplied by
    hair / the avatar's own hair colour.
  - CROWD's random everyday colours are off for zoned avatars. A ±12% shade per ped
    (`CrowdLook::shade`) keeps a crowd of one remap from looking cloned.
  - The player is never shaded.
  - Uniforms and suits that already match their sprite keep their own textures with no zones:
    police, army, Zaibatsu, Yakuza and SWAT.
- **Log:** every 300 frames, `peds: N of M figures drawn in their sprite's outfit (ASSET-PEDS
  zones)`.

## The player's avatar is his alone (FIX-AVATAR-IDENTITY, 9 Nov 2026)

The owner saw the hero change clothes at the V press: a black sprite in the classic view, a white striped
shirt and khaki shorts in the street views. Three causes, each fixed:

- **The old hero.** Before PED-STAGE-INTEGRATE (`801210a`, 13:21) the manifest's `pedestrian` was
  `human_male_01` (white striped shirt, khaki shorts). Runs and demos recorded before that, such as
  `DEMO_live_gameplay_20261109.mp4`, show it. Since then the hero is `human_male_adult_11` with remap 25's
  outfit: shirt 61,61,66 and trousers 53,53,62 (the sprite's near-black, `lift()`ed). On screen that is
  58,59,68 on the torso, against the sprite's 66,66,72.
- **Shared with the crowd.** The same avatar was also in the plain `pedestrians` list and in 9 civilian
  types (28, 29, 30, 35, 36, 42, 43, 46, 49). Passers-by had his face, hair and build
  (`feel3-ped-wears-identical-outfit-to-player`), and a figure of his that ever fell to a pick could
  come out in someone else's clothes.
  - `tools/make_ped_manifest.py` (`HERO`) leaves him out of the crowd list and out of every civilian
    type. The rotation still deals from the full pools, so every other type keeps its avatars.
  - The DLL enforces the same rule at load (`model_store.cpp`, after `ped_types`): the manifest's
    `pedestrian` is dropped from every list except the type that holds remap 25, and never from a list
    it would leave empty. The log says `models: player avatar '<name>' (remap 25), kept out of N crowd
    picks`; N is 0 with the regenerated manifest.
  - Whenever the player's figure changes model, the log says
    `player avatar: <name> (remap 25, the protagonist)`.
- **First-person sleeves.** `tools/gen_weapons.py` `SLEEVE` was off-white with dark stripes, copied from
  the old hero. It is now the hero's shirt, 60,60,66, with the plain cloth weave. Only the three 32x32
  `fp_arm_*_1.tga` textures change; the meshes stay as they were. The forearms stay bare, as the hero's
  short sleeves show in third person.
- **Seated driver.** Whatever seated figure FIX-SEATED draws goes through the boarding ghost of the player
  (`BoardingIsPlayer` makes it `ownPed`), so it is drawn with the same avatar and outfit.

The classic view is not touched: all of this is in the street-view model pick and the first-person view
model. Remix parity note 2 (`docs/remix-3d-parity.md`) can now tag the hero's textures, because no
civilian shares them any more.

## Regenerating

```
python3 tools/ped_sprite_outfits.py game/data/wil.sty assets-src/humans/pedtypes/outfits.json
bash assets-src/humans/fetch_rocketbox_pro.sh Professions Police_Male_04 Security_Female_01 Business_Male_04 \
     Business_Male_05 Business_Male_06 Business_Male_07 Medical_Male_04 Sports_Male_04 Fire_Male_03 Construction_Male_05
bash assets-src/humans/fetch_rocketbox_pro.sh Adults Male_Adult_06 Male_Adult_09 Male_Adult_12 Male_Adult_18 \
     Male_Adult_20 Female_Adult_17 Female_Adult_12 Female_Adult_04
python3 assets-src/humans/make_ped_manifest.py            # copy of tools/make_ped_manifest.py
python3 tools/import_assets.py assets-src/manifest.json assets/models --only <human_ names>
```

The comparison sheet is `tools/ped_identity/compare_sheet.py <models dir> <out prefix> [remaps]`. It renders each
avatar with nvdiffrast on the GPU and applies the zone tints exactly as the DLL does.

## Status

See the ASSET-PEDS comment on the issue for the verified frames.

- **Verified offline:** a sheet of all 54 types, each original sprite beside its avatars,
  rendered with the renderer's tint rules.
- **Verified in game** (run `ap_r1`, camera-modes `16fcaf8` plus this change, plain renderer,
  Downtown plaza, third person, `gamerun/assetpeds_probe.py`):
  - Every remap 0-53 was drawn on the player and the crowd through `GTA2DX9_PED_REMAP_FILE`,
    three frames each. The in-game crops match the offline sheet type by type.
  - In the natural crowd afterwards, `peds: N of N figures drawn in their sprite's outfit` on
    every 10 s line.
  - Log: `models: 54 pedestrian outfits`, `50 pedestrian types cover 54 remaps`, 0 `FAULT`s.
  - Frame times were unchanged in the probe's windows: sprites 1.4-2.0 ms average, 4.0 worst.
    The plaza is sparse (1-5 figures), so this is not a dense-crowd measurement.

What still looks wrong or is not done:

- **Coloured police remaps (1-3: green, red, yellow).** These keep the black uniform. The
  sprite tints the shirt; those remaps are not seen in single-player Downtown.
- **Shaded colours.** Colours are means of shaded sprite pixels, so a few civilians come out a
  shade darker than the sprite reads at a glance (dark purple and burgundy shirts).
- **Pattern under the tint.** An argyle sweater or a patterned blouse keeps its pattern in the
  new colour.
- **Krishna.** The torso colour is a mix of the sprite's torso and forearm colours, which gives
  a saffron-brown shirt. There is no robe geometry in the library.
- **Elvis.** No pompadour: the library has no such hair.
- **Hulks (23/24).** No bigger build and no green skin.
- **Hair tint** only reaches the hair cards, not hair painted into the head texture. The red
  and blonde rednecks therefore differ little on the short-haired avatars. (Since ASSET-PEDS-3 the
  cards are not tinted at all: see below.)
- **Remix:** untested. The tint uses the same `TFACTOR` stage as the cars' repaint.
- **SDXL/TRELLIS:** not used. Generated meshes come without a skeleton. The rigged MIT Rocketbox
  avatars, recoloured from the sprite palettes, are both more photoreal and closer to the
  sprites.

**Staging hazard.** Zoned avatars carry neutral-grey clothing textures. A DLL without
`PedZoneTints` (anything before this commit) would draw them grey. So the new
`gta2dx9_models_people` set and this DLL must be staged together. Do not copy the avatars into
`repo/assets/models` ahead of the code.

## Round 2 (ASSET-PEDS-2, 9 Nov 2026): police, Krishna, Elvis, rednecks, Hulks

Closes most of the open items above. All with the same pipeline; new in this round:

- **Baked avatar variants** (`tools/ped_identity/ap2_variants.json`, built by `make_ped_manifest.py`
  through `tools/ped_identity/recolor_hair.py`). The hair of a Rocketbox avatar is painted into its
  head map (no hair-card meshes on the avatars used here: every `zone_rgb_h` is null, so the hair
  tint of round 1 never had anything to reach). `recolor_hair.py hair` finds the hair texels (the
  upper part of the map, outside the face ellipse, that differ from the face's median skin), keeps
  their luminance detail and sets the hue; `mul` multiplies a whole map by a colour. Variants are
  new entries (`<avatar>_z`, `_hr`, `_hb`, `_k`, `_g`) with their own baked head/body texture in
  `assets-src/humans/rocketbox/_ap2/`; nothing under that folder goes into git.
- **Coloured police (remaps 1-3).** `Police_Male_03/04`, `Security_Female_01` copied with
  `ped_zones` (the black uniform becomes the neutral grey top/bottom zones). The type
  `police_coloured` tints them to the sprite's shirt (dark green, dark red, olive/yellow) and navy
  trousers. The blue police (0) keep the original textured uniform.
- **Krishna (9).** `Medical_Male_01` (a long coat to the knees) with the coat tinted saffron to the
  ground and the hair stubble-dark: the closest thing to a robe the library has.
- **Elvis (12).** `Male_Adult_10` and `Male_Adult_16` with black hair (`_k`), the tallest-styled hair
  available; no pompadour geometry exists in the library (a real quiff needs a hair mesh: open).
- **Rednecks (5, 6).** Split into `redneck_red` / `redneck_blonde` on `Male_Adult_16/09` heads baked
  ginger / blond.
- **Hulks (23, 24).** Types `hulk` / `hulk_green`: the manifest's `"scale": 1.3, "width": 1.18`
  per type (`PedTypeBuild` in `model_store.cpp`, applied in `live_geometry.cpp` where the figure is
  fitted; the player's own figure is never rescaled). Hulk 24 uses `Male_Adult_01_g` /
  `Sports_Male_04_g` with head and body maps multiplied green. Limit: the zone tint also multiplies
  the bare arms and legs of the top/bottom meshes, so the green Hulk's shirt and trousers are the
  sprite colours mixed toward green and read olive.

Regenerate: `python3 assets-src/humans/make_ped_manifest.py` (with `tools/ap2_variants.json` and
`recolor_hair.py` copied into `assets-src/humans/tools/`), then `tools/import_assets.py` with `--only` the
twelve new names (`human_police_male_03_z` ... `human_sports_male_04_g`); sheet: `compare_sheet.py`.
Needs the new DLL (`PedTypeBuild`) with the new `manifest.json`; an older DLL ignores the scale.

## Round 3 (ASSET-PEDS-3, 10 Nov 2026): garment-true paint halves, one hair colour per head (qav14)

The filing: a female ped in a sage jacket at arm's length (bil, first person) had hard-edged brown blotches,
a brown diagonal and 1-px speckle on the jacket, and a purple fringe round her blonde bun.

**Paint halves cut by colour.** `import_assets.py` (`ped_zones`) put a garment texel in the `_body_paint`
half only if it failed the skin test (classic RGB rule and within 0.06 of the face's chromaticity). The
bright folds of a brown leather jacket and the flat patches of a pink shirt pass that test, so they stayed
in the rest half in the avatar's own colour and showed through any tint. Three avatars have it badly:

| avatar | garment | what showed | texels moved to the paint half |
|---|---|---|---|
| `human_female_adult_04` (f004) | brown leather jacket | brown folds, a brown diagonal and speckle through the sage of remaps 47/51 | 16 849 (top 14 670, bottom 2 179) |
| `human_female_01` (f001) | pink shirt | pink patches through any shirt colour | 16 918 |
| `human_male_adult_05` (m009) | brown sleeves, green trousers | brown speckle on the sleeves and trousers | 7 132 |

`tools/ped_identity/paint_resplit.py <models> --out <dir> <model>_<tag> ...` re-splits by the garment's UV
triangles (the `#pt` / `#pb` paint meshes of the `.mesh`, rasterised in UV space). A garment texel left in
the rest half stays there only if it belongs to a solid region (one that contains an 11x11 square) that is lit
like skin (luminance >= 100, green chromaticity >= 0.295): the hands, f001's bare forearms, the necklines, and
m009's pale tan vest. Every other garment texel (the folds, the diagonal, the speckle) moves to the paint half
with its own luminance, by the importer's rule (contrast eased by 0.75 around the zone's mean, mean -> 128).
The zone's mean is worked out from the texels already in the paint half, so those texels do not change. A
second run on its output changes nothing. It writes new files (never through the hard links into the stage).
The tool's `--preview` sheet shows, per avatar, the original, the old and the new halves under a tint, and the
masks.

The tool also pads the edges. The gutters between UV islands (texels under no triangle) used to be opaque in
the rest half, in the avatar's old colour, and empty in the paint half. Where bilinear filtering or a mip level
reached across a garment's edge, the alpha test let that gutter colour through: 1-px dark specks along the
seams, such as f004's hood seam. The gutters are now shared out ring by ring (`--pad 4`) between the paint
texels and the rest's opaque texels; ties go to the rest. A gutter texel the paint reaches takes the mean grey
of its paint neighbours and is see-through in the rest half. Gutter texels given to the paint half: f004 23 297,
f001 15 791, m009 20 112.

f004 is dealt to remaps 18, 19, 37-40, 44, 45, 47, 51 and 52. f001 and m009 are in no ped type and not in the
`pedestrians` list of today's manifest: the game never deals them. They were fixed so that a later manifest can
use them.
Not this class, and not touched: female_05's plaid, construction m111's plaid, m002's stripes, the bikini and
the fire kits. Their two-tone designs are kept in the rest half on purpose.

**The bun.** Remaps 47-51 give hair 159,139,159 (a lilac grey from the sprite's palette). `PedZoneTints` tinted
the hair cards (`_opacity`: the strands round the bun, and the eyelashes) toward it. The head map, which
carries the painted hair, keeps the avatar's blonde, so one head had two hair colours: the purple fringe.
Every Rocketbox avatar paints its hair into the head map, and no tint reaches it, because face and hair are one
texture. So the cards are no longer tinted (`model_store.cpp` `PedZoneTints`: `hair = false`). They keep the
avatar's own colour, as the head map does. A sprite hair colour reaches an avatar only through a baked variant
whose head map carries it (ASSET-PEDS-2 `_hr`, `_hb`, `_k`). The variants' cards are dark (mean about 20); the old
tint clamped at 2x and moved them very little.

**Verified** (plain renderer, Downtown plaza, a private stage of HEAD 17a29382 plus this change). The probe is
`linux/docker/ap3_peds.py` with `keys_ap3_peds.sh` (copy both into `gamerun/`). It uses fixed regress cameras about 2 m from the figure: front, 3/4,
side and back at eye height, and the bun from behind. `GTA2DX9_PED_REMAP_FILE` draws the remap. The private
manifest deals remap 47 -> f004, 40 -> f001 and 19 -> m009. Before (the live stage dd489cab with the old halves)
against after:
- f004 in remap 47's sage: the brown blotches and the diagonal are gone, and the jacket is one sage with its own
  leather shading. The bun is one blonde, with no lilac.
- f001 in remap 40's burgundy: the pink patches are gone.
- m009 in remap 19's teal and blue: the brown speckle on the trousers is gone.

**Still short:**
- m009's tan vest is kept untinted (a design panel the split keeps), so remap 19's teal shows only on the
  sleeves and the T-shirt.
- f004's sage is a satin-bright mint at noon. That comes from the existing tint calibration, not from this split.
- The sprite's hair colour for remaps 47-51 (lilac grey) is not shown on avatars with painted hair: that needs
  baked grey-hair variants.
- **Remix:** the three pairs' texel hashes changed. Their new pair prims (6 hashes 8BF3CBFAFF278C9E, FC049AB32E6739B0, 525C8B73D1BB1BC9, 5F04FB36314B66F4,
  8AA21727C60994AB, EB6E86C8E75CE6C2; albedo = the merged halves,
  normal and roughness from the Rocketbox sources) were built with `tools/remix_model_materials.py --pattern
  '^human_(female_adult_04_f004|female_01_f001|male_adult_05_m009)_body(_paint)?\.tga$'` into a scratch layer and
  merged with `tools/remix_layer_merge.py`: 12 prims inserted into `mod.usda` and `mod_wet.usda`, none replaced, and
  `model_prims.txt` 1171 -> 1177. The old-hash prims stay and are inert. The 18 DDS files are a layer bundle
  (`layer_deploy/ASSET-PEDS-3`). Until it is deployed, these avatars draw with the legacy material: colour right,
  no normal or roughness maps. A path-traced take of the first, unpadded build of these prims (private package
  with the prims merged; f004 in remap 47 and f001 in remap 40, at the fixed cameras): the jacket is one dark sage
  leather with its folds as shading, the bun is one blonde, and f001's shirt is one burgundy. The layer's
  sun makes the colours much darker than the plain renderer's. The padded build's prims were not taken path
  traced (the halves differ from the unpadded ones only in the gutters).
- **Not in git:** the textures ship in the `people` release archive, which needs repacking
  (`python3 tools/pack_release.py <out> people`).

## Civilian variety (PEDS-VARIETY, 12 Nov 2026)

The owner asked for more variety in the civilians' faces and clothes, outfits right for men and women and never
ridiculous, in the Rocketbox look. Uniforms, gangs, police, medics, the Hulks, the naked type and the player do not
change.

- **Faces.** Each `civilian_*` type (remaps 15, 18-21, 27-52) now deals from nine or ten zone-ready avatars, four of
  them women, a mix of its own seeded by the remap (`tools/make_ped_manifest.py` `civilian_pool`; the manifest's
  `ped_types`). Women: `female_01/03/05/08`, `female_adult_02/04/12/13/17`, `business_female_01`. Men: `male_01/04/07/10/13`,
  `male_adult_02/05/06/08/09/12/16/18/20`, `business_male_04/06/07`. Left out: the hero (`male_adult_11`), the swimwear,
  the religious dress and the baked `_hb/_hr/_k/_g/_z` variants. The plain `pedestrians` list (remaps with no type)
  holds all of them. Before: three or four avatars per type out of fifteen, picked by the sprite's sleeve length.
- **Clothes** (`identity.cpp` `CrowdVariety` / `CivilianOutfit`, a port of `tools/ped_identity/outfits.py`). A civilian
  (`PedRemapIsCivilian`: a `civilian_*` type, or no type) on an avatar with clothing zones wears, by a hash of his ped
  id, a curated outfit three times in four, else the avatar's own colours. Men's, women's (`female` in the avatar's
  name) and formal (`business`) palettes; the top and the bottom at least 70 apart in RGB (40 for formal wear); at
  most one strong colour (chroma > 0.28). Zone tint = colour / `zone_ref`, clamped 0..2; the hair is never tinted; a
  +-6% shade, applied once (other zoned types keep the +-12% over their sprite colours). The record says `clothes`
  when an outfit was drawn. The C++ and the Python give the same outfit for 60 000 seeds (`tools/ped_identity/outfit_parity.py`:
  the function compiled natively against `outfits.outfit`).
- **What it replaces.** Civilians on zoned avatars wore their remap's sprite colours (ASSET-PEDS), so a remap's crowd
  was one outfit (remap 20 all grey over denim, 52 all hot pink, 33 olive on olive). The 3D civilian no longer
  matches the classic sprite's shirt colour; `tools/identity_parity.py` checks the player and cars only, so no check
  changes. `[crowd] variety=0` (or `GTA2DX9_CROWD=0`) restores the sprite colours (with no build or shade variety).
- **Unzoned avatars.** `business_female_01` (a black suit with a `_paint` half) keeps the old everyday tint three in
  four: on near-black paint it only darkens or warms the suit.
- **Sheet.** `CUDA_VISIBLE_DEVICES=0 gen3d/venv/bin/python tools/ped_identity/crowd_sheet.py stage/gta2dx9_models
  out.jpg --remaps 15,18,20 --seeds 24` renders consecutive ped ids as the DLL dresses them (`outfits.crowd()`).
