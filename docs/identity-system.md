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
WARN). Those need new art (VEHICLE-ART), then the same treatment as 004. (Done for 67 and 84 by FIX-CAR-IDENTITY-3: section 8.3.)

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
- 057 T-Rex's green sprite draws near-black in third person: the paint split took the chrome (section 8.2).

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

## 8. The T-Rex, the TV van and the special agent car; the first-person bonnet re-checked (FIX-CAR-IDENTITY-3, 9 Nov 2026)

### 8.1 pm101: the first-person bonnet (wine red while the third-person body is lavender)

Filed on the afb3cb6 DLLs; the fix is section 6.4 (c8ba78f). Re-filmed on fafad27 (private stage, ste, seated in the
player's 044 Arachnid by warp + Return: `gamerun/keys_fci3_seat.sh`, a copy of `keys_identity_parity.sh` that goes back to
the door before Return; the original steps away and stays on foot). Pixels of the car's body: classic 56,53,67 (hue 253),
third 93,91,124 (hue 244), the seat's bonnet 110,111,135 (hue 238): the same violet-grey, lighter in 3D under the sun.
`identity_parity.py` passes the record (one fingerprint in the three views) but fails the classic crop at this spot: the
probe rectangle round the small dark car is mostly the olive pavement (90,98,71). bil (the green Maurice, F10 scene car):
green in classic and third; first person not filmed (F10 then Return twice left him on foot).

### 8.2 057 T-Rex near-black: the paint split took the chrome, not the body

Not the remap-texel measure (the log's paint 40,96,58 for a 30,98,66 green sprite in remap) and not the tint: the model's
texture pair. `car_paint_resplit.py` picked the body's hue from the histogram of every texel with saturation >= 0.1, and the
generator's chrome (bumpers, trim, whitewalls) reflects a pale blue sky: the peak was 215 (blue), so the paint half became
the chrome and the gold body (hue 35) went back into the untinted rest. The body texels of the base are mostly dark (86 % of
its opaque texels under luminance 40: the atlas' gaps and the shadowed panels), so with the chrome tinted green and the
body left the generator's dark gold, the car read near-black at street distance. Re-split from the pre-resplit original
with `--only 057 --min-sat 0.35` (the chrome is pale, the gold saturated): body hue 35, paint 28 759 texels (was 25 181
texels of chrome). Seen (`fci3_show1`, force_car_model 57 with force_car_paint): in the ste green 40,96,58 the body is
green, 59,123,93 from above (hue 151 against the sprite's 139); in the default gold 120,84,64 it is bronze, 109,95,84 (hue
27 against 21). The flank's brown pin-stripe and the roof's grey panel stay in the untinted rest.

### 8.3 067 TV van and 084: painted cars, not liveries

The TV van's sprite is one colour in each of its six remaps (tan default, light blue, red, white, blue, purple, green): one
body colour, not a livery. Its generated texture is two-tone (sage upper, cream lower, a tan roof). Re-split as one paint
with two new options of `car_paint_resplit.py`: `--hue 70 --hue-tol 60 --min-sat 0.05` (sage, cream and tan in one mask:
122 815 texels) and `--flatten 0.8` (the paint's large-scale shading, a blur inside the mask, pulled 80 % toward the level:
the two tones become one, the panel detail stays). 67 left `Livery()` (identity.cpp) and the resplit tool's livery set.
Seen: light blue 78,105,140 all over in `fci3_show1` (forced paint); in ste traffic (`fci3_tr1`, live remaps) a tan TV van
one tan from the roof to the sills (was sage over cream), and a light blue one in classic whose third-person frame fell in
the BUSTED cut. The wheels' cream hubcaps are in the mask and take the tint.

084 draws 014 Eddy's mesh and textures since VEHICLE-ART (manifest "84": "014_eddy"), and its sprite is the Eddy's
(yellow-green; dark grey in remap 2). As a livery it drew the Eddy untinted; it is a painted car now. Seen: yellow-green
in `fci3_show1` (force_car_model 84, force_car_paint 95,107,10). In the dark grey of remap 2 (`fci3_show2`) its roof
stayed yellow: the Eddy's generated body is red with a yellow roof panel, and the earlier re-split (body hue 355) left the
roof in the untinted rest. Re-split from the pre-resplit original as one paint, `--only 014 --hue 30 --hue-tol 42
--min-sat 0.15 --flatten 0.5` (red and yellow in one mask, the roof kept a little lighter, as the sprite's is): 90 770
paint texels. This changes the 014 Eddy in traffic too (its sprite: yellow-green body, lighter roof).

The textures changed are in the cars archive (`assets/models`, not git): `057_t_rex_0(_paint).tga`,
`067_tv_van_0(_paint).tga`, `014_eddy_0(_paint).tga` (the originals and the pre-resplit 057/014 in `/mnt/gta2/gta2-linux/backup_fci3_textures`). Their Remix prims: section 8.5.

### 8.4 Still short

- The repainted tops of 012/034 (section 6.3) and the re-split bodies are the sprite's flat colour with the generator's
  detail: right colours, not AAA paint (no crisp panel lines, no clear-coat depth beyond the Remix layer's class maps).
- The TV van's hubcaps take the body tint; the T-Rex's pin-stripe and roof panel stay the generator's colours.
- The parity tool's classic crop fails on a small dark car on bright pavement (8.1); traffic WARN lines are still crops
  (section 6.5).

### 8.5 The Remix prims of the repainted and re-split textures

The gta2hd layer is keyed by each model texture's XXH3 hash, so the textures changed in sections 6 and 8 had no prims.
Built for the six pairs (`004_g4_bank_van_0`, `012_cop_car_0`, `034_medicar_0`, `057_t_rex_0`, `067_tv_van_0`,
`014_eddy_0`, each with its `_paint` twin) into a scratch layer, from a scratch models folder holding exactly the shipped
textures, and merged into `package/rtx-remix/mods/gta2hd` (docs/remix-materials.md, "Car textures changed by
FIX-CAR-IDENTITY-2 and -3"):

    flock /tmp/gta2-gen.lock taskset -c 0-4 nice -n 10 <venv>/python tools/remix_model_materials.py <scratch models> <scratch layer> \
        --src <workspace>/assets-src --pattern '^(004_g4_bank_van|012_cop_car|034_medicar|057_t_rex|067_tv_van|014_eddy)_0(_paint)?\.tga$'
    cp <scratch layer>/mod.usda <scratch layer>/mod_wet.usda      # model prims are the same in both
    <venv>/python tools/remix_layer_merge.py <scratch layer> package/rtx-remix/mods/gta2hd <scratch layer>/model_prims.txt

12 prims inserted (none replaced: the old-hash prims of these cars stay, inert), 58 map files, model_prims 787 -> 799;
`git diff` of the three texts is additions only; `remix_materials.validate`: 3449 prims, no problems. **Not seen path
traced**: no Remix frame of these cars was taken by this stream. The DDS maps ship in `remix_mod_gta2hd.zip` (repack).


## 9. The paint apply: a dark saturated paint stays saturated on the lit body (FIX-CAR-IDENTITY-4, 10 Nov 2026)

feel25 again (DEFECT-TRIAGE rejected c8ba78f): the record was right (`shown 133,65,65`, the red Minx sprite's mean) but
the drawn body was salmon pink, lit bonnet 234,184,190 (saturation 0.21) against the classic 181,92,90 (0.50).

### 9.1 What it was (measured, `out/fci4_minx1`, `out/fci4_minx2`)

- **The tint's reference.** tint = sprite paint / the model's own paint. Since c8ba78f the model's own paint is the
  plain mean of the texels its paint meshes cover. An authored body imports an opaque paint atlas (013, 063, 068:
  `authored-paint-opaque-base-twin`) that covers the windows, tyres, chrome and trim too: 013's mean is 108 while its
  panels sit at ~230. 133,65,65 / 108 = **1.23**,0.60,0.60 drove the panels to 283,139,139, clipped by the texture
  stage to 255,139,139: pink on every lit face. The same happens to any bright paint (013 yellow: tint 1.85,1.67,0.46).
- **The sheen.** The paint's specular exponent 26 is broad enough to lay ~+20 of white over a whole lid seen from the
  classic camera (sun half-angle ~19 deg: 0.33 x cos^26 = 0.08): a pastel wash on top of the clip.
- **The lids' light** (found after FIX-FX-3's 4ecf174 landed): the bodies are now lit by the world's sun (24 degrees up
  by default) instead of a fixed sun 51 degrees up, so a lid gets 0.35 ambient + 0.78 x sin 24 = 0.67 of light instead
  of 0.96 and every body drew ~0.7 as bright as before (same tint, `out/fci4_paint4` against `out/fci4_paint3`).

### 9.2 What changed

- `ModelOwnPaintPanel` (model_store.cpp, measured with the other own-paint numbers, once per model on the worker
  thread): the **panels as the car is seen from above** — the paint texels at or over half the 90th-percentile level
  (not windows, tyres, trim), each weighted by how much its triangle faces up after the node's rest transform (the
  sprite is the top view) — and the 97th-percentile level of those up-facing texels (`top`). Logged as
  `models: <name>: own paint measured ... panels r,g,b top N`.
- `DeriveVehicle` (identity.cpp): for a remap-measured paint the reference is the panels; the tint is scaled
  **down uniformly** when texel x lid light x tint would pass 250 in any channel on the brightest lid texel (hue and
  saturation kept, a little lightness lost on very bright paints); a **gain** gives back what the 3D light takes from
  a lid: 1.25 at the lid light 0.96 it was measured under (gain 1 drew the Minx 104,49,54 against its sprite's
  133,65,65, `out/fci4_paint2`), scaled by 0.96 / the lid's actual light (car_bodies.cpp, from the sun the bodies are
  lit by; 1.0 under Remix, where the tint is albedo for the path tracer). The dark-paint floor (FIX-CAR-RENDER) is now
  a least level, not a second multiply on the gain. `shown` is the colour the lit body reads as (without the gain).
- car_bodies.cpp: the paint sheen's exponent **50** (a highlight, not a wash); the dark-paint sheen still broadens
  toward 12 with darkness.
- Devtools for same-spot A/B (re-read every 60 frames, re-derive every car): `paint_ref` (1 new, 0 the c8ba78f mean),
  `paint_gain_percent` (125), `paint_spec_power` (50); `force_car_paint=R,G,B[,r,g,b]` now stands for a remap-measured
  sprite paint (mean, and the brighter half the floor tests), so `force_car_model=13` + `force_car_paint=133,65,65,189,109,108`
  is the wil red Minx's record. Probe: `gamerun/keys_fci4_paint.sh` (`fci4_paint.py`: the player's stopped car,
  `MODELS`, `PAINTS`, `MODES`, `POSES=top` = the classic camera); measure with the paint mask (the pixels that change
  between two paints) as in section 9.3.

### 9.3 Measured (frames opened; top pose = the classic camera)

The red Minx (013 forced, paint 133,65,65), body pixels by paint mask:

| Build | Body mean | Lit lids (top quarter) | Saturation (body / lids) |
|---|---|---|---|
| classic sprite (reference, feel25 triage) | 133,65,65 | bonnet 181,92,90 | 0.51 / 0.50 |
| c8ba78f rule, fixed sun (`fci4_minx2`, `fci4_paint1`) | 174,93,102 / 185,98,107 | 243,136,149 | 0.47 / 0.44 |
| this change, fixed sun (`fci4_minx2`) | 130,62,68 | 180,85,93 | 0.53 / 0.53 |
| this change, world sun (`fci4_paint7`, final) | 118,55,60 | 160,74,82 | 0.54 |

Evidence sheet: `defects/evidence/fci4_feel25_minx_classic_old_new.png`. Across hues and models (final build,
`out/fci4_paint7`; old rule from `out/fci4_paint1`), L* of the body against the sprite paint's, hue difference:

| Model | dark red | navy | black | yellow | green | white |
|---|---|---|---|---|---|---|
| 013 Minx (authored), old rule | +44 % | +103 % | +305 % | +6 % (hue 11) | +45 % | -6 % |
| 013, this build | -13 % | -3 % | +8 % | -15 % | -10 % | -20 % (lids 221,228,237) |
| 018 Shark (generated), old rule | +39 % | +101 % | +318 % | +9 % | +36 % | -3 % |
| 018, this build | +6 % | +23 % | +65 % | -4 % | +8 % | -12 % |
| 000 Romero (generated), this build | -7 % | +6 % | +33 % | -21 % | -5 % | -26 % |
| 063 truck cab (authored), this build | +7 % | +24 % | +60 % | 0 % | +9 % | -8 % |
| 040 Maurice, old rule / this build | -65 % / -26 % | -59 % / -16 % | | -58 % / -40 % | -62 % / -23 % | -56 % / -43 % |

Hue within 7 degrees of the sprite for every model and paint (old rule: up to 11); saturation 0.52-0.59 against the
sprites' 0.50-0.51 for the chromatic paints. Classic: `tools/vreg/vreg.sh stage` 31 PASS, `spawn_classic` 0 tiles.
No `identity` share in any slow-frame `car parts (ms)` line in the six traffic sessions (`out/fci4_tr_*`); the
own-paint measurement (now with the up-facing raster) is 13-50 ms per model on the worker thread, once.

### 9.4 Still short

- **Black and navy** on the generated/authored bodies other than 013 read lighter than the sprite (black +33..+65 %,
  navy up to +24 %): the dark-paint floor (FIX-CAR-RENDER pm3: a near-black body must keep its shape in 3D) holds them
  up on purpose. Parity says lower it; the pm3 look says keep it. Not changed here.
- **040 Maurice** (and 036 Schmidt): the lids draw darker than the measured panels for every paint (their up-facing
  paint texels in the drawn textures are ~75-100): a paint-split/art matter, written on the feel25 order for VEHICLE-ART.
- **Model spread**: the generated bodies' baked light differs per model (018's roof texels sit at 255), so one sprite
  paint lands -13..+7 % L* across 013/018/000/063. Bright paints (white, yellow) lose up to 26 % on the body mean
  because a lid can not go past white; their lids reach the sprite's highlight.
- The 3D red still reads a touch cooler than the sprite (hue 355 against 0: the frame's sky multiply) and the authored
  texture's speckle shows; the sprite's painted highlights (the bright bonnet spot) are not reproduced by the light.
- Traffic parity (`out/fci4_tr_{old,new}_{ste,wil,bil}`, before the world-sun rebase) stays noisy (crops of dark
  street, occluded cars): read the sheets, not the WARN count.

### 9.5 The per-build parity run (one command)

    GTA2_GPU=<n> tools/identity_parity_run.sh <stage dir> [name]

Queues two sessions on the stage through `gamerun/grun.sh` (~9 minutes of one slot) and writes `out/<name>_parity.md`;
the exit status is the number of failures, so DEFECT-TRIAGE and the restage gate (`linux/docker/restage.sh`, after
`stage_smoke.sh`) can call it on a candidate stage and refuse on a non-zero status:

1. `keys_identity_parity.sh` (section 6.5): the player on foot and in the car the warp key seats him in, classic /
   3D at the classic camera / third / first at the same moment; `tools/identity_parity.py`: one fingerprint per entity
   across the views, colours against the classic sprite, the car's silhouette (IoU).
2. `keys_paint_parity.sh` + `paint_parity_probe.py` (tracked in `linux/docker`, copied into `gamerun/` when missing): the
   player's stopped car forced to one model per body class (`PARITY_MODELS`, default 13 authored sedan, 0 and 18
   generated, 63 authored truck cab, 68 authored van), painted as a sprite of six colours (dark red, navy, black,
   yellow, green, white), seen from the classic camera's pose (regression camera); `tools/paint_parity.py`: the paint
   pixels (those that change between two paints) against the sprite paint: hue FAIL over 15 degrees, lightness WARN over
   10 % and FAIL over 25 % for the chromatic paints; black, navy and white are reported (the dark floor and white's
   ceiling, 9.4), never failed. This half is deterministic (forced model and paint, fixed camera): it measures the paint
   apply itself, where the traffic probe (6.5) measures whatever passes.

Liveries (cop, taxi, bus, ambulance) draw untinted and are not in the paint half: their parity is the record check in
(1) and the traffic sessions of 6.5. Known FAILs on 10 Nov: 040 Maurice's lids (art, 9.4) if it is added to the list.


## 10. The paint is a function of (sprite, palette); liveries take the lid light (FIX-CAR-IDENTITY-5, 10 Nov 2026)

Work orders pmt4 (2g1, bil F10 car brown in third, green in classic, first-person bonnet brown then green in one drive),
pmt5 (2w3, the identity half: the wil taxi ochre in third person), ptm1 (2w2, the identity half: the jacked bank van).

### 10.1 pmt4: what it was

The record's paint was measured from the **drawn** sprite record (`car_bodies.cpp` `Measured`, cached by sprite and device
texture), and the record kept a car's paint by the object it is drawn for unless a new one held for 45 frames
(`IdentityForVehicle`, the feel9 hold). Two inputs could move it inside one drive:

- **The game re-uses vehicle objects.** The bil F10 scene car took object slot `…0f98` in every session; in the filer's
  session that object had been a brown Maurice (sprite 35, another remap) drawn in 3D minutes before. Same model, same
  sprite: "the same car", so the record held the brown paint for the green car until a green re-measure had held for
  45 frames of 3D drawing, ~10 s into the drive (`identity: vehicle CHANGED paint obj 3d220f98 (the player's) ... paint
  38,57,37` at 01:54:22, `out/pmt4_bil`). Classic drew its own remap (green) all along. The first-person bonnet takes the
  record's tint, so it was brown in the round before the change and green after.
- **The drawn art changes with damage.** Dents, burning, doors and lamps are pixel deltas on the drawn record, and the
  paint was re-measured from them (`fci5_pmt4c`: 38,57,37 -> 37,55,36 with dents; the filer's change came 6 s after the
  car caught fire).

### 10.2 What changed

| Piece | Where | What |
|---|---|---|
| The paint from the clean art | `texture_store.cpp` `CarSpriteCleanImages`, `car_bodies.cpp` `Measured` | The sprite's own style art (the SPRG indices, no deltas) decoded in the palette the car is drawn in and in the other palette the remap rule compares with. The paint (remap texels' mean, and the brighter-half rule for the floor) is measured from those: a pure function of (sprite, palette), the same for every car in that remap, every frame, every session, dented or burning. Log: `car body: sprite S palette P paint from its remap texels (clean style art, ...)`. `GTA2DX9_CLEAN_PAINT=0` measures the drawn record as before (A/B runs). `PaletteColours` returns one shared buffer: copy the first palette before asking for a second. |
| The palette in the record | `identity.h` `SpriteRef::palette`, `identity.cpp` `IdentityForVehicle` | The palette (the remap the classic view draws) is part of what makes it the same car. A record not drawn for 30 frames whose palette differs (a re-used object) is re-derived at once; a car drawn all along whose palette changes (a respray) holds the new one for 45 frames, as a paint change did. Log: `identity: vehicle [CHANGED palette] ... fp <hex> palette P`. A forced paint (`force_car_paint`) has palette -1. |
| The driven car's paint input | `car_bodies.cpp` | `identity: driven car art obj O sprite S palette P pixels .. art .. measured r,g,b damage D fire F`, each time the driven car's art changes (200 lines at most): what the record of the player's car is fed. |

### 10.3 Measured (frames opened)

- `out/fci5_pmt4n2` (keys_pm130.sh, the filer's script, bil, this build): the player's Maurice `palette 184 ... measured
  38,57,37` from its first 3D frame to the end, through dents and fire (damage 0 -> 20 395, fire stage 3), one record
  (`fp 34f7bb7b palette 184`), no CHANGED line. Frames d1a/d1c (third), d2a/b/c (first: bonnet), d3a/b/c (classic): the
  same dark green in all nine.
- `out/fci5_idpbil1` (`gamerun/keys_fci5_idp_bil.sh`: the parity cycle with the F10 car, two rounds in it): the car's
  probe lines carry one fingerprint in classic, third and first in both rounds. Body colour by the car's hue band inside
  the probe rectangles (the parity tool's k-means took the pavement in this classic crop and the black ground in the
  third-person one; read the sheet): classic 31,55,35; third 32,54,36 (CIE76 1.6) in both rounds; first-person bonnet
  31,54,36 (1.4) in round 2 and 24,40,27 (8.3, same hue 135, the car parked in shade) in round 1. The record's paint
  38,57,37 is 2.4 from the classic pixels.
- Classic: `tools/vreg/vreg.sh stage` (`out/vreg_fci5_b`): `spawn_classic` PASS, 0 changed tiles. The one FAIL
  (`yakuza1_street`, 27 tiles) and 4 WARNs are window panes and figures (FIX-WORLD-7's sky in the panes and the
  figure/first-person shots, newer than the goldens), no car in those frames.

### 10.4 pmt5: a livery takes the lid light too

A livery (taxi, cop, ambulance, bus ...) took tint 1 and no gain, while a painted body gets `paint_gain_percent` x 0.96 /
the lid's light (~1.79 at the default world sun, section 9.2): every livery drew ~0.56 of a painted body's level. The 051
taxi's authored paint texture is 193,130,32 (its panels 200,135,33) against the sprite's 206,130,33: the albedo is right,
the light was not given back. `DeriveVehicle` now gives a livery the same gain, uniform (its colours and markings are
kept), under the same no-clip cap; the draw sends a livery whose tint is not 1 through the tint stage like a painted body.
Not under Remix (gain 1: the tint is albedo for the path tracer), not for a devtools-forced model without a forced paint,
not for wrecks. `[devtools] livery_gain=0` turns it off for same-spot A/B (re-derives every car).

Measured (`out/fci5_pmt5b`, own car forced to each model at the street warp, `livery_gain` 0/1 at the same pose; the body is
the sprite's hue band; evidence `defects/evidence/fci5/pmt5_*`): 051 lit quarter 76,52,9 -> 138,93,16, L* against its
style sprite -72 % -> -45 % (hue 5 deg); 056 -64 % -> -34 %; 034 -34 % -> -18 %; the cop's white roof reaches white without
clipping a panel. Still short: a tinted yellow 013 at the same pose reaches its sprite (lit 200,189,40 vs 200,180,50), the
051 not: the remaining gap is how the authored body is lit at that pose (a shadow band over its front, the lids), on the
order for VEHICLE-ART-10.

### 10.5 ptm1: the bank van's record

With the paint from the clean art in the drawn palette, the bank van's record is 70,99,85 when the classic view draws it in
remap 36 (dark green) and 59,82,115 in its own palette (blue): `assets-src/cars/sprites/004_g4_bank_van_{default,remap36}.png`
by the same rule, offline. On ART-10's new 004 (`out/fci5_ptm1a`) the renderer draws the cab, flanks and rear in that
green (hue 11 deg, saturation 0.27 vs 0.29; lit cab roof 39,62,57: paint delta 9.5) and blue for the other palette (hue
2 deg). The body reads ~23 % darker than the paint, like the other new authored kits (below).

### 10.6 The gate: two fresh sessions, one vehicle per body class (acceptance 2 and 3)

`tools/identity_parity_run.sh` now queues three sessions:

1. `keys_identity_parity.sh` **twice**, two fresh sessions at the same spawn. `tools/identity_parity.py` checks, across
   them: the player's fingerprint, **his car's** fingerprint (the parked car the warp key seats him in), and for every
   vehicle input (model, sprite, palette) one paint and one fingerprint. The across-session vehicle check had compared 0
   records since FIX-CAR-IDENTITY added `obj <hex>` to the log line (the pattern no longer matched); fixed.
2. `keys_paint_parity.sh` with one model per **body class**: 0 generated, 13 / 63 / 68 authored, 18 authored carkit, 4
   remapped (painted, also in its own sprite's two paints: `EXTRA_PAINTS=4:van36,vanblue`), 51 livery and 74 wreck (their
   own colours: one frame each, `ONE_PAINT_MODELS`). `tools/paint_parity.py` reports a class column; painted bodies against
   the paint they were given (hue FAIL over 15 deg, lightness WARN over 10 %, FAIL over 25 % for chromatic mid paints);
   **liveries** against their style sprite's dominant saturated hue (`--sprites`, `assets-src/cars/sprites`; hue FAIL,
   lightness WARN: their colours are their art); **wrecks** against the wreck sprite's dominant colour (paint delta, FAIL
   over 25). The paint mask is now what changes against the first paint in every other paint's frame (the largest change
   took in passers-by: the van's body read 96,103,93 for a 70,99,85 paint).

The car's colour in `identity_parity.py`: the k-means took the pavement inside a classic sprite quad (73,77,63) and the black
ground under a third-person car (11,12,10) for the bil Maurice (`out/fci5_idpbil1`, sheet opened: green in all three views).
For the player's car it now takes the pixels within 25 deg of the record's hue (`shown`, the classic sprite's paint) with at
least 80 % of its chroma when there are enough of them, else the k-means as before (a 3D body of another hue falls back, so
a hue fault still shows). Same frames: classic 33,59,36 vs third 32,54,36 (CIE76 4.0), first 31,54,36 (3.9).

First gate run on this build (`out/fci5_gate1_parity.md`, wil spawn, private stage of HEAD da4b79d + these commits):

| Check | Result |
|---|---|
| Two fresh sessions | player `ee58ea54` and his car (`068_van`) `e275a4ff` in both; 64 vehicle inputs (model, sprite, palette), 18 seen in both, 0 with more than one paint or fingerprint; 0 record/view failures |
| Player / his car, classic vs third | 18,12,4 vs 85,80,72 (paint delta 15.3) / 106,101,83 vs 75,74,60 (6.4) |
| generated (000) | hue <= 7 deg, L* -7..+5 % on the chromatic paints (yellow -21 % WARN) |
| authored (013, 063, 068) | hue <= 7 deg, L* -18..+14 % (WARNs only) |
| authored carkit (018) | hue <= 7 deg, **L* -35..-41 % FAIL** |
| remapped (004, ART-10's new van) | hue 2 deg (its blue sprite paint) and **17 deg (its remap-36 green) FAIL**, **L* -27..-34 % FAIL** |
| livery (051) | hue 6 deg, L* -45 % (WARN: its own colours) |
| wreck (074) | 15,14,12 vs the wreck sprite's 27,22,20 (L* 4 vs 8, WARN) |

The bil F10 car (section 10.3) passes the same checks in two fresh sessions (`out/fci5_idpbil1`, `fci5_idpbil2`).

### 10.7 Still short

- **The new authored kits read dark**: 018 (carkit) -35..-41 %, 004 -27..-34 %, 051 -45 % at the classic-camera pose, where
  the older authored bodies (013, 063, 068) and the generated 000 land within -21..+14 %. The record and the tint are the
  same rule for all of them; the kits' paint textures measure near white (018: 235 / panels 197) and their stored normals
  agree with their winding (98-100 % of the paint area). The 018 white body draws flat mid grey with no sun gradient
  (`out/fci5_base_paint` pt_top_018_white_new against 013): how these kits are lit, for VEHICLE-ART-10 with the renderer.
- **The van's remap-36 green** lands 11-17 deg toward teal at -24..-28 % L*: a low-chroma green under the sky's blue
  ambient; its blue paint lands at 2 deg.
- The re-used-object case of pmt4 cannot be forced in a run; it is closed by construction (palette in the record, clean art)
  and visible in the log (`CHANGED palette`, `driven car art`).
- First person on foot has no body to probe; Remix not run for these changes (the livery gain is off under Remix by design).
