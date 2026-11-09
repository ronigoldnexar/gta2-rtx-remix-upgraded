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

So the record drives Remix through the same two channels as the plain renderer. `tools/identity_remix_check.py`
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
- Cars: 303 of 323 textures pass; 20 have no prim or a prim whose albedo no longer matches the texture drawn.
- None of this makes the albedo grey: a texture without a prim keeps its colour. So the grey-clay figure
  (`pt-remix-third-figure-single-tone-grey-clay-no-albedo`) is not a missing albedo file. It needs a Remix
  capture of the figure's draw.

The layer is rebuilt by `build_remix_mod.sh` (REMIX streams); the check tells that stream which identity
textures are missing.
