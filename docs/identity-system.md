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
