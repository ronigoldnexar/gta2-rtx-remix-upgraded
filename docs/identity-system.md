# Entity identity: one record per entity, shared by the classic view and the 3D views

Agent IDENTITY-SYSTEM, 9 Nov 2026. Owner directive `/mnt/gta2/IDENTITY_MECHANISM.md`: a consistent mechanism
that keeps the player, every pedestrian and every vehicle looking the same in the original top-down view (BEV)
and the 3D views. This document is the design (written before the code) and, below it, what was built and
verified.

## 1. The problem, in code terms (state at `7bfd77b`)

What an entity looks like in 3D was decided in four places, each with its own inputs:

| Entity | Where the look was decided | Inputs | Fault |
|---|---|---|---|
| Player | `live_geometry.cpp` `DrawPedFigures`: `ownPed ? ModelForPedestrian() : pool` | `g_playerObject` match | Correct only while `ownPed` is true. Any frame where the match fails (respawn, boarding ghost before `BoardingIsPlayer`, a second object for him) drops him into the crowd path below. Also, the hero's avatar sat in the crowd pools (`feel3-ped-wears-identical-outfit-to-player`). |
| Pedestrian | same function: `PedRemapForPalette` -> `ModelForPedestrian(object >> 4, remap)`, `CrowdLookFor(object >> 4, ...)`, `PedZoneTints`, `PedRemapTint` | the sprite's palette (good), **the sprite object's heap address** (bad) | The avatar within a type, the build and the clothes tint were seeded by a heap address. Same save, same spawn, different session: a different person. |
| Vehicle (built) | `car_bodies.cpp` `CarBodiesDraw`: `ModelForVehicle(model number, sprite)`, paint/tint/livery/lift/sheen inline | the game's model number, the paint measured from the live sprite art | Deterministic, but the decision lived inline in a 3 400-line draw function. |
| Vehicle (by sprite) | `live_geometry.cpp` `ProcessCar`: `ModelForCar(sprite)` -> `DrawCarModels` | sprite number only | A second vehicle path with **no paint at all**. Dormant today (`cars.by_sprite` is empty), but a manifest entry would turn it on, and those cars would ignore the sprite's colour. |
| FP arms | `tools/gen_weapons.py` `SLEEVE`, baked into `fp_arm_*_1.tga` | a constant in a Python script | Not connected to the player's outfit at all; it matched the old hero (striped) until FIX-AVATAR-IDENTITY changed the constant. |

The striped shirt in the owner's videos was the old hero (`human_male_01`, before `801210a`). FIX-AVATAR-IDENTITY
found that and is fixing the pool exclusion. This design is the structural answer: no code path can choose an
appearance except through the identity record.

## 2. The mechanism

### 2.1 One module, one record per entity

`dll/src/identity.h` / `identity.cpp` (owned by IDENTITY-SYSTEM). Nothing else may call `ModelForPedestrian`,
`ModelForVehicle`, `ModelForCar`, `CrowdLookFor`, `PedZoneTints`, `PedRemapTint` or `PedTypeBuild` for drawing.
The draw paths ask the identity module and use what they get back.

```
enum class IdKind { Player, Ped, Vehicle };

struct SpriteRef {            // what the CLASSIC view draws for this entity: the reference
    int remap;                // ped: the remap of the palette the sprite is drawn with (-1 none)
    int body;                 // ped: sprite set (frame / 158: 0 common body, 1 GANG_GRAPHIC, 2+ EMERG_GRAPHIC)
    int carModel, carSprite;  // vehicle: the game's model number (CARI) and car sprite
    float paint[3];           // vehicle: the paint measured from the sprite art the classic view draws
};

struct IdentityRecord {
    IdKind kind;
    uint32_t key;             // player 0; ped: the game's ped id (Ped +0x200); vehicle: the game object
    SpriteRef ref;
    const Model* model;       // the 3D model: derived, never chosen elsewhere
    // the colours the 3D model is drawn with, all derived from ref:
    bool zoned; float zone[3][3]; bool zoneHair;   // shirt, trousers, hair (avatar zones)
    bool tinted; float tint[3];                    // a type's whole-clothing tint
    float height, width, shade;                    // build (crowd variety; 1 for the player)
    bool clothes; float clothesTint[3];            // a civilian's everyday-colour clothes
    bool livery; float paintTint[3]; float lift, darkness;  // vehicle paint over the model's own
    float shownTop[3], shownBottom[3];             // the colours the 3D view should show (for the checks)
    uint32_t fingerprint;     // hash of everything above except key: equal across sessions
};
```

`IdentityForPlayer()`, `IdentityForPed(spriteRef, pedId)`, `IdentityForVehicle(spriteRef)` return a
`const IdentityRecord&`. Records are cached by key and recomputed only when the `SpriteRef` changes (a respray, an
outfit change by the script, a wreck). A change is logged.

### 2.2 Why the two views cannot disagree

1. **The reference is the classic draw's own input.** The classic view draws the game's sprite with a palette. The
   ped record's `remap` is that palette's remap. The vehicle record's paint is measured from the sprite art the
   classic view draws. The classic path itself is not touched: it stays byte-for-byte. The record is built from
   what it draws.
2. **The 3D look is a pure function of the reference.** `Derive(kind, ref, seed)` has no other inputs: no clock,
   no heap address, no draw order, no per-session random. The seed is the game's ped id (deterministic for a given
   save and spawn), or for the player none.
3. **There is one resolver.** The second vehicle path (`ModelForCar(sprite)` -> `DrawCarModels`) is retired. Every
   car goes through `CarBodiesDraw` with its record. The player record is dedicated: it never goes through a pool,
   and its model (the manifest's `pedestrian`) is excluded from every crowd pick inside `Derive`. This does not
   depend on the manifest being right; FIX-AVATAR-IDENTITY's load-time exclusion is the same rule from the data side.
4. **The player is decided by identity, not by a pointer match on a frame.** `ownPed` (the game's player object,
   plus the boarding ghost) selects `IdentityForPlayer()`. A figure whose ped id equals the player's ped id is also
   the player, so a missed pointer match no longer reaches the crowd path.
5. **First-person arms take their sleeve colour from the player record** (texture factor over the sleeve texture),
   not from a constant in a generator script.

### 2.3 Determinism

Every seed is a game id: `Ped +0x200` for people. Vehicles need no seed (model number and measured paint). The
fallback, when the id cannot be read, is a hash of `(remap, body)`. That makes a crowd of one type look alike, but
it never depends on the session. The record's `fingerprint` is logged:

```
identity: player key 0 remap 25 -> human_male_adult_11 top 61,61,66 bottom 53,53,62 fp 1a2b3c4d
identity: ped key 1043 remap 30 body 0 -> human_male_adult_16 ... fp ...
identity: vehicle model 5 sprite 9 paint 182,40,38 -> 005_beamer tint 1.21,0.40,0.38 fp ...
```

The per-session check compares the player's fingerprint and the fingerprints per vehicle model across fresh
sessions. They must be identical.

### 2.4 Remix

Under RTX Remix the 3D figure and car draws are the same D3D9 draws. The record's colours reach Remix in two ways:

- as the texture factor on stage 1, which Remix applies (`rtx.enableMultiStageTextureFactorBlending`, on by
  default; proven for car paint in `docs/remix-materials.md`), and
- the replacement material (albedo, normal, roughness) keyed by the hash of the model texture the record names.

So the record drives Remix through the same two channels as the plain renderer.

**Figures under Remix: one draw per surface, the record's colours in its albedo.** The root cause of the
grey-clay figure and of the floating head (`pt-remix-third-figure-*`) is the split pair, not the tint: the
importer (`tools/import_assets.py` `ped_zone_split`) draws a person's clothing as a second mesh over the same
triangles. For `human_male_adult_11`, all 2 775 triangles of the shirt mesh (`#pt`) and all 594 of the trousers
mesh (`#pb`) are also in the body mesh, whose texture is cut out (alpha 0) on the cloth. Remix takes the second
draw of a surface as a duplicate (`docs/remix-materials.md`, "Car paint": the same thing cut the cars in half),
so the clothing was never path traced: what was left were the body mesh's uncut parts, the head, forearms and
shoes (`out/idr_1`, run on this commit's first build, with the tint bake below already on). Under the bake the
body mesh is drawn once with one merged texture (`FigurePairMerged`): its own texels, and where it is cut out
the paint half's texels times the record's tint for that texel's zone. The zones (top, bottom) are rasterised
from the `#pt` / `#pb` meshes' UVs. The paint meshes are not drawn (`FigurePairPaintSkipped`). Merged textures
are cached per model, texture and tint at 1/64, at most 256.

**Figures under Remix: the record's tints baked into the albedo.** The figures' clothing tints (the
zones' shirt, trousers and hair, and the one-tint types and civilian clothes) are not left to the stage-1
texture factor under Remix. Playtests saw the third-person figure as grey clay (`4ed7169`), then with its torso
and legs missing (`7bfd77b`): exactly the meshes drawn with that stage. With `IdentityBakeTints()` (on when the
Remix API is up, or `GTA2DX9_IDENTITY_BAKE=1`; `=0` never), `ModelDraw` binds a copy of the mesh's texture with
the record's tint multiplied in (`BakedTint`, cached by texture and tint at 1/64, at most 256 copies) and no
stage 1. Remix then sees an ordinary textured draw whose albedo is the record's colours. A baked copy has its
own texture hash, so no prim of the layer replaces it: the legacy material, with the record's albedo. The
plain renderer keeps the texture factor (its frames unchanged). The two are equal to within the factor's own
quantisation: the stage gives texel x floor(t x 127.5) / 127.5, the bake texel x round(t x 64) / 64. `tools/identity_remix_check.py`
checks offline, per build, that every texture an identity model draws with has its Remix prim, that the prim's
albedo file exists, and that the albedo is not flat grey. Missing prims are listed. A missing prim is not
grey on its own: Remix then uses the game texture. But it means no PBR. The grey-clay figure
(`pt-remix-third-figure-single-tone-grey-clay-no-albedo`) is checked against this list; see section 4.

**Figures under Remix with the gta2hd layer: the layer's materials, the record's tints as a factor (FIX-REMIX-3,
9 Nov).** The merged bake above gives every figure the right colours, but each bake is a new texture with a new hash,
so no prim of the layer replaced it: under Remix every body path traced with the legacy material (flat roughness, no
cloth or skin normals; `remix-figure-baked-textures-miss-layer-prims`, probe `out/rhv_probe1`). The layer's pair prim
for a body (`tools/remix_model_materials.py`) already holds the whole body: albedo = the rest texels plus the
untinted paint texels (neutral grey 127, measured on four avatars: no texel is opaque in both halves), opaque, with
the normal and roughness maps per texel. So now (`model_store.cpp` `LayerPrimFor`, `FigureZoneSplitFor`):

- At the first figure draw under the bake the DLL reads the installed layer's prim hashes from
  `rtx-remix/mods/gta2hd/mod.usda` (every `mat_<16 hex>`; log `models: Remix layer: N material prims`), and hashes each
  figure texture the way Remix does (XXH3-64 of mip 0 as uploaded; log `Remix layer prim for <tga> (0x...): yes|no`).
- A body whose rest texture has a prim is drawn with that texture, unmodified, so the prim keys. The record's tints go
  on as the stage-1 texture factor (`MODULATE2X`, as the plain renderer), which Remix applies
  (`rtx.enableMultiStageTextureFactorBlending`).
- One factor per draw cannot follow a per-texel cloth edge, so the body's triangles are split by what their texels
  are: skin (the rest's own texels, untinted), top cloth, bottom cloth (zone from the `#pt` / `#pb` mesh with the same
  UVs), each drawn with its own factor over its own triangles (disjoint, so Remix still sees one draw per surface).
  A triangle on an edge, or holding an untinted detail inside the cloth (a zip, a print), takes the kind covering more
  of it (log `figure zones for Remix: ... N skin, N top, N bottom`). Tinting whole paint-mesh triangles was wrong: the
  paint meshes cover whole limbs, and the hands came out in the shirt's colour (`out/fr3_noon1`).
  `GTA2DX9_REMIX_FIGURE_EDGES=bake` draws the edge triangles with the merged bake instead (exact per texel, but its
  legacy material next to the prim's showed as a patchwork on busy clothes, `out/fr3_noon2`).
- Hair and other tinted zone meshes with a prim take the factor too; without a prim they keep the tint bake.
- No layer, or a texture without a prim: the merged bake, as before. `GTA2DX9_REMIX_LAYER_TINT=0` forces the bake.

Verified: the probe layer of `tools/remix_model_hash_probe.py` (`--only '^human_'`, installed as gta2hd): before
(`out/fr3_probe1`) bodies kept their own colours; after (`out/fr3_probe2`) the hero's arms and the pedestrians' bodies
are magenta like the heads. With the real layer (`out/fr3_noon3`, noon): the hero has skin forearms and hands, a dark
shirt and trousers. Edge-triangle colours are exact only to the triangle: a sleeve hem follows the mesh's triangles, not
the texels.

### 2.5 The cross-mode parity check

`tools/identity_parity.py` with a keys script `linux/docker/keys_identity_parity.sh`. It runs per build from a
private stage. The DLL's probe (`GTA2DX9_IDENTITY_PROBE=1`) logs, for the subject (the player, or the car he
sits in), its record and its screen rectangle in each view:

- classic: the rectangle of the sprite quad the game draws,
- third person: the projected bounds of the 3D model,
- first person: for the player, the sleeves' rectangle; for a car, the bonnet below the eye.

At the same moment means the same place and pose: the subject stands still while the script presses V twice in
under two seconds. Assertions, each a FAIL line and a non-zero exit:

1. **Record:** the same fingerprint for the subject in all three views, and across sessions when several runs are
   given.
2. **Colour:** the dominant colours of the subject's pixels (classic sprite crop, third-person crop, first-person
   crop) agree with each other within a CIE76 delta-E threshold (default 25, after the lighting is normalised by
   dividing by the crop's grey-world mean of the scene around it).
3. **Silhouette:** in the classic view against the 3D view at the classic camera (`TransitionSeconds` stretched,
   as in `docs/bev-parity.md`), the drawn-pixel masks overlap (IoU >= 0.5) and have the same aspect within 25%.
4. **Classes:** the player, then one vehicle per class: sedan, sports, van/truck, bus, emergency livery (police),
   taxi livery. The script warps him next to each (`[devtools]` scene points and `force_own_car_model`), enters,
   and repeats the capture.

### 2.6 What is not changed

- The classic view: no draw, state or texture of the classic path changes. The identity module only reads.
- Behaviour variety (idle clips, fidgets, glance timing) stays seeded as it is. It is motion, not appearance.
- The models and textures themselves. This is the mechanism. Art passes (VEHICLE-REVIEW, ASSET-PEDS) feed it.

## 3. Implementation steps (each with frames)

1. `identity.{h,cpp}`: records, derivation, logging, the player/ped/vehicle resolvers. Ped draws in
   `DrawPedFigures` switched over. The ped id is read with the sprite (`Sprite::pedId`).
2. Vehicles: `CarBodiesDraw` takes model and paint from the record; the by-sprite path is retired.
3. First-person arms: sleeve tint from the player record.
4. The probe and `tools/identity_parity.py`; keys script; runs over several fresh sessions.
5. Remix: `tools/identity_remix_check.py`, and the grey-clay figure investigated with the record's textures.

## 4. Built and verified (9 Nov 2026)

### 4.1 What is in the code

| Piece | Where | What it does |
|---|---|---|
| The records | `dll/src/identity.h`, `identity.cpp` | `IdentityForPlayer()`, `IdentityForPed(cacheKey, pedId, palette, frame)`, `IdentityForVehicle(cacheKey, SpriteRef)`. Pure derivations (`DerivePlayer`, `DerivePed`, `DeriveVehicle`), cached, logged once and again on any change (`identity: ... CHANGED`). The crowd variety (`CrowdVariety`, was `CrowdLookFor` in `live_geometry.cpp`) and the vehicle paint/livery/floor/sheen rule (was inline in `CarBodiesDraw`) now live here. |
| People | `live_geometry.cpp` `DrawPedFigures` | The pick block, the build and the tint/zone block read `ident` only. The player is his record when the object matches or the boarding ghost is his, and also when the figure's game ped id is his. The ped id is read with the sprite (`Sprite::pedId`, Ped +0x200). |
| Vehicles | `car_bodies.cpp` `CarBodiesDraw` | Model and paint from `IdentityForVehicle`. The devtools overrides (`force_car_model`, `force_own_car_model`, `force_car_paint`, `wreck_models`) are inputs to the record, not side paths. |
| Second vehicle resolver retired | `live_geometry.cpp` car capture | `ModelForCar(sprite)` -> `DrawCarModels` (no paint) is gone; every car goes through `CarBodiesDraw`, where `ModelForVehicle` still falls back to `cars.by_sprite`. |
| First-person sleeves | `live_geometry.cpp` view model, `model_store.cpp` `ModelSetNodeTint` / `ModelNodeTextureMean` | The `sleeve*` nodes of `fp_arm_*` take a texture factor = the player record's shirt / the sleeve texture's own mean. Log: `identity: first-person sleeves <mean> -> the player's shirt <rgb> (fp <hex>)`. The generator's constant no longer decides the colour. |
| Probe | `identity.cpp` `IdentityProbe*`, hooks in `AddSprite` (classic, read only), `DrawPedFigures`, `CarBodiesDraw`, the view model | `GTA2DX9_IDENTITY_PROBE=1` (`_EVERY=N`, default 15 frames by the wall clock): `identity probe: <player\|mycar\|car\|sleeve> view <v> frame <f> t <unix> obj <hex> rect x0 y0 x1 y1 fp <hex> model <name> shown <top> <bottom>`. Classic rectangles are the game's own sprite quads (640x480 space), 3D ones the projected model bounds. |
| Parity check | `tools/identity_parity.py`, `linux/docker/keys_identity_parity.sh` | Section 2.5. Exit status = number of failures. |
| Remix check | `tools/identity_remix_check.py` | Section 2.4, offline, per build. |

Rule check (no other resolver): `grep -n "ModelForPedestrian\|ModelForVehicle\|ModelForCar\|PedZoneTints\|PedRemapTint\|PedTypeBuild" dll/src/*.cpp`
lists only `model_store.cpp`, `identity.cpp` and one diagnostic log line in `car_bodies.cpp` (`car nose`, `GTA2DX9_LOG_NOSES`).

### 4.2 Run it

```
# private stage with the build, then a session (about 3 min, one slot)
GTA2_DIRECT_KEYS=1 PRIO=1 FPS=0 STAGE=<stage> INI_SED='s/^warp_key=.*/warp_key=F9/' \
  gamerun/grun.sh idp_<n> 220 keys_identity_parity.sh -e GTA2DX9_IDENTITY_PROBE=1 -e SETTINGS_EXTRA=/work/bev_parity.settings
# the check over one or several sessions (numpy + Pillow: /mnt/gta2/gta2-linux/vreg/venv/bin/python)
python3 tools/identity_parity.py out/idp_<n> [out/idp_<m> ...] --report r.md --sheet sheet.png
# the Remix layer (numpy, Pillow, xxhash)
python3 tools/identity_remix_check.py stage/gta2dx9_models package/rtx-remix/mods/gta2hd
```

The keys script: into the level, the warp key to the nearest parked car's door, 1.2 s walk (at the door itself
he is not drawn after a warp, a known warp artefact noted in `docs/visual-regression.md`), then classic -> V
(the frame 0.9 s later is the 3D view at the classic camera, `TransitionSeconds=12`) -> third -> first ->
classic, then into the car and the same cycle.

### 4.3 Results: four fresh sessions (`out/idp_s1` .. `idp_s4`, stage `stage_identity`)

**Determinism (acceptance 2).** The player's record is `cfafb894` (`human_male_adult_11`, remap 25, shirt
61,61,66, trousers 53,53,62) in all four sessions, with no `CHANGED` line. 52 distinct vehicle inputs
(model, sprite, paint) were seen across the sessions; each has exactly one fingerprint in every session.

**Record equality across views (acceptance 1, 3).** Every probe line of the player (classic sprite, the 3D
figure at the classic camera, third person) carries `cfafb894`. His car's lines in classic, third and first
person all carry `744f918b`.

**Colour, player (`idp_s4`).** The classic sprite's dominant colour is 21,14,4 (near black). The third-person
figure's is 74,70,68 (dark grey shirt and jeans, lit): delta-E 25.9, limit 30, **pass**. Seen from the
classic camera the 3D figure is 70,68,74 against the sprite's 21,14,4: delta-E 26.3, **pass**. The same person
in the same dark clothes. (The black/white outfit swap of the owner's report would be delta-E of about 70.)

**Colour, vehicles: a real failure the check catches.** The car the warp key finds is a `068_van`. Its
sprite's paint is 99,97,81 (khaki-olive). The 3D model reads 78,59,44 from the classic camera and 30,21,13 from
the chase camera (dark brown), delta-E 16.8 and 33.9: **FAIL** in every session. The record's paint is right:
the tint takes the model's `_paint` half (texture mean 138,109,84, manifest `paint_rgb` 138,107,94) to
112,103,90. But most of the van's visible body is in the model's non-paint texture, which is brown. That is an
art fault of `068_van` for VEHICLE-REVIEW, not a mechanism fault. The mechanism makes it measurable on every
build.

**Not covered yet.** First person on foot draws no body and no arms without a weapon, so the sleeve check
reads the record line (`identity: first-person sleeves`) but has no frame. The own car's first-person
bonnet is drawn by the cab copy, which the probe does not report (the record line is checked, the frame
is not).

### 4.4 Remix (`tools/identity_remix_check.py`, the shipped `gta2hd` layer)

- The player: `human_male_adult_11_m001_head` has its prim and its albedo (mean 98,66,51, the texture's own).
  The two body halves (`m001_body`, `m001_body_paint`) have **no prim**: ASSET-PEDS re-split them after the
  layer was built, so under Remix they are drawn with the game texture and the legacy material (colour, but no
  normal or roughness map).
- Pedestrians: 96 of 215 avatar textures have their prim; the rest are legacy material for the same reason.
- Cars: 303 of 323 textures pass; the other 20 (10 models) have no prim; none is stale.
- None of this makes the albedo grey: a texture without a prim keeps its colour. The grey-clay figure
  (`pt-remix-third-figure-single-tone-grey-clay-no-albedo`) and the floating head
  (`pt-remix-third-figure-torso-legs-invisible-floating-head-arms-shoes`) were the duplicate split pair (2.4).

### 4.5 Remix, path traced (`remix_l4.sh`, `keys_remix_gpu.sh`, `PREWARM_WAIT=250`, GPU 4, stage `stage_identity`)

| run | build | third-person figure |
|---|---|---|
| `out/idr_1` | tint bake only (stage-1 factor replaced by baked copies) | head, forearms and shoes only: torso and legs not drawn (the 7bfd77b report reproduced) |
| `out/idr_2` | + one draw per surface (`FigurePairMerged`) | the whole figure: dark navy shirt, dark trousers, skin, hair, in `view_1_third`, `_walked`, `_turned` |

The plain renderer with the same path forced on (`GTA2DX9_IDENTITY_BAKE=1`, `out/idp_bake2`) draws the same
figure as with the texture-factor path (`out/idp_s4`): same dark shirt and jeans, whole. The parity check
passes him (delta-E 29.3 against the sprite).

Still short of the owner's bar: under Remix the merged figure textures have no PBR maps (a runtime copy has its
own hash, so the layer's normal and roughness prims do not apply; the hero's body halves had none anyway). Cloth
is the legacy material's constant roughness. The fix for that is a layer prim keyed by the merged texture's
hash, which needs the record's tints known at build time (the player's are fixed: remap 25).

The layer is rebuilt by `build_remix_mod.sh` (REMIX streams); the check tells that stream which identity
textures are missing.

Cars are not merged at run time. Their split pairs are handled by the layer's merged prims (`remix_model_materials.py`:
both halves one opaque whole-car material, with PBR maps), which a runtime copy would bypass. A car whose
textures the check lists as "no prim" (20 textures of 10 models today: `003_pacifier`, `004_g4_bank_van`, `005_beamer`,
`019_gt_a1`, `021_garbage_truck`, `022_armed_land_roamer`, `029_dementia`, `052_swat_van`, `069_u_jerk_truck`,
`071_rumbler`; none stale) can be path traced in halves until the layer is rebuilt.

## 5. The player's car: one object, the sprite's paint (FIX-CAR-IDENTITY, 9 Nov 2026)

Work orders pm33 (2s), pm17 + pf18-car-colour + pm22 (2g), pf18-jacked-truck (2i), feel9 (10d).

### 5.1 What was wrong

1. **Every car's own paint was 235.** `DeriveVehicle` made the tint `live / model->paintRgb`, and
   `model_store.cpp` reads `paint_rgb` only from the manifest's `imported` report entries, which never carry it.
   A generated body whose paint half is painted ~90-200 in its own hue was drawn at texel x live / 235:
   about half the sprite's brightness with the texture's hue mixed in (violet -> wine red, silver -> brown,
   green -> near black). The manifest's `models` entries' `paint_rgb` is not a safe source either: it is the
   default sprite's paint, 20-120 off the texels for most cars (VEHICLE-ART-3, `va3_paint_check`).
2. **The record re-derived on every paint re-measure.** The paint is measured from the sprite art the
   classic view draws; that art changes for a frame or a few at a wall hit, a door, a lamp or a dent. Each
   change re-derived the record: a new tint (the body's colour popped, feel9) and a `CHANGED` line.
3. **The door-busy stand-in body was keyed by the sprite object alone.** The game re-uses a car's sprite
   object for another car within seconds (a 150 s Downtown run: dozens of `CHANGED model a->b` on recycled
   objects). With a ped at the new car's door, the previous car's measured body and paint stood in for up to 90 frames.

### 5.2 What changed

| Piece | Where | What |
|---|---|---|
| The model's own paint, measured | `model_store.cpp` `ModelOwnPaint` | The texels a car model's `_paint` meshes cover (their triangles rasterised in UV space with `RasterUv`, alpha >= 128 in the shipped file, before any soft mask), reduced by the sprite's own rule (`MeasureSprite`: the mean of the brighter half). Cached per model; measured on a low-priority thread from the first car on (not at load). Log: `models: <name>: own paint measured r,g,b (<n> texels ...)`. |
| The tint | `identity.cpp` `DeriveVehicle` | `tint = lift x live / own`, `own` from `ModelOwnPaint`. The body's paint half now has the sprite's measured paint on average, for generated and authored bodies alike (authored neutral bodies measure 184-207, not 235: their baked shading). Liveries and wrecks unchanged (no tint). |
| The paint hold | `identity.cpp` `IdentityForVehicle` | A car keeps its paint until another has held within 14 (per channel) for 45 frames (a respray). A new model, sprite or wreck state re-derives at once. |
| The log | same | `identity: vehicle [CHANGED model a->b \| CHANGED paint] obj <hex> [(the player's)] ...`: every change of the player's car is logged with its object. |
| The stand-in | `car_bodies.cpp` `g_lastBuilt` | Keyed by object and checked against the sprite and model it was measured for. |
| The paint half of a generated car | `tools/car_paint_resplit.py` (run on the cars archive, `assets/models`) | `import_assets.py` split each image-to-3D texture by a colour distance to the manifest's `paint_rgb` (the default sprite's paint). The generator rarely painted the body that colour: the 082 Jagular's body is sage green and its paint half was the whitewall tyres; 044's paint half held 15 % of its body. The tint could only recolour that half, so the 3D car kept the generator's colour whatever the sprite showed. The tool re-splits every generated pair by the body's own dominant hue (count-weighted hue histogram of the coloured, lit texels of both halves; the texels within 30 degrees, saturation >= 0.10, max >= 26 are the paint; an old paint texel of another hue goes back to the rest in its own colour), and makes the paint neutral: its luminance, scaled so the brighter half is 215 (the authored bodies' convention). The live tint then gives the body the sprite's measured paint with the generator's shading. Liveries (drawn untinted), authored atlases and wrecks are skipped; a second run changes nothing. 44 pairs changed. |

### 5.3 pm33 (the driven car "changes model"): what it was

The player's car never changed model. With the identity probe on (`out/fci_pm33a`, keys_pm33.sh, bil): 132 probe
lines of the player's car in classic, third and first person, one object, one model (`040_maurice`), one
fingerprint, through a crash (damage 382 -> 19 327 -> 25 000, burning). The "orange muscle car" of the report's
frame 044 is the parked 082 Jagular the Maurice lands on after driving off the level-4 roof (player z 4.00 -> 2.01):
for ~1.5 s after the impact (`view: car impact 3.41 blocks/s lost`, `camera clearance ... safety net moved 7 frames`)
there is no projected rectangle of the player's car in third person, and the first one after has corners far off
screen: the chase camera's eye is inside the Maurice's hull (back faces culled, so it is invisible) and the view
shows the car it hit. That is the chase camera (stream #4), not identity. The "silver sedan" two seconds later is
the Maurice itself: its generated texture's body sat in the untinted half (5.2, the re-split).
The `identity: vehicle CHANGED model` lines of the report were other cars: the game re-uses sprite objects for new
cars within seconds (a 150 s Downtown run logged dozens of `CHANGED model a->b` on recycled objects), and the record
re-derives correctly for each.

## 6. The sprite's paint from its remap texels, liveries, the seat bonnet, the parity check (FIX-CAR-IDENTITY-2, 9 Nov 2026)

Work orders pm40 (2u, ste bank vans), feel25 (2w, wil Minx), pm24 (2o, police), pm29 (2p, ambulance), the first-person
bonnet that read dark maroon on a car whose body was right, and the parity tool.

### 6.1 The sprite's paint: the texels the game's remaps recolour (feel25)

`MeasureSprite`'s paint, the mean of the brighter half of each hood/boot row, took in the highlight the sprite artist
painted on the body. The wil Minx in remap 26 has a deep red body (the remap's texels: 133,65,65) and measured
189,109,108; the 3D car took that as its paint and came out salmon pink. Now (`car_bodies.cpp` `Measured`,
`texture_store.cpp` `CarSpriteOtherImageFor`) the drawn sprite is decoded a second time in another of its palettes (its own
palette if it is drawn in a remap, else its first remap: CARI lists them). The texels whose colour differs are the paint:
a remap recolours exactly the paint ramp. The paint is their mean, or the mean of the saturated ones (saturation >= 0.3 in
either palette) when those are at least 30 % of them: the remap also moves pale trim (the bank van's roof panels). A car
with no remap keeps the brighter-half rule. The model's own paint (`ModelOwnPaint`) is measured by the same rule on its
side: the plain mean of its paint texels when the sprite's is a mean, the brighter half otherwise. The luminance floor
(`car_paint_floor_percent`) is still tested on the brighter-half value it was tuned on. Log:
`car body: sprite S paint from its remap texels (n of m opaque, k saturated, drawn in a remap | own palette): r,g,b
(brighter-half rule r,g,b)` and `models: <name>: own paint measured r,g,b mean r,g,b`.

Measured on the style's sprites (`assets-src/cars/sprites`, default against each remap): Minx remap 26 133,65,65 (was
~166,95,96); bank van default 59,82,115 and remap 36 70,99,85.

### 6.2 The G4 bank van is a painted car, not a livery (pm40)

The bank van (model 4) was in `Livery`: drawn untinted, in the generator's navy, while ste draws its sprite in remap 36
(dark green, pale mint roof). It is a painted car now. Its texture pair was re-split by its body's hue with
`tools/car_paint_resplit.py <models> --only 004 --min-sat 0.3` (the saturated navy body is the neutral paint half; the
pale roof panels and the white band stay in the untinted rest), and the record tints the body to the sprite's measured
paint like any other car: navy in its own palette (`tint 0.52,0.72,1.01`), green in remap 36 (`tint 0.61,0.87,0.74`).

Other liveries the game remaps (from the style's sprites): bus 11 (the stripe), cop 12 and SWAT 52 (blue to green in
remap 36), TV van 67 (whole body, six remaps), 84 (yellow to dark grey). They stay liveries: the TV van's generated art
is two-tone (sage upper, cream lower, tan roof) and 84's authored atlas is painted saturated yellow, so neither can be
tinted to the sprite. Seen in ste traffic: a light blue TV van in classic is khaki in third person (`fci2_tr1`, parity
WARN). Those need new art (VEHICLE-ART), then the same treatment as 004.

### 6.3 Police and ambulance tops repainted from the sprite (pm24, pm29)

`tools/car_livery_project.py <models> <name> --sprite <the default sprite>` locates every texel of a livery model's
texture pair on the mesh (triangles rasterised in UV space: position and normal per texel). A texel facing up
(`--min-up`) above the beltline (`--belt`) takes the sprite's colour at the same point of the footprint (model x across,
z along, onto the sprite's opaque box, nose at the bottom; orientation checked on the cop's light bar), plus its own fine
detail (luminance minus a blur, x0.6), where its blurred colour differs from the sprite's by more than `--tol` (70):
what already agrees (the ambulance's roof cross, the shield) stays. `--ends tail|nose|both` does the end faces from the
sprite's end rows (lamps and dark glass excluded; the nose catches the windscreen, so only `tail` was used). `--preview`
writes the top seen from above before | after | the sprite, and the end views.

| Model | Command | Result |
|---|---|---|
| 012 cop car | `--min-up 0.15` | 19 875 texels: the roof, bonnet and boot navy -> white with blue at the flanks, like the sprite |
| 034 medicar | `--ends tail` | 26 195 texels: the near-black rear deck, boot and rear panel -> cream |

### 6.4 The first-person bonnet (dark maroon on a car whose body was right)

The seat's bonnet (`BonnetSurfaceFor`) samples the body's colour where its rays hit, from `RgbFor`: a 64x64 average of
the base texture, its paint share `1 - alpha`, the colour assumed to be the paint's ("the see-through texels keep the
paint's RGB"). Since `car_paint_resplit.py` that is false: a re-split base keeps the generator's old colour under its
see-through texels and the neutral paint is only in the `_paint` twin, so the bonnet was the old colour times the tint
(on 044 Arachnid's bonnet: 62,32,33, dark maroon, for a sprite paint of 51,47,59). Also an 8x8-texel cell of an
image-to-3D atlas takes in the black gaps between islands. Now `RgbFor` keeps each cell's alpha-weighted colour at 256
cells across, and the hit colour is the base's opaque colour and the paint twin's own colour mixed by the share: 74,70,85
on the same bonnet (offline, same texture and tint), blue on the blue Arachnid in `fci2_idp_ste1` (`idp_car_3first`).

### 6.5 The parity check, per build (the owner's acceptance item 3)

`tools/identity_parity.py` measured nothing useful for cars: classic crops sat beside the sprite and third-person crops
read a car's dark rear (delta-E 30+ on cars that matched by eye). Fixed:

- **Classic rectangles** are the game's 640x480 screen, which the renderer draws as the centre of the frame at the render
  height's scale (`x' = W/2 + (x - 320) H/480`, `y' = y H/480`), not stretched to the width. Fitted on parked cars.
- **The probe's rectangle at the shot's moment**: interpolated between the probe lines either side of it (a moving car's
  nearest line was up to a second off); the traffic script logs the grab's start (`t0=`).
- **The dominant colour of a car**: k-means (k=4) in Lab, the largest cluster by count x (1 + chroma/25), near-black
  pixels (shadow, tyres, glass interior) dropped unless they are most of it. People keep IDENTITY-SYSTEM's rule.
- **The measure**: "paint delta", CIE76 with lightness at half weight (the 3D sun and sheen move lightness the sprite
  bakes in), limit 25, and the hue difference (limit 25 degrees) when both colours have chroma >= 15.
- **The first-person bonnet is probed** (`IdentityProbePoints`: the far rows of the seat's bonnet, as `mycar` view 2).
- **Traffic**: `gamerun/keys_fci2_traffic.sh` (he stands at the spawn, V cycles with shots in each view, `ROUNDS`)
  compares every car seen big enough in classic and again in third / first by its probe object, and reports per class
  (car, van, truck, bus, police, taxi, emergency, authored). `-e WARP=1` with `INI_SED='s/^scene_key=.*/scene_key=F10/;
  s/^scene_xy=.*/scene_xy=171,123/'` and `-e GTA2DX9_SCENE_NO_CAR=1` puts him on a busy wil street first (the spawn has little traffic).

Run it per build (one slot each, ~2.5 min):

```
# the player and his car (warp to the nearest parked car, enter), same moment in the three views
GTA2_DIRECT_KEYS=1 PRIO=1 FPS=0 STAGE=<stage> GTA2_GPU=<n> [SWAP_LEVEL=ste|bil] INI_SED='s/^warp_key=.*/warp_key=F9/' \
  gamerun/grun.sh idp_<n> 150 keys_identity_parity.sh -e GTA2DX9_IDENTITY_PROBE=1 -e SETTINGS_EXTRA=/work/bev_parity.settings
# traffic: one vehicle per class as it passes
GTA2_DIRECT_KEYS=1 PRIO=1 FPS=0 STAGE=<stage> GTA2_GPU=<n> SWAP_LEVEL=ste INI_SED='s/^force_wanted=.*/force_wanted=1/' \
  gamerun/grun.sh tr_<n> 170 keys_fci2_traffic.sh -e ROUNDS=16 -e GTA2DX9_IDENTITY_PROBE=1 -e GTA2DX9_IDENTITY_PROBE_EVERY=5
/mnt/gta2/gta2-linux/vreg/venv/bin/python tools/identity_parity.py out/idp_<n> out/tr_<n> --report r.md --sheet s.png
```

The keys scripts live in `gamerun/` (not in git); `linux/docker/keys_fci2_traffic.sh` is the tracked copy. The exit
status is the number of failures of the player and his car (the deterministic subjects). Traffic mismatches are WARN
lines (`--traffic-strict` counts them): the probe logs a car every few frames, and right after a V press the camera is
still settling, so a rectangle can sit off its car; the tool calibrates the probe-to-picture latency per view and run
(the offset at which the rectangles hold the most car), but read every WARN on the sheet before believing it. A third-
person crop of a car in a shadowed street reads dark; the paint delta weighs lightness at half, so a dark grey car
against a mid grey sprite passes. Occlusion (a car behind a building inside its rectangle) is not detected. The warp is
not deterministic: a session where he is not seated reports "not found in the classic frame"; run another.

Results (this build, private stage `stage_fcid2`):

| Session | Subject | Classic | Third | First | Result |
|---|---|---|---|---|---|
| `fci2_idp_wil1` | player | 20,13,4 | 33,31,29 | (no body on foot) | 4.8 pass |
| `fci2_idp_wil1` | his car, 068 van (authored) | 105,101,83 | 80,80,69 | (not probed before this build) | 6.2 pass |
| `fci2_idp_ste1` | player | 20,13,4 | 15,16,16 | | 4.8 pass |
| `fci2_idp_ste1` | his car, 044 Arachnid | 35,76,103 | 53,105,149 | bonnet 29,27,26 (crop was the dash; narrowed after) | 11.2 pass |
| `fci2_tr1` (ste traffic) | 012 cop car c0c8 | 188,212,228 | 185,209,232 | | 3.8 pass |
| `fci2_tr1` | 048 Meteor, 044 Arachnid | | | | 13.3-17.7 pass |
| `fci2_tr1` | 067 TV van | 79,120,142 | khaki/black | | WARN, real (art: 6.2) |
| `fci2_tr1` | 057 T-Rex | 30,98,66 | near-black | | WARN (not investigated) |
| `fci2_tr2` (ste traffic) | 7 sedans (5 models), a truck, the bank van c1f4 | | | | 10.9-24.1 pass; one ambulance WARN with its rectangle off the car |
| `fci2_trw2` (wil, `WARP=1` to 171,123) | 16 pairs: authored 063/068, U-Jerk, bank van, taxi, Romero, Schmidt | | | | 7 ok, 9 WARN: by eye on the sheet the taxi is yellow and the U-Jerk teal in both views; the WARNs are crops (classic boxes lag fast cars, dark street crops) |
| `fci2_trw1` (wil spawn) | red Minx (remap 26) | log: paint 133,65,65 (old rule 189,109,108), shown 133,65,65 | | | not filmed close: re-run feel25's demo |

### 6.6 Still short

- The remaining liveries the game remaps (TV van 67, 84; bus 11's stripe, cop/SWAT remap 36) need art before they can
  follow the sprite; the TV van is the visible one in ste.
- The repainted tops are the sprite's low-resolution colour with the model's fine detail: right colours, not AAA
  surfaces (no crisp panel lines where the generator's were dark, the cop's door shield and the ambulance's cross kept
  only where they already agreed). The cop's end faces were left (the sprite's end rows carry the light bar's colours).
- The textures changed in the cars archive (`assets/models`, not git): `004_g4_bank_van_0(_paint).tga`,
  `012_cop_car_0(_paint).tga`, `034_medicar_0(_paint).tga`. The cars archive needs repacking and their Remix prims
  rebuilding (`docs/remix-materials.md`, last section).
- 057 T-Rex's green sprite draws near-black in third person: not investigated.

## 7. Under Remix: the semi-truck red-orange in classic, brown in third person (FIX-REMIX-IDENTITY, 9 Nov 2026)

Defect `pt-remix-first-truck-classic-red-orange-cab-third-brown-maroon` (wil 164.5,149.5 at 13:00, filed on c836ec7).

**Remix was consuming the record; the record was brown.** The filer's log (`out/ptrmx7_wil`) has, at the classic and
third-person marks, `identity: vehicle obj 43d4f980 model 63 sprite 57 paint 97,67,63 -> 063_truck_cab tint
0.48,0.33,0.31 shown 98,68,63`. Vehicles were not left out of the Remix wiring: the 063 paint half
(`063_truck_cab_2_paint.tga`) has no layer prim, so it is drawn with the `BakedTint` copy of the record's tint (the
plain renderer's stage-1 factor in a texture). The cause was the brighter-half rule of the time: for the cab's sprite
(sprite 57, remap 28) the rows outside CARI's window rows are the black fifth wheel and chassis, and the bright
red-orange roof lies between the window rows. An offline emulation of that rule over `assets-src/cars/sprites`
reproduces every 063 record in the log to the unit (remap 28 97,67,63; remap 24 98,71,57; remap 05 59,75,60).

**Fixed by section 6** (c8ba78f, after the filer's stage): the paint is the mean of the texels the remap recolours,
matched against the model's plain mean. The same truck's record is now `paint 121,63,48 -> tint 0.95,0.49,0.38`
(`out/rid_truckD`, log `car body: sprite 57 paint from its remap texels ... 121,63,48 (brighter-half rule 97,67,63)`).

**Verified path traced** (`out/rid_truckD`: GPU 4, Ultra preset `rtx_premix_max.conf.extra`, the filer's point at
13:00, `GTA2DX9_IDENTITY_PROBE=1`): the remap-28 cab (obj 43d4f5fc) in classic and third person within 25 s. The
paint (saturated pixels, brighter half) of the classic sprite's body against the third-person door panel:

| | classic | third person | delta-E |
|---|---|---|---|
| before (the filer's frames, c836ec7) | 104,61,47 (L 31, hue 43, chroma 24) | 79,61,55 (L 27, hue 44, chroma 10) | 14.7 |
| HEAD (`rid_truckD`) | 109,63,52 (L 32, hue 39, chroma 24) | 100,64,56 (L 31, hue 38, chroma 18) | 5.8 |

Classic view: not touched (no code change; the record feeds only the 3D bodies).
**Still short:** the 3D cab is 25 % less saturated than the sprite (chroma 18 against 24: the clear coat's sky
reflection). This truck was not in the first-person frames of the run, and at 19:30 it was a far-field speck: no honest
dusk or night number for it. Two things were tried and dropped: a painted-roof rule for the old brighter-half
measure (156 of 668 sprites changed, none worse offline, but after section 6 it only moves the dark-paint floor test,
untested), and a global hue-cluster rule (87 sprites worse).
