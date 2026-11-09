// IDENTITY-SYSTEM (docs/identity-system.md): one appearance record per entity (the player,
// every pedestrian, every vehicle), owned by this module and consumed by every 3D path.
//
// The classic (top-down) view draws the game's own sprite and is not touched: the sprite is
// the REFERENCE. A record is built from exactly what the classic view draws for the entity
// (the remap of the palette the ped sprite is drawn with, the car's model number and the
// paint measured from its sprite art) and from the game's own ids, never from a heap address,
// a clock or a per-session random. The 3D model, its clothing / paint tints and its build are
// a pure function of that, so the two views cannot disagree and a session cannot reroll it.
//
// Rule: no draw path picks a model or a colour for an entity except through this module
// (ModelForPedestrian / ModelForVehicle / PedZoneTints / PedRemapTint / PedTypeBuild are
// called from identity.cpp only).
#pragma once

#include <cstdint>

struct IDirect3DDevice9;

namespace gta2dx9 {

struct Model;

enum class IdKind : uint8_t { Player = 0, Ped = 1, Vehicle = 2 };

// What the classic view draws for the entity: the reference.
struct SpriteRef {
    int remap = -1;        // ped: remap of the sprite's palette (-1 none); player: 25 unless a devtools override
    int body = 0;          // ped: sprite set, frame / 158 (0 common body, 1 GANG_GRAPHIC, 2+ EMERG_GRAPHIC)
    int carModel = -1;     // vehicle: the game's model number (CARI order), after the wreck mapping
    int carSprite = -1;    // vehicle: the car sprite the classic view draws
    float paint[3] = {0, 0, 0};   // vehicle: the paint measured from that sprite's art
    bool forcedModel = false;     // vehicle: a devtools model override (keeps the model's own paint)
    int wholeModel = -1;          // vehicle: the game's model number when it is not a wreck (-1 a wreck or unread)
};

struct IdentityRecord {
    IdKind kind = IdKind::Ped;
    uint32_t seed = 0;     // ped: the game's ped id (Ped +0x200), or a hash of (remap, body) when unread
    SpriteRef ref;
    const Model* model = nullptr;
    // People: the colours the avatar is drawn with.
    bool zoned = false;         // per-zone tints (shirt, trousers, hair)
    float zone[3][3] = {{1, 1, 1}, {1, 1, 1}, {1, 1, 1}};
    bool zoneHair = false;
    bool tinted = false;        // one whole-clothing tint (a type's colour or a civilian's everyday clothes)
    float tint[3] = {1, 1, 1};
    bool clothes = false;       // the tint is a civilian's everyday-colour clothes (crowd variety)
    float height = 1.0f, width = 1.0f;   // build (crowd variety x type build; 1 for the player)
    // Vehicles: the paint over the model's own.
    bool livery = false;        // the model keeps its own paint (cop car, taxi, ...): no tint stage
    float paintTint[3] = {1, 1, 1};
    float darkness = 0.0f;      // 0..1: a dark body's sheen (car_bodies.cpp material)
    // VEHICLE-ART-3 (vr-wrecks-flat-dark-pancakes): a burnt-out car (models 72..81) is drawn as the
    // charred copy of the car it was (`model` is that copy): wreckOf is the whole car's model number,
    // remembered from this vehicle's last whole sighting, else the wreck class's stand-in.
    bool wreck = false;
    int wreckOf = -1;
    // The colours the 3D view should show where the classic view shows the sprite's
    // (people: shirt and trousers; vehicles: the body paint). 0..255. For the checks.
    float shownTop[3] = {0, 0, 0}, shownBottom[3] = {0, 0, 0};
    // A hash of everything above except the cache key: equal across sessions for the same entity.
    uint32_t fingerprint = 0;
};

// The player: a dedicated record. Never dealt from a crowd pool, never seeded.
const IdentityRecord& IdentityForPlayer();
// A pedestrian. `cacheKey` is only a cache key (the sprite object), never a seed. `pedId` is
// the game's id (-1 when unread). `palette` is the physical palette the classic view draws his
// sprite with (its TextureRecord's; -1 unknown), `spriteFrame` his sprite frame.
const IdentityRecord& IdentityForPed(uintptr_t cacheKey, int pedId, int palette, unsigned spriteFrame);
// A vehicle: `cacheKey` the sprite object (cache only).
const IdentityRecord& IdentityForVehicle(uintptr_t cacheKey, const SpriteRef& ref);
// The car model number the classic view's sprite stands for: a burnt-out car keeps its model
// number but the game swaps its sprite for one of the ten wreck sprites 65..74 (CARI 72..81).
int IdentityVehicleModelNumber(int gameModel, int sprite);
// The game's wreck class of a whole car model (CARI's wreck byte: model 72 + class), -1 none;
// and the whole model a wreck class stands for when the car was never seen whole.
int IdentityWreckClassOf(int wholeModel);
int IdentityWreckStandIn(int wreckModel);

// The hero's avatar (the manifest's "pedestrian"), which no crowd record may get.
const Model* IdentityHeroModel();

// Whether a figure's record tints are baked into its textures (model_store ModelSetBakeTints)
// rather than applied by the stage-1 texture factor: under RTX Remix, or GTA2DX9_IDENTITY_BAKE=1
// (=0: never). docs/identity-system.md 2.4.
bool IdentityBakeTints();

// Settings, from their owners' ini readers.
void IdentitySetCrowdVariety(bool on);     // [crowd] variety
void IdentitySetPaintFloor(float floor);   // [renderer] car_paint_floor_percent, as 0..255 luminance

// Once a frame (records not seen for a while are let go; the probe's per-frame state).
void IdentityBeginFrame(uint32_t frame);

// GTA2DX9_IDENTITY_PROBE=1: the parity probe (tools/identity_parity.py). The subject's
// record and its screen rectangle in the current view, logged every `every` frames.
bool IdentityProbeOn();
// view: 0 classic, 1 third, 2 first. what: "player", "car", "sleeve", "bonnet".
bool ProbeDue(const char* what, const void* object, int view);
void IdentityProbeRect(const char* what, const void* object, const IdentityRecord& rec, int view, float x0, float y0, float x1, float y1);

// The projected rectangle of `model` placed by `world` (row-vector, D3D) under the device's
// current view, projection and viewport, logged as IdentityProbeRect.
void IdentityProbeModel(IDirect3DDevice9* device, const char* what, const void* object, const IdentityRecord& rec, const Model& model,
                        const float world[4][4], int view);
// The classic view: a sprite quad the game draws for `object` (screen-space vertices, stride
// 0x20, x and y first). Logged for the player and for every car (`isCar`).
void IdentityProbeSprite(const void* object, bool isCar, const float* vertices, int corners);
// The record a vehicle's sprite object last had (null: never drawn in 3D this session).
const IdentityRecord* IdentityLookupVehicle(uintptr_t cacheKey);
// The probe's subjects, set by their owners each frame.
void IdentityProbeSetSubjects(const void* playerObject, const void* playerCarObject, const IdentityRecord* playerCar);

}  // namespace gta2dx9
