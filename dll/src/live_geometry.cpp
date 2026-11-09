#include "live_geometry.h"
#include "boarding.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <deque>
#include <set>
#include <list>
#include <memory>
#include <utility>
#include <map>
#include <string>
#include <unordered_map>
#include <vector>

#include "../../src/gta2_map.h"
#include <windows.h>
#include <mmsystem.h>   // QB-29: the reload clicks (waveOut)
#include "../../src/renderer.h"
#include "cache_warmup.h"
#include "car_bodies.h"
#include "compat.h"
#include "game_access.h"
#include "gibs.h"
#include "log.h"
#include "overlay.h"
#include "remix_api.h"
#include "remix_lights.h"
#include "texture_store.h"
#include "time_of_day.h"
#include "view_modes.h"
#include "model_store.h"
#include "ragdoll.h"
#include "map_objects.h"
#include "explosion_fx.h"

namespace gta2dx9 {
namespace {

constexpr DWORD kWorldFvf = D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1;
constexpr int kGameVertexFloats = 8;
constexpr int kUvU = 6;
constexpr int kUvV = 7;

// How far a sprite is lifted off the floor it stands on.
//
// GTA2 itself lifts them by nothing at all. Its object pass puts all four
// corners of the quad at exactly the level of the block underneath - read back
// out of the game's own vertex shadow, a pedestrian at cell (158,138) comes out
// as (158.2656 138.7500 2.0000) (158.2656 138.2500 2.0000) (158.7344 138.2500
// 2.0000) (158.7344 138.7500 2.0000), all four at 2.0000, while the floor there
// is the lid at 2.0. Perfectly coplanar.
//
// It gets away with that because its renderers never depth test: 3dfx.dll calls
// grDepthBufferFunction(GR_CMP_ALWAYS) and imports no grDepthMask or
// grDepthBufferMode at all, and d3ddll.dll never sets ZENABLE, ZWRITEENABLE or
// ZFUNC. Both are pure painter's algorithm - the map is drawn level by level and
// the object pass paints over the floor it just laid down. That is also why the
// screen-space overlay pass never had this problem: it replays submission order
// with no depth test, which is the original behaviour exactly.
//
// Turning a sprite into real 3D geometry is what breaks it. Coplanar surfaces
// have no defined order in 3D: the depth test drops them, and under Remix the
// ray hit is ambiguous however the raster state is set, so ZFUNC_LESSEQUAL would
// fix the raster view and still leave the path tracer fighting itself.
//
// So the lift is ours and has to be justified rather than guessed.
//
// A quarter of a ground texel - 1/256 of a block, the first value used here -
// is enough to break the coplanarity and nothing more. That settles flat
// ground, and does nothing at all for a slope: GTA2 gives all four corners of
// the quad the object's single level, so on a ramp a horizontal quad cuts
// straight through the lid and the uphill half of the sprite disappears into
// it. A sprite of length L on a gradient g sinks by up to g*L/2.
//
// Measured over the shipped districts, of the surfaces a sprite can actually
// stand on (ground type road or pavement, 16419 of them):
//
//     flat                                  72.06%
//     7 degrees   (8 steps, g = 0.125)      21.88%
//     26 degrees  (2 steps, g = 0.5)         5.92%
//     45 degrees  (1 step,  g = 1.0)         0.14%
//
// A pedestrian quad is 0.47 blocks across (measured off the game's own shadow
// slots), a car about 2. So 1/8 of a block clears 99.5% of the sloped surfaces
// a pedestrian can reach and 78% of those a car can, which is every 7 degree
// ramp - the common case by a wide margin. Doubling it to 1/4 buys nothing more
// for cars, and it takes a full 1/2 block to cover them on 26 degree ramps,
// which floats every sprite in the city half a block to fix 6% of surfaces.
//
// No single number does both jobs, which is why this is now the fallback rather
// than the mechanism. It is used where there is no floor to measure - off the
// map, over a hole, or with conforming switched off - and as the ceiling on the
// extra clearance a footprint straddling a kerb is given.
float g_spriteLift = kDefaultSpriteLift;

// The car sprite number of the tank (the green one with tracks); its turret is a
// sprite of its own that must be lifted onto the dome. See the roof-sprite pass in Draw.
constexpr int kTankCarSprite = 48;
constexpr int kTaxiSignSprite = 45;   // the checker taxi, whose roof sign is part of its hand-made art

// --- Conforming -----------------------------------------------------------
//
// The real answer, and what runs by default: sample the lid under the sprite's
// four corners, fit a plane to it, and make that plane the sprite's transform.
// The quad is then parallel to what it is standing on, so the whole slope term
// above disappears and the clearance collapses to kConformClearance - a quarter
// of a ground texel, enough to break coplanarity and nothing more.
//
// The part that matters for Remix: **the object-space quad does not change.**
// Baking per-corner heights into the vertices is the obvious way to tilt a
// sprite and it is the wrong one - local[] would become ground-dependent, so it
// would change continuously as a car climbed a ramp, CanonicalShape's eight-shape
// cache would fill and then dither, and the topological hash would churn exactly
// the way the note above Place explains it must not. So the shape is still
// measured from the flat corners the game gave, bit for bit, and every bit of
// the ground adaptation lives in objectToWorld, which stays a pure rotation and
// translation. That is the one form of this that Remix is happy with, and it
// pays twice over: the normal handed to the path tracer becomes the ground
// normal, so a car on a ramp is lit as one, and a replacement mesh placed by
// this matrix inherits the bank for free.
//
// Two rules keep it out of trouble without having to recognise anything:
//
//   * A sprite is never moved *down*. Where the game's own level is above the
//     floor the map reports, the game's wins - which leaves a jumping car, a
//     helicopter and a bullet exactly where they were put, with no notion of
//     what any of them are.
//   * The tilt fades out over the same gap, so something leaving the ground
//     rotates level again smoothly instead of snapping when it crosses a
//     threshold.
bool g_spriteConform = true;
bool g_spriteSmooth = kDefaultSpriteSmooth;

// How high the object sits above the road, as opposed to how far the quad is
// held off it for the depth test. See kDefaultSpriteHeight: this is the one that
// decides whether a car casts a shadow, and it was the thing the old fixed lift
// was accidentally providing a little of while trying to do something else.
float g_spriteHeight = kDefaultSpriteHeight;

float Smoothstep(float edge0, float edge1, float x) {
    if (x <= edge0) return 0.0f;
    if (x >= edge1) return 1.0f;
    const float t = (x - edge0) / (edge1 - edge0);
    return t * t * (3.0f - 2.0f * t);
}

// Where the tilt starts to fade and where it is gone. The near edge is well
// above any step a sprite stands on and well below a real jump; the far edge is
// a block, at which point the game has plainly taken the object off the floor.
constexpr float kTiltFadeNear = 0.25f;
constexpr float kTiltFadeFar = 1.0f;

// The tilt cap as the sine of the angle, which is what the normal is clamped
// against: the horizontal part of a unit normal is exactly sin of the slope.
const float kMaxTiltTan = std::tan(kMaxTiltDegrees * 3.14159265358979f / 180.0f);

// How much a sprite keeps of a sideways tilt. See kDefaultSpriteRoll.
float g_spriteRoll = kDefaultSpriteRoll;

// How far a footprint may depart from the plane fitted through it before the
// tilt stops being believed. Below the first figure the ground really is one
// plane and the fit is worth following whole; past the second it is a step or a
// block edge, where a confident tilt is worse than none.
constexpr float kFitGood = 0.05f;
constexpr float kFitPoor = 0.30f;

// How much of the way to this frame's answer a sprite moves. The game is paced
// at 30 fps, so a quarter converges in about a third of a second: fast enough to
// follow a car up a ramp, slow enough that a footprint crossing a kerb eases
// rather than steps.
constexpr float kSmoothing = 0.25f;

// Wider than anything can travel between two frames - a car at GTA2's top speed
// covers about a third of this - and narrower than the gap to the next sprite.
constexpr float kTrackRadius = 0.75f;

// Anything outside this is stale data left in the shadow slots by an earlier
// draw rather than a position the game just computed.
constexpr float kWorldMargin = 8.0f;
constexpr float kMinLevel = -4.0f;
constexpr float kMaxLevel = 16.0f;

struct Vec {
    float x, y, z;
};

Vec Cross(const Vec& a, const Vec& b) {
    return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}

}  // namespace

void SetSpriteLift(float blocks) {
    // Negative would push sprites into the floor, which is the bug this exists
    // to avoid; the ceiling is a whole block, past which a sprite is standing on
    // the storey above.
    g_spriteLift = blocks < 0.0f ? 0.0f : (blocks > 1.0f ? 1.0f : blocks);
}

float SpriteLift() { return g_spriteLift; }

void SetSpriteConform(bool on) { g_spriteConform = on; }
void SetSpriteSmooth(bool on) { g_spriteSmooth = on; }
namespace { bool g_ghostSwitch[kGhostSwitchCount] = {}; }
namespace {
const void* g_hiddenObjects[2] = {nullptr, nullptr};
const void* g_playerObject = nullptr;
bool g_logPedFrames = false;
bool g_logFigures = false;   // GTA2DX9_LOG_FIGURES=1: a line per frame per figure near the player (ACTIONS-3D-4)
// GTA2DX9_LOG_JOINTS=1 (ANIM-BLEND-AUDIT): a "figj:" line per frame for the player's figure and
// everyone within 1.5 blocks: the posed feet, pelvis, head and hands in the world, the state
// words and the blend weights, for tools/anim_audit.py (foot skate, pops, teleports, sinking).
bool g_logJoints = false;
// Pedestrians getting into or out of a car (ped state 3/4) seen last frame,
// with the vehicle they are boarding: the car's door swings for them. Last
// frame's list is read when the cars are collected, because a frame's
// pedestrians may be drawn after its cars.
struct DoorPed { uintptr_t vehicle; float x, z; int state; };
std::vector<DoorPed> g_doorPeds, g_doorPedsNow;
// QB-14 jacking: the cars drawn last frame and this one (renderer coordinates) and
// whether a driver sits in each, which tells a jack from the boarding of an empty
// car; and the drivers seen thrown out beside a boarding ped (where, which frame).
struct CarSeat { float x, z; bool driver; };
std::vector<CarSeat> g_carSeats, g_carSeatsNow;
struct JackThrow { float x, z; uint32_t frame; };
std::vector<JackThrow> g_jackThrows;
// Frame ranges (within one body's 158) of the punch, the aim and the hands up;
// see PedActionFor. Filled in from the probe runs; -1 disables a range.
int g_pedPunchFrames[2] = {115, 130};   // the swing 115-122, the recovery 123-130 (probe run)
int g_pedAimFrames[2] = {36, 47};      // arm out, from the frame sheet (not yet seen in a run)
int g_pedHandsUpFrames[2] = {-1, -1};
   // GTA2DX9_LOG_PED_FRAMES=1: the player's frame/state changes, for the clip tables
bool g_pedWeapons = true;   // the pickup models in the hand of a figure that aims
// CROWD ([crowd] in gta2dx9.ini, CrowdLoad): civilians' own clothing colours and
// builds, heads that follow the player, glances. The player's drawn spot (and the
// frame of it and of his last shot) is kept as his figure is drawn, for the others.
bool g_crowdVariety = true, g_crowdLookAt = true;
float g_crowdLookRange = 5.0f;
float g_crowdPlayerX = 0.0f, g_crowdPlayerZ = 0.0f;
uint32_t g_crowdPlayerFrame = 0, g_crowdPlayerShot = 0;
int g_crowdCount[5] = {};   // this frame: drawn, own clothes, looking at the player, glancing, in sprite outfits (ASSET-PEDS)
float g_crowdNearD2 = 1e9f, g_crowdNearRel = 0.0f;   // this frame: the nearest other figure to the player (log)
int g_crowdWin[4] = {};   // over the log's ten seconds: figure-frames in range, passed over (one in four), behind him, looking
uint32_t CrowdHash(uint32_t x) {
    x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; x ^= x >> 16;
    return x;
}
// One person's look, fixed by his object: a build (height +-6%, width +-5%) and,
// for a civilian (no uniform, no gang colours) three times in four, clothes of an
// everyday colour: the avatar's "_paint" half multiplied toward it (most of the
// way, so the cloth's own shading and the second garment's contrast remain).
struct CrowdLook { float height = 1.0f, width = 1.0f; bool clothes = false; float tint[3] = {1.0f, 1.0f, 1.0f}; float shade = 1.0f; };
CrowdLook CrowdLookFor(uint32_t seed, const Model& model, int remap, bool player) {
    CrowdLook look;
    if (!g_crowdVariety || player) return look;
    const uint32_t h = CrowdHash(seed ^ 0x9e3779b9u);
    look.height = 0.94f + 0.12f * static_cast<float>(h & 255) / 255.0f;
    look.width = 0.95f + 0.10f * static_cast<float>((h >> 8) & 255) / 255.0f;
    // The remaps the manifest gives a uniform or gang colours: 0-14, 16, 17, 22.
    const bool civilian = remap < 0 || remap == 15 || (remap >= 18 && remap != 22);
    // ASSET-PEDS: a zoned avatar wears his remap's own outfit (the sprite's colours);
    // the crowd's variety is then a shade of it (+-12%), not another colour.
    look.shade = 0.88f + 0.24f * static_cast<float>((h >> 24) & 255) / 255.0f;
    if (civilian && model.splitPaint && !model.pedZones && ((h >> 16) & 3) != 0) {
        static const uint8_t kClothes[][3] = {
            {38, 52, 92},    {60, 62, 66},   {28, 28, 32},   {196, 178, 140}, {92, 100, 58},  {118, 32, 44},
            {70, 104, 150},  {214, 212, 204}, {128, 130, 134}, {110, 76, 50},  {36, 80, 52},   {200, 160, 50},
            {40, 120, 124},  {176, 46, 40},  {210, 140, 160}, {140, 176, 210}, {160, 146, 104}, {90, 60, 110},
            {230, 120, 60},  {84, 40, 34},
        };
        constexpr uint32_t kN = sizeof(kClothes) / sizeof(kClothes[0]);
        const uint8_t* c = kClothes[(h >> 18) % kN];
        for (int k = 0; k < 3; ++k) {
            const float ratio = static_cast<float>(c[k]) / (std::max)(8.0f, model.paintRgb[k]);
            look.tint[k] = (std::max)(0.3f, (std::min)(2.0f, 1.0f + (ratio - 1.0f) * 0.85f));
        }
        look.clothes = true;
    }
    return look;
}
bool g_fxUpright = true;    // effect artwork faced to a street-level camera; bullets as streaks
// Where small effect artwork (a muzzle flash, a bullet, a spark) was drawn last
// frame: a figure standing in the attack state next to one is shooting, which
// the game's own frames do not say (the gun stance shares frames 53-60 with the
// fists). Read by DrawPedFigures, written by the sprite pass.
struct FxSpot { float x, y, z; };
std::vector<FxSpot> g_fxSpotsLast, g_fxSpotsNow;
// Fresh effect sprites: the small ones first seen in a frame (a muzzle flash,
// a bullet leaving the gun, an impact flash on a wall), with their size. The
// figures claim the ones beside a shooter as his shot (the recoil kick, the
// muzzle glow, a shell); what is left and does not fly is an impact.
struct FxFresh { float x, y, z, size; uintptr_t object; bool claimed; };
std::vector<FxFresh> g_fxFreshLast, g_fxFreshNow;
struct FxSeen { float x, y, z; uint32_t frame; float size; bool flying; };
std::map<uintptr_t, FxSeen> g_fxSeen;   // every small effect sprite's last position
struct PedSpot { float x, y, z; };
std::vector<PedSpot> g_pedSpots;        // where the figures stood this frame (blood on a hit)
// ACTIONS-3D-4: the figures drawn this frame and last (object, where, mid-swing and
// with which fist), so a figure whose health drops can find who punched him (the
// puncher may be drawn before or after him in a frame).
// QB-16: and when he last fired (muzzleFrame), which way he faces, and his weapon,
// so a figure whose health drops with nobody mid-swing beside him can be put to a shooter.
struct FigureSpot { uintptr_t object; float x, z; bool punching, alt; uint32_t shotFrame; float fx, fz; int weapon; };
// QB-16: GTA2DX9_SHOT_HITS=0 turns the shot reactions off (a punch's stay).
bool ShotHitsOn() {
    static int on = -1;
    if (on < 0) { char v[8] = {}; on = (GetEnvironmentVariableA("GTA2DX9_SHOT_HITS", v, sizeof v) && v[0] == '0') ? 0 : 1; }
    return on != 0;
}
constexpr uintptr_t kPedHealthWord = 0x216;   // int16, as world_view.cpp's peds line reads it
std::vector<FigureSpot> g_figuresNow, g_figuresLast;
constexpr float kSprintStrideOverRun = 1.405f;   // tools/gen_ped_clips.py: the sprint's stride over the run's
int g_playerWeapon = -1, g_playerAmmo = 0;   // from the game, see SetPlayerWeapon
int g_playerWeaponSeen = 0;             // the last weapon the player's own figure was drawn with
// The weapon in every drawn pedestrian's hands as the game numbers it (PedWeapon;
// 0 bare hands), by his sprite object, read with his state words (game::PedWeaponOf)
// and used when his figure picks its stance and model. Overwritten each frame.
std::unordered_map<uintptr_t, int> g_pedWeaponByObject;
uint32_t g_fpShotFrame = 0;             // the player's last shot seen from the first-person eye
int g_carLamps = 1;         // [renderer] car_lamps: 0 none, 1 when dark + brake lamps, 2 always
gta2::Vec3 g_viewEye = {0.0f, 0.0f, 0.0f};
gta2::Vec3 g_viewForward = {0.0f, -1.0f, 0.0f};
bool g_uprightPeds = false;
}
void SetHiddenObjects(const void* first, const void* second) {
    g_hiddenObjects[0] = first;
    g_hiddenObjects[1] = second;
}
std::vector<uint8_t> g_grassTiles;
int g_treeStatGrass = 0, g_treeStatPlaced = 0, g_treeStatFrames = 0;
void SetGrassTiles(const std::vector<uint8_t>& grass) { g_grassTiles = grass; }
std::vector<EnvCell> g_railCells, g_busStops;
void SetEnvCells(const std::vector<EnvCell>& rail, const std::vector<EnvCell>& busStops) { g_railCells = rail; g_busStops = busStops; }
// GTA2's water is one animated tile group, 608 and the frames after it, in every style.
bool IsWaterTile(int tile) { return tile >= 608 && tile <= 619; }
bool IsGrassTile(int tile) { return tile >= 0 && tile < static_cast<int>(g_grassTiles.size()) && g_grassTiles[static_cast<size_t>(tile)] != 0; }

float g_playerPosX = 0.0f, g_playerPosY = 0.0f, g_playerPosZ = 0.0f;
bool g_playerPosValid = false;
std::vector<FireSpotPublic> g_fireSpotsLast;
int FireSpotsNear(float x, float z, float radius, const void* carShell) {
    int n = 0;
    for (const FireSpotPublic& f : g_fireSpotsLast) {
        const float dx = f.x - x, dz = f.z - z;
        if ((carShell && f.car == carShell) || dx * dx + dz * dz <= radius * radius) ++n;
    }
    return n;
}
void SetPlayerPosition(float x, float y, float z, bool valid) {
    g_playerPosX = x; g_playerPosY = y; g_playerPosZ = z; g_playerPosValid = valid;
}
void SetPlayerObject(const void* object) {
    g_playerObject = object;
    static bool checked = false;
    if (!checked) { checked = true; char buf[8] = {}; g_logPedFrames = GetEnvironmentVariableA("GTA2DX9_LOG_PED_FRAMES", buf, sizeof buf) && buf[0] == '1';
                    g_logFigures = GetEnvironmentVariableA("GTA2DX9_LOG_FIGURES", buf, sizeof buf) && buf[0] == '1';
                    g_logJoints = GetEnvironmentVariableA("GTA2DX9_LOG_JOINTS", buf, sizeof buf) && buf[0] == '1'; }
}
// The people's pop log (see DrawPedFigures, BeginFrame), street views only.
int g_pedPops = 0, g_pedPopsInView = 0, g_pedPopsNear = 0;
float g_pedPopDist = 0.0f;
bool g_viewActiveForPops = false;

// The view frustum's side planes (left, right, bottom, top) as a*x + b*y + c*z + d >= 0
// inside, normalised, from the camera's view-projection (row vectors, D3D).
float g_frustum[4][4] = {};
// QB-6: the camera's view-projection of the last Draw, for LiveWorldToScreen.
float g_viewProj[4][4] = {};
bool g_viewProjValid = false;
std::vector<AimPed> g_aimPeds;
uint32_t g_aimPedsFrame = 0;
bool g_frustumValid = false;
void SetViewFrustum(const gta2::Camera& camera, int width, int height) {
    g_frustumValid = false;
    g_viewProjValid = false;
    if (width <= 0 || height <= 0) return;
    const gta2::Mat4 v = camera.ViewMatrix();
    const gta2::Mat4 p = camera.ProjectionMatrix(static_cast<float>(width) / static_cast<float>(height));
    float m[4][4];
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c) {
            float sum = 0.0f;
            for (int k = 0; k < 4; ++k) sum += v.m[r][k] * p.m[k][c];
            m[r][c] = sum;
        }
    std::memcpy(g_viewProj, m, sizeof m);
    g_viewProjValid = true;
    const int axis[4] = {0, 0, 1, 1};
    const float sign[4] = {1.0f, -1.0f, 1.0f, -1.0f};
    for (int i = 0; i < 4; ++i) {
        float pl[4];
        for (int r = 0; r < 4; ++r) pl[r] = m[r][3] + sign[i] * m[r][axis[i]];
        const float n = std::sqrt(pl[0] * pl[0] + pl[1] * pl[1] + pl[2] * pl[2]);
        if (!(n > 1e-6f)) return;
        for (int r = 0; r < 4; ++r) g_frustum[i][r] = pl[r] / n;
    }
    g_frustumValid = true;
}
bool OutsideViewFrustum(float x, float y, float z, float radius) {
    if (!g_frustumValid) return false;
    for (int i = 0; i < 4; ++i) {
        if (g_frustum[i][0] * x + g_frustum[i][1] * y + g_frustum[i][2] * z + g_frustum[i][3] < -radius) return true;
    }
    return false;
}
bool BehindView(float x, float y, float z, float margin) {
    const float dx = x - g_viewEye.x, dy = y - g_viewEye.y, dz = z - g_viewEye.z;
    return dx * g_viewForward.x + dy * g_viewForward.y + dz * g_viewForward.z < -margin;
}
const std::vector<AimPed>& LiveAimPeds() { return g_aimPeds; }
uint32_t LiveAimPedsFrame() { return g_aimPedsFrame; }
bool LiveWorldToScreen(float x, float y, float z, float* sx, float* sy) {
    if (!g_viewProjValid) return false;
    const float (*m)[4] = g_viewProj;
    const float cx = x * m[0][0] + y * m[1][0] + z * m[2][0] + m[3][0];
    const float cy = x * m[0][1] + y * m[1][1] + z * m[2][1] + m[3][1];
    const float cw = x * m[0][3] + y * m[1][3] + z * m[2][3] + m[3][3];
    if (!(cw > 0.05f)) return false;
    *sx = 0.5f + 0.5f * cx / cw;
    *sy = 0.5f - 0.5f * cy / cw;
    return true;
}
void SetUprightPeds(bool on) { g_uprightPeds = on; }
void SetPlayerWeapon(int weapon, int ammo) { g_playerWeapon = weapon; g_playerAmmo = ammo; }
int PlayerWeapon() { return g_playerWeapon; }
void SetCarLamps(int mode) { g_carLamps = mode; }
bool UprightPeds() { return g_uprightPeds; }
namespace { bool g_pedFigures = false; }
void SetPedFigures(bool on) { g_pedFigures = on; }
bool PedFigures() { return g_pedFigures; }
namespace { bool g_groundModels = false; }
void SetGroundModels(bool on) { g_groundModels = on; }
bool GroundModels() { return g_groundModels; }

namespace {
// Which way the artwork's top points in a quad's own space, and how long and
// wide the quad is: the top of a GTA2 car or pedestrian sprite is its front.
void SpriteFrame(const LiveGeometry::Vertex* local, int corners, float* fx, float* fz, float* length, float* width) {
    float cx = 0.0f, cz = 0.0f, minV = 1e9f;
    for (int i = 0; i < corners; ++i) { cx += local[i].x; cz += local[i].z; minV = (std::min)(minV, local[i].v); }
    cx /= corners; cz /= corners;
    // The edge with the two lowest v values is the top edge; its midpoint from the centre is forward.
    int a = 0, b = 1; float va = 1e9f, vb = 1e9f;
    for (int i = 0; i < corners; ++i) {
        if (local[i].v < va) { vb = va; b = a; va = local[i].v; a = i; }
        else if (local[i].v < vb) { vb = local[i].v; b = i; }
    }
    float dx = (local[a].x + local[b].x) * 0.5f - cx, dz = (local[a].z + local[b].z) * 0.5f - cz;
    const float len = std::sqrt(dx * dx + dz * dz);
    if (len > 1e-5f) { dx /= len; dz /= len; } else { dx = 0.0f; dz = 1.0f; }
    *fx = dx; *fz = dz;
    // Extents along forward and across it.
    float minF = 1e9f, maxF = -1e9f, minS = 1e9f, maxS = -1e9f;
    for (int i = 0; i < corners; ++i) {
        const float f = (local[i].x - cx) * dx + (local[i].z - cz) * dz;
        const float s = (local[i].x - cx) * dz - (local[i].z - cz) * dx;
        minF = (std::min)(minF, f); maxF = (std::max)(maxF, f); minS = (std::min)(minS, s); maxS = (std::max)(maxS, s);
    }
    *length = maxF - minF; *width = maxS - minS;
}

// The model's own space onto a sprite's: forward along the sprite's front,
// scaled so the model is as long as the sprite, standing on the sprite's plane.
gta2::Mat4 FitModel(const Model& model, const LiveGeometry::Vertex* local, int corners, const gta2::Mat4& placed, float heightBlocks) {
    float fx, fz, length, width;
    SpriteFrame(local, corners, &fx, &fz, &length, &width);
    float scale;
    if (heightBlocks > 0.0f) scale = heightBlocks / (std::max)(model.Height(), 0.01f);
    else scale = length / (std::max)(model.Length(), 0.01f);
    // Rows: the model's x (right), y (up), z (forward, signed by which way it faces).
    const float f = model.forward;
    gta2::Mat4 fit;
    fit.m[0][0] = fz * scale * f;  fit.m[0][1] = 0.0f;  fit.m[0][2] = -fx * scale * f;
    fit.m[1][0] = 0.0f;            fit.m[1][1] = scale; fit.m[1][2] = 0.0f;
    fit.m[2][0] = fx * scale * f;  fit.m[2][1] = 0.0f;  fit.m[2][2] = fz * scale * f;
    fit.m[3][0] = 0.0f; fit.m[3][1] = -model.boundsMin.y * scale; fit.m[3][2] = 0.0f; fit.m[3][3] = 1.0f;
    // Then the sprite's own placement (its tilt onto the ground and position).
    gta2::Mat4 out;
    for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) {
        float s = 0.0f;
        for (int k = 0; k < 4; ++k) s += fit.m[r][k] * placed.m[k][c];
        out.m[r][c] = s;
    }
    return out;
}
}  // namespace
void SetGhostSwitch(int which, bool on) {
    if (which >= 0 && which < kGhostSwitchCount) g_ghostSwitch[which] = on;
}
namespace { float g_boardingHeight = 0.45f; }
void SetBoardingHeight(float fraction) { g_boardingHeight = fraction < 0.0f ? 0.0f : (fraction > 1.0f ? 1.0f : fraction); }
float BoardingHeight() { return g_boardingHeight; }
bool GhostSwitchOn(int which) {
    return which >= 0 && which < kGhostSwitchCount && g_ghostSwitch[which];
}
bool SpriteSmooth() { return g_spriteSmooth; }
bool SpriteConform() { return g_spriteConform; }

void SetSpriteRoll(float amount) {
    g_spriteRoll = amount < 0.0f ? 0.0f : (amount > 1.0f ? 1.0f : amount);
}

float SpriteRoll() { return g_spriteRoll; }

void SetSpriteHeight(float blocks) {
    // Negative would bury the sprite, which is the bug all of this exists to
    // avoid. The ceiling is a whole block: past that a sprite is standing at the
    // height of the storey above the one the game put it on.
    g_spriteHeight = blocks < 0.0f ? 0.0f : (blocks > 1.0f ? 1.0f : blocks);
}

float SpriteHeight() { return g_spriteHeight; }

float g_spriteFeather = 0.0f;

void SetSpriteFeather(float strength) {
    g_spriteFeather = strength < 0.0f ? 0.0f : (strength > 1.0f ? 1.0f : strength);
}

float SpriteFeather() { return g_spriteFeather; }

// A hundredth of a block. Far below anything visible at GTA2's near-top-down
// camera, and comfortably above the depth buffer's resolving power at the ten to
// twenty units the camera actually sits at.
float g_spriteStackStep = 0.01f;

void SetSpriteStackStep(float blocks) {
    g_spriteStackStep = blocks < 0.0f ? 0.0f : (blocks > 0.25f ? 0.25f : blocks);
}

float SpriteStackStep() { return g_spriteStackStep; }

int g_effectBatches = 0;
int EffectBatchesDrawn() { return g_effectBatches; }

bool g_ownCarLamps = kDefaultOwnCarLamps;
void ReleaseLampTextures();
void ReleaseLampMaterials();
float g_lampGlow = kDefaultCarLampGlow;
uint32_t g_pedsOverCars = 0;   // log counter: pedestrians lifted over a car
// The frame each pedestrian was last seen with a vehicle of his own - in it, or
// getting in or out. He is not lifted over a car for a little while after: that is
// the door, not a jump.
std::map<uintptr_t, uint32_t> g_pedWithCar;
float g_lampSize = kDefaultCarLampSize;
void SetCarLampSize(float fraction) { g_lampSize = fraction < 0.1f ? 0.1f : (fraction > 1.0f ? 1.0f : fraction); }
void SetCarLampGlow(float intensity) { g_lampGlow = intensity < 0.0f ? 0.0f : intensity; }
bool g_bloodGloss = true;
float g_bloodRough = 0.07f;
float g_bloodAlbedo = 0.55f;
void SetBloodLook(bool gloss, float roughness, float albedo) {
    g_bloodGloss = gloss;
    g_bloodRough = roughness < 0.0f ? 0.0f : (roughness > 1.0f ? 1.0f : roughness);
    g_bloodAlbedo = albedo < 0.05f ? 0.05f : (albedo > 1.0f ? 1.0f : albedo);
}
float CarLampGlow() { return g_lampGlow; }
// Per lamp delta, one entry per car sprite.
std::map<int, std::vector<LampArt>> g_lampArt;
// Per dent / door delta, one entry per car sprite. See SetCarDeltaArt.
std::map<int, std::vector<LampArt>> g_deltaArt;
// Per car sprite, the pixels any of those deltas can paint: what the car's colour
// is not measured over, since the game's sprite changes there as a door opens.
std::map<int, std::vector<uint8_t>> g_deltaFootprint;
void ReleaseDoorMaterials();
bool g_carWheels = kDefaultCarWheels;
float g_wheelMaxAngle = kDefaultCarWheelMaxAngle * 3.14159265f / 180.0f;
float g_wheelSide = kDefaultCarWheelSide;
float g_wheelAxleInset = kDefaultCarWheelAxleInset;
float g_wheelFrontExtra = kDefaultCarWheelFrontExtra;
void SetCarWheels(bool on, float maxAngleDegrees, float side, float axleInset, float frontExtra) {
    g_carWheels = on;
    const float clamped = (std::max)(0.0f, (std::min)(maxAngleDegrees, 60.0f));
    g_wheelMaxAngle = clamped * 3.14159265f / 180.0f;
    g_wheelSide = (std::max)(0.2f, (std::min)(side, 0.6f));
    g_wheelAxleInset = (std::max)(0.1f, (std::min)(axleInset, 0.4f));
    g_wheelFrontExtra = (std::max)(-0.1f, (std::min)(frontExtra, 0.2f));
}
bool CarWheels() { return g_carWheels; }
void SetOwnCarLamps(bool on) { g_ownCarLamps = on; }
bool OwnCarLamps() { return g_ownCarLamps; }

namespace {
bool g_carBodies = kDefaultCarBodies;
float g_carBodyHeight = kDefaultCarBodyHeight;
float g_carBodyInset = kDefaultCarBodyInset;
float g_carDomeShoulder = 0.7f;
}  // namespace

void SetCarBodies(bool on) { g_carBodies = on; }
namespace { bool g_carModels3d = false; }
void SetCarModels3d(bool on) { g_carModels3d = on; }
bool CarBodies() { return g_carBodies; }
void SetCarBodyHeight(float blocks) { g_carBodyHeight = (std::max)(0.0f, (std::min)(blocks, 0.6f)); }
float CarBodyHeight() { return g_carBodyHeight; }
void SetCarDomeShoulder(float exponent) { g_carDomeShoulder = (std::max)(0.15f, (std::min)(exponent, 1.5f)); }
float CarDomeShoulder() { return g_carDomeShoulder; }
void SetCarBodyInset(float fraction) { g_carBodyInset = (std::max)(0.0f, (std::min)(fraction, 0.4f)); }
float CarBodyInset() { return g_carBodyInset; }

namespace {
bool g_carMaterial = kDefaultCarMaterial;
float g_carRoughness = kDefaultCarRoughness;
float g_carMetallic = kDefaultCarMetallic;
}  // namespace

void SetCarMaterial(bool on, float roughness, float metallic) {
    g_carMaterial = on;
    g_carRoughness = (std::max)(0.0f, (std::min)(roughness, 1.0f));
    g_carMetallic = (std::max)(0.0f, (std::min)(metallic, 1.0f));
}

std::vector<uint32_t> LampTexels(const LampArt& art, bool mirrored) {
    std::vector<uint32_t> texels(art.argb.size(), 0);
    uint32_t sum[3] = {}, count = 0;
    for (uint32_t c : art.argb) {
        if (!(c >> 24)) continue;
        sum[0] += (c >> 16) & 0xFF;
        sum[1] += (c >> 8) & 0xFF;
        sum[2] += c & 0xFF;
        ++count;
    }
    const uint32_t fill =
        count ? ((sum[0] / count) << 16) | ((sum[1] / count) << 8) | (sum[2] / count) : 0;
    for (int y = 0; y < art.height; ++y) {
        for (int x = 0; x < art.width; ++x) {
            const int from = mirrored ? art.width - 1 - x : x;
            const uint32_t c = art.argb[static_cast<size_t>(y) * art.width + from];
            texels[static_cast<size_t>(y) * art.width + x] = (c >> 24) ? c : fill;
        }
    }
    return texels;
}

void SetCarLampArt(int delta, std::vector<LampArt> bySprite) {
    // Textures point at the art they were made from.
    ReleaseLampTextures();
    ReleaseLampMaterials();
    g_lampArt[delta] = std::move(bySprite);
}

void SetCarDeltaArt(int delta, std::vector<LampArt> bySprite) {
    ReleaseDoorMaterials();
    for (LampArt& art : bySprite) {
        art.opaque = 0;
        for (const uint32_t c : art.argb) {
            if ((c >> 24) >= 128) ++art.opaque;
        }
    }
    g_deltaFootprint.clear();
    g_deltaArt[delta] = std::move(bySprite);
}

// Textures for the lamps, made on first use, keyed by the art and which side.
std::map<std::pair<const LampArt*, bool>, IDirect3DTexture9*> g_lampTextures;
IDirect3DDevice9* g_lampDevice = nullptr;

void ReleaseLampTextures() {
    for (auto& entry : g_lampTextures) {
        if (entry.second) entry.second->Release();
    }
    g_lampTextures.clear();
}

IDirect3DTexture9* LampTexture(IDirect3DDevice9* device, const LampArt* art, bool mirrored) {
    if (!art || !art->Valid()) return nullptr;
    if (g_lampDevice != device) {
        ReleaseLampTextures();
        g_lampDevice = device;
    }
    auto found = g_lampTextures.find({art, mirrored});
    if (found != g_lampTextures.end()) return found->second;
    IDirect3DTexture9* texture = nullptr;
    if (FAILED(device->CreateTexture(art->width, art->height, 1, 0, D3DFMT_A8R8G8B8,
                                     D3DPOOL_MANAGED, &texture, nullptr))) {
        texture = nullptr;
    } else {
        const std::vector<uint32_t> texels = LampTexels(*art, mirrored);
        D3DLOCKED_RECT locked;
        if (SUCCEEDED(texture->LockRect(0, &locked, nullptr, 0))) {
            for (int y = 0; y < art->height; ++y) {
                memcpy(static_cast<uint8_t*>(locked.pBits) + y * locked.Pitch,
                       &texels[static_cast<size_t>(y) * art->width],
                       static_cast<size_t>(art->width) * 4);
            }
            texture->UnlockRect(0);
        }
    }
    g_lampTextures[{art, mirrored}] = texture;
    return texture;
}


// ---- Smoothed small sprites --------------------------------------------------
//
// See SetSpriteSmooth. The source texture is read back, enlarged 4x and cached
// against the source's pointer; the cache holds a reference on the source so a
// pointer can never be reused for different artwork while its entry lives.
namespace {

constexpr int kSmoothMaxSide = 48;     // larger artwork is not "small flat" any more
constexpr int kSmoothFactor = 4;
constexpr size_t kSmoothCacheMax = 256;

struct SmoothEntry {
    IDirect3DTexture9* source = nullptr;
    IDirect3DTexture9* smooth = nullptr;  // null: could not be made, use the source
};
std::map<IDirect3DTexture9*, SmoothEntry> g_smoothTextures;
IDirect3DDevice9* g_smoothDevice = nullptr;

void ReleaseSmoothTextures() {
    for (auto& entry : g_smoothTextures) {
        if (entry.second.smooth) entry.second.smooth->Release();
        if (entry.second.source) entry.second.source->Release();
    }
    g_smoothTextures.clear();
}

struct Rgba { float r, g, b, a; };

Rgba Unpack(uint32_t c) {
    return {static_cast<float>((c >> 16) & 255), static_cast<float>((c >> 8) & 255),
            static_cast<float>(c & 255), static_cast<float>(c >> 24)};
}

// Scale2x (EPX): doubles the picture and rounds diagonal staircases without
// blending colours, which is what keeps the artwork's flat colours crisp.
std::vector<uint32_t> Scale2x(const std::vector<uint32_t>& src, int w, int h) {
    std::vector<uint32_t> out(static_cast<size_t>(w) * 2 * h * 2);
    auto at = [&](int x, int y) {
        x = (std::max)(0, (std::min)(w - 1, x));
        y = (std::max)(0, (std::min)(h - 1, y));
        return src[static_cast<size_t>(y) * w + x];
    };
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const uint32_t p = at(x, y), a = at(x, y - 1), b = at(x + 1, y), c = at(x - 1, y),
                           d = at(x, y + 1);
            uint32_t e0 = p, e1 = p, e2 = p, e3 = p;
            if (c == a && c != d && a != b) e0 = a;
            if (a == b && a != c && b != d) e1 = b;
            if (d == c && d != b && c != a) e2 = c;
            if (b == d && b != a && d != c) e3 = d;
            const size_t o = static_cast<size_t>(y * 2) * (w * 2) + x * 2;
            out[o] = e0;
            out[o + 1] = e1;
            out[o + w * 2] = e2;
            out[o + w * 2 + 1] = e3;
        }
    }
    return out;
}

float CubicWeight(float t) {  // Catmull-Rom
    t = std::fabs(t);
    if (t < 1.0f) return 1.5f * t * t * t - 2.5f * t * t + 1.0f;
    if (t < 2.0f) return -0.5f * t * t * t + 2.5f * t * t - 4.0f * t + 2.0f;
    return 0.0f;
}

// Catmull-Rom resample to w2 x h2 with colour weighted by alpha, so the colour of
// the transparent margin never bleeds into the edge.
std::vector<uint32_t> ResampleCubic(const std::vector<uint32_t>& src, int w, int h, int w2, int h2) {
    std::vector<uint32_t> out(static_cast<size_t>(w2) * h2);
    for (int y = 0; y < h2; ++y) {
        const float sy = (y + 0.5f) * h / h2 - 0.5f;
        const int y0 = static_cast<int>(std::floor(sy));
        for (int x = 0; x < w2; ++x) {
            const float sx = (x + 0.5f) * w / w2 - 0.5f;
            const int x0 = static_cast<int>(std::floor(sx));
            float r = 0, g = 0, b = 0, a = 0, wsum = 0;
            for (int j = -1; j <= 2; ++j) {
                const int yy = (std::max)(0, (std::min)(h - 1, y0 + j));
                const float wy = CubicWeight(sy - (y0 + j));
                for (int i = -1; i <= 2; ++i) {
                    const int xx = (std::max)(0, (std::min)(w - 1, x0 + i));
                    const float wgt = wy * CubicWeight(sx - (x0 + i));
                    const Rgba p = Unpack(src[static_cast<size_t>(yy) * w + xx]);
                    r += p.r * p.a * wgt;
                    g += p.g * p.a * wgt;
                    b += p.b * p.a * wgt;
                    a += p.a * wgt;
                    wsum += wgt;
                }
            }
            (void)wsum;
            float cr = 0, cg = 0, cb = 0;
            if (a > 0.5f) { cr = r / a; cg = g / a; cb = b / a; }
            // Steepen the coverage so the edge stays a clean cutout under the alpha
            // test instead of a soft halo.
            float cov = a / 255.0f;
            cov = (cov - 0.5f) * 3.0f + 0.5f;
            cov = (std::max)(0.0f, (std::min)(1.0f, cov));
            auto q = [](float v) { return static_cast<uint32_t>((std::max)(0.0f, (std::min)(255.0f, v)) + 0.5f); };
            out[static_cast<size_t>(y) * w2 + x] =
                (q(cov * 255.0f) << 24) | (q(cr) << 16) | (q(cg) << 8) | q(cb);
        }
    }
    return out;
}

// A smoothed 4x copy of `source`, or `source` itself when it is not small
// artwork or the copy cannot be made.
IDirect3DTexture9* SmoothSpriteTexture(IDirect3DDevice9* device, IDirect3DTexture9* source) {
    if (!source) return source;
    if (g_smoothDevice != device) {
        ReleaseSmoothTextures();
        g_smoothDevice = device;
    }
    const auto found = g_smoothTextures.find(source);
    if (found != g_smoothTextures.end()) return found->second.smooth ? found->second.smooth : source;

    if (g_smoothTextures.size() >= kSmoothCacheMax) ReleaseSmoothTextures();
    SmoothEntry entry;
    entry.source = source;
    source->AddRef();

    D3DSURFACE_DESC desc;
    if (SUCCEEDED(source->GetLevelDesc(0, &desc)) && desc.Format == D3DFMT_A8R8G8B8 &&
        desc.Width >= 4 && desc.Height >= 4 && desc.Width <= kSmoothMaxSide &&
        desc.Height <= kSmoothMaxSide) {
        const int w = static_cast<int>(desc.Width), h = static_cast<int>(desc.Height);
        std::vector<uint32_t> pixels(static_cast<size_t>(w) * h);
        D3DLOCKED_RECT locked;
        bool read = false;
        if (SUCCEEDED(source->LockRect(0, &locked, nullptr, D3DLOCK_READONLY))) {
            for (int y = 0; y < h; ++y) {
                memcpy(&pixels[static_cast<size_t>(y) * w],
                       static_cast<const uint8_t*>(locked.pBits) + y * locked.Pitch,
                       static_cast<size_t>(w) * 4);
            }
            source->UnlockRect(0);
            read = true;
        }
        if (read) {
            // The colour-key index drives the alpha, so Scale2x on whole ARGB values
            // keeps the cutout's shape as well as the colours.
            std::vector<uint32_t> big = Scale2x(pixels, w, h);
            big = ResampleCubic(big, w * 2, h * 2, w * kSmoothFactor, h * kSmoothFactor);
            IDirect3DTexture9* made = nullptr;
            if (SUCCEEDED(device->CreateTexture(w * kSmoothFactor, h * kSmoothFactor, 1, 0,
                                                D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &made, nullptr))) {
                D3DLOCKED_RECT out;
                if (SUCCEEDED(made->LockRect(0, &out, nullptr, 0))) {
                    for (int y = 0; y < h * kSmoothFactor; ++y) {
                        memcpy(static_cast<uint8_t*>(out.pBits) + y * out.Pitch,
                               &big[static_cast<size_t>(y) * w * kSmoothFactor],
                               static_cast<size_t>(w) * kSmoothFactor * 4);
                    }
                    made->UnlockRect(0);
                    entry.smooth = made;
                } else {
                    made->Release();
                }
            }
        }
    }
    g_smoothTextures[source] = entry;
    return entry.smooth ? entry.smooth : source;
}

// ---- Skid marks and tyre smoke ---------------------------------------------------
//
// GTA2 lays a skid mark as a string of small strips, each a few texels wide, fading
// from solid to a sparse stipple, a few dozen of them overlapping. Drawn as they are,
// as hard-edged cutouts, they read as three or four layered dark stripes. So the rubber
// strips (grey ones; the same artwork in red is blood and is left alone) are redrawn
// from a soft, enlarged, translucent copy: edges that fade out, the stipple blurred into
// a smooth gradient, and a peak opacity that is a setting. And each new strip near a car
// is where a tyre has just been, which is where the smoke comes from.

SkidSmokeSettings g_skid;
std::string g_skidIniPath;

struct SkidEntry {
    IDirect3DTexture9* source = nullptr;
    IDirect3DTexture9* soft = nullptr;
    bool rubber = false;
    float opacity = 0.0f, softness = 0.0f;
};
std::map<IDirect3DTexture9*, SkidEntry> g_skidTextures;
IDirect3DDevice9* g_skidDevice = nullptr;
IDirect3DTexture9* g_smokeTexture = nullptr;
IDirect3DTexture9* g_smokeGlowTexture = nullptr;   // the same puff with its shape in the colour

struct Puff {
    float x, y, z;
    float vx, vy, vz;
    float angle, spin;
    float size0, size1;
    float life, age;
    float alphaMax = 0.2f;   // peak opacity
    float grey = 1.0f;       // 0 black .. 1 white, at birth; smoke pales as it spreads
};
FireSettings g_fire;
std::string g_fireIniPath;
std::vector<Puff> g_fireSmoke;   // smoke off burning cars
std::vector<Puff> g_flames;      // flame tongues off burning cars
std::vector<Puff> g_embers;      // sparks off burning cars
IDirect3DTexture9* g_flameTexture = nullptr;
// A burnt mark on the ground where something blew up. Kept for a minute, fading very slowly.
struct Scorch {
    float x, y, z, size;
    float angle;
    double born;
};
std::vector<Scorch> g_scorch;
IDirect3DTexture9* g_scorchTexture = nullptr;
float g_puffDt = 0.0f;           // this frame's time step, seconds
std::vector<Puff> g_puffs;
std::map<uint64_t, uint32_t> g_skidSeen;   // strip position (1/32 tile) -> frame last drawn

// Skid strips the renderer remembers after the game has dropped them. Keyed by where the
// strip lies (1/256 tile); the artwork is the first one seen there and is held by a
// reference of its own, so the soft copy can be found again whatever the cache has done.
struct SkidGhost {
    LiveGeometry::SpriteType sprite;
    IDirect3DTexture9* source = nullptr;
    double born = 0.0;
};
std::unordered_map<uint64_t, SkidGhost> g_skidGhosts;
constexpr size_t kSkidGhostCap = 6000;
void ClearSkidGhosts();
uint32_t g_skidRng = 0x9E3779B9u;

float SkidRand() {
    g_skidRng = g_skidRng * 1664525u + 1013904223u;
    return static_cast<float>((g_skidRng >> 8) & 0xFFFFu) / 65535.0f;
}

void ReleaseSkidTextures() {
    for (auto& entry : g_skidTextures) {
        if (entry.second.soft) entry.second.soft->Release();
        if (entry.second.source) entry.second.source->Release();
    }
    g_skidTextures.clear();
    if (g_flameTexture) {
        g_flameTexture->Release();
        g_flameTexture = nullptr;
    }
    if (g_scorchTexture) {
        g_scorchTexture->Release();
        g_scorchTexture = nullptr;
    }
    if (g_smokeGlowTexture) {
        g_smokeGlowTexture->Release();
        g_smokeGlowTexture = nullptr;
    }
    if (g_smokeTexture) {
        g_smokeTexture->Release();
        g_smokeTexture = nullptr;
    }
}

uint32_t SkidHash(int x, int y, int salt) {
    uint32_t h = static_cast<uint32_t>(x) * 374761393u + static_cast<uint32_t>(y) * 668265263u +
                 static_cast<uint32_t>(salt) * 2246822519u;
    h = (h ^ (h >> 13)) * 1274126177u;
    return h ^ (h >> 16);
}

// Two box blurs a side, near enough to a gaussian for a soft edge.
void SkidBlur(std::vector<float>* field, int w, int h, int radius) {
    if (radius < 1) return;
    std::vector<float> tmp(field->size());
    for (int pass = 0; pass < 2; ++pass) {
        for (int y = 0; y < h; ++y) {
            for (int x = 0; x < w; ++x) {
                float sum = 0.0f;
                for (int k = -radius; k <= radius; ++k) {
                    sum += (*field)[static_cast<size_t>(y) * w + (std::max)(0, (std::min)(w - 1, x + k))];
                }
                tmp[static_cast<size_t>(y) * w + x] = sum / static_cast<float>(radius * 2 + 1);
            }
        }
        for (int y = 0; y < h; ++y) {
            for (int x = 0; x < w; ++x) {
                float sum = 0.0f;
                for (int k = -radius; k <= radius; ++k) {
                    sum += tmp[static_cast<size_t>((std::max)(0, (std::min)(h - 1, y + k))) * w + x];
                }
                (*field)[static_cast<size_t>(y) * w + x] = sum / static_cast<float>(radius * 2 + 1);
            }
        }
    }
}

// The soft copy of one decal strip, and whether the strip is rubber. Not rubber: null.
IDirect3DTexture9* SoftSkidTexture(IDirect3DDevice9* device, IDirect3DTexture9* source,
                                   bool* rubber) {
    *rubber = false;
    if (!source) return nullptr;
    if (g_skidDevice != device) {
        ReleaseSkidTextures();
        ClearSkidGhosts();
        g_skidDevice = device;
    }
    auto found = g_skidTextures.find(source);
    if (found != g_skidTextures.end()) {
        SkidEntry& e = found->second;
        if (!e.rubber || (e.opacity == g_skid.skidOpacity && e.softness == g_skid.skidSoftness)) {
            *rubber = e.rubber;
            return e.rubber ? e.soft : nullptr;
        }
        // The look settings changed: build this one again.
        if (e.soft) e.soft->Release();
        e.soft = nullptr;
        if (e.source) e.source->Release();
        g_skidTextures.erase(found);
    }
    if (g_skidTextures.size() >= 256) ReleaseSkidTextures();
    SkidEntry entry;
    entry.source = source;
    source->AddRef();
    entry.opacity = g_skid.skidOpacity;
    entry.softness = g_skid.skidSoftness;

    D3DSURFACE_DESC desc;
    if (SUCCEEDED(source->GetLevelDesc(0, &desc)) && desc.Format == D3DFMT_A8R8G8B8 &&
        desc.Width >= 2 && desc.Height >= 2 && desc.Width <= 64 && desc.Height <= 64) {
        const int w = static_cast<int>(desc.Width), h = static_cast<int>(desc.Height);
        std::vector<uint32_t> pixels(static_cast<size_t>(w) * h);
        D3DLOCKED_RECT locked;
        bool read = false;
        if (SUCCEEDED(source->LockRect(0, &locked, nullptr, D3DLOCK_READONLY))) {
            for (int y = 0; y < h; ++y) {
                memcpy(&pixels[static_cast<size_t>(y) * w],
                       static_cast<const uint8_t*>(locked.pBits) + y * locked.Pitch,
                       static_cast<size_t>(w) * 4);
            }
            source->UnlockRect(0);
            read = true;
        }
        if (read) {
            // Rubber is grey. Blood, from the same strips, is red.
            double sr = 0, sg = 0, sb = 0;
            int opaque = 0;
            std::vector<float> cover(static_cast<size_t>(w) * h, 0.0f);
            for (size_t i = 0; i < pixels.size(); ++i) {
                if ((pixels[i] >> 24) >= 128) {
                    sr += (pixels[i] >> 16) & 255;
                    sg += (pixels[i] >> 8) & 255;
                    sb += pixels[i] & 255;
                    ++opaque;
                    cover[i] = 1.0f;
                }
            }
            bool grey = false;
            if (opaque > 0) {
                const double r = sr / opaque, g = sg / opaque, b = sb / opaque;
                const double hi = (std::max)(r, (std::max)(g, b)), lo = (std::min)(r, (std::min)(g, b));
                grey = hi - lo <= 40.0;
            }
            entry.rubber = grey;
            if (grey) {
                constexpr int F = 6;
                const int ow = w * F, oh = h * F;
                std::vector<float> field(static_cast<size_t>(ow) * oh);
                auto texel = [&](int x, int y) {
                    return cover[static_cast<size_t>((std::max)(0, (std::min)(h - 1, y))) * w +
                                 (std::max)(0, (std::min)(w - 1, x))];
                };
                for (int y = 0; y < oh; ++y) {
                    const float sy = (y + 0.5f) / F - 0.5f;
                    const int y0 = static_cast<int>(std::floor(sy));
                    const float fy = sy - y0;
                    for (int x = 0; x < ow; ++x) {
                        const float sx = (x + 0.5f) / F - 0.5f;
                        const int x0 = static_cast<int>(std::floor(sx));
                        const float fx = sx - x0;
                        const float top = texel(x0, y0) * (1 - fx) + texel(x0 + 1, y0) * fx;
                        const float bot = texel(x0, y0 + 1) * (1 - fx) + texel(x0 + 1, y0 + 1) * fx;
                        field[static_cast<size_t>(y) * ow + x] = top * (1 - fy) + bot * fy;
                    }
                }
                SkidBlur(&field, ow, oh,
                         (std::max)(1, static_cast<int>(g_skid.skidSoftness * F * 0.8f + 0.5f)));
                // The strip's edge is the quad's edge, so the softness has to come from
                // inside it: a hump across the narrow side that reaches nothing at the
                // border. A square dot gets it both ways.
                const bool windowX = w <= h, windowY = h <= w;
                std::vector<uint32_t> out(field.size());
                for (int y = 0; y < oh; ++y) {
                    const float ty = (y + 0.5f) / oh;
                    const float wy = windowY ? std::pow(std::sin(3.14159265f * ty), 0.6f) : 1.0f;
                    for (int x = 0; x < ow; ++x) {
                        const float tx = (x + 0.5f) / ow;
                        const float wx = windowX ? std::pow(std::sin(3.14159265f * tx), 0.6f) : 1.0f;
                        const float grain = 0.86f + 0.14f * static_cast<float>(SkidHash(x, y, 7) & 255) / 255.0f;
                        float a = field[static_cast<size_t>(y) * ow + x] * wx * wy * grain * g_skid.skidOpacity;
                        a = (std::max)(0.0f, (std::min)(1.0f, a));
                        const uint32_t q = static_cast<uint32_t>(a * 255.0f + 0.5f);
                        out[static_cast<size_t>(y) * ow + x] = (q << 24) | (26u << 16) | (23u << 8) | 22u;
                    }
                }
                IDirect3DTexture9* made = nullptr;
                if (SUCCEEDED(device->CreateTexture(ow, oh, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED,
                                                    &made, nullptr))) {
                    D3DLOCKED_RECT dst;
                    if (SUCCEEDED(made->LockRect(0, &dst, nullptr, 0))) {
                        for (int y = 0; y < oh; ++y) {
                            memcpy(static_cast<uint8_t*>(dst.pBits) + y * dst.Pitch,
                                   &out[static_cast<size_t>(y) * ow], static_cast<size_t>(ow) * 4);
                        }
                        made->UnlockRect(0);
                        entry.soft = made;
                    } else {
                        made->Release();
                    }
                }
                if (!entry.soft) entry.rubber = false;   // could not be made: draw it as before
            }
        }
    }
    *rubber = entry.rubber;
    IDirect3DTexture9* result = entry.rubber ? entry.soft : nullptr;
    g_skidTextures[source] = entry;
    return result;
}

float SmokeNoise(float x, float y, int salt) {
    const int xi = static_cast<int>(std::floor(x)), yi = static_cast<int>(std::floor(y));
    const float fx = x - xi, fy = y - yi;
    const float sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
    auto v = [&](int a, int b) { return static_cast<float>(SkidHash(a, b, salt) & 1023) / 1023.0f; };
    const float top = v(xi, yi) * (1 - sx) + v(xi + 1, yi) * sx;
    const float bot = v(xi, yi + 1) * (1 - sx) + v(xi + 1, yi + 1) * sx;
    return top * (1 - sy) + bot * sy;
}

// A soft round puff, broken up by noise so a cloud of them is not a row of discs.
IDirect3DTexture9* SmokeTexture(IDirect3DDevice9* device) {
    if (g_smokeTexture) return g_smokeTexture;
    constexpr int N = 64;
    IDirect3DTexture9* made = nullptr;
    if (FAILED(device->CreateTexture(N, N, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &made, nullptr))) {
        return nullptr;
    }
    D3DLOCKED_RECT dst;
    if (FAILED(made->LockRect(0, &dst, nullptr, 0))) {
        made->Release();
        return nullptr;
    }
    for (int y = 0; y < N; ++y) {
        uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(dst.pBits) + y * dst.Pitch);
        for (int x = 0; x < N; ++x) {
            const float dx = (x + 0.5f) / N * 2.0f - 1.0f, dy = (y + 0.5f) / N * 2.0f - 1.0f;
            const float r = std::sqrt(dx * dx + dy * dy);
            float radial = (std::max)(0.0f, 1.0f - r);
            radial = radial * radial * (3.0f - 2.0f * radial);
            const float n = 0.5f * SmokeNoise(x * 0.12f, y * 0.12f, 3) +
                            0.3f * SmokeNoise(x * 0.25f, y * 0.25f, 5) +
                            0.2f * SmokeNoise(x * 0.5f, y * 0.5f, 9);
            float a = radial * (0.25f + 1.25f * n);
            a = (std::max)(0.0f, (std::min)(1.0f, a));
            const uint32_t q = static_cast<uint32_t>(a * 255.0f + 0.5f);
            row[x] = (q << 24) | (232u << 16) | (232u << 8) | 236u;
        }
    }
    made->UnlockRect(0);
    g_smokeTexture = made;
    return made;
}

// The same puff for adding to the picture: an additive draw ignores alpha, so the soft edge and
// the noise have to be in the colour. Remix takes additive draws as lights of their own, so the
// smoke stays white however little light falls on it.
IDirect3DTexture9* SmokeGlowTexture(IDirect3DDevice9* device) {
    if (g_smokeGlowTexture) return g_smokeGlowTexture;
    IDirect3DTexture9* source = SmokeTexture(device);
    if (!source) return nullptr;
    constexpr int N = 64;
    IDirect3DTexture9* made = nullptr;
    if (FAILED(device->CreateTexture(N, N, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &made, nullptr))) {
        return nullptr;
    }
    D3DLOCKED_RECT src, dst;
    if (FAILED(source->LockRect(0, &src, nullptr, D3DLOCK_READONLY))) {
        made->Release();
        return nullptr;
    }
    if (FAILED(made->LockRect(0, &dst, nullptr, 0))) {
        source->UnlockRect(0);
        made->Release();
        return nullptr;
    }
    for (int y = 0; y < N; ++y) {
        const uint32_t* in = reinterpret_cast<const uint32_t*>(static_cast<const uint8_t*>(src.pBits) + y * src.Pitch);
        uint32_t* out = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(dst.pBits) + y * dst.Pitch);
        for (int x = 0; x < N; ++x) {
            const uint32_t a = in[x] >> 24;
            const uint32_t r = 232u * a / 255u, g = 232u * a / 255u, b = 236u * a / 255u;
            out[x] = (255u << 24) | (r << 16) | (g << 8) | b;
        }
    }
    made->UnlockRect(0);
    source->UnlockRect(0);
    g_smokeGlowTexture = made;
    return made;
}

double SkidNowSeconds();

// A flame tongue: a lobed, ragged blob that is white-yellow at the middle and red at the edge,
// stored premultiplied because it is drawn additively. Rotated at random, a crowd of them reads
// as a fire rather than as a stack of one picture.
IDirect3DTexture9* FlameTexture(IDirect3DDevice9* device) {
    if (g_flameTexture) return g_flameTexture;
    constexpr int N = 128;
    constexpr int K = 7;
    float lobes[K];
    for (int i = 0; i < K; ++i) lobes[i] = static_cast<float>(SkidHash(i, 7, 21) & 1023) / 1023.0f;
    IDirect3DTexture9* made = nullptr;
    if (FAILED(device->CreateTexture(N, N, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &made, nullptr))) return nullptr;
    D3DLOCKED_RECT dst;
    if (FAILED(made->LockRect(0, &dst, nullptr, 0))) {
        made->Release();
        return nullptr;
    }
    const float kPi = 3.14159265f;
    auto sstep = [](float t) { t = (std::max)(0.0f, (std::min)(1.0f, t)); return t * t * (3.0f - 2.0f * t); };
    for (int y = 0; y < N; ++y) {
        uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(dst.pBits) + y * dst.Pitch);
        for (int x = 0; x < N; ++x) {
            const float dx = (x + 0.5f) / N * 2.0f - 1.0f, dy = (y + 0.5f) / N * 2.0f - 1.0f;
            const float r = std::sqrt(dx * dx + dy * dy);
            const float u = (std::atan2(dy, dx) + kPi) / (2.0f * kPi) * K;
            const int i0 = static_cast<int>(std::floor(u)) % K;
            const int i1 = (i0 + 1) % K;
            const float f = sstep(u - std::floor(u));
            const float lobe = lobes[i0] * (1.0f - f) + lobes[i1] * f;
            const float edge = 0.62f + 0.38f * lobe;
            float a = sstep((edge - r) / 0.7f);
            const float n = 0.55f * SmokeNoise(x * 0.042f, y * 0.042f, 9) + 0.30f * SmokeNoise(x * 0.083f, y * 0.083f, 10) +
                            0.15f * SmokeNoise(x * 0.17f, y * 0.17f, 11);
            a = (std::max)(0.0f, (std::min)(1.0f, a * (0.6f + 0.55f * n) * 1.15f));
            // red at the rim, orange, then hot yellow where the tongue is thickest
            const float v = std::pow(a, 1.1f);
            const float lo = (std::min)(1.0f, v / 0.55f), hi = (std::max)(0.0f, (v - 0.55f) / 0.45f);
            const float c1[3] = {0.85f, 0.16f, 0.02f}, c2[3] = {1.0f, 0.50f, 0.06f}, c3[3] = {1.0f, 0.88f, 0.50f};
            float rgb[3];
            for (int k = 0; k < 3; ++k) rgb[k] = (c1[k] * (1.0f - lo) + c2[k] * lo) * (1.0f - hi) + c3[k] * hi;
            auto q = [](float t) { return static_cast<uint32_t>((std::max)(0.0f, (std::min)(1.0f, t)) * 255.0f + 0.5f); };
            row[x] = (q(a) << 24) | (q(rgb[0] * a) << 16) | (q(rgb[1] * a) << 8) | q(rgb[2] * a);
        }
    }
    made->UnlockRect(0);
    g_flameTexture = made;
    return made;
}

// Flame tongues and sparks off one burning spot. `size` is the spot's own size in tiles.
void SpawnFlames(float x, float y, float z, float size, float share) {
    const float scale = (std::max)(0.5f, size);
    auto count = [&](float perSecond) {
        const float expect = perSecond * share * g_puffDt;
        int n = static_cast<int>(expect);
        if (SkidRand() < expect - static_cast<float>(n)) ++n;
        return n;
    };
    const int tongues = count(g_fire.flameRate);
    for (int i = 0; i < tongues; ++i) {
        if (g_flames.size() >= 700) g_flames.erase(g_flames.begin());
        Puff p;
        const float spread = 0.17f * scale;
        p.x = x + (SkidRand() - 0.5f) * spread * 2.0f;
        p.z = z + (SkidRand() - 0.5f) * spread * 2.0f;
        p.y = y + 0.02f;
        p.vx = (SkidRand() - 0.5f) * 0.10f;
        p.vz = (SkidRand() - 0.5f) * 0.10f;
        p.vy = (0.22f + 0.34f * SkidRand()) * g_fire.flameRise;
        p.angle = SkidRand() * 6.2831853f;
        p.spin = (SkidRand() - 0.5f) * 3.0f;
        p.size0 = (0.50f + 0.32f * SkidRand()) * g_fire.flameSize * scale * 0.62f;
        p.size1 = p.size0 * 0.45f;
        p.life = g_fire.flameLife * (0.65f + 0.7f * SkidRand());
        p.age = 0.0f;
        p.alphaMax = g_fire.flameBright;
        g_flames.push_back(p);
    }
    const int sparks = count(g_fire.emberRate);
    for (int i = 0; i < sparks; ++i) {
        if (g_embers.size() >= 200) g_embers.erase(g_embers.begin());
        Puff p;
        p.x = x + (SkidRand() - 0.5f) * 0.3f * scale;
        p.z = z + (SkidRand() - 0.5f) * 0.3f * scale;
        p.y = y + 0.05f;
        p.vx = (SkidRand() - 0.5f) * 0.5f;
        p.vz = (SkidRand() - 0.5f) * 0.5f;
        p.vy = 0.5f + 0.9f * SkidRand();
        p.angle = 0.0f;
        p.spin = 0.0f;
        p.size0 = p.size1 = 0.028f + 0.030f * SkidRand();
        p.life = 0.7f + 1.0f * SkidRand();
        p.age = 0.0f;
        p.alphaMax = 1.0f;
        g_embers.push_back(p);
    }
}

// Draws the tongues and sparks additively - Remix takes additive draws for emissive particles, so
// the fire lights its surroundings - flat on the horizontal like the smoke, one fixed quad.
void DrawFlames(IDirect3DDevice9* device, bool blending, DWORD alphaRef) {
    if (!g_fire.flames || (g_flames.empty() && g_embers.empty())) return;
    IDirect3DTexture9* texture = FlameTexture(device);
    if (!texture) return;
    struct FlameVertex { float x, y, z, nx, ny, nz, u, v; };
    static const uint16_t indices[6] = {0, 1, 2, 0, 2, 3};
    static const FlameVertex quad[4] = {
        {-0.5f, 0, -0.5f, 0, 1, 0, 0, 1}, {0.5f, 0, -0.5f, 0, 1, 0, 1, 1},
        {0.5f, 0, 0.5f, 0, 1, 0, 1, 0},   {-0.5f, 0, 0.5f, 0, 1, 0, 0, 0},
    };
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_ONE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_TFACTOR);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    device->SetTexture(0, texture);
    const float now = static_cast<float>(SkidNowSeconds());

    auto drawOne = [&](const Puff& p, bool ember) {
        const float t = p.age / p.life;
        const float grow = p.size0 + (p.size1 - p.size0) * t;
        const float rise = t < 0.1f ? t / 0.1f : 1.0f;
        float level = p.alphaMax * rise * std::pow(1.0f - t, ember ? 0.7f : 0.85f);
        // Each tongue shimmers on a phase of its own.
        level *= 0.82f + 0.18f * std::sin(now * 17.0f + p.angle * 5.0f);
        if (level < 0.01f) return;
        const float wobble = ember ? 0.0f : 0.045f * std::sin(p.age * 9.0f + p.angle * 3.0f);
        const float angle = p.angle + p.spin * p.age;
        D3DMATRIX world = {};
        world._11 = grow * std::cos(angle);
        world._13 = grow * std::sin(angle);
        world._31 = -grow * std::sin(angle);
        world._33 = grow * std::cos(angle);
        world._22 = 1.0f;
        world._41 = p.x + p.vx * p.age + wobble;
        world._42 = p.y + p.vy * p.age;
        world._43 = p.z + p.vz * p.age + wobble * 0.7f;
        world._44 = 1.0f;
        device->SetTransform(D3DTS_WORLD, &world);
        // Cools towards red as it rises; a spark stays hot and just goes out.
        const float g = ember ? 0.72f : 1.0f - 0.5f * t, b = ember ? 0.30f : 1.0f - 0.85f * t;
        auto q = [](float v) { return static_cast<int>((std::max)(0.0f, (std::min)(1.0f, v)) * 255.0f + 0.5f); };
        device->SetRenderState(D3DRS_TEXTUREFACTOR, D3DCOLOR_ARGB(255, q(level), q(level * g), q(level * b)));
        device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, 4, 2, indices, D3DFMT_INDEX16, quad, sizeof(FlameVertex));
    };
    for (const Puff& p : g_flames) drawOne(p, false);
    for (const Puff& p : g_embers) drawOne(p, true);

    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
    device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, blending ? TRUE : FALSE);
    device->SetRenderState(D3DRS_ALPHAREF, blending ? 1u : alphaRef);
}

void SpawnPuffs(float x, float y, float z) {
    float count = g_skid.smokeAmount;
    int n = static_cast<int>(count);
    if (SkidRand() < count - static_cast<float>(n)) ++n;
    for (int i = 0; i < n; ++i) {
        if (g_puffs.size() >= 600) g_puffs.erase(g_puffs.begin());
        Puff p;
        p.x = x + (SkidRand() - 0.5f) * 0.10f;
        p.z = z + (SkidRand() - 0.5f) * 0.10f;
        p.y = y + 0.03f;
        p.vx = (SkidRand() - 0.5f) * 0.14f * g_skid.smokeDrift;
        p.vz = (SkidRand() - 0.5f) * 0.14f * g_skid.smokeDrift;
        p.vy = (0.07f + 0.08f * SkidRand()) * g_skid.smokeRise;
        p.angle = SkidRand() * 6.2831853f;
        p.spin = (SkidRand() - 0.5f) * 1.2f;
        p.size0 = (0.10f + 0.05f * SkidRand()) * g_skid.smokeSize;
        p.size1 = (0.42f + 0.28f * SkidRand()) * g_skid.smokeSize;
        p.life = g_skid.smokeLife * (0.8f + 0.4f * SkidRand());
        p.age = 0.0f;
        p.alphaMax = g_skid.smokeOpacity;
        p.grey = 1.0f;
        g_puffs.push_back(p);
    }
}

// Dark smoke off a flame: bigger, slower, darker and longer-lived than tyre smoke.
void SpawnFireSmoke(float x, float y, float z, float size) {
    const float expect = g_fire.smokeRate * g_puffDt;
    int n = static_cast<int>(expect);
    if (SkidRand() < expect - static_cast<float>(n)) ++n;
    for (int i = 0; i < n; ++i) {
        if (g_fireSmoke.size() >= 150) g_fireSmoke.erase(g_fireSmoke.begin());
        Puff p;
        const float spread = 0.12f * (std::max)(0.5f, size);
        p.x = x + (SkidRand() - 0.5f) * spread;
        p.z = z + (SkidRand() - 0.5f) * spread;
        p.y = y + 0.06f;
        p.vx = (SkidRand() - 0.5f) * 0.16f * g_fire.smokeDrift;
        p.vz = (SkidRand() - 0.5f) * 0.16f * g_fire.smokeDrift;
        p.vy = (0.16f + 0.14f * SkidRand()) * g_fire.smokeRise;
        p.angle = SkidRand() * 6.2831853f;
        p.spin = (SkidRand() - 0.5f) * 0.9f;
        p.size0 = (0.22f + 0.08f * SkidRand()) * g_fire.smokeSize;
        p.size1 = (0.9f + 0.5f * SkidRand()) * g_fire.smokeSize;
        p.life = g_fire.smokeLife * (0.75f + 0.5f * SkidRand());
        p.age = 0.0f;
        p.alphaMax = g_fire.smokeOpacity;
        p.grey = g_fire.smokeGrey;
        g_fireSmoke.push_back(p);
    }
}

double SkidNowSeconds() {
    static LARGE_INTEGER frequency = {};
    if (!frequency.QuadPart) QueryPerformanceFrequency(&frequency);
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    return static_cast<double>(now.QuadPart) / static_cast<double>(frequency.QuadPart);
}

void ClearSkidGhosts() {
    for (auto& g : g_skidGhosts) {
        if (g.second.source) g.second.source->Release();
    }
    g_skidGhosts.clear();
}

// Remembers a rubber strip the game has just submitted. The first sighting fixes its
// artwork and its birth time; later ones change nothing, so the game's own thinning of
// an old mark does not touch it.
void NoteSkidStrip(const LiveGeometry::SpriteType& s, IDirect3DTexture9* source, double now) {
    const int32_t kx = static_cast<int32_t>(std::floor(s.objectToWorld.m[3][0] * 256.0f));
    const int32_t kz = static_cast<int32_t>(std::floor(s.objectToWorld.m[3][2] * 256.0f));
    const uint64_t key = (static_cast<uint64_t>(static_cast<uint32_t>(kx)) << 32) |
                         static_cast<uint32_t>(kz);
    if (g_skidGhosts.find(key) != g_skidGhosts.end()) return;
    if (g_skidGhosts.size() >= kSkidGhostCap) {
        // Full: drop the oldest tenth in one pass rather than one at a time.
        std::vector<double> borns;
        borns.reserve(g_skidGhosts.size());
        for (const auto& g : g_skidGhosts) borns.push_back(g.second.born);
        const size_t cut = borns.size() / 10;
        std::nth_element(borns.begin(), borns.begin() + cut, borns.end());
        const double limit = borns[cut];
        for (auto it = g_skidGhosts.begin(); it != g_skidGhosts.end();) {
            if (it->second.born < limit) {
                if (it->second.source) it->second.source->Release();
                it = g_skidGhosts.erase(it);
            } else {
                ++it;
            }
        }
    }
    SkidGhost ghost;
    ghost.sprite = s;
    ghost.sprite.lamp = nullptr;
    ghost.sprite.hidden = false;
    ghost.sprite.ghost = false;
    ghost.source = source;
    source->AddRef();
    ghost.born = now;
    g_skidGhosts.emplace(key, std::move(ghost));
}

// Draws one list of puffs: flat quads laid on the horizontal, since the view is from above.
// One fixed unit quad serves every puff and the world matrix places it. Remix keys a mesh on
// its vertices, so a quad rebuilt in world space each frame was a new mesh per puff per frame -
// hundreds of acceleration structures rebuilt every frame, which is what made a burning car
// lag. A fixed one is a single mesh.
// glow draws the puffs added to the picture (see SmokeGlowTexture): Remix takes that as a light
// of its own, so the smoke is white whatever lights the road - drawn as an ordinary translucent
// surface it is lit like one and comes out grey over dark asphalt.
void DrawPuffList(IDirect3DDevice9* device, const std::vector<Puff>& list, bool blending,
                  DWORD alphaRef, bool glow = false) {
    if (list.empty()) return;
    IDirect3DTexture9* texture = glow ? SmokeGlowTexture(device) : SmokeTexture(device);
    if (!texture) return;

    struct SmokeVertex { float x, y, z, nx, ny, nz, u, v; };
    static const uint16_t indices[6] = {0, 1, 2, 0, 2, 3};
    static const SmokeVertex quad[4] = {
        {-0.5f, 0, -0.5f, 0, 1, 0, 0, 1},
        {0.5f, 0, -0.5f, 0, 1, 0, 1, 1},
        {0.5f, 0, 0.5f, 0, 1, 0, 1, 0},
        {-0.5f, 0, 0.5f, 0, 1, 0, 0, 0},
    };
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHAFUNC, D3DCMP_GREATEREQUAL);
    device->SetRenderState(D3DRS_ALPHAREF, 1u);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_SRCBLEND, glow ? D3DBLEND_ONE : D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, glow ? D3DBLEND_ONE : D3DBLEND_INVSRCALPHA);
    if (glow) device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    // The texture's own grey, scaled by the puff's grey: white tyre smoke, black fire smoke.
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_TFACTOR);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, glow ? D3DTOP_SELECTARG1 : D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_TFACTOR);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    device->SetTexture(0, texture);

    for (const Puff& p : list) {
        const float t = p.age / p.life;
        const float grow = 1.0f - (1.0f - t) * (1.0f - t);
        const float size = p.size0 + (p.size1 - p.size0) * grow;
        const float rise = t < 0.12f ? t / 0.12f : 1.0f;
        const float alpha = p.alphaMax * rise * std::pow(1.0f - t, 1.4f);
        if (alpha < 0.004f) continue;
        const float angle = p.angle + p.spin * p.age;
        D3DMATRIX world = {};
        world._11 = size * std::cos(angle);
        world._13 = size * std::sin(angle);
        world._31 = -size * std::sin(angle);
        world._33 = size * std::cos(angle);
        world._22 = 1.0f;
        world._41 = p.x + p.vx * p.age;
        world._42 = p.y + p.vy * p.age;
        world._43 = p.z + p.vz * p.age;
        world._44 = 1.0f;
        device->SetTransform(D3DTS_WORLD, &world);
        const float grey = (std::min)(1.0f, p.grey + (1.0f - p.grey) * t * t * 0.45f);
        const int g = static_cast<int>(grey * 255.0f + 0.5f);
        if (glow) {
            // Added, so the brightness is the colour: the puff's opacity as a level, a little
            // stronger than the translucent version so it reads as smoke over bright ground too.
            const int level = static_cast<int>((std::min)(1.0f, alpha * 1.3f * grey) * 255.0f + 0.5f);
            device->SetRenderState(D3DRS_TEXTUREFACTOR, D3DCOLOR_ARGB(255, level, level, level));
        } else {
            device->SetRenderState(D3DRS_TEXTUREFACTOR,
                                   D3DCOLOR_ARGB(static_cast<int>((std::min)(1.0f, alpha) * 255.0f + 0.5f), g, g, g));
        }
        device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, 4, 2, indices, D3DFMT_INDEX16, quad,
                                       sizeof(SmokeVertex));
    }

    if (glow) {
        device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
        device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
    }
    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, blending ? TRUE : FALSE);
    device->SetRenderState(D3DRS_ALPHAREF, blending ? 1u : alphaRef);
}

// The scorch mark: near-black soot with a ragged edge and streaks thrown outward from the middle.
IDirect3DTexture9* ScorchTexture(IDirect3DDevice9* device) {
    if (g_scorchTexture) return g_scorchTexture;
    constexpr int N = 128;
    IDirect3DTexture9* made = nullptr;
    if (FAILED(device->CreateTexture(N, N, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &made, nullptr))) return nullptr;
    D3DLOCKED_RECT dst;
    if (FAILED(made->LockRect(0, &dst, nullptr, 0))) {
        made->Release();
        return nullptr;
    }
    auto fbm = [](float x, float y, int salt) {
        return 0.55f * SmokeNoise(x, y, salt) + 0.30f * SmokeNoise(x * 2.1f, y * 2.1f, salt + 7) +
               0.15f * SmokeNoise(x * 4.3f, y * 4.3f, salt + 13);
    };
    for (int y = 0; y < N; ++y) {
        uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(dst.pBits) + y * dst.Pitch);
        for (int x = 0; x < N; ++x) {
            const float dx = (x + 0.5f) / N * 2.0f - 1.0f, dy = (y + 0.5f) / N * 2.0f - 1.0f;
            const float r = std::sqrt(dx * dx + dy * dy);
            const float ang = std::atan2(dy, dx);
            // The edge wanders; the streaks are long thin rays reaching past it.
            const float edge = 0.50f + 0.34f * (fbm(dx * 2.2f + 5.0f, dy * 2.2f + 9.0f, 21) - 0.5f) * 2.0f;
            const float ray = SmokeNoise(ang * 3.2f + 40.0f, r * 1.5f, 33);
            const float reach = edge + 0.20f * (ray - 0.35f);
            float a = 1.0f - (r - reach * 0.55f) / (std::max)(0.05f, reach * 0.55f + 0.1f);
            a = (std::max)(0.0f, (std::min)(1.0f, a));
            a = a * a * (3.0f - 2.0f * a);
            // Mottled: patches of heavier soot and patches that are only dusted.
            a *= 0.62f + 0.38f * fbm(dx * 5.0f + 11.0f, dy * 5.0f + 3.0f, 55);
            // Dark hot core, a little paler brown towards the rim.
            const float rim = (std::min)(1.0f, r / (std::max)(0.2f, reach));
            const uint32_t red = static_cast<uint32_t>(10 + 22 * rim * rim);
            const uint32_t grn = static_cast<uint32_t>(8 + 16 * rim * rim);
            const uint32_t blu = static_cast<uint32_t>(7 + 12 * rim * rim);
            const uint32_t alpha = static_cast<uint32_t>((std::max)(0.0f, (std::min)(1.0f, a)) * 255.0f + 0.5f);
            row[x] = (alpha << 24) | (red << 16) | (grn << 8) | blu;
        }
    }
    made->UnlockRect(0);
    g_scorchTexture = made;
    return made;
}

// Remembers a blast. Several sprites of one explosion land on the same spot over a few frames,
// and the sprite grows: those are one mark, kept at the largest size seen.
void NoteScorch(float x, float y, float z, float size) {
    const double now = SkidNowSeconds();
    for (Scorch& s : g_scorch) {
        const float dx = s.x - x, dz = s.z - z;
        if (now - s.born < 20.0 && dx * dx + dz * dz < 1.2f * 1.2f) {
            if (size > s.size) s.size = size;
            return;
        }
    }
    if (g_scorch.size() >= 24) g_scorch.erase(g_scorch.begin());
    Scorch s;
    s.x = x; s.y = y; s.z = z;
    s.size = size;
    s.angle = SkidRand() * 6.2831853f;
    s.born = now;
    g_scorch.push_back(s);
}

void DrawScorch(IDirect3DDevice9* device, bool blending, DWORD alphaRef) {
    const double now = SkidNowSeconds();
    const double life = (std::max)(5.0, static_cast<double>(g_fire.scorchLife));
    for (size_t i = 0; i < g_scorch.size();) {
        if (now - g_scorch[i].born >= life) {
            g_scorch.erase(g_scorch.begin() + static_cast<std::ptrdiff_t>(i));
        } else {
            ++i;
        }
    }
    if (!g_fire.scorch || g_scorch.empty()) return;
    IDirect3DTexture9* texture = ScorchTexture(device);
    if (!texture) return;
    struct ScorchVertex { float x, y, z, nx, ny, nz, u, v; };
    static const uint16_t indices[6] = {0, 1, 2, 0, 2, 3};
    static const ScorchVertex quad[4] = {
        {-0.5f, 0, -0.5f, 0, 1, 0, 0, 1}, {0.5f, 0, -0.5f, 0, 1, 0, 1, 1},
        {0.5f, 0, 0.5f, 0, 1, 0, 1, 0},   {-0.5f, 0, 0.5f, 0, 1, 0, 0, 0},
    };
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHAFUNC, D3DCMP_GREATEREQUAL);
    device->SetRenderState(D3DRS_ALPHAREF, 1u);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_TFACTOR);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    device->SetTexture(0, texture);

    for (const Scorch& s : g_scorch) {
        const float t = static_cast<float>((now - s.born) / life);
        // Dark at once, held for the first stretch, then a long, eased fade to nothing.
        const float ramp = (std::min)(1.0f, static_cast<float>(now - s.born) / 0.6f);
        float k = t < 0.15f ? 1.0f : 1.0f - (t - 0.15f) / 0.85f;
        k = k * k * (3.0f - 2.0f * k);
        const float alpha = g_fire.scorchOpacity * ramp * (std::max)(0.0f, k);
        if (alpha < 0.004f) continue;
        const float size = s.size * g_fire.scorchSize * (0.85f + 0.15f * (std::min)(1.0f, static_cast<float>(now - s.born) / 1.5f));
        D3DMATRIX world = {};
        world._11 = size * std::cos(s.angle);
        world._13 = size * std::sin(s.angle);
        world._31 = -size * std::sin(s.angle);
        world._33 = size * std::cos(s.angle);
        world._22 = 1.0f;
        world._41 = s.x;
        world._42 = s.y;
        world._43 = s.z;
        world._44 = 1.0f;
        device->SetTransform(D3DTS_WORLD, &world);
        device->SetRenderState(D3DRS_TEXTUREFACTOR,
                               D3DCOLOR_ARGB(static_cast<int>((std::min)(1.0f, alpha) * 255.0f + 0.5f), 255, 255, 255));
        device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, 4, 2, indices, D3DFMT_INDEX16, quad, sizeof(ScorchVertex));
    }

    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
    device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, blending ? TRUE : FALSE);
    device->SetRenderState(D3DRS_ALPHAREF, blending ? 1u : alphaRef);
}

// Ages every puff, tyre and fire, and draws the tyre smoke. Called once a frame.
void DrawTyreSmoke(IDirect3DDevice9* device, bool blending, DWORD alphaRef) {
    const double now = SkidNowSeconds();
    static double last = 0.0;
    const float dt = last > 0.0 ? static_cast<float>((std::min)(0.1, (std::max)(0.0, now - last))) : 0.0f;
    last = now;
    g_puffDt = dt;
    for (std::vector<Puff>* list : {&g_puffs, &g_fireSmoke, &g_flames, &g_embers}) {
        for (size_t i = 0; i < list->size();) {
            (*list)[i].age += dt;
            if ((*list)[i].age >= (*list)[i].life) {
                (*list)[i] = list->back();
                list->pop_back();
            } else {
                ++i;
            }
        }
    }
    if (g_skid.smoke) DrawPuffList(device, g_puffs, blending, alphaRef, g_skid.smokeGlow);
}

// The smoke off burning cars, drawn after the fire it comes from.
void DrawFireSmoke(IDirect3DDevice9* device, bool blending, DWORD alphaRef) {
    if (g_fire.smoke) DrawPuffList(device, g_fireSmoke, blending, alphaRef);
}

}  // namespace

IDirect3DTexture9* SmoothedSmallTexture(IDirect3DDevice9* device, IDirect3DTexture9* source) {
    if (!g_spriteSmooth || !device || !source) return source;
    return SmoothSpriteTexture(device, source);
}

// ---- Tyres ----------------------------------------------------------------------
//
// See SetCarWheels. A dark rubber texture of our own, and each car's steering, worked
// out from how its placement changed between frames.
namespace {

IDirect3DTexture9* g_tyreTexture = nullptr;
IDirect3DDevice9* g_tyreDevice = nullptr;

void ReleaseTyreTexture() {
    if (g_tyreTexture) g_tyreTexture->Release();
    g_tyreTexture = nullptr;
    g_tyreDevice = nullptr;
}

IDirect3DTexture9* TyreTexture(IDirect3DDevice9* device) {
    if (g_tyreDevice != device) ReleaseTyreTexture();
    if (g_tyreTexture) return g_tyreTexture;
    IDirect3DTexture9* texture = nullptr;
    if (FAILED(device->CreateTexture(4, 4, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &texture, nullptr))) {
        return nullptr;
    }
    D3DLOCKED_RECT locked;
    if (SUCCEEDED(texture->LockRect(0, &locked, nullptr, 0))) {
        for (int y = 0; y < 4; ++y) {
            uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(locked.pBits) + y * locked.Pitch);
            for (int x = 0; x < 4; ++x) row[x] = 0xFF1C1C1E;
        }
        texture->UnlockRect(0);
    }
    g_tyreTexture = texture;
    g_tyreDevice = device;
    return texture;
}

// One car's steering, estimated from where it was and which way it faced last frame.
struct SteerState {
    float x = 0, z = 0, yaw = 0;
    float angle = 0;       // radians, positive turns toward increasing yaw
    uint32_t frame = 0;
};
std::map<uintptr_t, SteerState> g_steer;

float WrapAngle(float a) {
    const float kPi = 3.14159265f;
    while (a > kPi) a -= 2.0f * kPi;
    while (a < -kPi) a += 2.0f * kPi;
    return a;
}

}  // namespace

// The last complete frame's conform counts. The menu has no handle on the
// LiveGeometry instance - the same reason EffectBatchesDrawn is a free function.
LiveGeometry::Conform g_lastConform;
const LiveGeometry::Conform& SpriteConformCounts() { return g_lastConform; }


// ---- Cars as Remix materials ------------------------------------------------
//
// A D3D9 draw can only carry the global legacy material, so a car cannot be made
// glossy without making the road and the grass glossy too. The Remix API can
// give one mesh its own material, but it takes the albedo as a file: each car
// sprite's artwork is written once to a small DDS beside the game, and a material
// made from it. Everything here fails soft - any refusal leaves the dome to be
// drawn as ordinary geometry, as it was before.
namespace {
struct CarMaterial {
    remixapi_MaterialHandle handle = nullptr;
    bool failed = false;
    uint32_t born = 0;   // the frame it was made in; see kCarMaterialWarmup
    float gain[3] = {1.0f, 1.0f, 1.0f};   // the car's repaint
    float tint[3] = {1.0f, 1.0f, 1.0f};   // what takes the game's default paint to this car's
};
uint32_t g_carFrame = 0;
// The arrest (POLICE-3D). GTA2 has no hands-up animation: an officer punches the
// wanted player down (state 8, sub-state 0x16, frame 72 lying) and the game busts
// him there - his cop points (ped+0x20A) are cleared and his weapons taken while
// he still has health - then about 2.5 s later he is back at the police station.
// ActionProbes notes that moment (g_bustFrame); the player's figure then gets up,
// raises his hands, is cuffed and walks with his hands behind his back towards the
// nearest police car until the game moves him (see DrawPedFigures).
uint32_t g_bustFrame = 0;
struct ArrestWalk { float ox = 0.0f, oz = 0.0f, carX = 0.0f, carZ = 0.0f; bool car = false; uint32_t frame = 0; };
ArrestWalk g_arrestWalk;
constexpr uint32_t kBustFrames = 360;      // how long after the bust the figure may act it out (the game moves him after 2.5-6 s)
constexpr float kBustUpSecs = 0.7f;        // getting up (the knock-down played back)
constexpr float kBustHandsSecs = 1.3f;     // hands up until then, cuffed after
// New car materials built this frame. Each is a recolour of the hand-made artwork, a file
// written, and a trip over the bridge, so a street of new cars at once was one long frame.
int g_carMaterialsThisFrame = 0;
// The last artwork of each car (by game object) whose material was ready. A car's
// artwork changes for a few frames whenever a door opens, and each change is a
// new material to load; through those frames the car keeps the last one it had
// loaded rather than falling back to the flat sprite and back.
struct WarmArt {
    IDirect3DTexture9* art = nullptr;
    int sprite = -1;
    uint32_t seen = 0;
};
std::map<uintptr_t, WarmArt> g_warmArt;
// Remix loads a new material's textures in the background, and until they are in
// it draws something else. A car's art changes with its doors, its damage and
// its paint, so a new material is not trusted for this many frames, and the
// plain sprite stands in for the car meanwhile rather than the car flickering.
constexpr uint32_t kCarMaterialWarmup = 8;
std::map<std::pair<IDirect3DTexture9*, int>, CarMaterial> g_carMaterials;
// A car's art is a new texture whenever a door opens or a panel is dented, and each
// new texture used to be a new material, cold for kCarMaterialWarmup frames: the car
// fell back to its flat low-resolution sprite and back as it was entered. The same
// material is now found again from what it is made of: for a hand-made car, its
// sprite and its paint; for any other, the pixels.
std::map<std::pair<int, uint64_t>, CarMaterial> g_hdMaterials;
std::map<uint64_t, CarMaterial> g_pixelMaterials;
std::map<uint64_t, remixapi_MeshHandle> g_carMeshes;
int g_carMaterialLogs = 0;

uint64_t Fnv64(const void* data, size_t bytes, uint64_t hash = 1469598103934665603ull) {
    const uint8_t* p = static_cast<const uint8_t*>(data);
    for (size_t i = 0; i < bytes; ++i) {
        hash ^= p[i];
        hash *= 1099511628211ull;
    }
    return hash;
}

std::wstring CacheDirectory() {
    wchar_t exe[MAX_PATH] = {};
    GetModuleFileNameW(nullptr, exe, MAX_PATH);
    std::wstring dir = exe;
    const size_t slash = dir.find_last_of(L"\\/");
    dir = slash == std::wstring::npos ? L"." : dir.substr(0, slash);
    return dir + L"\\gta2dx9_cache";
}

// Uncompressed BGRA8 DDS with a full mip chain, so the car is not aliased when it
// is drawn smaller than the texture.
bool WriteDds(const std::wstring& path, UINT width, UINT height, const std::vector<uint8_t>& bgra) {
    std::vector<std::vector<uint8_t>> levels;
    std::vector<std::pair<UINT, UINT>> sizes;
    levels.push_back(bgra);
    sizes.push_back({width, height});
    while (sizes.back().first > 1 || sizes.back().second > 1) {
        const UINT pw = sizes.back().first, ph = sizes.back().second;
        const UINT nw = (std::max)(1u, pw / 2), nh = (std::max)(1u, ph / 2);
        const std::vector<uint8_t>& src = levels.back();
        std::vector<uint8_t> dst(static_cast<size_t>(nw) * nh * 4);
        for (UINT y = 0; y < nh; ++y) {
            for (UINT x = 0; x < nw; ++x) {
                const UINT x0 = (std::min)(x * 2, pw - 1), x1 = (std::min)(x * 2 + 1, pw - 1);
                const UINT y0 = (std::min)(y * 2, ph - 1), y1 = (std::min)(y * 2 + 1, ph - 1);
                for (int c = 0; c < 4; ++c) {
                    const unsigned sum = src[(static_cast<size_t>(y0) * pw + x0) * 4 + c] +
                                         src[(static_cast<size_t>(y0) * pw + x1) * 4 + c] +
                                         src[(static_cast<size_t>(y1) * pw + x0) * 4 + c] +
                                         src[(static_cast<size_t>(y1) * pw + x1) * 4 + c];
                    dst[(static_cast<size_t>(y) * nw + x) * 4 + c] = static_cast<uint8_t>((sum + 2) / 4);
                }
            }
        }
        levels.push_back(std::move(dst));
        sizes.push_back({nw, nh});
    }
    uint32_t header[32] = {};
    header[0] = 0x20534444;   // "DDS "
    header[1] = 124;
    header[2] = 0x100F | 0x20000;   // CAPS | HEIGHT | WIDTH | PITCH | PIXELFORMAT | MIPMAPCOUNT
    header[3] = height;
    header[4] = width;
    header[5] = width * 4;
    header[7] = static_cast<uint32_t>(levels.size());
    header[19] = 32;          // pixel format size
    header[20] = 0x41;        // RGB | ALPHAPIXELS
    header[22] = 32;
    header[23] = 0x00FF0000;
    header[24] = 0x0000FF00;
    header[25] = 0x000000FF;
    header[26] = 0xFF000000;
    header[27] = 0x1000 | 0x8 | 0x400000;   // TEXTURE | COMPLEX | MIPMAP
    HANDLE file = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    bool ok = WriteFile(file, header, sizeof(header), &written, nullptr) && written == sizeof(header);
    for (const auto& level : levels) {
        ok = ok && WriteFile(file, level.data(), static_cast<DWORD>(level.size()), &written,
                             nullptr) && written == level.size();
    }
    CloseHandle(file);
    return ok;
}

// The first mip of a BGRA8 DDS written by WriteDds or by the tool that made the
// artwork. Anything else is refused.
bool ReadDds(const std::wstring& path, int* width, int* height, std::vector<uint8_t>* bgra) {
    HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    uint32_t header[32] = {};
    DWORD got = 0;
    bool ok = ReadFile(file, header, sizeof(header), &got, nullptr) && got == sizeof(header);
    ok = ok && header[0] == 0x20534444 && header[1] == 124 && header[19] == 32 &&
         header[20] == 0x41 && header[22] == 32 && header[3] > 0 && header[4] > 0 &&
         header[3] <= 8192 && header[4] <= 8192;
    if (ok) {
        *width = static_cast<int>(header[4]);
        *height = static_cast<int>(header[3]);
        bgra->resize(static_cast<size_t>(*width) * *height * 4);
        ok = ReadFile(file, bgra->data(), static_cast<DWORD>(bgra->size()), &got, nullptr) &&
             got == bgra->size();
    }
    CloseHandle(file);
    return ok;
}

bool g_carHd = true;
bool g_carNormalMaps = true;

// One car's hand-made artwork, found in gta2dx9_hd\: the sprite redrawn at some
// whole multiple of its own size, and the maps that go with it. All are laid out
// exactly as the sprite is, so the sprite's own texture coordinates address them.
// Paint gloss for one car sprite where it should differ from car_paint_gloss_percent: 0..1, or -1
// for the global setting. None are overridden by default.
// Set by car_paint_gloss_NN_percent in the [renderer] section of gta2dx9.ini.
constexpr int kGlossSprites = 80;
float g_paintGlossCar[kGlossSprites] = {
    -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,
    -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, 0.35f, -1,   // 38: light paint read as chrome
    -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,
    -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1};
struct HdCar {
    float paintGloss = -1.0f;
    bool tried = false;
    bool ok = false;
    int width = 0, height = 0;
    std::vector<uint8_t> albedo;   // BGRA8, at the redrawn size
    std::vector<uint8_t> roughPx, metalPx;   // BGRA8 too, when they are the albedo's size
    // The sprite as the game draws it in its own default paint, at the sprite's own
    // size, when car_NN_base.dds is there: what a repaint is measured against.
    std::vector<uint8_t> basePx;
    int baseWidth = 0, baseHeight = 0;
    std::wstring normal, rough, metal;
    std::wstring normalUsed;     // the normal map handed to Remix: this one, scaled
    bool normalPrepared = false;
    std::wstring roughUsed, metalUsed;   // the maps handed to Remix: these, with the glass made glossy
    bool glassPrepared = false;
};
float g_carNormalStrength = 0.5f;
float g_carGlassGloss = 1.0f;   // 0 leaves the glass as the maps made it
float g_carPaintGloss = 1.0f;   // 0 leaves the paint's roughness and metal as the maps made them
// A burnt-out car is the game's own sprite in a very dark palette. Its mean brightness (0-255,
// over the opaque pixels) is how it is told from paint: below this it is charred metal and soot,
// which has no gloss at all. 0 turns the rule off. Set by `car_charred_luma` in the [fire]
// section of the effects ini.
float g_charredLuma = 30.0f;
// Getting into or out of a car the pedestrian is drawn through the screen-space layer, over the
// car and its door, as the original draws him. In the path traced world he is a small sprite that
// changes artwork every animation frame while he moves across the screen, which gives the denoiser
// nothing to follow: it leaves his earlier positions behind as a see-through smear. Set by
// `boarding_ui` (off by default: it turned out the smear was not the denoiser at all, see the
// classifier note in Draw; 1 draws him in the screen layer anyway) and `boarding_ui_night_percent`, how bright he is
// after dark - the layer is not lit, so he is dimmed by the sun's height to sit in the scene.
bool g_boardingUi = false;
float g_boardingUiNight = 0.5f;
// Car sprites 65-74 are the game's burnt-out wrecks (dark, ragged, one per size of car): read
// off the style file, not guessed from the brightness.
bool IsWreckSprite(int sprite) { return sprite >= 65 && sprite <= 74; }
// How blue the artwork is: the blue over the red of its opaque pixels, 1 for grey. The Rednecks'
// pickup is navy, and the same sprite in red, green or yellow is not theirs.
float BlueOverRed(const std::vector<uint8_t>& bgra) {
    double blue = 0.0, red = 0.0;
    for (size_t at = 0; at + 3 < bgra.size(); at += 4) {
        if (bgra[at + 3] < 128) continue;
        blue += bgra[at];
        red += bgra[at + 2];
    }
    return static_cast<float>((blue + 1.0) / (red + 1.0));
}
float MeanLuma(const std::vector<uint8_t>& bgra) {
    double sum = 0.0;
    size_t count = 0;
    for (size_t at = 0; at + 3 < bgra.size(); at += 4) {
        if (bgra[at + 3] < 128) continue;
        sum += 0.114 * bgra[at] + 0.587 * bgra[at + 1] + 0.299 * bgra[at + 2];
        ++count;
    }
    return count ? static_cast<float>(sum / count) : 255.0f;
}
float g_carGlassCurve = 0.6f;   // 0 leaves the glass as flat as the normal maps made it
std::map<int, HdCar> g_hdCars;

// The glass and normal maps of a hand-made car (PrepareGlass, PrepareNormal) are a lot of
// arithmetic the first time, and a whole-picture hash every time: on a PC that has never run
// the mod, each of the 77 cars used to cost the game a stall the first time it turned up. A
// thread of its own now does that for every car one after another from the first frame on,
// and the game picks up its answer (which cache files to use) when the car first appears.
//   0 not started   1 the thread is on it   2 the thread has done it   3 the game took it
struct HdPrepared {
    std::wstring normalUsed, roughUsed, metalUsed;
    bool normalDone = false, glassDone = false;
};
constexpr int kHdPrepSprites = 80;
volatile LONG g_hdPrepState[kHdPrepSprites];
HdPrepared g_hdPrepared[kHdPrepSprites];
volatile LONG g_hdPrepStarted = 0;

std::wstring HdDirectory() {
    std::wstring dir = CacheDirectory();
    const size_t slash = dir.find_last_of(L'\\');
    return dir.substr(0, slash) + L"\\gta2dx9_hd";
}

// Reads one car's hand-made artwork from gta2dx9_hd\ into hd. Used by the game's own thread
// (HdFor) and by the preparing thread; it touches nothing shared.
void LoadHdInto(int sprite, HdCar& hd) {
    hd.paintGloss = (sprite >= 0 && sprite < kGlossSprites) ? g_paintGlossCar[sprite] : -1.0f;
    wchar_t name[64];
    const std::wstring dir = HdDirectory();
    swprintf(name, 64, L"\\car_%02d_albedo.dds", sprite);
    if (!ReadDds(dir + name, &hd.width, &hd.height, &hd.albedo)) return;
    swprintf(name, 64, L"\\car_%02d_normal.dds", sprite);
    hd.normal = dir + name;
    swprintf(name, 64, L"\\car_%02d_rough.dds", sprite);
    hd.rough = dir + name;
    swprintf(name, 64, L"\\car_%02d_metal.dds", sprite);
    hd.metal = dir + name;
    hd.ok = GetFileAttributesW(hd.normal.c_str()) != INVALID_FILE_ATTRIBUTES &&
            GetFileAttributesW(hd.rough.c_str()) != INVALID_FILE_ATTRIBUTES &&
            GetFileAttributesW(hd.metal.c_str()) != INVALID_FILE_ATTRIBUTES;
    if (hd.ok) {
        swprintf(name, 64, L"\\car_%02d_base.dds", sprite);
        if (!ReadDds(dir + name, &hd.baseWidth, &hd.baseHeight, &hd.basePx)) hd.basePx.clear();
        // Read for the glass: see RecolourHd. A map that does not fit is simply
        // not used for that.
        int w = 0, h = 0;
        if (ReadDds(hd.rough, &w, &h, &hd.roughPx) && (w != hd.width || h != hd.height)) {
            hd.roughPx.clear();
        }
        if (ReadDds(hd.metal, &w, &h, &hd.metalPx) && (w != hd.width || h != hd.height)) {
            hd.metalPx.clear();
        }
    }
}

HdCar& HdFor(int sprite) {
    HdCar& hd = g_hdCars[sprite];
    if (hd.tried) return hd;
    hd.tried = true;
    // Whether the preparing thread has this car's maps ready. If it is on this very car, wait
    // for it rather than do the same work twice; if it has not got to it, the game does it
    // itself as it always did, and the thread skips it.
    bool prepared = false;
    if (sprite >= 0 && sprite < kHdPrepSprites) {
        LONG state = InterlockedCompareExchange(&g_hdPrepState[sprite], 3, 0);
        if (state == 1) {
            for (int waited = 0; waited < 30000 && InterlockedCompareExchange(&g_hdPrepState[sprite], 0, 0) == 1; ++waited) {
                Sleep(1);
            }
            state = InterlockedCompareExchange(&g_hdPrepState[sprite], 0, 0);
        }
        prepared = state == 2;
    }
    LoadHdInto(sprite, hd);
    if (prepared && hd.ok) {
        const HdPrepared& p = g_hdPrepared[sprite];
        if (p.glassDone) {
            hd.glassPrepared = true;
            hd.roughUsed = p.roughUsed;
            hd.metalUsed = p.metalUsed;
        }
        if (p.normalDone) {
            hd.normalPrepared = true;
            hd.normalUsed = p.normalUsed;
        }
    }
    if (prepared) InterlockedExchange(&g_hdPrepState[sprite], 3);
    return hd;
}

// The hand-made gang emblem for a GangLogo id, from gta2dx9_hd\logo_<name>.dds, or null when there
// is none (the game's own 20-pixel sprite is then drawn). A BGRA8 DDS laid out like the sprite, so the
// sprite's texture coordinates address it; drawn bilinear, never smoothed.
struct HdLogo {
    bool tried = false;
    IDirect3DTexture9* texture = nullptr;
};
HdLogo g_hdLogos[kLogoCount];
IDirect3DDevice9* g_hdLogoDevice = nullptr;

// Gang emblems laid on a car's roof by the mod itself. The game only ever put the Loonies'
// smiley on a car; the Zaibatsu Z-Type (car 63) is plain black. g_logoCar says which car sprite
// number wears each gang's emblem (-1: none). Set by the [logos] section of the effects ini.
bool g_roofLogos = true;
int g_logoCar[kLogoCount] = {-1, 32, 63, 36, 42, 26, 9};   // order of GangLogo: Meteor (Scientists), Karma Bus (Krishna), Bulwark (Russian Mafia)
float g_logoLumaMax[kLogoCount] = {0, 256, 55, 78, 0, 0, 0};  // >0: only cars whose artwork is darker than this (the black Zaibatsu paint is 48; the next darkest Z-Type paint is 59)
float g_logoSize[kLogoCount] = {0.18f, 0.11f, 0.18f, 0.15f, 0.20f, 0.40f, 0.22f};       // per emblem; the Miara's roof is small
float g_logoForward[kLogoCount] = {-0.30f, -0.20f, -0.30f, 0.20f, -0.06f, 0.0f, -0.38f};
int g_logoTurn[kLogoCount] = {2, 2, 0, 2, 0, 2, 2};  // quarter turns so the artwork stands upright when the car drives up the screen
float g_logoBlueMin[kLogoCount] = {0, 0, 0, 1.20f, 0, 0, 0};   // >0: only cars whose artwork is at least this much more blue than red
float g_logoLift = 0.004f;         // how far the emblem floats over the roof, in tiles; the higher, the longer its shadow on the roof
float g_roofLogoSize = 0.18f;      // length of the emblem along the car, in tiles
float g_roofLogoForward = -0.30f;
int g_roofLogoQuarter = 0;         // quarter turns of the emblem on the roof (rotate_degrees / 90)    // -1..1 of half the car's length; positive is toward the nose

void ReleaseHdLogos() {
    for (HdLogo& logo : g_hdLogos) {
        if (logo.texture) logo.texture->Release();
        logo = HdLogo();
    }
}

IDirect3DTexture9* HdLogoTexture(IDirect3DDevice9* device, int id) {
    if (id < 0 || id >= kLogoCount) return nullptr;
    if (g_hdLogoDevice != device) {
        ReleaseHdLogos();
        g_hdLogoDevice = device;
    }
    HdLogo& logo = g_hdLogos[id];
    if (logo.tried) return logo.texture;
    logo.tried = true;
    static const wchar_t* const kNames[kLogoCount] = {L"loonies", L"yakuza", L"zaibatsu", L"rednecks",
                                                       L"srs", L"krishna", L"russian"};
    const std::wstring path = HdDirectory() + L"\\logo_" + kNames[id] + L".dds";
    int w = 0, h = 0;
    std::vector<uint8_t> bgra;
    if (!ReadDds(path, &w, &h, &bgra)) return nullptr;
    IDirect3DTexture9* made = nullptr;
    if (FAILED(device->CreateTexture(w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &made, nullptr))) {
        return nullptr;
    }
    D3DLOCKED_RECT out;
    if (FAILED(made->LockRect(0, &out, nullptr, 0))) {
        made->Release();
        return nullptr;
    }
    for (int y = 0; y < h; ++y) {
        memcpy(static_cast<uint8_t*>(out.pBits) + y * out.Pitch, &bgra[static_cast<size_t>(y) * w * 4],
               static_cast<size_t>(w) * 4);
    }
    made->UnlockRect(0);
    logo.texture = made;
    Log("logo: loaded %ls (%dx%d)", path.c_str(), w, h);
    return made;
}

// The redrawn car in the colours this sprite is actually drawn in. The redraw is
// in the car's default paint; the game recolours the sprite per car, so the
// redraw's fine detail - the ratio of each of its pixels to the average of the
// sprite pixel it sits in - is laid over the sprite's own colours, smoothly
// enlarged. Every paint job gets the new detail without being redrawn.
// How much of glass a pixel of the car's maps is, 0..1: smooth and not metal.
float GlassWeight(const HdCar& hd, size_t at) {
    if (hd.roughPx.empty() || hd.metalPx.empty() || at + 2 >= hd.roughPx.size()) return 0.0f;
    const float rough = hd.roughPx[at] / 255.0f;
    const float metal = hd.metalPx[at] / 255.0f;
    const float a = (std::max)(0.0f, (std::min)(1.0f, (0.17f - rough) / 0.08f));
    const float b = (std::max)(0.0f, (std::min)(1.0f, (0.22f - metal) / 0.10f));
    return a * b;
}

// The car's normal map at the strength the setting asks for. The maps on disk are
// built to show every panel line and curve; a lot of that is more than a painted
// redraw can carry and shows up as odd glints, so the tilt of every normal is
// scaled back here and the result kept in the cache beside the artwork.
const std::wstring& PrepareNormal(HdCar& hd) {
    if (hd.normalPrepared) return hd.normalUsed;
    hd.normalPrepared = true;
    hd.normalUsed = hd.normal;
    const float strength = g_carNormalStrength;
    const float curve = g_carGlassCurve;
    const bool bulge = curve > 0.005f && !hd.roughPx.empty() && !hd.metalPx.empty();
    if (strength >= 0.995f && !bulge) return hd.normalUsed;
    int w = 0, h = 0;
    std::vector<uint8_t> px;
    if (!ReadDds(hd.normal, &w, &h, &px)) return hd.normalUsed;
    const bool fits = bulge && w == hd.width && h == hd.height;
    uint64_t hash = Fnv64(px.data(), px.size());
    const int percent = static_cast<int>(strength * 100.0f + 0.5f);
    hash = Fnv64(&percent, sizeof(percent), hash);
    const int curvePercent = fits ? static_cast<int>(curve * 100.0f + 0.5f) : 0;
    if (curvePercent) hash = Fnv64(&curvePercent, sizeof(curvePercent), hash ^ 0x61A55u);
    const std::wstring dir = CacheDirectory();
    CreateDirectoryW(dir.c_str(), nullptr);
    wchar_t name[64];
    swprintf(name, 64, L"\\normal_%016llx.dds", static_cast<unsigned long long>(hash));
    const std::wstring path = dir + name;
    CacheWarmupNote(path);
    if (GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES) {
        // The maps keep the glass a flat, sunk panel, and a flat mirror seen from above
        // reflects one patch of sky: the same everywhere on the window. Glass bulged
        // outwards turns each part of it to a different part of the sky - the lighter
        // horizon, a sun glint, a street lamp - which is what makes a window read as
        // glass. The bulge is the blurred glass mask used as a height: the normal
        // tilts away from the middle of each window, by up to `curve` x 0.5 slope.
        std::vector<float> gx, gy;
        if (fits) {
            const size_t count = static_cast<size_t>(w) * h;
            std::vector<float> a(count), b(count);
            for (size_t i = 0; i < count; ++i) {
                a[i] = GlassWeight(hd, i * 4);
            }
            const int radius = (std::max)(3, w / 18);
            for (int pass = 0; pass < 3; ++pass) {
                // Box blur along x, then along y, by running sums.
                for (int y = 0; y < h; ++y) {
                    float acc = 0.0f;
                    for (int x = -radius; x <= radius; ++x) {
                        acc += a[static_cast<size_t>(y) * w + (std::min)((std::max)(x, 0), w - 1)];
                    }
                    for (int x = 0; x < w; ++x) {
                        b[static_cast<size_t>(y) * w + x] = acc / (2 * radius + 1);
                        const int add = (std::min)(x + radius + 1, w - 1);
                        const int sub = (std::max)(x - radius, 0);
                        acc += a[static_cast<size_t>(y) * w + add] - a[static_cast<size_t>(y) * w + sub];
                    }
                }
                for (int x = 0; x < w; ++x) {
                    float acc = 0.0f;
                    for (int y = -radius; y <= radius; ++y) {
                        acc += b[static_cast<size_t>((std::min)((std::max)(y, 0), h - 1)) * w + x];
                    }
                    for (int y = 0; y < h; ++y) {
                        a[static_cast<size_t>(y) * w + x] = acc / (2 * radius + 1);
                        const int add = (std::min)(y + radius + 1, h - 1);
                        const int sub = (std::max)(y - radius, 0);
                        acc += b[static_cast<size_t>(add) * w + x] - b[static_cast<size_t>(sub) * w + x];
                    }
                }
            }
            gx.assign(count, 0.0f);
            gy.assign(count, 0.0f);
            float peak = 0.0f;
            for (int y = 1; y + 1 < h; ++y) {
                for (int x = 1; x + 1 < w; ++x) {
                    const size_t at = static_cast<size_t>(y) * w + x;
                    gx[at] = (a[at + 1] - a[at - 1]) * 0.5f;
                    gy[at] = (a[at + w] - a[at - w]) * 0.5f;
                    peak = (std::max)(peak, std::sqrt(gx[at] * gx[at] + gy[at] * gy[at]));
                }
            }
            if (peak > 1e-6f) {
                const float scale = 0.5f * (std::min)(curve, 1.5f) / peak;
                for (size_t i = 0; i < count; ++i) {
                    gx[i] *= scale;
                    gy[i] *= scale;
                }
            } else {
                gx.clear();
                gy.clear();
            }
        }
        for (size_t i = 0; i + 3 < px.size(); i += 4) {
            float nx = (px[i + 2] / 255.0f * 2.0f - 1.0f) * strength;
            float ny = (px[i + 1] / 255.0f * 2.0f - 1.0f) * strength;
            float nz = (std::max)(px[i + 0] / 255.0f * 2.0f - 1.0f, 0.05f);
            if (!gx.empty()) {
                // Same convention as the maps: x is minus the slope along the row, y is
                // plus the slope down the column, so a hill tilts away from its top.
                nx -= gx[i / 4];
                ny += gy[i / 4];
            }
            const float len = std::sqrt(nx * nx + ny * ny + nz * nz);
            px[i + 2] = static_cast<uint8_t>((nx / len * 0.5f + 0.5f) * 255.0f + 0.5f);
            px[i + 1] = static_cast<uint8_t>((ny / len * 0.5f + 0.5f) * 255.0f + 0.5f);
            px[i + 0] = static_cast<uint8_t>((nz / len * 0.5f + 0.5f) * 255.0f + 0.5f);
        }
        if (!WriteDds(path, w, h, px)) return hd.normalUsed;
    }
    hd.normalUsed = path;
    return hd.normalUsed;
}

// A car's roughness and metal maps with the glass made a mirror: smooth but not
// perfectly - a perfect mirror from straight above shows the dark sky and nothing
// else, where a little roughness gathers a street lamp or a headlight into a
// glint - and metal, so that what it reflects is tinted by the glass's own
// colour (which RecolourHd brightens to match) rather than the few percent a dark
// dielectric gives from straight above. Kept in the cache beside the artwork.
void PrepareGlass(HdCar& hd) {
    if (hd.glassPrepared) return;
    hd.glassPrepared = true;
    hd.roughUsed = hd.rough;
    hd.metalUsed = hd.metal;
    const float gloss = g_carGlassGloss;
    const float paintGloss = (std::min)(hd.paintGloss >= 0.0f ? hd.paintGloss : g_carPaintGloss, 1.0f);
    if ((gloss < 0.01f && paintGloss < 0.01f) || hd.roughPx.empty() || hd.metalPx.empty()) return;
    uint64_t hash = Fnv64(hd.roughPx.data(), hd.roughPx.size());
    hash = Fnv64(hd.metalPx.data(), hd.metalPx.size(), hash);
    const int percent = static_cast<int>(gloss * 100.0f + 0.5f);
    hash = Fnv64(&percent, sizeof(percent), hash);
    const int paintPercent = static_cast<int>(paintGloss * 100.0f + 0.5f);
    hash = Fnv64(&paintPercent, sizeof(paintPercent), hash ^ 0x9A1117u);
    const std::wstring dir = CacheDirectory();
    CreateDirectoryW(dir.c_str(), nullptr);
    wchar_t name[96];
    swprintf(name, 96, L"\\glassr_%016llx.dds", static_cast<unsigned long long>(hash));
    const std::wstring roughPath = dir + name;
    swprintf(name, 96, L"\\glassm_%016llx.dds", static_cast<unsigned long long>(hash));
    const std::wstring metalPath = dir + name;
    CacheWarmupNote(roughPath);
    CacheWarmupNote(metalPath);
    if (GetFileAttributesW(roughPath.c_str()) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(metalPath.c_str()) == INVALID_FILE_ATTRIBUTES) {
        std::vector<uint8_t> rough = hd.roughPx, metal = hd.metalPx;
        for (size_t at = 0; at + 3 < rough.size(); at += 4) {
            const float g = GlassWeight(hd, at) * (std::min)(gloss, 1.0f);
            // Paint is what the maps make a middling roughness: not the mirror of glass
            // or chrome, not the satin of a work deck. Left at 0.30 rough and 0.30 metal
            // it reflects a street lamp as a broad dull smear; smoother, and with more
            // metal in it, the same lamp is a bright crisp glint and the car beside it
            // shows up in the paint.
            const float r0 = rough[at] / 255.0f;
            const float pw = paintGloss *
                (std::max)(0.0f, (std::min)(1.0f, (r0 - 0.20f) / 0.06f)) *
                (std::max)(0.0f, (std::min)(1.0f, (0.50f - r0) / 0.10f));
            if (g <= 0.0f && pw <= 0.0f) continue;
            float r = rough[at];
            float m = metal[at];
            if (pw > 0.0f) {
                r *= 1.0f - 0.45f * pw;
                m += (std::max)(0.0f, 0.45f * 255.0f - m) * pw;
            }
            if (g > 0.0f) {
                r += (0.10f * 255.0f - r) * g;
                m += (0.85f * 255.0f - m) * g;
            }
            for (int c = 0; c < 3; ++c) {
                rough[at + c] = static_cast<uint8_t>(r + 0.5f);
                metal[at + c] = static_cast<uint8_t>(m + 0.5f);
            }
        }
        if (!WriteDds(roughPath, hd.width, hd.height, rough) ||
            !WriteDds(metalPath, hd.width, hd.height, metal)) return;
    }
    hd.roughUsed = roughPath;
    hd.metalUsed = metalPath;
}

// Makes every hand-made car's glass and normal maps (and reads its artwork, so the disk has
// it in memory when the car turns up), one car at a time, at the lowest priority. Keeps
// nothing but the names of the files it made; see g_hdPrepState.
DWORD WINAPI HdPrepareThread(LPVOID) {
    SetThreadPriority(GetCurrentThread(), THREAD_MODE_BACKGROUND_BEGIN);
    Sleep(1500);
    const DWORD started = GetTickCount();
    int cars = 0;
    for (int sprite = 0; sprite < kHdPrepSprites; ++sprite) {
        if (InterlockedCompareExchange(&g_hdPrepState[sprite], 1, 0) != 0) continue;   // the game has it
        {
            HdCar car;
            LoadHdInto(sprite, car);
            if (car.ok) {
                HdPrepared& p = g_hdPrepared[sprite];
                PrepareGlass(car);
                p.roughUsed = car.roughUsed;
                p.metalUsed = car.metalUsed;
                p.glassDone = true;
                if (g_carNormalMaps) {
                    PrepareNormal(car);
                    p.normalUsed = car.normalUsed;
                    p.normalDone = true;
                }
                ++cars;
            }
        }
        InterlockedExchange(&g_hdPrepState[sprite], 2);
    }
    Log("hand-made cars: glass and normal maps ready for %d cars in %.1f s (done off the game's thread)",
        cars, (GetTickCount() - started) / 1000.0);
    return 0;
}

void StartHdPrepare() {
    if (InterlockedExchange(&g_hdPrepStarted, 1)) return;
    HANDLE thread = CreateThread(nullptr, 0, HdPrepareThread, nullptr, 0, nullptr);
    if (thread) CloseHandle(thread);
}

// Which pixels of a car's sprite the game's door and dent deltas can paint, either
// side: the colour of the car is not read there.
const std::vector<uint8_t>& DeltaFootprint(int sprite, int w, int h) {
    auto found = g_deltaFootprint.find(sprite);
    if (found != g_deltaFootprint.end()) return found->second;
    std::vector<uint8_t> mask(static_cast<size_t>(w) * h, 0);
    for (const auto& entry : g_deltaArt) {
        if (sprite < 0 || sprite >= static_cast<int>(entry.second.size())) continue;
        const LampArt& a = entry.second[sprite];
        if (!a.Valid() || a.spriteWidth != w || a.spriteHeight != h) continue;
        for (int y = 0; y < a.height; ++y) {
            for (int x = 0; x < a.width; ++x) {
                if (!(a.argb[static_cast<size_t>(y) * a.width + x] >> 24)) continue;
                const int px = a.x0 + x, py = a.y0 + y;
                if (py < 0 || py >= h || px < 0 || px >= w) continue;
                mask[static_cast<size_t>(py) * w + px] = 1;
                mask[static_cast<size_t>(py) * w + (w - 1 - px)] = 1;
            }
        }
    }
    return g_deltaFootprint.emplace(sprite, std::move(mask)).first->second;
}

// The car's repaint as one gain per channel, not one per pixel.
//
// The redraw is not the sprite enlarged: its windows, highlights and panel
// lines sit a little differently from the sprite's, so a gain read off the
// sprite pixel by pixel and laid over the redraw landed on the wrong features
// - patches of the old paint beside patches of the new, which looked like an
// oil slick, and a repaint as coarse as the sprite. The game's repaint is a
// change of the paint's colour, so it is measured once: over the sprite
// pixels that are paint in the default colours (saturated, not tyre-dark),
// the sum of the car's colour against the sum of its default.
//
// Not over the pixels a door or a dent can change, though, and the result is
// rounded to about a tenth of a stop: a car whose door is open is the same car
// in the same paint, and must come out as the same material, not a near one.
bool MeasurePaintGain(const HdCar& hd, const std::vector<uint8_t>& game, int w, int h,
                      int sprite, float gain[3], float tint[3],
                      const std::vector<uint8_t>* footprint = nullptr) {
    gain[0] = gain[1] = gain[2] = 1.0f;
    tint[0] = tint[1] = tint[2] = 1.0f;
    const bool haveBase = hd.baseWidth == w && hd.baseHeight == h &&
                          hd.basePx.size() == static_cast<size_t>(w) * h * 4;
    if (!haveBase || hd.width % w != 0) return false;
    const int S = hd.width / w;
    const std::vector<uint8_t>& skip = footprint ? *footprint : DeltaFootprint(sprite, w, h);
    for (int pass = 0; pass < 2; ++pass) {
        double sumGame[3] = {0, 0, 0}, sumBase[3] = {0, 0, 0}, sumHd[3] = {0, 0, 0};
        int paint = 0;
        for (size_t i = 0; i < static_cast<size_t>(w) * h; ++i) {
            if (game[i * 4 + 3] < 128 || hd.basePx[i * 4 + 3] < 128) continue;
            if (pass == 0 && skip[i]) continue;
            const uint8_t* b = &hd.basePx[i * 4];
            const float mx = static_cast<float>((std::max)(b[0], (std::max)(b[1], b[2])));
            const float mn = static_cast<float>((std::min)(b[0], (std::min)(b[1], b[2])));
            if (mx < 40.0f || (mx - mn) / (mx + 1.0f) < 0.22f) continue;
            // The redraw's own colour here, over the sprite pixel's block.
            const int px = static_cast<int>(i % w), py = static_cast<int>(i / w);
            double blockSum[3] = {0, 0, 0}, blockAlpha = 0;
            for (int y = 0; y < S; ++y) {
                for (int x = 0; x < S; ++x) {
                    const uint8_t* q = &hd.albedo[(static_cast<size_t>(py * S + y) * hd.width + px * S + x) * 4];
                    const double a = q[3] / 255.0;
                    for (int c = 0; c < 3; ++c) blockSum[c] += q[c] * a;
                    blockAlpha += a;
                }
            }
            if (blockAlpha < 0.5 * S * S) continue;
            for (int c = 0; c < 3; ++c) {
                sumGame[c] += game[i * 4 + c] + 10.0f;
                sumBase[c] += b[c] + 10.0f;
                sumHd[c] += blockSum[c] / blockAlpha + 10.0;
            }
            ++paint;
        }
        if (paint < 20) continue;
        for (int c = 0; c < 3; ++c) {
            const double g = (std::max)(0.15, (std::min)(6.0, sumGame[c] / sumBase[c]));
            gain[c] = static_cast<float>(std::exp2(std::floor(std::log2(g) * 8.0 + 0.5) / 8.0));
            // The redraw's paint need not be the sprite's, even in the default
            // colours, and a door is the sprite's art: it is taken to the redraw's
            // paint first, then repainted like the rest of the car.
            const double look = (std::max)(0.2, (std::min)(5.0, sumHd[c] / sumBase[c]));
            tint[c] = static_cast<float>(gain[c] * look);
        }
        return true;
    }
    return false;
}

uint64_t GainKey(const float gain[3]) {
    uint64_t key = 0;
    for (int c = 0; c < 3; ++c) {
        key = key * 257 + static_cast<uint64_t>(std::lround(std::log2(gain[c]) * 8.0) + 128);
    }
    return key;
}

bool RecolourHd(const HdCar& hd, const std::vector<uint8_t>& game, int w, int h,
                const float paintGain[3], std::vector<uint8_t>* out) {
    if (w <= 0 || h <= 0 || hd.width % w != 0 || hd.height % h != 0) return false;
    const int S = hd.width / w;
    if (S < 1 || hd.height / h != S) return false;
    const int W = hd.width, H = hd.height;
    // The redraw averaged over the sprite's own pixels, weighted by its alpha.
    std::vector<float> low(static_cast<size_t>(w) * h * 4, 0.0f);   // premultiplied b, g, r, a
    for (int y = 0; y < H; ++y) {
        for (int x = 0; x < W; ++x) {
            const uint8_t* p = &hd.albedo[(static_cast<size_t>(y) * W + x) * 4];
            float* l = &low[(static_cast<size_t>(y / S) * w + x / S) * 4];
            const float a = p[3] / 255.0f;
            l[0] += p[0] * a;
            l[1] += p[1] * a;
            l[2] += p[2] * a;
            l[3] += a;
        }
    }
    // The game's sprite, premultiplied.
    std::vector<float> gp(static_cast<size_t>(w) * h * 4);
    for (size_t i = 0; i < static_cast<size_t>(w) * h; ++i) {
        const float a = game[i * 4 + 3] >= 128 ? 1.0f : 0.0f;
        gp[i * 4 + 0] = game[i * 4 + 0] * a;
        gp[i * 4 + 1] = game[i * 4 + 1] * a;
        gp[i * 4 + 2] = game[i * 4 + 2] * a;
        gp[i * 4 + 3] = a;
    }
    const bool haveBase = hd.baseWidth == w && hd.baseHeight == h &&
                          hd.basePx.size() == static_cast<size_t>(w) * h * 4;
    // Bilinear sample of a premultiplied sprite-resolution image at hi-res pixel (x, y).
    auto sample = [&](const std::vector<float>& img, int x, int y, float* rgb, float* wsum) {
        const float fx = (x + 0.5f) / S - 0.5f, fy = (y + 0.5f) / S - 0.5f;
        const int x0 = static_cast<int>(std::floor(fx)), y0 = static_cast<int>(std::floor(fy));
        const float tx = fx - x0, ty = fy - y0;
        float acc[4] = {0, 0, 0, 0};
        for (int j = 0; j < 2; ++j) {
            for (int i = 0; i < 2; ++i) {
                const int xi = (std::max)(0, (std::min)(w - 1, x0 + i));
                const int yj = (std::max)(0, (std::min)(h - 1, y0 + j));
                const float wgt = (i ? tx : 1 - tx) * (j ? ty : 1 - ty);
                const float* s = &img[(static_cast<size_t>(yj) * w + xi) * 4];
                for (int c = 0; c < 4; ++c) acc[c] += s[c] * wgt;
            }
        }
        *wsum = acc[3];
        for (int c = 0; c < 3; ++c) rgb[c] = acc[3] > 1e-4f ? acc[c] / acc[3] : 0.0f;
    };
    out->assign(static_cast<size_t>(W) * H * 4, 0);
    for (int y = 0; y < H; ++y) {
        for (int x = 0; x < W; ++x) {
            const uint8_t* p = &hd.albedo[(static_cast<size_t>(y) * W + x) * 4];
            uint8_t* o = &(*out)[(static_cast<size_t>(y) * W + x) * 4];
            o[3] = p[3];
            float hs[3], gs[3], hw = 0.0f, gw = 0.0f;
            sample(low, x, y, hs, &hw);
            sample(gp, x, y, gs, &gw);
            if (haveBase) {
                // The redraw is already in the car's default paint, so a car in
                // that paint is left alone, and a repaint takes the paint's gain
                // - only where the redraw's own pixel is paint: saturated. Glass,
                // chrome, tyres and lamps keep their colours.
                const float mx = (std::max)(p[0], (std::max)(p[1], p[2]));
                const float mn = (std::min)(p[0], (std::min)(p[1], p[2]));
                const float sat = (mx - mn) / (mx + 1.0f);
                float t = (std::max)(0.0f, (std::min)(1.0f, (sat - 0.12f) / 0.18f));
                t = t * t * (3.0f - 2.0f * t);
                // Glass, which is made a mirror in the maps, reflects in its own
                // colour; the redraw's is nearly black, which would reflect nearly
                // nothing. So it is lifted to a tinted grey, more where it is more
                // glass.
                const float glass = GlassWeight(hd, (static_cast<size_t>(y) * W + x) * 4) *
                                    (std::min)(g_carGlassGloss, 1.0f);
                static const float kGlassBgr[3] = {110.0f, 96.0f, 84.0f};
                // And a soft diagonal sheen across it, the glint a window always
                // has in a picture of a car, so that it reads as glass in any light.
                const float diag = (static_cast<float>(x) / W + static_cast<float>(y) / H) * 0.5f;
                const float band = (std::max)(0.0f, 1.0f - std::fabs(diag - 0.46f) / 0.10f);
                const float sheen = 70.0f * band * band * glass;
                // The highlights painted into the redraw (the bright creases and glints on the
                // bodywork) are light, not paint: a per-channel gain left them as saturated as
                // the paint, a neon line along every fender. They are taken back toward the
                // redraw's own grey, as a real highlight on coloured paint is pale.
                const float hl = (mx > 150.0f ? (std::min)(1.0f, (mx - 150.0f) / 90.0f) : 0.0f) * t;
                const float lumP = 0.114f * p[0] + 0.587f * p[1] + 0.299f * p[2];
                for (int c = 0; c < 3; ++c) {
                    float v = p[c] * (1.0f + (paintGain[c] - 1.0f) * t);
                    v += (lumP - v) * hl * 0.55f;
                    if (glass > 0.0f) v += ((std::max)(v, kGlassBgr[c]) - v) * glass + sheen;
                    o[c] = static_cast<uint8_t>((std::max)(0.0f, (std::min)(255.0f, v)));
                }
                continue;
            }
            if (hw < 1e-3f || gw < 0.25f) {
                o[0] = p[0]; o[1] = p[1]; o[2] = p[2];
                continue;
            }
            // Glass is not painted: the game draws a car's windows in the car's
            // own colour, and recolouring the redraw from the sprite would turn
            // them into paint. Where the redraw's own maps say glass - smooth and
            // not metal - the redraw's dark glass is kept as it is.
            float glass = 0.0f;
            if (!hd.roughPx.empty() && !hd.metalPx.empty()) {
                const size_t at = (static_cast<size_t>(y) * W + x) * 4;
                const float rough = hd.roughPx[at] / 255.0f;
                const float metal = hd.metalPx[at] / 255.0f;
                const float a = (std::max)(0.0f, (std::min)(1.0f, (0.17f - rough) / 0.08f));
                const float b = (std::max)(0.0f, (std::min)(1.0f, (0.22f - metal) / 0.10f));
                glass = a * b;
            }
            // hs: the redraw at sprite resolution, but "low" holds sums per block, so
            // it is already an average once divided by the alpha total, as sample does.
            const float lumH = 0.114f * p[0] + 0.587f * p[1] + 0.299f * p[2];
            const float lumS = 0.114f * hs[0] + 0.587f * hs[1] + 0.299f * hs[2];
            float ratio = (lumH + 6.0f) / (lumS + 6.0f);
            ratio = (std::max)(0.4f, (std::min)(2.5f, ratio));
            for (int c = 0; c < 3; ++c) {
                const float painted = gs[c] * ratio;
                const float v = painted + (p[c] - painted) * glass;
                o[c] = static_cast<uint8_t>((std::max)(0.0f, (std::min)(255.0f, v)));
            }
        }
    }
    return true;
}

// A new car paint's material is a lot of arithmetic: the paint measured off the sprite, the
// redraw recoloured pixel by pixel at its full size, hashed, and written to a file. Done on
// the frame the car appeared it was 6 to 24 ms of a 33 ms frame, every second or so while
// driving, which is the stutter. So it runs on a thread of its own, in two steps - measure,
// then (only if there is no material for that paint yet) recolour, hash and write - and the
// frame loop only picks up the finished result and makes the material, one a frame.
struct CarJob {
    std::pair<IDirect3DTexture9*, int> key;
    int sprite = 0, w = 0, h = 0;
    HdCar* hd = nullptr;                          // loaded before the job starts, read-only to it
    std::vector<uint8_t> game;                    // the sprite's own pixels, BGRA
    const std::vector<uint8_t>* skip = nullptr;   // the door and dent footprint
    std::wstring cacheDir;
    int phase = 0;                                // 0 measuring, 1 recolouring
    float luma = 255.0f;                          // the sprite's mean brightness: low means burnt out
    volatile LONG done = 0;
    bool cancelled = false;
    // Results.
    bool measured = false;
    float gain[3] = {1.0f, 1.0f, 1.0f}, tint[3] = {1.0f, 1.0f, 1.0f};
    bool ok = false, fileOk = false;
    UINT outWidth = 0, outHeight = 0;
    uint64_t hash = 0;
    std::wstring path;
};
std::list<std::unique_ptr<CarJob>> g_carJobs;

DWORD WINAPI CarJobThread(LPVOID param) {
    CarJob* j = static_cast<CarJob*>(param);
    if (j->phase == 0) {
        j->measured = MeasurePaintGain(*j->hd, j->game, j->w, j->h, j->sprite, j->gain, j->tint, j->skip);
    } else {
        std::vector<uint8_t> pixels;
        if (RecolourHd(*j->hd, j->game, j->w, j->h, j->gain, &pixels)) {
            j->outWidth = static_cast<UINT>(j->hd->width);
            j->outHeight = static_cast<UINT>(j->hd->height);
            uint64_t hash = Fnv64(pixels.data(), pixels.size(), Fnv64(&j->outWidth, sizeof(j->outWidth)));
            hash = Fnv64(&j->sprite, sizeof(j->sprite), hash);
            j->hash = hash;
            CreateDirectoryW(j->cacheDir.c_str(), nullptr);
            wchar_t name[64];
            swprintf(name, 64, L"\\car_%016llx.dds", static_cast<unsigned long long>(hash));
            j->path = j->cacheDir + name;
            CacheWarmupNote(j->path);
            j->fileOk = GetFileAttributesW(j->path.c_str()) != INVALID_FILE_ATTRIBUTES ||
                        WriteDds(j->path, j->outWidth, j->outHeight, pixels);
            j->ok = true;
        }
    }
    InterlockedExchange(&j->done, 1);
    return 0;
}

void StartCarJob(CarJob* j) {
    InterlockedExchange(&j->done, 0);
    HANDLE thread = CreateThread(nullptr, 0, CarJobThread, j, 0, nullptr);
    if (thread) {
        SetThreadPriority(thread, THREAD_PRIORITY_BELOW_NORMAL);
        CloseHandle(thread);
    } else {
        CarJobThread(j);   // no thread to be had: do it here
    }
}

remixapi_MaterialHandle CarMaterialFor(IDirect3DTexture9* art, int sprite) {
    if (!art || !RemixApiHasInstances()) return nullptr;
    CarMaterial& slot = g_carMaterials[{art, sprite}];
    if (slot.handle || slot.failed) return slot.handle;
    // One new material a frame. The car waits as its flat sprite (see the warm-up) and
    // is tried again next frame, so cars turning up together are spread over a few frames
    // instead of landing on one.
    if (g_carMaterialsThisFrame >= 1) return nullptr;
    ++g_carMaterialsThisFrame;
    slot.failed = true;   // until proven otherwise, so a refusal is tried once

    D3DSURFACE_DESC desc;
    if (FAILED(art->GetLevelDesc(0, &desc))) return nullptr;
    if (desc.Format != D3DFMT_A8R8G8B8 && desc.Format != D3DFMT_X8R8G8B8) return nullptr;
    D3DLOCKED_RECT locked;
    if (FAILED(art->LockRect(0, &locked, nullptr, D3DLOCK_READONLY))) return nullptr;
    std::vector<uint8_t> pixels(static_cast<size_t>(desc.Width) * desc.Height * 4);
    for (UINT y = 0; y < desc.Height; ++y) {
        memcpy(&pixels[static_cast<size_t>(y) * desc.Width * 4],
               static_cast<const uint8_t*>(locked.pBits) + static_cast<size_t>(y) * locked.Pitch,
               static_cast<size_t>(desc.Width) * 4);
    }
    art->UnlockRect(0);
    if (desc.Format == D3DFMT_X8R8G8B8) {
        for (size_t i = 3; i < pixels.size(); i += 4) pixels[i] = 255;
    }

    // The hand-made version of this car, in this paint, when there is one. That is done on
    // a thread of its own; see CarJob. Only a car with no hand-made artwork is made here.
    UINT outWidth = desc.Width, outHeight = desc.Height;
    const float artLuma = MeanLuma(pixels);
    static int s_lumaLogs = 0;
    if (s_lumaLogs++ < 80) {
        Log("car sprite %d artwork brightness %.1f%s", sprite, artLuma,
            IsWreckSprite(sprite) || (g_charredLuma > 0.0f && artLuma < g_charredLuma) ? " - burnt out, matte" : "");
    }
    HdCar* hd = nullptr;
    float gain[3] = {1.0f, 1.0f, 1.0f}, tint[3] = {1.0f, 1.0f, 1.0f};
    bool measured = false;
    if (g_carHd && sprite >= 0) {
        HdCar& found = HdFor(sprite);
        const int w = static_cast<int>(desc.Width), h = static_cast<int>(desc.Height);
        const bool fits = found.ok && w > 0 && h > 0 && found.width % w == 0 &&
                          found.height % h == 0 && found.height / h == found.width / w;
        if (fits) {
            auto job = std::make_unique<CarJob>();
            job->key = {art, sprite};
            job->sprite = sprite;
            job->w = w;
            job->h = h;
            job->hd = &found;
            job->game = std::move(pixels);
            job->skip = &DeltaFootprint(sprite, w, h);
            job->cacheDir = CacheDirectory();
            job->phase = 0;
            job->luma = artLuma;
            CarJob* raw = job.get();
            g_carJobs.push_back(std::move(job));
            StartCarJob(raw);
            return nullptr;   // the slot stays "failed" (waiting) until the job is picked up
        } else if (g_carMaterialLogs++ < 8) {
            Log("car material: no hand-made artwork for car sprite %d here (%s)", sprite,
                found.ok ? "size does not fit the sprite" : "files not found");
        }
    }

    // Which cars have turned up, and whether they got the hand-made artwork:
    // the sprite number is not the name the game gives a car, so this is the
    // way to tell whether a particular one has been on the road.
    static int s_seenLogs = 0;
    if (s_seenLogs++ < 200) {
        Log("car sprite %d seen: %s", sprite, hd ? "HD artwork" : "original sprite");
    }

    uint64_t hash = Fnv64(pixels.data(), pixels.size(), Fnv64(&outWidth, sizeof(outWidth)));
    hash = Fnv64(&sprite, sizeof(sprite), hash);
    {
        const auto same = g_pixelMaterials.find(hash);
        if (same != g_pixelMaterials.end() && same->second.handle) {
            slot = same->second;
            return slot.handle;
        }
    }
    const std::wstring dir = CacheDirectory();
    CreateDirectoryW(dir.c_str(), nullptr);
    wchar_t name[64];
    swprintf(name, 64, L"\\car_%016llx.dds", static_cast<unsigned long long>(hash));
    const std::wstring path = dir + name;
    CacheWarmupNote(path);
    if (GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES) {
        if (!WriteDds(path, outWidth, outHeight, pixels)) {
            if (g_carMaterialLogs++ < 8) Log("car material: could not write the artwork file");
            return nullptr;
        }
    }

    remixapi_MaterialInfoOpaqueEXT opaque = {};
    opaque.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT;
    opaque.albedoConstant = {1.0f, 1.0f, 1.0f};
    opaque.opacityConstant = 1.0f;
    // The cut-out comes from the instance, which says what the sprite's alpha
    // test is; see the draw.
    opaque.useDrawCallAlphaState = 1;
    if (hd) {
        // The maps say where it is glass, paint and chrome, so the constants step
        // aside.
        opaque.roughnessConstant = 1.0f;
        opaque.metallicConstant = 1.0f;
        PrepareGlass(*hd);
        opaque.roughnessTexture = hd->roughUsed.c_str();
        opaque.metallicTexture = hd->metalUsed.c_str();
    } else {
        opaque.roughnessConstant = g_carRoughness;
        opaque.metallicConstant = g_carMetallic;
    }
    if (IsWreckSprite(sprite) || (g_charredLuma > 0.0f && artLuma < g_charredLuma)) {
        opaque.roughnessConstant = 0.95f;
        opaque.metallicConstant = 0.0f;
        opaque.roughnessTexture = nullptr;
        opaque.metallicTexture = nullptr;
    }

    remixapi_MaterialInfo info = {};
    info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO;
    info.pNext = &opaque;
    info.hash = hash | 1;
    info.albedoTexture = path.c_str();
    if (hd && g_carNormalMaps) info.normalTexture = PrepareNormal(*hd).c_str();
    info.emissiveColorConstant = {0.0f, 0.0f, 0.0f};
    info.filterMode = 1;   // linear
    info.wrapModeU = 2;    // clamp to edge
    info.wrapModeV = 2;

    remixapi_MaterialHandle handle = nullptr;
    const remixapi_ErrorCode result = RemixApi()->CreateMaterial(&info, &handle);
    if (g_carMaterialLogs++ < 8) {
        Log("car material: CreateMaterial -> %d (%s)", static_cast<int>(result),
            result == REMIXAPI_ERROR_CODE_SUCCESS ? "ok" : "refused");
    }
    if (result != REMIXAPI_ERROR_CODE_SUCCESS || !handle) return nullptr;
    slot.handle = handle;
    slot.failed = false;
    slot.born = g_carFrame;
    for (int c = 0; c < 3; ++c) {
        slot.gain[c] = hd ? gain[c] : 1.0f;
        slot.tint[c] = hd ? tint[c] : 1.0f;
    }
    g_pixelMaterials[hash] = slot;
    if (hd && measured) g_hdMaterials[{sprite, GainKey(gain)}] = slot;
    return handle;
}

// Picks up the car-material jobs that have finished. Called once a frame, before the cars are
// drawn. A finished measuring step either finds the paint already has a material (done) or
// starts the recolour; a finished recolour has its material made here, one a frame, because
// that is the part that has to be on this thread.
void PumpCarJobs() {
    int made = 0;
    for (auto it = g_carJobs.begin(); it != g_carJobs.end();) {
        CarJob& j = **it;
        if (!j.done) { ++it; continue; }
        if (j.cancelled) { it = g_carJobs.erase(it); continue; }
        CarMaterial& slot = g_carMaterials[j.key];
        if (j.phase == 0) {
            if (j.measured) {
                const auto same = g_hdMaterials.find({j.sprite, GainKey(j.gain)});
                if (same != g_hdMaterials.end() && same->second.handle) {
                    slot = same->second;
                    it = g_carJobs.erase(it);
                    continue;
                }
            }
            j.phase = 1;
            StartCarJob(&j);
            ++it;
            continue;
        }
        if (made >= 1) { ++it; continue; }
        ++made;
        HdCar* hd = j.hd;
        if (!j.ok || !j.fileOk) {
            if (g_carMaterialLogs++ < 8) Log("car material: hand-made artwork for car sprite %d could not be prepared", j.sprite);
            it = g_carJobs.erase(it);
            continue;
        }
        static int s_seenLogs = 0;
        if (s_seenLogs++ < 200) Log("car sprite %d seen: HD artwork", j.sprite);
        const auto same = g_pixelMaterials.find(j.hash);
        if (same != g_pixelMaterials.end() && same->second.handle) {
            slot = same->second;
            it = g_carJobs.erase(it);
            continue;
        }
        remixapi_MaterialInfoOpaqueEXT opaque = {};
        opaque.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT;
        opaque.albedoConstant = {1.0f, 1.0f, 1.0f};
        opaque.opacityConstant = 1.0f;
        opaque.useDrawCallAlphaState = 1;
        opaque.roughnessConstant = 1.0f;
        opaque.metallicConstant = 1.0f;
        PrepareGlass(*hd);
        opaque.roughnessTexture = hd->roughUsed.c_str();
        opaque.metallicTexture = hd->metalUsed.c_str();
        // Burnt out: no gloss left in it, whatever the maps of the car it was say.
        const bool charred = IsWreckSprite(j.sprite) || (g_charredLuma > 0.0f && j.luma < g_charredLuma);
        if (charred) {
            opaque.roughnessConstant = 0.95f;
            opaque.metallicConstant = 0.0f;
            opaque.roughnessTexture = nullptr;
            opaque.metallicTexture = nullptr;
        }
        remixapi_MaterialInfo info = {};
        info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO;
        info.pNext = &opaque;
        info.hash = (charred ? (j.hash ^ 0xC4A2EDull) : j.hash) | 1;
        info.albedoTexture = j.path.c_str();
        if (g_carNormalMaps) info.normalTexture = PrepareNormal(*hd).c_str();
        info.emissiveColorConstant = {0.0f, 0.0f, 0.0f};
        info.filterMode = 1;
        info.wrapModeU = 2;
        info.wrapModeV = 2;
        remixapi_MaterialHandle handle = nullptr;
        const remixapi_ErrorCode result = RemixApi()->CreateMaterial(&info, &handle);
        if (g_carMaterialLogs++ < 8) {
            Log("car material: CreateMaterial -> %d (%s)", static_cast<int>(result),
                result == REMIXAPI_ERROR_CODE_SUCCESS ? "ok" : "refused");
        }
        if (result == REMIXAPI_ERROR_CODE_SUCCESS && handle) {
            slot.handle = handle;
            slot.failed = false;
            slot.born = g_carFrame;
            for (int c = 0; c < 3; ++c) {
                slot.gain[c] = j.gain[c];
                slot.tint[c] = j.tint[c];
            }
            g_pixelMaterials[j.hash] = slot;
            if (j.measured) g_hdMaterials[{j.sprite, GainKey(j.gain)}] = slot;
        }
        it = g_carJobs.erase(it);
    }
}

// How a car is painted, for the doors and dents laid over it: what takes the game's
// default colours to this car's (tint) and what takes the redraw's to it (gain).
struct PaintLook {
    float tint[3] = {1.0f, 1.0f, 1.0f};
    float gain[3] = {1.0f, 1.0f, 1.0f};
};
bool CarPaintLook(IDirect3DTexture9* art, int sprite, PaintLook* look) {
    const auto found = g_carMaterials.find({art, sprite});
    if (found == g_carMaterials.end() || !found->second.handle) return false;
    for (int c = 0; c < 3; ++c) {
        look->tint[c] = found->second.tint[c];
        look->gain[c] = found->second.gain[c];
    }
    return true;
}

bool CarMaterialWarm(IDirect3DTexture9* art, int sprite) {
    const auto found = g_carMaterials.find({art, sprite});
    return found != g_carMaterials.end() && found->second.handle &&
           g_carFrame - found->second.born >= kCarMaterialWarmup;
}

// The frame each cached mesh was last asked for. A mesh is keyed by its vertices and its
// material, and a new car, a new paint, a door or a dent is a new key, so over a long
// session the cache only grows. It used to stop at 4096 entries and from then on hand back
// nothing: every car met after that - a painted van, any car that spawned - was drawn as
// its flat low-resolution sprite, for the rest of the level. Now, when it is full, the
// meshes nothing has asked for in a while are let go of and the cache carries on.
std::map<uint64_t, uint32_t> g_carMeshUsed;
constexpr size_t kCarMeshLimit = 4096;

void TrimCarMeshes() {
    static uint32_t lastTrim = 0;
    if (g_carFrame - lastTrim < 30 && lastTrim != 0) return;   // not every frame it is full
    lastTrim = g_carFrame;
    const remixapi_Interface* api = RemixApi();
    size_t dropped = 0;
    // Quiet for ten seconds or so first, then for two if that was not enough.
    for (const uint32_t quiet : {600u, 60u}) {
        if (g_carMeshes.size() <= kCarMeshLimit * 3 / 4) break;
        for (auto it = g_carMeshes.begin(); it != g_carMeshes.end();) {
            const auto used = g_carMeshUsed.find(it->first);
            const uint32_t last = used != g_carMeshUsed.end() ? used->second : 0;
            if (g_carFrame - last > quiet) {
                if (it->second && api && api->DestroyMesh) api->DestroyMesh(it->second);
                g_carMeshUsed.erase(it->first);
                it = g_carMeshes.erase(it);
                ++dropped;
            } else {
                ++it;
            }
        }
    }
    if (dropped) {
        Log("car meshes: cache was full, let go of %zu not used lately (%zu kept)", dropped,
            g_carMeshes.size());
    }
}

remixapi_MeshHandle CarMeshFor(const void* vertices, int vertexCount, size_t stride,
                               const std::vector<uint16_t>& indices,
                               remixapi_MaterialHandle material) {
    // The shape depends on the car's size and nothing else, so it is built once.
    uint64_t key = Fnv64(vertices, vertexCount * stride);
    key = Fnv64(&material, sizeof(material), key) | 1;
    auto found = g_carMeshes.find(key);
    if (found != g_carMeshes.end()) {
        g_carMeshUsed[key] = g_carFrame;
        return found->second;
    }
    if (g_carMeshes.size() > kCarMeshLimit) {
        TrimCarMeshes();
        if (g_carMeshes.size() > kCarMeshLimit) return nullptr;
    }
    g_carMeshes[key] = nullptr;   // a refusal is not retried every frame
    g_carMeshUsed[key] = g_carFrame;

    std::vector<remixapi_HardcodedVertex> verts(vertexCount);
    for (int i = 0; i < vertexCount; ++i) {
        const float* v = reinterpret_cast<const float*>(static_cast<const uint8_t*>(vertices) + i * stride);
        remixapi_HardcodedVertex out = {};
        out.position[0] = v[0];
        out.position[1] = v[1];
        out.position[2] = v[2];
        out.normal[0] = v[3];
        out.normal[1] = v[4];
        out.normal[2] = v[5];
        out.texcoord[0] = v[6];
        out.texcoord[1] = v[7];
        out.color = 0xFFFFFFFFu;
        verts[i] = out;
    }
    std::vector<uint32_t> index32(indices.begin(), indices.end());

    remixapi_MeshInfoSurfaceTriangles surface = {};
    surface.vertices_values = verts.data();
    surface.vertices_count = verts.size();
    surface.indices_values = index32.data();
    surface.indices_count = index32.size();
    surface.skinning_hasvalue = 0;
    surface.material = material;
    remixapi_MeshInfo mesh = {};
    mesh.sType = REMIXAPI_STRUCT_TYPE_MESH_INFO;
    mesh.hash = key;
    mesh.surfaces_values = &surface;
    mesh.surfaces_count = 1;

    remixapi_MeshHandle handle = nullptr;
    const remixapi_ErrorCode result = RemixApi()->CreateMesh(&mesh, &handle);
    if (g_carMaterialLogs++ < 8) {
        Log("car material: CreateMesh -> %d (%s)", static_cast<int>(result),
            result == REMIXAPI_ERROR_CODE_SUCCESS ? "ok" : "refused");
    }
    if (result != REMIXAPI_ERROR_CODE_SUCCESS || !handle) return nullptr;
    g_carMeshes[key] = handle;
    return handle;
}


// ---- Glowing car lamps ---------------------------------------------------------
//
// A lamp drawn through D3D9 is a plain quad with the world's one legacy material:
// the lamp's few pixels of tan or amber, lit like paint. Nothing in the mod gives
// those textures an emissive, so a headlight was a dim square on the body. Through
// the Remix API the lamp gets a material of its own whose emissive map is the
// lamp's own colours at full brightness, and a path tracer shows that as a source
// of light - with bloom around it - not a smudge.
struct LampMaterial {
    remixapi_MaterialHandle handle = nullptr;
    bool failed = false;
    uint32_t born = 0;
};
std::map<std::pair<const LampArt*, bool>, LampMaterial> g_lampMaterials;

remixapi_MaterialHandle LampMaterialFor(const LampArt& art, bool mirrored) {
    LampMaterial& slot = g_lampMaterials[{&art, mirrored}];
    if (slot.handle || slot.failed) return slot.handle;
    slot.failed = true;   // until proven otherwise, so a refusal is tried once
    const std::vector<uint32_t> texels = LampTexels(art, mirrored);
    if (texels.size() != static_cast<size_t>(art.width) * art.height) return nullptr;

    std::vector<uint8_t> albedo(texels.size() * 4), glow(texels.size() * 4);
    // The lamp's brightest pixel, so that only the core of the lamp glows: the
    // crop around it holds the lamp's dimmer rim and the paint beside it, and with
    // every pixel brought to full brightness the glow was a good deal bigger than
    // the lamp.
    float peak = 1.0f;
    for (const uint32_t t : texels) {
        if ((t >> 24) == 0) continue;
        peak = (std::max)(peak, static_cast<float>((std::max)(static_cast<uint8_t>(t >> 16),
                                (std::max)(static_cast<uint8_t>(t >> 8), static_cast<uint8_t>(t)))));
    }
    for (size_t i = 0; i < texels.size(); ++i) {
        const uint32_t t = texels[i];
        const uint8_t a = static_cast<uint8_t>(t >> 24);
        const uint8_t r = static_cast<uint8_t>(t >> 16), g = static_cast<uint8_t>(t >> 8),
                      b = static_cast<uint8_t>(t);
        albedo[i * 4 + 0] = b; albedo[i * 4 + 1] = g; albedo[i * 4 + 2] = r; albedo[i * 4 + 3] = a;
        // The emitted colour: the lamp's own, pulled a little toward white where it
        // is not strongly coloured - a lit bulb is the whitest thing about its
        // colour. Red and blue lamps keep theirs. Weighted by how close the pixel
        // is to the lamp's brightest.
        const float mx = static_cast<float>((std::max)(r, (std::max)(g, b)));
        float out[3] = {0, 0, 0};
        if (a > 0 && mx > 1.0f) {
            const float mn = static_cast<float>((std::min)(r, (std::min)(g, b)));
            const float white = 0.45f * (1.0f - (mx - mn) / mx);
            float core = (mx / peak - 0.60f) / 0.30f;
            core = (std::max)(0.0f, (std::min)(1.0f, core));
            core = core * core * (3.0f - 2.0f * core);
            const float in[3] = {static_cast<float>(r), static_cast<float>(g), static_cast<float>(b)};
            for (int c = 0; c < 3; ++c) {
                const float full = in[c] / mx * 255.0f;
                out[c] = (full + (255.0f - full) * white) * core;
            }
        }
        glow[i * 4 + 0] = static_cast<uint8_t>(out[2] + 0.5f);
        glow[i * 4 + 1] = static_cast<uint8_t>(out[1] + 0.5f);
        glow[i * 4 + 2] = static_cast<uint8_t>(out[0] + 0.5f);
        glow[i * 4 + 3] = a;
    }
    uint64_t hash = Fnv64(albedo.data(), albedo.size());
    hash = Fnv64(&art.width, sizeof(art.width), hash);
    const std::wstring dir = CacheDirectory();
    CreateDirectoryW(dir.c_str(), nullptr);
    wchar_t name[96];
    swprintf(name, 96, L"\\lamp_%016llx.dds", static_cast<unsigned long long>(hash));
    const std::wstring albedoPath = dir + name;
    swprintf(name, 96, L"\\lamp_%016llx_glow.dds", static_cast<unsigned long long>(hash));
    const std::wstring glowPath = dir + name;
    CacheWarmupNote(albedoPath);
    CacheWarmupNote(glowPath);
    if (GetFileAttributesW(albedoPath.c_str()) == INVALID_FILE_ATTRIBUTES &&
        !WriteDds(albedoPath, art.width, art.height, albedo)) return nullptr;
    if (GetFileAttributesW(glowPath.c_str()) == INVALID_FILE_ATTRIBUTES &&
        !WriteDds(glowPath, art.width, art.height, glow)) return nullptr;

    remixapi_MaterialInfoOpaqueEXT opaque = {};
    opaque.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT;
    opaque.albedoConstant = {1.0f, 1.0f, 1.0f};
    opaque.opacityConstant = 1.0f;
    opaque.useDrawCallAlphaState = 1;
    opaque.roughnessConstant = 0.3f;
    opaque.metallicConstant = 0.0f;
    remixapi_MaterialInfo info = {};
    info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO;
    info.pNext = &opaque;
    info.hash = (hash ^ 0x1A3F00D5u) | 1;
    info.albedoTexture = albedoPath.c_str();
    info.emissiveTexture = glowPath.c_str();
    info.emissiveIntensity = g_lampGlow;
    info.emissiveColorConstant = {1.0f, 1.0f, 1.0f};
    info.filterMode = 0;   // nearest: a lamp is a few pixels, and stays crisp
    info.wrapModeU = 2;
    info.wrapModeV = 2;
    remixapi_MaterialHandle handle = nullptr;
    const remixapi_ErrorCode result = RemixApi()->CreateMaterial(&info, &handle);
    if (g_carMaterialLogs++ < 8) {
        Log("lamp material: CreateMaterial -> %d (%s)", static_cast<int>(result),
            result == REMIXAPI_ERROR_CODE_SUCCESS ? "ok" : "refused");
    }
    if (result != REMIXAPI_ERROR_CODE_SUCCESS || !handle) return nullptr;
    slot.handle = handle;
    slot.failed = false;
    slot.born = g_carFrame;
    return handle;
}

bool LampMaterialWarm(const LampArt& art, bool mirrored) {
    const auto found = g_lampMaterials.find({&art, mirrored});
    return found != g_lampMaterials.end() && found->second.handle &&
           g_carFrame - found->second.born >= kCarMaterialWarmup;
}

// ---- Blood on the ground ---------------------------------------------------------------
//
// A pool, a pair of drops or a trail strip is a small red cutout drawn through D3D9 with the
// world's one legacy material, which is fully rough: blood read as a matte red stain. Through
// the Remix API each distinct piece of blood artwork gets a material of its own - the game's
// red pulled darker, and nearly smooth, so a puddle reflects the street the way a wet one does.
struct BloodMaterial {
    remixapi_MaterialHandle handle = nullptr;
    bool failed = false;
    bool blood = false;   // the artwork is red; grey rubber and anything else is left alone
    uint32_t born = 0;
};
std::unordered_map<uint64_t, BloodMaterial> g_bloodMaterials;

// The material for this decal artwork, or null when it is not blood (or could not be made).
// *warm says whether it has had the frames Remix needs to load it.
remixapi_MaterialHandle BloodMaterialFor(IDirect3DTexture9* texture, bool* warm) {
    *warm = false;
    if (!texture || !RemixApiHasInstances()) return nullptr;
    D3DSURFACE_DESC desc;
    if (FAILED(texture->GetLevelDesc(0, &desc)) || desc.Format != D3DFMT_A8R8G8B8 ||
        desc.Width < 1 || desc.Height < 1 || desc.Width > 256 || desc.Height > 256) {
        return nullptr;
    }
    const int w = static_cast<int>(desc.Width), h = static_cast<int>(desc.Height);
    std::vector<uint8_t> px(static_cast<size_t>(w) * h * 4);
    D3DLOCKED_RECT locked;
    if (FAILED(texture->LockRect(0, &locked, nullptr, D3DLOCK_READONLY))) return nullptr;
    for (int y = 0; y < h; ++y) {
        memcpy(&px[static_cast<size_t>(y) * w * 4],
               static_cast<const uint8_t*>(locked.pBits) + static_cast<size_t>(y) * locked.Pitch,
               static_cast<size_t>(w) * 4);
    }
    texture->UnlockRect(0);

    uint64_t hash = Fnv64(px.data(), px.size());
    hash = Fnv64(&w, sizeof(w), hash);
    hash = Fnv64(&h, sizeof(h), hash);
    hash = Fnv64(&g_bloodAlbedo, sizeof(g_bloodAlbedo), hash);
    hash = Fnv64(&g_bloodRough, sizeof(g_bloodRough), hash);

    BloodMaterial& slot = g_bloodMaterials[hash];
    if (slot.handle || slot.failed) {
        if (slot.handle && g_carFrame - slot.born >= kCarMaterialWarmup) *warm = true;
        return slot.blood ? slot.handle : nullptr;
    }
    slot.failed = true;   // until proven otherwise, so a refusal is tried once

    // Red, as the game draws blood: the mean of the opaque pixels leans well toward red.
    double sr = 0, sg = 0, sb = 0;
    int opaque = 0;
    for (size_t i = 0; i + 3 < px.size(); i += 4) {
        if (px[i + 3] < 128) continue;
        sb += px[i]; sg += px[i + 1]; sr += px[i + 2];
        ++opaque;
    }
    if (opaque == 0) return nullptr;
    sr /= opaque; sg /= opaque; sb /= opaque;
    if (!(sr > sg + 40.0 && sr > sb + 40.0)) return nullptr;   // not blood: stays failed, so not retried
    slot.blood = true;

    std::vector<uint8_t> albedo(px.size());
    for (size_t i = 0; i + 3 < px.size(); i += 4) {
        albedo[i + 0] = static_cast<uint8_t>(px[i + 0] * g_bloodAlbedo + 0.5f);
        albedo[i + 1] = static_cast<uint8_t>(px[i + 1] * g_bloodAlbedo + 0.5f);
        albedo[i + 2] = static_cast<uint8_t>(px[i + 2] * g_bloodAlbedo + 0.5f);
        albedo[i + 3] = px[i + 3];
    }
    const std::wstring dir = CacheDirectory();
    CreateDirectoryW(dir.c_str(), nullptr);
    wchar_t name[96];
    swprintf(name, 96, L"\\blood_%016llx.dds", static_cast<unsigned long long>(hash));
    const std::wstring albedoPath = dir + name;
    CacheWarmupNote(albedoPath);
    if (GetFileAttributesW(albedoPath.c_str()) == INVALID_FILE_ATTRIBUTES &&
        !WriteDds(albedoPath, w, h, albedo)) return nullptr;

    remixapi_MaterialInfoOpaqueEXT opaqueInfo = {};
    opaqueInfo.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT;
    opaqueInfo.albedoConstant = {1.0f, 1.0f, 1.0f};
    opaqueInfo.opacityConstant = 1.0f;
    opaqueInfo.useDrawCallAlphaState = 1;
    opaqueInfo.roughnessConstant = g_bloodRough;
    opaqueInfo.metallicConstant = 0.0f;
    remixapi_MaterialInfo info = {};
    info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO;
    info.pNext = &opaqueInfo;
    info.hash = (hash ^ 0xB10D0001u) | 1;
    info.albedoTexture = albedoPath.c_str();
    info.filterMode = 0;   // nearest, like the game's own sprites
    info.wrapModeU = 2;
    info.wrapModeV = 2;
    remixapi_MaterialHandle handle = nullptr;
    const remixapi_ErrorCode result = RemixApi()->CreateMaterial(&info, &handle);
    static int bloodLogs = 0;
    if (bloodLogs++ < 8) {
        Log("blood material: %dx%d, CreateMaterial -> %d (%s)", w, h, static_cast<int>(result),
            result == REMIXAPI_ERROR_CODE_SUCCESS ? "ok" : "refused");
    }
    if (result != REMIXAPI_ERROR_CODE_SUCCESS || !handle) return nullptr;
    slot.handle = handle;
    slot.failed = false;
    slot.born = g_carFrame;
    return handle;
}


// ---- Doors and dents on a hand-made car ------------------------------------------
//
// The game paints a car's open doors and dents into its own sprite, which a car with
// hand-made artwork does not draw: the redraw is of the closed, undamaged car. So the
// delta's pixels are laid over the dome - the same low-resolution art the game would
// have drawn, enlarged smoothly and given the car's paint.
struct DoorMaterial {
    remixapi_MaterialHandle handle = nullptr;
    bool failed = false;
    uint32_t born = 0;
};
std::map<std::pair<const LampArt*, uint64_t>, DoorMaterial> g_doorMaterials;
constexpr int kDoorScale = 4;

float g_carDamage = 1.4f;   // how strongly dents show; 0 draws none

// A dent as shading, not as the game's own pixels. The game's damage is a patch of
// crumpled sprite pixels, a quarter of the car for a corner, and laid over the redraw
// it hid the redraw's paint under a smear of the old low-resolution car. So only the
// change the dent makes is kept: where it is darker or lighter than the car's default
// paint at that pixel, by how much, and that is laid over the redraw's own colour,
// repainted. Where the dent changes nothing, nothing is drawn, and nothing outside
// the body is: the crumpled edge standing out of it only frays the outline.
bool DamageTexels(const LampArt& art, int sprite, const PaintLook& look, HdCar& hd,
                  std::vector<uint32_t>* out) {
    const int w = hd.baseWidth, h = hd.baseHeight;
    if (!hd.ok || w != art.spriteWidth || h != art.spriteHeight ||
        hd.basePx.size() != static_cast<size_t>(w) * h * 4 || w <= 0 || hd.width % w != 0) return false;
    const int S = hd.width / w;
    if (hd.height / h != S) return false;
    out->assign(art.argb.size(), 0);
    double fill[3] = {0, 0, 0};
    int kept = 0;
    auto paintWeight = [](float r, float g, float b) {
        const float mx = (std::max)(r, (std::max)(g, b)), mn = (std::min)(r, (std::min)(g, b));
        float t = (std::max)(0.0f, (std::min)(1.0f, ((mx - mn) / (mx + 1.0f) - 0.12f) / 0.18f));
        return t * t * (3.0f - 2.0f * t);
    };
    for (int y = 0; y < art.height; ++y) {
        for (int x = 0; x < art.width; ++x) {
            const uint32_t c = art.argb[static_cast<size_t>(y) * art.width + x];
            if (!(c >> 24)) continue;
            const int px = art.x0 + x, py = art.y0 + y;
            if (px < 0 || px >= w || py < 0 || py >= h) continue;
            const float dr = static_cast<float>((c >> 16) & 0xFF), dg = static_cast<float>((c >> 8) & 0xFF),
                        db = static_cast<float>(c & 0xFF);
            float rgb[3];
            const uint8_t* b = &hd.basePx[(static_cast<size_t>(py) * w + px) * 4];
            double block[3] = {0, 0, 0}, alpha = 0;
            if (b[3] >= 128) {
                for (int j = 0; j < S; ++j) {
                    for (int i = 0; i < S; ++i) {
                        const uint8_t* q = &hd.albedo[(static_cast<size_t>(py * S + j) * hd.width + px * S + i) * 4];
                        const double a = q[3] / 255.0;
                        for (int k = 0; k < 3; ++k) block[k] += q[k] * a;
                        alpha += a;
                    }
                }
            }
            if (alpha >= 0.5 * S * S) {
                const float lumD = 0.299f * dr + 0.587f * dg + 0.114f * db;
                const float lumB = 0.299f * b[2] + 0.587f * b[1] + 0.114f * b[0];
                float lr = std::log((lumD + 8.0f) / (lumB + 8.0f));
                if (std::fabs(lr) < 0.15f) continue;   // the dent leaves this pixel as it was
                const float ratio = (std::max)(0.3f, (std::min)(1.7f, std::exp(lr * g_carDamage)));
                const float hb = static_cast<float>(block[0] / alpha), hg = static_cast<float>(block[1] / alpha),
                            hr = static_cast<float>(block[2] / alpha);
                const float t = paintWeight(hr, hg, hb);
                const float base[3] = {hr, hg, hb};
                for (int k = 0; k < 3; ++k) {
                    // look.gain is B, G, R like the redraw's own bytes; rgb is R, G, B.
                    rgb[k] = base[k] * (1.0f + (look.gain[2 - k] - 1.0f) * t) * ratio;
                }
            } else {
                continue;   // the crumpled edge outside the body is not drawn: it only frays the outline
            }
            uint32_t packed = 0xFF000000u;
            for (int k = 0; k < 3; ++k) {
                const uint32_t v = static_cast<uint32_t>((std::max)(0.0f, (std::min)(255.0f, rgb[k])));
                packed |= v << (16 - 8 * k);
                fill[k] += v;
            }
            (*out)[static_cast<size_t>(y) * art.width + x] = packed;
            ++kept;
        }
    }
    if (kept < 4) return false;
    const uint32_t fillColour = (static_cast<uint32_t>(fill[0] / kept) << 16) |
                                (static_cast<uint32_t>(fill[1] / kept) << 8) |
                                static_cast<uint32_t>(fill[2] / kept);
    for (uint32_t& t : *out) {
        if (!(t >> 24)) t = fillColour;
    }
    return true;
}

// A dent drawn at the redraw's own resolution. The game's damage is only a change of
// light and dark at the sprite's pixels, so that change - smoothed, and capped so a
// scratch line does not become a black dash - is laid over the redraw's pixel itself,
// repainted exactly as the dome under it is (RecolourHd). Where the dent changes
// little the patch is the dome again, so its edge cannot be seen, and the redraw's
// panel lines, chrome and glass run through it instead of a blurred average of them.
// A box blur by running sums, edges clamped, of a w x h plane of floats: along the row,
// then down the column.
void BoxBlurPlane(std::vector<float>* plane, int w, int h, int radius) {
    if (radius < 1 || w < 2 || h < 2) return;
    std::vector<float> tmp(plane->size());
    const float norm = 1.0f / (2 * radius + 1);
    for (int y = 0; y < h; ++y) {
        const float* in = &(*plane)[static_cast<size_t>(y) * w];
        float* out = &tmp[static_cast<size_t>(y) * w];
        float acc = 0.0f;
        for (int x = -radius; x <= radius; ++x) acc += in[(std::min)((std::max)(x, 0), w - 1)];
        for (int x = 0; x < w; ++x) {
            out[x] = acc * norm;
            acc += in[(std::min)(x + radius + 1, w - 1)] - in[(std::max)(x - radius, 0)];
        }
    }
    for (int x = 0; x < w; ++x) {
        float acc = 0.0f;
        for (int y = -radius; y <= radius; ++y) {
            acc += tmp[static_cast<size_t>((std::min)((std::max)(y, 0), h - 1)) * w + x];
        }
        for (int y = 0; y < h; ++y) {
            (*plane)[static_cast<size_t>(y) * w + x] = acc * norm;
            acc += tmp[static_cast<size_t>((std::min)(y + radius + 1, h - 1)) * w + x] -
                   tmp[static_cast<size_t>((std::max)(y - radius, 0)) * w + x];
        }
    }
}

// Smooth value noise, -1..1, on a lattice of the given cell size (in the redraw's own pixels).
// The game's damage is only a few sprite pixels of shading, so on its own it can only make soft,
// blurry blotches; this is what puts crinkles and scuffs of the redraw's own fineness into them.
float DamageNoiseAt(int x, int y, uint32_t seed) {
    uint32_t h = static_cast<uint32_t>(x) * 374761393u + static_cast<uint32_t>(y) * 668265263u + seed * 2246822519u;
    h = (h ^ (h >> 13)) * 1274126177u;
    h ^= h >> 16;
    return static_cast<float>(h & 0xFFFFu) / 32767.5f - 1.0f;
}
float DamageNoise(float x, float y, float cell, uint32_t seed) {
    x /= cell;
    y /= cell;
    const int x0 = static_cast<int>(std::floor(x)), y0 = static_cast<int>(std::floor(y));
    const float tx = x - x0, ty = y - y0;
    const float sx = tx * tx * (3.0f - 2.0f * tx), sy = ty * ty * (3.0f - 2.0f * ty);
    const float a = DamageNoiseAt(x0, y0, seed), b = DamageNoiseAt(x0 + 1, y0, seed);
    const float c = DamageNoiseAt(x0, y0 + 1, seed), d = DamageNoiseAt(x0 + 1, y0 + 1, seed);
    const float top = a + (b - a) * sx, bottom = c + (d - c) * sx;
    return top + (bottom - top) * sy;
}

bool DentOverlayHd(const LampArt& art, int sprite, const PaintLook& look, HdCar& hd,
                   std::vector<uint8_t>* bgra, int* outW, int* outH,
                   std::vector<uint8_t>* roughOut, std::vector<uint8_t>* metalOut,
                   std::vector<uint8_t>* normalOut) {
    const int w = hd.baseWidth, h = hd.baseHeight;
    if (!hd.ok || w != art.spriteWidth || h != art.spriteHeight ||
        hd.basePx.size() != static_cast<size_t>(w) * h * 4 || w <= 0 || hd.width % w != 0) return false;
    const int S = hd.width / w;
    if (hd.height / h != S || S < 1 || art.width <= 0 || art.height <= 0) return false;
    if (static_cast<long long>(art.width) * S > 4096 || static_cast<long long>(art.height) * S > 4096) return false;

    // The change in light at each of the dent's texels, in the sprite's own pixels.
    const int aw = art.width, ah = art.height;
    std::vector<float> lr(static_cast<size_t>(aw) * ah, 0.0f);
    int changed = 0;
    for (int y = 0; y < ah; ++y) {
        for (int x = 0; x < aw; ++x) {
            const uint32_t c = art.argb[static_cast<size_t>(y) * aw + x];
            if (!(c >> 24)) continue;
            const int px = art.x0 + x, py = art.y0 + y;
            if (px < 0 || px >= w || py < 0 || py >= h) continue;
            const uint8_t* b = &hd.basePx[(static_cast<size_t>(py) * w + px) * 4];
            if (b[3] < 128) continue;   // outside the body: the crumpled edge is not drawn
            const float lumD = 0.299f * ((c >> 16) & 0xFF) + 0.587f * ((c >> 8) & 0xFF) + 0.114f * (c & 0xFF);
            const float lumB = 0.299f * b[2] + 0.587f * b[1] + 0.114f * b[0];
            const float v = std::log((lumD + 8.0f) / (lumB + 8.0f));
            if (std::fabs(v) < 0.15f) continue;   // the dent leaves this pixel as it was
            lr[static_cast<size_t>(y) * aw + x] = v;
            ++changed;
        }
    }
    if (changed < 4) return false;
    // Smoothed, so a one-pixel crack is a faint line and a broad crumple stays itself.
    std::vector<float> sm(lr.size(), 0.0f);
    for (int y = 0; y < ah; ++y) {
        for (int x = 0; x < aw; ++x) {
            float acc = 0.0f;
            for (int j = -1; j <= 1; ++j) {
                for (int i = -1; i <= 1; ++i) {
                    const int xi = x + i, yj = y + j;
                    if (xi < 0 || xi >= aw || yj < 0 || yj >= ah) continue;
                    acc += lr[static_cast<size_t>(yj) * aw + xi] * ((i == 0 && j == 0) ? 2.0f : 1.0f);
                }
            }
            sm[static_cast<size_t>(y) * aw + x] = acc / 10.0f;
        }
    }

    const int W = aw * S, H = ah * S;
    const size_t count = static_cast<size_t>(W) * H;

    // The dent's change in light at every texel of the redraw: the smoothed field,
    // bilinear between the sprite's texels.
    std::vector<float> chg(count, 0.0f);
    for (int y = 0; y < H; ++y) {
        for (int x = 0; x < W; ++x) {
            const float fx = (x + 0.5f) / S - 0.5f, fy = (y + 0.5f) / S - 0.5f;
            const int x0 = static_cast<int>(std::floor(fx)), y0 = static_cast<int>(std::floor(fy));
            const float tx = fx - x0, ty = fy - y0;
            float change = 0.0f;
            for (int j = 0; j < 2; ++j) {
                for (int i = 0; i < 2; ++i) {
                    const int xi = (std::max)(0, (std::min)(aw - 1, x0 + i));
                    const int yj = (std::max)(0, (std::min)(ah - 1, y0 + j));
                    change += sm[static_cast<size_t>(yj) * aw + xi] * (i ? tx : 1 - tx) * (j ? ty : 1 - ty);
                }
            }
            // The patch is the delta's rectangle, and the game's damage runs right up to its edge:
            // laid over the redraw that edge was a visible block. Faded out over the last couple
            // of sprite pixels, the patch melts into the car instead.
            const float edge = static_cast<float>((std::min)((std::min)(x, W - 1 - x), (std::min)(y, H - 1 - y)));
            const float feather = Smoothstep(0.0f, 4.0f * S, edge);
            chg[static_cast<size_t>(y) * W + x] = change * feather;
        }
    }
    // The change in light that tints the colour is the sprite's own few pixels, and drawn as it
    // is it shows as soft blocks the size of a sprite pixel - the low resolution of the old car
    // back inside the redraw. For the colour it is smoothed over about two sprite pixels, so it is
    // a gradient and not a block; the slope for the normal (below) keeps the sharper field, and the
    // fine crumple is what gives the patch its detail.
    std::vector<float> tintChg = chg;
    BoxBlurPlane(&tintChg, W, H, S);
    BoxBlurPlane(&tintChg, W, H, S);

    // What a dent is to the light is its shape, not a dark patch. The game's damage art
    // is crumple: lighter where the metal is pushed up, darker where it is pushed in. Read
    // as a height - blurred over about a sprite pixel, so a one-pixel crack is a groove and
    // not a spike - its slope is the normal, and the lamps and the sun find the creases
    // themselves.
    std::vector<float> height = chg;
    const int blurRadius = (std::max)(1, S / 2);
    BoxBlurPlane(&height, W, H, blurRadius);
    BoxBlurPlane(&height, W, H, blurRadius);
    // How much damaged this is, 0..1: where the paint is scuffed and the metal rough.
    std::vector<float> damage(count);
    for (size_t i = 0; i < count; ++i) damage[i] = std::fabs(chg[i]);
    BoxBlurPlane(&damage, W, H, blurRadius);
    for (size_t i = 0; i < count; ++i) damage[i] = (std::min)(1.0f, damage[i] / 0.30f);
    // Where the patch is drawn: the damage and a little beyond it. Outside the damage it is
    // the dome again - its colour, its maps, its normals - so the edge cannot be seen.
    std::vector<float> reach = damage;
    BoxBlurPlane(&reach, W, H, 2 * S);

    // Fine crumple in the damaged area: creases and dimples at the redraw's own fineness, on top
    // of the game's soft shape, so a dented panel is crinkled metal and not a blurred smear.
    // Two sizes of it, both in the redraw's pixels, so it looks the same whatever the scale.
    const uint32_t noiseSeed = static_cast<uint32_t>(sprite) * 7919u + static_cast<uint32_t>(art.x0) * 31u +
                               static_cast<uint32_t>(art.y0);
    const float coarse = (std::max)(2.0f, 0.8f * S), fine = (std::max)(1.5f, 0.35f * S);
    std::vector<float> grain(count, 0.0f);   // -1..1, only where there is damage
    for (int y = 0; y < H; ++y) {
        for (int x = 0; x < W; ++x) {
            const size_t i = static_cast<size_t>(y) * W + x;
            if (damage[i] <= 0.02f) continue;
            const float gx = static_cast<float>(art.x0 * S + x), gy = static_cast<float>(art.y0 * S + y);
            const float n = 0.65f * DamageNoise(gx, gy, coarse, noiseSeed) +
                            0.35f * DamageNoise(gx, gy, fine, noiseSeed ^ 0x9E3779B9u);
            grain[i] = n * damage[i];
            height[i] += n * damage[i] * 0.14f;
        }
    }

    // The maps the dome is drawn with, so that the patch is made of the same stuff. They were
    // made ready before this thread started (see DoorMaterialFor).
    std::vector<uint8_t> roughPx, metalPx, normalPx;
    int mw = 0, mh = 0;
    const bool haveRough = ReadDds(hd.roughUsed, &mw, &mh, &roughPx) && mw == hd.width && mh == hd.height;
    const bool haveMetal = ReadDds(hd.metalUsed, &mw, &mh, &metalPx) && mw == hd.width && mh == hd.height;
    bool haveNormal = false;
    if (g_carNormalMaps) {
        haveNormal = hd.normalPrepared && ReadDds(hd.normalUsed, &mw, &mh, &normalPx) && mw == hd.width && mh == hd.height;
    }

    bgra->assign(count * 4, 0);
    roughOut->assign(count * 4, 255);
    metalOut->assign(count * 4, 255);
    normalOut->assign(count * 4, 255);
    static const float kGlassBgr[3] = {110.0f, 96.0f, 84.0f};
    const float strength = (std::min)(g_carDamage, 1.5f);
    for (int y = 0; y < H; ++y) {
        for (int x = 0; x < W; ++x) {
            const size_t i = static_cast<size_t>(y) * W + x;
            uint8_t* o = &(*bgra)[i * 4];
            uint8_t* orr = &(*roughOut)[i * 4];
            uint8_t* om = &(*metalOut)[i * 4];
            uint8_t* on = &(*normalOut)[i * 4];
            // A flat normal and the paint's own roughness and metal, for any texel that is not
            // drawn, so a filter never blends in nothing.
            on[0] = 255; on[1] = 128; on[2] = 128;
            const int hx = art.x0 * S + x, hy = art.y0 * S + y;
            if (hx < 0 || hx >= hd.width || hy < 0 || hy >= hd.height) continue;
            const size_t at = (static_cast<size_t>(hy) * hd.width + hx) * 4;
            const uint8_t* p = &hd.albedo[at];
            const float a = damage[i];

            // The maps' own roughness and metal here, and what damage does to them: paint
            // scuffed to a rougher, more metal finish, glass cracked to a frosted one,
            // chrome and the satin of a work deck left alone.
            const float r0 = haveRough ? roughPx[at] / 255.0f : 0.17f;
            const float m0 = haveMetal ? metalPx[at] / 255.0f : 0.45f;
            const float pw = (std::max)(0.0f, (std::min)(1.0f, (r0 - 0.20f) / 0.06f)) *
                             (std::max)(0.0f, (std::min)(1.0f, (0.50f - r0) / 0.10f));
            const float gl = (std::max)(0.0f, (std::min)(1.0f, (0.20f - r0) / 0.10f)) *
                             (m0 < 0.9f ? 1.0f : 0.0f);
            const float r1 = r0 + (0.68f - r0) * a * pw + (0.45f - r0) * a * 0.8f * gl;
            const float m1 = m0 + (0.78f - m0) * a * pw * 0.9f;
            orr[0] = orr[1] = orr[2] = static_cast<uint8_t>((std::min)(1.0f, r1) * 255.0f + 0.5f);
            om[0] = om[1] = om[2] = static_cast<uint8_t>((std::min)(1.0f, m1) * 255.0f + 0.5f);

            // The dome's pixel here, painted as RecolourHd paints it.
            const float mx = (std::max)(p[0], (std::max)(p[1], p[2]));
            const float mn = (std::min)(p[0], (std::min)(p[1], p[2]));
            float t = (std::max)(0.0f, (std::min)(1.0f, ((mx - mn) / (mx + 1.0f) - 0.12f) / 0.18f));
            t = t * t * (3.0f - 2.0f * t);
            const float glass = GlassWeight(hd, at) * (std::min)(g_carGlassGloss, 1.0f);
            // Darker or lighter, but never to black: a scratch is a pale line in dark paint
            // and the dark of a crumple is shade, which the normal now makes by itself.
            // (A crashed car has to look crashed: the crumple reads darker and the scratches paler
            // than they did at the first, timid setting, which left a wrecked car looking merely
            // scuffed.)
            // The soft low-resolution field only sets the broad shade (kept gentle: it is as blurry
            // as the sprite it came from); the crinkle and scuff on top of it are fine.
            const float ratio = (std::max)(0.64f, (std::min)(1.18f, std::exp(tintChg[i] * g_carDamage * 0.9f) *
                                                                    (1.0f + 0.42f * grain[i])));
            float v[3];
            const float hl = (mx > 150.0f ? (std::min)(1.0f, (mx - 150.0f) / 90.0f) : 0.0f) * t;
            const float lumP = 0.114f * p[0] + 0.587f * p[1] + 0.299f * p[2];
            for (int c = 0; c < 3; ++c) {
                v[c] = p[c] * (1.0f + (look.gain[c] - 1.0f) * t);
                v[c] += (lumP - v[c]) * hl * 0.55f;   // as RecolourHd: a highlight is pale, not neon
                if (glass > 0.0f) v[c] += ((std::max)(v[c], kGlassBgr[c]) - v[c]) * glass;
                v[c] *= ratio;
            }
            // Paint flaked off goes a little grey: bare metal showing through.
            const float lum = 0.114f * v[0] + 0.587f * v[1] + 0.299f * v[2];
            const float flake = 0.50f * a * pw;
            for (int c = 0; c < 3; ++c) {
                // Scuffed paint is also dirtier and darker, not only greyer.
                const float w = (v[c] + (lum - v[c]) * flake) * (1.0f - 0.22f * a * pw);
                o[c] = static_cast<uint8_t>((std::max)(0.0f, (std::min)(255.0f, w)));
            }

            // The normal: the dome's own, tilted by the slope of the crumple.
            float nx = 0.0f, ny = 0.0f, nz = 1.0f;
            if (haveNormal) {
                nx = normalPx[at + 2] / 255.0f * 2.0f - 1.0f;
                ny = normalPx[at + 1] / 255.0f * 2.0f - 1.0f;
                nz = (std::max)(normalPx[at + 0] / 255.0f * 2.0f - 1.0f, 0.05f);
            }
            if (x > 0 && x + 1 < W && y > 0 && y + 1 < H) {
                // Slope per sprite pixel, in the maps' convention: x is minus the slope along
                // the row, y plus the slope down the column.
                const float gx = (height[i + 1] - height[i - 1]) * 0.5f * S;
                const float gy = (height[i + W] - height[i - W]) * 0.5f * S;
                float tx = -gx * 2.2f * strength, ty = gy * 2.2f * strength;
                const float len = std::sqrt(tx * tx + ty * ty);
                if (len > 1.25f) { tx *= 1.25f / len; ty *= 1.25f / len; }
                nx += tx;
                ny += ty;
            }
            const float nl = std::sqrt(nx * nx + ny * ny + nz * nz);
            on[2] = static_cast<uint8_t>((nx / nl * 0.5f + 0.5f) * 255.0f + 0.5f);
            on[1] = static_cast<uint8_t>((ny / nl * 0.5f + 0.5f) * 255.0f + 0.5f);
            on[0] = static_cast<uint8_t>((nz / nl * 0.5f + 0.5f) * 255.0f + 0.5f);

            o[3] = (p[3] >= 128 && reach[i] > 0.01f) ? 255 : 0;
        }
    }
    *outW = W;
    *outH = H;
    return true;
}

// A door's or a dent's picture is a lot of arithmetic - a dent most of all: planes of
// floats at the redraw's full size, blurred a dozen times - and it used to be made on the
// frame a car turned up, for every door and dent it has, which was the stutter whenever a
// new car appeared. It is made on a thread of its own now, one at a time, and the frame
// loop only picks up the finished file and makes the material from it (PumpDoorJobs).
struct DoorJob {
    std::pair<const LampArt*, uint64_t> key;   // what the material is filed under
    LampArt art;                               // a copy: a reload of the art cannot pull it from under the thread
    int delta = 0, sprite = 0;
    PaintLook look;
    HdCar* hd = nullptr;                       // read-only to the thread; its maps are prepared before it starts
    bool cancelled = false;
    bool started = false;
    uint32_t asked = 0;                        // the last frame a car wanted it: the newest are made first
    volatile LONG done = 0;
    bool ok = false, hdDent = false;
    uint64_t hash = 0, mapsHash = 0;
    std::wstring path, dentRoughPath, dentMetalPath, dentNormalPath;
};
std::list<std::unique_ptr<DoorJob>> g_doorJobs;
std::map<std::pair<const LampArt*, uint64_t>, DoorJob*> g_doorPending;

void DoorJobCompute(DoorJob& job) {
    const LampArt& art = job.art;
    const int delta = job.delta, sprite = job.sprite;
    const PaintLook& look = job.look;
    // A dent is shading on the redraw; a door is the game's own art, repainted.
    const bool dent = delta <= 4;
    std::vector<uint32_t> texels;
    std::vector<uint8_t> bgra;
    int W = 0, H = 0;
    std::vector<uint8_t> dentRough, dentMetal, dentNormal;
    const bool hdDent = dent && DentOverlayHd(art, sprite, look, *job.hd, &bgra, &W, &H, &dentRough, &dentMetal, &dentNormal);
    if (!hdDent) {
        if (dent) {
            if (!DamageTexels(art, sprite, look, *job.hd, &texels)) return;
        } else {
            texels = LampTexels(art, false);
        }
        if (texels.size() != static_cast<size_t>(art.width) * art.height) return;
    }
    const float* gain = look.tint;
    const int w = art.width, h = art.height;
    if (!hdDent) {
        W = w * kDoorScale;
        H = h * kDoorScale;
        bgra.assign(static_cast<size_t>(W) * H * 4, 0);
    }
    for (int y = 0; y < (hdDent ? 0 : H); ++y) {
        for (int x = 0; x < W; ++x) {
            const float fx = (x + 0.5f) / kDoorScale - 0.5f, fy = (y + 0.5f) / kDoorScale - 0.5f;
            const int x0 = static_cast<int>(std::floor(fx)), y0 = static_cast<int>(std::floor(fy));
            const float tx = fx - x0, ty = fy - y0;
            float acc[4] = {0, 0, 0, 0};
            for (int j = 0; j < 2; ++j) {
                for (int i = 0; i < 2; ++i) {
                    const int xi = (std::max)(0, (std::min)(w - 1, x0 + i));
                    const int yj = (std::max)(0, (std::min)(h - 1, y0 + j));
                    const float wgt = (i ? tx : 1 - tx) * (j ? ty : 1 - ty);
                    const uint32_t t = texels[static_cast<size_t>(yj) * w + xi];
                    acc[0] += ((t >> 16) & 0xFF) * wgt;
                    acc[1] += ((t >> 8) & 0xFF) * wgt;
                    acc[2] += (t & 0xFF) * wgt;
                    acc[3] += ((t >> 24) & 0xFF) * wgt;
                }
            }
            // The paint's gain, where this pixel is paint rather than glass or shadow.
            const float mx = (std::max)(acc[0], (std::max)(acc[1], acc[2]));
            const float mn = (std::min)(acc[0], (std::min)(acc[1], acc[2]));
            float t = (std::max)(0.0f, (std::min)(1.0f, ((mx - mn) / (mx + 1.0f) - 0.12f) / 0.18f));
            t = t * t * (3.0f - 2.0f * t);
            if (dent) t = 0.0f;   // already in the car's own colours
            uint8_t* o = &bgra[(static_cast<size_t>(y) * W + x) * 4];
            for (int c = 0; c < 3; ++c) {
                const float v = acc[2 - c] * (1.0f + (gain[2 - c] - 1.0f) * t);
                o[c] = static_cast<uint8_t>((std::max)(0.0f, (std::min)(255.0f, v)));
            }
            o[3] = static_cast<uint8_t>((std::max)(0.0f, (std::min)(255.0f, acc[3])));
        }
    }
    uint64_t hash = Fnv64(bgra.data(), bgra.size());
    hash = Fnv64(&W, sizeof(W), hash);
    const std::wstring dir = CacheDirectory();
    CreateDirectoryW(dir.c_str(), nullptr);
    wchar_t name[96];
    swprintf(name, 96, L"\\door_%016llx.dds", static_cast<unsigned long long>(hash));
    const std::wstring path = dir + name;
    CacheWarmupNote(path);
    if (GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES &&
        !WriteDds(path, W, H, bgra)) return;

    // A dent has maps of its own: the paint's roughness and metal where it is scuffed, and
    // the normals of the crumple. Named by what is in them, like the artwork.
    std::wstring dentRoughPath, dentMetalPath, dentNormalPath;
    uint64_t mapsHash = 0;
    if (hdDent) {
        mapsHash = Fnv64(dentRough.data(), dentRough.size());
        mapsHash = Fnv64(dentMetal.data(), dentMetal.size(), mapsHash);
        mapsHash = Fnv64(dentNormal.data(), dentNormal.size(), mapsHash);
        wchar_t mapName[96];
        swprintf(mapName, 96, L"\\doorr_%016llx.dds", static_cast<unsigned long long>(hash ^ mapsHash));
        dentRoughPath = dir + mapName;
        swprintf(mapName, 96, L"\\doorm_%016llx.dds", static_cast<unsigned long long>(hash ^ mapsHash));
        dentMetalPath = dir + mapName;
        swprintf(mapName, 96, L"\\doorn_%016llx.dds", static_cast<unsigned long long>(hash ^ mapsHash));
        dentNormalPath = dir + mapName;
        if ((GetFileAttributesW(dentRoughPath.c_str()) == INVALID_FILE_ATTRIBUTES &&
             !WriteDds(dentRoughPath, W, H, dentRough)) ||
            (GetFileAttributesW(dentMetalPath.c_str()) == INVALID_FILE_ATTRIBUTES &&
             !WriteDds(dentMetalPath, W, H, dentMetal)) ||
            (GetFileAttributesW(dentNormalPath.c_str()) == INVALID_FILE_ATTRIBUTES &&
             !WriteDds(dentNormalPath, W, H, dentNormal))) return;
    }

    job.hdDent = hdDent;
    job.hash = hash;
    job.mapsHash = mapsHash;
    job.path = path;
    job.dentRoughPath = dentRoughPath;
    job.dentMetalPath = dentMetalPath;
    job.dentNormalPath = dentNormalPath;
    job.ok = true;
}

DWORD WINAPI DoorJobThread(LPVOID param) {
    DoorJob* j = static_cast<DoorJob*>(param);
    DoorJobCompute(*j);
    InterlockedExchange(&j->done, 1);
    return 0;
}

// The second half, which has to be on the game's thread: the material from the finished file.
void FinishDoorJob(DoorJob& j) {
    DoorMaterial& slot = g_doorMaterials[j.key];
    slot.failed = true;
    if (!j.ok) return;
    const bool hdDent = j.hdDent;
    const uint64_t hash = j.hash, mapsHash = j.mapsHash;
    const std::wstring& path = j.path;
    const std::wstring& dentRoughPath = j.dentRoughPath;
    const std::wstring& dentMetalPath = j.dentMetalPath;
    const std::wstring& dentNormalPath = j.dentNormalPath;
    remixapi_MaterialInfoOpaqueEXT opaque = {};
    opaque.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT;
    opaque.albedoConstant = {1.0f, 1.0f, 1.0f};
    opaque.opacityConstant = 1.0f;
    opaque.useDrawCallAlphaState = 1;
    if (hdDent) {
        opaque.roughnessConstant = 1.0f;
        opaque.metallicConstant = 1.0f;
        opaque.roughnessTexture = dentRoughPath.c_str();
        opaque.metallicTexture = dentMetalPath.c_str();
    } else {
        // A door is paint, so it is the same paint as the body's maps make it: see
        // PrepareGlass.
        const float pg = (std::min)(g_carPaintGloss, 1.0f);
        opaque.roughnessConstant = (std::max)(g_carRoughness, 0.3f) * (1.0f - 0.45f * pg);
        opaque.metallicConstant = g_carMetallic + ((std::max)(g_carMetallic, 0.45f) - g_carMetallic) * pg;
    }
    remixapi_MaterialInfo info = {};
    info.sType = REMIXAPI_STRUCT_TYPE_MATERIAL_INFO;
    info.pNext = &opaque;
    info.hash = (hash ^ mapsHash ^ 0x0D00D5u ^ (static_cast<uint64_t>(g_carPaintGloss * 100.0f + 0.5f) * 0x9E3779B1ull)) | 1;
    info.albedoTexture = path.c_str();
    if (hdDent) info.normalTexture = dentNormalPath.c_str();
    info.emissiveColorConstant = {0.0f, 0.0f, 0.0f};
    info.filterMode = 1;   // linear
    info.wrapModeU = 2;
    info.wrapModeV = 2;
    remixapi_MaterialHandle handle = nullptr;
    const remixapi_ErrorCode result = RemixApi()->CreateMaterial(&info, &handle);
    if (result != REMIXAPI_ERROR_CODE_SUCCESS || !handle) return;
    slot.handle = handle;
    slot.failed = false;
    slot.born = g_carFrame;
    return;
}


// Called once a frame before the cars are drawn: makes the materials of the pictures that
// are finished (two a frame at most), and starts the next picture, one at a time.
void PumpDoorJobs() {
    int made = 0;
    bool running = false;
    for (auto it = g_doorJobs.begin(); it != g_doorJobs.end();) {
        DoorJob& j = **it;
        if (j.started && !j.done) { running = true; ++it; continue; }
        // Cancelled, or for a car nobody has wanted for a minute: dropped.
        if (j.cancelled || (!j.started && g_carFrame - j.asked > 1800)) {
            g_doorPending.erase(j.key);
            it = g_doorJobs.erase(it);
            continue;
        }
        if (j.started && j.done) {
            if (made >= 2) { ++it; continue; }
            ++made;
            FinishDoorJob(j);
            g_doorPending.erase(j.key);
            it = g_doorJobs.erase(it);
            continue;
        }
        ++it;
    }
    if (running) return;
    // The one a car asked for most recently, and a door (quick) before a dent (slow).
    DoorJob* next = nullptr;
    for (auto& job : g_doorJobs) {
        if (job->started || job->cancelled) continue;
        if (!next || job->asked > next->asked ||
            (job->asked == next->asked && job->delta > 4 && next->delta <= 4)) next = job.get();
    }
    if (!next) return;
    next->started = true;
    InterlockedExchange(&next->done, 0);
    HANDLE thread = CreateThread(nullptr, 0, DoorJobThread, next, 0, nullptr);
    if (thread) {
        SetThreadPriority(thread, THREAD_PRIORITY_BELOW_NORMAL);
        CloseHandle(thread);
    } else {
        DoorJobThread(next);   // no thread to be had: do it here
    }
}

remixapi_MaterialHandle DoorMaterialFor(const LampArt& art, int delta, int sprite,
                                        const PaintLook& look, bool create) {
    const auto key = std::make_pair(&art, GainKey(look.tint));
    const auto found = g_doorMaterials.find(key);
    if (found != g_doorMaterials.end()) return found->second.handle;
    if (!create) return nullptr;
    const auto pending = g_doorPending.find(key);
    if (pending != g_doorPending.end()) {
        pending->second->asked = g_carFrame;
        return nullptr;
    }
    // Queued for the thread. Its maps are made ready here (a no-op once the preparing thread
    // has done them) because the thread only reads them.
    HdCar& hd = HdFor(sprite);
    PrepareGlass(hd);
    if (g_carNormalMaps) PrepareNormal(hd);
    auto job = std::make_unique<DoorJob>();
    job->key = key;
    job->art = art;
    job->delta = delta;
    job->sprite = sprite;
    job->look = look;
    job->hd = &hd;
    job->asked = g_carFrame;
    g_doorPending[key] = job.get();
    g_doorJobs.push_back(std::move(job));
    return nullptr;
}

bool DoorMaterialWarm(const LampArt& art, const PaintLook& look) {
    const auto found = g_doorMaterials.find({&art, GainKey(look.tint)});
    return found != g_doorMaterials.end() && found->second.handle &&
           g_carFrame - found->second.born >= kCarMaterialWarmup;
}

// Which delta a bit of a car's mask stands for when it is a dent or a door, or -1.
// The same reading as the lamps: from bit 22 up, bit - 17 drawn mirrored. Delta 11
// is the first frame of the second door on a car that has a delta 12 as well, and
// on a car that does not it is a headlight, which is not a door.
int DoorDeltaOfBit(int bit, bool* mirrored) {
    *mirrored = bit >= game::kMirroredDeltaFirstBit;
    const int delta = *mirrored ? bit - game::kMirroredDeltaOffset : bit;
    if (delta >= 5 && delta <= 6) return -1;
    if (*mirrored && delta < 7) return -1;
    if (delta <= 4 || (delta >= 7 && delta <= 14)) return delta;
    return -1;
}

bool DeltaIsDoor(int delta, int sprite) {
    if (delta != 11) return true;
    const auto next = g_deltaArt.find(12);
    return next != g_deltaArt.end() && sprite >= 0 && sprite < static_cast<int>(next->second.size()) &&
           next->second[sprite].opaque > 0;
}

// The deltas a car sprite has, so a new car can have them all made before they are
// wanted: a door that opens is a delta that was not on the car a moment ago, and
// its material, new, would take its warm-up to show.
void PrewarmDoors(int sprite, const PaintLook& look) {
    for (const auto& entry : g_deltaArt) {
        if (sprite < 0 || sprite >= static_cast<int>(entry.second.size())) continue;
        const LampArt& art = entry.second[sprite];
        if (!art.Valid() || art.opaque <= 0) continue;
        if (!DeltaIsDoor(entry.first, sprite)) continue;
        DoorMaterialFor(art, entry.first, sprite, look, true);
    }
}

// One mesh instance with the sprite's own alpha test, as the car's dome is drawn.
bool DrawCutoutInstance(remixapi_MeshHandle mesh, const D3DMATRIX& world) {
    remixapi_InstanceInfo instance = {};
    instance.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO;
    remixapi_InstanceInfoBlendEXT alpha = {};
    alpha.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO_BLEND_EXT;
    alpha.alphaTestEnabled = 1;
    alpha.alphaTestReferenceValue = static_cast<uint8_t>(
        (std::max)(1, (std::min)(255, static_cast<int>(gta2::GetAlphaRef()))));
    alpha.alphaTestCompareOp = 6;
    alpha.alphaBlendEnabled = 0;
    alpha.srcColorBlendFactor = 1;
    alpha.dstColorBlendFactor = 0;
    alpha.colorBlendOp = 0;
    alpha.srcAlphaBlendFactor = 1;
    alpha.dstAlphaBlendFactor = 0;
    alpha.alphaBlendOp = 0;
    alpha.writeMask = 0xFFFFFFFFu;
    alpha.textureColorArg1Source = 1;
    alpha.textureColorArg2Source = 0;
    alpha.textureColorOperation = 3;
    alpha.textureAlphaArg1Source = 1;
    alpha.textureAlphaArg2Source = 0;
    alpha.textureAlphaOperation = 1;
    alpha.tFactor = 0xFFFFFFFFu;
    alpha.isTextureFactorBlend = 0;
    alpha.isVertexColorBakedLighting = 0;
    instance.pNext = &alpha;
    instance.mesh = mesh;
    instance.doubleSided = 1;
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 4; ++c) instance.transform.matrix[r][c] = world.m[c][r];
    }
    return RemixApi()->DrawInstance(&instance) == REMIXAPI_ERROR_CODE_SUCCESS;
}

void ReleaseCarMaterials() {
    for (auto& job : g_carJobs) job->cancelled = true;   // finished and dropped by PumpCarJobs
    // Handles belong to Remix and die with it; only our own bookkeeping goes.
    for (auto& job : g_doorJobs) job->cancelled = true;
    g_lampMaterials.clear();
    g_doorMaterials.clear();
    g_carMaterials.clear();
    g_hdMaterials.clear();
    g_pixelMaterials.clear();
    g_carMeshes.clear();
    g_carMeshUsed.clear();
    g_warmArt.clear();
}
}  // namespace

void ReleaseLampMaterials() {
    g_lampMaterials.clear();
    g_bloodMaterials.clear();
}
void ReleaseDoorMaterials() {
    for (auto& job : g_doorJobs) job->cancelled = true;   // finished and dropped by PumpDoorJobs
    g_doorMaterials.clear();
}

void SetCarDamage(float strength) {
    g_carDamage = strength < 0.0f ? 0.0f : (strength > 2.0f ? 2.0f : strength);
}

void SetCarGlassGloss(float gloss) {
    g_carGlassGloss = gloss < 0.0f ? 0.0f : (gloss > 2.0f ? 2.0f : gloss);
}

void SetCarPaintGlossFor(int sprite, float gloss) {
    if (sprite >= 0 && sprite < kGlossSprites) g_paintGlossCar[sprite] = gloss < 0.0f ? -1.0f : (gloss > 1.0f ? 1.0f : gloss);
}

void SetCarPaintGloss(float gloss) {
    g_carPaintGloss = gloss < 0.0f ? 0.0f : (gloss > 1.0f ? 1.0f : gloss);
}

void SetCarGlassCurve(float curve) {
    g_carGlassCurve = curve < 0.0f ? 0.0f : (curve > 1.5f ? 1.5f : curve);
}

SkidSmokeSettings& SkidSmoke() { return g_skid; }

void SkidSmokeLoad(const char* iniPath) {
    if (!iniPath || !*iniPath) return;
    g_skidIniPath = iniPath;
    auto pct = [&](const char* key, int fallback) {
        return GetPrivateProfileIntA("skids", key, fallback, iniPath) / 100.0f;
    };
    SkidSmokeSettings& k = g_skid;
    k.soft = GetPrivateProfileIntA("skids", "skid_soft", 1, iniPath) != 0;
    k.skidOpacity = pct("skid_opacity_percent", 45);
    k.skidSoftness = pct("skid_softness_percent", 100);
    k.persist = GetPrivateProfileIntA("skids", "skid_persist", 1, iniPath) != 0;
    k.skidHold = static_cast<float>(GetPrivateProfileIntA("skids", "skid_hold_s", 60, iniPath));
    k.skidFade = static_cast<float>(GetPrivateProfileIntA("skids", "skid_fade_s", 60, iniPath));
    k.smoke = GetPrivateProfileIntA("skids", "smoke", 0, iniPath) != 0;
    k.smokeGlow = GetPrivateProfileIntA("skids", "smoke_glow", 1, iniPath) != 0;
    k.smokeAmount = pct("smoke_amount_percent", 100);
    k.smokeOpacity = pct("smoke_opacity_percent", 22);
    k.smokeSize = pct("smoke_size_percent", 100);
    k.smokeLife = GetPrivateProfileIntA("skids", "smoke_life_ms", 1500, iniPath) / 1000.0f;
    k.smokeRise = pct("smoke_rise_percent", 100);
    k.smokeDrift = pct("smoke_drift_percent", 100);
}

bool SkidSmokeSave() {
    if (g_skidIniPath.empty()) return false;
    const SkidSmokeSettings& k = g_skid;
    bool ok = true;
    auto put = [&](const char* key, int value) {
        char text[24];
        snprintf(text, sizeof(text), "%d", value);
        ok &= WritePrivateProfileStringA("skids", key, text, g_skidIniPath.c_str()) != 0;
    };
    auto pc = [](float v) { return static_cast<int>(v * 100.0f + 0.5f); };
    put("skid_soft", k.soft ? 1 : 0);
    put("skid_opacity_percent", pc(k.skidOpacity));
    put("skid_softness_percent", pc(k.skidSoftness));
    put("skid_persist", k.persist ? 1 : 0);
    put("skid_hold_s", static_cast<int>(k.skidHold + 0.5f));
    put("skid_fade_s", static_cast<int>(k.skidFade + 0.5f));
    put("smoke", k.smoke ? 1 : 0);
    put("smoke_glow", k.smokeGlow ? 1 : 0);
    put("smoke_amount_percent", pc(k.smokeAmount));
    put("smoke_opacity_percent", pc(k.smokeOpacity));
    put("smoke_size_percent", pc(k.smokeSize));
    put("smoke_life_ms", static_cast<int>(k.smokeLife * 1000.0f + 0.5f));
    put("smoke_rise_percent", pc(k.smokeRise));
    put("smoke_drift_percent", pc(k.smokeDrift));
    return ok;
}

FireSettings& FireEffects() { return g_fire; }

void CrowdLoad(const char* iniPath) {
    char buf[8] = {};
    const bool off = GetEnvironmentVariableA("GTA2DX9_CROWD", buf, sizeof buf) && buf[0] == '0';
    g_crowdVariety = !off && GetPrivateProfileIntA("crowd", "variety", 1, iniPath) != 0;
    g_crowdLookAt = !off && GetPrivateProfileIntA("crowd", "look_at", 1, iniPath) != 0;
    const int range = static_cast<int>(GetPrivateProfileIntA("crowd", "look_range", 5, iniPath));
    g_crowdLookRange = static_cast<float>((std::max)(1, (std::min)(12, range)));
    Log("crowd: variety %d, look_at %d, look_range %.0f blocks", g_crowdVariety ? 1 : 0, g_crowdLookAt ? 1 : 0, g_crowdLookRange);
}

void FireEffectsLoad(const char* iniPath) {
    if (!iniPath || !*iniPath) return;
    g_fireIniPath = iniPath;
    auto num = [&](const char* key, int fallback) {
        return GetPrivateProfileIntA("fire", key, fallback, iniPath);
    };
    auto pct = [&](const char* key, int fallback) { return num(key, fallback) / 100.0f; };
    FireSettings& f = g_fire;
    f.onTop = num("fire_on_top", 1) != 0;
    f.sizeScale = pct("fire_size_percent", 160);
    f.maxSize = pct("fire_max_size_percent", 80);
    f.layers = (std::max)(0, (std::min)(8, static_cast<int>(num("fire_layers", 3))));
    f.layerRise = pct("fire_layer_rise_percent", 5);
    f.layerGrow = pct("fire_layer_grow_percent", 25);
    f.layerBright = pct("fire_layer_bright_percent", 70);
    f.tint[0] = pct("fire_tint_r", 100);
    f.tint[1] = pct("fire_tint_g", 55);
    f.tint[2] = pct("fire_tint_b", 18);
    f.flicker = pct("fire_flicker_percent", 20);
    f.flickerHz = static_cast<float>(num("fire_flicker_hz", 13));
    ExplosionFxLoad(iniPath);
    g_charredLuma = static_cast<float>(num("car_charred_luma", 30));
    {
        // Signed: GetPrivateProfileInt returns an unsigned number, and a negative default such as
        // forward_percent=-30 turned into 4 billion and threw the emblem off the car.
        auto logos = [&](const char* key, int fallback) {
            return static_cast<int>(GetPrivateProfileIntA("logos", key, fallback, iniPath));
        };
        g_roofLogos = logos("roof_logos", 1) != 0;
        g_logoCar[kLogoLoonies] = logos("loonies_car", -1);
        g_logoCar[kLogoYakuza] = logos("yakuza_car", 32);
        g_logoCar[kLogoZaibatsu] = logos("zaibatsu_car", 63);
        g_logoLumaMax[kLogoLoonies] = static_cast<float>(logos("loonies_max_brightness", 0));
        g_logoLumaMax[kLogoYakuza] = static_cast<float>(logos("yakuza_max_brightness", 256));
        g_logoLumaMax[kLogoZaibatsu] = static_cast<float>(logos("zaibatsu_max_brightness", 55));
        g_logoCar[kLogoRednecks] = logos("rednecks_car", 36);
        g_logoLumaMax[kLogoRednecks] = static_cast<float>(logos("rednecks_max_brightness", 78));
        g_logoBlueMin[kLogoRednecks] = logos("rednecks_blue_min_percent", 120) / 100.0f;
        g_logoSize[kLogoRednecks] = logos("rednecks_size_percent", 15) / 100.0f;
        g_logoForward[kLogoRednecks] = logos("rednecks_forward_percent", 20) / 100.0f;
        g_logoTurn[kLogoRednecks] = (logos("rednecks_turn_degrees", 180) / 90) & 3;
        // Scientists (Meteor), Hare Krishna (Karma Bus), Russian Mafia (Bulwark).
        g_logoCar[kLogoSrs] = logos("srs_car", 42);
        g_logoLumaMax[kLogoSrs] = static_cast<float>(logos("srs_max_brightness", 0));
        g_logoBlueMin[kLogoSrs] = logos("srs_blue_min_percent", 0) / 100.0f;
        g_logoSize[kLogoSrs] = logos("srs_size_percent", 20) / 100.0f;
        g_logoForward[kLogoSrs] = logos("srs_forward_percent", -6) / 100.0f;
        g_logoTurn[kLogoSrs] = (logos("srs_turn_degrees", 0) / 90) & 3;
        g_logoCar[kLogoKrishna] = logos("krishna_car", 26);
        g_logoLumaMax[kLogoKrishna] = static_cast<float>(logos("krishna_max_brightness", 0));
        g_logoBlueMin[kLogoKrishna] = logos("krishna_blue_min_percent", 0) / 100.0f;
        g_logoSize[kLogoKrishna] = logos("krishna_size_percent", 40) / 100.0f;
        g_logoForward[kLogoKrishna] = logos("krishna_forward_percent", 0) / 100.0f;
        g_logoTurn[kLogoKrishna] = (logos("krishna_turn_degrees", 180) / 90) & 3;
        g_logoCar[kLogoRussian] = logos("russian_car", 9);
        g_logoLumaMax[kLogoRussian] = static_cast<float>(logos("russian_max_brightness", 0));
        g_logoBlueMin[kLogoRussian] = logos("russian_blue_min_percent", 0) / 100.0f;
        g_logoSize[kLogoRussian] = logos("russian_size_percent", 22) / 100.0f;
        g_logoForward[kLogoRussian] = logos("russian_forward_percent", -38) / 100.0f;
        g_logoTurn[kLogoRussian] = (logos("russian_turn_degrees", 180) / 90) & 3;
        g_roofLogoSize = logos("size_percent", 18) / 100.0f;
        g_roofLogoForward = logos("forward_percent", -30) / 100.0f;
        // Per-gang overrides; Zaibatsu follows the shared size_percent/forward_percent above.
        g_logoLift = (std::max)(0.0005f, logos("lift_thousandths", 4) / 1000.0f);
        g_logoSize[kLogoZaibatsu] = g_roofLogoSize;
        g_logoForward[kLogoZaibatsu] = g_roofLogoForward;
        g_logoSize[kLogoYakuza] = logos("yakuza_size_percent", 11) / 100.0f;
        g_logoForward[kLogoYakuza] = logos("yakuza_forward_percent", -20) / 100.0f;
        g_logoSize[kLogoLoonies] = logos("loonies_size_percent", 18) / 100.0f;
        g_logoForward[kLogoLoonies] = logos("loonies_forward_percent", -30) / 100.0f;
        g_logoTurn[kLogoYakuza] = (logos("yakuza_turn_degrees", 180) / 90) & 3;
        g_logoTurn[kLogoLoonies] = (logos("loonies_turn_degrees", 180) / 90) & 3;
        g_roofLogoQuarter = (logos("rotate_degrees", 0) / 90) & 3;
    }
    g_boardingUi = num("boarding_ui", 0) != 0;
    SetBoardingHeight(pct("boarding_height_percent", 45));
    g_boardingUiNight = (std::max)(0.0f, (std::min)(1.0f, pct("boarding_ui_night_percent", 50)));
    f.smoke = num("fire_smoke", 1) != 0;
    f.smokeRate = pct("fire_smoke_rate_x100", 700);
    f.smokeOpacity = pct("fire_smoke_opacity_percent", 35);
    f.smokeSize = pct("fire_smoke_size_percent", 100);
    f.smokeLife = num("fire_smoke_life_ms", 2500) / 1000.0f;
    f.smokeRise = pct("fire_smoke_rise_percent", 100);
    f.smokeDrift = pct("fire_smoke_drift_percent", 100);
    f.smokeGrey = pct("fire_smoke_grey_percent", 16);
    f.flames = num("fire_flames", 1) != 0;
    f.flameRate = static_cast<float>(num("fire_flame_rate", 90));
    f.flameSize = pct("fire_flame_size_percent", 100);
    f.flameRise = pct("fire_flame_rise_percent", 100);
    f.flameLife = num("fire_flame_life_ms", 700) / 1000.0f;
    f.flameBright = pct("fire_flame_bright_percent", 100);
    f.emberRate = static_cast<float>(num("fire_ember_rate", 12));
    f.spriteBright = pct("fire_sprite_bright_percent", 50);
    f.scorch = num("fire_scorch", 1) != 0;
    f.scorchLife = static_cast<float>(num("fire_scorch_life_s", 60));
    f.scorchOpacity = pct("fire_scorch_opacity_percent", 85);
    f.scorchSize = pct("fire_scorch_size_percent", 100);
}

bool FireEffectsSave() {
    if (g_fireIniPath.empty()) return false;
    const FireSettings& f = g_fire;
    bool ok = true;
    auto put = [&](const char* key, int value) {
        char text[24];
        snprintf(text, sizeof(text), "%d", value);
        ok &= WritePrivateProfileStringA("fire", key, text, g_fireIniPath.c_str()) != 0;
    };
    auto pc = [](float v) { return static_cast<int>(v * 100.0f + 0.5f); };
    put("fire_on_top", f.onTop ? 1 : 0);
    put("fire_size_percent", pc(f.sizeScale));
    put("fire_max_size_percent", pc(f.maxSize));
    put("fire_layers", f.layers);
    put("fire_layer_rise_percent", pc(f.layerRise));
    put("fire_layer_grow_percent", pc(f.layerGrow));
    put("fire_layer_bright_percent", pc(f.layerBright));
    put("fire_tint_r", pc(f.tint[0]));
    put("fire_tint_g", pc(f.tint[1]));
    put("fire_tint_b", pc(f.tint[2]));
    put("fire_flicker_percent", pc(f.flicker));
    put("fire_flicker_hz", static_cast<int>(f.flickerHz + 0.5f));
    put("fire_smoke", f.smoke ? 1 : 0);
    put("fire_smoke_rate_x100", pc(f.smokeRate));
    put("fire_smoke_opacity_percent", pc(f.smokeOpacity));
    put("fire_smoke_size_percent", pc(f.smokeSize));
    put("fire_smoke_life_ms", static_cast<int>(f.smokeLife * 1000.0f + 0.5f));
    put("fire_smoke_rise_percent", pc(f.smokeRise));
    put("fire_smoke_drift_percent", pc(f.smokeDrift));
    put("fire_smoke_grey_percent", pc(f.smokeGrey));
    put("fire_flames", f.flames ? 1 : 0);
    put("fire_flame_rate", static_cast<int>(f.flameRate + 0.5f));
    put("fire_flame_size_percent", pc(f.flameSize));
    put("fire_flame_rise_percent", pc(f.flameRise));
    put("fire_flame_life_ms", static_cast<int>(f.flameLife * 1000.0f + 0.5f));
    put("fire_flame_bright_percent", pc(f.flameBright));
    put("fire_ember_rate", static_cast<int>(f.emberRate + 0.5f));
    put("fire_sprite_bright_percent", pc(f.spriteBright));
    put("fire_scorch", f.scorch ? 1 : 0);
    put("fire_scorch_life_s", static_cast<int>(f.scorchLife + 0.5f));
    put("fire_scorch_opacity_percent", pc(f.scorchOpacity));
    put("fire_scorch_size_percent", pc(f.scorchSize));
    return ok;
}

void SetCarNormalStrength(float strength) {
    g_carNormalStrength = strength < 0.0f ? 0.0f : (strength > 1.0f ? 1.0f : strength);
}

void SetCarHd(bool hd, bool normalMaps) {
    g_carHd = hd;
    g_carNormalMaps = normalMaps;
}

void LiveGeometry::DrawCarModels(IDirect3DDevice9* device) {
    if (carModels_.empty()) return;
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetFVF(kWorldFvf);
    for (const CarModelUse& use : carModels_) ModelDraw(device, *use.model, use.placement, nullptr, 0.0f);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
}

// Street furniture and plants, placed by rule rather than by hand so every
// district gets them: a lamp post at each of the map's own lamps; on the
// pavement cells of street-level columns against a building a bin, a bench
// or a hydrant now and then. Which cell gets what is a hash of the cell, so it never changes
// between frames or sessions. Drawn within a radius of the camera, nearest
// first, up to a budget, since the models are dense.
void LiveGeometry::DrawProps(IDirect3DDevice9* device, const gta2::Vec3& eye) {
    if (!ground_ || !ground_->Ready()) return;
    const gta2::Map* map = ground_->MapData();
    const Model* lamp = ModelForProp("lamp");
    const Model* bin = ModelForProp("bin");
    const Model* bench = ModelForProp("bench");
    const Model* hydrant = ModelForProp("hydrant");
    const Model* trees[3] = {ModelForProp("tree1"), ModelForProp("tree2"), ModelForProp("tree3")};
    const bool anyTree = trees[0] || trees[1] || trees[2];
    // Street furniture, docks and rooftops (tools/gen_env2.py): placed by rule
    // like the rest, see the cell loop below and the two loops after it.
    const Model* signStop = ModelForProp("sign_stop");
    const Model* signOneWay = ModelForProp("sign_oneway");
    const Model* busShelter = ModelForProp("bus_shelter");
    const Model* meter = ModelForProp("parking_meter");
    const Model* mailbox = ModelForProp("mailbox");
    const Model* containers[4] = {ModelForProp("container1"), ModelForProp("container2"), ModelForProp("container3"), ModelForProp("container4")};
    const Model* crane = ModelForProp("crane");
    const Model* roofAc = ModelForProp("roof_ac");
    const Model* roofVent = ModelForProp("roof_vent");
    const Model* waterTower = ModelForProp("water_tower");
    const Model* rail = ModelForProp("rail");
    const bool anyEnv = signStop || signOneWay || busShelter || meter || mailbox || containers[0] || crane || roofAc || roofVent || waterTower || rail;
    if (!lamp && !bin && !bench && !hydrant && !anyTree && !anyEnv) return;

    struct Placed { const Model* model; float x, y, z, yaw, scale; float d2; };
    std::vector<Placed> placed;
    // 48 blocks, a quarter into the fog (18-130), where a lamp is a few pixels tall: the
    // edge where props appear is no longer seen while driving (PERF-2; was 36 with a budget
    // of 180, and 26 before that). Affordable since the placements are cached per cell,
    // the meshes merged and what is beside the picture skipped.
    constexpr float kRadius = 48.0f;
    constexpr int kBudget = 260;
    // A column's lid tile, ground type and level, or false off the map / in a hole.
    auto lidOf = [&](int cx, int cz, int* tile, int* ground, int* level) {
        const int my = gta2::kMapHeight - 1 - cz;
        if (cx < 0 || cx >= gta2::kMapWidth || my < 0 || my >= gta2::kMapHeight) return false;
        const gta2::Column& c = map->ColumnAt(cx, my);
        if (c.blocks.empty() || c.blocks.back() >= map->BlockCount()) return false;
        const gta2::Block& b = map->BlockAt(c.blocks.back());
        *tile = b.lid.Tile();
        *ground = b.GroundType();
        *level = c.offset + static_cast<int>(c.blocks.size());
        return true;
    };
    auto isRoad = [&](int cx, int cz, int level) { int t, g, l; return lidOf(cx, cz, &t, &g, &l) && g == 1 && l == level; };
    auto isWater = [&](int cx, int cz, int level) { int t, g, l; return lidOf(cx, cz, &t, &g, &l) && IsWaterTile(t) && l <= level; };
    int cranes = 0;

    // The placements depend only on the eye's cell and level (the rules read the map, the
    // hashes the cell): kept from the last frame while the eye stays in its cell, with
    // only the distances brought up to date (PERF-2: the scan of 73 x 73 cells with their
    // neighbours was a millisecond or more of every frame).
    static std::vector<Placed> s_placedCache;
    static const void* s_placedMap = nullptr;
    static int s_placedKey[3] = {-100000, -100000, -100000};
    const int placedKey[3] = {static_cast<int>(std::floor(eye.x)), static_cast<int>(std::floor(eye.z)),
                              static_cast<int>(std::floor(eye.y))};
    if (s_placedMap == map && placedKey[0] == s_placedKey[0] && placedKey[1] == s_placedKey[1] &&
        placedKey[2] == s_placedKey[2]) {
        placed = s_placedCache;
        for (Placed& p : placed) {
            const float dx = p.x - eye.x, dz = p.z - eye.z;
            p.d2 = dx * dx + dz * dz;
        }
    } else {
    // The lamps. The post goes to the edge of its cell, not under the light wherever the
    // map put it (often mid-pavement, where the game walks its people straight through
    // it: defect pt-player-walks-through-street-lamps): to the kerb when a road runs
    // beside the cell, else against a building, else to the cell's nearest edge. A lamp
    // over the roadway stands on the kerb of a pavement cell beside it, or not at all
    // (never on a cell a car drives over). Computed once per level for every lamp and
    // shared with the chase camera's obstacles (MapLampPosts).
    if (lamp) {
        static const void* s_postsMap = nullptr;
        static size_t s_postsCount = 0;
        const std::vector<gta2::Vec3>& lamps = MapLamps();
        if (s_postsMap != map || s_postsCount != lamps.size() || MapLampPosts().size() != lamps.size()) {
            std::vector<gta2::Vec3> posts;
            posts.reserve(lamps.size());
            int moved = 0, dropped = 0;
            auto higher = [&](int nx, int nz, int level) {
                const int nMapY = gta2::kMapHeight - 1 - nz;
                if (nx < 0 || nx >= gta2::kMapWidth || nMapY < 0 || nMapY >= gta2::kMapHeight) return false;
                const gta2::Column& nc = map->ColumnAt(nx, nMapY);
                return nc.offset + static_cast<int>(nc.blocks.size()) > level;
            };
            for (const gta2::Vec3& at : lamps) {
                gta2::Vec3 post = at;
                float floor = at.y;
                const int cx = static_cast<int>(std::floor(at.x)), cz = static_cast<int>(std::floor(at.z));
                int t, g, l;
                if (!ground_->SurfaceAt(at.x, at.z, at.y + 0.5f, &floor) || !lidOf(cx, cz, &t, &g, &l)) { posts.push_back(post); continue; }
                auto clampIn = [](float v, int c) { return (std::min)(c + 0.85f, (std::max)(c + 0.15f, v)); };
                if (g == 1) {
                    // Over the roadway: the kerb of a pavement neighbour at this level, on its road side.
                    bool found = false;
                    for (int k = 0; k < 4 && !found; ++k) {
                        const int dx = (k == 0) - (k == 1), dz = (k == 2) - (k == 3);
                        int nt, ng, nl;
                        if (!lidOf(cx + dx, cz + dz, &nt, &ng, &nl) || ng != 2 || nl != l) continue;
                        post.x = dx ? cx + dx + 0.5f - dx * 0.42f : clampIn(at.x, cx);
                        post.z = dz ? cz + dz + 0.5f - dz * 0.42f : clampIn(at.z, cz);
                        found = true;
                    }
                    if (!found) { post.x = std::nanf(""); ++dropped; } else ++moved;
                    posts.push_back(post);
                    continue;
                }
                int edgeDx = 0, edgeDz = 0;
                for (int k = 0; k < 4 && !edgeDx && !edgeDz; ++k) {   // a road beside: the kerb
                    const int dx = (k == 0) - (k == 1), dz = (k == 2) - (k == 3);
                    if (isRoad(cx + dx, cz + dz, l)) { edgeDx = dx; edgeDz = dz; }
                }
                for (int k = 0; k < 4 && !edgeDx && !edgeDz; ++k) {   // else a building beside: the wall
                    const int dx = (k == 0) - (k == 1), dz = (k == 2) - (k == 3);
                    if (higher(cx + dx, cz + dz, l)) { edgeDx = dx; edgeDz = dz; }
                }
                if (!edgeDx && !edgeDz) {   // else the cell's edge nearest the light
                    const float fx = at.x - cx - 0.5f, fz = at.z - cz - 0.5f;
                    if (std::fabs(fx) >= std::fabs(fz)) edgeDx = fx < 0.0f ? -1 : 1; else edgeDz = fz < 0.0f ? -1 : 1;
                }
                post.x = edgeDx ? cx + 0.5f + edgeDx * 0.42f : clampIn(at.x, cx);
                post.z = edgeDz ? cz + 0.5f + edgeDz * 0.42f : clampIn(at.z, cz);
                if (std::fabs(post.x - at.x) + std::fabs(post.z - at.z) > 0.02f) ++moved;
                posts.push_back(post);
            }
            SetMapLampPosts(posts);
            s_postsMap = map;
            s_postsCount = lamps.size();
            Log("lamp posts: %zu lamps, %d posts moved to a kerb or wall, %d over the roadway left out", lamps.size(), moved, dropped);
        }
        const std::vector<gta2::Vec3>& posts = MapLampPosts();
        for (size_t i = 0; i < lamps.size() && i < posts.size(); ++i) {
            const gta2::Vec3& at = lamps[i];
            const gta2::Vec3& post = posts[i];
            if (std::isnan(post.x)) continue;
            const float dx = post.x - eye.x, dz = post.z - eye.z;
            const float d2 = dx * dx + dz * dz;
            if (d2 > kRadius * kRadius) continue;
            float floor = at.y;
            if (!ground_->SurfaceAt(post.x, post.z, at.y + 0.5f, &floor)) continue;
            // A GTA2 street lamp sits well above the road; the post stands under it.
            if (at.y - floor > 3.5f || at.y - floor < 0.3f) continue;
            placed.push_back({lamp, post.x, floor, post.z, 0.0f, (at.y - floor + 0.3f) / (std::max)(lamp->Height(), 0.1f), d2});
        }
    }
    // The cells.
    const int cx0 = static_cast<int>(std::floor(eye.x - kRadius)), cx1 = static_cast<int>(std::floor(eye.x + kRadius));
    const int cz0 = static_cast<int>(std::floor(eye.z - kRadius)), cz1 = static_cast<int>(std::floor(eye.z + kRadius));
    const int eyeLevel = static_cast<int>(std::floor(eye.y));
    for (int cz = cz0; cz <= cz1; ++cz) {
        for (int cx = cx0; cx <= cx1; ++cx) {
            const int mapY = gta2::kMapHeight - 1 - cz;
            if (cx < 0 || cx >= gta2::kMapWidth || mapY < 0 || mapY >= gta2::kMapHeight) continue;
            const float px = cx + 0.5f, pz = cz + 0.5f;
            const float dx = px - eye.x, dz = pz - eye.z;
            const float d2 = dx * dx + dz * dz;
            if (d2 > kRadius * kRadius) continue;
            const gta2::Column& column = map->ColumnAt(cx, mapY);
            if (column.blocks.empty()) continue;
            const uint32_t topIndex = column.blocks.back();
            if (topIndex >= map->BlockCount()) continue;
            const gta2::Block& top = map->BlockAt(topIndex);
            if (!top.lid) continue;
            const int topLevel = column.offset + static_cast<int>(column.blocks.size());   // the lid's height
            if (topLevel > eyeLevel + 2 || topLevel < eyeLevel - 6) continue;         // street level only
            const int ground = top.GroundType();
            const uint32_t h = (static_cast<uint32_t>(cx) * 73856093u) ^ (static_cast<uint32_t>(mapY) * 19349663u);
            const float yaw = static_cast<float>((h >> 8) & 1023) / 1024.0f * 6.2832f;
            const Model* model = nullptr;
            float scale = 1.0f;
            float ox = 0.0f, oz = 0.0f;
            // Trees in the parks: the lid is a grass tile, and so are the four
            // cells around it at the same height, which keeps them to lawns and
            // off the odd grass-topped roof or verge; one cell in four gets one.
            // ("Field" alone is no guide: GTA2 uses that lid type for roofs,
            // plazas and bare ground as much as for grass.)
            if (anyTree && IsGrassTile(top.lid.Tile())) ++g_treeStatGrass;
            if (anyTree && IsGrassTile(top.lid.Tile()) && (h % 4) == 0) {
                bool lawn = true;
                for (int k = 0; k < 4 && lawn; ++k) {
                    const int nx = cx + (k == 0) - (k == 1), nz = cz + (k == 2) - (k == 3);
                    const int nMapY = gta2::kMapHeight - 1 - nz;
                    if (nx < 0 || nx >= gta2::kMapWidth || nMapY < 0 || nMapY >= gta2::kMapHeight) { lawn = false; break; }
                    const gta2::Column& nc = map->ColumnAt(nx, nMapY);
                    if (nc.blocks.empty() || nc.blocks.back() >= map->BlockCount()) { lawn = false; break; }
                    const gta2::Block& nb = map->BlockAt(nc.blocks.back());
                    if (nc.offset + static_cast<int>(nc.blocks.size()) != topLevel || !IsGrassTile(nb.lid.Tile())) lawn = false;
                }
                if (lawn) {
                    const Model* tree = trees[(h >> 5) % 3];
                    if (!tree) tree = trees[0] ? trees[0] : (trees[1] ? trees[1] : trees[2]);
                    if (tree) {
                        ++g_treeStatPlaced;
                        model = tree;
                        const float height = 2.0f + static_cast<float>((h >> 9) & 7) / 7.0f * 1.2f;   // 2.0 .. 3.2 blocks
                        scale = height / (std::max)(tree->Height(), 0.1f);
                        ox = (static_cast<float>((h >> 12) & 15) / 15.0f - 0.5f) * 0.5f;
                        oz = (static_cast<float>((h >> 16) & 15) / 15.0f - 0.5f) * 0.5f;
                    }
                }
            }
            if (!model && anyEnv && ground != 1 && !IsWaterTile(top.lid.Tile())) {
                // The kerb side: a road neighbour at this level. A junction is a
                // road cell with three or more road neighbours. (Pavement only.)
                int roadDx = 0, roadDz = 0;
                for (int k = 0; k < 4 && !roadDx && !roadDz && ground == 2; ++k) {
                    const int nx = cx + (k == 0) - (k == 1), nz = cz + (k == 2) - (k == 3);
                    if (isRoad(nx, nz, topLevel)) { roadDx = nx - cx; roadDz = nz - cz; }
                }
                // Water beside the cell: a quay (the map types quays as plain
                // lids, not pavement). Containers along it, now and then a
                // crane whose boom reaches over the water.
                int waterDx = 0, waterDz = 0;
                for (int k = 0; k < 4 && !waterDx && !waterDz; ++k) {
                    const int nx = cx + (k == 0) - (k == 1), nz = cz + (k == 2) - (k == 3);
                    if (isWater(nx, nz, topLevel)) { waterDx = nx - cx; waterDz = nz - cz; }
                }
                if (roadDx || roadDz) {
                    const int rx = cx + roadDx, rz = cz + roadDz;
                    int roadNeighbours = 0;
                    for (int k = 0; k < 4; ++k) roadNeighbours += isRoad(rx + (k == 0) - (k == 1), rz + (k == 2) - (k == 3), topLevel) ? 1 : 0;
                    const float faceRoad = std::atan2(static_cast<float>(-roadDx), static_cast<float>(-roadDz));   // the plate (-z) toward the road
                    // One stop sign per junction corner at most: the pavement cell
                    // diagonal to the junction's corner, picked by a hash of the
                    // junction cell so the four approaches do not all get one.
                    if (roadNeighbours >= 3 && signStop && ((static_cast<uint32_t>(rx) * 2246822519u ^ static_cast<uint32_t>(rz) * 3266489917u) % 4) == 0 && (h % 3) == 0) {
                        model = signStop; scale = 1.0f;
                        ox = roadDx * 0.38f; oz = roadDz * 0.38f;
                        placed.push_back({model, px + ox, 0.0f, pz + oz, faceRoad, scale, d2});   // y filled below
                        model = nullptr;
                        float floor = static_cast<float>(topLevel);
                        ground_->SurfaceAt(px + ox, pz + oz, topLevel + 0.5f, &floor);
                        placed.back().y = floor;
                        continue;
                    }
                    if (roadNeighbours == 2 && signOneWay && (h % 41) == 0) {
                        float floor = static_cast<float>(topLevel);
                        ground_->SurfaceAt(px + roadDx * 0.38f, pz + roadDz * 0.38f, topLevel + 0.5f, &floor);
                        placed.push_back({signOneWay, px + roadDx * 0.38f, floor, pz + roadDz * 0.38f, faceRoad, 1.0f, d2});
                        continue;
                    }
                    if (meter && (h % 11) == 0) {
                        float floor = static_cast<float>(topLevel);
                        ground_->SurfaceAt(px + roadDx * 0.36f, pz + roadDz * 0.36f, topLevel + 0.5f, &floor);
                        placed.push_back({meter, px + roadDx * 0.36f, floor, pz + roadDz * 0.36f, faceRoad, 1.0f, d2});
                        continue;
                    }
                }
                // A dock yard, not a waterside walkway: the cell and the two cells
                // behind it (away from the water) are plain lids at this height,
                // nothing built stands within a block, and no road runs beside it.
                // (Azeri Heights' cobbled quay promenade runs between the river and
                // a road, with a container dropped in the middle of it otherwise.)
                // Yards are plain lids only: a pavement or road cell beside the
                // water is a promenade, and a field cell is a beach or a lawn.
                bool dockYard = (waterDx || waterDz) && ground == 0 && !IsGrassTile(top.lid.Tile());
                for (int k = 1; k <= 2 && dockYard; ++k) {
                    int t, g, l;
                    if (!lidOf(cx - waterDx * k, cz - waterDz * k, &t, &g, &l) || l != topLevel || g != 0 || IsWaterTile(t) || IsGrassTile(t)) dockYard = false;
                }
                for (int dz = -1; dz <= 1 && dockYard; ++dz) {
                    for (int dx = -1; dx <= 1 && dockYard; ++dx) {
                        if (!dx && !dz) continue;
                        const int nx = cx + dx, nz = cz + dz, nMapY = gta2::kMapHeight - 1 - nz;
                        if (nx < 0 || nx >= gta2::kMapWidth || nMapY < 0 || nMapY >= gta2::kMapHeight) continue;
                        const gta2::Column& nc = map->ColumnAt(nx, nMapY);
                        if (nc.offset + static_cast<int>(nc.blocks.size()) > topLevel) dockYard = false;   // something built beside it
                        else if (isRoad(nx, nz, topLevel)) dockYard = false;
                    }
                }
                if (dockYard && containers[0]) {
                    const float alongEdge = waterDx ? 0.0f : 1.5708f;   // the long axis parallel to the quay
                    if (crane && cranes < 2 && (h % 29) == 0) {
                        // Needs a run of quay: the two cells along the edge must be quay too.
                        const int ex = waterDx ? 0 : 1, ez = waterDx ? 1 : 0;
                        int t1, g1, l1, t2, g2, l2;
                        const bool run = lidOf(cx + ex, cz + ez, &t1, &g1, &l1) && l1 == topLevel && isWater(cx + ex + waterDx, cz + ez + waterDz, topLevel)
                                      && lidOf(cx - ex, cz - ez, &t2, &g2, &l2) && l2 == topLevel && isWater(cx - ex + waterDx, cz - ez + waterDz, topLevel);
                        if (run) {
                            ++cranes;
                            float floor = static_cast<float>(topLevel);
                            ground_->SurfaceAt(px - waterDx * 0.3f, pz - waterDz * 0.3f, topLevel + 0.5f, &floor);
                            placed.push_back({crane, px - waterDx * 0.3f, floor, pz - waterDz * 0.3f, std::atan2(static_cast<float>(waterDx), static_cast<float>(waterDz)), 1.0f, d2});
                            continue;
                        }
                    }
                    if ((h % 5) == 0) {
                        const Model* box = containers[(h >> 3) & 3];
                        if (!box) box = containers[0];
                        float floor = static_cast<float>(topLevel);
                        ground_->SurfaceAt(px - waterDx * 0.1f, pz - waterDz * 0.1f, topLevel + 0.5f, &floor);
                        placed.push_back({box, px - waterDx * 0.1f, floor, pz - waterDz * 0.1f, alongEdge, 1.0f, d2});
                        continue;
                    }
                }
            }
            if (!model && ground == 2) {
                // Against a building: a neighbour whose column stands higher.
                int wallDx = 0, wallDz = 0;
                for (int k = 0; k < 4 && !wallDx && !wallDz; ++k) {
                    const int nx = cx + (k == 0) - (k == 1), nz = cz + (k == 2) - (k == 3);
                    const int nMapY = gta2::kMapHeight - 1 - nz;
                    if (nx < 0 || nx >= gta2::kMapWidth || nMapY < 0 || nMapY >= gta2::kMapHeight) continue;
                    const gta2::Column& nc = map->ColumnAt(nx, nMapY);
                    if (nc.offset + static_cast<int>(nc.blocks.size()) > topLevel) { wallDx = nx - cx; wallDz = nz - cz; }
                }
                if (!wallDx && !wallDz) continue;
                const uint32_t pick = h % 23;
                if (pick == 0 && bin) { model = bin; scale = 0.45f / (std::max)(bin->Height(), 0.1f); }
                else if (pick == 1 && bench && (h & 64)) { model = bench; scale = 0.75f / (std::max)((std::max)(bench->Length(), bench->Width()), 0.1f); }
                else if (pick == 2 && hydrant) { model = hydrant; scale = 0.4f / (std::max)(hydrant->Height(), 0.1f); }
                else if (pick == 3 && mailbox && (h & 128)) { model = mailbox; scale = 1.0f; }
                if (!model) continue;
                ox = wallDx * 0.34f;
                oz = wallDz * 0.34f;
            }
            if (!model) continue;
            float floor = static_cast<float>(topLevel);
            ground_->SurfaceAt(px + ox, pz + oz, topLevel + 0.5f, &floor);
            placed.push_back({model, px + ox, floor, pz + oz, yaw, scale, d2});
        }
    }
    // Bus shelters: on the pavement cell beside each bus-stop zone cell, open side to it.
    if (busShelter) {
        for (const EnvCell& stop : g_busStops) {
            const int sz = gta2::kMapHeight - 1 - stop.y;
            const float dx = stop.x + 0.5f - eye.x, dz = sz + 0.5f - eye.z;
            if (dx * dx + dz * dz > kRadius * kRadius) continue;
            int t0, g0, l0;
            if (!lidOf(stop.x, sz, &t0, &g0, &l0)) continue;
            for (int k = 0; k < 4; ++k) {
                const int nx = stop.x + (k == 0) - (k == 1), nz = sz + (k == 2) - (k == 3);
                int t, g, l;
                if (!lidOf(nx, nz, &t, &g, &l) || g != 2 || l != l0) continue;
                // Open side (-x in the model) toward the stop cell; the model's
                // -x turns onto (toRoadX, toRoadZ) with yaw = atan2(-toRoadZ, -toRoadX)
                // in the drawer's rotation (x' = c x - s z, z' = s x + c z).
                const int toRoadX = stop.x - nx, toRoadZ = sz - nz;
                const float yaw = std::atan2(static_cast<float>(toRoadZ), static_cast<float>(toRoadX)) + 3.14159f;
                float floor = static_cast<float>(l);
                ground_->SurfaceAt(nx + 0.5f - toRoadX * 0.2f, nz + 0.5f - toRoadZ * 0.2f, l + 0.5f, &floor);
                placed.push_back({busShelter, nx + 0.5f - toRoadX * 0.2f, floor, nz + 0.5f - toRoadZ * 0.2f, yaw, 1.0f, dx * dx + dz * dz});
                break;
            }
        }
    }
    // The elevated track: girders and rails on every straight rail cell.
    if (rail) {
        constexpr float kRailRadius = 40.0f;
        for (const EnvCell& cell : g_railCells) {
            if (cell.alongX == 2) continue;
            const int rz = gta2::kMapHeight - 1 - cell.y;
            const float px = cell.x + 0.5f, pz = rz + 0.5f;
            const float dx = px - eye.x, dz = pz - eye.z;
            const float d2 = dx * dx + dz * dz;
            if (d2 > kRailRadius * kRailRadius) continue;
            placed.push_back({rail, px, static_cast<float>(cell.level), pz, cell.alongX ? 1.5708f : 0.0f, 1.0f, d2});
        }
    }
    // Rooftops above the street: a unit, a vent or a water tower on flat roofs
    // whose four neighbours are at the same height (so never on an edge).
    if (roofAc || roofVent || waterTower) {
        constexpr float kRoofRadius = 30.0f;
        const int rx0 = static_cast<int>(std::floor(eye.x - kRoofRadius)), rx1 = static_cast<int>(std::floor(eye.x + kRoofRadius));
        const int rz0 = static_cast<int>(std::floor(eye.z - kRoofRadius)), rz1 = static_cast<int>(std::floor(eye.z + kRoofRadius));
        for (int cz = rz0; cz <= rz1; ++cz) {
            for (int cx = rx0; cx <= rx1; ++cx) {
                const uint32_t h = (static_cast<uint32_t>(cx) * 2654435761u) ^ (static_cast<uint32_t>(cz) * 40503u);
                const uint32_t pick = h % 211;
                const Model* model = pick == 0 && waterTower ? waterTower : (pick < 12 && roofAc ? roofAc : (pick < 20 && roofVent ? roofVent : nullptr));
                if (!model) continue;
                int t, g, l;
                if (!lidOf(cx, cz, &t, &g, &l)) continue;
                if (l <= eyeLevel + 2 || l > eyeLevel + 9 || IsGrassTile(t) || IsWaterTile(t)) continue;
                bool flat = true;
                for (int k = 0; k < 4 && flat; ++k) {
                    int nt, ng, nl;
                    if (!lidOf(cx + (k == 0) - (k == 1), cz + (k == 2) - (k == 3), &nt, &ng, &nl) || nl != l) flat = false;
                }
                if (!flat) continue;
                const float px = cx + 0.5f + (static_cast<float>((h >> 12) & 15) / 15.0f - 0.5f) * 0.4f;
                const float pz = cz + 0.5f + (static_cast<float>((h >> 16) & 15) / 15.0f - 0.5f) * 0.4f;
                const float dx = px - eye.x, dz = pz - eye.z;
                const float d2 = dx * dx + dz * dz;
                if (d2 > kRoofRadius * kRoofRadius) continue;
                placed.push_back({model, px, static_cast<float>(l), pz, static_cast<float>((h >> 20) & 3) * 1.5708f, 1.0f, d2});
            }
        }
    }
    if (anyEnv && (g_treeStatFrames % 300) == 299) {
        int counts[16] = {};
        const Model* kinds[16] = {signStop, signOneWay, busShelter, meter, mailbox, containers[0], containers[1], containers[2], containers[3], crane, roofAc, roofVent, waterTower, rail, nullptr, nullptr};
        for (const Placed& p : placed) for (int k = 0; k < 14; ++k) if (kinds[k] && p.model == kinds[k]) ++counts[k];
        Log("environment props in range: stop %d oneway %d shelter %d meter %d mailbox %d containers %d crane %d ac %d vent %d tower %d rail %d",
            counts[0], counts[1], counts[2], counts[3], counts[4], counts[5] + counts[6] + counts[7] + counts[8], counts[9], counts[10], counts[11], counts[12], counts[13]);
    }
    if (anyTree && (++g_treeStatFrames % 300) == 0) {
        Log("park trees: in the last 300 frames %d grass cells seen, %d trees placed (eye level %d)", g_treeStatGrass, g_treeStatPlaced, eyeLevel);
        g_treeStatGrass = g_treeStatPlaced = 0;
    }
    s_placedCache = placed;
    s_placedMap = map;
    for (int k = 0; k < 3; ++k) s_placedKey[k] = placedKey[k];
    }   // the placement scan
    // Nothing behind the camera (a prop is at most about a block across).
    placed.erase(std::remove_if(placed.begin(), placed.end(),
                                [](const Placed& p) { return BehindView(p.x, p.y, p.z, 1.5f); }),
                 placed.end());
    // Nothing under the player's feet, and nothing beside a car's doors: the
    // game puts him on the pavement when he leaves a car, and a bin or a meter
    // placed by rule exactly there would hold his eye. The map's own lamps and
    // the park trees stay where they are (a lamp has its light above it).
    {
        std::vector<std::pair<float, float>> doors;
        for (const CarBodyUse& use : carBodies_) doors.push_back({use.objectToWorld.m[3][0], use.objectToWorld.m[3][2]});
        for (const CarModelUse& use : carModels_) doors.push_back({use.placement.m[3][0], use.placement.m[3][2]});
        // (The player on foot beside a prop: faded in the draw loop below, not removed.)
        placed.erase(std::remove_if(placed.begin(), placed.end(), [&](const Placed& p) {
                         if (p.model == lamp || p.model == trees[0] || p.model == trees[1] || p.model == trees[2]) return false;
                         for (const auto& d : doors) {
                             const float dx = p.x - d.first, dz = p.z - d.second;
                             if (dx * dx + dz * dz < 1.1f * 1.1f) return true;
                         }
                         return false;
                     }),
                     placed.end());
    }
    if (placed.empty()) { propFootprints_.clear(); return; }
    std::sort(placed.begin(), placed.end(), [](const Placed& a, const Placed& b) { return a.d2 < b.d2; });
    if (placed.size() > static_cast<size_t>(kBudget)) placed.resize(kBudget);
    propFootprints_.clear();
    for (const Placed& p : placed) {
        if (p.model == lamp || p.model == trees[0] || p.model == trees[1] || p.model == trees[2]) continue;
        const float r = (std::min)(0.6f, (std::max)(0.12f, 0.5f * p.scale * (std::max)(p.model->Length(), p.model->Width())));
        propFootprints_.push_back({p.x, p.y, p.z, r, (std::max)(0.3f, p.model->Height() * p.scale)});
    }

    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);   // leaves are cutouts
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetFVF(kWorldFvf);
    // PROPS-SLIM: what the street furniture costs, logged every 300 drawn frames:
    // props in range and drawn per frame, their triangles and draws, by kind.
    static int s_propFrames = 0;
    static double s_inRange = 0, s_drawn = 0, s_tris = 0, s_draws = 0;
    static int s_maxDrawn = 0, s_maxTris = 0;
    static double s_kind[6] = {};   // lamp, bin, bench, hydrant, tree, other
    int frameDrawn = 0, frameTris = 0;
    s_inRange += static_cast<double>(placed.size());
    // Defect pt-player-walks-through-street-lamps: the game does not know these props, so
    // its people and cars pass through them. A small prop (lamp post, bin, bench, hydrant,
    // mailbox, meter, sign) that a person or a car body overlaps fades out, smoothly over
    // the last 0.2 block of approach, and comes back as they move on; and the eye is never
    // inside one: faded fully within 0.2 block of it. Shelters, containers, cranes, rail,
    // roof units and trees stay as they are. GTA2DX9_PROP_OVERLAP_FADE=0 turns it off.
    static int s_overlapFade = -1;
    if (s_overlapFade < 0) {
        char v[8] = {};
        s_overlapFade = (GetEnvironmentVariableA("GTA2DX9_PROP_OVERLAP_FADE", v, sizeof v) && v[0] == '0') ? 0 : 1;
        Log("props: overlap fade %s (people, car bodies and the eye fade the small street props they reach)", s_overlapFade ? "on" : "off");
    }
    struct CarRect { float cx, cz, ax, az, bx, bz, ha, hb; };   // centre, unit axes, half extents
    std::vector<CarRect> carRects;
    if (s_overlapFade) {
        auto addRect = [&](const gta2::Mat4& m, float x0, float x1, float z0, float z1) {
            const float lx = 0.5f * (x0 + x1), lz = 0.5f * (z0 + z1);
            CarRect r;
            r.cx = lx * m.m[0][0] + lz * m.m[2][0] + m.m[3][0];
            r.cz = lx * m.m[0][2] + lz * m.m[2][2] + m.m[3][2];
            const float la = std::hypot(m.m[0][0], m.m[0][2]), lb = std::hypot(m.m[2][0], m.m[2][2]);
            if (la < 1e-5f || lb < 1e-5f) return;
            r.ax = m.m[0][0] / la; r.az = m.m[0][2] / la; r.bx = m.m[2][0] / lb; r.bz = m.m[2][2] / lb;
            r.ha = 0.5f * (x1 - x0) * la; r.hb = 0.5f * (z1 - z0) * lb;
            carRects.push_back(r);
        };
        for (const CarBodyUse& use : carBodies_) {
            float x0 = 1e9f, x1 = -1e9f, z0 = 1e9f, z1 = -1e9f;
            for (const CarBodyVertex& v : use.local) { x0 = (std::min)(x0, v.x); x1 = (std::max)(x1, v.x); z0 = (std::min)(z0, v.z); z1 = (std::max)(z1, v.z); }
            if (x1 > x0) addRect(use.objectToWorld, x0, x1, z0, z1);
        }
        for (const CarModelUse& use : carModels_)
            if (use.model) addRect(use.placement, use.model->boundsMin.x, use.model->boundsMax.x, use.model->boundsMin.z, use.model->boundsMax.z);
    }
    auto smooth01 = [](float t) { t = (std::min)(1.0f, (std::max)(0.0f, t)); return t * t * (3.0f - 2.0f * t); };
    auto overlapAlpha = [&](const Placed& p) -> float {
        if (!s_overlapFade) return 1.0f;
        if (!(p.model == lamp || p.model == bin || p.model == bench || p.model == hydrant || p.model == mailbox ||
              p.model == meter || p.model == signStop || p.model == signOneWay)) return 1.0f;
        const float r = p.model == lamp ? 0.08f
                      : (std::min)(0.6f, (std::max)(0.08f, 0.5f * p.scale * (std::max)(p.model->Length(), p.model->Width())));
        const float top = p.y + p.model->Height() * p.scale;
        float alpha = 1.0f;
        // The eye: never inside, gone within 0.2 block of the prop's rim.
        if (eye.y > p.y - 0.3f && eye.y < top + 0.3f)
            alpha = (std::min)(alpha, smooth01((std::hypot(eye.x - p.x, eye.z - p.z) - r - 0.2f) / 0.3f));
        // People (a figure's body is about 0.15 block across the shoulders' half), the player included.
        auto person = [&](float x, float z) {
            const float d = std::hypot(x - p.x, z - p.z) - r - 0.15f;
            alpha = (std::min)(alpha, smooth01((d + 0.05f) / 0.2f));
        };
        for (const std::vector<FigureSpot>* list : {&g_figuresNow, &g_figuresLast})
            for (const FigureSpot& f : *list) person(f.x, f.z);
        if (g_playerPosValid && std::fabs(g_playerPosY - p.y) < 1.5f) person(g_playerPosX, g_playerPosZ);
        // Car bodies: the distance from the prop to the body's rectangle.
        for (const CarRect& c : carRects) {
            const float vx = p.x - c.cx, vz = p.z - c.cz;
            const float qa = std::fabs(vx * c.ax + vz * c.az) - c.ha, qb = std::fabs(vx * c.bx + vz * c.bz) - c.hb;
            const float out = std::hypot((std::max)(qa, 0.0f), (std::max)(qb, 0.0f)) + (std::min)((std::max)(qa, qb), 0.0f);
            alpha = (std::min)(alpha, smooth01((out - r + 0.05f) / 0.2f));
        }
        return alpha;
    };
    struct FadedProp { const Model* model; gta2::Mat4 m; float alpha; };
    std::vector<FadedProp> faded;
    int hiddenNow = 0;
    for (const Placed& p : placed) {
        const float overlap = overlapAlpha(p);
        if (overlap <= 0.02f) { ++hiddenNow; continue; }
        {
            // Beside the picture (PERF-2): the model's bounding sphere, from its foot point up.
            // Still counted above (budget, footprints), only not drawn.
            const float h = p.model->Height() * p.scale;
            const float r = 0.5f * p.scale * std::sqrt(p.model->Height() * p.model->Height() + p.model->Width() * p.model->Width() +
                                                       p.model->Length() * p.model->Length());
            if (OutsideViewFrustum(p.x, p.y + 0.5f * h, p.z, r + 0.25f)) continue;
        }
        {
            int tris = 0, draws = 0;
            for (const ModelMesh& mm : p.model->meshes) { tris += static_cast<int>(mm.indices.size() / 3); ++draws; }
            ++frameDrawn; frameTris += tris; s_draws += draws;
            const int kind = p.model == lamp ? 0 : p.model == bin ? 1 : p.model == bench ? 2 : p.model == hydrant ? 3
                           : (p.model == trees[0] || p.model == trees[1] || p.model == trees[2]) ? 4 : 5;
            s_kind[kind] += 1.0;
        }
        gta2::Mat4 m;
        const float c = std::cos(p.yaw), sn = std::sin(p.yaw);
        m.m[0][0] = c * p.scale;  m.m[0][2] = -sn * p.scale;
        m.m[1][1] = p.scale;
        m.m[2][0] = sn * p.scale; m.m[2][2] = c * p.scale;
        m.m[3][0] = p.x; m.m[3][1] = p.y - p.model->boundsMin.y * p.scale; m.m[3][2] = p.z; m.m[3][3] = 1.0f;
        if (overlap < 0.98f) { faded.push_back({p.model, m, overlap}); continue; }
        ModelDraw(device, *p.model, m, nullptr, 0.0f);
    }
    if (!faded.empty()) {
        // Last and see-through (texture alpha times the fade), no depth writes, as the
        // map objects' near fade (map_objects.cpp): what stands behind shows through.
        DWORD factor = 0xFFFFFFFF, alphaOp = D3DTOP_SELECTARG1, alphaArg1 = D3DTA_TEXTURE, alphaArg2 = D3DTA_CURRENT;
        DWORD blend = FALSE, test = TRUE, zwrite = TRUE, src = D3DBLEND_ONE, dst = D3DBLEND_ZERO;
        device->GetRenderState(D3DRS_ALPHABLENDENABLE, &blend);
        device->GetRenderState(D3DRS_ALPHATESTENABLE, &test);
        device->GetRenderState(D3DRS_ZWRITEENABLE, &zwrite);
        device->GetRenderState(D3DRS_SRCBLEND, &src);
        device->GetRenderState(D3DRS_DESTBLEND, &dst);
        device->GetRenderState(D3DRS_TEXTUREFACTOR, &factor);
        device->GetTextureStageState(0, D3DTSS_ALPHAOP, &alphaOp);
        device->GetTextureStageState(0, D3DTSS_ALPHAARG1, &alphaArg1);
        device->GetTextureStageState(0, D3DTSS_ALPHAARG2, &alphaArg2);
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
        device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
        device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
        device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
        device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_TFACTOR);
        std::sort(faded.begin(), faded.end(), [](const FadedProp& a, const FadedProp& b) { return a.alpha > b.alpha; });
        for (const FadedProp& f : faded) {
            const DWORD a = static_cast<DWORD>((std::min)(1.0f, (std::max)(0.0f, f.alpha)) * 255.0f + 0.5f);
            device->SetRenderState(D3DRS_TEXTUREFACTOR, (a << 24) | 0x00FFFFFFu);
            ModelDraw(device, *f.model, f.m, nullptr, 0.0f);
        }
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, blend);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, test);
        device->SetRenderState(D3DRS_ZWRITEENABLE, zwrite);
        device->SetRenderState(D3DRS_SRCBLEND, src);
        device->SetRenderState(D3DRS_DESTBLEND, dst);
        device->SetRenderState(D3DRS_TEXTUREFACTOR, factor);
        device->SetTextureStageState(0, D3DTSS_ALPHAOP, alphaOp);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, alphaArg1);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG2, alphaArg2);
    }
    {
        static int s_fadeFrames = 0, s_fadedSum = 0, s_hiddenSum = 0;
        s_fadedSum += static_cast<int>(faded.size()); s_hiddenSum += hiddenNow;
        if (++s_fadeFrames == 300) {
            if (s_fadedSum || s_hiddenSum) Log("props: overlap fade over 300 frames: %d prop-frames see-through, %d hidden", s_fadedSum, s_hiddenSum);
            s_fadeFrames = s_fadedSum = s_hiddenSum = 0;
        }
    }
    s_drawn += frameDrawn; s_tris += frameTris;
    s_maxDrawn = (std::max)(s_maxDrawn, frameDrawn); s_maxTris = (std::max)(s_maxTris, frameTris);
    if (++s_propFrames == 300) {
        const double n = s_propFrames;
        Log("props drawn: per frame %.1f in range, %.1f drawn (max %d), %.0f triangles (max %d), %.1f draws; "
            "drawn by kind lamp %.1f bin %.1f bench %.1f hydrant %.1f tree %.1f other %.1f",
            s_inRange / n, s_drawn / n, s_maxDrawn, s_tris / n, s_maxTris, s_draws / n,
            s_kind[0] / n, s_kind[1] / n, s_kind[2] / n, s_kind[3] / n, s_kind[4] / n, s_kind[5] / n);
        s_propFrames = 0; s_inRange = s_drawn = s_tris = s_draws = 0; s_maxDrawn = s_maxTris = 0;
        for (double& k : s_kind) k = 0;
    }
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
}

void LiveGeometry::BeginFrame() {
    // Pop log: a car body seen this frame that was not seen last frame is a
    // car that came into existence or into the game's window.
    for (const auto& seen : carSeenNow_) {
        bool known = false;
        for (const auto& prev : carSeenPrev_) if (prev.first == seen.first) { known = true; break; }
        if (!known) { ++carPops_; carPopDist_ += seen.second; if (seen.second < 12.0f) ++carPopsNear_; }
    }
    carSeenPrev_.swap(carSeenNow_); carSeenNow_.clear();
    if ((g_carFrame % 900) == 899) {
        Log("car pops: %d new bodies in 900 frames, %d within 12 blocks, mean first-seen distance %.1f blocks",
            carPops_, carPopsNear_, carPops_ ? carPopDist_ / carPops_ : 0.0f);
        if (g_pedPops) {
            Log("ped pops: %d new people in 900 frames (street views), %d of them in the picture, %d of those within 10 blocks, mean first-seen distance %.1f blocks",
                g_pedPops, g_pedPopsInView, g_pedPopsNear, g_pedPopDist / g_pedPops);
        }
        g_pedPops = g_pedPopsInView = g_pedPopsNear = 0;
        g_pedPopDist = 0.0f;
        carPops_ = carPopsNear_ = 0; carPopDist_ = 0.0f;
    }
    carModels_.clear();
    carBodies_.clear();
    g_doorPeds.swap(g_doorPedsNow);
    g_doorPedsNow.clear();
    g_carSeats.swap(g_carSeatsNow);
    g_carSeatsNow.clear();
    if (g_carHd && g_carMaterial && !g_hdPrepStarted) StartHdPrepare();
    sprites_.clear();
    shells_.clear();
    lastObject_ = nullptr;
    stacks_.clear();
    spriteQuads_ = 0;
    effectQuads_ = 0;
    g_lastConform = conform_;
    conform_ = Conform{};
    // This frame's placements become next frame's history.
    tracks_.swap(tracksNext_);
    tracksNext_.clear();
}

const LiveGeometry::Track* LiveGeometry::FindTrack(const void* texture, float x, float z) const {
    const Track* best = nullptr;
    float bestDistance = kTrackRadius * kTrackRadius;
    for (const Track& track : tracks_) {
        // The texture has to match: two sprites can share a spot - a car and its
        // own headlight quad - and easing one toward the other's answer is the
        // pop this is meant to remove, not a smaller one.
        if (track.texture != texture) continue;
        const float dx = track.x - x, dz = track.z - z;
        const float distance = dx * dx + dz * dz;
        if (distance <= bestDistance) {
            bestDistance = distance;
            best = &track;
        }
    }
    return best;
}

// Which layer of a stack this sprite belongs to.
//
// Two quads count as stacked when their centres are within about a third of a
// tile, which is well inside a car and well outside the gap to the next one. The
// search is linear over the sprites already taken this frame, which is tens of
// entries - a car's worth of parts, a few pedestrians - so it costs nothing
// worth indexing away.
//
// Only a sprite that is not much smaller counts as something to stack on. The
// stack is for a car's lights, logo and roof light, which are drawn after the
// body and are its own size or smaller, so they still climb onto it. It is not
// for the burst of exhaust smoke a car puffs out under itself as it pulls away:
// six small particles drawn *before* the body counted as a pile six deep and
// lifted the car by six steps, three times its ride height, which in Remix
// tears its shadow off - and then it eased back down as the smoke died. That
// was the hop when a car starts from standstill, and whatever small thing sat
// under a parked car held it up the same way.
int LiveGeometry::StackLayerFor(float cx, float cz, float area) {
    const float kSameSpot = 0.33f * 0.33f;
    // A quarter of the area: a car's roof light still counts against a car,
    // a smoke puff or a pedestrian does not.
    const float kComparable = 0.25f;
    int layer = 0;
    for (const Stack& s : stacks_) {
        const float dx = s.x - cx, dz = s.z - cz;
        if (dx * dx + dz * dz > kSameSpot || s.layer < layer) continue;
        if (s.area < area * kComparable) continue;
        layer = s.layer + 1;
    }
    // A car with a light and a logo is three deep; anything claiming more than
    // this is sprites that happen to share a spot rather than a real stack, and
    // letting it climb would float them.
    const int kMaxLayers = 6;
    if (layer > kMaxLayers) layer = kMaxLayers;
    stacks_.push_back({cx, cz, area, layer});
    return layer;
}

// The game's world frame is x east, y south, level up. Ours is x east, y up,
// z north, so the row is mirrored exactly the way the static mesh builder
// mirrors it - sharing the sign would put sprites on the wrong side of town.
bool LiveGeometry::ReadCorners(const float* vertices, int corners, const void* texture,
                              uintptr_t shadowBase, Vertex* out) const {
    const TextureRecord* record = static_cast<const TextureRecord*>(texture);
    const float invU = record && record->width ? 1.0f / record->width : 1.0f / 64.0f;
    const float invV = record && record->height ? 1.0f / record->height : 1.0f / 64.0f;

    for (int i = 0; i < corners; ++i) {
        const float* world = reinterpret_cast<const float*>(
            shadowBase + static_cast<uintptr_t>(i + game::kWorldShadowSlots) * game::kVertexStride);
        if (!std::isfinite(world[0]) || !std::isfinite(world[1]) || !std::isfinite(world[2])) {
            ++drops_.notFinite;
            return false;
        }
        if (world[0] < -kWorldMargin || world[0] > gta2::kMapWidth + kWorldMargin ||
            world[1] < -kWorldMargin || world[1] > gta2::kMapHeight + kWorldMargin ||
            world[2] < kMinLevel || world[2] > kMaxLevel) {
            ++drops_.outOfWorld;
            return false;
        }
        out[i].x = world[0];
        out[i].y = world[2];
        out[i].z = static_cast<float>(gta2::kMapHeight) - world[1];
        out[i].u = vertices[i * kGameVertexFloats + kUvU] * invU;
        out[i].v = vertices[i * kGameVertexFloats + kUvV] * invV;
    }

    // A real normal rather than a fixed "up": GTA2 sprites lie flat but the odd
    // block faces are vertical, and Remix uses the normal.
    const Vec e1{out[1].x - out[0].x, out[1].y - out[0].y, out[1].z - out[0].z};
    const Vec e2{out[2].x - out[0].x, out[2].y - out[0].y, out[2].z - out[0].z};
    Vec n = Cross(e1, e2);
    const float length = std::sqrt(n.x * n.x + n.y * n.y + n.z * n.z);
    if (length < 1e-9f) {
        ++drops_.degenerate;  // no area, nothing to draw
        return false;
    }
    n = {n.x / length, n.y / length, n.z / length};
    for (int i = 0; i < corners; ++i) {
        out[i].nx = n.x;
        out[i].ny = n.y;
        out[i].nz = n.z;
    }
    return true;
}

namespace {

// The quad a sprite has always had, rather than the one this frame worked out.
//
// Quantising the measured quad is not quite enough. The corners arrive from the
// game's fixed point through a normalise, so the last mantissa bits move about
// even for a parked car, and a value that happens to sit on a rounding boundary
// dithers between two quantised results - which is precisely the vertex-hash
// churn this whole exercise exists to remove.
//
// So the first quad seen for a sprite is quantised and kept, and every later one
// that is the same shape to within a coarse tolerance is answered with the
// stored copy, bit for bit. A sprite genuinely drawn at a second size gets a
// second entry; the cap is there so that something continuously scaled cannot
// grow this without bound.
struct Shape {
    LiveGeometry::Vertex local[4];
};
std::map<const void*, std::vector<Shape>> g_shapes;
constexpr size_t kMaxShapesPerTexture = 8;

void CanonicalShape(const void* texture, const LiveGeometry::Vertex* measured, int corners,
                    LiveGeometry::Vertex* out) {
    // A 256th of a tile, about 8 mm at GTA2's scale: far above the float noise
    // and far below any real difference in sprite size.
    const float kTolerance = 1.0f / 256.0f;

    std::vector<Shape>& known = g_shapes[texture];
    for (const Shape& shape : known) {
        bool same = true;
        for (int i = 0; i < corners && same; ++i) {
            same = std::fabs(shape.local[i].x - measured[i].x) < kTolerance &&
                   std::fabs(shape.local[i].y - measured[i].y) < kTolerance &&
                   std::fabs(shape.local[i].z - measured[i].z) < kTolerance &&
                   std::fabs(shape.local[i].u - measured[i].u) < kTolerance &&
                   std::fabs(shape.local[i].v - measured[i].v) < kTolerance;
        }
        if (same) {
            memcpy(out, shape.local, sizeof(Shape::local[0]) * corners);
            return;
        }
    }

    Shape shape{};
    auto quantise = [](float value) { return std::floor(value * 4096.0f + 0.5f) / 4096.0f; };
    for (int i = 0; i < corners; ++i) {
        shape.local[i] = measured[i];
        shape.local[i].x = quantise(measured[i].x);
        shape.local[i].y = quantise(measured[i].y);
        shape.local[i].z = quantise(measured[i].z);
    }
    memcpy(out, shape.local, sizeof(Shape::local[0]) * corners);
    if (known.size() < kMaxShapesPerTexture) known.push_back(shape);
}

}  // namespace

void SpriteShapeCounts(int* shapes, int* textures) {
    int total = 0;
    for (const auto& entry : g_shapes) total += static_cast<int>(entry.second.size());
    if (shapes) *shapes = total;
    if (textures) *textures = static_cast<int>(g_shapes.size());
}

// Take the quad apart into a shape and a placement.
//
// The shape is the quad measured in its own frame: origin at its centre, one
// axis along its first edge, one along its normal. A GTA2 sprite is rigid, so
// for a given sprite that measurement is the same numbers wherever it stands and
// however it is turned - which is exactly the property Remix needs to recognise
// it again next frame. The placement is that frame's position in the world, and
// it is what Remix differentiates to get the motion vector.
//
// The measured shape goes through CanonicalShape above, which is what makes it
// bit-identical rather than merely close.
bool LiveGeometry::Place(const Vertex* world, int corners, const Vec3& centre,
                         const Vec3* groundUp, Sprite* out) const {
    // The corners' own centroid, which is what the shape is measured about. It is
    // deliberately not `centre`: the shape has to come out the same numbers
    // wherever the sprite stands, so the placement can never be allowed to leak
    // into it.
    const Vec measured{
        (world[0].x + world[1].x + world[2].x + world[3].x) * 0.25f,
        (world[0].y + world[1].y + world[2].y + world[3].y) * 0.25f,
        (world[0].z + world[1].z + world[2].z + world[3].z) * 0.25f,
    };

    // The quad's own frame: right along its first edge, up along its normal,
    // forward completing the set. Orthonormal by construction, so the matrix is a
    // rotation and a translation and nothing else - normals survive it unchanged
    // and Remix's inverse of it is exact.
    const Vec edge{world[1].x - world[0].x, world[1].y - world[0].y, world[1].z - world[0].z};
    const Vec up{world[0].nx, world[0].ny, world[0].nz};   // ReadCorners already normalised this

    const float edgeLength = std::sqrt(edge.x * edge.x + edge.y * edge.y + edge.z * edge.z);
    if (edgeLength < 1e-6f) {
        ++drops_.degenerate;
        return false;
    }
    const Vec right{edge.x / edgeLength, edge.y / edgeLength, edge.z / edgeLength};
    // Cross(right, up) rather than Cross(up, right): the three axes have to come
    // out right handed or the matrix is a reflection, which flips the winding and
    // has Remix guessing at which way the face points.
    const Vec forward = Cross(right, up);

    Vertex local[4];
    for (int i = 0; i < corners; ++i) {
        const Vec offset{world[i].x - measured.x, world[i].y - measured.y, world[i].z - measured.z};
        local[i].x = offset.x * right.x + offset.y * right.y + offset.z * right.z;
        local[i].y = offset.x * up.x + offset.y * up.y + offset.z * up.z;
        local[i].z = offset.x * forward.x + offset.y * forward.y + offset.z * forward.z;
        // The normal is the frame's own up, so in object space it is exactly that
        // for every sprite - one more thing that cannot drift.
        local[i].nx = 0.0f;
        local[i].ny = 1.0f;
        local[i].nz = 0.0f;
        local[i].u = world[i].u;
        local[i].v = world[i].v;
    }
    CanonicalShape(out->texture, local, corners, out->local);
    out->corners = corners;

    // Now the same frame rotated onto the ground. The shape above was measured
    // against the quad's own up; rotating both axes together is a rigid motion of
    // that frame, so local[] still describes the same sprite - which is precisely
    // why the tilt goes here and not into the vertices.
    Vec rightOut = right;
    Vec upOut = up;
    Vec forwardOut = forward;
    if (groundUp) {
        // The quad's normal can point either way depending on how the game wound
        // it, and the ground normal only ever points up. Matching the sign keeps
        // the frame's handedness, which local[] was built against; taking it
        // straight would mirror every sprite whose quad happened to face down.
        const float sign = up.y >= 0.0f ? 1.0f : -1.0f;
        const Vec ground{groundUp->x * sign, groundUp->y * sign, groundUp->z * sign};
        // The heading, re-squared against the new up. A GTA2 sprite's first edge
        // is horizontal, so this is a small rotation about it and nothing else.
        const float along = right.x * ground.x + right.y * ground.y + right.z * ground.z;
        const Vec projected{right.x - ground.x * along, right.y - ground.y * along,
                            right.z - ground.z * along};
        const float length = std::sqrt(projected.x * projected.x + projected.y * projected.y +
                                       projected.z * projected.z);
        // Only a quad standing on its edge could line up with the ground normal,
        // and there is no heading to recover from one. Those keep their own frame.
        if (length > 1e-4f) {
            rightOut = {projected.x / length, projected.y / length, projected.z / length};
            upOut = ground;
            forwardOut = Cross(rightOut, upOut);
        }
    }

    // D3D9 multiplies row vectors on the left, so the basis goes in the rows and
    // the translation in the last one.
    gta2::Mat4& m = out->objectToWorld;
    m = gta2::Mat4{};
    m.m[0][0] = rightOut.x;   m.m[0][1] = rightOut.y;   m.m[0][2] = rightOut.z;
    m.m[1][0] = upOut.x;      m.m[1][1] = upOut.y;      m.m[1][2] = upOut.z;
    m.m[2][0] = forwardOut.x; m.m[2][1] = forwardOut.y; m.m[2][2] = forwardOut.z;
    m.m[3][0] = centre.x;     m.m[3][1] = centre.y;     m.m[3][2] = centre.z;
    m.m[3][3] = 1.0f;
    return true;
}

void LiveGeometry::AddSprite(unsigned flags, const void* texture, const float* vertices,
                             int corners, bool lamps) {
    if (!texture || !vertices) return;
    // With this flag only vertex 0 is filled in, so the other three shadow slots
    // still hold whatever the previous draw left there.
    if (flags & quad_flags::kExpandFromTexture) {
        ++drops_.expandFlag;
        return;
    }

    // The shadow slots only describe the game's *own* vertex array. FUN_004be060
    // also draws an object's drop shadow from a nudged stack copy of those
    // vertices, and pairing that copy with the unmoved world positions stretched
    // the sprite into a second, wrong polygon - the extra "sprouting" panels on
    // trees. Only the real array can be trusted here.
    if (reinterpret_cast<uintptr_t>(vertices) != game::kSpriteVertexArray) {
        ++drops_.notTheSpriteArray;
        return;
    }

    // A pedestrian blown apart: the limbs are on the ground, so the body is not.
    // See gibs.cpp.
    if (GibsHideCurrentSprite()) return;

    // The player's own sprite, and his car's, from his own eyes: every quad
    // the game draws for them, the lamp quad included. See SetHiddenObjects.
    // ... except his car when the cars are 3D bodies: its flat sprite goes, its
    // body is drawn round him (the eye sits in the cabin; see CarBodiesCabin).
    bool ownCar = false;
    if (g_hiddenObjects[0] || g_hiddenObjects[1]) {
        const void* object = GameObjectBeingDrawn();
        if (object && (object == g_hiddenObjects[0] || object == g_hiddenObjects[1]) && corners == 4 &&
            TextureIsEffect(texture)) {
            // A flame over the player's own car (its sprites are not drawn from his
            // seat): still counted, so the log can say his car is burning.
            Vertex fx[4];
            if (ReadCorners(vertices, corners, texture, game::kSpriteVertexArray, fx)) {
                float cx = 0, cy = 0, cz = 0;
                for (int i = 0; i < 4; ++i) { cx += fx[i].x * 0.25f; cy += fx[i].y * 0.25f; cz += fx[i].z * 0.25f; }
                g_fireSpotsLast.push_back({cx, cy, cz, object});
            }
        }
        if (object && object == g_hiddenObjects[0]) return;
        if (object && object == g_hiddenObjects[1]) {
            if (!(g_groundModels && g_carModels3d) || lamps) return;
            ownCar = true;
        }
    }

    Vertex out[4];
    if (!ReadCorners(vertices, corners, texture, game::kSpriteVertexArray, out)) return;

    // A car's lamps, laid on its body.
    //
    // The game draws them as a second quad with exactly the body's corners - the
    // same vertex array, only the texture coordinates set again (FUN_004B9BC0) -
    // and placed on its own it drifted from the body: a ground fit, a smoothing
    // history and a stack layer of its own, which on a slope or a kerb left the
    // lamps inside the car. So it takes the body's placement outright, shape and
    // transform, and sits a hair above it along the body's own normal, where it
    // cannot end up anywhere but on top.
    if (lamps) {
        const void* object = GameObjectBeingDrawn();
        if (g_ownCarLamps && object && object == lastObject_ && lastSprite_ < sprites_.size()) {
            // Ours instead of the game's. See OwnCarLamps.
            AddCarLamps(sprites_[lastSprite_]);
            return;
        }
        if (object && object == lastObject_ && lastSprite_ < sprites_.size() && corners == 4) {
            Sprite placed = sprites_[lastSprite_];
            placed.hidden = false;
            placed.texture = texture;
            placed.objectModel = nullptr;   // the model stands in for the first quad only
            // The quad's own up can face the ground, depending on how the game
            // wound it; "above" is whichever way its frame's up points in the
            // world.
            const float above = placed.objectToWorld.m[1][1] >= 0.0f ? 1.0f : -1.0f;
            for (int i = 0; i < 4; ++i) {
                placed.local[i].u = out[i].u;
                placed.local[i].v = out[i].v;
                placed.local[i].y += kConformClearance * above;
            }
            sprites_.push_back(placed);
            ++spriteQuads_;
            ++drops_.accepted;
            return;
        }
        // No body this frame to lay them on; placed like any other sprite.
    }

    // Limbs are drawn larger than their artwork. See gibs.cpp.
    const float scale = corners == 4 ? GibsCurrentScale() : 1.0f;
    if (scale != 1.0f) {
        const float mx = (out[0].x + out[1].x + out[2].x + out[3].x) * 0.25f;
        const float mz = (out[0].z + out[1].z + out[2].z + out[3].z) * 0.25f;
        for (int i = 0; i < 4; ++i) {
            out[i].x = mx + (out[i].x - mx) * scale;
            out[i].z = mz + (out[i].z - mz) * scale;
        }
    }

    // Only quads come through here - gbh_DrawQuad and gbh_DrawQuadClipped are the
    // only callers - and Place measures the frame from four corners.
    if (corners != 4) {
        ++drops_.degenerate;
        return;
    }

    // Where the game put the sprite. All four corners carry the single level of
    // the object, so this is that level and the footprint it covers.
    float cx = 0.0f, cy = 0.0f, cz = 0.0f;
    for (int i = 0; i < corners; ++i) {
        cx += out[i].x;
        cy += out[i].y;
        cz += out[i].z;
    }
    const float inv = 1.0f / static_cast<float>(corners);
    cx *= inv;
    cy *= inv;
    cz *= inv;

    // The stack layer is decided from where the sprite sits, before it is
    // lifted, so a car's lights and logo land on the body rather than on each
    // other's raised copies.
    // A quad's corners go round its edge in order, so two adjacent sides give
    // its footprint.
    const float sideAx = out[1].x - out[0].x, sideAz = out[1].z - out[0].z;
    const float sideBx = out[2].x - out[1].x, sideBz = out[2].z - out[1].z;
    const float area = std::sqrt(sideAx * sideAx + sideAz * sideAz) *
                       std::sqrt(sideBx * sideBx + sideBz * sideBz);
    // Skid marks, blood trails and blood pools lie on the road rather than
    // standing on it: no ride height, and none of the clearance a car is given.
    // They still follow the ground's tilt, keep the quarter-texel gap that
    // breaks coplanarity with the road, and stack against each other - but by
    // a sliver per layer, because a trail is dozens of overlapping strips and a
    // car's worth of stack step each piled them into the air.
    const bool decal = IsGroundDecal(texture);
    // A limb or a body lies on the road rather than standing on it like a
    // pedestrian, but it is not flat paint either: a third of a sprite's ride
    // height.
    const bool lying = scale != 1.0f || GameObjectIsCorpse();
    // A limb that has landed goes on the floor, whatever height the game left it
    // at. See GibsCurrentIsResting.
    const bool resting = scale != 1.0f && GibsCurrentIsResting();
    const float stackStep = decal ? kConformClearance * 0.25f : g_spriteStackStep;
    const float stacked = stackStep > 0.0f ? StackLayerFor(cx, cz, area) * stackStep : 0.0f;

    // Stand it on the floor the map says is under it. See the note on
    // g_spriteConform: the quad itself is not touched, only the frame it is
    // placed in.
    Vec3 groundUp{0.0f, 1.0f, 0.0f};
    bool tilted = false;
    float baseY = cy;
    float clearance = g_spriteLift;
    // The real floor under the corners and the middle, kept for the guard after
    // smoothing. A sample with no floor under it is left out.
    float guardX[5], guardZ[5], guardFloor[5];
    int guardSamples = 0;

    // A quad standing on its edge has no floor under it in any useful sense.
    // Nothing on this path should be one, but the guard is a line and the
    // alternative is a sprite laid flat on the road.
    const bool flatQuad = std::fabs(out[0].ny) > 0.5f;
    if (g_spriteConform && ground_ && ground_->Ready() && flatQuad) {
        // The corners plus the middle. A car parked across the ridge where a ramp
        // meets the flat has all four corners low and the crest under its belly,
        // which four samples cannot see at all.
        const float xs[5] = {out[0].x, out[1].x, out[2].x, out[3].x, cx};
        const float zs[5] = {out[0].z, out[1].z, out[2].z, out[3].z, cz};
        const gta2dx9::GroundPlane plane =
            ground_->Fit(xs, zs, corners + 1, cy + GroundSampler::kCeilingHeadroom, cx, cz);
        if (plane.valid) {
            for (int i = 0; i < corners + 1; ++i) {
                float floorHere = 0.0f;
                if (!ground_->SurfaceAt(xs[i], zs[i], cy + GroundSampler::kCeilingHeadroom,
                                        &floorHere)) {
                    continue;
                }
                guardX[guardSamples] = xs[i];
                guardZ[guardSamples] = zs[i];
                guardFloor[guardSamples] = floorHere;
                ++guardSamples;
            }
        }
        if (!plane.valid) {
            ++conform_.noGround;
        } else {
            // A ground decal is paint on the road: whatever height the game gave it (a pool is
            // put where the body fell, at the body's height), it goes down on the surface. Left
            // at the game's height it hung above the asphalt and picked up shadow from the gap.
            const float gap = (resting || decal) ? 0.0f : cy - plane.y;
            if (gap > conform_.maxGap) conform_.maxGap = gap;
            if (plane.residual > conform_.maxResidual) conform_.maxResidual = plane.residual;

            // Never downward: above its floor, the game's own height wins -
            // except for a limb at rest, whose gap is taken as none.
            baseY = gap > 0.0f ? cy : plane.y;

            // The gradient the ground actually has. Working in gradient rather
            // than in the normal keeps every adjustment below a plain scaling of
            // two numbers, and the normal falls out at the end.
            const float rawGx = -plane.nx / plane.ny;
            const float rawGz = -plane.nz / plane.ny;

            // Two reasons to use less of it than all. A footprint that is not one
            // plane has a fit that means little, so a large residual damps the
            // tilt instead of steering it - that is a corner over a kerb, which
            // is exactly the case that used to lift one corner of a car. And a
            // sprite off the ground levels out over the same gap the lift fades
            // across.
            const float trust = 1.0f - Smoothstep(kFitGood, kFitPoor, plane.residual);
            const float fade = 1.0f - Smoothstep(kTiltFadeNear, kTiltFadeFar, gap);
            float gx = rawGx * trust * fade;
            float gz = rawGz * trust * fade;

            // Pitch is kept, roll is damped. The long side of the quad is the
            // sprite's own direction of travel - two blocks against one for a
            // car - so a gradient along it tips the nose, which is what driving
            // up a ramp looks like, and a gradient across it lifts one side,
            // which a car on wheels does not do. See kDefaultSpriteRoll.
            float axisX = out[1].x - out[0].x, axisZ = out[1].z - out[0].z;
            const float sideA = std::sqrt(axisX * axisX + axisZ * axisZ);
            const float otherX = out[2].x - out[1].x, otherZ = out[2].z - out[1].z;
            const float sideB = std::sqrt(otherX * otherX + otherZ * otherZ);
            if (sideB > sideA) {
                axisX = otherX;
                axisZ = otherZ;
            }
            const float axisLength = (std::max)(sideA, sideB);
            if (axisLength > 1e-6f && g_spriteRoll < 1.0f) {
                axisX /= axisLength;
                axisZ /= axisLength;
                const float along = gx * axisX + gz * axisZ;   // the pitch part
                const float acrossX = gx - axisX * along;      // the roll part
                const float acrossZ = gz - axisZ * along;
                gx = axisX * along + acrossX * g_spriteRoll;
                gz = axisZ * along + acrossZ * g_spriteRoll;
            }

            const float slope = std::sqrt(gx * gx + gz * gz);
            if (slope > kMaxTiltTan) {
                const float scale = kMaxTiltTan / slope;
                gx *= scale;
                gz *= scale;
                ++conform_.capped;
            }
            if (slope > 1e-6f) {
                const float inv = 1.0f / std::sqrt(gx * gx + 1.0f + gz * gz);
                groundUp = {-gx * inv, inv, -gz * inv};
                tilted = true;
            }

            // Clearance is measured against the tilt the sprite actually ended up
            // with, not the one the ground has - so everything given away above,
            // to the roll damping, the trust and the cap, comes back here as
            // height instead of as a sprite cutting into the road.
            float needed = 0.0f;
            if (gap > kConformClearance) {
                // The game has it above the plane fitted under it, and that
                // plane is then not the floor. The case is a car on the upper
                // of two floors with part of its footprint over the lower one -
                // a kerb, a block edge: the fit runs a slope between the two,
                // and its residual measures the step, not anything under the
                // car. Adding that back as clearance floated the car by up to
                // half a block, and eased it up over a few frames as it started
                // to move onto an edge - the hop - or held it up while it stood
                // there and dropped it as it drove off.
                //
                // The samples themselves say what is actually under it: clear
                // whatever real floor rises above the quad, and nothing else.
                // The lower floor it overhangs contributes nothing, and the one
                // it stands on only what its own tilt dips into.
                const float ceiling = cy + GroundSampler::kCeilingHeadroom;
                for (int i = 0; i < corners + 1; ++i) {
                    float floorHere = 0.0f;
                    if (!ground_->SurfaceAt(xs[i], zs[i], ceiling, &floorHere)) continue;
                    const float quadHere = baseY + gx * (xs[i] - cx) + gz * (zs[i] - cz);
                    if (floorHere - quadHere > needed) needed = floorHere - quadHere;
                }
            } else {
                // On the fitted floor. The residual is how far the highest sample
                // pokes above the plane, so the quad has to clear that plus
                // whatever the plane itself rises above the quad at a corner -
                // which is where the gap between two flat things is widest.
                float worst = 0.0f;
                for (int i = 0; i < corners; ++i) {
                    const float dx = out[i].x - cx;
                    const float dz = out[i].z - cz;
                    const float floorHere = plane.y + rawGx * dx + rawGz * dz;
                    const float quadHere = baseY + gx * dx + gz * dz;
                    if (floorHere - quadHere > worst) worst = floorHere - quadHere;
                }
                needed = worst + plane.residual;
            }
            const float owed = (needed - g_spriteHeight * groundUp.y) / groundUp.y;
            const float extra = owed > 0.0f ? (std::min)(owed, kMaxExtraClearance) : 0.0f;
            clearance = kConformClearance + extra;
            if (needed > kConformClearance) ++conform_.straddled;
            if (fade < 1.0f) {
                ++conform_.airborne;
            } else {
                ++conform_.grounded;
            }
        }
    }

    // Ease toward this frame's answer rather than snapping to it. Only the lift
    // and the tilt are smoothed: baseY follows the ground directly, because a car
    // driving up a ramp *should* rise with it and lagging that would be the
    // strange movement rather than the fix for it. See the Track note.
    float offset = decal  ? kConformClearance + stacked
                 : lying  ? kConformClearance + g_spriteHeight * 0.33f + stacked
                          : g_spriteHeight + clearance + stacked;
    if (const Track* previous = FindTrack(texture, cx, cz)) {
        offset = previous->offset + (offset - previous->offset) * kSmoothing;
        Vec3 eased{previous->nx + (groundUp.x - previous->nx) * kSmoothing,
                   previous->ny + (groundUp.y - previous->ny) * kSmoothing,
                   previous->nz + (groundUp.z - previous->nz) * kSmoothing};
        const float length =
            std::sqrt(eased.x * eased.x + eased.y * eased.y + eased.z * eased.z);
        if (length > 1e-6f) {
            groundUp = {eased.x / length, eased.y / length, eased.z / length};
            tilted = std::fabs(groundUp.x) > 1e-5f || std::fabs(groundUp.z) > 1e-5f;
        }
    }

    // The floor guard, after the smoothing and against what is actually drawn.
    //
    // Clearance above is worked out for the tilt and height the sprite is
    // heading for, but both are then eased there over a few frames. Driving onto
    // a ramp that lag is the clip: the target tips the nose up and adds the
    // clearance the kink needs, the eased sprite is still nearly level and
    // nearly as low, and for a few frames the front corner is inside the slope.
    // So measure the real floor at the corners and the middle against the tilt
    // this frame really has, and if any of them would be under it, raise the
    // sprite to just clear it - now, not eased. Only ever up, and only as far as
    // the floor demands, so nothing already clear moves: easing still decides
    // everything else, and lowering stays smooth.
    if (guardSamples > 0 && groundUp.y > 1e-3f) {
        const float gx = -groundUp.x / groundUp.y;
        const float gz = -groundUp.z / groundUp.y;
        float least = offset;
        for (int i = 0; i < guardSamples; ++i) {
            const float under = baseY + gx * (guardX[i] - cx) + gz * (guardZ[i] - cz);
            const float need = (guardFloor[i] + kConformClearance - under) / groundUp.y;
            if (need > least) least = need;
        }
        offset = least;
    }
    tracksNext_.push_back({texture, cx, cz, offset, groundUp.x, groundUp.y, groundUp.z});

    // Along the ground normal rather than straight up: on a ramp those are not
    // the same direction, and clearance measured the wrong way is not clearance.
    // The ride height goes the same way, so a car on a ramp rides above the ramp
    // rather than leaning out of it.
    const Vec3 centre{cx + groundUp.x * offset, baseY + groundUp.y * offset,
                      cz + groundUp.z * offset};

    Sprite placed;
    placed.texture = texture;
    if (!Place(out, corners, centre, tilted ? &groundUp : nullptr, &placed)) return;

    // Which game object this is, written into the quad itself.
    //
    // Every sprite of one texture and size used to be the very same geometry, so
    // to Remix two pedestrians on the same animation frame, or two phone boxes,
    // were one mesh drawn twice. It tells those instances apart from frame to
    // frame by position alone (InstanceManager::findSimilarInstance: an exact
    // transform, else the nearest unclaimed instance of that mesh), and a
    // transform that moves by so much as a stack step loses the exact match. The
    // nearest one is then sometimes the other object, which hands this sprite
    // that object's history - its previous position and its motion - and the
    // denoiser and DLSS draw it where the other one was. That is the copy in the
    // wrong place.
    //
    // The game's sprite object is the identity: the same object every frame for
    // as long as the thing exists, and no two live things share one. A few low
    // bits of it become an offset along the quad's normal of at most 6e-5 tiles -
    // a quarter of a millimetre - which no one can see and which makes each
    // object's quad a mesh of its own, so there is nothing left to confuse.
    if (const void* object = GameObjectBeingDrawn()) {
        const uint32_t bits = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(object) >> 2);
        const float nudge = static_cast<float>(bits & 0xFFFF) * (1.0f / 1073741824.0f);
        for (int i = 0; i < placed.corners; ++i) placed.local[i].y += nudge;
    }
    placed.plain = GameObjectIsPowerUp();
    placed.object = reinterpret_cast<uintptr_t>(GameObjectBeingDrawn());
    // A pedestrian lying on the road, dead or knocked down: see the car loop in Draw.
    placed.corpse = GameObjectIsCorpse();
    if (g_logPedFrames) GTA2_TRY {
        // Which sprite base and number does the game draw a dead or knocked-down
        // pedestrian's body with? (It leaves the ped base after a few frames.)
        // Guarded: a sprite of another base has no ped behind its owner, and the
        // word read as one can be any address (a fire truck's water spray read
        // 0x00220000 and took the game down, POLICE-3D run pol_veh1).
        if (const uint8_t* object = static_cast<const uint8_t*>(GameObjectBeingDrawn())) {
            const int32_t base = *reinterpret_cast<const int32_t*>(object + game::kSpriteObjectBase);
            const uint8_t* physics = *reinterpret_cast<const uint8_t* const*>(object + game::kSpriteObjectOwner);
            const uint8_t* ped = game::PlausiblePointer(physics)
                                     ? *reinterpret_cast<const uint8_t* const*>(physics + game::kPhysicsPed)
                                     : nullptr;
            if (base == game::kSpriteBasePed && (lying || !game::PlausiblePointer(ped))) {
                // A ped-base sprite that is not a pedestrian on his feet with a ped behind it.
                static std::map<uintptr_t, int> seen2;
                const unsigned num = *reinterpret_cast<const uint16_t*>(object + game::kSpriteObjectNumber);
                const int key = static_cast<int>(num) * 4 + (lying ? 2 : 0) + (game::PlausiblePointer(ped) ? 1 : 0);
                if (seen2[reinterpret_cast<uintptr_t>(object)] != key) {
                    seen2[reinterpret_cast<uintptr_t>(object)] = key;
                    Log("ped anim: ped-base sprite %p number %u (%u) lying %d scale %.2f corners %d ped %p corpse %d",
                        static_cast<const void*>(object), num, num % 158u, lying ? 1 : 0, scale, corners,
                        static_cast<const void*>(ped), placed.corpse ? 1 : 0);
                }
            }
            if (base != game::kSpriteBasePed && game::PlausiblePointer(ped)) {
                const int32_t st = *reinterpret_cast<const int32_t*>(ped + game::kPedState);
                const int32_t sub = *reinterpret_cast<const int32_t*>(ped + game::kPedSubState);
                if (st == 9 || st == 8) {
                    static std::map<uintptr_t, int> seen;
                    const unsigned num = *reinterpret_cast<const uint16_t*>(object + game::kSpriteObjectNumber);
                    const int key = base * 100000 + static_cast<int>(num);
                    if (seen[reinterpret_cast<uintptr_t>(object)] != key) {
                        seen[reinterpret_cast<uintptr_t>(object)] = key;
                        Log("ped anim: body object %p base %d number %u state %d sub 0x%x scale %.2f corners %d",
                            static_cast<const void*>(object), base, num, st, sub, scale, corners);
                    }
                }
            }
        }    } GTA2_EXCEPT {
    }
    if (const uint8_t* object = static_cast<const uint8_t*>(GameObjectBeingDrawn())) {
        placed.pedestrian = !lying && *reinterpret_cast<const int32_t*>(object + game::kSpriteObjectBase) ==
                                         game::kSpriteBasePed;
        if (*reinterpret_cast<const int32_t*>(object + game::kSpriteObjectBase) == game::kSpriteBasePed) {
            // His frame and state words, on his feet or on the ground, for the figure's clips.
            placed.pedFrame = *reinterpret_cast<const uint16_t*>(object + game::kSpriteObjectNumber);
            const uint8_t* physics = *reinterpret_cast<const uint8_t* const*>(object + game::kSpriteObjectOwner);
            const uint8_t* ped = game::PlausiblePointer(physics)
                                     ? *reinterpret_cast<const uint8_t* const*>(physics + game::kPhysicsPed)
                                     : nullptr;
            if (game::PlausiblePointer(ped)) {
                placed.pedState = *reinterpret_cast<const int32_t*>(ped + game::kPedState);
                placed.pedSub = *reinterpret_cast<const int32_t*>(ped + game::kPedSubState);
                placed.pedPending = *reinterpret_cast<const int32_t*>(ped + game::kPedStatePending);
                placed.pedCause = *reinterpret_cast<const int32_t*>(ped + game::kPedDamageCause);
                placed.pedHealth = *reinterpret_cast<const int16_t*>(ped + kPedHealthWord);
                {
                    const uint8_t* wobj = *reinterpret_cast<const uint8_t* const*>(ped + game::kPedCurrentWeapon);
                    if (game::PlausiblePointer(wobj)) {
                        placed.pedAmmo = *reinterpret_cast<const int16_t*>(wobj + game::kWeaponAmmo);
                        placed.pedReload = *reinterpret_cast<const int16_t*>(wobj + 2);
                        placed.pedWeaponObject = reinterpret_cast<uintptr_t>(wobj);
                    }
                }
                g_pedWeaponByObject[reinterpret_cast<uintptr_t>(object)] = game::PedWeaponOf(ped);
                if ((placed.pedState == 3 || placed.pedState == 4) && g_doorPedsNow.size() < 32) {
                    // The ped's vehicle word is only set once he is inside, so the car
                    // he is boarding is matched by position when the cars are collected.
                    const uint8_t* vehicle = *reinterpret_cast<const uint8_t* const*>(ped + game::kPedVehicle);
                    g_doorPedsNow.push_back({game::PlausiblePointer(vehicle) ? reinterpret_cast<uintptr_t>(vehicle) : 0,
                                             placed.objectToWorld.m[3][0], placed.objectToWorld.m[3][2], placed.pedState});
                }
                if (g_logPedFrames && reinterpret_cast<const void*>(object) == g_playerObject) {
                    static unsigned lastFrame = 9999; static int32_t lastState = -2, lastSub = -2;
                    if (placed.pedFrame != lastFrame || placed.pedState != lastState || placed.pedSub != lastSub) {
                        lastFrame = placed.pedFrame; lastState = placed.pedState; lastSub = placed.pedSub;
                        Log("ped anim: player frame %u (%u) state %d sub 0x%x pending %d%s", placed.pedFrame,
                            placed.pedFrame % 158u, placed.pedState, placed.pedSub, placed.pedPending,
                            placed.corpse ? " corpse" : "");
                    }
                }
            }
        }
        if (placed.pedestrian) {
            // Frames 182-193 of a pedestrian are the climb into a car, 24-35 the climb out of one (read off the
            // player's own log: the game gives him no vehicle until the very end of it, so the
            // vehicle test alone misses most of the animation).
            const unsigned climbFrame = *reinterpret_cast<const uint16_t*>(object + game::kSpriteObjectNumber);
            placed.climbing = (climbFrame >= 182 && climbFrame <= 193) || (climbFrame >= 24 && climbFrame <= 35);
            const uint8_t* physics = *reinterpret_cast<const uint8_t* const*>(object + game::kSpriteObjectOwner);
            const uint8_t* ped = game::PlausiblePointer(physics)
                                     ? *reinterpret_cast<const uint8_t* const*>(physics + game::kPhysicsPed)
                                     : nullptr;
            if (game::PlausiblePointer(ped)) {
                const uint8_t* vehicle = *reinterpret_cast<const uint8_t* const*>(ped + game::kPedVehicle);
                const uintptr_t key = reinterpret_cast<uintptr_t>(ped);
                placed.inVehicleNow = game::PlausiblePointer(vehicle);
                if (game::PlausiblePointer(vehicle)) g_pedWithCar[key] = g_carFrame;
                const auto seen = g_pedWithCar.find(key);
                placed.recentlyInCar = seen != g_pedWithCar.end() && g_carFrame - seen->second < 60;
                // Which style sprites does the player's own pedestrian walk through? The
                // camera follows him, so the pedestrian standing at its centre on foot is
                // him. Each new frame number is logged once: that is the list of art an HD
                // character has to cover.
                {
                    float camX = 0.0f, camY = 0.0f;
                    if (game::CameraPosition(&camX, &camY)) {
                        const float dx = *reinterpret_cast<const int32_t*>(ped + game::kPedX) * game::kFixedScale - camX;
                        const float dy = *reinterpret_cast<const int32_t*>(ped + game::kPedY) * game::kFixedScale - camY;
                        // The chase view's last resort for finding the player: see LocatePlayer.
                        if (!placed.inVehicleNow) NotePedNearCamera(ped, std::sqrt(dx * dx + dy * dy));
                        if (dx * dx + dy * dy < 0.25f) {
                            // [0] on foot, [1] with a vehicle of his own: climbing in or out.
                            static bool seenFrame[2][1024] = {};
                            const unsigned frame = *reinterpret_cast<const uint16_t*>(object + game::kSpriteObjectNumber);
                            const int withCar = placed.inVehicleNow ? 1 : 0;
                            if (frame < 1024 && !seenFrame[withCar][frame]) {
                                seenFrame[withCar][frame] = true;
                                Log("player ped frame %u (style sprite %u), %s, %.2f tiles from camera centre", frame,
                                    frame + 77u, withCar ? "getting in/out" : "on foot", std::sqrt(dx * dx + dy * dy));
                            }
                        }
                    }
                }
                if (g_pedWithCar.size() > 128) {
                    for (auto it = g_pedWithCar.begin(); it != g_pedWithCar.end();) {
                        it = (g_carFrame - it->second > 600) ? g_pedWithCar.erase(it) : std::next(it);
                    }
                }
            }
        }
    }
    if (g_carBodies && !decal && corners == 4) RaiseCarBody(&placed);
    // The own car only ever as its body: if it did not become one, nothing.
    if (ownCar && !placed.hidden) return;
    // The game's objects - cones, bins, phone boxes - as models in the street-level views.
    if (!decal && !lying && corners == 4 && !placed.pedestrian && !placed.hidden && !placed.plain &&
        !placed.lamp && !placed.corpse) {
        const Model* model = MapObjectModel(GameObjectBeingDrawn(), placed.local, corners, placed.objectToWorld);
        if (model && g_groundModels) {
            placed.objectModel = model;
            placed.hidden = true;   // the flat sprite goes; the model stands in for it
        }
    }
    // Small flat artwork that is neither a car nor a pedestrian: see SetSpriteSmooth.
    if (g_spriteSmooth && !decal && !lying && corners == 4) {
        const uint8_t* object = static_cast<const uint8_t*>(GameObjectBeingDrawn());
        const int32_t base = object ? *reinterpret_cast<const int32_t*>(object + game::kSpriteObjectBase) : -1;
        placed.smooth = base != game::kSpriteBaseCar && base != game::kSpriteBasePed;
    }
    lastObject_ = GameObjectBeingDrawn();
    lastSprite_ = sprites_.size();
    sprites_.push_back(placed);
    ++spriteQuads_;
    ++drops_.accepted;

    // The game's own corner positions, straight out of the shadow slots and
    // before our axis swap, so the question "does GTA2 lift a sprite off the
    // floor it stands on?" can be answered from its numbers rather than ours.
    if (spriteLogs_ < 8) {
        ++spriteLogs_;
        char line[320];
        int used = snprintf(line, sizeof(line), "sprite corners (game frame x,y,level):");
        for (int i = 0; i < corners && used > 0 && used < static_cast<int>(sizeof(line)) - 40; ++i) {
            const float* world = reinterpret_cast<const float*>(
                game::kSpriteVertexArray +
                static_cast<uintptr_t>(i + game::kWorldShadowSlots) * game::kVertexStride);
            used += snprintf(line + used, sizeof(line) - used, "  (%.4f %.4f %.4f)", world[0],
                             world[1], world[2]);
        }
        Log("%s", line);
    }
}

// How tall a car's dome stands along the car's length, as a fraction of the full
// CarBodyHeight. `b` runs from 0 at the rear (the top of the sprite) to 1 at the
// front. Most cars are one even hump, so 1. A truck cab is not: behind the cab the
// frame, fifth wheel and engine bay sit far lower than the cab roof, which is what
// the trailer couples onto. Sprites 57 and 58 are those cabs. The rear stays at
// `low` of the cab's height up to `lowEnd`, then climbs over the cab's back wall to
// full height by `riseEnd`.
static float CarDomeProfile(int sprite, float b) {
    // A burnt-out wreck has fallen in on itself: it stands well below the car it was.
    if (IsWreckSprite(sprite)) return 0.5f;
    struct Step { int sprite; float lowEnd, riseEnd, low; };
    static const Step kSteps[] = {{57, 0.30f, 0.42f, 0.22f}, {58, 0.30f, 0.42f, 0.22f}};
    for (const Step& s : kSteps) {
        if (s.sprite != sprite) continue;
        float t = (b - s.lowEnd) / (s.riseEnd - s.lowEnd);
        t = (std::max)(0.0f, (std::min)(1.0f, t));
        t = t * t * (3.0f - 2.0f * t);
        return s.low + (1.0f - s.low) * t;
    }
    return 1.0f;
}

// A car's four tyres. See SetCarWheels.
//
// The sprite quad's own frame: x along its first edge, z across, y along the normal.
// The car's length runs along whichever edge the texture's v changes along fastest, and
// its front is where v is larger (the sprites are drawn nose-down).
void LiveGeometry::BuildCarTyres(const Sprite& body, CarShell* shell, const void* objectPtr,
                                 float peak) {
    if (!g_carWheels) return;
    const Vertex* c = body.local;
    const float ax = c[1].x - c[0].x, az = c[1].z - c[0].z;
    const float bx = c[3].x - c[0].x, bz = c[3].z - c[0].z;
    const float lenA = std::sqrt(ax * ax + az * az), lenB = std::sqrt(bx * bx + bz * bz);
    if (lenA < 1e-4f || lenB < 1e-4f) return;
    const float dvA = c[1].v - c[0].v, dvB = c[3].v - c[0].v;
    const float duA = c[1].u - c[0].u, duB = c[3].u - c[0].u;
    const bool lengthIsB = std::fabs(dvB) >= std::fabs(dvA);
    const float L = lengthIsB ? lenB : lenA;       // the quad's length and width, in tiles
    const float W = lengthIsB ? lenA : lenB;
    const float dvLen = lengthIsB ? dvB : dvA;     // v along the length, u along the width
    const float duWid = lengthIsB ? duA : duB;
    if (std::fabs(dvLen) < 1e-6f || std::fabs(duWid) < 1e-6f) return;
    float fx = lengthIsB ? bx / lenB : ax / lenA;
    float fz = lengthIsB ? bz / lenB : az / lenA;
    if (dvLen < 0.0f) { fx = -fx; fz = -fz; }   // toward larger v: the nose
    // Across the car: the local plane's quarter turn from the nose.
    const float px = -fz, pz = fx;
    const float cx0 = 0.25f * (c[0].x + c[1].x + c[2].x + c[3].x);
    const float cz0 = 0.25f * (c[0].z + c[1].z + c[2].z + c[3].z);
    const float above = peak >= 0.0f ? 1.0f : -1.0f;

    // Where the car really is inside its quad. The sprite is a nearly square picture with
    // the car in the middle of it, so the quad's edges are nowhere near the body's: the
    // tyres go by the artwork's own opaque extent.
    float noseDist = 0.5f * L, tailDist = -0.5f * L, leftLat = -0.5f * W, rightLat = 0.5f * W;
    {
        int x0, x1, y0, y1, tw, th;
        bool have = SpriteOpaqueBounds(body.texture, &x0, &x1, &y0, &y1, &tw, &th) && x1 > x0 && y1 > y0;
        if (have) {
            // An open door (or a car thrown open as someone gets in) sticks out of the body,
            // and the tyres must not follow it. So the body is the most inward box seen over the
            // first sightings of this sprite - a door is only open for a moment - then frozen.
            struct Seen { int count = 0, x0 = 0, x1 = 0, y0 = 0, y1 = 0, w = 0, h = 0; };
            static std::map<int, Seen> seen;
            Seen& s = seen[shell->sprite];
            if (s.count == 0 || s.w != tw || s.h != th) {
                s = Seen{1, x0, x1, y0, y1, tw, th};
            } else if (s.count < 40) {
                s.x0 = (std::max)(s.x0, x0);
                s.x1 = (std::min)(s.x1, x1);
                s.y0 = (std::max)(s.y0, y0);
                s.y1 = (std::min)(s.y1, y1);
                ++s.count;
            }
            if (s.x1 > s.x0 && s.y1 > s.y0) { x0 = s.x0; x1 = s.x1; y0 = s.y0; y1 = s.y1; }
        }
        if (have) {
            const float uLo = static_cast<float>(x0) / tw, uHi = static_cast<float>(x1) / tw;
            const float vLo = static_cast<float>(y0) / th, vHi = static_cast<float>(y1) / th;
            const float vMid = 0.25f * (c[0].v + c[1].v + c[2].v + c[3].v);
            const float uMid = 0.25f * (c[0].u + c[1].u + c[2].u + c[3].u);
            // Distance from the quad's middle along the nose, per unit of v.
            const float perV = L / std::fabs(dvLen);
            noseDist = (vHi - vMid) * perV;
            tailDist = (vLo - vMid) * perV;
            // Across the car, sign by whether u grows toward px,pz.
            const float wex = lengthIsB ? ax : bx, wez = lengthIsB ? az : bz;
            const float wsign = ((px * wex + pz * wez) * duWid) >= 0.0f ? 1.0f : -1.0f;
            const float perU = W / std::fabs(duWid);
            const float a0 = wsign * (uLo - uMid) * perU, a1 = wsign * (uHi - uMid) * perU;
            leftLat = (std::min)(a0, a1);
            rightLat = (std::max)(a0, a1);
        }
    }
    const float bodyLength = noseDist - tailDist;
    const float bodyWidth = rightLat - leftLat;
    if (bodyLength < 1e-3f || bodyWidth < 1e-3f) return;
    const float latMid = 0.5f * (leftLat + rightLat);

    // Size and place, as fractions of the body itself.
    const float tyreLength = 0.17f * bodyLength, tyreWidth = 0.12f * bodyWidth;
    const float height = std::fabs(peak) * 0.42f;
    const float frontAxle = noseDist - g_wheelAxleInset * bodyLength;
    const float rearAxle = tailDist + g_wheelAxleInset * bodyLength;
    const float side = g_wheelSide * bodyWidth;
    const float wheelbase = frontAxle - rearAxle;

    // The tyre: a box with sloped sides, centred on its own origin.
    const float hl = tyreLength * 0.5f, hw = tyreWidth * 0.5f;
    const float tl = hl * 0.88f, tw = hw * 0.80f;
    const float ring[4][2] = {{1, -1}, {1, 1}, {-1, 1}, {-1, -1}};
    LiveGeometry::Vertex bottom[4], top[4];
    for (int k = 0; k < 4; ++k) {
        bottom[k] = {};
        top[k] = {};
        bottom[k].x = fx * (ring[k][0] * hl) + px * (ring[k][1] * hw);
        bottom[k].z = fz * (ring[k][0] * hl) + pz * (ring[k][1] * hw);
        bottom[k].y = 0.0f;
        top[k].x = fx * (ring[k][0] * tl) + px * (ring[k][1] * tw);
        top[k].z = fz * (ring[k][0] * tl) + pz * (ring[k][1] * tw);
        top[k].y = height * above;
    }
    int n = 0;
    auto put = [&](const LiveGeometry::Vertex& v, float nx, float ny, float nz) {
        LiveGeometry::Vertex out = v;
        out.nx = nx; out.ny = ny; out.nz = nz;
        out.u = 0.5f; out.v = 0.5f;
        shell->tyreMesh[n++] = out;
    };
    for (int k = 0; k < 4; ++k) {
        const int j = (k + 1) & 3;
        const LiveGeometry::Vertex& b0 = bottom[k];
        const LiveGeometry::Vertex& b1 = bottom[j];
        const LiveGeometry::Vertex& t0 = top[k];
        const float e1x = b1.x - b0.x, e1y = b1.y - b0.y, e1z = b1.z - b0.z;
        const float e2x = t0.x - b0.x, e2y = t0.y - b0.y, e2z = t0.z - b0.z;
        float nx = e1y * e2z - e1z * e2y, ny = e1z * e2x - e1x * e2z, nz = e1x * e2y - e1y * e2x;
        const float len = std::sqrt(nx * nx + ny * ny + nz * nz);
        if (len > 1e-9f) { nx /= len; ny /= len; nz /= len; }
        // Away from the tyre's middle.
        if (nx * (b0.x + b1.x) + nz * (b0.z + b1.z) < 0.0f) { nx = -nx; ny = -ny; nz = -nz; }
        put(bottom[k], nx, ny, nz);
        put(bottom[j], nx, ny, nz);
        put(top[j], nx, ny, nz);
        put(top[k], nx, ny, nz);
    }
    for (int k = 0; k < 4; ++k) put(top[k], 0.0f, above, 0.0f);

    // Steering, from how the car's placement changed since it was last seen.
    const gta2::Mat4& o = body.objectToWorld;
    const uintptr_t key = reinterpret_cast<uintptr_t>(objectPtr);
    // The nose in the world: the local direction through the car's rotation.
    float wfx = fx * o.m[0][0] + fz * o.m[2][0];
    float wfz = fx * o.m[0][2] + fz * o.m[2][2];
    const float wlen = std::sqrt(wfx * wfx + wfz * wfz);
    float steer = 0.0f;
    float sideSign = 1.0f;   // whether the local quarter turn px,pz is a turn toward more yaw
    if (wlen > 1e-6f) {
        wfx /= wlen;
        wfz /= wlen;
        const float wpx = px * o.m[0][0] + pz * o.m[2][0];
        const float wpz = px * o.m[0][2] + pz * o.m[2][2];
        sideSign = (wpx * (-wfz) + wpz * wfx) >= 0.0f ? 1.0f : -1.0f;
        const float x = o.m[3][0], z = o.m[3][2];
        const float yaw = std::atan2(wfz, wfx);
        SteerState& st = g_steer[key];
        if (g_carFrame - st.frame > 30) {
            st = SteerState{};
            st.x = x; st.z = z; st.yaw = yaw; st.frame = g_carFrame;
        } else if (st.frame != g_carFrame) {
            const float ds = (x - st.x) * wfx + (z - st.z) * wfz;
            const float dyaw = WrapAngle(yaw - st.yaw);
            float target = st.angle * 0.92f;   // standing still: the wheels stay as they were, easing home
            if (std::fabs(ds) > 0.004f && std::fabs(ds) < 1.0f) {
                target = std::atan(wheelbase * dyaw / ds);
                target = (std::max)(-g_wheelMaxAngle, (std::min)(g_wheelMaxAngle, target));
            }
            st.angle += (target - st.angle) * 0.30f;
            st.x = x; st.z = z; st.yaw = yaw; st.frame = g_carFrame;
        }
        steer = st.angle;
        if (g_steer.size() > 256) {
            for (auto it = g_steer.begin(); it != g_steer.end();) {
                it = (g_carFrame - it->second.frame > 600) ? g_steer.erase(it) : std::next(it);
            }
        }
    }

    // The tyres' own matrices, in the car's local frame and then through its placement.
    auto place = [&](float along, float across, float angle) {
        gta2::Mat4 m;
        // Local rotation about the quad's normal; positive moves the nose toward the side
        // the world calls more yaw.
        const float phi = angle * sideSign;
        const float cs = std::cos(phi), sn = std::sin(phi);
        gta2::Mat4 local;
        local.m[0][0] = cs;  local.m[0][2] = sn;
        local.m[2][0] = -sn; local.m[2][2] = cs;
        local.m[1][1] = 1.0f;
        local.m[3][0] = cx0 + fx * along + px * across;
        local.m[3][1] = 0.0f;
        local.m[3][2] = cz0 + fz * along + pz * across;
        local.m[3][3] = 1.0f;
        for (int r = 0; r < 4; ++r) {
            for (int col = 0; col < 4; ++col) {
                float sum = 0.0f;
                for (int k = 0; k < 4; ++k) sum += local.m[r][k] * o.m[k][col];
                m.m[r][col] = sum;
            }
        }
        return m;
    };
    shell->tyres.clear();
    const float frontSide = side + g_wheelFrontExtra * bodyWidth;
    shell->tyres.push_back(place(frontAxle, latMid - frontSide, steer));
    shell->tyres.push_back(place(frontAxle, latMid + frontSide, steer));
    shell->tyres.push_back(place(rearAxle, latMid - side, 0.0f));
    shell->tyres.push_back(place(rearAxle, latMid + side, 0.0f));
}

// A car's dome. See CarShell.
//
// Local space is the sprite's own: x along its first edge, z across, y along the
// normal. `above` is which way y points in the world, as for the lamps. The body
// quad itself is left exactly as it was, flat on the ground, underneath.
void LiveGeometry::RaiseCarBody(Sprite* body) {
    if (!body || body->corners != 4 || body->lamp) return;
    const uint8_t* object = static_cast<const uint8_t*>(GameObjectBeingDrawn());
    if (!object || !game::PlausiblePointer(object)) return;
    if (*reinterpret_cast<const int32_t*>(object + game::kSpriteObjectBase) != game::kSpriteBaseCar) {
        return;
    }
    if (g_carBodyHeight < 1e-4f) return;

    if (g_groundModels && g_carModels3d) {
        const int sprite = static_cast<int>(*reinterpret_cast<const uint16_t*>(object + game::kSpriteObjectNumber));
        // A hand-picked model when the manifest names one for this sprite; otherwise
        // a body built from the sprite itself, so the car stays the car the game drew.
        {
            const float sx = body->objectToWorld.m[3][0] - lastEye_.x, sz = body->objectToWorld.m[3][2] - lastEye_.z;
            carSeenNow_.push_back({reinterpret_cast<uintptr_t>(object), std::sqrt(sx * sx + sz * sz)});
            // QB-14: where it is and whether anyone is at the wheel (a ped boarding it is a jack).
            const uint8_t* seatCar = *reinterpret_cast<const uint8_t* const*>(object + game::kSpriteObjectOwner);
            if (g_carSeatsNow.size() < 256 && game::PlausiblePointer(seatCar))
                g_carSeatsNow.push_back({body->objectToWorld.m[3][0], body->objectToWorld.m[3][2], game::VehicleHasDriver(seatCar)});
        }
        if (const Model* model = ModelForCar(sprite)) {
            carModels_.push_back({model, FitModel(*model, body->local, body->corners, body->objectToWorld, 0.0f),
                                  reinterpret_cast<uintptr_t>(object)});
            body->hidden = true;
            return;
        }
        // Far cars keep the dome: see kCarBodyLodBlocks.
        const float ddx = body->objectToWorld.m[3][0] - lastEye_.x, ddy = body->objectToWorld.m[3][1] - lastEye_.y,
                    ddz = body->objectToWorld.m[3][2] - lastEye_.z;
        const bool distant = ddx * ddx + ddy * ddy + ddz * ddz > kCarBodyLodBlocks * kCarBodyLodBlocks;
        if (distant) goto dome;
        CarBodyUse use;
        use.texture = body->texture;
        use.sprite = sprite;
        // The vehicle the sprite belongs to, and its model number.
        {
            const uint8_t* car = *reinterpret_cast<const uint8_t* const*>(object + game::kSpriteObjectOwner);
            if (game::PlausiblePointer(car)) {
                const int32_t number = *reinterpret_cast<const int32_t*>(car + game::kVehicleModel);
                if (number >= 0 && number < 256) use.model = number;
                // The damage word (int16, 0..32000, docs/actions-3d.md "Vehicle fields") and the
                // fire stage byte (3 burning, 4 burning hard); not the word's low byte.
                use.damage = *reinterpret_cast<const int16_t*>(car + 0x74);
                use.fireStage = *(car + 0x8C);
                if (const uint8_t* me = static_cast<const uint8_t*>(LocatedPlayerPed()))
                    use.driven = game::PlausiblePointer(me) && *reinterpret_cast<const uint8_t* const*>(me + game::kPedVehicle) == car;
                float best = 1.6f * 1.6f;   // a boarding ped stands within a car's half length plus a door
                for (const DoorPed& dp : g_doorPeds) {
                    const float ddx = dp.x - body->objectToWorld.m[3][0], ddz = dp.z - body->objectToWorld.m[3][2];
                    const float d2 = ddx * ddx + ddz * ddz;
                    const bool match = dp.vehicle ? dp.vehicle == reinterpret_cast<uintptr_t>(car) : d2 < best;
                    if (!match) continue;
                    best = d2; use.doorPed = true; use.doorPedX = dp.x; use.doorPedZ = dp.z;
                    if (dp.vehicle) break;
                }
            }
        }
        use.object = reinterpret_cast<uintptr_t>(object);
        use.own = object == g_hiddenObjects[1];
        static_assert(sizeof(CarBodyVertex) == sizeof(Vertex), "car body vertices share the world layout");
        memcpy(use.local, body->local, sizeof(use.local));
        use.objectToWorld = body->objectToWorld;
        carBodies_.push_back(use);
        body->hidden = true;
        return;
    }
dome:
    const float above = body->objectToWorld.m[1][1] >= 0.0f ? 1.0f : -1.0f;
    const float peak = g_carBodyHeight * above;
    // Clear of the flat body underneath, so the two never fight for the pixel.
    const float clear = 0.012f * above;

    constexpr int n = kDomeSegments;
    constexpr float kPi = 3.14159265358979f;
    struct P {
        float x, y, z;
    };
    // Position, texture coordinate of grid point (i, j): the bilinear blend of
    // the body's corners, which also carries however the game turned the sprite.
    auto blend = [&](float s, float t, float* u, float* v) {
        const float w0 = (1 - s) * (1 - t), w1 = s * (1 - t), w2 = s * t, w3 = (1 - s) * t;
        const Vertex* c = body->local;
        *u = c[0].u * w0 + c[1].u * w1 + c[2].u * w2 + c[3].u * w3;
        *v = c[0].v * w0 + c[1].v * w1 + c[2].v * w2 + c[3].v * w3;
        return P{c[0].x * w0 + c[1].x * w1 + c[2].x * w2 + c[3].x * w3,
                 c[0].y * w0 + c[1].y * w1 + c[2].y * w2 + c[3].y * w3,
                 c[0].z * w0 + c[1].z * w1 + c[2].z * w2 + c[3].z * w3};
    };
    // How high the dome stands at (s, t): flat-topped rather than pointed. A car
    // that is not one even hump (a truck cab, see CarDomeProfile) is scaled along
    // its length by where the point lies between the sprite's top (rear) and bottom.
    const int spriteNo = static_cast<int>(*reinterpret_cast<const uint16_t*>(object + game::kSpriteObjectNumber));
    float vLo = body->local[0].v, vHi = body->local[0].v;
    for (int i = 1; i < 4; ++i) {
        vLo = (std::min)(vLo, body->local[i].v);
        vHi = (std::max)(vHi, body->local[i].v);
    }
    auto height = [&](float s, float t) {
        const float k = std::sin(kPi * s) * std::sin(kPi * t);
        float u, v;
        blend(s, t, &u, &v);
        const float b = vHi > vLo ? (v - vLo) / (vHi - vLo) : 0.5f;
        return clear + peak * std::pow((std::max)(k, 0.0f), g_carDomeShoulder) * CarDomeProfile(spriteNo, b);
    };

    P grid[n + 1][n + 1];
    float us[n + 1][n + 1], vs[n + 1][n + 1];
    for (int j = 0; j <= n; ++j) {
        for (int i = 0; i <= n; ++i) {
            const float s = static_cast<float>(i) / n, t = static_cast<float>(j) / n;
            P p = blend(s, t, &us[j][i], &vs[j][i]);
            p.y += height(s, t);
            grid[j][i] = p;
        }
    }

    // Which way is out of the sprite, from the body's own normal if it has one.
    P facing{body->local[0].nx, body->local[0].ny, body->local[0].nz};
    if (std::fabs(facing.x) + std::fabs(facing.y) + std::fabs(facing.z) < 1e-4f) {
        facing = {0.0f, above, 0.0f};
    }

    CarShell shell;
    shell.texture = body->texture;
    shell.sprite = static_cast<int>(*reinterpret_cast<const uint16_t*>(object + game::kSpriteObjectNumber));
    shell.object = reinterpret_cast<uintptr_t>(object);
    shell.objectToWorld = body->objectToWorld;
    for (int j = 0; j <= n; ++j) {
        for (int i = 0; i <= n; ++i) {
            // Central differences along both axes, one-sided at the rim.
            const P& a = grid[j][(std::max)(i - 1, 0)];
            const P& b = grid[j][(std::min)(i + 1, n)];
            const P& c = grid[(std::max)(j - 1, 0)][i];
            const P& d = grid[(std::min)(j + 1, n)][i];
            const P ds{b.x - a.x, b.y - a.y, b.z - a.z};
            const P dt{d.x - c.x, d.y - c.y, d.z - c.z};
            P nrm{ds.y * dt.z - ds.z * dt.y, ds.z * dt.x - ds.x * dt.z,
                  ds.x * dt.y - ds.y * dt.x};
            const float len = std::sqrt(nrm.x * nrm.x + nrm.y * nrm.y + nrm.z * nrm.z);
            if (len < 1e-9f) return;   // a degenerate car: leave it flat
            nrm = {nrm.x / len, nrm.y / len, nrm.z / len};
            if (nrm.x * facing.x + nrm.y * facing.y + nrm.z * facing.z < 0.0f) {
                nrm = {-nrm.x, -nrm.y, -nrm.z};
            }
            Vertex& out = shell.local[j * (n + 1) + i];
            out.x = grid[j][i].x;
            out.y = grid[j][i].y;
            out.z = grid[j][i].z;
            out.nx = nrm.x;
            out.ny = nrm.y;
            out.nz = nrm.z;
            out.u = us[j][i];
            out.v = vs[j][i];
        }
    }
    // The dome stands in for the body entirely when it has hand-made artwork:
    // the flat sprite beneath it would show at the edge and fight it for depth.
    const bool handMade = g_carHd && g_carMaterial && RemixApiHasInstances() && HdFor(shell.sprite).ok;
    if (handMade) BuildCarDoors(*body, &shell, object);
    BuildCarTyres(*body, &shell, object, peak);
    shells_.push_back(shell);
    body->shell = static_cast<int>(shells_.size()) - 1;
    if (handMade) body->hidden = true;
}

// The height of the car's dome at (a, b), each 0..1 across the sprite as its texture runs, read the
// way the dome mesh itself is: the analytic height at the mesh's own kDomeSegments x kDomeSegments
// points, blended bilinearly between them. (RaiseCarBody samples the smooth formula only at those
// points; the surface drawn is flat in between.)
static float DomeHeightOnGrid(int sprite, float a, float b, const int N) {
    constexpr float kPi = 3.14159265358979f;
    auto lattice = [&](int i, int j) {
        const float la = static_cast<float>(i) / N, lb = static_cast<float>(j) / N;
        const float k = std::sin(kPi * la) * std::sin(kPi * lb);
        return g_carBodyHeight * std::pow((std::max)(k, 0.0f), g_carDomeShoulder) * CarDomeProfile(sprite, lb);
    };
    const float fa = (std::max)(0.0f, (std::min)(1.0f, a)) * N;
    const float fb = (std::max)(0.0f, (std::min)(1.0f, b)) * N;
    const int i = (std::min)(static_cast<int>(fa), N - 1), j = (std::min)(static_cast<int>(fb), N - 1);
    const float ta = fa - i, tb = fb - j;
    const float h0 = lattice(i, j) * (1 - ta) + lattice(i + 1, j) * ta;
    const float h1 = lattice(i, j + 1) * (1 - ta) + lattice(i + 1, j + 1) * ta;
    return h0 * (1 - tb) + h1 * tb;
}

// The car's open doors and dents, as grids lying on its dome. The game paints those
// into its own sprite; the hand-made artwork is of the closed, undamaged car, so
// they are drawn over it from the deltas the car's mask names. Laid out as the lamps
// are - the same bilinear reading of the body's corners from texture coordinates -
// but a grid, not a flat quad, since a door is big enough to need the dome's curve.
void LiveGeometry::BuildCarDoors(const Sprite& body, CarShell* shell, const void* objectPtr) {
    const uint8_t* object = static_cast<const uint8_t*>(objectPtr);
    const uint8_t* car = *reinterpret_cast<const uint8_t* const*>(object + game::kSpriteObjectOwner);
    if (!game::PlausiblePointer(car)) return;
    const uint32_t mask = *reinterpret_cast<const uint32_t*>(car + game::kVehicleDeltaMask);
    const int sprite = shell->sprite;

    float u0 = body.local[0].u, u1 = u0, v0 = body.local[0].v, v1 = v0;
    for (int i = 1; i < 4; ++i) {
        u0 = (std::min)(u0, body.local[i].u);
        u1 = (std::max)(u1, body.local[i].u);
        v0 = (std::min)(v0, body.local[i].v);
        v1 = (std::max)(v1, body.local[i].v);
    }
    if (u1 - u0 < 1e-6f || v1 - v0 < 1e-6f) return;
    int corner[2][2] = {{0, 0}, {0, 0}};
    for (int i = 0; i < 4; ++i) {
        const int su = body.local[i].u > (u0 + u1) * 0.5f ? 1 : 0;
        const int sv = body.local[i].v > (v0 + v1) * 0.5f ? 1 : 0;
        corner[su][sv] = i;
    }
    const float above = body.objectToWorld.m[1][1] >= 0.0f ? 1.0f : -1.0f;
    constexpr int n = kDoorSegments;

    for (int bit = 0; bit < 32; ++bit) {
        if (!(mask & (1u << bit))) continue;
        bool mirrored = false;
        const int delta = DoorDeltaOfBit(bit, &mirrored);
        if (delta < 0) continue;
        if (delta <= 4 && g_carDamage < 0.01f) continue;
        // Car 17's digits 11..14 are its roof number, laid as decals with the lamps.
        if (sprite == game::kRoofNumberSprite && delta >= game::kRoofNumberFirstDelta) continue;
        const auto arts = g_deltaArt.find(delta);
        if (arts == g_deltaArt.end() || sprite < 0 || sprite >= static_cast<int>(arts->second.size())) continue;
        const LampArt& r = arts->second[sprite];
        if (!r.Valid() || r.opaque <= 0) continue;
        if (!DeltaIsDoor(delta, sprite)) continue;

        const int rx0 = r.x0, rx1 = r.x0 + r.width;
        const float px0 = static_cast<float>(mirrored ? r.spriteWidth - rx1 : rx0);
        const float px1 = static_cast<float>(mirrored ? r.spriteWidth - rx0 : rx1);
        const float tu0 = u0 + (u1 - u0) * px0 / r.spriteWidth;
        const float tu1 = u0 + (u1 - u0) * px1 / r.spriteWidth;
        const float tv0 = v0 + (v1 - v0) * static_cast<float>(r.y0) / r.spriteHeight;
        const float tv1 = v0 + (v1 - v0) * static_cast<float>(r.y0 + r.height) / r.spriteHeight;

        CarShell::Door door;
        door.delta = delta;
        door.art = &r;
        for (int j = 0; j <= n; ++j) {
            for (int i = 0; i <= n; ++i) {
                const float fu = static_cast<float>(i) / n, fv = static_cast<float>(j) / n;
                const float u = tu0 + (tu1 - tu0) * fu, v = tv0 + (tv1 - tv0) * fv;
                const float a = (std::max)(0.0f, (std::min)(1.0f, (u - u0) / (u1 - u0)));
                const float b = (std::max)(0.0f, (std::min)(1.0f, (v - v0) / (v1 - v0)));
                const Vertex& p00 = body.local[corner[0][0]];
                const Vertex& p10 = body.local[corner[1][0]];
                const Vertex& p01 = body.local[corner[0][1]];
                const Vertex& p11 = body.local[corner[1][1]];
                Vertex out = p00;
                out.x = (p00.x * (1 - a) + p10.x * a) * (1 - b) + (p01.x * (1 - a) + p11.x * a) * b;
                out.y = (p00.y * (1 - a) + p10.y * a) * (1 - b) + (p01.y * (1 - a) + p11.y * a) * b;
                out.z = (p00.z * (1 - a) + p10.z * a) * (1 - b) + (p01.z * (1 - a) + p11.z * a) * b;
                // Over the dome's surface under this point, a little above it. The dome the car
                // is drawn with is a coarse grid (kDomeSegments) of this height, flat between its
                // points, so the height here is read off that grid the same way, not off the smooth
                // formula: on the steep front of a long car the formula is a good deal above the
                // dome's own facets, and a patch laid by it hovered over the roof as a slab.
                out.y += above * (0.012f + DomeHeightOnGrid(shell->sprite, a, b, kDomeSegments) + 0.006f);
                out.nx = 0.0f;
                out.ny = above;
                out.nz = 0.0f;
                // The texels are the unmirrored delta's: a far-side door reads them
                // from the other end.
                out.u = mirrored ? 1.0f - fu : fu;
                out.v = fv;
                door.local[j * (n + 1) + i] = out;
            }
        }
        // Normals of the dome under the patch, from the grid's own slopes (as RaiseCarBody does for the
        // dome). With the flat normal every point had, a patch on the sloping front was lit as a
        // flat plate against the curving roof around it, which is what made it read as a box.
        for (int j = 0; j <= n; ++j) {
            for (int i = 0; i <= n; ++i) {
                const Vertex& pa = door.local[j * (n + 1) + (std::max)(i - 1, 0)];
                const Vertex& pb = door.local[j * (n + 1) + (std::min)(i + 1, n)];
                const Vertex& pc = door.local[(std::max)(j - 1, 0) * (n + 1) + i];
                const Vertex& pd = door.local[(std::min)(j + 1, n) * (n + 1) + i];
                const float dsx = pb.x - pa.x, dsy = pb.y - pa.y, dsz = pb.z - pa.z;
                const float dtx = pd.x - pc.x, dty = pd.y - pc.y, dtz = pd.z - pc.z;
                float nx = dsy * dtz - dsz * dty, ny = dsz * dtx - dsx * dtz, nz = dsx * dty - dsy * dtx;
                const float len = std::sqrt(nx * nx + ny * ny + nz * nz);
                if (len < 1e-9f) continue;   // degenerate: keep the flat normal
                nx /= len; ny /= len; nz /= len;
                if (ny * above < 0.0f) { nx = -nx; ny = -ny; nz = -nz; }
                Vertex& out = door.local[j * (n + 1) + i];
                out.nx = nx;
                out.ny = ny;
                out.nz = nz;
            }
        }
        shell->doors.push_back(door);
    }
}

// Each lit lamp of the car just drawn, as a quad of its own over the lamp's
// pixels on the body. The body's corners carry the sprite's texture coordinates,
// so a point of the sprite at (u, v) is the bilinear blend of the corners by
// where u and v fall between the corners' own - which also takes care of however
// the game turned or mirrored the quad.
void LiveGeometry::AddCarLamps(const Sprite& body) {
    const uint8_t* object = static_cast<const uint8_t*>(GameObjectBeingDrawn());
    if (!object || body.corners != 4) return;
    if (*reinterpret_cast<const int32_t*>(object + game::kSpriteObjectBase) != game::kSpriteBaseCar) {
        return;
    }
    const uint8_t* car = *reinterpret_cast<const uint8_t* const*>(object + game::kSpriteObjectOwner);
    if (!game::PlausiblePointer(car)) return;
    const uint32_t mask = *reinterpret_cast<const uint32_t*>(car + game::kVehicleDeltaMask);
    const int sprite = *reinterpret_cast<const uint16_t*>(object + game::kSpriteObjectNumber);

    float u0 = body.local[0].u, u1 = u0, v0 = body.local[0].v, v1 = v0;
    for (int i = 1; i < 4; ++i) {
        u0 = (std::min)(u0, body.local[i].u);
        u1 = (std::max)(u1, body.local[i].u);
        v0 = (std::min)(v0, body.local[i].v);
        v1 = (std::max)(v1, body.local[i].v);
    }
    if (u1 - u0 < 1e-6f || v1 - v0 < 1e-6f) return;
    // Which corner is which, by its texture coordinates: 0 at the low end.
    int corner[2][2] = {{0, 0}, {0, 0}};
    for (int i = 0; i < 4; ++i) {
        const int su = body.local[i].u > (u0 + u1) * 0.5f ? 1 : 0;
        const int sv = body.local[i].v > (v0 + v1) * 0.5f ? 1 : 0;
        corner[su][sv] = i;
    }
    auto at = [&](float u, float v) {
        const float a = (u - u0) / (u1 - u0), b = (v - v0) / (v1 - v0);
        const Vertex& p00 = body.local[corner[0][0]];
        const Vertex& p10 = body.local[corner[1][0]];
        const Vertex& p01 = body.local[corner[0][1]];
        const Vertex& p11 = body.local[corner[1][1]];
        Vertex out = p00;
        out.x = (p00.x * (1 - a) + p10.x * a) * (1 - b) + (p01.x * (1 - a) + p11.x * a) * b;
        out.y = (p00.y * (1 - a) + p10.y * a) * (1 - b) + (p01.y * (1 - a) + p11.y * a) * b;
        out.z = (p00.z * (1 - a) + p10.z * a) * (1 - b) + (p01.z * (1 - a) + p11.z * a) * b;
        return out;
    };
    // Above the body, whichever way its frame faces.
    const float above = body.objectToWorld.m[1][1] >= 0.0f ? 1.0f : -1.0f;

    // Exactly the bits the game is about to draw as its lamp quad: the car's own
    // mask, cut down to the lamp mask FUN_004BE060 chose for this car.
    uint32_t lit = mask & *reinterpret_cast<const uint32_t*>(game::kLampMaskPtr);
    // Car 17's roof number: any of its digit deltas, not only those the game lights.
    const bool numberCar = sprite == game::kRoofNumberSprite;
    if (numberCar) lit = (lit & ~game::kRoofNumberMask) | (mask & game::kRoofNumberMask);
    for (int bit = 0; bit < 32; ++bit) {
        if (!(lit & (1u << bit))) continue;
        // FUN_0044AEA0's reading: from bit 22 up, delta bit - 17 mirrored.
        const bool mirrored = bit >= game::kMirroredDeltaFirstBit;
        const int delta = mirrored ? bit - game::kMirroredDeltaOffset : bit;
        const bool number = numberCar && delta >= game::kRoofNumberFirstDelta &&
                            delta <= game::kRoofNumberLastDelta;
        if (number && mirrored) continue;
        // The taxi's roof-sign lamps are laid from where the sign is on the game's little sprite,
        // which is not where the hand-made sign is: they came out as bright white bars on the
        // checker stripe, beside the sign rather than in it. The hand-made art has its own sign.
        if (sprite == kTaxiSignSprite && delta >= 15 && g_carHd && HdFor(sprite).ok) continue;
        auto arts = g_lampArt.find(delta);
        if (arts == g_lampArt.end() || sprite >= static_cast<int>(arts->second.size())) continue;
        const LampArt& r = arts->second[sprite];
        if (!r.Valid()) continue;
        {
            // The mirrored lamp is the same pixels flipped across the sprite.
            const int rx0 = r.x0, rx1 = r.x0 + r.width;
            const float px0 = static_cast<float>(mirrored ? r.spriteWidth - rx1 : rx0);
            const float px1 = static_cast<float>(mirrored ? r.spriteWidth - rx0 : rx1);
            const float tu0 = u0 + (u1 - u0) * px0 / r.spriteWidth;
            const float tu1 = u0 + (u1 - u0) * px1 / r.spriteWidth;
            const float tv0 = v0 + (v1 - v0) * static_cast<float>(r.y0) / r.spriteHeight;
            const float tv1 = v0 + (v1 - v0) * static_cast<float>(r.y0 + r.height) / r.spriteHeight;
            Sprite lamp = body;
            lamp.hidden = false;
            lamp.texture = nullptr;
            lamp.lamp = &r;
            lamp.lampMirrored = mirrored;
            lamp.lampPlain = number;
            const float us[4] = {tu0, tu1, tu1, tu0};
            const float vs[4] = {tv0, tv0, tv1, tv1};
            const float uvs[4][2] = {{0, 0}, {1, 0}, {1, 1}, {0, 1}};
            // A car with a dome has its roof standing up to CarBodyHeight above the
            // flat sprite, and a lamp laid on the flat sprite is then underneath
            // it: a roof light bar vanishes into the roof, and a headlight is seen
            // only where the dome slopes away. So the lamp goes up onto the dome,
            // at the height of the dome's own surface under it, plus a margin for
            // the surface curving above the flat quad between its corners.
            float lift = kConformClearance;
            if (body.shell >= 0 && g_carBodyHeight > 1e-4f) {
                constexpr float kPi = 3.14159265358979f;
                float top = 0.0f;
                for (int i = 0; i < 4; ++i) {
                    const float a = (std::max)(0.0f, (std::min)(1.0f, (us[i] - u0) / (u1 - u0)));
                    const float b = (std::max)(0.0f, (std::min)(1.0f, (vs[i] - v0) / (v1 - v0)));
                    const float k = std::sin(kPi * a) * std::sin(kPi * b);
                    top = (std::max)(top, g_carBodyHeight * std::pow((std::max)(k, 0.0f), g_carDomeShoulder) * CarDomeProfile(sprite, b));
                }
                lift = 0.012f + top + 0.014f;
            }
            for (int i = 0; i < 4; ++i) {
                lamp.local[i] = at(us[i], vs[i]);
                lamp.local[i].y += lift * above;
                lamp.local[i].u = uvs[i][0];
                lamp.local[i].v = uvs[i][1];
            }
            sprites_.push_back(lamp);
            ++spriteQuads_;
        }
    }
}

namespace {
// Where Draw's time goes, a stage at a time, for the frame-time log in world_view.cpp.
// Slots: 0 setup, 1 loop, 2 skidmemory, 3 issue (the game's quads), 4 car
// models + bodies, 5 props, 6 map objects, 7 pedestrian figures, 8 the rest
// (skids, domes, lamps).
double g_drawStageMs[kDrawStages] = {};
struct DrawStageTimer {
    LARGE_INTEGER last;
    int n = 0;
    double toMs;
    DrawStageTimer() {
        LARGE_INTEGER f;
        QueryPerformanceFrequency(&f);
        toMs = 1000.0 / static_cast<double>(f.QuadPart);
        for (double& v : g_drawStageMs) v = 0.0;
        QueryPerformanceCounter(&last);
    }
    void Mark() {
        LARGE_INTEGER now;
        QueryPerformanceCounter(&now);
        if (n < kDrawStages) g_drawStageMs[n] = static_cast<double>(now.QuadPart - last.QuadPart) * toMs;
        last = now;
        ++n;
    }
    ~DrawStageTimer() { if (n < kDrawStages) Mark(); }
};
}  // namespace

const double* LiveDrawStageMs() { return g_drawStageMs; }

// A pedestrian stood on his feet as a billboard, for a camera that is not above
// him. GTA2 draws its pedestrians from above and lays them flat on the road,
// which from a chase camera is a line; this takes the quad as placed - the
// same object-space shape Remix hashes, so nothing about the mesh changes -
// and turns its frame so the quad is vertical, square to the camera, and
// standing on the point where it lay, with the artwork's top uppermost. Only
// the matrix differs, which is the thing Remix expects to change.
static gta2::Mat4 UprightPedMatrix(const LiveGeometry::Vertex* local, int corners,
                                   const gta2::Mat4& placed, const gta2::Vec3& eye) {
    float minZ = 1e9f, maxZ = -1e9f, topV = 1e9f;
    int top = 0;
    for (int i = 0; i < corners; ++i) {
        minZ = (std::min)(minZ, local[i].z);
        maxZ = (std::max)(maxZ, local[i].z);
        if (local[i].v < topV) {
            topV = local[i].v;
            top = i;
        }
    }
    // Which way along the quad's own z the artwork's top lies.
    const float zTop = local[top].z >= (minZ + maxZ) * 0.5f ? 1.0f : -1.0f;
    const float cx = placed.m[3][0], cy = placed.m[3][1], cz = placed.m[3][2];
    float vx = eye.x - cx, vz = eye.z - cz;
    const float len = std::sqrt(vx * vx + vz * vz);
    if (len < 1e-4f) {
        vx = 0.0f;
        vz = 1.0f;
    } else {
        vx /= len;
        vz /= len;
    }
    // Rows are the object axes in the world: x stays horizontal and square to
    // the camera, the normal (y) faces the camera, z becomes up - signed so the
    // top of the artwork is up and the frame stays a rotation, not a mirror.
    gta2::Mat4 m;
    m.m[0][0] = -vz * zTop; m.m[0][1] = 0.0f; m.m[0][2] = vx * zTop;
    m.m[1][0] = vx;         m.m[1][1] = 0.0f; m.m[1][2] = vz;
    m.m[2][0] = 0.0f;       m.m[2][1] = zTop; m.m[2][2] = 0.0f;
    // The corner that becomes the bottom edge stands on the ground the quad lay on.
    const float bottomZ = zTop > 0.0f ? minZ : maxZ;
    m.m[3][0] = cx;
    m.m[3][1] = cy - zTop * bottomZ;
    m.m[3][2] = cz;
    m.m[3][3] = 1.0f;
    return m;
}

// ---------------------------------------------------------------------------
// GTA2DX9_FORCE_ACTION_FILE (see DrawPedFigures): the forced action, lying clip
// and weapon, read from the file every 15 frames.
void ForcedAction(int* action, int* lie, int* weapon) {
    static int checked = 0;
    static char path[MAX_PATH] = {};
    static int a = -1, l = 0, w = -1;
    static uint32_t lastRead = 0;
    if (!checked) { checked = 1; if (!GetEnvironmentVariableA("GTA2DX9_FORCE_ACTION_FILE", path, sizeof path)) path[0] = 0; }
    if (!path[0]) { *action = -1; return; }
    if (g_carFrame - lastRead >= 15 || lastRead == 0) {
        lastRead = g_carFrame;
        int na = -1, nl = 0, nw = -1;
        if (FILE* f = fopen(path, "r")) {
            if (fscanf(f, "%d %d %d", &na, &nl, &nw) < 1) na = -1;
            fclose(f);
        }
        if (na != a || nl != l || nw != w) Log("devtools: forced action %d lying %d weapon %d", na, nl, nw);
        a = na; l = nl; w = nw;
    }
    *action = a; *lie = l; *weapon = w;
}

// Which action clip the game's own animation frame and state words call for.
// Frames are the style sprite number within the ped base, modulo the 158 frames
// of one body (three bodies share the layout). Ranges from the frame sheet and
// from logging the player's frames per state (assets-src/humans/ped_states.json).
namespace {
int PedActionFor(bool corpse, unsigned pedFrame, int32_t pedState, int32_t pedSub) {
    if (corpse) return 4;   // dead, or knocked down: lying
    const unsigned f = pedFrame % 158u;
    if (pedState == 4) return 6;   // getting out (sub 7: frames 36 down to 28, then 28-31; the game slides him out sideways)
    if (f >= 24 && f <= 35 && pedState == 3) return 5;   // the climb (sub 6); the same frames pass in state 0 just after an exit   // the climb (state 3: in, 4: out); the same frames pass in state 0 just after an exit
    if (f >= 16 && f <= 23 && pedState == 3) return 5;    // reaching for the door
    if (pedState == 8 && pedSub == 0x13) return 20;   // falling from a height: arms and legs flailing (fall_air)
    if (pedState == 8 && pedSub == 0x11) return 7;    // thrown (before the frame ranges: a thrown ped passes through them)
    if (f >= static_cast<unsigned>(g_pedPunchFrames[0]) && f <= static_cast<unsigned>(g_pedPunchFrames[1])) return 1;
    // The aim only while attacking with something other than fists (state 7, sub 0xe = fists).
    if (pedState == 7 && pedSub != 0xe && f >= static_cast<unsigned>(g_pedAimFrames[0]) && f <= static_cast<unsigned>(g_pedAimFrames[1])) return 2;
    // The two-handed stance: the heavy-weapon frames (48-52 on the sheet), in the
    // attack state or carried while standing.
    if (f >= 48 && f <= 52 && (pedState == 7 || pedState == 0)) return 8;
    // In the water (state 8 sub 0x14), or the sinking frames.
    if ((pedState == 8 && pedSub == 0x14) || (f >= 131 && f <= 135)) return 9;
    if (g_pedHandsUpFrames[0] >= 0 && f >= static_cast<unsigned>(g_pedHandsUpFrames[0]) && f <= static_cast<unsigned>(g_pedHandsUpFrames[1])) return 3;
    return 0;
}
}

// Pedestrians as figures. See SetPedFigures.
//
// A figure is six boxes in its own space - x to its right, y up, z the way it
// faces, feet at y = 0 - built fresh each frame with the limbs swung by the
// walk cycle, and placed with a world matrix made from the sprite's position
// and heading. Sizes are in blocks. A GTA2 car sprite is one block long, so a
// block is a car's length, about 4.8 m, and the 3D cars' roofs come out at
// 0.35-0.37 blocks (car_bodies.cpp fits them to the sprite footprint); an adult
// stands about 1.2 times a sedan's roof, hence kPedHeight. The eye height in
// view_modes.h (fpEyeFoot) follows from the same figure.
// ---------------------------------------------------------------------------
namespace {

constexpr float kPedHeight = 0.46f;   // a standing adult, in blocks (see above)

struct FigVertex {
    float x, y, z, nx, ny, nz;
    DWORD color;
};
constexpr DWORD kFigFvf = D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_DIFFUSE;

// ---------------------------------------------------------------------------
// Shooting. The weapons in the renderer's own order (the game's weapon type,
// read off the ped's weapon object, maps to it through game::PedWeaponFromGame;
// see SetPlayerWeapon and g_pedWeaponByObject), each with
// its stance clip, its model (assets-src/weapons, tools/gen_weapons.py: the
// grip at the origin, the barrel along +z), its length in blocks, and its
// muzzle flash (size in blocks, colour, the light it throws).
// ---------------------------------------------------------------------------
enum PedWeapon { kWpnNone = 0, kWpnPistol, kWpnDual, kWpnSilencedMg, kWpnMg, kWpnRocket, kWpnElectro,
                 kWpnMolotov, kWpnGrenade, kWpnShotgun, kWpnFlame, kWpnCount };
struct WeaponInfo {
    const char* name;
    const char* model;
    int action;         // the stance clip: 2 aim, 10 aim_dual, 8 aim_heavy, 11 aim_launcher, 12 aim_flame, 13 throw
    bool twoHanded;     // laid along the line from the right hand to the left
    float length;       // blocks
    float flashSize;    // blocks; 0: no flash of its own
    float r, g, b;      // the flash's colour
    float light;        // the Remix light's intensity, 0..1
    bool shells;        // ejects a case
    float kick;         // the first-person view model's kick back, blocks
};
const WeaponInfo kWeapons[kWpnCount] = {
    {"none", nullptr, 0, false, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, false, 0.0f},
    {"pistol", "weapon_pistol", 2, false, 0.065f, 0.10f, 1.0f, 0.85f, 0.55f, 0.6f, true, 0.020f},
    {"dual_pistol", "weapon_pistol", 10, false, 0.065f, 0.10f, 1.0f, 0.85f, 0.55f, 0.6f, true, 0.020f},
    {"silenced_mg", "weapon_silenced_mg", 8, true, 0.17f, 0.045f, 0.9f, 0.8f, 0.6f, 0.15f, true, 0.010f},
    {"machine_gun", "weapon_machine_gun", 8, true, 0.17f, 0.13f, 1.0f, 0.8f, 0.45f, 0.8f, true, 0.014f},
    {"rocket_launcher", "weapon_rocket_launcher", 11, true, 0.26f, 0.28f, 1.0f, 0.7f, 0.4f, 1.0f, false, 0.040f},
    {"electro_gun", "weapon_electro_gun", 8, true, 0.16f, 0.12f, 0.6f, 0.85f, 1.0f, 0.7f, false, 0.0f},
    {"molotov", "weapon_molotov", 13, false, 0.05f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, false, 0.0f},
    {"grenade", "weapon_grenade", 13, false, 0.03f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, false, 0.0f},
    {"shotgun", "weapon_shotgun", 8, true, 0.20f, 0.20f, 1.0f, 0.8f, 0.45f, 1.0f, true, 0.035f},
    {"flamethrower", "weapon_flamethrower", 12, true, 0.19f, 0.16f, 1.0f, 0.6f, 0.2f, 0.5f, false, 0.0f},
};
// A weapon model's largest extent: its length for the guns, its height for a
// bottle or a grenade (modelled upright), which scaling by the length alone
// blew up to three times their size.
float WeaponSpan(const Model& m) { return (std::max)(m.Length(), (std::max)(m.Height(), m.Width())); }
bool IsAimAction(int action) { return action == 2 || action == 8 || action == 10 || action == 11 || action == 12; }
// Carrying, not firing: the weapon in the hands at low ready (clips carry*,
// tools/gen_ped_clips.py): 14 one-handed (pistol, grenade, molotov), 15 dual
// pistols, 16 long guns, 17 the launcher on the shoulder, 18 the flamethrower.
bool IsCarryAction(int action) { return action >= 14 && action <= 18; }
int CarryFor(int weapon) {
    switch (weapon) {
        case kWpnDual: return 15;
        case kWpnSilencedMg: case kWpnMg: case kWpnShotgun: case kWpnElectro: return 16;
        case kWpnRocket: return 17;
        case kWpnFlame: return 18;
        default: return 14;
    }
}
// QB-29: reloading. GTA2 has no magazines (a weapon fires until its ammunition
// is gone), so each gun gets a notional one: the shots are counted off the
// weapon object (its ammunition dropping or its reload timer restarting, see
// gameShot in DrawPedFigures) and, the magazine spent, the reload clip plays
// once he stops firing (a shot cuts it off: the game fires regardless). Clips
// (tools/gen_ped_clips.py): 24 reload (pistol, the dual pistols' right gun),
// 25 reload_heavy (machine guns, shotgun), 26 reload_launcher. The times are
// the clip's own: the magazine leaves the gun, the fresh one goes in, the
// slide or charging handle (each a click for the player, see ReloadClick).
// GTA2DX9_RELOAD=0 turns it off.
struct ReloadInfo { int mag; int action; float len, dropT, grabT, insertT, rackT; };
const ReloadInfo kReloads[kWpnCount] = {
    {0, 0, 0, 0, 0, 0, 0},                                // none
    {6, 24, 1.40f, 0.30f, 0.55f, 0.80f, 0.98f},           // pistol (a pickup is 10 shots)
    {12, 24, 1.40f, 0.30f, 0.55f, 0.80f, 0.98f},          // dual pistols
    {30, 25, 1.55f, 0.35f, 0.65f, 0.95f, 1.12f},          // silenced machine gun
    {30, 25, 1.55f, 0.35f, 0.65f, 0.95f, 1.12f},          // machine gun
    {1, 26, 1.20f, -1.0f, 0.40f, 0.85f, -1.0f},           // rocket launcher: a rocket in, nothing out
    {0, 0, 0, 0, 0, 0, 0},                                // electro gun (a battery: no reload)
    {0, 0, 0, 0, 0, 0, 0},                                // molotov
    {0, 0, 0, 0, 0, 0, 0},                                // grenade
    {6, 25, 1.55f, 0.35f, 0.65f, 0.95f, 1.12f},           // shotgun
    {0, 0, 0, 0, 0, 0, 0},                                // flamethrower
};
bool IsReloadAction(int action) { return action >= 24 && action <= 26; }
int g_reloadOn = -1;   // GTA2DX9_RELOAD (default on)
bool ReloadOn() {
    if (g_reloadOn < 0) { char buf[8] = {}; g_reloadOn = !(GetEnvironmentVariableA("GTA2DX9_RELOAD", buf, sizeof buf) && buf[0] == '0'); }
    return g_reloadOn != 0;
}
// The player's clicks: synthesized (no recorded sound), 22.05 kHz mono through
// waveOut, so they mix with the game's own sound and do not stop the voice-over
// (PlaySound plays one sound at a time). 0 the magazine out, 1 in, 2 the slide.
// GTA2DX9_RELOAD_SOUND=0 turns them off.
void ReloadClick(int kind) {
    static int on = -1;
    if (on < 0) { char buf[8] = {}; on = !(GetEnvironmentVariableA("GTA2DX9_RELOAD_SOUND", buf, sizeof buf) && buf[0] == '0'); }
    if (!on || kind < 0 || kind > 2) return;
    static HWAVEOUT out = nullptr;
    static bool tried = false;
    static std::vector<int16_t> pcm[3];
    static WAVEHDR hdr[3];
    constexpr int kRate = 22050;
    if (!tried) {
        tried = true;
        WAVEFORMATEX fmt = {};
        fmt.wFormatTag = WAVE_FORMAT_PCM; fmt.nChannels = 1; fmt.nSamplesPerSec = kRate;
        fmt.wBitsPerSample = 16; fmt.nBlockAlign = 2; fmt.nAvgBytesPerSec = kRate * 2;
        if (waveOutOpen(&out, WAVE_MAPPER, &fmt, 0, 0, CALLBACK_NULL) != MMSYSERR_NOERROR) { out = nullptr; Log("reload: no waveOut device, clicks off"); return; }
        // A click: a burst of noise and a damped metallic ring, at onset seconds.
        uint32_t seed = 0x2545F491u;
        auto click = [&](std::vector<int16_t>& v, float onset, float ring, float decay, float amp) {
            const int start = static_cast<int>(onset * kRate);
            const int n = static_cast<int>(0.06f * kRate);
            if (static_cast<int>(v.size()) < start + n) v.resize(start + n, 0);
            for (int i = 0; i < n; ++i) {
                seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5;
                const float t = static_cast<float>(i) / kRate;
                const float noise = (static_cast<float>(seed & 0xFFFF) / 32768.0f - 1.0f) * std::exp(-t * 900.0f);
                const float tone = std::sin(6.2831853f * ring * t) * std::exp(-t * decay) * 0.6f +
                                   std::sin(6.2831853f * ring * 2.7f * t) * std::exp(-t * decay * 1.6f) * 0.25f;
                const float s = (noise + tone) * amp * 9000.0f + v[start + i];
                v[start + i] = static_cast<int16_t>((std::max)(-32000.0f, (std::min)(32000.0f, s)));
            }
        };
        click(pcm[0], 0.0f, 900.0f, 90.0f, 0.8f);                                    // the magazine released
        click(pcm[1], 0.0f, 1500.0f, 120.0f, 0.7f); click(pcm[1], 0.035f, 2100.0f, 160.0f, 1.0f);   // seated
        click(pcm[2], 0.0f, 1800.0f, 110.0f, 0.8f); click(pcm[2], 0.11f, 2400.0f, 140.0f, 1.0f);    // back and home
        for (int i = 0; i < 3; ++i) {
            hdr[i] = {};
            hdr[i].lpData = reinterpret_cast<LPSTR>(pcm[i].data());
            hdr[i].dwBufferLength = static_cast<DWORD>(pcm[i].size() * sizeof(int16_t));
            waveOutPrepareHeader(out, &hdr[i], sizeof(WAVEHDR));
        }
    }
    if (!out) return;
    if ((hdr[kind].dwFlags & WHDR_INQUEUE) && !(hdr[kind].dwFlags & WHDR_DONE)) return;   // still playing
    hdr[kind].dwFlags &= ~WHDR_DONE;
    waveOutWrite(out, &hdr[kind], sizeof(WAVEHDR));
    static int logged = 0;
    if (logged < 60) { ++logged; Log("reload: click %d", kind); }
}
// A magazine (or a rocket) as a particle: dark, falling to the ground beside him
// and lying there a moment (kind 6); held, a particle of one frame's life.
void ShotSpawnMag(float x, float y, float z, float vx, float vy, float vz, float life, float floorY, bool rocket);
// Clips written as upper-body layers (only Bip01 Spine1 and up): drawn blended
// at just under full weight over the walk, run or idle so the legs keep moving
// (model_store.cpp: a joint the second clip leaves alone keeps the first's).
bool IsUpperLayer(int action) {
    // ACTIONS-3D-4: the fists (1), the car door (5, 6), taking a punch (22) and running
    // beside a moving car with a hand on its door (23) too.
    return action == 1 || action == 2 || action == 3 || action == 5 || action == 6 ||
           (action >= 8 && action <= 18 && action != 9) || action == 19 || action == 21 || action == 22 || action == 23 ||
           IsReloadAction(action);   // QB-29
}

// The particles the shots leave: a muzzle glow, sparks, a brass case, blood,
// the smoke behind a rocket, the arc of the electro gun. Camera-facing quads,
// all in one buffer a frame, added (sparks, glows) or blended (the rest).
struct ShotParticle {
    float x, y, z, vx, vy, vz;
    float life, age, size0, size1;
    float r, g, b, a;
    uint8_t kind;   // 0 spark, 1 shell, 2 blood, 3 smoke, 4 glow, 5 arc, 6 magazine (QB-29)
    float floorY = -1e9f;   // kind 6: the ground it comes to rest on
};
std::vector<ShotParticle> g_shotParticles;
// The muzzle lights, held for the frame they were seen on and the next: the
// world pass submits them when the frame's invented lights are listed
// (ShotLightsSubmit, before LightsReconcile).
struct ShotLight { RemixLightDesc desc; uint32_t frame; };
std::vector<ShotLight> g_shotLights;
IDirect3DTexture9* g_shotGlowTexture = nullptr;
float ShotRand() {
    static uint32_t st = 0x9E3779B9u;
    st ^= st << 13; st ^= st >> 17; st ^= st << 5;
    return static_cast<float>(st & 0xFFFFFFu) / 16777216.0f;
}
void ShotSpawn(float x, float y, float z, float vx, float vy, float vz, float life, float s0, float s1,
               float r, float g, float b, float a, uint8_t kind) {
    if (!g_uprightPeds) return;   // the street-level views only: the top-down view keeps the game's own art
    if (g_shotParticles.size() >= 1200) g_shotParticles.erase(g_shotParticles.begin());
    static int logged = 0;
    if (logged < 40) { ++logged; Log("shot fx: kind %d size %.3f..%.3f life %.2f at %.2f,%.2f,%.2f v %.2f,%.2f,%.2f", kind, s0, s1, life, x, y, z, vx, vy, vz); }
    s0 = (std::min)(s0, 0.6f); s1 = (std::min)(s1, 0.6f);
    g_shotParticles.push_back({x, y, z, vx, vy, vz, life, 0.0f, s0, s1, r, g, b, a, kind});
}
void ShotSpawnMag(float x, float y, float z, float vx, float vy, float vz, float life, float floorY, bool rocket) {
    if (!g_uprightPeds) return;
    if (g_shotParticles.size() >= 1200) g_shotParticles.erase(g_shotParticles.begin());
    ShotParticle p = {x, y, z, vx, vy, vz, life, 0.0f, rocket ? 0.020f : 0.014f, rocket ? 0.020f : 0.014f,
                      rocket ? 0.30f : 0.10f, rocket ? 0.32f : 0.10f, rocket ? 0.22f : 0.11f, 1.0f, 6};
    p.floorY = floorY;
    g_shotParticles.push_back(p);
}
// A soft round spot: white, alpha falling off to the edge.
IDirect3DTexture9* ShotGlowTexture(IDirect3DDevice9* device) {
    if (g_shotGlowTexture) return g_shotGlowTexture;
    constexpr int N = 32;
    IDirect3DTexture9* made = nullptr;
    if (FAILED(device->CreateTexture(N, N, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &made, nullptr))) return nullptr;
    D3DLOCKED_RECT lr;
    if (FAILED(made->LockRect(0, &lr, nullptr, 0))) { made->Release(); return nullptr; }
    for (int y = 0; y < N; ++y) {
        uint32_t* out = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
        for (int x = 0; x < N; ++x) {
            const float dx = (x + 0.5f) / N - 0.5f, dy = (y + 0.5f) / N - 0.5f;
            const float r = (std::min)(1.0f, std::sqrt(dx * dx + dy * dy) * 2.0f);
            const float a = (1.0f - r) * (1.0f - r);
            const uint32_t av = static_cast<uint32_t>(a * 255.0f + 0.5f);
            // The falloff in the colour too: the added pass ignores the alpha.
            out[x] = (av << 24) | (av << 16) | (av << 8) | av;
        }
    }
    made->UnlockRect(0);
    g_shotGlowTexture = made;
    return made;
}
// What leaves the muzzle on a shot: the flash as a glow with a Remix light in
// it, sparks ahead, a case out of the right side, the electro gun's arc.
void ShotFxMuzzle(int weapon, const float* pos, const float* dir, const float* right, const float* up, bool firstPerson) {
    if (weapon <= 0 || weapon >= kWpnCount) return;
    const WeaponInfo& wi = kWeapons[weapon];
    if (wi.flashSize > 0.0f) {
        const float fs = wi.flashSize * (0.85f + 0.3f * ShotRand()) * (firstPerson ? 0.55f : 1.0f);
        ShotSpawn(pos[0] + dir[0] * fs * 0.3f, pos[1] + dir[1] * fs * 0.3f, pos[2] + dir[2] * fs * 0.3f, 0, 0, 0,
                  0.07f, fs, fs * 1.3f, wi.r, wi.g, wi.b, 1.0f, 4);
        // A smaller, whiter core.
        ShotSpawn(pos[0] + dir[0] * fs * 0.15f, pos[1] + dir[1] * fs * 0.15f, pos[2] + dir[2] * fs * 0.15f, 0, 0, 0,
                  0.05f, fs * 0.45f, fs * 0.5f, 1.0f, 1.0f, 0.9f, 1.0f, 4);
        const int sparks = weapon == kWpnShotgun ? 8 : (weapon == kWpnFlame ? 0 : 3);
        for (int i = 0; i < sparks; ++i) {
            const float sp = 2.5f + 2.0f * ShotRand();
            const float sx = (ShotRand() - 0.5f) * 1.2f, sy = (ShotRand() - 0.5f) * 1.2f;
            ShotSpawn(pos[0], pos[1], pos[2], (dir[0] + right[0] * sx + up[0] * sy) * sp, (dir[1] + right[1] * sx + up[1] * sy) * sp,
                      (dir[2] + right[2] * sx + up[2] * sy) * sp, 0.12f + 0.08f * ShotRand(), 0.012f, 0.004f,
                      1.0f, 0.85f, 0.5f, 1.0f, 0);
        }
        RemixLightDesc d;
        d.pos[0] = pos[0] + dir[0] * 0.05f; d.pos[1] = pos[1] + dir[1] * 0.05f + 0.02f; d.pos[2] = pos[2] + dir[2] * 0.05f;
        d.rgb[0] = wi.r; d.rgb[1] = wi.g; d.rgb[2] = wi.b;
        d.intensity = wi.light;
        d.radius = 2.5f;
        d.emitterRadius = 0.03f;
        g_shotLights.push_back({d, g_carFrame});
    }
    if (wi.shells) {
        // Out of the ejection port, up and to the right, tumbling down.
        const float back = firstPerson ? 0.10f : 0.5f * wi.length;
        const float ex = pos[0] - dir[0] * back + right[0] * 0.015f, ey = pos[1] - dir[1] * back + right[1] * 0.015f + 0.01f,
                    ez = pos[2] - dir[2] * back + right[2] * 0.015f;
        const float vr = 0.45f + 0.3f * ShotRand(), vu = 0.6f + 0.3f * ShotRand(), vb = -0.1f + 0.2f * ShotRand();
        ShotSpawn(ex, ey, ez, right[0] * vr + up[0] * vu + dir[0] * vb, right[1] * vr + up[1] * vu + dir[1] * vb,
                  right[2] * vr + up[2] * vu + dir[2] * vb, 0.7f, 0.009f, 0.009f, 0.85f, 0.7f, 0.3f, 1.0f, 1);
    }
    if (weapon == kWpnElectro) {
        // The arc: a jagged line of short-lived sparks a block and a half out.
        float px = pos[0], py = pos[1], pz = pos[2];
        for (int i = 0; i < 14; ++i) {
            const float jx = (ShotRand() - 0.5f) * 0.08f, jy = (ShotRand() - 0.5f) * 0.08f;
            px += dir[0] * 0.11f + right[0] * jx + up[0] * jy;
            py += dir[1] * 0.11f + right[1] * jx + up[1] * jy;
            pz += dir[2] * 0.11f + right[2] * jx + up[2] * jy;
            ShotSpawn(px, py, pz, 0, 0, 0, 0.06f, 0.035f, 0.02f, 0.65f, 0.9f, 1.0f, 1.0f, 5);
        }
    }
}
void ShotFxSparks(float x, float y, float z) {
    for (int i = 0; i < 7; ++i) {
        const float a = ShotRand() * 6.2831853f, e = ShotRand() * 1.4f, sp = 0.8f + 1.4f * ShotRand();
        ShotSpawn(x, y, z, std::cos(a) * std::cos(e) * sp, std::sin(e) * sp, std::sin(a) * std::cos(e) * sp,
                  0.18f + 0.15f * ShotRand(), 0.014f, 0.004f, 1.0f, 0.8f, 0.45f, 1.0f, 0);
    }
    ShotSpawn(x, y, z, 0, 0, 0, 0.06f, 0.07f, 0.09f, 1.0f, 0.75f, 0.4f, 0.8f, 4);
}
void ShotFxBlood(float x, float y, float z) {
    for (int i = 0; i < 6; ++i) {
        const float a = ShotRand() * 6.2831853f, sp = 0.15f + 0.35f * ShotRand();
        ShotSpawn(x + (ShotRand() - 0.5f) * 0.04f, y + (ShotRand() - 0.5f) * 0.06f, z + (ShotRand() - 0.5f) * 0.04f,
                  std::cos(a) * sp, 0.1f + 0.3f * ShotRand(), std::sin(a) * sp, 0.3f + 0.2f * ShotRand(),
                  0.02f, 0.06f, 0.45f, 0.03f, 0.03f, 0.85f, 2);
    }
}
void ShotFxSmoke(float x, float y, float z) {
    ShotSpawn(x + (ShotRand() - 0.5f) * 0.03f, y, z + (ShotRand() - 0.5f) * 0.03f, (ShotRand() - 0.5f) * 0.08f, 0.08f,
              (ShotRand() - 0.5f) * 0.08f, 0.8f + 0.4f * ShotRand(), 0.05f, 0.26f, 0.7f, 0.7f, 0.72f, 0.45f, 3);
}
// Ages and draws the particles. After the figures and the game's effects.
void ShotFxDraw(IDirect3DDevice9* device, float dt) {
    for (size_t i = 0; i < g_shotParticles.size();) {
        ShotParticle& sp = g_shotParticles[i];
        sp.age += dt;
        if (sp.age >= sp.life) { sp = g_shotParticles.back(); g_shotParticles.pop_back(); continue; }
        if (sp.kind == 0 || sp.kind == 1 || sp.kind == 2 || sp.kind == 6) sp.vy -= (sp.kind == 2 ? 1.2f : 2.8f) * dt;   // gravity
        sp.x += sp.vx * dt; sp.y += sp.vy * dt; sp.z += sp.vz * dt;
        if (sp.kind == 6 && sp.y < sp.floorY) { sp.y = sp.floorY; sp.vx = sp.vy = sp.vz = 0.0f; }   // a magazine at rest
        ++i;
    }
    if (g_shotParticles.empty()) return;
    IDirect3DTexture9* texture = ShotGlowTexture(device);
    if (!texture) return;
    // Camera-facing: the eye's right and up.
    const gta2::Vec3 f = g_viewForward;
    float rx = f.z, rz = -f.x;
    const float rl = (std::max)(1e-4f, std::sqrt(rx * rx + rz * rz));
    rx /= rl; rz /= rl;
    // up = cross(right, forward) with right = (rx, 0, rz).
    const float Ux = -rz * f.y, Uy = rz * f.x - rx * f.z, Uz = rx * f.y;
    struct PV { float x, y, z; DWORD color; float u, v; };
    static const uint16_t quad[6] = {0, 1, 2, 0, 2, 3};
    std::vector<PV> add, blend;
    std::vector<uint16_t> addIdx, blendIdx;
    for (const ShotParticle& sp : g_shotParticles) {
        const float t = sp.age / sp.life;
        const float size = sp.size0 + (sp.size1 - sp.size0) * t;
        float alpha = sp.a;
        if (sp.kind == 0 || sp.kind == 5) alpha *= 1.0f - t;
        else if (sp.kind == 4) alpha *= 1.0f - t * t;
        else if (sp.kind == 2) alpha *= 1.0f - t;
        else if (sp.kind == 3) alpha *= (t < 0.1f ? t / 0.1f : 1.0f) * (1.0f - t) * (1.0f - t);
        else if (sp.kind == 6 && sp.life > 0.2f) alpha *= t > 0.8f ? (1.0f - t) / 0.2f : 1.0f;
        const bool additive = sp.kind == 0 || sp.kind == 4 || sp.kind == 5;
        const float lv = additive ? alpha : 1.0f;
        const DWORD c = D3DCOLOR_COLORVALUE(sp.r * lv, sp.g * lv, sp.b * lv, additive ? 1.0f : alpha);
        std::vector<PV>& v = additive ? add : blend;
        std::vector<uint16_t>& ix = additive ? addIdx : blendIdx;
        if (v.size() > 60000) continue;
        const uint16_t base = static_cast<uint16_t>(v.size());
        float ax = rx * size, ay = 0.0f, az = rz * size, bx = Ux * size, by = Uy * size, bz = Uz * size;
        if (sp.kind == 6) {
            // A magazine: an upright bar (a rocket: a fatter one), along its fall
            // while it falls.
            const float vl = std::sqrt(sp.vx * sp.vx + sp.vy * sp.vy + sp.vz * sp.vz);
            if (vl > 0.05f) { bx = sp.vx / vl * size * 2.2f; by = sp.vy / vl * size * 2.2f; bz = sp.vz / vl * size * 2.2f; }
            else { bx = 0.0f; by = size * 2.2f; bz = 0.0f; }
            ax = by * f.z - bz * f.y; ay = bz * f.x - bx * f.z; az = bx * f.y - by * f.x;
            const float al = (std::max)(1e-4f, std::sqrt(ax * ax + ay * ay + az * az));
            ax = ax / al * size * 0.8f; ay = ay / al * size * 0.8f; az = az / al * size * 0.8f;
        } else if (sp.kind == 0 || sp.kind == 1) {
            // A spark or a case: stretched along its motion.
            const float vl = std::sqrt(sp.vx * sp.vx + sp.vy * sp.vy + sp.vz * sp.vz);
            if (vl > 0.05f) {
                const float st = sp.kind == 0 ? (std::min)(6.0f, 1.0f + vl * 2.0f) : 1.8f;
                bx = sp.vx / vl * size * st; by = sp.vy / vl * size * st; bz = sp.vz / vl * size * st;
                // Perpendicular to the motion and the line of sight.
                ax = by * f.z - bz * f.y; ay = bz * f.x - bx * f.z; az = bx * f.y - by * f.x;
                const float al = (std::max)(1e-4f, std::sqrt(ax * ax + ay * ay + az * az));
                ax = ax / al * size; ay = ay / al * size; az = az / al * size;
            }
        }
        v.push_back({sp.x - ax - bx, sp.y - ay - by, sp.z - az - bz, c, 0.0f, 1.0f});
        v.push_back({sp.x - ax + bx, sp.y - ay + by, sp.z - az + bz, c, 0.0f, 0.0f});
        v.push_back({sp.x + ax + bx, sp.y + ay + by, sp.z + az + bz, c, 1.0f, 0.0f});
        v.push_back({sp.x + ax - bx, sp.y + ay - by, sp.z + az - bz, c, 1.0f, 1.0f});
        for (uint16_t q : quad) ix.push_back(static_cast<uint16_t>(base + q));
    }
    if (add.empty() && blend.empty()) return;
    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    device->SetTexture(0, texture);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_DIFFUSE | D3DFVF_TEX1);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    if (!blend.empty()) {
        device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
        device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
        device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(blend.size()), static_cast<UINT>(blendIdx.size() / 3),
                                       blendIdx.data(), D3DFMT_INDEX16, blend.data(), sizeof(PV));
    }
    if (!add.empty()) {
        device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
        device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_ONE);
        device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(add.size()), static_cast<UINT>(addIdx.size() / 3),
                                       addIdx.data(), D3DFMT_INDEX16, add.data(), sizeof(PV));
    }
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetTexture(0, nullptr);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
}
// The fresh effects nobody claimed as his shot and that did not fly off as a
// bullet: impacts. Sparks on a wall; blood when it is beside a figure.
void ShotFxImpacts() {
    for (const FxFresh& fx : g_fxFreshLast) {
        if (fx.claimed) continue;
        auto seen = g_fxSeen.find(fx.object);
        if (seen != g_fxSeen.end() && seen->second.flying) continue;
        if (fx.size > 0.16f) continue;   // an explosion, a flame: the game's own art
        bool onPed = false;
        for (const PedSpot& p : g_pedSpots) {
            const float dx = p.x - fx.x, dz = p.z - fx.z;
            if (dx * dx + dz * dz < 0.09f) { onPed = true; break; }
        }
        if (onPed) ShotFxBlood(fx.x, fx.y + 0.28f, fx.z);
        else ShotFxSparks(fx.x, fx.y + 0.30f, fx.z);
    }
}
// First person: the player's weapon as a view model, lower right of the eye,
// with the same kick on a shot (the shot: a fresh flash or bullet just ahead
// of the eye, since the player's own sprite is not seen in this view). Drawn
// over everything (no depth test), after the figures.
void DrawViewModel(IDirect3DDevice9* device, const gta2::Camera& camera) {
    if (CurrentViewMode() != ViewMode::FirstPerson || !g_playerObject || g_hiddenObjects[0] != g_playerObject || !g_pedWeapons) return;
    const gta2::Vec3 eye = camera.Position();
    const gta2::Vec3 f = g_viewForward;
    // FIX-FIGURE (fp-viewmodel-box-gun-no-hands): this frame's fresh effects too
    // (the sprites were issued before this call), so the 3D flash lands on the
    // frame the game fires, not one later beside the game's own flash.
    for (std::vector<FxFresh>* list : {&g_fxFreshLast, &g_fxFreshNow}) {
        for (FxFresh& fx : *list) {
            if (fx.claimed) continue;
            const float dx = fx.x - eye.x, dy = fx.y - eye.y, dz = fx.z - eye.z;
            if (dx * dx + dz * dz < 1.44f && std::fabs(dy) < 0.8f && dx * f.x + dz * f.z > 0.0f) {
                fx.claimed = true;
                if (g_carFrame - g_fpShotFrame >= 3) g_fpShotFrame = g_carFrame;
            }
        }
    }
    {
        // QB-16: his figure is not drawn here, so it left no FigureSpot: the eye stands
        // in for it (where he is, the way he looks, his last shot from his ammunition
        // word or a flash ahead), so the man he shoots reacts in this view too.
        static int32_t lastAmmo = -1;
        static uint32_t shotFrame = 0;
        if (g_playerWeapon > 0 && lastAmmo >= 0 && g_playerAmmo < lastAmmo) shotFrame = g_carFrame;
        if (g_fpShotFrame == g_carFrame) shotFrame = g_carFrame;
        lastAmmo = g_playerWeapon > 0 ? g_playerAmmo : -1;
        const float fl = std::sqrt(f.x * f.x + f.z * f.z);
        if (g_playerPosValid && fl > 1e-3f)
            g_figuresNow.push_back({reinterpret_cast<uintptr_t>(g_playerObject), g_playerPosX, g_playerPosZ, false, false, shotFrame,
                                    f.x / fl, f.z / fl, g_playerWeapon > 0 ? g_playerWeapon : kWpnPistol});
    }
    // The game's word (0: bare hands, nothing drawn); without it, the weapon the
    // figure was last drawn with, shown only around a shot.
    int weapon = g_playerWeapon >= 0 && g_playerWeapon < kWpnCount ? g_playerWeapon : g_playerWeaponSeen;
    if (g_playerWeapon < 0 && weapon <= 0 && g_fpShotFrame && g_carFrame - g_fpShotFrame < 90) weapon = kWpnPistol;
    if (weapon <= 0 || weapon >= kWpnCount) return;
    if (g_playerWeapon < 0 && (!g_fpShotFrame || g_carFrame - g_fpShotFrame > 150)) return;
    const WeaponInfo& wi = kWeapons[weapon];
    const Model* model = ModelByName(wi.model);
    if (!model) return;
    // The eye's frame.
    float right[3] = {f.z, 0.0f, -f.x};
    const float rl = (std::max)(1e-4f, std::sqrt(right[0] * right[0] + right[2] * right[2]));
    right[0] /= rl; right[2] /= rl;
    // up = cross(forward, right): the eye's up, as the particles use it.
    float up[3] = {f.y * right[2], f.z * right[0] - f.x * right[2], -f.y * right[0]};
    // The kick: up to full in two frames, back over ~0.15 s (rise, a little roll).
    const float shotT = g_fpShotFrame ? static_cast<float>(g_carFrame - g_fpShotFrame) / 30.0f : 10.0f;
    const float kick = shotT < 0.034f ? 0.6f + 0.4f * shotT / 0.034f : (shotT > 0.25f ? 0.0f : std::exp(-(shotT - 0.034f) / 0.05f));
    const bool thrown = wi.action == 13;
    // QB-29: the reload, from the game's words for the player (the figure, whose
    // shots drive it in the other views, is not drawn here): the same magazine
    // count (kReloads) off his weapon's ammunition, timed in real seconds.
    static int rlWeapon = -1, rlShots = 0;
    static int32_t rlAmmo = -1;
    static uint32_t rlLastShot = 0;
    static DWORD rlStart = 0;
    static float rlPrevT = -1.0f;
    float reloadT = -1.0f;
    const ReloadInfo& ri = kReloads[weapon];
    if (ReloadOn() && ri.mag > 0 && g_playerWeapon == weapon) {
        if (weapon != rlWeapon) { rlWeapon = weapon; rlShots = 0; rlStart = 0; rlAmmo = g_playerAmmo; }
        const bool shot = rlAmmo >= 0 && g_playerAmmo < rlAmmo;
        if (shot) { ++rlShots; rlLastShot = g_carFrame; }
        else if (rlAmmo >= 0 && g_playerAmmo > rlAmmo && rlShots > 0) rlShots = ri.mag;   // a pickup
        rlAmmo = g_playerAmmo;
        if (shot) {   // not a fresh effect ahead: the last bullets still fly after the trigger is let go
            rlStart = 0;
        } else if (!rlStart && rlShots >= ri.mag && g_carFrame - rlLastShot >= 9) {
            rlStart = GetTickCount() | 1u;
            rlShots = 0;
            rlPrevT = -1.0f;
            Log("reload: first person %s starts (magazine %d)", wi.name, ri.mag);
        }
        if (rlStart) {
            reloadT = static_cast<float>(GetTickCount() - rlStart) / 1000.0f;
            if (reloadT >= ri.len) { rlStart = 0; reloadT = -1.0f; }
        }
    } else {
        rlStart = 0;
    }
    // Down and in, the muzzle up and the gun rolled to show its side, back up at
    // the end; a jolt back on the slide or the charging handle.
    float rs = 0.0f, rack = 0.0f;
    if (reloadT >= 0.0f) {
        const float u = reloadT / ri.len;
        rs = (std::min)(1.0f, (std::min)(u / 0.18f, (1.0f - u) / 0.22f));
        rs = rs * rs * (3.0f - 2.0f * rs);
        if (ri.rackT >= 0.0f && reloadT >= ri.rackT && reloadT < ri.rackT + 0.12f) rack = 1.0f - (reloadT - ri.rackT) / 0.12f;
    }
    const float ahead = (wi.twoHanded ? 0.20f : 0.155f) - wi.kick * kick - 0.02f * rs - 0.02f * rack;
    const float side = (wi.twoHanded ? 0.055f : 0.075f) - 0.015f * rs,
                down = (wi.twoHanded ? 0.075f : 0.066f) + (thrown ? 0.02f : 0.0f) + 0.07f * rs - 0.006f * kick;
    float pos[3];
    for (int c = 0; c < 3; ++c) pos[c] = (&eye.x)[c] + (&f.x)[c] * ahead + right[c] * side - up[c] * down;
    // The barrel on the crosshair: aimed at the point 5 blocks along the view
    // (the line of the shot), tipped up by the kick and the reload.
    float dir[3];
    {
        float aim[3];
        for (int c = 0; c < 3; ++c) aim[c] = (&eye.x)[c] + (&f.x)[c] * 5.0f - pos[c];
        const float al = (std::max)(1e-4f, std::sqrt(aim[0] * aim[0] + aim[1] * aim[1] + aim[2] * aim[2]));
        for (int c = 0; c < 3; ++c) dir[c] = aim[c] / al + up[c] * (0.16f * kick * (wi.twoHanded ? 0.6f : 1.0f) + 0.22f * rs) - right[c] * 0.05f * rs;
    }
    const float dl = (std::max)(1e-4f, std::sqrt(dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]));
    for (float& v : dir) v /= dl;
    float wr[3] = {dir[2], 0.0f, -dir[0]};
    const float wrl = (std::max)(1e-4f, std::sqrt(wr[0] * wr[0] + wr[2] * wr[2]));
    wr[0] /= wrl; wr[2] /= wrl;
    float wu[3] = {dir[1] * wr[2] - dir[2] * wr[1], dir[2] * wr[0] - dir[0] * wr[2], dir[0] * wr[1] - dir[1] * wr[0]};
    if (rs > 0.0f || kick > 0.0f) {
        // Rolled about the barrel: the magazine well toward the eye on a reload,
        // a few degrees to the right on a shot.
        const float roll = -0.75f * rs - 0.10f * kick;
        const float ca = std::cos(roll), sa = std::sin(roll);
        for (int c = 0; c < 3; ++c) { const float r0 = wr[c], u0 = wu[c]; wr[c] = r0 * ca + u0 * sa; wu[c] = u0 * ca - r0 * sa; }
    }
    if (reloadT >= 0.0f) {
        auto crossed = [&](float e) { return e >= 0.0f && rlPrevT < e && reloadT >= e; };
        if (crossed(ri.dropT)) {
            ShotSpawnMag(pos[0] - wu[0] * 0.03f, pos[1] - wu[1] * 0.03f, pos[2] - wu[2] * 0.03f, right[0] * 0.1f - up[0] * 0.4f,
                         -0.4f * up[1], right[2] * 0.1f - up[2] * 0.4f, 1.5f, eye.y - 0.9f, false);
            ReloadClick(0);
            Log("reload: first person magazine out at t=%.2f", reloadT);
        }
        if (reloadT >= ri.grabT && reloadT < ri.insertT) {
            // The fresh magazine rising from below into the well.
            const float u2 = (reloadT - ri.grabT) / (std::max)(0.05f, ri.insertT - ri.grabT);
            float m[3];
            for (int c = 0; c < 3; ++c) m[c] = pos[c] - up[c] * (0.02f + 0.13f * (1.0f - u2)) - right[c] * 0.04f * (1.0f - u2) + (&f.x)[c] * 0.02f;
            ShotSpawnMag(m[0], m[1], m[2], 0.0f, 0.0f, 0.0f, 0.045f, -1e9f, weapon == kWpnRocket);
        }
        if (crossed(ri.insertT)) { ReloadClick(1); Log("reload: first person magazine in at t=%.2f", reloadT); }
        if (crossed(ri.rackT)) ReloadClick(2);
        rlPrevT = reloadT;
    }
    const float k = (wi.length * (wi.twoHanded ? 1.2f : 1.4f)) / (std::max)(0.01f, WeaponSpan(*model));
    static int logged = 0;
    if (logged < 12) { ++logged; Log("view model: %s at %.2f,%.2f,%.2f dir %.2f,%.2f,%.2f up %.2f,%.2f,%.2f k %.3f kick %.2f", wi.name, pos[0], pos[1], pos[2], dir[0], dir[1], dir[2], up[0], up[1], up[2], k, kick); }
    gta2::Mat4 place;
    for (int c = 0; c < 3; ++c) { place.m[0][c] = wr[c] * k; place.m[1][c] = wu[c] * k; place.m[2][c] = dir[c] * k; place.m[3][c] = pos[c]; }
    place.m[3][3] = 1.0f;
    // FIX-FIGURE: the hands (tools/gen_weapons.py fp_arm_*: the right fist round
    // the grip at the gun's origin, the left on the fore grip or cupping the
    // fist), in the gun's frame at one size for every weapon, so they kick with it.
    const float kHand = 1.30f;
    auto handAt = [&](float gx, float gy, float gz, bool mirror) {
        gta2::Mat4 m;
        for (int c = 0; c < 3; ++c) {
            m.m[0][c] = wr[c] * kHand * (mirror ? -1.0f : 1.0f); m.m[1][c] = wu[c] * kHand; m.m[2][c] = dir[c] * kHand;
            m.m[3][c] = pos[c] + (wr[c] * gx + wu[c] * gy + dir[c] * gz) * k;
        }
        m.m[3][3] = 1.0f;
        return m;
    };
    // The support hand's place on each weapon (its model's units, the fore grip).
    float fore[3] = {0.0f, 0.0f, 0.0f};
    const char* leftName = nullptr;
    switch (weapon) {
        case kWpnPistol: leftName = "fp_arm_left_cup"; break;
        case kWpnMg: leftName = "fp_arm_left"; fore[1] = 0.000f; fore[2] = 0.090f; break;
        case kWpnSilencedMg: leftName = "fp_arm_left"; fore[1] = 0.010f; fore[2] = 0.045f; break;
        case kWpnShotgun: leftName = "fp_arm_left"; fore[1] = 0.004f; fore[2] = 0.080f; break;
        case kWpnRocket: leftName = "fp_arm_left"; fore[1] = 0.004f; fore[2] = 0.060f; break;
        case kWpnFlame: leftName = "fp_arm_left"; fore[1] = 0.000f; fore[2] = 0.060f; break;
        case kWpnElectro: leftName = "fp_arm_left"; fore[1] = 0.004f; fore[2] = 0.030f; break;
        default: break;
    }
    const bool leftBusy = reloadT >= 0.0f && reloadT > ri.dropT && reloadT < ri.insertT + 0.1f;   // fetching the magazine
    const Model* armR = ModelByName("fp_arm_right");
    const Model* armL = (leftName && !leftBusy) ? ModelByName(leftName) : nullptr;
    const Model* armDual = weapon == kWpnDual ? armR : nullptr;
    // Lit by the sun the car bodies use (dimmer at night), the texture modulated
    // by it, so the gun and hands have shape. The depth range squeezed to the
    // front: they cover each other properly and the world never cuts into them.
    DWORD zEnable = TRUE, zWrite = TRUE, zFunc = D3DCMP_LESSEQUAL, colorOp = 0, colorArg1 = 0, colorArg2 = 0, alphaTest = 0, cull = D3DCULL_CCW, lighting = FALSE;
    device->GetRenderState(D3DRS_ZENABLE, &zEnable);
    device->GetRenderState(D3DRS_ZWRITEENABLE, &zWrite);
    device->GetRenderState(D3DRS_ZFUNC, &zFunc);
    device->GetRenderState(D3DRS_ALPHATESTENABLE, &alphaTest);
    device->GetRenderState(D3DRS_CULLMODE, &cull);
    device->GetRenderState(D3DRS_LIGHTING, &lighting);
    device->GetTextureStageState(0, D3DTSS_COLOROP, &colorOp);
    device->GetTextureStageState(0, D3DTSS_COLORARG1, &colorArg1);
    device->GetTextureStageState(0, D3DTSS_COLORARG2, &colorArg2);
    D3DVIEWPORT9 vp = {};
    const bool haveVp = SUCCEEDED(device->GetViewport(&vp));
    if (haveVp) { D3DVIEWPORT9 vpNear = vp; vpNear.MinZ = 0.0f; vpNear.MaxZ = 0.002f; device->SetViewport(&vpNear); }
    device->SetRenderState(D3DRS_ZENABLE, TRUE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device->SetRenderState(D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    {
        const bool night = gta2::SkyConfig().sunElevationDeg < 6.0f;
        D3DLIGHT9 sun = {};
        sun.Type = D3DLIGHT_DIRECTIONAL;
        const float li = night ? 0.45f : 0.80f;
        sun.Diffuse = {li, li, li, 1.0f};
        // From above, a little ahead and to the left of the eye: the top of the
        // slide and the back of the hand catch it.
        float ld[3];
        for (int c = 0; c < 3; ++c) ld[c] = -up[c] * 0.85f + (&f.x)[c] * 0.35f + right[c] * 0.40f;
        const float ll = std::sqrt(ld[0] * ld[0] + ld[1] * ld[1] + ld[2] * ld[2]);
        sun.Direction = {ld[0] / ll, ld[1] / ll, ld[2] / ll};
        device->SetLight(0, &sun);
        device->LightEnable(0, TRUE);
        device->LightEnable(1, FALSE);
        D3DMATERIAL9 material = {};
        material.Diffuse = {1.0f, 1.0f, 1.0f, 1.0f};
        material.Ambient = {1.0f, 1.0f, 1.0f, 1.0f};
        device->SetMaterial(&material);
        device->SetRenderState(D3DRS_LIGHTING, TRUE);
        device->SetRenderState(D3DRS_AMBIENT, night ? 0x00404048u : 0x00686868u);
        device->SetRenderState(D3DRS_SPECULARENABLE, FALSE);
        device->SetRenderState(D3DRS_NORMALIZENORMALS, TRUE);
        device->SetRenderState(D3DRS_COLORVERTEX, FALSE);
        device->SetRenderState(D3DRS_DIFFUSEMATERIALSOURCE, D3DMCS_MATERIAL);
        device->SetRenderState(D3DRS_AMBIENTMATERIALSOURCE, D3DMCS_MATERIAL);
    }
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetFVF(kWorldFvf);
    ModelDraw(device, *model, place, nullptr, 0.0f);
    if (armR) ModelDraw(device, *armR, handAt(0.0f, 0.0f, 0.0f, false), nullptr, 0.0f);
    if (armL) ModelDraw(device, *armL, handAt(fore[0], fore[1], fore[2], false), nullptr, 0.0f);
    if (weapon == kWpnDual) {
        gta2::Mat4 other = place;
        for (int c = 0; c < 3; ++c) other.m[3][c] = pos[c] - right[c] * 2.0f * side;
        ModelDraw(device, *model, other, nullptr, 0.0f);
        if (armDual) {
            // The left gun's hand: the right's mirror, at the left gun.
            gta2::Mat4 h = handAt(0.0f, 0.0f, 0.0f, true);
            for (int c = 0; c < 3; ++c) h.m[3][c] = other.m[3][c];
            ModelDraw(device, *armDual, h, nullptr, 0.0f);
        }
    }
    {
        static bool armsLogged = false;
        if (!armsLogged) { armsLogged = true; Log("view model: hands %s/%s", armR ? "fp_arm_right" : "missing", leftName ? (armL ? leftName : "missing") : "none"); }
    }
    if (haveVp) device->SetViewport(&vp);
    device->SetRenderState(D3DRS_LIGHTING, lighting);
    device->SetRenderState(D3DRS_ZENABLE, zEnable);
    device->SetRenderState(D3DRS_ZWRITEENABLE, zWrite);
    device->SetRenderState(D3DRS_ZFUNC, zFunc);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, alphaTest);
    device->SetRenderState(D3DRS_CULLMODE, cull);
    device->SetTextureStageState(0, D3DTSS_COLOROP, colorOp);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, colorArg1);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, colorArg2);
    device->SetTexture(0, nullptr);
    if (g_fpShotFrame == g_carFrame && !thrown) {
        float muzzle[3];
        for (int c = 0; c < 3; ++c) muzzle[c] = pos[c] + dir[c] * model->boundsMax.z * k;
        ShotFxMuzzle(weapon, muzzle, dir, wr, wu, true);
    }
}

// Bullets that stopped beside a figure: blood where they ended. Called at the
// start of a frame, before the effects are seen again.
void ShotFxBulletEnds() {
    for (auto it = g_fxSeen.begin(); it != g_fxSeen.end();) {
        const uint32_t age = g_carFrame - it->second.frame;
        if (age == 2 && it->second.flying) {
            for (const PedSpot& p : g_pedSpots) {
                const float dx = p.x - it->second.x, dz = p.z - it->second.z;
                if (dx * dx + dz * dz < 0.12f) { ShotFxBlood(it->second.x, it->second.y + 0.28f, it->second.z); break; }
            }
        }
        it = age > 120 ? g_fxSeen.erase(it) : std::next(it);
    }
}

// A box hanging from a pivot: its top face is `drop` below the pivot (0 for a
// box centred on it), swung by `swing` radians about the pivot's x axis.
void AddBox(std::vector<FigVertex>* out, float px, float py, float pz, float sx, float sy, float sz,
            float drop, float swing, DWORD color) {
    const float c = std::cos(swing), s = std::sin(swing);
    auto place = [&](float x, float y, float z, float nx, float ny, float nz) {
        // Local box space: y runs down from the pivot.
        const float ly = -drop - y, lz = z;
        const float ry = ly * c - lz * s, rz = ly * s + lz * c;
        const float rny = ny * c - nz * s, rnz = ny * s + nz * c;
        return FigVertex{px + x, py + ry, pz + rz, nx, rny, rnz, color};
    };
    const float hx = sx * 0.5f, hz = sz * 0.5f;
    // Faces as two triangles each; (x, y, z) with y from 0 (top) to sy (bottom).
    struct Face { float nx, ny, nz; float v[4][3]; };
    const Face faces[6] = {
        {0, 0, -1, {{-hx, 0, -hz}, {hx, 0, -hz}, {hx, sy, -hz}, {-hx, sy, -hz}}},    // back
        {0, 0, 1, {{hx, 0, hz}, {-hx, 0, hz}, {-hx, sy, hz}, {hx, sy, hz}}},          // front
        {-1, 0, 0, {{-hx, 0, hz}, {-hx, 0, -hz}, {-hx, sy, -hz}, {-hx, sy, hz}}},    // left
        {1, 0, 0, {{hx, 0, -hz}, {hx, 0, hz}, {hx, sy, hz}, {hx, sy, -hz}}},          // right
        {0, 1, 0, {{-hx, 0, hz}, {hx, 0, hz}, {hx, 0, -hz}, {-hx, 0, -hz}}},          // top
        {0, -1, 0, {{-hx, sy, -hz}, {hx, sy, -hz}, {hx, sy, hz}, {-hx, sy, hz}}},    // bottom
    };
    for (const Face& f : faces) {
        const int order[6] = {0, 1, 2, 0, 2, 3};
        for (int i : order) {
            out->push_back(place(f.v[i][0], f.v[i][1], f.v[i][2], f.nx, f.ny, f.nz));
        }
    }
}

// Clothes from a hash of the object, so a pedestrian keeps his colours from
// frame to frame and no two neighbours match.
void FigureColours(uintptr_t object, DWORD* skin, DWORD* hair, DWORD* shirt, DWORD* trousers) {
    const uint32_t h = static_cast<uint32_t>(object >> 4) * 2654435761u;
    static const DWORD skins[] = {0xFFE0B090, 0xFFC89070, 0xFF8A5A3A, 0xFFF0C8A8, 0xFF6A4028};
    static const DWORD hairs[] = {0xFF201810, 0xFF503820, 0xFF907040, 0xFFC0A060, 0xFF303030, 0xFF804020};
    static const DWORD shirts[] = {0xFF2040A0, 0xFFA03030, 0xFF308040, 0xFFE0E0E0, 0xFF303030, 0xFFC0A020,
                                   0xFF7030A0, 0xFF20A0A0, 0xFFF08020, 0xFF604020, 0xFF9090A0, 0xFF206030};
    static const DWORD legs[] = {0xFF202840, 0xFF303030, 0xFF605040, 0xFF3A3A5A, 0xFF806040, 0xFF202020};
    *skin = skins[h % 5];
    *hair = hairs[(h >> 8) % 6];
    *shirt = shirts[(h >> 16) % 12];
    *trousers = legs[(h >> 24) % 6];
}

}  // namespace

void LiveGeometry::DrawPedFigures(IDirect3DDevice9* device) {
    g_figuresLast.swap(g_figuresNow);
    g_figuresNow.clear();
    g_aimPeds.clear();
    g_aimPedsFrame = g_carFrame;
    // QB-27: the cars drawn this frame, for the ragdolls (the car that hit him, its pace).
    if (g_groundModels && RagdollEnabled()) {
        for (const CarBodyUse& use : carBodies_) {
            float corners[4][3];
            const float (*cm)[4] = use.objectToWorld.m;
            for (int i = 0; i < 4; ++i) {
                const float lx = use.local[i].x, ly = use.local[i].y, lz = use.local[i].z;
                for (int c = 0; c < 3; ++c) corners[i][c] = lx * cm[0][c] + ly * cm[1][c] + lz * cm[2][c] + cm[3][c];
            }
            RagdollNoteCar(use.object, corners, g_carFrame);
        }
    }
    std::vector<FigVertex> verts;
    verts.reserve(36 * 6);

    // States for untextured, vertex-coloured geometry; put back afterwards.
    DWORD colorOp = 0, colorArg1 = 0, alphaOp = 0, alphaArg1 = 0, alphaTest = 0, alphaBlend = 0;
    device->GetTextureStageState(0, D3DTSS_COLOROP, &colorOp);
    device->GetTextureStageState(0, D3DTSS_COLORARG1, &colorArg1);
    device->GetTextureStageState(0, D3DTSS_ALPHAOP, &alphaOp);
    device->GetTextureStageState(0, D3DTSS_ALPHAARG1, &alphaArg1);
    device->GetRenderState(D3DRS_ALPHATESTENABLE, &alphaTest);
    device->GetRenderState(D3DRS_ALPHABLENDENABLE, &alphaBlend);
    device->SetTexture(0, nullptr);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetFVF(kFigFvf);

    constexpr float kPi = 3.14159265f;
    // CROWD: last frame's counts, every ten seconds of drawing.
    {
        static uint32_t frames = 0;
        if (g_crowdCount[0] && ++frames % 300 == 0) {
            Log("crowd: %d figures drawn, %d in clothes of their own, %d looking at the player, %d glancing; nearest %.1f blocks at %.0f deg (player seen %d frames ago)",
                g_crowdCount[0], g_crowdCount[1], g_crowdCount[2], g_crowdCount[3], std::sqrt(g_crowdNearD2), g_crowdNearRel * 57.3f,
                g_crowdPlayerFrame ? static_cast<int>(g_carFrame - g_crowdPlayerFrame) : -1);
            Log("peds: %d of %d figures drawn in their sprite's outfit (ASSET-PEDS zones)", g_crowdCount[4], g_crowdCount[0]);
            Log("crowd: last 300 frames: %d figure-frames within look_range, %d passed over, %d with the player behind them, %d looking",
                g_crowdWin[0], g_crowdWin[1], g_crowdWin[2], g_crowdWin[3]);
            for (int& c : g_crowdWin) c = 0;
        }
        for (int& c : g_crowdCount) c = 0;
        g_crowdNearD2 = 1e9f;
    }
    int drawn = 0;
    if (g_logPedFrames) {
        // Corpses in this frame's list and how each is flagged, when it changes.
        static std::string last;
        std::string now;
        for (const Sprite& sprite : sprites_) {
            if (!sprite.corpse) continue;
            char buf[96];
            snprintf(buf, sizeof buf, " %p[c%d g%d h%d b%d p%d f%u s%d]", reinterpret_cast<const void*>(sprite.object),
                     sprite.corners, sprite.ghost ? 1 : 0, sprite.hidden ? 1 : 0, sprite.boardUi ? 1 : 0,
                     sprite.pedestrian ? 1 : 0, sprite.pedFrame % 158u, sprite.pedState);
            now += buf;
        }
        if (now != last) { last = now; Log("ped anim: corpses:%s", now.empty() ? " none" : now.c_str()); }
    }
    // ANIM-VEHICLE-ENTRY (boarding.h): a ped the game stopped drawing halfway into a car
    // is drawn on from his last sprite until the door is shut behind him.
    const size_t boardRealSprites = sprites_.size();
    std::set<uintptr_t> boardGhosts;
    if (g_groundModels && BoardingEnabled()) {
        BoardingSetLog(g_logFigures);
        for (auto it = boardSprites_.begin(); it != boardSprites_.end();) {
            if (g_carFrame - it->second.first > 90) { it = boardSprites_.erase(it); continue; }
            bool present = false;
            for (size_t i = 0; i < boardRealSprites && !present; ++i) {
                const Sprite& sp = sprites_[i];
                present = sp.object == it->first && sp.pedestrian && !sp.hidden && !sp.ghost && !sp.boardUi && sp.corners == 4;
            }
            if (!present && BoardingWantsGhost(it->first, g_carFrame)) {
                sprites_.push_back(it->second.second);
                Sprite& g = sprites_.back();
                g.hidden = false; g.ghost = false; g.boardUi = false;
                boardGhosts.insert(it->first);
            }
            ++it;
        }
    }
    for (const Sprite& sprite : sprites_) {
        // On his feet, or - with the models, which have clips for it - on the
        // ground (dead, knocked down) or climbing into or out of a car.
        const bool withModel = g_groundModels;
        if (!(sprite.pedestrian || (sprite.corpse && withModel)) || sprite.ghost || sprite.boardUi ||
            sprite.corners != 4 || sprite.hidden || (sprite.climbing && !withModel)) {
            continue;
        }
        const gta2::Mat4& m = sprite.objectToWorld;
        const float cx = m.m[3][0], cy = m.m[3][1], cz = m.m[3][2];
        if (sprite.object && reinterpret_cast<const void*>(sprite.object) != g_playerObject)
            g_aimPeds.push_back({sprite.object, cx, cy, cz, sprite.pedHealth, sprite.corpse});   // QB-6

        // Which way the artwork's top points is which way he faces: the sprite's
        // own z axis, signed by where the top of the picture lies along it.
        float minZ = 1e9f, maxZ = -1e9f, topV = 1e9f;
        int top = 0;
        for (int i = 0; i < 4; ++i) {
            minZ = (std::min)(minZ, sprite.local[i].z);
            maxZ = (std::max)(maxZ, sprite.local[i].z);
            if (sprite.local[i].v < topV) {
                topV = sprite.local[i].v;
                top = i;
            }
        }
        const float zTop = sprite.local[top].z >= (minZ + maxZ) * 0.5f ? 1.0f : -1.0f;
        float fx = m.m[2][0] * zTop, fz = m.m[2][2] * zTop;
        const float flen = std::sqrt(fx * fx + fz * fz);
        if (flen > 1e-4f) {
            fx /= flen;
            fz /= flen;
        } else {
            fx = 0.0f;
            fz = 1.0f;
        }

        // His pace, from where he was last frame. The game moves once a frame.
        PedTrack& track = pedTracks_[sprite.object];
        if (track.frame == 0 && g_viewActiveForPops) {
            // Pop log (PERF-2): a person the renderer had no track for, appearing now;
            // in the picture and near is a pop the player sees.
            const float pdx = cx - g_viewEye.x, pdz = cz - g_viewEye.z;
            const float pd = std::sqrt(pdx * pdx + pdz * pdz);
            const bool inView = !BehindView(cx, g_viewEye.y - 1.0f, cz, 0.0f) && !OutsideViewFrustum(cx, g_viewEye.y - 1.0f, cz, 0.5f);
            ++g_pedPops;
            g_pedPopDist += pd;
            if (inView) { ++g_pedPopsInView; if (pd < 10.0f) ++g_pedPopsNear; }
        }
        const unsigned frames = track.frame != 0 && g_carFrame > track.frame ? g_carFrame - track.frame : 1;
        const float dt = (std::min)(static_cast<float>(frames), 6.0f) / 30.0f;
        const bool freshTrack = track.frame == 0 || frames >= 10;   // QB-14: new, or back after being out of sight (in a car)
        if (track.frame != 0 && frames < 10) {
            const float dx = cx - track.x, dz = cz - track.z;
            const float dist = std::sqrt(dx * dx + dz * dz);
            const float speed = dist / dt;
            track.speed += (speed - track.speed) * 0.3f;
            track.phase += dist / 0.7f * 2.0f * kPi;   // one cycle per two strides of 0.35
            if (track.phase > 1e4f) track.phase -= 1e4f;
            if (dist > 0.01f) {
                track.faceX = dx / dist;
                track.faceZ = dz / dist;
            }
        } else {
            track.speed = 0.0f;
            track.faceX = fx;
            track.faceZ = fz;
        }
        track.x = cx;
        track.z = cz;
        track.frame = g_carFrame;
        // A moving pedestrian faces the way he moves, which the artwork agrees
        // with but reads more cleanly off the motion.
        const bool gameMoving = track.speed > 0.6f;
        if (gameMoving) {
            fx = track.faceX;
            fz = track.faceZ;
        }

        // The drawn figure follows the game's position through a critically
        // damped spring (a few centimetres behind at walking pace, never more
        // than about a tenth of a block), snapped when the game teleports him
        // (respawn, getting out of a car) or when he is new.
        {
            const float ex = track.dx - cx, ez = track.dz - cz;
            const bool snap = !track.placed || frames >= 10 || ex * ex + ez * ez > 0.8f * 0.8f;
            if (snap) {
                track.placed = true;
                track.dx = cx; track.dz = cz;
                track.vx = track.vz = 0.0f;
                track.drawnSpeed = 0.0f;
                const float hx0 = gameMoving ? fx : -fx, hz0 = gameMoving ? fz : -fz;
                track.heading = std::atan2(hx0, hz0);
                track.turnRate = 0.0f;
                track.walkWeight = gameMoving ? 1.0f : 0.0f;
                track.runWeight = 0.0f;
                const uint32_t h = static_cast<uint32_t>(sprite.object >> 4) * 2246822519u;
                track.cycle = static_cast<float>(h & 1023) / 1024.0f;          // his own phase of the cycle
                track.idleVariant = static_cast<int>((h >> 10) % 3);
                track.idleOffset = static_cast<float>((h >> 12) & 4095) / 64.0f;   // up to 64 s into the clip
                track.idleRate = 0.9f + static_cast<float>((h >> 24) & 255) / 255.0f * 0.2f;
            } else {
                constexpr float kOmega = 18.0f;   // rad/s: lag = speed / omega, 8 cm at 1.5 blocks/s
                const float ax = -2.0f * kOmega * track.vx - kOmega * kOmega * ex;
                const float az = -2.0f * kOmega * track.vz - kOmega * kOmega * ez;
                track.vx += ax * dt;
                track.vz += az * dt;
                const float px = track.dx, pz = track.dz;
                track.dx += track.vx * dt;
                track.dz += track.vz * dt;
                // Never further behind than a tenth of a block: pulled along.
                const float lx = track.dx - cx, lz = track.dz - cz;
                const float lag = std::sqrt(lx * lx + lz * lz);
                if (lag > 0.1f) { track.dx = cx + lx / lag * 0.1f; track.dz = cz + lz / lag * 0.1f; }
                const float mx = track.dx - px, mz = track.dz - pz;
                const float moved = std::sqrt(mx * mx + mz * mz);
                track.drawnSpeed += (moved / dt - track.drawnSpeed) * (std::min)(1.0f, dt / 0.12f);
            }
        }
        // Busted: the player's figure acts out the arrest (see g_bustFrame); after
        // the hands up he walks cuffed towards the nearest police car, his drawn
        // position offset from the game's (which stays where he lies) by up to a
        // block and a half.
        const bool playerSprite = sprite.object && reinterpret_cast<const void*>(sprite.object) == g_playerObject;
        const bool arrested = playerSprite && g_bustFrame && g_carFrame - g_bustFrame < kBustFrames && sprite.pedState == 8 && sprite.pedSub == 0x16;
        const float bustSecs = arrested ? static_cast<float>(g_carFrame - g_bustFrame) / 30.0f : 0.0f;
        if (!playerSprite) {
            // nothing: the walk belongs to the player's figure alone
        } else if (!arrested) {
            g_arrestWalk.ox = g_arrestWalk.oz = 0.0f; g_arrestWalk.car = false;
        } else {
            if (!g_arrestWalk.car && (g_carFrame - g_bustFrame) % 6u == 0) {
                // The police car he is led to: the nearest cop car (model 12) within three
                // blocks of where he lies, chosen once.
                float best = 9.0f;
                for (const CarBodyUse& use : carBodies_) {
                    if (use.model != 12) continue;
                    // The body quad's middle in the world (the quad need not be centred on its origin).
                    float lx = 0.0f, ly = 0.0f, lz = 0.0f;
                    for (int i = 0; i < 4; ++i) { lx += 0.25f * use.local[i].x; ly += 0.25f * use.local[i].y; lz += 0.25f * use.local[i].z; }
                    const float (*cm)[4] = use.objectToWorld.m;
                    const float carX = lx * cm[0][0] + ly * cm[1][0] + lz * cm[2][0] + cm[3][0];
                    const float carZ = lx * cm[0][2] + ly * cm[1][2] + lz * cm[2][2] + cm[3][2];
                    const float ddx = carX - track.dx, ddz = carZ - track.dz;
                    if (ddx * ddx + ddz * ddz < best) { best = ddx * ddx + ddz * ddz; g_arrestWalk.carX = carX; g_arrestWalk.carZ = carZ; g_arrestWalk.car = true; }
                }
                if (g_logPedFrames) {
                    Log("arrest: busted %.1f s ago, figure at %.2f,%.2f, police car %s %.2f,%.2f", bustSecs, track.dx, track.dz,
                        g_arrestWalk.car ? "at" : "none within three blocks", g_arrestWalk.carX, g_arrestWalk.carZ);
                }
            }
            g_arrestWalk.frame = g_carFrame;
            if (bustSecs > kBustHandsSecs && g_arrestWalk.car) {
                const float wx = g_arrestWalk.carX - (track.dx + g_arrestWalk.ox), wz = g_arrestWalk.carZ - (track.dz + g_arrestWalk.oz);
                const float wd = std::sqrt(wx * wx + wz * wz);
                const float led = std::sqrt(g_arrestWalk.ox * g_arrestWalk.ox + g_arrestWalk.oz * g_arrestWalk.oz);
                if (wd > 0.75f && led < 1.5f) {
                    const float step = 0.6f * dt;
                    g_arrestWalk.ox += wx / wd * step; g_arrestWalk.oz += wz / wd * step;
                    track.drawnSpeed = 0.6f;   // the walk under the cuffed layer
                }
            }
        }
        // ACTIONS-3D-4. Getting into or out of a car (state 3 / 4): the car's middle,
        // the nearest body within 1.3 blocks, followed every frame (it may be moving), so
        // the figure faces into the car on the way in and away from it on the way out
        // while its legs step the ground the game moves it.
        if (sprite.pedState == 3 || sprite.pedState == 4) {
            if (track.carState != sprite.pedState) {
                track.carState = sprite.pedState; track.carStateFrame = g_carFrame; track.carKnown = false;
                track.jacking = false;
            }
            // QB-14: boarding a car with a driver at the wheel is a jack (the game uses the
            // same states as for an empty car). Decided at the door, before the climb gets
            // far (reach and early climb frames 16-27): the nearest car drawn within a block,
            // by its driver word (further off, a ped walking past to another car's door).
            if (sprite.pedState == 3 && !track.jacking && (sprite.pedFrame % 158u) >= 16u && (sprite.pedFrame % 158u) < 28u) {
                float best = 1.0f * 1.0f;
                bool driver = false, found = false;
                for (const std::vector<CarSeat>* list : {&g_carSeats, &g_carSeatsNow}) {
                    for (const CarSeat& s : *list) {
                        const float ddx = s.x - cx, ddz = s.z - cz;
                        if (ddx * ddx + ddz * ddz < best) { best = ddx * ddx + ddz * ddz; driver = s.driver; found = true; }
                    }
                }
                if (found && driver) {
                    track.jacking = true;
                    if (g_logPedFrames)
                        Log("jack: %p boarding a car with a driver %.2f blocks off (frame %u sub 0x%x)", reinterpret_cast<const void*>(sprite.object),
                            std::sqrt(best), sprite.pedFrame % 158u, sprite.pedSub);
                }
            }
            {   // every frame: the car may be moving (boarding a car on the move)
                const bool had = track.carKnown && track.carSeenFrame && g_carFrame - track.carSeenFrame < 4;
                const float oldX = track.carX, oldZ = track.carZ;
                float best = 1.3f * 1.3f;
                for (const CarBodyUse& use : carBodies_) {
                    float lx = 0.0f, ly = 0.0f, lz = 0.0f;
                    for (int i = 0; i < 4; ++i) { lx += 0.25f * use.local[i].x; ly += 0.25f * use.local[i].y; lz += 0.25f * use.local[i].z; }
                    const float (*cm)[4] = use.objectToWorld.m;
                    const float carX = lx * cm[0][0] + ly * cm[1][0] + lz * cm[2][0] + cm[3][0];
                    const float carZ = lx * cm[0][2] + ly * cm[1][2] + lz * cm[2][2] + cm[3][2];
                    const float ddx = carX - cx, ddz = carZ - cz;
                    if (ddx * ddx + ddz * ddz < best) { best = ddx * ddx + ddz * ddz; track.carX = carX; track.carZ = carZ; track.carKnown = true; }
                }
                if (track.carKnown) {
                    // The car's own pace: a parked car's boarding is a walk to the door,
                    // a moving car's is a run beside it.
                    const float span = had ? static_cast<float>(g_carFrame - track.carSeenFrame) / 30.0f : 0.0f;
                    const float moved = had ? std::sqrt((track.carX - oldX) * (track.carX - oldX) + (track.carZ - oldZ) * (track.carZ - oldZ)) : 0.0f;
                    if (span > 0.0f && moved < 0.5f) track.carSpeed += (moved / span - track.carSpeed) * (std::min)(1.0f, span / 0.15f);
                    track.carSeenFrame = g_carFrame;
                }
            }
        } else if (track.action != 6) {
            track.carState = -1; track.carKnown = false; track.carSpeed = 0.0f; track.carSeenFrame = 0;
        }
        // Taking a punch: a blow another figure landed on him (PendingHit) starts the
        // hit layer and a stagger of his drawn figure along the blow: 7 cm back over
        // 0.15 s, then home over 0.6 s; the legs step it like any other motion.
        bool hitNow = false;
        {
            // The game's word that a blow landed: his health dropped while a figure
            // within 0.7 block is mid-swing (this frame's or last frame's list). The
            // blow's direction is from that figure; its hand (cross or jab) picks
            // which way his head turns.
            const int32_t hp = sprite.pedHealth;
            if (hp >= 0 && track.lastHealth >= 0 && hp < track.lastHealth && !sprite.corpse) {
                const FigureSpot* by = nullptr;
                float best = 0.7f * 0.7f;
                for (const std::vector<FigureSpot>* list : {&g_figuresNow, &g_figuresLast}) {
                    for (const FigureSpot& f : *list) {
                        if (!f.punching || f.object == sprite.object) continue;
                        const float vx = cx - f.x, vz = cz - f.z;
                        if (vx * vx + vz * vz < best) { best = vx * vx + vz * vz; by = &f; }
                    }
                }
                // QB-16: shot. Nobody mid-swing: the figure that fired in the last
                // 1.5 s (a bullet flies: 0.8 s to 3 blocks, qb16_r8) within 12 blocks with his aim nearest the line to him (within
                // 60 degrees: the drawn heading is eased) put a bullet in him. Which way the bullet came, against
                // his own facing, picks the clip (front, back, his left or right side,
                // hitSide 2-5) and the gun the stagger (a shotgun throws him further).
                const FigureSpot* shooter = nullptr;
                float missD = -1.0f, missAlong = 0.0f;   // the nearest recent shooter turned away, for the log
                if (!by && ShotHitsOn()) {
                    float bestScore = 1e9f;
                    for (const std::vector<FigureSpot>* list : {&g_figuresNow, &g_figuresLast}) {
                        for (const FigureSpot& f : *list) {
                            if (f.object == sprite.object || !f.shotFrame || g_carFrame - f.shotFrame > 45) continue;
                            const float vx = cx - f.x, vz = cz - f.z;
                            const float d2 = vx * vx + vz * vz;
                            if (d2 > 12.0f * 12.0f || d2 < 1e-6f) continue;
                            const float d = std::sqrt(d2);
                            const float along = (vx * f.fx + vz * f.fz) / d;
                            if (along < 0.5f) {
                                if (missD < 0.0f || d < missD) { missD = d; missAlong = along; }
                                continue;
                            }
                            const float score = d * (2.0f - along);
                            if (score < bestScore) { bestScore = score; shooter = &f; }
                        }
                    }
                }
                if (!by && !shooter && (g_logFigures || g_logPedFrames))
                    Log("fig: health %04x %d -> %d, nobody mid-swing within 0.7 or firing at him (state %d sub 0x%x cause %d; nearest shooter %.1f blocks facing %.2f)",
                        static_cast<unsigned>((sprite.object >> 2) & 0xFFFF), track.lastHealth, hp, sprite.pedState, sprite.pedSub, sprite.pedCause,
                        missD, missAlong);
                if (shooter) {
                    const float vx = cx - shooter->x, vz = cz - shooter->z;
                    const float d = (std::max)(1e-3f, std::sqrt(vx * vx + vz * vz));
                    const float ux = vx / d, uz = vz / d;   // the bullet's way
                    const float fwd = ux * std::sin(track.heading) + uz * std::cos(track.heading);
                    const float right = ux * std::cos(track.heading) - uz * std::sin(track.heading);
                    int side = fwd < -0.5f ? 2 : fwd > 0.5f ? 3 : right > 0.0f ? 4 : 5;   // front, back, his left, his right
                    hitNow = true;
                    track.hitFrame = g_carFrame; track.hitSide = side;
                    track.hitDirX = ux; track.hitDirZ = uz;
                    const int w = shooter->weapon;
                    track.hitPush = w == kWpnShotgun ? 0.16f : (w == kWpnMg || w == kWpnSilencedMg) ? 0.10f : 0.08f;
                    if (g_logFigures || g_logPedFrames) {
                        static const char* const kSides[6] = {"", "", "front", "back", "left", "right"};
                        Log("fig: shot %04x%s by %04x (weapon %d, %.1f blocks, %s) health %d -> %d state %d sub 0x%x",
                            static_cast<unsigned>((sprite.object >> 2) & 0xFFFF),
                            reinterpret_cast<const void*>(sprite.object) == g_playerObject ? " (player)" : "",
                            static_cast<unsigned>((shooter->object >> 2) & 0xFFFF), w, d, kSides[side], track.lastHealth, hp, sprite.pedState, sprite.pedSub);
                    }
                }
                if (by) {
                    const float vx = cx - by->x, vz = cz - by->z;
                    const float d = (std::max)(1e-3f, std::sqrt(vx * vx + vz * vz));
                    hitNow = true;
                    track.hitFrame = g_carFrame; track.hitSide = by->alt ? 1 : 0;
                    track.hitDirX = vx / d; track.hitDirZ = vz / d; track.hitPush = 0.07f;
                    if (g_logFigures || g_logPedFrames)
                        Log("fig: hit %04x by %04x (%s) health %d -> %d state %d sub 0x%x", static_cast<unsigned>((sprite.object >> 2) & 0xFFFF),
                            static_cast<unsigned>((by->object >> 2) & 0xFFFF), by->alt ? "jab" : "cross", track.lastHealth, hp, sprite.pedState, sprite.pedSub);
                }
            }
            track.lastHealth = hp;
        }
        {
            float st = 0.0f;
            if (track.hitFrame) {
                const float ht = static_cast<float>(g_carFrame - track.hitFrame) / 30.0f;
                if (ht < 0.15f) st = Smoothstep(0.0f, 0.15f, ht);
                else if (ht < 0.75f) st = 1.0f - Smoothstep(0.15f, 0.75f, ht);
            }
            track.staggerX = track.hitDirX * track.hitPush * st;
            track.staggerZ = track.hitDirZ * track.hitPush * st;
        }
        // What the game has him doing, from his animation frame and state words.
        int wantAction = PedActionFor(sprite.corpse, sprite.pedFrame, sprite.pedState, sprite.pedSub);
        // (the player's boarding ghost too: the game no longer names him once he is in the car)
        const bool ownPed = sprite.object && (reinterpret_cast<const void*>(sprite.object) == g_playerObject ||
                                              (boardGhosts.count(sprite.object) && BoardingIsPlayer(sprite.object)));
        bool shotNow = false;
        {
            // The weapon: the player's from the game; a stranger's from his frames
            // (the one-handed stance: a pistol, the two-handed: a machine gun),
            // refined by what leaves his gun (a big flash: a shotgun; a rocket).
            // The game's word first (the player's through SetPlayerWeapon, anyone's
            // through g_pedWeaponByObject: the weapon object his ped holds); the
            // frames and the flash only tell weapons apart while the game is unread.
            int gameWeapon = -1;
            if (ownPed && g_playerWeapon >= 0 && g_playerWeapon < kWpnCount) gameWeapon = g_playerWeapon;
            else if (sprite.object) {
                const auto it = g_pedWeaponByObject.find(sprite.object);
                if (it != g_pedWeaponByObject.end() && it->second >= 0 && it->second < kWpnCount) gameWeapon = it->second;
            }
            if (gameWeapon >= 0) track.weapon = gameWeapon;
            else if (wantAction == 2 && (track.weapon == kWpnNone || kWeapons[track.weapon].twoHanded)) track.weapon = kWpnPistol;
            else if (wantAction == 8 && (track.weapon == kWpnNone || !kWeapons[track.weapon].twoHanded)) track.weapon = kWpnMg;
            // The game has put a weapon in his hands (its weapon object, see
            // game::PedWeaponOf): the stance and the carry follow it, not the frames.
            const bool armed = gameWeapon > 0 && !sprite.corpse;
            // Shooting: a flash or a bullet appearing beside him while he attacks
            // (state 7; frame 139 is the firing frame measured on the player).
            const unsigned f = sprite.pedFrame % 158u;
            if (sprite.pedState == 7 && f == 139 && wantAction == 0) wantAction = 2;
            if (sprite.pedState == 7 || wantAction == 2 || wantAction == 8 || (armed && g_carFrame < track.aimUntil)) {
                for (FxFresh& fx : g_fxFreshLast) {
                    if (fx.claimed) continue;
                    const float dx = fx.x - cx, dz = fx.z - cz;
                    if (dx * dx + dz * dz < 0.64f && std::fabs(fx.y - cy) < 0.8f) {
                        fx.claimed = true;
                        shotNow = true;
                        if (gameWeapon < 0 && fx.size > 0.15f && fx.size < 0.3f && track.weapon == kWpnMg) track.weapon = kWpnShotgun;
                    }
                }
                for (const FxSpot& fx : g_fxSpotsLast) {
                    const float dx = fx.x - cx, dz = fx.z - cz;
                    if (dx * dx + dz * dz < 1.0f) { track.shotFrame = g_carFrame; break; }
                }
                // Attacking on frames the sheet does not name (the thrown and the
                // heavy weapons' own) with a shot just seen: the stance all the same.
                if (wantAction == 0 && sprite.pedState == 7 && track.shotFrame && g_carFrame - track.shotFrame < 45) wantAction = 2;
            }
            if (shotNow && g_carFrame - track.muzzleFrame >= 2) track.muzzleFrame = g_carFrame;
            if (shotNow && track.weapon == kWpnNone && gameWeapon < 0) track.weapon = kWpnPistol;   // shooting with nothing named: a pistol
            if (armed && (wantAction == 0 || wantAction == 2 || wantAction == 8)) {
                // Armed, by the game's word. Attacking (the attack state, a shot
                // beside him, the aim frames) raises the weapon's own stance, held a
                // second past the last of them so a burst does not drop the gun
                // between shots; otherwise the weapon is carried at low ready: the
                // player always, anyone else for three seconds after he fired (a
                // gang member or a cop walking his beat does not wave a gun about).
                // The game's own shot: his weapon's ammunition dropped, or its reload
                // timer restarted (a kill frenzy's ammunition never drops). Not the
                // attack state: he stands in state 7 whenever he is armed and still.
                const bool sameGun = sprite.pedWeaponObject && sprite.pedWeaponObject == track.lastWeaponObject;
                const bool gameShot = sameGun && ((sprite.pedAmmo >= 0 && track.lastAmmo >= 0 && sprite.pedAmmo < track.lastAmmo) ||
                                                  (sprite.pedReload > track.lastReload && track.lastReload >= 0));
                const bool attacking = gameShot || shotNow || f == 139;
                if (gameShot && !shotNow && g_carFrame - track.muzzleFrame >= 2) track.muzzleFrame = g_carFrame;
                if (g_logPedFrames && gameShot && ownPed) Log("player shot: ammo %d -> %d reload %d -> %d", track.lastAmmo, sprite.pedAmmo, track.lastReload, sprite.pedReload);
                if (g_logPedFrames && (gameShot || shotNow) && !ownPed) {
                    static int npcShots = 0;
                    if (npcShots < 80) {
                        ++npcShots;
                        Log("npc shot: object %p weapon %d (%s) ammo %d -> %d reload %d -> %d flash %d at %.2f,%.2f,%.2f",
                            reinterpret_cast<const void*>(sprite.object), track.weapon, gameShot ? "game" : "flash",
                            track.lastAmmo, sprite.pedAmmo, track.lastReload, sprite.pedReload, shotNow ? 1 : 0, cx, cy, cz);
                    }
                }
                if (attacking) track.aimUntil = g_carFrame + 30;
                const bool carrying = ownPed || (track.aimUntil && g_carFrame < track.aimUntil + 90);
                // QB-29: the magazine. Shots counted on this gun; a new gun starts full;
                // ammunition going up (a pickup) with shots fired reloads too.
                const ReloadInfo& ri = kReloads[track.weapon];
                bool reloading = false;
                if (ReloadOn() && ri.mag > 0) {
                    if (!sameGun) { track.magShots = 0; track.reloadStart = 0; }
                    if (gameShot) { ++track.magShots; track.magLastShot = g_carFrame; }
                    if (sameGun && !gameShot && sprite.pedAmmo > track.lastAmmo && track.lastAmmo >= 0 && track.magShots > 0) track.magShots = ri.mag;
                    if (attacking) {
                        if (track.reloadStart && g_logPedFrames) Log("reload: %p %s cut off by a shot", reinterpret_cast<const void*>(sprite.object), kWeapons[track.weapon].name);
                        track.reloadStart = 0;
                    } else if (!track.reloadStart && track.magShots >= ri.mag && g_carFrame - track.magLastShot >= 9 && carrying) {
                        track.reloadStart = g_carFrame;
                        track.magShots = 0;
                        track.reloadPrevT = -1.0f;
                        static int logged = 0;
                        if (logged < 120) {
                            ++logged;
                            Log("reload: %p%s %s starts (clip %d, magazine %d)", reinterpret_cast<const void*>(sprite.object), ownPed ? " (player)" : "",
                                kWeapons[track.weapon].name, ri.action, ri.mag);
                        }
                    }
                    // Held to its end (the clip's own time; frames as a backstop for a
                    // figure that never runs it, the box figure or an avatar without it).
                    if (track.reloadStart) {
                        const bool started = track.action == ri.action;
                        const bool over = (started && track.actionTime >= ri.len) || g_carFrame - track.reloadStart > 150 ||
                                          (!started && g_carFrame - track.reloadStart > 3);
                        if (over) track.reloadStart = 0;
                        else reloading = true;
                    }
                }
                if (reloading) {
                    wantAction = ri.action;
                } else if (track.weapon == kWpnMolotov || track.weapon == kWpnGrenade) {
                    // A throw per press: the attack state's rising edge, or the thrown thing seen.
                    const bool press = gameShot || shotNow;
                    if (track.action == 13 || press) wantAction = 13;
                    else wantAction = carrying ? CarryFor(track.weapon) : 0;
                } else if (g_carFrame < track.aimUntil) {
                    wantAction = kWeapons[track.weapon].action;
                } else {
                    wantAction = carrying ? CarryFor(track.weapon) : 0;
                }
            } else if ((wantAction == 2 || wantAction == 8) && track.weapon > 0) {
                // The game's weapon unread: the stance the inferred weapon calls for;
                // a thrown weapon's throw, one shot, on the throw itself.
                const int stance = kWeapons[track.weapon].action;
                wantAction = stance == 13 ? (shotNow ? 13 : 0) : stance;
            }
            if (ownPed && track.weapon > 0) g_playerWeaponSeen = track.weapon;
            track.lastAmmo = sprite.pedAmmo; track.lastReload = sprite.pedReload; track.lastWeaponObject = sprite.pedWeaponObject;
        }
        // On fire: the game's flames on him (they travel with a burning person)
        // three frames running. He runs flailing (the burn layer over his run);
        // dying in it, he curls up (lying clip "burnt").
        const bool ownFlames = track.weapon == kWpnFlame && track.aimUntil && g_carFrame < track.aimUntil + 30;
        if (!ownFlames && FireSpotsNear(cx, cz, 0.18f, nullptr) > 0) {
            if (++track.burnFrames >= 3) track.burnSeen = g_carFrame;
        } else {
            track.burnFrames = 0;
        }
        if (!sprite.corpse && track.burnSeen && g_carFrame - track.burnSeen < 12 &&
            (wantAction == 0 || IsCarryAction(wantAction) || IsAimAction(wantAction) || wantAction == 7 || IsReloadAction(wantAction))) {
            wantAction = 19;
        }
        // In the water (state 8 sub 0x14): the drowning clip, sinking as it runs.
        if (wantAction == 9) {
            if (!track.waterFrame) track.waterFrame = g_carFrame;
        } else if (!sprite.corpse) {
            track.waterFrame = 0;
        }
        // QB-14: the driver of a jacked car. The game shows him first thrown (state 8 sub
        // 0x11) beside a ped boarding the car, then knocked down (sub 0x19 / 0x16); he was
        // out of sight in the car until then, so his track is fresh. He plays "jacked"
        // (lying clip 5: hauled out of the seat, stumbling back, over onto his back)
        // from the throw on, facing the car, instead of a stagger and the run-over arc.
        // A driver who gets out by himself (state 4: the game sometimes lets him step out
        // as the jacker reaches the door) keeps exit_car, but still releases the jacker's haul.
        const bool thrownOut = sprite.pedState == 8 && sprite.pedSub == 0x11;
        if (freshTrack && (thrownOut || sprite.pedState == 4) && !sprite.corpse) {
            const DoorPed* jacker = nullptr;
            float best = 1.2f * 1.2f;
            for (const std::vector<DoorPed>* list : {&g_doorPeds, &g_doorPedsNow}) {
                for (const DoorPed& dp : *list) {
                    const float ddx = dp.x - cx, ddz = dp.z - cz;
                    if (dp.state == 3 && ddx * ddx + ddz * ddz < best) { best = ddx * ddx + ddz * ddz; jacker = &dp; }
                }
            }
            if (jacker) {
                float tx = jacker->x, tz = jacker->z, bestCar = 1.6f * 1.6f;
                for (const std::vector<CarSeat>* list : {&g_carSeats, &g_carSeatsNow}) {
                    for (const CarSeat& s : *list) {
                        const float ddx = s.x - cx, ddz = s.z - cz;
                        if (ddx * ddx + ddz * ddz < bestCar) { bestCar = ddx * ddx + ddz * ddz; tx = s.x; tz = s.z; }
                    }
                }
                if (thrownOut) {
                    track.jacked = true; track.jackFrame = g_carFrame;
                    if ((tx - cx) * (tx - cx) + (tz - cz) * (tz - cz) > 1e-4f) track.heading = std::atan2(tx - cx, tz - cz);
                }
                if (g_jackThrows.size() > 16) g_jackThrows.erase(g_jackThrows.begin());
                g_jackThrows.push_back({cx, cz, g_carFrame});
                if (g_logPedFrames)
                    Log("jack: driver %p %s %.2f blocks from the boarding ped, the car %.2f off", reinterpret_cast<const void*>(sprite.object),
                        thrownOut ? "thrown out" : "stepping out", std::sqrt(best), std::sqrt((tx - cx) * (tx - cx) + (tz - cz) * (tz - cz)));
            }
        }
        if (track.jacked) {
            if (g_carFrame - track.jackFrame < 600 && sprite.pedState == 8 && (sprite.pedSub == 0x11 || sprite.corpse)) wantAction = 4;
            else if (!sprite.corpse) track.jacked = false;
        }
        // Down: which way he falls follows what put him there (the game's damage
        // cause word, the fire): burnt, blown off his feet by an explosion, run
        // over or struck by a car (cause 1/3, or the car knock-down sub-states
        // 0x18-0x1A), else onto his back or his front by his own seed.
        if (wantAction == 4 && track.action != 4 && track.jacked) {
            track.lieClip = 5;
        } else if (wantAction == 4 && track.action != 4) {
            const int32_t cause = sprite.pedCause;
            const bool carHit = cause == game::kDamageCarHit || cause == game::kDamageRunOver ||
                                (sprite.pedState == 8 && sprite.pedSub >= 0x18 && sprite.pedSub <= 0x1A);
            // Cause 11 came with the game's flames on the body in the probe runs (a3m3).
            if ((track.burnSeen && g_carFrame - track.burnSeen < 90) || cause == 11) track.lieClip = 4;
            else if (cause == game::kDamageExplosion) track.lieClip = 3;
            else if (carHit) track.lieClip = 2;
            else track.lieClip = ((static_cast<uint32_t>(sprite.object >> 4) * 2654435761u) >> 20) % 3 == 0 ? 1 : 0;
            if (g_logPedFrames) {
                Log("ped anim: down %p cause %d state %d sub 0x%x -> lying clip %d", reinterpret_cast<const void*>(sprite.object),
                    cause, sprite.pedState, sprite.pedSub, track.lieClip);
            }
        }
        track.lastState = sprite.pedState;
        // A showcase for checking the clips on the player's own figure, off by
        // default: GTA2DX9_FORCE_ACTION_FILE names a file (re-read twice a second)
        // holding "action [lying clip] [weapon]"; -1 or no file lets the game drive.
        // Taking a punch (ACTIONS-3D-4): over his walk, idle or carry; not while down,
        // falling, swimming or climbing (the lying clip takes over if the game knocks
        // him down: state 8 sub 0x16).
        // QB-16: a bullet over the aim too (it takes the gun off the line for a moment),
        // and the reaction held to its end over the walk, the carry or the aim, which
        // would otherwise take the layer back the next frame.
        if (hitNow && !sprite.corpse && (wantAction == 0 || IsCarryAction(wantAction) || wantAction == 22 ||
                                         (track.hitSide >= 2 && IsAimAction(wantAction)))) wantAction = 22;
        if (!hitNow && track.action == 22 && !track.actionReverse && track.actionTime < 0.6f && !sprite.corpse &&
            (wantAction == 0 || IsCarryAction(wantAction) || (track.hitSide >= 2 && IsAimAction(wantAction)))) wantAction = 22;
        // A man shot as he squares up (the game's swing frames start the instant he is
        // hit, qb16_r3) takes the bullet first: his swing waits out the jolt (0.35 s).
        if (track.action == 22 && track.hitSide >= 2 && !track.actionReverse && track.actionTime < 0.35f && !sprite.corpse &&
            (wantAction == 1 || hitNow)) wantAction = 22;
        // Boarding a car on the move (ACTIONS-3D-4): the game carries him along with the car
        // in state 3 before the climb (sprite frames below 24). While he covers ground faster
        // than a walk he runs beside it (legs from the ground covered, heading along the
        // motion) with a hand on the door (grab_door_r / _l, by which side the car is on);
        // the climb's frames then pull him in (enter_car from its duck).
        if (sprite.pedState == 3 && (sprite.pedFrame % 158u) < 24u && (wantAction == 0 || wantAction == 5) &&
            track.carKnown && (track.carSpeed > 0.3f || track.action == 23) &&
            (track.legSpeed > 0.6f || (track.action == 23 && track.legSpeed > 0.35f))) {
            wantAction = 23;
            if (track.action != 23) {   // which hand: chosen once, as he takes hold
                const float rx = std::cos(track.heading), rz = -std::sin(track.heading);   // his right
                track.grabLeft = (track.carX - cx) * rx + (track.carZ - cz) * rz < 0.0f;
            }
        }
        if (arrested && bustSecs > 0.0f) {
            // Up from the knock-down (the state machine plays the fall backwards),
            // then the hands up, then cuffed. No weapon: the game has taken them.
            wantAction = bustSecs < kBustHandsSecs ? 3 : 21;
            track.weapon = kWpnNone;
        }
        if (ownPed) {
            int fa = -1, fl = 0, fw = -1;
            ForcedAction(&fa, &fl, &fw);
            if (fa >= 0) {
                if (fa == 4 && track.action != 4) track.lieClip = fl;
                if (fa == 9 && !track.waterFrame) track.waterFrame = g_carFrame;
                if (fw >= 0 && fw < kWpnCount) track.weapon = fw;
                if (fa != track.action && fa != 4 && track.action == 4) track.action = 0;   // straight up again
                wantAction = fa;
            }
        }
        if (wantAction == 4 && track.action != 4) {
            track.action = 4; track.actionTime = 0.0f; track.actionReverse = false;
        } else if (wantAction != 4 && track.action == 4 && !track.actionReverse) {
            // Up again (knocked down, not dead): the fall, backwards, from where it is.
            track.actionReverse = true;
            if (track.lieClip == 5) track.lieClip = 0;   // QB-14: "jacked" ends on "fall"'s last pose
            track.actionTime = (std::min)(track.actionTime, 0.7f);
        } else if (wantAction != 0 && wantAction != 4 && track.action != wantAction && track.action != 4) {
            if (wantAction == 1) {
                // A new swing within 1.2 s of the last continues the combo with the other
                // fist; otherwise he leads with the right cross.
                track.punchAlt = track.lastPunchFrame && g_carFrame - track.lastPunchFrame < 36 ? !track.punchAlt : false;
                track.lastPunchT = 0.0f;
            }
            const bool pullIn = wantAction == 5 && track.action == 23;
            track.action = wantAction; track.actionTime = pullIn ? (track.jacking ? 0.5f : 0.65f) : 0.0f; track.actionReverse = false;
        } else if (hitNow && track.action == 22) {
            track.actionTime = 0.0f;   // hit again: the snap again
        }
        if (g_logPedFrames && track.action != track.lastLoggedAction) {
            track.lastLoggedAction = track.action;
            Log("ped anim: object %p action %d (frame %u state %d sub 0x%x%s)", reinterpret_cast<const void*>(sprite.object),
                track.action, sprite.pedFrame % 158u, sprite.pedState, sprite.pedSub, sprite.corpse ? " corpse" : "");
        }
        // Heading: toward the game's, at a human turning rate (540 deg/s on
        // foot, quicker at a run), eased so a turn starts and ends softly; the
        // standing figure's heading comes from the artwork, whose top edge is
        // the back of his head, so it points the other way (checked against the
        // chase camera, which sits behind the game's own heading).
        if (track.action != 4) {
            const float tx = gameMoving ? fx : -fx, tz = gameMoving ? fz : -fz;
            float target = std::atan2(tx, tz);
            if (track.action == 23 && track.vx * track.vx + track.vz * track.vz > 0.09f) {
                // Running beside a moving car: facing the way he runs.
                target = std::atan2(track.vx, track.vz);
            } else if (track.carKnown && (sprite.pedState == 3 || sprite.pedState == 4 || track.action == 6)) {
                // Into the car facing it, out of it facing away (ACTIONS-3D-4): the legs
                // step whichever way the game moves him meanwhile (back as the door swings).
                const float ax = track.carX - track.dx, az = track.carZ - track.dz;
                if (ax * ax + az * az > 0.0025f) target = sprite.pedState == 3 ? std::atan2(ax, az) : std::atan2(-ax, -az);
            }
            if (arrested && g_arrestWalk.car && bustSecs > kBustHandsSecs) {
                // Led away: facing the police car.
                target = std::atan2(g_arrestWalk.carX - (track.dx + g_arrestWalk.ox), g_arrestWalk.carZ - (track.dz + g_arrestWalk.oz));
            }
            float diff = target - track.heading;
            while (diff > kPi) diff -= 2.0f * kPi;
            while (diff < -kPi) diff += 2.0f * kPi;
            float cap = (track.runWeight > 0.5f ? 14.0f : 9.4f), ease = 0.07f;
            // The player's own figure in the chase view turns under the camera's
            // rule (a lower cap, a longer ease), so it never snaps in the frame.
            const bool own = sprite.object && reinterpret_cast<const void*>(sprite.object) == g_playerObject;
            const bool smoothed = own && ViewPlayerDrawnTurn(&cap, &ease);
            const float rate = cap * dt;   // radians this frame
            float step = diff * (std::min)(1.0f, dt / ease);
            if (step > rate) step = rate;
            if (step < -rate) step = -rate;
            track.heading += step;
            while (track.heading > kPi) track.heading -= 2.0f * kPi;
            while (track.heading < -kPi) track.heading += 2.0f * kPi;
            track.turnRate += (step / dt - track.turnRate) * (std::min)(1.0f, dt / 0.15f);
            if (smoothed) ViewLogPlayerDrawnYaw(track.heading, step / (std::max)(dt, 1e-3f), dt);
        }
        // An aim carried off the line of his walk: the legs face the way he
        // moves (within 100 degrees of the aim), the torso is twisted onto the
        // aim; both eased so neither snaps when he stops or turns.
        {
            float twistTarget = 0.0f;
            if (IsAimAction(track.action) && track.drawnSpeed > 0.35f) {
                const float motion = std::atan2(track.vx, track.vz);
                float d = track.heading - motion;
                while (d > kPi) d -= 2.0f * kPi;
                while (d < -kPi) d += 2.0f * kPi;
                if (std::fabs(d) < 1.75f) twistTarget = (std::max)(-1.0f, (std::min)(1.0f, d));
            }
            track.twist += (twistTarget - track.twist) * (std::min)(1.0f, dt / 0.12f);
        }
        // ANIM-VEHICLE-ENTRY: getting in or out of a car is the boarding plan's (boarding.h):
        // where the figure stands, how low (seated), which way it faces, the clip and time.
        BoardingOut boardOut;
        bool boarding = false;
        if (g_groundModels && !sprite.corpse && BoardingEnabled()) {
            if (sprite.pedState == 3 && !boardGhosts.count(sprite.object)) boardSprites_[sprite.object] = {g_carFrame, sprite};
            BoardingIn bi;
            bi.ped = sprite.object; bi.own = ownPed; bi.state = sprite.pedState; bi.sub = sprite.pedSub;
            bi.frame = sprite.pedFrame % 158u; bi.gameX = cx; bi.gameZ = cz; bi.groundY = cy;
            bi.drawnX = track.dx; bi.drawnZ = track.dz; bi.heading = track.heading;
            bi.ghost = boardGhosts.count(sprite.object) != 0; bi.dt = dt; bi.now = g_carFrame;
            bi.jacking = track.jacking;
            if (track.jacking) {
                bi.driverIn = true;
                for (const JackThrow& j : g_jackThrows)
                    if (j.frame >= track.carStateFrame && (j.x - cx) * (j.x - cx) + (j.z - cz) * (j.z - cz) < 1.3f * 1.3f) bi.driverIn = false;
            }
            boarding = BoardingUpdate(bi, &boardOut);
            if (boarding) {
                track.dx = boardOut.x; track.dz = boardOut.z; track.vx = boardOut.vx; track.vz = boardOut.vz;
                track.heading = boardOut.heading; track.twist = 0.0f; track.turnRate = 0.0f;
                track.staggerX = track.staggerZ = 0.0f;
                if (boardOut.action == 5 && track.jacking) {
                    // QB-14: jack_pull keeps its own timing (held until the driver is out).
                    if (track.action != 5) { track.action = 5; track.actionReverse = false; track.actionTime = 0.5f; track.actionWeight = 1.0f; }
                } else if (boardOut.action) {
                    track.action = boardOut.action; track.actionReverse = false;
                    track.actionTime = boardOut.clipT; track.actionWeight = 1.0f;
                }
            }
        }
        const float boardSink = boarding ? boardOut.sink : 0.0f;
        const float legHeading = track.heading - track.twist;
        // CROWD: where his head turns ([crowd] look_at). Toward the player when the
        // player is within look_range and in front of him (twice as far while the
        // player's gun is going off; one passer-by in four does not look unless it
        // is), clamped to 70 degrees (50 walking); otherwise a glance now and then:
        // standing every 3-8 s for 1-2.5 s up to 70 degrees, walking every 5-12 s up
        // to 35. Only with no action clip on (those pose the head themselves);
        // eased over 0.25 s at up to 230 degrees a second.
        {
            const bool own = sprite.object && reinterpret_cast<const void*>(sprite.object) == g_playerObject;
            float headTarget = 0.0f;
            track.lookingAtPlayer = false;
            if (own) {
                g_crowdPlayerX = track.dx; g_crowdPlayerZ = track.dz; g_crowdPlayerFrame = g_carFrame;
                g_crowdPlayerShot = track.muzzleFrame;
            } else if (g_crowdLookAt && track.action == 0 && !sprite.corpse) {
                const uint32_t seed = static_cast<uint32_t>(sprite.object >> 4);
                const bool walking = track.walkWeight > 0.5f;
                if (g_crowdPlayerFrame && g_carFrame - g_crowdPlayerFrame <= 3) {
                    const float px = g_crowdPlayerX - track.dx, pz = g_crowdPlayerZ - track.dz;
                    const bool gunfire = g_crowdPlayerShot && g_carFrame - g_crowdPlayerShot < 90;
                    const float range = g_crowdLookRange * (gunfire ? 2.0f : 1.0f);
                    const float d2 = px * px + pz * pz;
                    if (d2 < g_crowdNearD2) {
                        g_crowdNearD2 = d2;
                        float rl = std::atan2(px, pz) - track.heading;
                        while (rl > kPi) rl -= 2.0f * kPi;
                        while (rl < -kPi) rl += 2.0f * kPi;
                        g_crowdNearRel = rl;
                    }
                    if (d2 < range * range && d2 > 0.04f) { ++g_crowdWin[0]; if (!gunfire && (CrowdHash(seed) & 3) == 0) ++g_crowdWin[1]; }
                    if (d2 < range * range && d2 > 0.04f && (gunfire || (CrowdHash(seed) & 3) != 0)) {
                        float rel = std::atan2(px, pz) - track.heading;
                        while (rel > kPi) rel -= 2.0f * kPi;
                        while (rel < -kPi) rel += 2.0f * kPi;
                        if (std::fabs(rel) < 1.9f) {
                            const float lim = walking ? 0.87f : 1.22f;
                            headTarget = (std::max)(-lim, (std::min)(lim, rel));
                            track.lookingAtPlayer = true;
                            ++g_crowdWin[3];
                        } else {
                            ++g_crowdWin[2];
                        }
                    }
                }
                if (!track.lookingAtPlayer) {
                    const uint32_t r = CrowdHash(seed ^ (g_carFrame * 2654435761u));
                    if (track.nextGlance == 0) track.nextGlance = g_carFrame + 30 + r % 210;
                    if (g_carFrame >= track.glanceUntil && g_carFrame >= track.nextGlance) {
                        const float side = (r & 1) ? 1.0f : -1.0f;
                        const float amount = static_cast<float>((r >> 1) & 255) / 255.0f;
                        track.glanceYaw = side * (walking ? 0.3f + 0.3f * amount : 0.4f + 0.82f * amount);
                        track.glanceUntil = g_carFrame + 30 + (r >> 9) % 45;
                        track.nextGlance = track.glanceUntil + (walking ? 150 + (r >> 16) % 210 : 90 + (r >> 16) % 150);
                    }
                    if (g_carFrame < track.glanceUntil) headTarget = track.glanceYaw;
                }
            }
            float step = (headTarget - track.headYaw) * (std::min)(1.0f, dt / 0.25f);
            const float cap = 4.0f * dt;
            step = (std::max)(-cap, (std::min)(cap, step));
            track.headYaw += step;
        }
        const float hx = std::sin(legHeading), hz = std::cos(legHeading);
        // Where the figure stands: the drawn position, at the sprite's height.
        const float gx = track.dx + (arrested ? g_arrestWalk.ox : 0.0f) + track.staggerX,
                    gz = track.dz + (arrested ? g_arrestWalk.oz : 0.0f) + track.staggerZ;
        fx = hx;
        fz = hz;
        // ACTIONS-3D-4: the ground the drawn figure covered since last frame, signed
        // along the way its legs face (a step back is a step back), and its pace. The
        // legs' cycle is driven by this, never by the game's animation frame, so a
        // figure the game slides (out of a car door, pushed, led) steps it.
        {
            const float mx = gx - track.lastPX, mz = gz - track.lastPZ;
            const float md = std::sqrt(mx * mx + mz * mz);
            if (!track.havePrev || frames >= 10 || md > 0.4f) {
                track.stepFwd = 0.0f; track.legSpeed = 0.0f;
            } else {
                track.stepFwd = mx * hx + mz * hz;
                track.legSpeed += (md / dt - track.legSpeed) * (std::min)(1.0f, dt / 0.1f);
            }
            track.lastPX = gx; track.lastPZ = gz; track.havePrev = true;
        }
        g_figuresNow.push_back({sprite.object, gx, gz, track.action == 1, track.punchAlt, track.muzzleFrame,
                                std::sin(track.heading), std::cos(track.heading), track.weapon});
        {
            // QB-16 probe aid, GTA2DX9_LOG_NEAR_PED=1: three times a second, the nearest
            // standing figure to the player's own, its distance and its bearing off his
            // drawn facing (radians, + to his right), so a script can turn onto someone.
            static int on = -1;
            if (on < 0) { char v[8] = {}; on = GetEnvironmentVariableA("GTA2DX9_LOG_NEAR_PED", v, sizeof v) && v[0] == '1'; }
            static uint32_t nearFrame = 0;
            static float nearD = 1e9f, nearA = 0.0f, ownX = 0.0f, ownZ = 0.0f, ownH = 0.0f;
            static bool ownValid = false;
            if (on) {
                if (g_carFrame != nearFrame) {
                    if (nearD < 10.0f && g_carFrame % 10 == 0) Log("qb16: near ped d=%.2f bearing=%.2f", nearD, nearA);
                    nearFrame = g_carFrame; nearD = 1e9f;
                }
                if (ownPed) { ownX = gx; ownZ = gz; ownH = track.heading; ownValid = true; }
                if (CurrentViewMode() == ViewMode::FirstPerson && g_playerPosValid) {   // his figure is not drawn: the eye
                    ownX = g_playerPosX; ownZ = g_playerPosZ; ownH = std::atan2(g_viewForward.x, g_viewForward.z); ownValid = true;
                }
                if (!ownPed && ownValid && !sprite.corpse) {
                    const float vx = gx - ownX, vz = gz - ownZ, d = std::sqrt(vx * vx + vz * vz);
                    if (d < nearD && d > 0.3f) {
                        float a = std::atan2(vx, vz) - ownH;
                        while (a > kPi) a -= 2.0f * kPi;
                        while (a < -kPi) a += 2.0f * kPi;
                        nearD = d; nearA = a;
                    }
                }
            }
        }

        if (g_groundModels) {
            // Which of the people he is: fixed by his object, so he keeps his look.
            // (the protagonist: always the manifest's default, unless a developer remap
            // override is on: then he is drawn as that type too, the showcase's subject)
            const Model* model = (ownPed && PedRemapEffective(-1, 0) < 0)
                                     ? ModelForPedestrian()
                                     : nullptr;
            // His type (police, gang, medic, a civilian outfit) is the remap the
            // game drew his sprite with: the texture's palette gives it back.
            int remap = -1;
            if (!model) {
                const TextureRecord* rec = static_cast<const TextureRecord*>(sprite.texture);
                remap = PedRemapEffective(rec ? PedRemapForPalette(rec->palette) : -1, static_cast<uint32_t>(sprite.object >> 4));
                // No remap palette: the peds the game draws from their own sprite sets
                // rather than a remap of the common body (DMA: EMERG_GRAPHIC = SWAT, FBI;
                // GANG_GRAPHIC = Zaibatsu). The body is the frame's block of 158; they drew
                // as random civilians before (a33_pol4: SWAT shooting in plain clothes).
                if (remap < 0) {
                    const unsigned body = sprite.pedFrame / 158u;
                    static bool logged[8] = {};
                    if (body < 8 && !logged[body]) {
                        logged[body] = true;
                        Log("models: pedestrian without a remap palette on body %u (frame %u, palette %d) -> %s", body, sprite.pedFrame,
                            rec ? rec->palette : -1, body >= 2 ? "police type (SWAT/FBI)" : body == 1 ? "zaibatsu type" : "plain list");
                    }
                    if (body >= 2) remap = PedRemapHasType(53) ? 53 : 0;   // SWAT/FBI kit (ASSET-PEDS), else the police
                    else if (body == 1) remap = 8;   // the suits
                }
                model = ModelForPedestrian(static_cast<uint32_t>(sprite.object >> 4), remap);
            }
            // Behind the camera he is not drawn at all (his track above still
            // follows him, so he comes back without a jump). Beyond eight
            // blocks his poses are quantised twice as coarsely, so distant
            // people share cached poses and cost no skinning of their own.
            if (!sprite.corpse) g_pedSpots.push_back({gx, cy, gz});
            if (model && BehindView(gx, cy, gz, 0.6f)) continue;
            if (model && OutsideViewFrustum(gx, cy, gz, 0.75f)) continue;   // beside the picture: not drawn, track kept
            const float eyeDx = gx - g_viewEye.x, eyeDz = gz - g_viewEye.z;
            const float eyeD2 = eyeDx * eyeDx + eyeDz * eyeDz;
            const bool farAway = eyeD2 > 64.0f;
            const float cycleSteps = farAway ? 12.0f : 24.0f, idleSteps = farAway ? 5.0f : 10.0f;
            // Level of detail: the nearest eight within ten blocks are posed every
            // frame; the rest hold their pose for three frames at a time (the
            // cache answers the two in between); beyond eighteen blocks a figure
            // is the idle key, one pose shared by everyone that far off.
            track.eyeD2 = eyeD2;
            const int lod = eyeD2 > 18.0f * 18.0f ? 2 : (eyeD2 > 10.0f * 10.0f || track.rank >= 8) ? 1 : 0;
            if (model) {
                // The character, at his pace, where the figure would stand, facing
                // his drawn heading, upright, leaning a little into a turn.
                // CROWD: his own build and clothes (CrowdLookFor).
                const bool ownFigure = ownPed;   // (ownPed: the boarding ghost of the player too)
                const CrowdLook look = CrowdLookFor(static_cast<uint32_t>(sprite.object >> 4), *model, remap, ownFigure);
                float typeScale = 1.0f, typeWidth = 1.0f;
                if (!ownFigure) PedTypeBuild(remap, &typeScale, &typeWidth);   // ASSET-PEDS-2: the Hulks are bigger
                const float scale = kPedHeight * look.height * typeScale / (std::max)(model->Height(), 0.01f);
                const float paceFactor = (std::min)(track.drawnSpeed / 1.5f, 1.0f);
                float roll = -track.turnRate * paceFactor * 0.03f;
                if (roll > 0.1f) roll = 0.1f;
                if (roll < -0.1f) roll = -0.1f;
                const float cr = std::cos(roll), sr = std::sin(roll);
                // QB-20: the lean of acceleration, forward into a start and back into a
                // stop, from the change of his leg pace, on a critically damped spring
                // (about 0.15 s), at most 6 degrees forward and 3 back.
                {
                    const float accel = (track.legSpeed - track.leanSpeed) / (std::max)(dt, 1e-3f);
                    track.leanSpeed = track.legSpeed;
                    float want = accel * (accel > 0.0f ? 0.035f : 0.02f);
                    want = (std::max)(-0.05f, (std::min)(0.105f, want));
                    if (track.action != 0 && track.action != 2 && !IsCarryAction(track.action)) want = 0.0f;
                    const float w0 = 14.0f, h = (std::min)(dt, 0.05f);
                    track.leanV += (w0 * w0 * (want - track.lean) - 2.0f * w0 * track.leanV) * h;
                    track.lean += track.leanV * h;
                    track.lean = (std::max)(-0.06f, (std::min)(0.11f, track.lean));
                }
                const float cp = std::cos(track.lean), sp = std::sin(track.lean);
                // Rows: right, up, forward; right and up turned about forward by the roll,
                // then up and forward tipped about right by the lean (the feet stay put).
                gta2::Mat4 placed = m;
                placed.m[0][0] = hz * cr;  placed.m[0][1] = sr;  placed.m[0][2] = -hx * cr;
                placed.m[1][0] = -hz * sr * cp + hx * sp; placed.m[1][1] = cr * cp;  placed.m[1][2] = hx * sr * cp + hz * sp;
                placed.m[2][0] = hx * cp + hz * sr * sp;  placed.m[2][1] = -cr * sp; placed.m[2][2] = hz * cp - hx * sr * sp;
                placed.m[3][0] = gx; placed.m[3][1] = cy - 0.01f - boardSink; placed.m[3][2] = gz;
                gta2::Mat4 fit;
                fit.m[0][0] = scale * look.width * typeWidth * model->forward; fit.m[1][1] = scale; fit.m[2][2] = scale * look.width * typeWidth * model->forward;
                fit.m[3][1] = -model->boundsMin.y * scale; fit.m[3][3] = 1.0f;
                gta2::Mat4 world;
                for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) {
                    float acc = 0.0f;
                    for (int k = 0; k < 4; ++k) acc += fit.m[r][k] * placed.m[k][c];
                    world.m[r][c] = acc;
                }
                // A swimmer lies in the water to his shoulders: the prone clip puts
                // him at the surface, the figure is sunk the rest of the way.
                if (track.action == 9 || (track.action == 4 && track.waterFrame)) {
                    // Drowning: in to the chest at once, then under over three seconds
                    // (and a body in the water stays under).
                    const float inWater = track.waterFrame ? static_cast<float>(g_carFrame - track.waterFrame) / 30.0f : 0.0f;
                    const float sink = 0.16f + 0.30f * (std::min)(1.0f, inWater / 3.0f);
                    world.m[3][1] -= sink * (std::min)(1.0f, track.actionWeight);
                }
                // The clips: walk and run from the ground he covers, so the feet
                // do not slide; idle, one of three, at his own offset and pace;
                // walk and idle cross-faded over 0.2 s, walk and run over 0.25 s.
                const ModelAnimation* walk = model->Animation("walk");
                const ModelAnimation* run = model->Animation("run");
                static const char* const kIdles[3] = {"idle", "idle2", "idle3"};
                const ModelAnimation* idle = model->Animation(kIdles[track.idleVariant]);
                if (!idle) idle = model->Animation("idle");
                // ACTIONS-3D-4: locomotion from the drawn figure's own motion. The cycle
                // advances by the ground the figure covered along its legs' heading
                // (signed: pushed back, it steps back), with no cap, so the planted foot
                // stays put at any pace; walk, run and sprint are blended by that pace
                // (the sprint's stride is the run's x1.4, so at the player's 1.9 blocks a
                // second the legs cycle 2.5 times a second, not 3.6); idle when still,
                // with hysteresis so a figure creeping at the threshold does not flicker.
                // QB-20: the mocap fast run is the sprint where the avatar has it (its own
                // stride and phase from the loco tables); the procedural one otherwise.
                const ModelAnimation* sprint = model->Animation("run_fast");
                const Model::Loco* locoFast = sprint ? model->LocoFor("run_fast") : nullptr;
                if (!locoFast) sprint = model->Animation("sprint");
                const Model::Loco* locoRun = model->LocoFor("run");
                // Where the run's first frame sits on the walk cycle (the old clips: half a cycle on).
                const float runPh0 = locoRun && !locoRun->phase.empty() ? locoRun->phase[0] : 0.5f;
                const float fastPh0 = locoFast && !locoFast->phase.empty() ? locoFast->phase[0] : 0.0f;
                const float sprintOverRun = locoFast && model->runStride > 0.0f && locoFast->Length() > 0.01f
                    ? locoFast->Covered() * (sprint->length / locoFast->Length()) / model->runStride : kSprintStrideOverRun;
                const ModelAnimation* turnStep = model->Animation("turn_step");
                if (track.legSpeed > 0.08f) track.moveOn = true;
                else if (track.legSpeed < 0.04f) track.moveOn = false;
                const bool wasMoving = track.walkWeight > 0.5f;
                // ANIM-BLEND-AUDIT: a linear ramp (0.2 s in, 0.25 s out), drawn through a smoothstep
                // (walkW below), in place of an exponential ease whose first frame took a third of
                // the change (a one-frame jump of the legs from the idle into the cycle).
                if (track.moveOn) track.walkWeight = (std::min)(1.0f, track.walkWeight + dt / 0.2f);
                else track.walkWeight = (std::max)(0.0f, track.walkWeight - dt / 0.25f);
                const float runTarget = run && model->runStride > 0.0f ? Smoothstep(0.6f, 0.9f, track.legSpeed) : 0.0f;
                track.runWeight += (runTarget - track.runWeight) * (std::min)(1.0f, dt / 0.2f);
                const float sprintTarget = sprint && run && model->runStride > 0.0f ? Smoothstep(1.2f, 1.7f, track.legSpeed) : 0.0f;
                track.sprintWeight += (sprintTarget - track.sprintWeight) * (std::min)(1.0f, dt / 0.2f);
                const float walkCycle = model->stride > 0.0f ? model->stride * scale : 0.7f;
                const float runCycle = model->runStride > 0.0f ? model->runStride * scale : walkCycle * 1.4f;
                const float fastCycle = runCycle + (runCycle * sprintOverRun - runCycle) * track.sprintWeight;
                const float cycleLen = walkCycle + (fastCycle - walkCycle) * track.runWeight;
                if (track.moveOn) {
                    track.settleTo = -1.0f;
                    float c = track.cycle + track.stepFwd / cycleLen;
                    c -= std::floor(c);
                    track.cycle = c;
                } else {
                    if (wasMoving && track.settleTo < 0.0f) {
                        // Stopping: the nearest phase where the feet pass each other (the
                        // walk's 0 and 0.5; the run is played half a cycle on, the same
                        // phases), reached in 0.2 s while the idle fades in.
                        track.settleTo = std::floor(track.cycle * 2.0f + 0.5f) * 0.5f;
                    }
                    if (track.settleTo >= 0.0f) {
                        const float d = track.settleTo - track.cycle;
                        const float stepC = dt / 0.2f * 0.25f;
                        if (std::fabs(d) <= stepC) { track.cycle = track.settleTo - std::floor(track.settleTo); track.settleTo = -1.0f; }
                        else track.cycle += d > 0.0f ? stepC : -stepC;
                        if (track.cycle < 0.0f) track.cycle += 1.0f;
                    }
                }
                // Turning on the spot: the feet step (turn_step, a legs-only layer over
                // the idle), one cycle per 100 degrees turned; when the turn stops, the
                // step finishes to the next feet-together phase.
                {
                    const float turning = std::fabs(track.turnRate);
                    const bool turnOn = turnStep && !track.moveOn && track.walkWeight < 0.5f && turning > 0.9f && track.action != 4;
                    if (turnOn) track.turnCycle += turning * dt / 1.745f;
                    else if (track.turnWeight > 0.01f) {
                        const float to = std::ceil(track.turnCycle * 2.0f - 1e-3f) * 0.5f;
                        track.turnCycle = (std::min)(to, track.turnCycle + dt * 1.5f);
                    }
                    track.turnCycle -= std::floor(track.turnCycle);
                    track.turnWeight += ((turnOn ? 1.0f : 0.0f) - track.turnWeight) * (std::min)(1.0f, dt / (turnOn ? 0.08f : 0.15f));
                }
                // QB-20/39: mocap starts, stops and fidgets (Rocketbox motion capture,
                // retargeted on import; the tables are Model::Loco). A start is driven by
                // the ground he covers (or real time, whichever is ahead) and holds the
                // cycle on the phase its feet are at, so it hands over to the walk or run
                // without a skip; a stop is entered at the frame whose feet match the
                // cycle's, in its walking part, and plays out in real time into the idle;
                // after 5-13 s standing still he fidgets (looks round, scratches, shifts).
                const ModelAnimation* transClip = nullptr;
                const Model::Loco* transLoco = nullptr;
                {
                    static const char* const kTrans[6] = {nullptr, "walk_start", "run_start", "walk_stop", "run_stop", nullptr};
                    static const char* const kFidgets[4] = {"fidget1", "fidget2", "fidget3", "fidget4"};
                    const int lastTrans = track.trans;
                    track.paceHold = (std::max)(track.legSpeed, track.paceHold - 2.0f * dt);
                    const bool free = track.action == 0 && lod < 2;
                    const bool moving = track.moveOn;
                    if (track.trans == 5 && (moving || !free || track.turnWeight > 0.05f)) track.trans = 0;
                    if ((track.trans == 3 || track.trans == 4) && (moving || !free)) track.trans = 0;
                    // ANIM-BLEND-AUDIT: the starts are forward clips: walking backwards (Down) is
                    // the cycle played backwards, never a start (its feet slid back 25 cm a frame).
                    const bool backward = track.stepFwd < -0.002f;
                    if ((track.trans == 1 || track.trans == 2) && (!moving || !free || backward)) track.trans = 0;
                    if (moving && !wasMoving && free && !backward && track.trans == 0 && track.walkWeight < 0.6f) {
                        const int k = (std::max)(track.legSpeed, track.speed) > 0.75f ? 2 : 1;
                        if (model->Animation(kTrans[k]) && model->LocoFor(kTrans[k])) {
                            track.trans = k; track.transT = 0.0f; track.transDist = 0.0f;
                        }
                    }
                    if (!moving && wasMoving && free && (track.trans == 0 || track.trans == 1 || track.trans == 2)) {
                        const int k = (track.runWeight > 0.5f || track.paceHold > 0.75f) ? 4 : 3;
                        const Model::Loco* l = model->LocoFor(kTrans[k]);
                        if (model->Animation(kTrans[k]) && l && l->phase.size() == l->dist.size() && l->dist.size() > 6) {
                            // The walking part: until its pace falls under 60 % of its first.
                            const float v0 = l->dist[3] - l->dist[0];
                            size_t decel = 3;
                            while (decel + 3 < l->dist.size() && l->dist[decel + 3] - l->dist[decel] > 0.6f * v0) ++decel;
                            // His feet on the clip's reference cycle (the run's for a run stop).
                            float c = track.cycle - (k == 4 ? runPh0 : 0.0f);
                            c -= std::floor(c);
                            size_t best = 0; float bestD = 2.0f;
                            for (size_t i = 0; i <= decel; ++i) {
                                float d = std::fabs(l->phase[i] - c);
                                d = (std::min)(d, 1.0f - d);
                                if (d < bestD - 0.02f || (d < 0.05f && d <= bestD + 0.02f)) { bestD = (std::min)(d, bestD); best = i; }
                            }
                            track.trans = k; track.transT = static_cast<float>(best) / 15.0f;
                            track.settleTo = -1.0f;
                        } else {
                            track.trans = 0;
                        }
                    }
                    // Standing still: count, and fidget now and then.
                    if (!moving && free && track.trans == 0 && track.walkWeight < 0.05f && track.turnWeight < 0.05f) {
                        if (track.fidgetAt <= 0.0f) {
                            const uint32_t h = static_cast<uint32_t>(sprite.object >> 4) * 2654435761u;
                            track.fidgetAt = 5.0f + static_cast<float>((h >> 8) % 800u) / 100.0f;
                            track.fidgetNext = static_cast<int>((h >> 20) % 4u);
                        }
                        track.stillTime += dt;
                        if (track.stillTime > track.fidgetAt) {
                            const char* name = kFidgets[track.fidgetNext % 4];
                            ++track.fidgetNext;
                            if (model->Animation(name)) { track.trans = 5; track.transT = 0.0f; track.transEnd = (std::min)(model->Animation(name)->length, 9.0f); }
                            track.stillTime = 0.0f;
                            track.fidgetAt = 7.0f + static_cast<float>((static_cast<uint32_t>(sprite.object >> 4) * 40503u + track.fidgetNext * 977u) % 900u) / 100.0f;
                        }
                    } else if (track.trans != 5) {
                        track.stillTime = 0.0f;
                    }
                    if (track.trans == 5) {
                        transClip = model->Animation(kFidgets[(track.fidgetNext + 3) % 4]);
                        track.transT += dt;
                        if (!transClip || track.transT >= track.transEnd) { track.trans = 0; transClip = nullptr; }
                        else track.transW = Smoothstep(0.0f, 0.6f, track.transT) * (1.0f - Smoothstep(track.transEnd - 0.7f, track.transEnd, track.transT));
                    } else if (track.trans >= 1 && track.trans <= 4) {
                        transClip = model->Animation(kTrans[track.trans]);
                        transLoco = model->LocoFor(kTrans[track.trans]);
                        if (!transClip || !transLoco) track.trans = 0;
                    }
                    // The pace is still easing in on a start's first frames: a walk start that
                    // finds him at a run within its first 0.25 s becomes the run start.
                    if (track.trans == 1 && track.transT < 0.25f && (std::max)(track.legSpeed, track.speed) > 0.75f &&
                        model->Animation("run_start") && model->LocoFor("run_start")) {
                        track.trans = 2; transClip = model->Animation("run_start"); transLoco = model->LocoFor("run_start");
                    }
                    if (track.trans == 1 || track.trans == 2) {
                        // The game is at full pace at once, the capture accelerates: played at
                        // the pace of the ground he covers, but no faster than twice real time
                        // (a push-off seen, at the cost of a little slide) nor slower than real time.
                        // (ANIM-BLEND-AUDIT measured the slide: 6 cm a frame on average, 22 at worst;
                        // four times made it worse, 18 on average: the start's feet are not where
                        // the game's pace needs them at any speed of the clip.)
                        const float before = transLoco->TimeAtDist(track.transDist / scale);
                        track.transDist += (std::max)(0.0f, track.stepFwd);
                        const float byDist = transLoco->TimeAtDist(track.transDist / scale) - before;
                        const float advance = (std::max)(dt, (std::min)(2.0f * dt, byDist));
                        track.transT += advance;
                        const float rate = advance / (std::max)(dt, 1e-4f);   // clip seconds per real second, 1..2
                        const float len = (std::min)(transLoco->Length(), transClip->length);
                        if (track.transT >= len) { track.trans = 0; transClip = nullptr; }
                        else {
                            // The cycle follows the start's feet, so the hand-over meets it in step.
                            float c = transLoco->PhaseAt(track.transT) + (track.trans == 2 ? runPh0 : 0.0f);
                            track.cycle = c - std::floor(c);
                            // The start alone until its last quarter second, then the cycle; the quarter
                            // second in real time at the pace it is played (ANIM-BLEND-AUDIT: it was 0.25 s
                            // of clip, which at twice the pace is four frames).
                            track.transW = Smoothstep(0.0f, 0.25f, (len - track.transT) / rate);
                        }
                    } else if (track.trans == 3 || track.trans == 4) {
                        track.transT += dt;
                        const float len = transClip->length;
                        if (track.transT >= len) { track.trans = 0; transClip = nullptr; track.stillTime = 0.0f; }
                        else track.transW = 1.0f - Smoothstep(len - 0.45f, len, track.transT);   // into the idle
                    }
                    if (!track.trans) track.transW = 0.0f;
                    // ANIM-BLEND-AUDIT: a start, stop or fidget that ended while still drawn
                    // (cut short: he moved, stopped, turned or acted) fades out from the pose it
                    // stopped at over 0.25 s instead of vanishing (see the locomotion mix below).
                    // (a weaker one never replaces a stronger one still fading: a stop cut by a walk
                    // start that turns into a run start a frame later keeps the stop's fade)
                    const float fadeNow = track.transFadeClip ? track.transFadeW * Smoothstep(0.0f, 1.0f, track.transFadeK) : 0.0f;
                    if (track.trans != lastTrans && lastTrans != 0 && track.transDrawnClip && track.transDrawnW > 0.05f &&
                        track.transDrawnW >= fadeNow) {
                        track.transFadeClip = track.transDrawnClip; track.transFadeT = track.transDrawnT;
                        track.transFadeW = track.transDrawnW; track.transFadeK = 1.0f;
                    }
                    // (a walk start that becomes a run start is one start: its entry carries on)
                    track.transAge = track.trans != lastTrans && !(lastTrans == 1 && track.trans == 2) ? dt : track.transAge + dt;
                    if (track.transFadeClip) {
                        track.transFadeK -= dt / 0.25f;
                        if (track.transFadeK <= 0.0f) { track.transFadeClip = nullptr; track.transFadeK = 0.0f; }
                    }
                    if (track.trans != lastTrans && (g_logFigures || g_logPedFrames)) {
                        static unsigned transLogs = 0;
                        if (transLogs++ < 400)
                            Log("loco: %04x %s t=%.2f leg=%.2f cyc=%.3f own=%d", static_cast<unsigned>((sprite.object >> 2) & 0xFFFF),
                                track.trans == 0 ? "cycle/idle" : track.trans == 5 ? "fidget" : kTrans[track.trans], track.transT,
                                track.legSpeed, track.cycle, ownPed ? 1 : 0);
                    }
                }
                float u = std::floor(track.cycle * cycleSteps) / cycleSteps;   // quantised: shared poses
                float idleTime = idle ? std::floor((static_cast<float>(g_carFrame) / 30.0f * track.idleRate +
                                                    track.idleOffset) * idleSteps) / idleSteps
                                      : 0.0f;
                float walkW = std::floor(Smoothstep(0.0f, 1.0f, track.walkWeight) * 8.0f + 0.5f) / 8.0f;
                float runW = std::floor(track.runWeight * 8.0f + 0.5f) / 8.0f;
                float sprintW = std::floor(track.sprintWeight * 8.0f + 0.5f) / 8.0f;
                float turnW = std::floor(track.turnWeight * 8.0f + 0.5f) / 8.0f;
                float turnT = turnStep ? std::floor(track.turnCycle * 16.0f) / 16.0f * turnStep->length : 0.0f;
                float transT = std::floor(track.transT * 30.0f) / 30.0f;
                float transW = std::floor(track.transW * 8.0f + 0.5f) / 8.0f;
                // The action layer: its clip advances in real time (one-shots hold
                // their last pose, the fall holds lying; a knock-down plays back out),
                // and is faded in over the walk or idle, then out again when it is over.
                static const char* const kActionClips[27] = {nullptr, "punch", "aim", "handsup", "fall", "enter_car", "exit_car", "hit", "aim_heavy", "drown",
                                                             "aim_dual", "aim_launcher", "aim_flame", "throw",
                                                             "carry", "carry_dual", "carry_heavy", "carry_launcher", "carry_flame",
                                                             "burn", "fall_air", "cuffed", "hit_head", "grab_door_r",
                                                             "reload", "reload_heavy", "reload_launcher"};
                static const char* const kLyingClips[6] = {"fall", "fall_front", "runover", "blown", "burnt", "jacked"};
                const char* clipName = track.action > 0 && track.action < 27 ? kActionClips[track.action] : nullptr;
                if (track.action == 23 && track.grabLeft) clipName = "grab_door_l";
                if (track.action == 5 && track.jacking) clipName = "jack_pull";   // QB-14
                if (track.action == 4 && track.lieClip > 0 && track.lieClip < 6) clipName = kLyingClips[track.lieClip];
                if (track.action == 1 && track.punchAlt) clipName = "punch2";        // the combo's left jab
                if (track.action == 22 && track.hitSide == 1) clipName = "hit_head2";     // a jab turns his head the other way
                static const char* const kShotClips[4] = {"hit_shot_front", "hit_shot_back", "hit_shot_l", "hit_shot_r"};   // QB-16
                if (track.action == 22 && track.hitSide >= 2 && track.hitSide <= 5) clipName = kShotClips[track.hitSide - 2];
                const ModelAnimation* actionClip = clipName ? model->Animation(clipName) : nullptr;
                // Avatars imported before a clip existed fall back to the nearest older one.
                if (!actionClip && track.action == 5 && track.jacking) actionClip = model->Animation("enter_car");   // before QB-14
                if (!actionClip && track.action == 5) actionClip = model->Animation("getin");
                if (!actionClip && track.action == 6) actionClip = model->Animation("getout");
                if (!actionClip && track.action == 22) actionClip = model->Animation("hit_head");   // an avatar from before QB-16
                if (!actionClip && track.action == 22) actionClip = model->Animation("hit");
                if (!actionClip && track.action == 1) actionClip = model->Animation("punch");
                if (!actionClip && track.action == 4) actionClip = model->Animation("fall");
                if (!actionClip && track.action == 9) actionClip = model->Animation("swim");
                if (!actionClip && track.action == 20) actionClip = model->Animation("hit");
                if (!actionClip && IsReloadAction(track.action)) { track.action = 0; track.reloadStart = 0; }   // an avatar from before QB-29
                float actionT = 0.0f;
                if (actionClip) {
                    const float len = actionClip->length;
                    const bool oneShot = track.action == 1 || track.action == 5 || track.action == 6 || track.action == 7 || track.action == 13 ||
                                         track.action == 22 || IsReloadAction(track.action);
                    if (track.actionReverse) {
                        track.actionTime -= dt * 1.4f;
                        if (track.actionTime <= 0.0f) { track.action = 0; track.actionReverse = false; actionClip = nullptr; }
                    } else {
                        // Getting in: the reach and the pull run while the game backs him
                        // off the door (climb frames 24-31), the duck under the roof once
                        // it moves him in (32-35), a little faster.
                        if (track.action == 5 && track.jacking) {
                            // QB-14, jack_pull: the reach and the yank while he comes to the
                            // door (frames below 24), both hands in and the grip held until the
                            // driver is seen thrown out beside him, then the haul and the fling
                            // in real time, and the duck a little faster once the game moves
                            // him in (32-35).
                            const unsigned f5 = sprite.pedFrame % 158u;
                            bool out = false;
                            for (const JackThrow& j : g_jackThrows)
                                if (j.frame >= track.carStateFrame && (j.x - cx) * (j.x - cx) + (j.z - cz) * (j.z - cz) < 1.3f * 1.3f) out = true;
                            if (sprite.pedState == 3 && f5 < 24u) track.actionTime = (std::min)(track.actionTime + dt, 0.5f);
                            else if (sprite.pedState == 3 && f5 < 32u && !out) track.actionTime = (std::min)(track.actionTime + dt, 0.95f);
                            else track.actionTime += dt * (sprite.pedState == 3 && f5 >= 32u ? 1.6f : 1.0f);
                        } else if (track.action == 5) {
                            const unsigned f5 = sprite.pedFrame % 158u;
                            if (sprite.pedState == 3 && f5 < 32u) track.actionTime = (std::min)(track.actionTime + dt, 0.65f);
                            else track.actionTime += dt * 1.6f;
                        } else {
                            track.actionTime += dt;
                        }
                        // The game started the swing again: back to its first frames (115-116)
                        // from later ones. Not on its jumps between the swing and the recovery
                        // frames (123-130) while he walks with the key held, which cut the
                        // first build's punches off at 0.4 s.
                        const unsigned pf = sprite.pedFrame % 158u, lpf = track.lastPedFrame % 158u;
                        if (track.action == 1 && wantAction == 1 && pf <= 116u && pf >= 115u && lpf > 116u &&
                            track.actionTime > 0.5f) {
                            track.actionTime = 0.0f;   // the game started the swing again: the other fist
                            track.punchAlt = !track.punchAlt;
                            track.lastPunchT = 0.0f;
                        }
                        if (track.action == 1) {
                            // The strike key (0.33 s): logged with the figure it would reach (within
                            // half a block, 60 degrees either side), for the checks; whether it
                            // landed is the game's (the victim's health, see hitNow).
                            if (track.lastPunchT < 0.33f && track.actionTime >= 0.33f) {
                                const FigureSpot* victim = nullptr;
                                float best = 0.5f * 0.5f;
                                for (const std::vector<FigureSpot>* list : {&g_figuresNow, &g_figuresLast}) {
                                    for (const FigureSpot& f : *list) {
                                        if (f.object == sprite.object) continue;
                                        const float vx = f.x - gx, vz = f.z - gz;
                                        const float d2 = vx * vx + vz * vz;
                                        if (d2 >= best || d2 < 1e-6f) continue;
                                        const float d = std::sqrt(d2);
                                        if ((vx * std::sin(track.heading) + vz * std::cos(track.heading)) / d < 0.5f) continue;
                                        best = d2; victim = &f;
                                    }
                                    if (victim) break;
                                }
                                if (g_logFigures || g_logPedFrames)
                                    Log("fig: punch %04x %s lands on %04x", static_cast<unsigned>((sprite.object >> 2) & 0xFFFF),
                                        track.punchAlt ? "jab" : "cross", victim ? static_cast<unsigned>((victim->object >> 2) & 0xFFFF) : 0u);
                            }
                            track.lastPunchT = track.actionTime;
                            track.lastPunchFrame = g_carFrame;
                        }
                        // The recoil: each shot restarts the stance clip from its kick.
                        if (shotNow && IsAimAction(track.action) && track.actionTime > 0.05f) track.actionTime = 0.0f;
                        if (track.action == 13 && track.actionTime >= len) track.action = 0;   // the throw is over
                        if (oneShot && track.actionTime >= len && wantAction != track.action) track.action = 0;
                        if (!oneShot && track.action != 4 && wantAction != track.action && wantAction != 4) track.action = 0;
                        if (!track.action) {
                            // Ended: faded out from where it stopped, not dropped.
                            track.fadeClip = actionClip;
                            track.fadeT = std::floor((std::min)((std::max)(track.actionTime, 0.0f), len - 0.001f) * 30.0f) / 30.0f;
                            actionClip = nullptr;
                        }
                    }
                    actionT = (std::min)((std::max)(track.actionTime, 0.0f), len - 0.001f);
                    actionT = std::floor(actionT * 30.0f) / 30.0f;
                }
                if (boarding && boardOut.action && actionClip && track.action == boardOut.action && !(track.action == 5 && track.jacking)) {
                    // The plan's own time on the clip, at full weight from its first frame
                    // (an exit starts seated, not standing).
                    track.actionTime = boardOut.clipT;
                    actionT = std::floor((std::min)(boardOut.clipT, actionClip->length - 0.001f) * 30.0f) / 30.0f;
                    track.actionWeight = 1.0f;
                }
                track.lastPedFrame = sprite.pedFrame;
                static unsigned lyingLogs = 0;
                if (g_logPedFrames && track.action == 4 && lyingLogs < 400 && (++lyingLogs % 5) == 0) {
                    Log("ped anim: lying %p at %.2f,%.2f,%.2f t=%.2f w=%.2f clip %s len %.2f corpse %d frame %u",
                        reinterpret_cast<const void*>(sprite.object), gx, cy, gz, track.actionTime, track.actionWeight,
                        actionClip ? "yes" : "NO", actionClip ? actionClip->length : 0.0f, sprite.corpse ? 1 : 0,
                        sprite.pedFrame % 158u);
                }
                if (g_logPedFrames && ownPed && (g_carFrame % 15u) == 0) {
                    Log("player figure: action %d want %d t %.2f w %.2f clip %s weapon %d lod %d twist %.2f speed %.2f walkW %.2f frame %u state %d",
                        track.action, wantAction, track.actionTime, track.actionWeight, actionClip ? actionClip->name.c_str() : "-", track.weapon, lod,
                        track.twist, track.drawnSpeed, track.walkWeight, sprite.pedFrame % 158u, sprite.pedState);
                }
                const float wantWeight = actionClip ? 1.0f : 0.0f;
                // In fast (a punch, a blow, a shot are quick), out over 0.15 s.
                const float fadeIn = track.action == 4 ? 0.1f : (track.action == 1 || track.action == 22 || IsAimAction(track.action)) ? 0.05f : 0.15f;
                track.actionWeight += (wantWeight - track.actionWeight) * (std::min)(1.0f, dt / (actionClip ? fadeIn : 0.15f));
                if (actionClip) track.fadeClip = nullptr;
                bool actUpper = IsUpperLayer(track.action);
                if (!actionClip && track.fadeClip && track.actionWeight > 0.06f && ModelIsKnown(model)) {
                    // The ended action's last pose, fading over the locomotion.
                    actionClip = static_cast<const ModelAnimation*>(track.fadeClip);
                    actionT = track.fadeT;
                    actUpper = true;
                }
                if (!actionClip) track.fadeClip = nullptr;
                float actW = actionClip ? std::floor(track.actionWeight * 8.0f + 0.5f) / 8.0f : 0.0f;
                if (lod == 2) {
                    // The idle key; a body lying on the ground stays lying.
                    u = 0.0f; idleTime = 0.0f; walkW = 0.0f; runW = 0.0f; sprintW = 0.0f; turnW = 0.0f; turnT = 0.0f;
                    transClip = nullptr; transW = 0.0f;
                    if (track.action == 4 && actionClip) { actW = 1.0f; actionT = (std::max)(0.0f, actionClip->length - 0.001f); }
                    else { actW = 0.0f; actionClip = nullptr; }
                } else if (lod == 1) {
                    const bool refresh = track.lodFrame == 0 || ((g_carFrame + static_cast<uint32_t>(sprite.object >> 4)) % 3u) == 0 ||
                                         g_carFrame - track.lodFrame > 3;
                    if (refresh) {
                        track.lodFrame = g_carFrame;
                        track.lodU = u; track.lodIdleT = idleTime; track.lodWalkW = walkW; track.lodRunW = runW;
                        track.lodActT = actionT; track.lodActW = actW;
                        track.lodSprintW = sprintW; track.lodTurnW = turnW; track.lodTurnT = turnT;
                        track.lodTransT = transT; track.lodTransW = transW;
                    } else {
                        transT = track.lodTransT; transW = track.lodTransW;
                        u = track.lodU; idleTime = track.lodIdleT; walkW = track.lodWalkW; runW = track.lodRunW;
                        actionT = track.lodActT; actW = actionClip ? track.lodActW : 0.0f;
                        sprintW = track.lodSprintW; turnW = track.lodTurnW; turnT = track.lodTurnT;
                    }
                }
                const float walkTime = walk ? u * walk->length : 0.0f;
                // The run (and the sprint made from it) put the same foot forward half a
                // cycle after the walk does: played half a cycle on, so a walk/run blend
                // moves both legs the same way instead of cancelling them out.
                // QB-20: with the mocap tables the offsets are measured (the run's first frame
                // on the walk, the fast run's on the run) instead of assumed.
                const float runU = u - runPh0 - std::floor(u - runPh0);
                const float runTime = run ? runU * run->length : 0.0f;
                const float fastU = runU - fastPh0 - std::floor(runU - fastPh0);
                const float sprintTime = sprint ? (locoFast ? fastU : runU) * sprint->length : 0.0f;
                // ANIM-BLEND-AUDIT: the locomotion as one continuous mix of clips (the pair
                // below plus model_store's ModelSetLayers), in place of a pair that swapped clips
                // when a weight crossed a line: the walk dropped the frame the sprint came in, the
                // idle->moving fade swapped walk for run at runW 0.5, the turn step vanished when
                // he moved, and a start, stop or fidget cut short vanished in one frame (pops of
                // 20-50 cm at the hands and feet in docs/anim-audit.md). In order:
                //   the moving cycle: walk -> run by runW, the sprint over it by sprintW x runW;
                //   the idle over that by 1 - walkW; the turn step over the idle by turnW;
                //   the start, stop or fidget over all of it by its weight (a start comes out of
                //   the mix over its first 0.2 s, a stop goes into its clip over its first 0.25 s);
                //   a start/stop/fidget cut short, fading out from where it stopped over 0.25 s.
                // Every weight eases, so no frame jumps; weights stay in eighths for the pose cache.
                auto q8 = [](float w) { return std::floor(w * 8.0f + 0.5f) / 8.0f; };
                const ModelAnimation* locoA = idle; float locoTA = idleTime;
                const ModelAnimation* locoB = nullptr; float locoTB = 0.0f, locoW = 0.0f;
                const ModelAnimation* layerClip[kModelLayers] = {};
                float layerT[kModelLayers] = {}, layerW[kModelLayers] = {};
                int layers = 0;
                auto layer = [&](const ModelAnimation* c, float t, float w) {
                    w = q8((std::min)(1.0f, w));
                    if (c && w > 0.001f && layers < kModelLayers) { layerClip[layers] = c; layerT[layers] = t; layerW[layers] = w; ++layers; }
                };
                {
                    // While a start comes in, the cycle stays behind the idle (the start sets the
                    // cycle's phase from its own feet, which jumps): the start rises out of the idle
                    // and hands to the cycle at its end, as the pair did. Eased, so a start cut short
                    // brings the cycle back over 0.2 s.
                    const bool inStart = (track.trans == 1 || track.trans == 2) && transClip;
                    const float cycleTarget = inStart ? Smoothstep(0.0f, 0.2f, track.transAge) : 1.0f;
                    track.cycleVis += (std::max)(-dt / 0.2f, (std::min)(dt / 0.2f, cycleTarget - track.cycleVis));
                    if (lod != 0) track.cycleVis = cycleTarget;
                    const float moveW = walkW * track.cycleVis;
                    if (walk && moveW > 0.001f) {
                        locoA = walk; locoTA = walkTime;
                        if (run && runW > 0.001f) { locoB = run; locoTB = runTime; locoW = runW; }
                        if (sprint && run) layer(sprint, sprintTime, sprintW * runW);
                        if (moveW < 0.999f) layer(idle, idleTime, 1.0f - moveW);
                    }
                    if (turnStep) layer(turnStep, turnT, turnW);
                    float transDrawn = 0.0f, tt = 0.0f;
                    if (transClip && transW > 0.001f) {
                        tt = (std::min)(transT, transClip->length - 0.001f);
                        float w = transW;
                        // (in real time: a start's clip can run at twice its pace)
                        if (track.trans == 1 || track.trans == 2) w *= Smoothstep(0.0f, 0.2f, track.transAge);
                        else if (track.trans == 3 || track.trans == 4) w *= Smoothstep(0.0f, 0.25f, track.transAge);
                        transDrawn = q8(w);
                        layer(transClip, tt, w);
                    }
                    if (lod == 0 && track.transFadeClip && track.transFadeK > 0.001f)
                        layer(static_cast<const ModelAnimation*>(track.transFadeClip), track.transFadeT,
                              track.transFadeW * Smoothstep(0.0f, 1.0f, track.transFadeK));
                    track.transDrawnClip = transDrawn > 0.001f ? transClip : nullptr;
                    track.transDrawnT = tt; track.transDrawnW = transDrawn;
                }
                // The action as an overlay on the pair (model_store ModelSetOverlay): an
                // upper-body layer leaves the legs to the locomotion at any weight; a whole-
                // body clip at full weight is drawn alone (one cached pose for a body lying).
                const bool actAlone = actionClip && actW > 0.999f && !actUpper;
                if (actAlone) { locoA = actionClip; locoTA = actionT; locoB = nullptr; locoW = 0.0f; layers = 0; }
                ModelSetOverlay(actAlone ? nullptr : actionClip, actionT, actAlone ? 0.0f : actW);
                ModelSetLayers(model, layerClip, layerT, layerW, layers);
                device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
                device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
                device->SetFVF(kWorldFvf);
                // A gang member's colours: his clothing (the "_paint" half of a
                // split body texture) multiplied by the remap's colour over the
                // avatar's own; the two halves are alpha-tested back together.
                float tint[3];
                bool tinted = PedRemapTint(remap, *model, tint);
                if (!tinted && look.clothes) { for (int k = 0; k < 3; ++k) tint[k] = look.tint[k]; tinted = true; }
                // ASSET-PEDS: a zoned avatar's shirt, trousers (and hair) in his remap's
                // sprite colours; the protagonist is remap 25 (the default player ped).
                float zones[3][3];
                bool zoneHair = false;
                const bool zoned = model->pedZones && PedZoneTints(ownFigure && remap < 0 ? 25 : remap, *model, zones, &zoneHair);
                if (zoned) {
                    tinted = false;
                    if (!ownFigure)
                        for (int z = 0; z < 2; ++z) for (int k = 0; k < 3; ++k) zones[z][k] = (std::min)(2.0f, zones[z][k] * look.shade);
                    ModelSetZoneTints(zones[0], zones[1], zoneHair ? zones[2] : nullptr);
                    ++g_crowdCount[4];
                }
                ++g_crowdCount[0];
                if (look.clothes) ++g_crowdCount[1];
                if (track.lookingAtPlayer) ++g_crowdCount[2];
                else if (std::fabs(track.headYaw) > 0.2f) ++g_crowdCount[3];
                if (tinted) ModelSetPaintTint(tint);
                if (tinted || zoned || model->splitPaint) {
                    // The test must read the texture's alpha, which is where the
                    // split lives; the pass's own alpha stage may be set to the
                    // vertex colour.
                    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
                    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
                    device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
                    device->SetRenderState(D3DRS_ALPHAREF, 128u);
                    device->SetRenderState(D3DRS_ALPHAFUNC, D3DCMP_GREATEREQUAL);
                }
                // The torso twist of an aim off the walk (see legHeading above),
                // in 3 degree steps so the pose cache can share it; not for the
                // far figures, which hold coarser poses.
                const float twistQ = lod == 0 ? std::floor(track.twist / 0.0524f + 0.5f) * 0.0524f : 0.0f;
                ModelSetTorsoTwist(twistQ);
                // CROWD: the head turn, in 6 degree steps near, 12 further, none far.
                const float headStep = lod == 0 ? 0.105f : 0.21f;
                ModelSetHeadTurn(lod <= 1 ? std::floor(track.headYaw / headStep + 0.5f) * headStep : 0.0f);
                // QB-27: run over (lying clip 2) or blown off his feet (3): a ragdoll
                // seeded from this pose drives the skeleton while he is down.
                const bool ragdoll = RagdollFigure(sprite.object, track.lieClip == 2 ? 1 : track.lieClip == 3 ? 2 : 0,
                                                   track.action == 4 && !track.actionReverse && !track.waterFrame, *model, world,
                                                   gx, cy, gz, track.heading, dt, g_carFrame, locoA, locoTA, locoB, locoTB, locoW);
                // ANIM-VEHICLE-ENTRY: hands and feet onto the car (boarding.h), by IK in model space.
                bool boardIk = false;
                ModelClearLimbTargets();
                if (lod == 0 && g_groundModels) {
                    for (int limb = 0; limb < 4; ++limb) {
                        gta2::Vec3 bt, bp; float bw = 0.0f;
                        if (!BoardingLimb(sprite.object, limb, &bt, &bp, &bw)) continue;
                        float tm[3], pm[3];
                        BoardingWorldToModel(world, bt, false, tm);
                        BoardingWorldToModel(world, bp, true, pm);
                        ModelSetLimbTarget(limb, tm, pm, std::floor(bw * 16.0f + 0.5f) / 16.0f);
                        boardIk = true;
                    }
                }
                ModelDrawBlend(device, *model, world, locoA, locoTA, locoB, locoTB, locoW);
                if (ragdoll) RagdollDone();
                if (boardIk) {
                    // What the hands could not reach goes back to the plan (a lean toward it next frame).
                    for (int limb = 0; limb < 2; ++limb) {
                        float r[3];
                        if (!ModelLimbResidual(limb, r)) continue;
                        const gta2::Vec3 rw{r[0] * world.m[0][0] + r[1] * world.m[1][0] + r[2] * world.m[2][0],
                                            r[0] * world.m[0][1] + r[1] * world.m[1][1] + r[2] * world.m[2][1],
                                            r[0] * world.m[0][2] + r[1] * world.m[1][2] + r[2] * world.m[2][2]};
                        BoardingReportResidual(sprite.object, limb, rw);
                    }
                }
                if (boardIk && g_logFigures) {
                    // Contact: where each driven hand or foot was drawn against its target, blocks.
                    static const char* const kEnds[4] = {"Bip01 L Hand", "Bip01 R Hand", "Bip01 L Foot", "Bip01 R Foot"};
                    char buf[256]; int n = 0;
                    for (int limb = 0; limb < 4; ++limb) {
                        gta2::Vec3 bt, bp; float bw = 0.0f;
                        gta2::Mat4 nm;
                        if (!BoardingLimb(sprite.object, limb, &bt, &bp, &bw)) continue;
                        if (!ModelNodeWorld(*model, kEnds[limb], locoA, locoTA, locoB, locoTB, locoW, &nm)) continue;
                        const float px = nm.m[3][0], py = nm.m[3][1], pz = nm.m[3][2];
                        const float wx = px * world.m[0][0] + py * world.m[1][0] + pz * world.m[2][0] + world.m[3][0];
                        const float wy = px * world.m[0][1] + py * world.m[1][1] + pz * world.m[2][1] + world.m[3][1];
                        const float wz = px * world.m[0][2] + py * world.m[1][2] + pz * world.m[2][2] + world.m[3][2];
                        const float e = std::sqrt((wx - bt.x) * (wx - bt.x) + (wy - bt.y) * (wy - bt.y) + (wz - bt.z) * (wz - bt.z));
                        n += snprintf(buf + n, sizeof buf - n, " %d:w%.2f err%.3f y%.3f", limb, bw, e, wy - cy);
                    }
                    Log("board contact: f=%u o=%04x%s model %s", g_carFrame, static_cast<unsigned>((sprite.object >> 2) & 0xFFFF), buf,
                        model->name.c_str());
                }
                if (g_logJoints) {
                    char layerText[200] = "-";
                    for (int k = 0, at = 0; k < layers && at < 160; ++k)
                        at += snprintf(layerText + at, sizeof layerText - at, "%s%s:%.2f", k ? "|" : "", layerClip[k]->name.c_str(), layerW[k]);
                    // ANIM-BLEND-AUDIT: the joints as drawn (the same pair, overlay and twist),
                    // in the world, for the audit's foot-skate, pop and teleport measures.
                    const float pdx = cx - g_playerPosX, pdz = cz - g_playerPosZ;
                    if (ownPed || (g_playerPosValid && pdx * pdx + pdz * pdz < 2.25f)) {
                        static const char* const kJoints[6] = {"Bip01 L Foot", "Bip01 R Foot", "Bip01 Pelvis", "Bip01 Head",
                                                               "Bip01 L Hand", "Bip01 R Hand"};
                        float jp[6][3] = {};
                        for (int j = 0; j < 6; ++j) {
                            gta2::Mat4 node;
                            if (!ModelNodeWorld(*model, kJoints[j], locoA, locoTA, locoB, locoTB, locoW, &node)) continue;
                            for (int c = 0; c < 3; ++c)
                                jp[j][c] = node.m[3][0] * world.m[0][c] + node.m[3][1] * world.m[1][c] + node.m[3][2] * world.m[2][c] + world.m[3][c];
                        }
                        Log("figj: f=%u o=%04x own=%d st=%d sub=0x%x act=%d at=%.3f aw=%.2f tr=%d trt=%.2f trw=%.2f ww=%.2f rw=%.2f lod=%d "
                            "hd=%.3f game=%.3f,%.3f drawn=%.3f,%.3f gy=%.3f "
                            "lf=%.3f,%.3f,%.3f rf=%.3f,%.3f,%.3f pv=%.3f,%.3f,%.3f he=%.3f,%.3f,%.3f lh=%.3f,%.3f,%.3f rh=%.3f,%.3f,%.3f "
                            "A=%s B=%s w=%.2f O=%s rag=%d L=%s",
                            g_carFrame, static_cast<unsigned>((sprite.object >> 2) & 0xFFFF), ownPed ? 1 : 0, sprite.pedState, sprite.pedSub,
                            track.action, track.actionTime, actW, track.trans, transT, transW, walkW, runW, lod,
                            track.heading, cx, cz, gx, gz, cy,
                            jp[0][0], jp[0][1], jp[0][2], jp[1][0], jp[1][1], jp[1][2], jp[2][0], jp[2][1], jp[2][2],
                            jp[3][0], jp[3][1], jp[3][2], jp[4][0], jp[4][1], jp[4][2], jp[5][0], jp[5][1], jp[5][2],
                            locoA ? locoA->name.c_str() : "-", locoB ? locoB->name.c_str() : "-", locoW,
                            (!actAlone && actionClip) ? actionClip->name.c_str() : "-", ragdoll ? 1 : 0, layerText);
                    }
                }
                ModelSetHeadTurn(0.0f);
                if (tinted) {
                    ModelSetPaintTint(nullptr);
                    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
                }
                if (zoned) {
                    ModelSetZoneTints(nullptr, nullptr, nullptr);
                    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
                }
                // The weapon in his hands while he aims or throws: its own model
                // (assets-src/weapons) held at the hand joints of the pose just
                // drawn. A pistol sits in the right hand's frame (the barrel along
                // the fingers); a two-handed weapon is laid along the line from
                // the right hand (the grip) to the left (the fore-end), so the
                // stance clips place it by their hands. The muzzle flash, light,
                // sparks and case come off its muzzle on the frame of a shot.
                const bool reloadPose = IsReloadAction(track.action);   // QB-29
                const bool stance = IsAimAction(track.action) || track.action == 13 || IsCarryAction(track.action) || reloadPose;
                if (stance && actW > 0.3f && g_pedWeapons && track.weapon > 0 && track.weapon < kWpnCount &&
                    !(track.action == 13 && track.actionTime > 0.34f)) {
                    const WeaponInfo& wi = kWeapons[track.weapon];
                    const Model* weapon = ModelByName(wi.model);
                    if (!weapon) weapon = ModelByName(wi.twoHanded ? "pickup_machine_gun" : "pickup_pistol");
                    // The hands as drawn: the same pair, the overlay still set.
                    const ModelAnimation* base = locoA; const float baseT = locoTA;
                    const ModelAnimation* over = locoB; const float overT = locoTB; const float overW = locoW;
                    gta2::Mat4 hand, handL;
                    const bool haveR = weapon && ModelNodeWorld(*model, "Bip01 R Hand", base, baseT, over, overT, overW, &hand);
                    const bool haveL = haveR && (wi.twoHanded || track.action == 10 || track.action == 15 || reloadPose) &&
                                       ModelNodeWorld(*model, "Bip01 L Hand", base, baseT, over, overT, overW, &handL);
                    if (haveR) {
                        auto mul = [](const gta2::Mat4& a, const gta2::Mat4& b) {
                            gta2::Mat4 o;
                            for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) {
                                float acc = 0.0f;
                                for (int k = 0; k < 4; ++k) acc += a.m[r][k] * b.m[k][c];
                                o.m[r][c] = acc;
                            }
                            return o;
                        };
                        const gta2::Mat4 handWorld = mul(hand, world);
                        const float k = wi.length / (std::max)(0.01f, WeaponSpan(*weapon));
                        gta2::Mat4 place;
                        float dir[3], right[3], up[3];
                        bool placed = false;
                        if (wi.twoHanded && (reloadPose ? track.gripValid : haveL)) {
                            float dl;
                            if (reloadPose) {
                                // QB-29: the left hand is off fetching a magazine: the gun
                                // stays on the line it had in the right hand's frame.
                                for (int c = 0; c < 3; ++c)
                                    dir[c] = handWorld.m[0][c] * track.gripLocal[0] + handWorld.m[1][c] * track.gripLocal[1] + handWorld.m[2][c] * track.gripLocal[2];
                                dl = std::sqrt(dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]);
                            } else {
                                const gta2::Mat4 handLWorld = mul(handL, world);
                                dir[0] = handLWorld.m[3][0] - handWorld.m[3][0];
                                dir[1] = handLWorld.m[3][1] - handWorld.m[3][1];
                                dir[2] = handLWorld.m[3][2] - handWorld.m[3][2];
                                dl = std::sqrt(dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]);
                            }
                            if (dl < 0.02f) { dir[0] = std::sin(track.heading); dir[1] = 0.0f; dir[2] = std::cos(track.heading); dl = 1.0f; }
                            dir[0] /= dl; dir[1] /= dl; dir[2] /= dl;
                            if (!reloadPose) {
                                // The line in the right hand's frame (its rows are its axes, uniformly scaled).
                                for (int r = 0; r < 3; ++r) {
                                    const float rr = handWorld.m[r][0] * handWorld.m[r][0] + handWorld.m[r][1] * handWorld.m[r][1] + handWorld.m[r][2] * handWorld.m[r][2];
                                    track.gripLocal[r] = (dir[0] * handWorld.m[r][0] + dir[1] * handWorld.m[r][1] + dir[2] * handWorld.m[r][2]) / (std::max)(1e-8f, rr);
                                }
                                track.gripValid = true;
                            }
                            right[0] = dir[2]; right[1] = 0.0f; right[2] = -dir[0];
                            const float rl = (std::max)(1e-4f, std::sqrt(right[0] * right[0] + right[2] * right[2]));
                            right[0] /= rl; right[2] /= rl;
                            up[0] = dir[1] * right[2] - dir[2] * right[1];
                            up[1] = dir[2] * right[0] - dir[0] * right[2];
                            up[2] = dir[0] * right[1] - dir[1] * right[0];
                            for (int c = 0; c < 3; ++c) { place.m[0][c] = right[c] * k; place.m[1][c] = up[c] * k; place.m[2][c] = dir[c] * k; }
                            // The grip in the palm: a little below the hand joint, the
                            // launcher's tube up on the shoulder.
                            const float lift = track.weapon == kWpnRocket ? 0.02f : -0.012f;
                            for (int c = 0; c < 3; ++c) place.m[3][c] = handWorld.m[3][c] + up[c] * lift;
                            place.m[3][3] = 1.0f;
                            placed = true;
                        } else {
                            // How long a model unit is in the world at the hand.
                            const float sx = handWorld.m[0][0], sy = handWorld.m[0][1], sz = handWorld.m[0][2];
                            const float unit = (std::max)(1e-4f, std::sqrt(sx * sx + sy * sy + sz * sz));
                            const float kh = wi.length / (unit * (std::max)(0.01f, WeaponSpan(*weapon)));
                            // The weapon's barrel (+z) runs along the hand's fingers (+x), its
                            // top (+y) along the back of the hand (+z); the grip sits a little
                            // behind and below the hand so the muzzle leads.
                            gta2::Mat4 inHand;
                            inHand.m[0][1] = kh; inHand.m[1][2] = kh; inHand.m[2][0] = kh;
                            inHand.m[3][0] = 0.30f * weapon->Length() * kh;      // along the fingers
                            inHand.m[3][2] = -0.45f * weapon->Height() * kh;     // down from the back of the hand
                            inHand.m[3][3] = 1.0f;
                            place = mul(inHand, handWorld);
                            for (int c = 0; c < 3; ++c) { dir[c] = place.m[2][c]; right[c] = place.m[0][c]; up[c] = place.m[1][c]; }
                            auto norm = [](float* v) {
                                const float l = (std::max)(1e-5f, std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]));
                                v[0] /= l; v[1] /= l; v[2] /= l;
                            };
                            norm(dir); norm(right); norm(up);
                            placed = true;
                        }
                        if (placed) {
                            static int logged = 0;
                            if (logged < 24) {
                                ++logged;
                                Log("weapon in hand: %s action %d rows (%.3f %.3f %.3f) (%.3f %.3f %.3f) (%.3f %.3f %.3f) at %.2f,%.2f,%.2f hand %.2f,%.2f,%.2f figure %.2f,%.2f,%.2f len %.3f",
                                    wi.name, track.action, place.m[0][0], place.m[0][1], place.m[0][2], place.m[1][0], place.m[1][1], place.m[1][2],
                                    place.m[2][0], place.m[2][1], place.m[2][2], place.m[3][0], place.m[3][1], place.m[3][2],
                                    handWorld.m[3][0], handWorld.m[3][1], handWorld.m[3][2], gx, cy, gz, weapon->Length());
                            }
                            device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
                            device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
                            ModelDraw(device, *weapon, place, nullptr, 0.0f);
                            if ((track.action == 10 || track.action == 15) && haveL) {
                                // The second pistol, in the left hand: the mirror of the right's hold.
                                const gta2::Mat4 handLWorld = mul(handL, world);
                                const float sx = handLWorld.m[0][0], sy = handLWorld.m[0][1], sz = handLWorld.m[0][2];
                                const float unit = (std::max)(1e-4f, std::sqrt(sx * sx + sy * sy + sz * sz));
                                const float kh = wi.length / (unit * (std::max)(0.01f, WeaponSpan(*weapon)));
                                gta2::Mat4 inHand;
                                inHand.m[0][1] = -kh; inHand.m[1][2] = -kh; inHand.m[2][0] = kh;
                                inHand.m[3][0] = 0.30f * weapon->Length() * kh;
                                inHand.m[3][2] = 0.45f * weapon->Height() * kh;
                                inHand.m[3][3] = 1.0f;
                                ModelDraw(device, *weapon, mul(inHand, handLWorld), nullptr, 0.0f);
                            }
                            // The muzzle: the model's front, along its barrel.
                            const float ahead = weapon->boundsMax.z * k;
                            float muzzle[3];
                            for (int c = 0; c < 3; ++c) muzzle[c] = place.m[3][c] + dir[c] * ahead;
                            if (!wi.twoHanded) {   // the placement's own scale is in its rows
                                for (int c = 0; c < 3; ++c) muzzle[c] = place.m[3][c] + place.m[2][c] * weapon->boundsMax.z;
                            }
                            track.muzzleX = muzzle[0]; track.muzzleY = muzzle[1]; track.muzzleZ = muzzle[2];
                            if (reloadPose && track.weapon > 0 && track.weapon < kWpnCount) {
                                // QB-29: the reload's events as its clip passes them: the spent
                                // magazine drops from the grip, the fresh one rides in the left
                                // hand from the pouch to the gun, the clicks (the player's own).
                                const ReloadInfo& ri = kReloads[track.weapon];
                                const float t = track.actionTime, pt = track.reloadPrevT;
                                auto crossed = [&](float e) { return e >= 0.0f && pt < e && t >= e; };
                                const bool rocket = track.weapon == kWpnRocket;
                                // The magazine well: below the grip (a third of the way to the muzzle for a long gun).
                                float well[3];
                                for (int c = 0; c < 3; ++c) well[c] = place.m[3][c] + dir[c] * (wi.twoHanded ? 0.3f * wi.length : 0.0f) - up[c] * 0.015f;
                                if (crossed(ri.dropT)) {
                                    ShotSpawnMag(well[0], well[1], well[2], right[0] * 0.15f, -0.25f, right[2] * 0.15f, 2.5f, cy + 0.008f, false);
                                    if (ownPed) ReloadClick(0);
                                }
                                if (haveL && t >= ri.grabT && t < ri.insertT) {
                                    const gta2::Mat4 handLWorld = mul(handL, world);
                                    ShotSpawnMag(handLWorld.m[3][0], handLWorld.m[3][1], handLWorld.m[3][2], 0.0f, 0.0f, 0.0f, 0.045f, -1e9f, rocket);
                                }
                                if (crossed(ri.insertT) && ownPed) ReloadClick(1);
                                if (crossed(ri.rackT) && ownPed) ReloadClick(2);
                                static int logged = 0;
                                if ((crossed(ri.dropT) || crossed(ri.insertT)) && logged < 120) {
                                    ++logged;
                                    Log("reload: %p %s %s at t=%.2f, grip %.2f,%.2f,%.2f", reinterpret_cast<const void*>(sprite.object), wi.name,
                                        crossed(ri.dropT) ? "magazine out" : "magazine in", t, place.m[3][0], place.m[3][1], place.m[3][2]);
                                }
                                track.reloadPrevT = t;
                            }
                            if (track.action != 13 && track.muzzleFrame == g_carFrame && !(ownPed && g_hiddenObjects[0] == g_playerObject)) {
                                ShotFxMuzzle(track.weapon, muzzle, dir, right, up, false);
                            }
                        }
                    }
                }
                ModelSetTorsoTwist(0.0f);
                ModelSetOverlay(nullptr, 0.0f, 0.0f);
                ModelSetLayers(nullptr, nullptr, nullptr, nullptr, 0);
                ModelClearLimbTargets();
                if (g_logFigures) {
                    // GTA2DX9_LOG_FIGURES=1 (ACTIONS-3D-4): the player's figure and everyone within
                    // 1.5 blocks of him, every frame: where the game has him and where he is drawn,
                    // the state words, the clip and the locomotion weights, for the slide checks.
                    const float pdx = cx - g_playerPosX, pdz = cz - g_playerPosZ;
                    if (ownPed || (g_playerPosValid && pdx * pdx + pdz * pdz < 2.25f)) {
                        Log("fig: f=%u o=%04x own=%d game=%.3f,%.3f drawn=%.3f,%.3f v=%.2f st=%d sub=0x%x fr=%u act=%d t=%.2f aw=%.2f cyc=%.3f ww=%.2f rw=%.2f hd=%.2f leg=%.2f fwd=%.4f sw=%.2f tw=%.2f tr=%d trt=%.2f trw=%.2f lean=%.3f clip=%s",
                            g_carFrame, static_cast<unsigned>((sprite.object >> 2) & 0xFFFF), ownPed ? 1 : 0, cx, cz, gx, gz, track.drawnSpeed,
                            sprite.pedState, sprite.pedSub, sprite.pedFrame % 158u, track.action, track.actionTime, actW, track.cycle,
                            walkW, runW, track.heading, track.legSpeed, track.stepFwd, sprintW, turnW, track.trans, transT, transW, track.lean,
                            actionClip ? actionClip->name.c_str() : "-");
                    }
                }
                if (tinted || model->splitPaint) {
                    device->SetRenderState(D3DRS_ALPHATESTENABLE, alphaTest);
                    device->SetTextureStageState(0, D3DTSS_ALPHAOP, alphaOp);
                    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, alphaArg1);
                }
                device->SetFVF(kFigFvf);
                device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
                device->SetTexture(0, nullptr);
                ++drawn;
                continue;
            }
        }
        if (sprite.corpse || sprite.climbing) continue;   // the box figure has no clips for those
        DWORD skin, hair, shirt, trousers;
        FigureColours(sprite.object, &skin, &hair, &shirt, &trousers);
        const float pace = (std::min)(track.speed / 3.0f, 1.0f);
        const float swing = 0.55f * pace * std::sin(track.phase);
        const float bob = 0.012f * pace * std::fabs(std::sin(track.phase));

        verts.clear();
        // Legs: hang from the hips at 0.42, 0.40 long.
        AddBox(&verts, -0.055f, 0.42f + bob, 0.0f, 0.085f, 0.40f, 0.095f, 0.0f, swing, trousers);
        AddBox(&verts, 0.055f, 0.42f + bob, 0.0f, 0.085f, 0.40f, 0.095f, 0.0f, -swing, trousers);
        // Body: shoulders at 0.72.
        AddBox(&verts, 0.0f, 0.72f + bob, 0.0f, 0.25f, 0.31f, 0.13f, 0.0f, 0.0f, shirt);
        // Arms: from the shoulders, opposite to the legs.
        AddBox(&verts, -0.155f, 0.71f + bob, 0.0f, 0.065f, 0.30f, 0.075f, 0.0f, -swing * 0.8f, shirt);
        AddBox(&verts, 0.155f, 0.71f + bob, 0.0f, 0.065f, 0.30f, 0.075f, 0.0f, swing * 0.8f, shirt);
        // Head, with hair on top.
        AddBox(&verts, 0.0f, 0.855f + bob, 0.0f, 0.13f, 0.135f, 0.13f, 0.0f, 0.0f, skin);
        AddBox(&verts, 0.0f, 0.875f + bob, -0.005f, 0.14f, 0.05f, 0.14f, 0.0f, 0.0f, hair);

        // Stood where the sprite lay, turned to face his way. Rows are the object
        // axes: right, up, forward.
        D3DMATRIX world;
        memset(&world, 0, sizeof(world));
        world._11 = fz;  world._12 = 0.0f; world._13 = -fx;
        world._21 = 0.0f; world._22 = 1.0f; world._23 = 0.0f;
        world._31 = fx;  world._32 = 0.0f; world._33 = fz;
        world._41 = gx;  world._42 = cy - 0.01f; world._43 = gz; world._44 = 1.0f;
        device->SetTransform(D3DTS_WORLD, &world);
        device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(verts.size() / 3), verts.data(),
                                sizeof(FigVertex));
        ++drawn;
    }
    if (sprites_.size() > boardRealSprites) sprites_.resize(boardRealSprites);   // the boarding ghosts
    BoardingEndFrame(g_carFrame);
    // Ranks by distance for the next frame's level of detail: the nearest
    // eight people seen this frame are posed in full.
    {
        std::vector<std::pair<float, PedTrack*>> seen;
        for (auto& entry : pedTracks_) if (entry.second.frame == g_carFrame) seen.push_back({entry.second.eyeD2, &entry.second});
        std::sort(seen.begin(), seen.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
        for (size_t i = 0; i < seen.size(); ++i) seen[i].second->rank = static_cast<int>(i);
    }
    RagdollEndFrame(g_carFrame);   // QB-27
    // Tracks of pedestrians gone for a while are dropped.
    if (pedTracks_.size() > 512) {
        for (auto it = pedTracks_.begin(); it != pedTracks_.end();) {
            it = (g_carFrame - it->second.frame > 300) ? pedTracks_.erase(it) : std::next(it);
        }
    }

    device->SetFVF(kWorldFvf);
    device->SetTextureStageState(0, D3DTSS_COLOROP, colorOp);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, colorArg1);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, alphaOp);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, alphaArg1);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, alphaTest);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, alphaBlend);
    (void)drawn;
}

// Probes for the action checks, off by default (environment, read once):
//   GTA2DX9_FORCE_WANTED=N    keeps the player's wanted level at least N stars
//                             (his cop points, ped+0x20A; same as [devtools]
//                             force_wanted), so a script gets the police on the
//                             player (police fire, arrests) without a massacre first;
//   GTA2DX9_LOG_VEHICLES=1    every two seconds, each live vehicle of the special
//                             models (bus, fire truck, ambulance, tank, trains,
//                             cop cars) with its position, heading and driver, so
//                             a script can warp to a train or the tank.
namespace {
void ActionProbes() {
    // GTA2DX9_PED_REMAP_FILE=<file>: the remap number in the file (re-read every 15
    // frames; -1 off) is drawn for every pedestrian ([devtools] ped_remap_override,
    // switchable while the game runs): one 3D figure type after another for a sheet.
    {
        static int checked = 0, current = -100;
        static char path[MAX_PATH] = {};
        static uint32_t lastRead = 0;
        if (!checked) { checked = 1; if (!GetEnvironmentVariableA("GTA2DX9_PED_REMAP_FILE", path, sizeof path)) path[0] = 0; }
        if (path[0] && (g_carFrame - lastRead >= 15 || lastRead == 0)) {
            lastRead = g_carFrame;
            int r = -1;
            if (FILE* f = fopen(path, "r")) { if (fscanf(f, "%d", &r) < 1) r = -1; fclose(f); }
            if (r != current) { current = r; PedRemapOverride(r); Log("devtools: pedestrians drawn as remap %d (GTA2DX9_PED_REMAP_FILE)", r); }
        }
    }
    static int forceWanted = -2, logVehicles = -1;
    if (forceWanted == -2) {
        char buf[16] = {};
        forceWanted = GetEnvironmentVariableA("GTA2DX9_FORCE_WANTED", buf, sizeof buf) ? atoi(buf) : -1;
        logVehicles = GetEnvironmentVariableA("GTA2DX9_LOG_VEHICLES", buf, sizeof buf) && buf[0] == '1' ? 1 : 0;
        if (forceWanted >= 0) Log("devtools: wanted held at least %d stars (GTA2DX9_FORCE_WANTED, ped+0x20A)", forceWanted);
    }
    // GTA2DX9_POKE="police:0x4D4=0x300,player:0x64=3": words held at a value every
    // frame in the police manager or the player object, for finding which of the
    // words that change with the wanted level drives the police (a probe).
    static int pokes = -1;
    static struct { int region; uint32_t offset; int32_t value; } poke[8];
    if (pokes < 0) {
        pokes = 0;
        char buf[256] = {};
        if (GetEnvironmentVariableA("GTA2DX9_POKE", buf, sizeof buf)) {
            for (char* tok = strtok(buf, ","); tok && pokes < 8; tok = strtok(nullptr, ",")) {
                char region[16] = {}; unsigned off = 0; int val = 0;
                if (sscanf(tok, "%15[a-z]:%x=%i", region, &off, &val) == 3) {
                    poke[pokes].region = strcmp(region, "player") == 0 ? 1 : 0;
                    poke[pokes].offset = off; poke[pokes].value = val;
                    Log("devtools: poke %s+0x%X = %d", poke[pokes].region ? "player" : "police", off, val);
                    ++pokes;
                }
            }
        }
    }
    if (pokes > 0 && g_carFrame > 300) {
        GTA2_TRY {
            const uintptr_t bases[2] = {*reinterpret_cast<const uintptr_t*>(0x0066B7A0), *reinterpret_cast<const uintptr_t*>(0x005EB4FC)};
            for (int i = 0; i < pokes; ++i) {
                const uintptr_t b = bases[poke[i].region];
                if (b > 0x10000 && poke[i].offset < 0x800) *reinterpret_cast<int32_t*>(b + poke[i].offset) = poke[i].value;
            }
        } GTA2_EXCEPT {
        }
    }
    // The wanted level for QA: [devtools] force_wanted=N (0..6 stars, -1 off,
    // re-read once a second; GTA2DX9_FORCE_WANTED=N does the same from the
    // environment) keeps the player's cop points (ped+0x20A, game::kPedCopPoints)
    // at least at N stars' threshold. That is the field the game itself raises
    // for a crime, so the police manager picks him up as it would after one:
    // cars dispatched, officers on foot, gunfire from 2-3 stars, an arrest at 1.
    // His ped comes from his sprite object (owner +0x08 = physics, +0x7C = ped);
    // the last one found is kept while he is in a car.
    static int iniWanted = -1;
    if (CarBodiesDevIni()[0] && (g_carFrame % 30u) == 0) {
        const int v = GetPrivateProfileIntA("devtools", "force_wanted", -1, CarBodiesDevIni());
        if (v != iniWanted) Log("devtools: force_wanted %d", v);
        iniWanted = v;
    }
    const int wantStars = (std::max)(forceWanted, iniWanted);
    static const uint8_t* wantedPed = nullptr;
    static int lastStars = -1;
    if (g_carFrame > 60 && (g_carFrame % 2u) == 0) {
        GTA2_TRY {
            // On foot his own sprite object; at the wheel his car's when first person hides
            // it (the second hidden object); otherwise the ped last seen on foot is kept.
            const void* own = g_playerObject ? g_playerObject : g_hiddenObjects[1];
            if (const void* located = LocatedPlayerPed()) {
                // The camera's locator has him in every view (and at the wheel).
                if (game::PlausiblePointer(located)) wantedPed = static_cast<const uint8_t*>(located);
            } else if (own) {
                const uint8_t* obj = static_cast<const uint8_t*>(own);
                const int32_t objBase = *reinterpret_cast<const int32_t*>(obj + game::kSpriteObjectBase);
                if (objBase == game::kSpriteBasePed) {
                    const uint8_t* phys = *reinterpret_cast<const uint8_t* const*>(obj + game::kSpriteObjectOwner);
                    if (game::PlausiblePointer(phys)) {
                        const uint8_t* ped = *reinterpret_cast<const uint8_t* const*>(phys + game::kPhysicsPed);
                        if (game::PlausiblePointer(ped) &&
                            *reinterpret_cast<const uint8_t* const*>(ped + game::kPedPhysics) == phys) wantedPed = ped;
                    }
                } else if (objBase == game::kSpriteBaseCar) {
                    // At the wheel: the car's driver (vehicle +0x54) is he.
                    const uint8_t* car = *reinterpret_cast<const uint8_t* const*>(obj + game::kSpriteObjectOwner);
                    if (game::PlausiblePointer(car)) {
                        const uint8_t* ped = *reinterpret_cast<const uint8_t* const*>(car + game::kVehicleDriver);
                        if (game::PlausiblePointer(ped)) wantedPed = ped;
                    }
                }
            }
            // The bust (see g_bustFrame): his cop points cleared while he lives,
            // knocked down - on the same ped, or on the new player ped the game
            // puts in his place, lying in state 8 sub 0x16.
            // Two signals, whichever comes first: he is punched down (state 8 sub 0x16)
            // while wanted - an officer's knock-down is the arrest, and the game clears
            // the points either at once or as it moves him, 2.5 s later (runs pol_arrest3,
            // pol_arrest4) - or the points are cleared while he lives.
            static const uint8_t* lastPed = nullptr;
            static int16_t lastPoints = 0;
            static bool lastDown = false;
            if (wantedPed) {
                const int16_t now = *reinterpret_cast<const int16_t*>(wantedPed + game::kPedCopPoints);
                const int32_t st = *reinterpret_cast<const int32_t*>(wantedPed + game::kPedState);
                const int32_t sub = *reinterpret_cast<const int32_t*>(wantedPed + game::kPedSubState);
                const uint16_t health = *reinterpret_cast<const uint16_t*>(wantedPed + 0x216);
                const bool down = st == game::kPedStateInterrupted && sub == 0x16;
                const bool recent = g_bustFrame && g_carFrame - g_bustFrame < 300;
                if (down && !lastDown && (now >= game::kCopPointsForStars[1] || lastPoints >= game::kCopPointsForStars[1]) && !recent) {
                    g_bustFrame = g_carFrame;
                    Log("wanted: busted: punched down while wanted (cop points %d, health %u)", (std::max)(now, lastPoints), health);
                } else if (lastPoints >= game::kCopPointsForStars[1] && now == 0 && health > 0 && st != game::kPedStateDead &&
                           (wantedPed == lastPed || down)) {
                    if (!recent) g_bustFrame = g_carFrame;
                    Log("wanted: busted: cop points %d -> 0, health %u, state %d sub 0x%x%s%s", lastPoints, health, st, sub,
                        wantedPed == lastPed ? "" : ", a new player ped", recent ? " (the arrest already under way)" : "");
                }
                lastPed = wantedPed; lastPoints = now; lastDown = down;
            }
            if (wantedPed) {
                int16_t* points = reinterpret_cast<int16_t*>(const_cast<uint8_t*>(wantedPed) + game::kPedCopPoints);
                // Not straight after a bust: the game has just cleared them.
                if (wantStars > 0 && wantStars <= 6 && *points < game::kCopPointsForStars[wantStars] && g_carFrame - g_bustFrame > 300) {
                    *points = game::kCopPointsForStars[wantStars];
                    lastPoints = *points;
                }
                const int stars = game::PedWantedStars(wantedPed);
                if (stars != lastStars) {
                    const uintptr_t police = *reinterpret_cast<const uintptr_t*>(game::kPoliceManagerPtr);
                    Log("wanted: player cop points %d = %d stars (police response %d)", *points, stars,
                        police > 0x10000 ? *reinterpret_cast<const int32_t*>(police + game::kPoliceResponseLevel) : -1);
                    lastStars = stars;
                }
            }
        } GTA2_EXCEPT {
            wantedPed = nullptr;
        }
    }
    // GTA2DX9_LOG_POLICE=1: the police manager's words that changed, twice a
    // second, beside the wanted level at +0x654, to find what the level is made from.
    static int logPolice = -1;
    if (logPolice < 0) { char buf[8] = {}; logPolice = GetEnvironmentVariableA("GTA2DX9_LOG_POLICE", buf, sizeof buf) && buf[0] == '1' ? 1 : 0; }
    if (logPolice == 1 && (g_carFrame % 15u) == 0) {
        // Two regions: the police manager [0x66B7A0] and the player object [0x5EB4FC].
        static uint32_t prev[2][0x800 / 4] = {};
        static bool have[2] = {};
        static int lines = 0;
        GTA2_TRY {
            const uintptr_t police = *reinterpret_cast<const uintptr_t*>(0x0066B7A0);
            const uintptr_t player = *reinterpret_cast<const uintptr_t*>(0x005EB4FC);
            const uintptr_t bases[2] = {police, player};
            for (int r = 0; r < 2 && lines < 600; ++r) {
                if (bases[r] <= 0x10000) continue;
                const uint32_t* w = reinterpret_cast<const uint32_t*>(bases[r]);
                std::string line;
                int changed = 0;
                for (int i = 0; i < 0x800 / 4; ++i) {
                    if (have[r] && w[i] != prev[r][i] && changed < 40) {
                        char buf[40]; snprintf(buf, sizeof buf, " +%03X:%X>%X", i * 4, prev[r][i], w[i]); line += buf; ++changed;
                    }
                    prev[r][i] = w[i];
                }
                have[r] = true;
                if (changed) {
                    ++lines;
                    Log("%s words: wanted %d%s", r ? "player" : "police", police > 0x10000 ? *reinterpret_cast<const int32_t*>(police + 0x654) : -1, line.c_str());
                }
            }
        } GTA2_EXCEPT {
        }
    }
    if (logVehicles == 1 && (g_carFrame % 60u) == 0) {
        GTA2_TRY {
            std::string line;
            int guard = 0;
            for (const uint8_t* v = game::VehicleListHead(); v && guard < 1024; v = game::NextInList(v, game::kVehicleNext), ++guard) {
                const int32_t model = *reinterpret_cast<const int32_t*>(v + game::kVehicleModel);
                if (!(model == 11 || model == 12 || model == 17 || model == 34 || model == 52 || model == 54 ||
                      (model >= 59 && model <= 61) || model == 86)) continue;
                float x = 0, y = 0, z = 0, fx = 0, fy = 0;
                if (!game::ReadPlacement(v, game::kVehiclePlacementPtr, &x, &y, &z)) continue;
                game::ReadFacing(v, game::kVehiclePlacementPtr, &fx, &fy);
                char buf[96];
                snprintf(buf, sizeof buf, " [m%d %.2f,%.2f,%.2f f%.2f,%.2f d%d %p]", model, x, y, z, fx, fy,
                         game::VehicleHasDriver(v) ? 1 : 0, static_cast<const void*>(v));
                line += buf;
                // The tank's turret and the fire truck's water cannon: which of the
                // vehicle's words points at a placement block standing on the vehicle
                // (a sprite object of its own), with that block's heading against the
                // hull's - to find the field the turret's aim is read from.
                if ((model == 54 || model == 17) && game::VehicleHasDriver(v)) {
                    const uint16_t hullHeading = *reinterpret_cast<const uint16_t*>(game::Placement(v, game::kVehiclePlacementPtr) + game::kPlaceHeading);
                    for (uint32_t off = 0; off < 0x200; off += 4) {
                        const uint8_t* p = *reinterpret_cast<const uint8_t* const*>(v + off);
                        if (!game::PlausiblePointer(p) || off == game::kVehiclePlacementPtr) continue;
                        const float px = *reinterpret_cast<const int32_t*>(p + game::kPlaceX) * game::kFixedScale;
                        const float py = *reinterpret_cast<const int32_t*>(p + game::kPlaceY) * game::kFixedScale;
                        if (std::fabs(px - x) > 1.5f || std::fabs(py - y) > 1.5f) continue;
                        snprintf(buf, sizeof buf, " (+%03X: %.2f,%.2f h%u hull %u base %d)", off, px, py,
                                 *reinterpret_cast<const uint16_t*>(p + game::kPlaceHeading), hullHeading,
                                 *reinterpret_cast<const int32_t*>(p + game::kSpriteObjectBase));
                        line += buf;
                    }
                }
                if (line.size() > 1600) break;
            }
            Log("vehicles:%s", line.empty() ? " none of the special models" : line.c_str());
        } GTA2_EXCEPT {
        }
    }
}
}

void LiveGeometry::Draw(IDirect3DDevice9* device, const gta2::Camera& camera, int width,
                        int height) {
    if (!device) return;
    DrawStageTimer stageTimer;
    ModelsBeginFrame();
    g_viewEye = camera.Position();
    {
        const float cp = std::cos(camera.Pitch());
        g_viewForward = {std::sin(camera.Yaw()) * cp, std::sin(camera.Pitch()), std::cos(camera.Yaw()) * cp};
    }
    SetViewFrustum(camera, width, height);
    g_viewActiveForPops = CurrentViewMode() != ViewMode::Classic;
    ++g_carFrame;
    g_carMaterialsThisFrame = 0;
    lastEye_ = camera.Position();
    ActionProbes();

    // The texture table filled up (see kMaxFrames): empty it before anything of this frame
    // holds a texture, and forget what was keyed on the old textures' addresses - a new
    // texture can be made at an old one's address. The materials themselves stay, found
    // again from what they are made of, so the cars do not have to be made anew.
    if (TextureCacheTakeFlushRequest()) {
        ReleaseDeviceTextures();
        CarBodiesReleaseDevice();   // keyed on those textures' addresses
        g_carMaterials.clear();
        g_warmArt.clear();
        Log("texture cache: emptied (it was full), the cars' artwork is built again");
    }

    // A pedestrian over a car - the player jumping on or over one - stands above
    // it. The game gives him a height of his own, but the car's roof is now the
    // dome, which stands up to CarBodyHeight above the car's own level, and a
    // pedestrian placed against the sprite's old flat plane ended up under it:
    // the car was drawn over him and he seemed to walk beneath. So any pedestrian
    // on his feet whose middle is over a car's body is raised to just clear that
    // car's top. A pedestrian knocked down or run over is not on his feet and is
    // left where he lies, under the wheels.
    struct Roof { const CarShell* shell; float midX, midZ, halfX, halfZ, apexY; };
    std::vector<Roof> roofs;
    g_fireSpotsLast.clear();
    if (!shells_.empty()) {
        roofs.reserve(shells_.size());
        for (const CarShell& shell : shells_) {
            float lo[2] = {1e9f, 1e9f}, hi[2] = {-1e9f, -1e9f};
            for (int i = 0; i < kDomeVertices; ++i) {
                lo[0] = (std::min)(lo[0], shell.local[i].x); hi[0] = (std::max)(hi[0], shell.local[i].x);
                lo[1] = (std::min)(lo[1], shell.local[i].z); hi[1] = (std::max)(hi[1], shell.local[i].z);
            }
            const Vertex& apex = shell.local[(kDomeSegments / 2) * (kDomeSegments + 1) + kDomeSegments / 2];
            const float (*m)[4] = shell.objectToWorld.m;
            const float apexY = apex.x * m[0][1] + apex.y * m[1][1] + apex.z * m[2][1] + m[3][1];
            roofs.push_back({&shell, (lo[0] + hi[0]) * 0.5f, (lo[1] + hi[1]) * 0.5f,
                             (hi[0] - lo[0]) * 0.5f * 0.8f, (hi[1] - lo[1]) * 0.5f * 0.8f, apexY});
        }
        // Where the last boarding pedestrian was lifted to, so that the lift is let down over a few
        // frames when he steps clear instead of dropping in one: a body whose height jumps between
        // two frames has no motion the denoiser and frame generation can follow, and smears.
        struct LiftMemo { float x, z, lift; uint32_t frame; };
        static LiftMemo memo = {0.0f, 0.0f, 0.0f, 0};
        struct UiHold { float x, z; uint32_t frame; bool valid; };
        static UiHold uiHold = {0.0f, 0.0f, 0, false};
        for (Sprite& sprite : sprites_) {
            if (!sprite.pedestrian || sprite.corners != 4) continue;
            // Climbing into or out of a car he is drawn over it, as the game itself draws him. He is
            // lifted clear of the car's top whenever he is at the car at all - not only over its roof:
            // beside the door he stands under the dome's glass and the open door, and seen through
            // them he is a translucent, smeared ghost. Over everything he is whole and opaque.
            const bool boarding = sprite.climbing || sprite.inVehicleNow;
            const float liftReach = 1.0f;
            float cx = 0, cy = 0, cz = 0;
            for (int i = 0; i < 4; ++i) { cx += sprite.local[i].x * 0.25f; cy += sprite.local[i].y * 0.25f; cz += sprite.local[i].z * 0.25f; }
            float (*pm)[4] = sprite.objectToWorld.m;
            const float world[3] = {cx * pm[0][0] + cy * pm[1][0] + cz * pm[2][0] + pm[3][0],
                                    cx * pm[0][1] + cy * pm[1][1] + cz * pm[2][1] + pm[3][1],
                                    cx * pm[0][2] + cy * pm[1][2] + cz * pm[2][2] + pm[3][2]};
            const Roof* hit = nullptr;
            float best = 1e9f;
            for (const Roof& roof : roofs) {
                const float (*m)[4] = roof.shell->objectToWorld.m;
                const float d[3] = {world[0] - m[3][0], world[1] - m[3][1], world[2] - m[3][2]};
                float local[3];
                for (int j = 0; j < 3; ++j) local[j] = d[0] * m[j][0] + d[1] * m[j][1] + d[2] * m[j][2];
                if (boarding) {
                    // Distance outside the car's real footprint (the roof's is shrunk to 0.8); the
                    // nearest car within a block and a bit is the one he is getting into or out of.
                    const float ox = std::fabs(local[0] - roof.midX) - roof.halfX / 0.8f;
                    const float oz = std::fabs(local[2] - roof.midZ) - roof.halfZ / 0.8f;
                    const float out = (std::max)(ox, oz);
                    if (out < 1.1f && out < best) { best = out; hit = &roof; }
                } else {
                    if (std::fabs(local[0] - roof.midX) > roof.halfX * liftReach ||
                        std::fabs(local[2] - roof.midZ) > roof.halfZ * liftReach) continue;
                    hit = &roof;
                    break;
                }
            }
            // Which pedestrian goes through the screen-space layer: one climbing, and for a few frames
            // after, so that he does not change from one kind of drawing to the other in mid-step.
            if (g_boardingUi && !g_ghostSwitch[kGhostNoBoardUi]) {
                if (sprite.climbing) {
                    uiHold = {world[0], world[2], g_carFrame, true};
                    sprite.boardUi = true;
                } else if (uiHold.valid && g_carFrame - uiHold.frame < 8) {
                    const float dx = world[0] - uiHold.x, dz = world[2] - uiHold.z;
                    if (dx * dx + dz * dz < 0.9f * 0.9f) sprite.boardUi = true;
                }
            }
            // Getting in or out he is held low, at the height of the door, and the car's own body
            // masks him: whatever of him is under its dome is hidden, so he steps in over the door
            // and goes under the roof, and comes out of it the same way, instead of floating over
            // the roof and vanishing. How low is BoardingHeight, `boarding_height_percent` and F4.
            if (boarding) {
                if (hit && g_boardingHeight > 0.0f) {
                    const float baseY = hit->shell->objectToWorld.m[3][1];
                    const float target = baseY + g_boardingHeight * (hit->apexY - baseY);
                    if (target > world[1]) pm[3][1] += target - world[1];
                }
                continue;
            }
            float lift = 0.0f;
            if (hit) {
                const float need = hit->apexY + 0.04f - world[1];
                if (need > 0.0f) {
                    lift = need;
                    ++g_pedsOverCars;
                }
                if (boarding && lift > 0.0f) memo = {world[0], world[2], lift, g_carFrame};
            } else if (memo.lift > 0.0f && g_carFrame - memo.frame < 10) {
                const float dx = world[0] - memo.x, dz = world[2] - memo.z;
                if (dx * dx + dz * dz < 0.8f * 0.8f) {
                    lift = memo.lift * (1.0f - static_cast<float>(g_carFrame - memo.frame) / 10.0f);
                }
            }
            if (lift > 0.0f && !g_ghostSwitch[kGhostNoLift]) pm[3][1] += lift;
        }
        // (Getting into or out of a car he is no longer hidden: he is drawn over the car, lifted
        // clear of the roof, as the game draws him. See the lift above.)
        // A body on the road under a car. The dome stands over it, but the glass is clear and
        // the dome's low edge lets it show: the dead pedestrian, animated, laid over the roof.
        // While any part of the car is over his middle he is not drawn; he is back as soon as
        // the car has driven off him.
        for (Sprite& sprite : sprites_) {
            if (!sprite.corpse || sprite.corners != 4 || sprite.ghost) continue;
            float cx = 0, cy = 0, cz = 0;
            for (int i = 0; i < 4; ++i) { cx += sprite.local[i].x * 0.25f; cy += sprite.local[i].y * 0.25f; cz += sprite.local[i].z * 0.25f; }
            const float (*pm)[4] = sprite.objectToWorld.m;
            const float world[3] = {cx * pm[0][0] + cy * pm[1][0] + cz * pm[2][0] + pm[3][0],
                                    cx * pm[0][1] + cy * pm[1][1] + cz * pm[2][1] + pm[3][1],
                                    cx * pm[0][2] + cy * pm[1][2] + cz * pm[2][2] + pm[3][2]};
            for (const Roof& roof : roofs) {
                const float (*m)[4] = roof.shell->objectToWorld.m;
                const float d[3] = {world[0] - m[3][0], world[1] - m[3][1], world[2] - m[3][2]};
                float local[3];
                for (int j = 0; j < 3; ++j) local[j] = d[0] * m[j][0] + d[1] * m[j][1] + d[2] * m[j][2];
                if (std::fabs(local[0] - roof.midX) > roof.halfX * 1.25f ||
                    std::fabs(local[2] - roof.midZ) > roof.halfZ * 1.25f) continue;
                sprite.ghost = true;
                break;
            }
        }
    }
    if (g_carFrame % 600 == 0) {
        Log("car meshes cached: %zu, lamp materials: %zu, pedestrians lifted over cars: %u", g_carMeshes.size(), g_lampMaterials.size(), g_pedsOverCars);
    }
    if (sprites_.empty()) return;

    D3DMATRIX matrix;
    // No world matrix here: each sprite sets its own, which is the whole point.
    // See the note in live_geometry.h.
    const gta2::Mat4 view = camera.ViewMatrix();
    memcpy(&matrix, view.m, sizeof(matrix));
    device->SetTransform(D3DTS_VIEW, &matrix);
    const gta2::Mat4 projection =
        camera.ProjectionMatrix(static_cast<float>(width) / static_cast<float>(height));
    memcpy(&matrix, projection.m, sizeof(matrix));
    device->SetTransform(D3DTS_PROJECTION, &matrix);

    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_ZENABLE, D3DZB_TRUE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    // Sprites are flat quads and the odd block faces come in either winding, so
    // culling is off rather than guessed at.
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    const bool blending = gta2::GetAlphaMode() == gta2::AlphaMode::Blend;
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, blending ? TRUE : FALSE);
    // An alpha test rather than blending: it keeps the geometry opaque to the
    // path tracer, which behaves far better than a blended surface under Remix.
    // Sprites were hardcoded to alpha test, which is why the mode switch appeared
    // to do nothing to them: it only ever reached the static world mesh. An
    // explosion is exactly the case that wants blending - it is a soft glow, not
    // a cutout like a fence or a tree.
    device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHAFUNC, D3DCMP_GREATEREQUAL);
    // In blend mode the test drops to 1, which still discards the fully
    // transparent texels so they do not write depth over what is behind them.
    device->SetRenderState(D3DRS_ALPHAREF, blending ? 1u
                                                    : static_cast<DWORD>(gta2::GetAlphaRef()));
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);

    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
    device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);

    device->SetFVF(kWorldFvf);

    // Effect artwork - fire, explosions, muzzle flashes - is drawn in a second
    // pass, so the texture has to be resolved before the pass is chosen. See
    // texture_store.h for what makes a sprite an effect and why it matters.
    struct Drawable {
        const Sprite* sprite;
        IDirect3DTexture9* texture;
        bool enlarged = false;  // a smoothed copy: sampled bilinearly
        uint32_t color = 0;     // 0: as the artwork is; else a colour it is multiplied by
        bool blood = false;     // ground decal that may be red: drawn with the blood material
    };
    // Which domes are ready to stand in for their car's flat body: the artwork
    // resolved and its material made some frames ago. See kCarMaterialWarmup.
    std::vector<IDirect3DTexture9*> shellArt(shells_.size(), nullptr);    // the car's own
    std::vector<IDirect3DTexture9*> shellMatArt(shells_.size(), nullptr);  // what is drawn
    std::vector<char> shellWarm(shells_.size(), 0);
    PumpCarJobs();
    PumpDoorJobs();
    if (g_carMaterial) {
        for (size_t i = 0; i < shells_.size(); ++i) {
            bool unusedEffect = false;
            LARGE_INTEGER t0, t1, t2;
            QueryPerformanceCounter(&t0);
            shellArt[i] = DeviceTextureFor(device, shells_[i].texture, &unusedEffect, true);
            QueryPerformanceCounter(&t1);
            if (!shellArt[i]) continue;
            const bool materialReady = CarMaterialFor(shellArt[i], shells_[i].sprite) != nullptr;
            QueryPerformanceCounter(&t2);
            {
                // A car that cost real time to set up, and which part of it did.
                static LARGE_INTEGER freq = {};
                static int logged = 0;
                if (!freq.QuadPart) QueryPerformanceFrequency(&freq);
                const double texMs = 1000.0 * static_cast<double>(t1.QuadPart - t0.QuadPart) / static_cast<double>(freq.QuadPart);
                const double matMs = 1000.0 * static_cast<double>(t2.QuadPart - t1.QuadPart) / static_cast<double>(freq.QuadPart);
                if ((texMs > 4.0 || matMs > 4.0) && logged++ < 300) {
                    Log("car setup slow: sprite %d artwork %.1f ms, material %.1f ms", shells_[i].sprite, texMs, matMs);
                }
            }
            if (materialReady && CarMaterialWarm(shellArt[i], shells_[i].sprite)) {
                shellWarm[i] = 1;
                shellMatArt[i] = shellArt[i];
                g_warmArt[shells_[i].object] = {shellArt[i], shells_[i].sprite, g_carFrame};
                continue;
            }
            // Not ready: the car's last loaded artwork stands in, if it has one
            // and it is still the same car.
            const auto last = g_warmArt.find(shells_[i].object);
            if (last != g_warmArt.end() && last->second.sprite == shells_[i].sprite &&
                CarMaterialWarm(last->second.art, last->second.sprite)) {
                shellWarm[i] = 1;
                shellMatArt[i] = last->second.art;
                last->second.seen = g_carFrame;
            }
        }
        // Forget cars not seen for a while, so a long drive does not keep every
        // car it ever met.
        if (g_warmArt.size() > 256) {
            for (auto it = g_warmArt.begin(); it != g_warmArt.end();) {
                it = (g_carFrame - it->second.seen > 600) ? g_warmArt.erase(it) : std::next(it);
            }
        }
    }
    stageTimer.Mark();   // 0: setup
    std::vector<Drawable> plain, effects, skids, boarders;
    plain.reserve(sprites_.size());
    g_fxSpotsLast.swap(g_fxSpotsNow);
    g_fxSpotsNow.clear();
    g_fxFreshLast.swap(g_fxFreshNow);
    g_fxFreshNow.clear();
    ShotFxBulletEnds();
    g_pedSpots.clear();
    // Burning cars: effect sprites over a car are lifted clear of its roof, and the
    // small ones enlarged and layered. These are the altered copies the Drawables point to.
    std::deque<Sprite> fxSprites;
    struct FireSpot { float x, y, z, size; const void* car; };
    std::vector<FireSpot> fireSpots;
    struct FireSpotsKeeper {       // publishes this frame's flame positions when the pass ends
        std::vector<FireSpot>& spots;
        ~FireSpotsKeeper() {
            for (const FireSpot& f : spots) g_fireSpotsLast.push_back({f.x, f.y, f.z, f.car});
        }
    } fireSpotsKeeper{fireSpots};
    const double fxTime = SkidNowSeconds();
    // Flicker diagnostic: follows each pedestrian from frame to frame and logs, a few times only,
    // one that changes how it is drawn again and again (the flags below, smoothed or not) or that
    // drops out of the draw list for a few frames and comes back. The log line says which, and
    // carries everything known about the sprite at that moment.
    struct PedWatch {
        uint32_t bits = 0, last = 0;
        uint32_t flipWindow = 0, gapWindow = 0, smoothWindow = 0;
        int flips = 0, gaps = 0, smoothFlips = 0;
        int enlarged = -1;
    };
    static std::map<uintptr_t, PedWatch> pedWatch;
    static int pedWatchLogs = 0;
    auto watchPed = [&](const Sprite& s) {
        if (!s.object || (!s.pedestrian && !s.corpse)) return;
        const uint32_t f = g_carFrame;
        uint32_t bits = 0;
        const uint32_t flags[] = {s.ghost, s.hidden, s.climbing, s.recentlyInCar, s.inVehicleNow,
                                  s.boardUi, s.corpse, s.smooth, s.pedestrian,
                                  IsGroundDecal(s.texture), s.shell >= 0};
        for (size_t i = 0; i < sizeof(flags) / sizeof(flags[0]); ++i) bits |= (flags[i] ? 1u : 0u) << i;
        if (pedWatch.size() > 3000) {
            for (auto it = pedWatch.begin(); it != pedWatch.end();) {
                it = (f - it->second.last > 600) ? pedWatch.erase(it) : std::next(it);
            }
        }
        PedWatch& w = pedWatch[s.object];
        const TextureRecord* rec = static_cast<const TextureRecord*>(s.texture);
        if (w.last != 0 && w.last != f) {
            const uint32_t gap = f - w.last;
            if (gap >= 2 && gap <= 45) {
                if (f - w.gapWindow > 240) { w.gapWindow = f; w.gaps = 0; }
                if (++w.gaps == 3 && pedWatchLogs < 80) {
                    ++pedWatchLogs;
                    Log("ped flicker: object %p dropped out of the draw list %d times in 240 frames (last gap %u frames); "
                        "now bits %03x, texture %p %dx%d pal %d key %016llx",
                        reinterpret_cast<void*>(s.object), w.gaps, gap, bits, s.texture, rec ? rec->width : 0,
                        rec ? rec->height : 0, rec ? rec->palette : 0,
                        static_cast<unsigned long long>(SpriteIndexKey(s.texture)));
                }
            }
            if (bits != w.bits) {
                if (f - w.flipWindow > 60) { w.flipWindow = f; w.flips = 0; }
                if (++w.flips == 4 && pedWatchLogs < 80) {
                    ++pedWatchLogs;
                    Log("ped flicker: object %p changed state %d times in 60 frames: bits %03x -> %03x "
                        "(ghost,hidden,climbing,recentlyInCar,inVehicleNow,boardUi,corpse,smooth,pedestrian,decal,shell), "
                        "texture %p %dx%d pal %d key %016llx",
                        reinterpret_cast<void*>(s.object), w.flips, w.bits, bits, s.texture, rec ? rec->width : 0,
                        rec ? rec->height : 0, rec ? rec->palette : 0,
                        static_cast<unsigned long long>(SpriteIndexKey(s.texture)));
                }
            }
        }
        w.bits = bits;
        w.last = f;
    };
    auto watchPedSmooth = [&](const Sprite& s, bool enlargedNow) {
        if (!s.object || (!s.pedestrian && !s.corpse)) return;
        PedWatch& w = pedWatch[s.object];
        const uint32_t f = g_carFrame;
        if (w.enlarged >= 0 && w.enlarged != (enlargedNow ? 1 : 0)) {
            if (f - w.smoothWindow > 60) { w.smoothWindow = f; w.smoothFlips = 0; }
            if (++w.smoothFlips == 4 && pedWatchLogs < 80) {
                ++pedWatchLogs;
                const TextureRecord* rec = static_cast<const TextureRecord*>(s.texture);
                Log("ped flicker: object %p swapped between the smoothed and the raw sprite %d times in 60 frames, "
                    "texture %p %dx%d pal %d key %016llx",
                    reinterpret_cast<void*>(s.object), w.smoothFlips, s.texture, rec ? rec->width : 0,
                    rec ? rec->height : 0, rec ? rec->palette : 0,
                    static_cast<unsigned long long>(SpriteIndexKey(s.texture)));
            }
        }
        w.enlarged = enlargedNow ? 1 : 0;
    };
    for (const Sprite& sprite : sprites_) {
        watchPed(sprite);
        if (sprite.ghost) continue;
        if (g_ghostSwitch[kGhostHidePeds] && sprite.pedestrian) continue;
        if (sprite.hidden && !sprite.lamp && sprite.shell >= 0 &&
            sprite.shell < static_cast<int>(shellWarm.size()) && shellWarm[sprite.shell]) {
            continue;
        }
        if (sprite.hidden && sprite.shell < 0 && g_groundModels) continue;   // a model stands in for it
        if (sprite.lamp) {
            if (IDirect3DTexture9* lamp = LampTexture(device, sprite.lamp, sprite.lampMirrored)) {
                plain.push_back({&sprite, lamp});
            }
            continue;
        }
        bool effect = false;
        // A pedestrian is never an effect. The classifier reads the artwork - black fading out to
        // a cutout edge means fire - and a pedestrian climbing into a car is mostly a dark vest
        // seen from above, which it took for a flame: drawn as one, he was tinted fire-orange,
        // enlarged and stacked in layers rising off the car, which is the see-through orange
        // figure with a trail that haunted getting in and out of cars.
        IDirect3DTexture9* texture = DeviceTextureFor(device, sprite.texture, &effect,
                                                      !sprite.plain && !sprite.pedestrian && !sprite.corpse);
        if (!texture) {
            // The sprite was accepted and then had no artwork to draw with:
            // this is a sprite that vanishes for exactly one frame.
            ++drops_.noTexture;
            continue;
        }
        // Recorded so the texture report can tell a fireball from a road tile
        // that happens to have a hole in it. See texture_store.h.
        NoteSpriteTexture(sprite.texture);
        // A tank's turret and a fire truck's water cannon are sprites of their own,
        // laid over the hull at its flat level with a heading of their own: the aim.
        // Over a 3D model (POLICE-3D) the model's own turret is turned to that
        // heading (CarBodiesSetTurret) and the flat sprite, which would lie inside
        // the hull, is not drawn.
        if (g_groundModels && !carBodies_.empty() && !sprite.pedestrian && !sprite.corpse && sprite.corners == 4 && !effect) {
            float lfx = 0.0f, lfz = 0.0f, slen = 0.0f, swid = 0.0f;
            SpriteFrame(sprite.local, sprite.corners, &lfx, &lfz, &slen, &swid);
            const float (*sm)[4] = sprite.objectToWorld.m;
            float cx = 0, cy = 0, cz = 0;
            for (int i = 0; i < 4; ++i) { cx += sprite.local[i].x * 0.25f; cy += sprite.local[i].y * 0.25f; cz += sprite.local[i].z * 0.25f; }
            const float wx = cx * sm[0][0] + cy * sm[1][0] + cz * sm[2][0] + sm[3][0];
            const float wz = cx * sm[0][2] + cy * sm[1][2] + cz * sm[2][2] + sm[3][2];
            const float size = (std::max)(slen, swid);
            bool turret = false;
            if (size > 0.2f && size < 2.4f) {
                for (const CarBodyUse& use : carBodies_) {
                    if ((use.model != 54 && use.model != 17) || use.object == sprite.object) continue;
                    const float ddx = wx - use.objectToWorld.m[3][0], ddz = wz - use.objectToWorld.m[3][2];
                    if (ddx * ddx + ddz * ddz > 0.6f * 0.6f) continue;
                    // The turret artwork's top edge is the back of the turret (the barrel runs to
                    // the bottom of the sprite): every tank driving straight read exactly 180 deg
                    // off its hull (run pol_army2), so the barrel is the other way.
                    const float dirX = -(lfx * sm[0][0] + lfz * sm[2][0]), dirZ = -(lfx * sm[0][2] + lfz * sm[2][2]);
                    const float dl = std::sqrt(dirX * dirX + dirZ * dirZ);
                    if (dl < 1e-6f) continue;
                    CarBodiesSetTurret(use.object, dirX / dl, dirZ / dl, g_carFrame);
                    static std::set<uintptr_t> turretLogged;
                    if (turretLogged.size() < 24 && turretLogged.insert(use.object).second) {
                        Log("turret: model %d object %p: sprite %p %.2f x %.2f tiles, %.2f from the hull's middle, aim %.2f,%.2f",
                            use.model, reinterpret_cast<const void*>(use.object), sprite.texture, slen, swid,
                            std::sqrt(ddx * ddx + ddz * ddz), dirX / dl, dirZ / dl);
                    }
                    turret = true;
                    break;
                }
            }
            if (turret) continue;
        }
        if (effect && sprite.corners == 4 && !sprite.pedestrian && !sprite.corpse) {
            // Published for the player log line (fire=N): is his car burning?
            const float (*fm)[4] = sprite.objectToWorld.m;
            float cx = 0, cy = 0, cz = 0, ex = 0, ez = 0;
            for (int i = 0; i < 4; ++i) { cx += sprite.local[i].x * 0.25f; cy += sprite.local[i].y * 0.25f; cz += sprite.local[i].z * 0.25f; }
            for (int i = 0; i < 4; ++i) {
                ex = (std::max)(ex, std::fabs(sprite.local[i].x - cx)); ez = (std::max)(ez, std::fabs(sprite.local[i].z - cz));
            }
            const float wx = cx * fm[0][0] + cy * fm[1][0] + cz * fm[2][0] + fm[3][0];
            const float wy = cx * fm[0][1] + cy * fm[1][1] + cz * fm[2][1] + fm[3][1];
            const float wz = cx * fm[0][2] + cy * fm[1][2] + cz * fm[2][2] + fm[3][2];
            const float size = 2.0f * (std::max)(ex, ez);
            if (size <= g_fire.maxSize) g_fireSpotsLast.push_back({wx, wy, wz, sprite.object ? reinterpret_cast<const void*>(sprite.object) : nullptr});
        }
        // Rubber skid strips: drawn soft and translucent, and where one first appears
        // beside a car there is a tyre, so a puff of smoke.
        if ((g_skid.soft || g_skid.smoke) && sprite.corners == 4 && !effect &&
            IsGroundDecal(sprite.texture)) {
            bool rubber = false;
            IDirect3DTexture9* soft = SoftSkidTexture(device, texture, &rubber);
            if (rubber) {
                if (g_skid.smoke) {
                    const float wx = sprite.objectToWorld.m[3][0];
                    const float wy = sprite.objectToWorld.m[3][1];
                    const float wz = sprite.objectToWorld.m[3][2];
                    const int kx = static_cast<int>(std::floor(wx * 32.0f));
                    const int kz = static_cast<int>(std::floor(wz * 32.0f));
                    bool seenBefore = false;
                    for (int dx = -1; dx <= 1 && !seenBefore; ++dx) {
                        for (int dz = -1; dz <= 1; ++dz) {
                            const uint64_t key = (static_cast<uint64_t>(static_cast<uint32_t>(kx + dx)) << 32) |
                                                 static_cast<uint32_t>(kz + dz);
                            const auto it = g_skidSeen.find(key);
                            if (it != g_skidSeen.end() && g_carFrame - it->second < 120) {
                                seenBefore = true;
                                break;
                            }
                        }
                    }
                    g_skidSeen[(static_cast<uint64_t>(static_cast<uint32_t>(kx)) << 32) |
                               static_cast<uint32_t>(kz)] = g_carFrame;
                    if (!seenBefore) {
                        // Only beside a car: a strip coming back into view is not a skid.
                        for (const CarShell& car : shells_) {
                            const float ddx = car.objectToWorld.m[3][0] - wx;
                            const float ddz = car.objectToWorld.m[3][2] - wz;
                            if (ddx * ddx + ddz * ddz < 0.9f * 0.9f) {
                                SpawnPuffs(wx, wy, wz);
                                break;
                            }
                        }
                    }
                }
                if (g_skid.soft && soft) {
                    if (g_skid.persist) {
                        NoteSkidStrip(sprite, texture, fxTime);
                    } else {
                        skids.push_back({&sprite, soft, true});
                    }
                    continue;
                }
            }
        }
        // Small flat artwork is drawn from a smoothed copy. Never effects (they are
        // soft already) and never anything the Remix lamp path might replace.
        bool enlarged = false;
        // A gang emblem with hand-made artwork in gta2dx9_hd is drawn from that instead.
        bool hdLogo = false;
        // Which gang's emblem this sprite is, if any. Decided from the palette indices alone, and
        // before the effect verdict is trusted: the Loonies' smiley is a yellow disc with a black
        // outline, which the effect classifier can mistake for a flame - it was then drawn as an
        // un-smoothed effect, pixels and all, and never reached the HD artwork.
        int emblemId = -1;
        if (!sprite.pedestrian && !sprite.corpse && sprite.corners == 4 && !sprite.lamp) {
            emblemId = GangLogoFor(sprite.texture);
            if (emblemId >= 0) {
                static bool logoSeen[kLogoCount] = {};
                if (!logoSeen[emblemId]) {
                    logoSeen[emblemId] = true;
                    Log("logo: sprite %p is gang emblem %d (index key %016llx), game thought it %s, shell %d hidden %d",
                        sprite.texture, emblemId, static_cast<unsigned long long>(SpriteIndexKey(sprite.texture)),
                        effect ? "an effect" : "plain artwork", sprite.shell, sprite.hidden ? 1 : 0);
                }
                if (effect) {
                    // Ordinary artwork, not the effect rendition of it.
                    bool unusedEffect = false;
                    if (IDirect3DTexture9* plainArt = DeviceTextureFor(device, sprite.texture, &unusedEffect, false)) {
                        texture = plainArt;
                    }
                    effect = false;
                }
                if (IDirect3DTexture9* hd = HdLogoTexture(device, emblemId)) {
                    texture = hd;
                    hdLogo = true;
                    enlarged = true;
                }
            }
        }
        if (g_spriteSmooth && sprite.smooth && !effect && !hdLogo) {
            IDirect3DTexture9* smoothed = SmoothSpriteTexture(device, texture);
            enlarged = smoothed != texture;
            texture = smoothed;
        }
        watchPedSmooth(sprite, enlarged);
        // Diagnostic: what exactly does the game draw on a car? Every distinct piece of artwork that
        // is not a pedestrian and lies within a tile of a car shell, whatever the roof rules below
        // say, once each, with the numbers those rules use - so a gang logo that is missed shows up
        // here with the reason.
        if (!sprite.pedestrian && !sprite.corpse && !shells_.empty() && sprite.corners == 4) {
            static std::set<const void*> seenNear;
            if (!seenNear.count(sprite.texture) && seenNear.size() < 200) {
                const float (*sm)[4] = sprite.objectToWorld.m;
                float cw[3] = {0, 0, 0};
                for (int i = 0; i < 4; ++i) {
                    const Vertex& v = sprite.local[i];
                    for (int j = 0; j < 3; ++j) cw[j] += 0.25f * (v.x * sm[0][j] + v.y * sm[1][j] + v.z * sm[2][j] + sm[3][j]);
                }
                for (const CarShell& car : shells_) {
                    const float dx = car.objectToWorld.m[3][0] - cw[0];
                    const float dz = car.objectToWorld.m[3][2] - cw[2];
                    if (dx * dx + dz * dz > 1.0f) continue;
                    seenNear.insert(sprite.texture);
                    const TextureRecord* rec = static_cast<const TextureRecord*>(sprite.texture);
                    Log("near car (sprite %d): texture %p %dx%d key %016llx pal %d shell %d hidden %d lamp %d plain %d effect %d decal %d "
                        "lift-needed-roofs %d",
                        car.sprite, sprite.texture, rec ? rec->width : 0, rec ? rec->height : 0,
                        static_cast<unsigned long long>(SpriteIndexKey(sprite.texture)), rec ? rec->palette : 0,
                        sprite.shell, sprite.hidden ? 1 : 0, sprite.lamp ? 1 : 0, sprite.plain ? 1 : 0,
                        effect ? 1 : 0, IsGroundDecal(sprite.texture) ? 1 : 0, static_cast<int>(roofs.size()));
                    break;
                }
            }
        }
        // Whatever small the game lays on a car's roof - the gang logos on the Zaibatsu, Yakuza and
        // Loonies cars - is drawn at the car's own level, and the dome now stands over that level:
        // it is hidden inside it. It is raised to just clear the dome, like a pedestrian is.
        if (!effect && !sprite.pedestrian && !sprite.corpse && sprite.corners == 4 && sprite.shell < 0 &&
            !sprite.hidden && !sprite.lamp && !roofs.empty() && !g_ghostSwitch[kGhostNoRoofSprites] &&
            !IsGroundDecal(sprite.texture)) {
            const float (*sm)[4] = sprite.objectToWorld.m;
            auto toW = [&](const Vertex& v, float* out) {
                for (int j = 0; j < 3; ++j) out[j] = v.x * sm[0][j] + v.y * sm[1][j] + v.z * sm[2][j] + sm[3][j];
            };
            float w[4][3];
            for (int i = 0; i < 4; ++i) toW(sprite.local[i], w[i]);
            auto len = [](const float* a, const float* b) {
                return std::sqrt((a[0] - b[0]) * (a[0] - b[0]) + (a[1] - b[1]) * (a[1] - b[1]) +
                                 (a[2] - b[2]) * (a[2] - b[2]));
            };
            const float size = (std::max)(len(w[0], w[1]), len(w[0], w[3]));
            // The tank's turret is the one big thing a car carries: a sprite of its own, a
            // block or more across, whose barrel runs well past the hull. It is drawn at
            // the hull's flat level like the logos, so it lay under the dome. Over a tank
            // the size limit goes up and the footprint it may be centred in grows to the
            // whole hull and a little beyond.
            if (size >= 0.08f && size <= 3.0f) {
                const float cwx = (w[0][0] + w[1][0] + w[2][0] + w[3][0]) * 0.25f;
                const float cwy = (w[0][1] + w[1][1] + w[2][1] + w[3][1]) * 0.25f;
                const float cwz = (w[0][2] + w[1][2] + w[2][2] + w[3][2]) * 0.25f;
                for (const Roof& roof : roofs) {
                    const bool tank = roof.shell->sprite == kTankCarSprite;
                    if (size > 0.8f && !tank) continue;
                    const float reach = tank ? 1.9f : 1.0f;
                    const float (*m)[4] = roof.shell->objectToWorld.m;
                    const float d[3] = {cwx - m[3][0], cwy - m[3][1], cwz - m[3][2]};
                    float local[3];
                    for (int j = 0; j < 3; ++j) local[j] = d[0] * m[j][0] + d[1] * m[j][1] + d[2] * m[j][2];
                    if (tank) {
                        // Once each, what lies over a tank: the way to tell which sprite is its
                        // turret if this misses it.
                        static std::set<const void*> tankSeen;
                        if (tankSeen.size() < 40 && std::fabs(local[0] - roof.midX) <= roof.halfX * reach &&
                            std::fabs(local[2] - roof.midZ) <= roof.halfZ * reach &&
                            tankSeen.insert(sprite.texture).second) {
                            const TextureRecord* rec = static_cast<const TextureRecord*>(sprite.texture);
                            Log("over a tank: texture %p %dx%d, %.2f tiles, %.3f under the roof apex, "
                                "centre %.2f,%.2f from the hull's middle",
                                sprite.texture, rec ? rec->width : 0, rec ? rec->height : 0, size,
                                roof.apexY - cwy, local[0] - roof.midX, local[2] - roof.midZ);
                        }
                    }
                    if (std::fabs(local[0] - roof.midX) > roof.halfX * reach || std::fabs(local[2] - roof.midZ) > roof.halfZ * reach) continue;
                    if (emblemId >= 0) {
                        // A gang emblem the game laid on the roof. It is drawn the way the mod's own
                        // roof emblem is: the size the gang's logo is given (the game's sprite is
                        // far bigger than it should look on a car), resting a hair above the dome
                        // instead of floating 3 cm over it - that float is what threw a dark
                        // shadow of the logo onto the roof.
                        fxSprites.push_back(sprite);
                        Sprite& emblem = fxSprites.back();
                        const float target = g_logoSize[emblemId];
                        const float scale = (target > 0.0f && size > target) ? target / size : 1.0f;
                        float centre[3] = {0, 0, 0};
                        for (int i = 0; i < 4; ++i) {
                            centre[0] += 0.25f * emblem.local[i].x;
                            centre[1] += 0.25f * emblem.local[i].y;
                            centre[2] += 0.25f * emblem.local[i].z;
                        }
                        for (int i = 0; i < 4; ++i) {
                            Vertex& v = emblem.local[i];
                            v.x = centre[0] + (v.x - centre[0]) * scale;
                            v.y = centre[1] + (v.y - centre[1]) * scale;
                            v.z = centre[2] + (v.z - centre[2]) * scale;
                        }
                        emblem.objectToWorld.m[3][1] += roof.apexY + g_logoLift - cwy;
                        static bool emblemLogged[kLogoCount] = {};
                        if (!emblemLogged[emblemId]) {
                            emblemLogged[emblemId] = true;
                            Log("roof emblem: gang %d from the game, %.2f -> %.2f tiles, %.3f under the apex before, "
                                "lift %.4f, HD %s",
                                emblemId, size, size * scale, roof.apexY - cwy, g_logoLift, hdLogo ? "yes" : "no");
                        }
                        plain.push_back({&emblem, texture, enlarged});
                        goto roofSpriteDone;
                    }
                    const float need = roof.apexY + 0.03f - cwy;
                    static std::set<const void*> logged;
                    if (logged.insert(sprite.texture).second && logged.size() < 80) {
                        Log("roof sprite: texture %p, key %016llx, %.2f tiles, %.3f under the roof apex%s",
                            sprite.texture, static_cast<unsigned long long>(SpriteIndexKey(sprite.texture)), size,
                            roof.apexY - cwy, need > 0.0f ? " - lifted" : " - already clear");
                    }
                    if (need > 0.0f) {
                        fxSprites.push_back(sprite);
                        Sprite& lifted = fxSprites.back();
                        lifted.objectToWorld.m[3][1] += need;
                        plain.push_back({&lifted, texture, enlarged});
                        goto roofSpriteDone;
                    }
                    break;
                }
            }
        }
        if (false) {
            roofSpriteDone:
            continue;
        }
        // QB-19: a blast's own sprite is dimmed under the volumetric fireball (explosion_fx.cpp).
        uint32_t blastDim = 0;
        const bool blastFx = ExplosionFx().enabled && g_uprightPeds && g_fxUpright;
        if (effect && (g_fire.scorch || blastFx) && !sprite.pedestrian && sprite.corners == 4) {
            // A big effect sprite is a blast: it leaves a burnt mark on the ground.
            const float (*sm)[4] = sprite.objectToWorld.m;
            auto toW = [&](const Vertex& v, float* out) {
                for (int j = 0; j < 3; ++j) out[j] = v.x * sm[0][j] + v.y * sm[1][j] + v.z * sm[2][j] + sm[3][j];
            };
            float w[4][3];
            for (int i = 0; i < 4; ++i) toW(sprite.local[i], w[i]);
            auto len = [](const float* a, const float* b) {
                return std::sqrt((a[0] - b[0]) * (a[0] - b[0]) + (a[1] - b[1]) * (a[1] - b[1]) +
                                 (a[2] - b[2]) * (a[2] - b[2]));
            };
            const float blast = (std::max)(len(w[0], w[1]), len(w[0], w[3]));
            if (blast > g_fire.maxSize && blast < 6.0f) {
                const float bx = (w[0][0] + w[1][0] + w[2][0] + w[3][0]) * 0.25f;
                const float by = (w[0][1] + w[1][1] + w[2][1] + w[3][1]) * 0.25f;
                const float bz = (w[0][2] + w[1][2] + w[2][2] + w[3][2]) * 0.25f;
                // The ground is where the nearest car stands; failing that, the blast's own height.
                float ground = by;
                float best = 2.5f * 2.5f;
                for (const CarShell& car : shells_) {
                    const float ddx = car.objectToWorld.m[3][0] - bx, ddz = car.objectToWorld.m[3][2] - bz;
                    if (ddx * ddx + ddz * ddz < best) {
                        best = ddx * ddx + ddz * ddz;
                        ground = car.objectToWorld.m[3][1];
                    }
                }
                RagdollNoteBlast(bx, ground, bz, blast, g_carFrame);   // QB-27: blown off his feet away from it
                if (g_fire.scorch) NoteScorch(bx, ground + 0.02f, bz, blast * 1.35f);
                if (blastFx) {
                    ExplosionFxNote(bx, ground, bz, blast);
                    if (ExplosionFx().spriteBright < 0.999f) {
                        const int c = static_cast<int>((std::max)(0.0f, ExplosionFx().spriteBright) * 255.0f + 0.5f);
                        blastDim = static_cast<uint32_t>(D3DCOLOR_ARGB(255, c, c, c));
                    }
                }
            }
        }
        if (effect && g_fire.onTop && sprite.corners == 4 && !roofs.empty()) {
            const float (*sm)[4] = sprite.objectToWorld.m;
            auto toWorld = [&](const Vertex& v, float* out) {
                for (int j = 0; j < 3; ++j) out[j] = v.x * sm[0][j] + v.y * sm[1][j] + v.z * sm[2][j] + sm[3][j];
            };
            float cx = 0, cy = 0, cz = 0;
            for (int i = 0; i < 4; ++i) { cx += sprite.local[i].x * 0.25f; cy += sprite.local[i].y * 0.25f; cz += sprite.local[i].z * 0.25f; }
            Vertex centre = sprite.local[0];
            centre.x = cx; centre.y = cy; centre.z = cz;
            float cw[3];
            toWorld(centre, cw);
            const Roof* over = nullptr;
            for (const Roof& roof : roofs) {
                const float (*m)[4] = roof.shell->objectToWorld.m;
                const float d[3] = {cw[0] - m[3][0], cw[1] - m[3][1], cw[2] - m[3][2]};
                float local[3];
                for (int j = 0; j < 3; ++j) local[j] = d[0] * m[j][0] + d[1] * m[j][1] + d[2] * m[j][2];
                // The roof's half sizes are 0.8 of the body's: the flame is judged against a
                // little more than the body, so one on the car's edge is lifted too.
                if (std::fabs(local[0] - roof.midX) <= roof.halfX * 1.4f &&
                    std::fabs(local[2] - roof.midZ) <= roof.halfZ * 1.4f) {
                    over = &roof;
                    break;
                }
            }
            if (over) {
                float w0[3], w1[3], w3[3];
                toWorld(sprite.local[0], w0);
                toWorld(sprite.local[1], w1);
                toWorld(sprite.local[3], w3);
                auto dist = [](const float* a, const float* b) {
                    return std::sqrt((a[0] - b[0]) * (a[0] - b[0]) + (a[1] - b[1]) * (a[1] - b[1]) +
                                     (a[2] - b[2]) * (a[2] - b[2]));
                };
                const float baseSize = (std::max)(dist(w0, w1), dist(w0, w3));
                const bool flame = baseSize <= g_fire.maxSize;
                const float need = (std::max)(0.0f, over->apexY + 0.05f - cw[1]);
                // Scaled through the matrix, about the quad's middle: the vertices are what Remix
                // keys a mesh on, and a flicker that rewrote them was a new mesh every frame.
                auto scaleAbout = [&](Sprite& sp, float k) {
                    float ax = 0, ay = 0, az = 0;
                    for (int i = 0; i < 4; ++i) { ax += sp.local[i].x * 0.25f; ay += sp.local[i].y * 0.25f; az += sp.local[i].z * 0.25f; }
                    float (*m)[4] = sp.objectToWorld.m;
                    for (int j = 0; j < 4; ++j) {
                        const float shift = ax * m[0][j] + ay * m[1][j] + az * m[2][j];
                        for (int i = 0; i < 3; ++i) m[i][j] *= k;
                        m[3][j] += shift * (1.0f - k);
                    }
                };
                const float phase = static_cast<float>((reinterpret_cast<uintptr_t>(sprite.texture) >> 4) & 255u) * 0.37f;
                fxSprites.push_back(sprite);
                Sprite& base = fxSprites.back();
                base.objectToWorld.m[3][1] += need;
                if (flame) {
                    const float flick = 1.0f + g_fire.flicker * 0.5f *
                                                   std::sin(static_cast<float>(fxTime) * g_fire.flickerHz + phase);
                    scaleAbout(base, g_fire.sizeScale * flick);
                    fireSpots.push_back({cw[0], cw[1] + need, cw[2], baseSize * g_fire.sizeScale, over->shell});
                }
                {
                    uint32_t dim = 0;
                    if (flame && g_fire.flames && g_fire.spriteBright < 0.999f) {
                        const int c = static_cast<int>((std::max)(0.0f, g_fire.spriteBright) * 255.0f + 0.5f);
                        dim = static_cast<uint32_t>(D3DCOLOR_ARGB(255, c, c, c));
                    }
                    if (!flame && blastDim) dim = blastDim;
                    effects.push_back({&base, texture, enlarged, dim});
                }
                if (flame) {
                    for (int li = 1; li <= g_fire.layers; ++li) {
                        fxSprites.push_back(sprite);
                        Sprite& layer = fxSprites.back();
                        const float flick = 1.0f + g_fire.flicker *
                                std::sin(static_cast<float>(fxTime) * g_fire.flickerHz * (1.0f + 0.17f * li) + phase * li);
                        scaleAbout(layer, g_fire.sizeScale * (1.0f + g_fire.layerGrow * li) * flick);
                        layer.objectToWorld.m[3][1] += need + g_fire.layerRise * li;
                        const float bright = std::pow(g_fire.layerBright, static_cast<float>(li));
                        auto chan = [&](float t) {
                            return static_cast<int>((std::max)(0.0f, (std::min)(1.0f, t * bright)) * 255.0f + 0.5f);
                        };
                        effects.push_back({&layer, texture, enlarged,
                                           static_cast<uint32_t>(D3DCOLOR_ARGB(255, chan(g_fire.tint[0]),
                                                                              chan(g_fire.tint[1]),
                                                                              chan(g_fire.tint[2])))});
                    }
                }
                continue;
            }
        }
        if (sprite.boardUi && sprite.pedestrian && !effect && sprite.corners == 4) {
            boarders.push_back({&sprite, texture, enlarged});
            continue;
        }
        const bool bloodDecal = !effect && g_bloodGloss && sprite.corners == 4 && !sprite.pedestrian &&
                                !sprite.corpse && IsGroundDecal(sprite.texture);
        if (sprite.corners == 4 && !sprite.pedestrian && !sprite.corpse && !sprite.lamp && !bloodDecal) {
            // Tiny artwork (a bullet, a spark, a muzzle flash, whichever list it
            // lands in): remembered for the figures, see g_fxSpotsNow.
            const float (*m)[4] = sprite.objectToWorld.m;
            auto wp = [&](const Vertex& v, float* o) {
                for (int j = 0; j < 3; ++j) o[j] = v.x * m[0][j] + v.y * m[1][j] + v.z * m[2][j] + m[3][j];
            };
            float w0[3], w1[3], w3[3];
            wp(sprite.local[0], w0); wp(sprite.local[1], w1); wp(sprite.local[3], w3);
            auto d2 = [](const float* a, const float* b) {
                return (a[0] - b[0]) * (a[0] - b[0]) + (a[1] - b[1]) * (a[1] - b[1]) + (a[2] - b[2]) * (a[2] - b[2]);
            };
            if ((std::max)(d2(w0, w1), d2(w0, w3)) < 0.16f * 0.16f) {
                g_fxSpotsNow.push_back({0.5f * (w0[0] + w3[0]) + 0.5f * (w1[0] - w0[0]), 0.5f * (w0[1] + w3[1]),
                                        0.5f * (w0[2] + w3[2]) + 0.5f * (w1[2] - w0[2])});
            }
        }
        (effect ? effects : plain).push_back({&sprite, texture, enlarged, effect ? blastDim : 0u, bloodDecal});
    }

    stageTimer.Mark();   // 1: the sprite loop
    // Remembered skid strips: those the game still submits and those it has dropped, all
    // drawn from the memory, at full strength for a while and then fading.
    //
    // One draw call per strip was a thousand draw calls a frame after a few minutes of
    // driving, and Remix keeps an instance of each, so the game stuttered. So the strips
    // are grouped by where they lie (4-tile cells), when they were laid (3-second buckets)
    // and their artwork, and each group is one mesh in world space. A group's contents do not
    // change once its bucket has closed, so Remix sees the same mesh every frame; only the
    // few strips of the bucket still being laid are drawn one at a time. Fading is the
    // draw's own alpha, not the vertices'. Only the cells the game is drawing are issued.
    struct SkidBatchDraw {
        IDirect3DTexture9* texture;
        uint32_t color;
        std::vector<Vertex> verts;
        std::vector<uint16_t> idx;
    };
    std::vector<SkidBatchDraw> skidBatches;
    if (!g_skid.persist || !g_skid.soft) {
        if (!g_skidGhosts.empty()) ClearSkidGhosts();
    } else if (!g_skidGhosts.empty()) {
        float x0 = 1e30f, x1 = -1e30f, z0 = 1e30f, z1 = -1e30f;
        for (const Sprite& s : sprites_) {
            if (s.ghost) continue;
            const float x = s.objectToWorld.m[3][0], z = s.objectToWorld.m[3][2];
            x0 = (std::min)(x0, x); x1 = (std::max)(x1, x);
            z0 = (std::min)(z0, z); z1 = (std::max)(z1, z);
        }
        constexpr float kMargin = 3.0f;
        constexpr float kCell = 4.0f;
        constexpr double kBucket = 3.0;
        const double hold = (std::max)(0.0f, g_skid.skidHold);
        const double fade = (std::max)(0.5f, g_skid.skidFade);
        auto alphaAt = [&](double age) {
            if (age <= hold) return 1.0f;
            const float t = static_cast<float>((std::min)(1.0, (age - hold) / fade));
            return 1.0f - t * t * (3.0f - 2.0f * t);   // smoothstep: no visible step either end
        };
        auto colorFor = [](float a) -> uint32_t {
            if (a >= 0.999f) return 0;
            const int a8 = (std::max)(0, (std::min)(255, static_cast<int>(a * 255.0f + 0.5f)));
            return static_cast<uint32_t>(D3DCOLOR_ARGB(a8, 255, 255, 255));
        };
        struct Item {
            int cx, cz;
            int64_t bucket;
            IDirect3DTexture9* src;
            uint64_t key;
            const SkidGhost* g;
        };
        std::vector<Item> items;
        items.reserve(g_skidGhosts.size());
        for (auto it = g_skidGhosts.begin(); it != g_skidGhosts.end();) {
            SkidGhost& g = it->second;
            if (fxTime - g.born >= hold + fade) {
                if (g.source) g.source->Release();
                it = g_skidGhosts.erase(it);
                continue;
            }
            items.push_back({static_cast<int>(std::floor(g.sprite.objectToWorld.m[3][0] / kCell)),
                             static_cast<int>(std::floor(g.sprite.objectToWorld.m[3][2] / kCell)),
                             static_cast<int64_t>(std::floor(g.born / kBucket)), g.source, it->first, &g});
            ++it;
        }
        std::sort(items.begin(), items.end(), [](const Item& a, const Item& b) {
            if (a.cx != b.cx) return a.cx < b.cx;
            if (a.cz != b.cz) return a.cz < b.cz;
            if (a.bucket != b.bucket) return a.bucket < b.bucket;
            if (a.src != b.src) return a.src < b.src;
            return a.key < b.key;
        });
        auto sameGroup = [](const Item& a, const Item& b) {
            return a.cx == b.cx && a.cz == b.cz && a.bucket == b.bucket && a.src == b.src;
        };
        for (size_t i = 0; i < items.size();) {
            size_t j = i + 1;
            while (j < items.size() && sameGroup(items[i], items[j])) ++j;
            const Item& first = items[i];
            const float cellX = static_cast<float>(first.cx) * kCell;
            const float cellZ = static_cast<float>(first.cz) * kCell;
            const bool visible = cellX + kCell >= x0 - kMargin && cellX <= x1 + kMargin &&
                                 cellZ + kCell >= z0 - kMargin && cellZ <= z1 + kMargin;
            if (visible) {
                bool rubber = false;
                IDirect3DTexture9* soft = SoftSkidTexture(device, first.src, &rubber);
                if (rubber && soft) {
                    const double bucketEnd = static_cast<double>(first.bucket + 1) * kBucket;
                    if (fxTime - bucketEnd <= 1.0) {
                        // Still being laid: one at a time, each at its own age.
                        for (size_t k = i; k < j; ++k) {
                            const SkidGhost& g = *items[k].g;
                            skids.push_back({&g.sprite, soft, true, colorFor(alphaAt(fxTime - g.born))});
                        }
                    } else {
                        const float a = alphaAt(fxTime - (static_cast<double>(first.bucket) + 0.5) * kBucket);
                        if (a > 0.01f) {
                            SkidBatchDraw batch{soft, colorFor(a), {}, {}};
                            batch.verts.reserve((j - i) * 4);
                            batch.idx.reserve((j - i) * 6);
                            for (size_t k = i; k < j; ++k) {
                                const Sprite& sp = items[k].g->sprite;
                                if (sp.corners != 4) continue;
                                if (batch.verts.size() + 4 > 65000) {
                                    skidBatches.push_back(std::move(batch));
                                    batch = SkidBatchDraw{soft, colorFor(a), {}, {}};
                                }
                                const uint16_t base = static_cast<uint16_t>(batch.verts.size());
                                const float(*m)[4] = sp.objectToWorld.m;
                                for (int c = 0; c < 4; ++c) {
                                    const Vertex& v = sp.local[c];
                                    Vertex w;
                                    w.x = v.x * m[0][0] + v.y * m[1][0] + v.z * m[2][0] + m[3][0];
                                    w.y = v.x * m[0][1] + v.y * m[1][1] + v.z * m[2][1] + m[3][1];
                                    w.z = v.x * m[0][2] + v.y * m[1][2] + v.z * m[2][2] + m[3][2];
                                    float nx = v.nx * m[0][0] + v.ny * m[1][0] + v.nz * m[2][0];
                                    float ny = v.nx * m[0][1] + v.ny * m[1][1] + v.nz * m[2][1];
                                    float nz = v.nx * m[0][2] + v.ny * m[1][2] + v.nz * m[2][2];
                                    const float len = std::sqrt(nx * nx + ny * ny + nz * nz);
                                    if (len > 1e-6f) { nx /= len; ny /= len; nz /= len; }
                                    w.nx = nx; w.ny = ny; w.nz = nz;
                                    w.u = v.u; w.v = v.v;
                                    batch.verts.push_back(w);
                                }
                                const uint16_t quad[6] = {0, 1, 2, 0, 2, 3};
                                for (uint16_t q : quad) batch.idx.push_back(static_cast<uint16_t>(base + q));
                            }
                            if (!batch.idx.empty()) skidBatches.push_back(std::move(batch));
                        }
                    }
                }
            }
            i = j;
        }
    }

    stageTimer.Mark();   // 2: remembered skid strips
    // Two triangles from four corners, the same two every time. Indexed rather
    // than a six-vertex list so the index buffer is part of the topological hash
    // Remix buckets on, and so the quad really is four vertices rather than four
    // with two duplicated.
    static const uint16_t kQuadIndices[6] = {0, 1, 2, 0, 2, 3};

    // The device is a state machine and the texture rarely changes between
    // neighbouring sprites, so the redundant SetTexture calls are skipped. The
    // world matrix genuinely changes every time and cannot be.
    IDirect3DTexture9* bound = nullptr;
    bool linear = false;
    // Effect artwork stood up for a street-level camera. GTA2 lays its explosions,
    // flames, muzzle flashes and bullets flat on the road like everything else,
    // which from eye height is a sliver; here each is turned to face the camera:
    // the big ones (fire, blasts) standing on the spot they lay, the small ones
    // (a muzzle flash, a bullet, a spark) centred at about gun height. A small
    // one that moved since last frame is a bullet in flight and is drawn as a
    // streak along its path instead of a dot.
    std::map<uintptr_t, FxSeen>& fxSeen = g_fxSeen;
    const bool fxUpright = g_uprightPeds && g_fxUpright;
    const gta2::Vec3 fxEye = camera.Position();
    // FIX-FIGURE (fp-viewmodel-box-gun-no-hands): in first person on foot the
    // game's own flash (and a bullet's first frames) sits at the eye: seen from
    // there it is a pixelated orange sprite at the bottom edge, a second flash
    // beside the view model's. Effects that small within half a block of the
    // eye are left out; the view model draws the shot.
    const bool fxFpFoot = CurrentViewMode() == ViewMode::FirstPerson && g_playerObject && g_hiddenObjects[0] == g_playerObject;
    auto fxAtEye = [&](const float* c, float size) {
        if (!fxFpFoot || size >= 0.35f) return false;
        const float dx = c[0] - fxEye.x, dz = c[2] - fxEye.z;
        return dx * dx + dz * dz < 0.25f && std::fabs(c[1] - fxEye.y) < 0.9f;
    };
    auto issue = [&](const std::vector<Drawable>& list, bool fx = false) {
        bool tinted = false;
        for (const Drawable& d : list) {
            D3DMATRIX world;
            if (fx && fxUpright && d.sprite->corners == 4 && !d.blood && !d.sprite->pedestrian) {
                const Sprite& sp = *d.sprite;
                float c[3] = {0, 0, 0}, w0[3], w1[3], w3[3];
                auto toW = [&](const Vertex& v, float* o) {
                    const float (*m)[4] = sp.objectToWorld.m;
                    for (int j = 0; j < 3; ++j) o[j] = v.x * m[0][j] + v.y * m[1][j] + v.z * m[2][j] + m[3][j];
                };
                toW(sp.local[0], w0); toW(sp.local[1], w1); toW(sp.local[3], w3);
                for (int i = 0; i < 4; ++i) { float w[3]; toW(sp.local[i], w); for (int j = 0; j < 3; ++j) c[j] += 0.25f * w[j]; }
                auto dist = [](const float* a, const float* b) {
                    return std::sqrt((a[0] - b[0]) * (a[0] - b[0]) + (a[1] - b[1]) * (a[1] - b[1]) + (a[2] - b[2]) * (a[2] - b[2]));
                };
                const float size = (std::max)(dist(w0, w1), dist(w0, w3));
                const bool small = size < 0.22f;
                if (small) g_fxSpotsNow.push_back({c[0], c[1], c[2]});
                {
                    // GTA2DX9_LOG_FX=1: which code-object sprites the effects are (base,
                    // number, size), once per number: the muzzle flashes, bullets,
                    // sparks and shells of each weapon. A probe, off by default.
                    static int probe = -1;
                    if (probe < 0) { char buf[8] = {}; probe = GetEnvironmentVariableA("GTA2DX9_LOG_FX", buf, sizeof buf) && buf[0] == '1'; }
                    if (probe && sp.object) {
                        static std::set<int> seen;
                        const uint8_t* obj = reinterpret_cast<const uint8_t*>(sp.object);
                        int base = -1; unsigned num = 0;
                        GTA2_TRY {
                            base = *reinterpret_cast<const int32_t*>(obj + game::kSpriteObjectBase);
                            num = *reinterpret_cast<const uint16_t*>(obj + game::kSpriteObjectNumber);
                        } GTA2_EXCEPT { base = -2; }
                        const int key = base * 100000 + static_cast<int>(num);
                        if (seen.size() < 400 && seen.insert(key).second)
                            Log("fx sprite: base %d number %u size %.3f at %.1f,%.1f,%.1f%s", base, num, size, c[0], c[1], c[2], small ? " small" : "");
                    }
                }
                if (small && sp.object) {
                    // In flight? Where this object was drawn last frame.
                    auto seen = fxSeen.find(sp.object);
                    float px = c[0], py = c[1], pz = c[2];
                    bool flying = false;
                    const bool fresh = seen == fxSeen.end() || g_carFrame - seen->second.frame > 2;
                    if (!fresh) {
                        const float dx = c[0] - seen->second.x, dz = c[2] - seen->second.z;
                        const float moved = std::sqrt(dx * dx + dz * dz);
                        if (moved > 0.06f && moved < 2.5f) { flying = true; px = seen->second.x; py = seen->second.y; pz = seen->second.z; }
                        else if (seen->second.flying && moved > 0.02f) flying = true;
                    }
                    if (fresh) g_fxFreshNow.push_back({c[0], c[1], c[2], size, sp.object, false});
                    // A rocket (the big, slow flyer) leaves a smoke trail.
                    if (flying && size > 0.16f) ShotFxSmoke(c[0], c[1] + 0.30f, c[2]);   // a bullet is 0.125
                    fxSeen[sp.object] = {c[0], c[1], c[2], g_carFrame, size, flying};
                    if (fxSeen.size() > 4096) fxSeen.clear();
                    if (fxAtEye(c, size)) continue;
                    if (flying) {
                        // A streak from where it was to where it is, a hand wide, facing the eye.
                        const float gun = 0.30f;
                        float ax = c[0] - px, ay = 0.0f, az = c[2] - pz;
                        const float al = std::sqrt(ax * ax + az * az);
                        ax /= al; az /= al;
                        // No longer than half a block: a bullet crosses a block a frame
                        // and a full-length streak read as a flame.
                        if (al > 0.5f) { px = c[0] - ax * 0.5f; pz = c[2] - az * 0.5f; py = c[1]; }
                        float ex = fxEye.x - c[0], ez = fxEye.z - c[2];
                        const float el = (std::max)(1e-4f, std::sqrt(ex * ex + ez * ez));
                        ex /= el; ez /= el;
                        // Perpendicular to the path and to the line of sight.
                        float nx = ay * ez - az * 0.0f, ny = az * ex - ax * ez, nz = ax * 0.0f - ay * ex;
                        const float nl = std::sqrt(nx * nx + ny * ny + nz * nz);
                        if (nl < 1e-4f) { nx = 0.0f; ny = 1.0f; nz = 0.0f; } else { nx /= nl; ny /= nl; nz /= nl; }
                        const float hw = 0.018f;
                        Vertex q[4];
                        const float y0 = py + gun, y1 = c[1] + gun;
                        q[0] = {px + nx * hw, y0 + ny * hw, pz + nz * hw, 0, 1, 0, 0.0f, 0.0f};
                        q[1] = {c[0] + nx * hw, y1 + ny * hw, c[2] + nz * hw, 0, 1, 0, 1.0f, 0.0f};
                        q[2] = {c[0] - nx * hw, y1 - ny * hw, c[2] - nz * hw, 0, 1, 0, 1.0f, 1.0f};
                        q[3] = {px - nx * hw, y0 - ny * hw, pz - nz * hw, 0, 1, 0, 0.0f, 1.0f};
                        gta2::Mat4 id;
                        memcpy(&world, id.m, sizeof(world));
                        device->SetTransform(D3DTS_WORLD, &world);
                        if (d.texture != bound) { device->SetTexture(0, d.texture); bound = d.texture; }
                        device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, 4, 2, kQuadIndices, D3DFMT_INDEX16, q, sizeof(Vertex));
                        ++drops_.drawn;
                        continue;
                    }
                }
                if (fxAtEye(c, size)) continue;
                gta2::Mat4 up = UprightPedMatrix(sp.local, sp.corners, sp.objectToWorld, fxEye);
                if (small) {
                    // Centred at gun height rather than stood on the road.
                    float minZ = 1e9f, maxZ = -1e9f;
                    for (int i = 0; i < 4; ++i) { minZ = (std::min)(minZ, sp.local[i].z); maxZ = (std::max)(maxZ, sp.local[i].z); }
                    up.m[3][1] = c[1] + 0.30f - 0.5f * (maxZ - minZ) * std::fabs(up.m[2][1]);
                    up.m[3][0] = c[0]; up.m[3][2] = c[2];
                }
                memcpy(&world, up.m, sizeof(world));
                device->SetTransform(D3DTS_WORLD, &world);
                if (d.color) {
                    if (!tinted) {
                        device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
                        device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
                        device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_TFACTOR);
                        device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
                        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
                        device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_TFACTOR);
                        tinted = true;
                    }
                    device->SetRenderState(D3DRS_TEXTUREFACTOR, d.color);
                } else if (tinted) {
                    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
                    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
                    tinted = false;
                }
                if (d.enlarged != linear) {
                    device->SetSamplerState(0, D3DSAMP_MAGFILTER, d.enlarged ? D3DTEXF_LINEAR : D3DTEXF_POINT);
                    linear = d.enlarged;
                }
                if (d.texture != bound) { device->SetTexture(0, d.texture); bound = d.texture; }
                device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, 4, 2, kQuadIndices, D3DFMT_INDEX16, d.sprite->local, sizeof(Vertex));
                ++drops_.drawn;
                continue;
            }
            const bool onFeet = d.sprite->pedestrian && !d.sprite->climbing && !d.sprite->boardUi &&
                                !d.sprite->corpse && d.sprite->corners == 4;
            if (g_pedFigures && onFeet) continue;   // drawn as a figure instead, see DrawPedFigures
            // With the models, the lying and the climbing frames are figures too.
            if (g_pedFigures && g_groundModels && !d.sprite->boardUi && d.sprite->corners == 4 &&
                (d.sprite->corpse || (d.sprite->pedestrian && d.sprite->climbing))) continue;
            if (g_uprightPeds && onFeet) {
                // A chase or first-person camera: stood up facing it. See UprightPedMatrix.
                const gta2::Mat4 upright =
                    UprightPedMatrix(d.sprite->local, d.sprite->corners, d.sprite->objectToWorld, camera.Position());
                memcpy(&world, upright.m, sizeof(world));
            } else {
                memcpy(&world, d.sprite->objectToWorld.m, sizeof(world));
            }
            device->SetTransform(D3DTS_WORLD, &world);
            if (d.color) {
                if (!tinted) {
                    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
                    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
                    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_TFACTOR);
                    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
                    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
                    device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_TFACTOR);
                    tinted = true;
                }
                device->SetRenderState(D3DRS_TEXTUREFACTOR, d.color);
            } else if (tinted) {
                device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
                device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
                tinted = false;
            }
            if (d.enlarged != linear) {
                device->SetSamplerState(0, D3DSAMP_MAGFILTER, d.enlarged ? D3DTEXF_LINEAR : D3DTEXF_POINT);
                linear = d.enlarged;
            }
            if (d.texture != bound) {
                device->SetTexture(0, d.texture);
                bound = d.texture;
            }
            device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, 4, 2, kQuadIndices,
                                           D3DFMT_INDEX16, d.sprite->local, sizeof(Vertex));
            ++drops_.drawn;
        }
        if (tinted) {
            device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
            device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
        }
        if (linear) {
            device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
            linear = false;
        }
    };

    // The gang emblem on the roof of the gang's car: a quad lying on the top of the car's dome,
    // in the dome's own space, so it keeps the car's shape and placement every frame. See
    // g_logoCar. The sprite's top is the car's rear and its bottom the nose; the Z reads the same
    // either way round, so only the axis matters.
    if (g_roofLogos) {
        constexpr int n = kDomeSegments;
        for (size_t si = 0; si < shells_.size(); ++si) {
            const CarShell& shell = shells_[si];
            if (si >= shellWarm.size() || !shellWarm[si]) continue;
            int logoId = -1;
            for (int id = 0; id < kLogoCount; ++id) {
                if (g_logoCar[id] >= 0 && g_logoCar[id] == shell.sprite) { logoId = id; break; }
            }
            if (logoId < 0) continue;
            if (g_logoLumaMax[logoId] > 0.0f || g_logoBlueMin[logoId] > 0.0f) {
                // Only the gang's own paint: the Z-Type is also sold in other colours, and those are
                // not Zaibatsu. The paint is told by how dark the car's artwork is.
                IDirect3DTexture9* art = shellArt[si];
                if (!art) continue;
                struct LumaEntry { float luma; float blue; uint32_t frame; IDirect3DTexture9* art; };
                static std::map<uintptr_t, LumaEntry> lumaCache;
                auto hit = lumaCache.find(shell.object);
                if (hit == lumaCache.end() || hit->second.art != art || g_carFrame - hit->second.frame > 3000) {
                    float luma = 255.0f, blue = 1.0f;
                    D3DSURFACE_DESC ad;
                    D3DLOCKED_RECT lr;
                    if (SUCCEEDED(art->GetLevelDesc(0, &ad)) && ad.Format == D3DFMT_A8R8G8B8 &&
                        SUCCEEDED(art->LockRect(0, &lr, nullptr, D3DLOCK_READONLY))) {
                        std::vector<uint8_t> px(static_cast<size_t>(ad.Width) * ad.Height * 4);
                        for (UINT y = 0; y < ad.Height; ++y) {
                            memcpy(&px[static_cast<size_t>(y) * ad.Width * 4],
                                   static_cast<const uint8_t*>(lr.pBits) + static_cast<size_t>(y) * lr.Pitch,
                                   static_cast<size_t>(ad.Width) * 4);
                        }
                        art->UnlockRect(0);
                        luma = MeanLuma(px);
                        blue = BlueOverRed(px);
                    }
                    hit = lumaCache.insert_or_assign(shell.object, LumaEntry{luma, blue, g_carFrame, art}).first;
                    static int lumaLogs = 0;
                    if (lumaLogs++ < 60) {
                        const bool paintOk = (g_logoLumaMax[logoId] <= 0.0f || luma < g_logoLumaMax[logoId]) &&
                                             (g_logoBlueMin[logoId] <= 0.0f || blue >= g_logoBlueMin[logoId]);
                        Log("roof logo: car %d object %p artwork brightness %.1f, blue/red %.2f (emblem %d needs brightness under %.0f, blue/red over %.2f) -> %s",
                            shell.sprite, reinterpret_cast<void*>(shell.object), luma, blue, logoId, g_logoLumaMax[logoId],
                            g_logoBlueMin[logoId], paintOk ? "emblem" : "no emblem");
                    }
                }
                if (g_logoLumaMax[logoId] > 0.0f && hit->second.luma >= g_logoLumaMax[logoId]) continue;
                if (g_logoBlueMin[logoId] > 0.0f && hit->second.blue < g_logoBlueMin[logoId]) continue;
            }
            IDirect3DTexture9* logo = HdLogoTexture(device, logoId);
            if (!logo) continue;
            D3DSURFACE_DESC desc;
            if (FAILED(logo->GetLevelDesc(0, &desc)) || !desc.Width || !desc.Height) continue;
            auto P = [&](int i, int j) -> const Vertex& { return shell.local[j * (n + 1) + i]; };
            const Vertex& apex = P(n / 2, n / 2);
            const float above = apex.y >= P(0, 0).y ? 1.0f : -1.0f;
            auto axis = [&](const Vertex& a, const Vertex& b, float* x, float* z, float* half) {
                const float ax = b.x - a.x, az = b.z - a.z;
                const float len = std::sqrt(ax * ax + az * az);
                *half = len * 0.5f;
                *x = len > 1e-6f ? ax / len : 0.0f;
                *z = len > 1e-6f ? az / len : 0.0f;
            };
            float rx, rz, halfWide, dx, dz, halfLong;
            axis(P(0, n / 2), P(n, n / 2), &rx, &rz, &halfWide);
            axis(P(n / 2, 0), P(n / 2, n), &dx, &dz, &halfLong);
            float hh = g_logoSize[logoId] * 0.5f;
            float wh = hh * static_cast<float>(desc.Width) / static_cast<float>(desc.Height);
            if (wh > halfWide * 0.7f) { hh *= halfWide * 0.7f / wh; wh = halfWide * 0.7f; }
            const float cx = apex.x + dx * g_logoForward[logoId] * halfLong;
            const float cz = apex.z + dz * g_logoForward[logoId] * halfLong;
            // The roof is not flat: read the dome's height under the emblem (bilinear over the
            // lattice) and lay the emblem at the highest point under it, so it sits on the cab
            // roof instead of sinking into it.
            auto domeY = [&](float px, float pz) -> float {
                const float a = ((px - apex.x) * rx + (pz - apex.z) * rz) / (std::max)(halfWide, 1e-6f);
                const float b = ((px - apex.x) * dx + (pz - apex.z) * dz) / (std::max)(halfLong, 1e-6f);
                float fi = n * 0.5f + a * n * 0.5f, fj = n * 0.5f + b * n * 0.5f;
                fi = (std::min)((std::max)(fi, 0.0f), static_cast<float>(n) - 0.001f);
                fj = (std::min)((std::max)(fj, 0.0f), static_cast<float>(n) - 0.001f);
                const int i0 = static_cast<int>(fi), j0 = static_cast<int>(fj);
                const float ti = fi - i0, tj = fj - j0;
                const float y0 = P(i0, j0).y * (1 - ti) + P(i0 + 1, j0).y * ti;
                const float y1 = P(i0, j0 + 1).y * (1 - ti) + P(i0 + 1, j0 + 1).y * ti;
                return y0 * (1 - tj) + y1 * tj;
            };
            float roofY = domeY(cx, cz);
            for (int c = 0; c < 4; ++c) {
                const float sx4[4] = {-1, 1, 1, -1}, sy4[4] = {-1, -1, 1, 1};
                const float y = domeY(cx + rx * wh * sx4[c] + dx * hh * sy4[c],
                                      cz + rz * wh * sx4[c] + dz * hh * sy4[c]);
                roofY = above > 0 ? (std::max)(roofY, y) : (std::min)(roofY, y);
            }
            const float cy = roofY + above * g_logoLift;
            fxSprites.emplace_back();
            Sprite& s = fxSprites.back();
            s.texture = nullptr;
            s.corners = 4;
            s.objectToWorld = shell.objectToWorld;
            s.plain = true;
            s.shell = -1;
            const float sx[4] = {-1, 1, 1, -1}, sy[4] = {-1, -1, 1, 1};
            for (int c = 0; c < 4; ++c) {
                Vertex& v = s.local[c];
                v.x = cx + rx * wh * sx[c] + dx * hh * sy[c];
                v.y = cy;
                v.z = cz + rz * wh * sx[c] + dz * hh * sy[c];
                v.nx = 0.0f; v.ny = above; v.nz = 0.0f;
                const int tc = (c + g_roofLogoQuarter + g_logoTurn[logoId]) & 3;
                v.u = sx[tc] < 0 ? 0.0f : 1.0f;
                v.v = sy[tc] < 0 ? 0.0f : 1.0f;
            }
            static bool logged = false;
            if (!logged) {
                logged = true;
                Log("roof logo: emblem %d on car %d, %.2f x %.2f tiles, dome apex %.3f", logoId, shell.sprite,
                    2.0f * wh, 2.0f * hh, apex.y);
            }
            plain.push_back({&s, logo, true});
        }
    }

    // Blood on the ground through the Remix API with a dark, glossy material of its own; red
    // artwork only. Anything else, or blood whose material is still loading, is drawn plain.
    if (g_bloodGloss && g_carMaterial && RemixApiHasInstances()) {
        static const std::vector<uint16_t> bloodIndices = {0, 1, 2, 0, 2, 3};
        std::vector<Drawable> rest;
        rest.reserve(plain.size());
        for (const Drawable& d : plain) {
            bool drawn = false;
            if (d.blood) {
                bool warm = false;
                const remixapi_MaterialHandle material = BloodMaterialFor(d.texture, &warm);
                if (material && warm) {
                    const remixapi_MeshHandle mesh =
                        CarMeshFor(d.sprite->local, 4, sizeof(Vertex), bloodIndices, material);
                    D3DMATRIX world;
                    memcpy(&world, d.sprite->objectToWorld.m, sizeof(world));
                    drawn = mesh && DrawCutoutInstance(mesh, world);
                }
            }
            if (!drawn) rest.push_back(d);
        }
        plain.swap(rest);
    }

    // Lit lamps through the Remix API, each with a glowing material of its own; any
    // that cannot be (no API, material still loading, refused) are drawn plain.
    if (g_carMaterial && g_lampGlow > 0.01f && RemixApiHasInstances()) {
        static const std::vector<uint16_t> lampIndices = {0, 1, 2, 0, 2, 3};
        std::vector<Drawable> rest;
        rest.reserve(plain.size());
        for (const Drawable& d : plain) {
            bool drawn = false;
            if (d.sprite->lamp && !d.sprite->lampPlain && d.sprite->corners == 4) {
                const remixapi_MaterialHandle material =
                    LampMaterialFor(*d.sprite->lamp, d.sprite->lampMirrored);
                if (material && LampMaterialWarm(*d.sprite->lamp, d.sprite->lampMirrored)) {
                    // Drawn smaller than the lamp's pixels, toward its centre: the glow of
                    // a big headlight block was a bar standing out past the car's nose.
                    Vertex shrunk[4];
                    memcpy(shrunk, d.sprite->local, sizeof(shrunk));
                    float cx = 0, cy = 0, cz = 0;
                    for (const Vertex& v : shrunk) { cx += v.x * 0.25f; cy += v.y * 0.25f; cz += v.z * 0.25f; }
                    for (Vertex& v : shrunk) {
                        v.x = cx + (v.x - cx) * g_lampSize;
                        v.y = cy + (v.y - cy) * g_lampSize;
                        v.z = cz + (v.z - cz) * g_lampSize;
                    }
                    const remixapi_MeshHandle mesh =
                        CarMeshFor(shrunk, 4, sizeof(Vertex), lampIndices, material);
                    D3DMATRIX world;
                    memcpy(&world, d.sprite->objectToWorld.m, sizeof(world));
                    drawn = mesh && DrawCutoutInstance(mesh, world);
                }
            }
            if (!drawn) rest.push_back(d);
        }
        plain.swap(rest);
    }

    issue(plain);
    stageTimer.Mark();   // 3: the game's own quads issued
    if (g_groundModels) {
        DrawCarModels(device);
        {
            // Dark when the sky's sun is down: the lamps follow the picture, not the clock.
            const gta2::SkySettings& sky = gta2::SkyConfig();
            CarBodiesSetLamps(g_carLamps, sky.sunElevationDeg < 6.0f);
        }
        CarBodiesDraw(device, carBodies_, g_carFrame, camera.Position());
    }
    stageTimer.Mark();   // 4: cars
    if (g_groundModels) DrawProps(device, camera.Position());
    stageTimer.Mark();   // 5: props
    if (g_groundModels) MapObjectsDraw(device, sprites_);
    stageTimer.Mark();   // 6: map objects
    if (g_pedFigures) DrawPedFigures(device);
    if (g_pedFigures && g_groundModels && ModelsAvailable()) DrawViewModel(device, camera);
    stageTimer.Mark();   // 7: pedestrians
    // Textures the models will need, created and uploaded a few per frame
    // ahead of their first appearance (see ModelsWarmTextures).
    if (ModelsAvailable()) {
        static int left = 1;
        if (left > 0) {
            // The classic view has most of its frame to spare: the warm-up goes four
            // times faster there (all of it in ~4 s of a level instead of ~18).
            const bool classic = CurrentViewMode() == ViewMode::Classic;
            left = classic ? ModelsWarmTextures(device, 16, 8.0) : ModelsWarmTextures(device, 2, 2.0);
            if (left == 0) Log("models: every texture created and uploaded ahead of use");
        }
    }

    // Soft skid marks, translucent, over the road and under everything standing on it.
    if (!skids.empty() || !skidBatches.empty()) {
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
        device->SetRenderState(D3DRS_ALPHAREF, 1u);
        device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
        issue(skids);
        if (!skidBatches.empty()) {
            // Each batch is already in world space: identity world, linear sampling like the rest.
            D3DMATRIX identity = {};
            identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
            device->SetTransform(D3DTS_WORLD, &identity);
            device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
            bool batchTinted = false;
            for (const SkidBatchDraw& b : skidBatches) {
                if (b.color) {
                    if (!batchTinted) {
                        device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
                        device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
                        device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_TFACTOR);
                        device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
                        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
                        device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_TFACTOR);
                        batchTinted = true;
                    }
                    device->SetRenderState(D3DRS_TEXTUREFACTOR, b.color);
                } else if (batchTinted) {
                    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
                    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
                    batchTinted = false;
                }
                device->SetTexture(0, b.texture);
                device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(b.verts.size()),
                                               static_cast<UINT>(b.idx.size() / 3), b.idx.data(),
                                               D3DFMT_INDEX16, b.verts.data(), sizeof(Vertex));
                ++drops_.drawn;
            }
            if (batchTinted) {
                device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
                device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
            }
            device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
            bound = nullptr;
        }
        device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, blending ? TRUE : FALSE);
        device->SetRenderState(D3DRS_ALPHAREF, blending ? 1u
                                                        : static_cast<DWORD>(gta2::GetAlphaRef()));
    }
    // Tyre smoke: spawned above, aged and drawn here.
    DrawTyreSmoke(device, blending, blending ? 1u : static_cast<DWORD>(gta2::GetAlphaRef()));
    stageTimer.Mark();   // 8: lamps, skids, smoke (closed by the destructor otherwise)

    // The domes of the cars just drawn: each the car's own artwork over a rounded
    // grid, so one car is one 81-vertex mesh. Same alpha test as the sprites.
    if (!shells_.empty()) {
        static std::vector<uint16_t> domeIndices;
        if (domeIndices.empty()) {
            constexpr int n = kDomeSegments;
            for (int j = 0; j < n; ++j) {
                for (int i = 0; i < n; ++i) {
                    const uint16_t p00 = static_cast<uint16_t>(j * (n + 1) + i);
                    const uint16_t p10 = p00 + 1;
                    const uint16_t p01 = static_cast<uint16_t>(p00 + (n + 1));
                    const uint16_t p11 = p01 + 1;
                    // The body quad's own order, 0 1 2 / 0 2 3, so it faces the same way.
                    domeIndices.insert(domeIndices.end(), {p00, p10, p11, p00, p11, p01});
                }
            }
        }
        for (size_t shellIndex = 0; shellIndex < shells_.size(); ++shellIndex) {
            const CarShell& shell = shells_[shellIndex];
            IDirect3DTexture9* art = shellArt[shellIndex];
            if (!art) continue;
            D3DMATRIX world;
            memcpy(&world, shell.objectToWorld.m, sizeof(world));

            // With the Remix API, the dome is an instance with a material of its
            // own; the plain draw below is only the fallback.
            if (g_carMaterial) {
                IDirect3DTexture9* matArt = shellMatArt[shellIndex] ? shellMatArt[shellIndex] : art;
                const remixapi_MaterialHandle material = CarMaterialFor(matArt, shell.sprite);
                // Not yet loaded by Remix, and nothing earlier to stand in: the
                // flat body is drawn this frame instead.
                if (material && !shellWarm[shellIndex]) continue;
                const remixapi_MeshHandle mesh =
                    material ? CarMeshFor(shell.local, kDomeVertices, sizeof(Vertex), domeIndices,
                                          material)
                             : nullptr;
                if (mesh) {
                    remixapi_InstanceInfo instance = {};
                    instance.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO;
                    // The sprite's own alpha test, so the transparent margin of the
                    // sprite is cut away rather than drawn black. The compare
                    // operation is a Vulkan one: 6 is greater-or-equal.
                    remixapi_InstanceInfoBlendEXT alpha = {};
                    alpha.sType = REMIXAPI_STRUCT_TYPE_INSTANCE_INFO_BLEND_EXT;
                    alpha.alphaTestEnabled = 1;
                    alpha.alphaTestReferenceValue = static_cast<uint8_t>(
                        (std::max)(1, (std::min)(255, static_cast<int>(gta2::GetAlphaRef()))));
                    alpha.alphaTestCompareOp = 6;
                    alpha.alphaBlendEnabled = 0;
                    alpha.srcColorBlendFactor = 1;
                    alpha.dstColorBlendFactor = 0;
                    alpha.colorBlendOp = 0;
                    alpha.srcAlphaBlendFactor = 1;
                    alpha.dstAlphaBlendFactor = 0;
                    alpha.alphaBlendOp = 0;
                    alpha.writeMask = 0xFFFFFFFFu;
                    alpha.textureColorArg1Source = 1;
                    alpha.textureColorArg2Source = 0;
                    alpha.textureColorOperation = 3;
                    alpha.textureAlphaArg1Source = 1;
                    alpha.textureAlphaArg2Source = 0;
                    alpha.textureAlphaOperation = 1;
                    alpha.tFactor = 0xFFFFFFFFu;
                    alpha.isTextureFactorBlend = 0;
                    alpha.isVertexColorBakedLighting = 0;
                    instance.pNext = &alpha;
                    instance.mesh = mesh;
                    instance.doubleSided = 1;
                    for (int r = 0; r < 3; ++r) {
                        for (int c = 0; c < 4; ++c) instance.transform.matrix[r][c] = world.m[c][r];
                    }
                    if (RemixApi()->DrawInstance(&instance) == REMIXAPI_ERROR_CODE_SUCCESS) {
                        // The car's open doors and dents over it, and every door it
                        // has made ready for when one opens.
                        PaintLook look;
                        if (shellWarm[shellIndex] && HdFor(shell.sprite).ok &&
                            CarPaintLook(matArt, shell.sprite, &look)) {
                            PrewarmDoors(shell.sprite, look);
                            static std::vector<uint16_t> doorIndices;
                            if (doorIndices.empty()) {
                                constexpr int m = kDoorSegments;
                                for (int j = 0; j < m; ++j) {
                                    for (int i = 0; i < m; ++i) {
                                        const uint16_t p00 = static_cast<uint16_t>(j * (m + 1) + i);
                                        const uint16_t p01 = static_cast<uint16_t>(p00 + (m + 1));
                                        doorIndices.insert(doorIndices.end(),
                                                           {p00, static_cast<uint16_t>(p00 + 1),
                                                            static_cast<uint16_t>(p01 + 1), p00,
                                                            static_cast<uint16_t>(p01 + 1), p01});
                                    }
                                }
                            }
                            for (const CarShell::Door& door : shell.doors) {
                                if (g_ghostSwitch[kGhostHideDoors]) break;
                                const remixapi_MaterialHandle doorMaterial =
                                    DoorMaterialFor(*door.art, door.delta, shell.sprite, look, false);
                                if (!doorMaterial || !DoorMaterialWarm(*door.art, look)) continue;
                                const remixapi_MeshHandle doorMesh =
                                    CarMeshFor(door.local, kDoorVertices, sizeof(Vertex), doorIndices,
                                               doorMaterial);
                                if (doorMesh) DrawCutoutInstance(doorMesh, world);
                            }
                        }
                        continue;
                    }
                }
            }
            device->SetTransform(D3DTS_WORLD, &world);
            if (art != bound) {
                device->SetTexture(0, art);
                bound = art;
            }
            device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, kDomeVertices,
                                           static_cast<UINT>(domeIndices.size() / 3),
                                           domeIndices.data(), D3DFMT_INDEX16, shell.local,
                                           sizeof(Vertex));
        }
    }

    // Tyres: four dark boxes per car, the front pair turned. See SetCarWheels.
    if (g_carWheels && !shells_.empty()) {
        if (IDirect3DTexture9* rubber = TyreTexture(device)) {
            static std::vector<uint16_t> tyreIndices;
            if (tyreIndices.empty()) {
                for (int f = 0; f < 5; ++f) {
                    const uint16_t b = static_cast<uint16_t>(f * 4);
                    tyreIndices.insert(tyreIndices.end(), {b, static_cast<uint16_t>(b + 1),
                                                           static_cast<uint16_t>(b + 2), b,
                                                           static_cast<uint16_t>(b + 2),
                                                           static_cast<uint16_t>(b + 3)});
                }
            }
            device->SetTexture(0, rubber);
            bound = rubber;
            for (const CarShell& shell : shells_) {
                for (const gta2::Mat4& tyre : shell.tyres) {
                    D3DMATRIX world;
                    memcpy(&world, tyre.m, sizeof(world));
                    device->SetTransform(D3DTS_WORLD, &world);
                    device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, CarShell::kTyreVertices,
                                                   static_cast<UINT>(tyreIndices.size() / 3),
                                                   tyreIndices.data(), D3DFMT_INDEX16,
                                                   shell.tyreMesh, sizeof(Vertex));
                }
            }
        }
    }

    if (!effects.empty()) {
        // Additive, which is what this artwork was drawn for: it fades to black
        // on its way out, and black adds nothing. The rim disappears because it
        // stops being painted at all rather than because anything was cut out of
        // it, and the fireball ends up a glow over the scene the way it should.
        //
        // Remix treats additively blended draws as emissive particles, so this is
        // also the classification that gets a fireball to light the street rather
        // than sit on it as a flat decal.
        device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
        device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
        device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_ONE);
        // Still depth *tested*, so a fire behind a wall stays behind it, but not
        // depth written: a glow must not stop what is drawn after it.
        device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
        issue(effects, true);
        device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
        device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
        device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    }
    // Dark smoke off each flame, then everything already rising.
    // The smoke rate is per burning car, not per flame sprite: a car on fire shows many flame
    // sprites at once, and a puff for each of them piled up hundreds of quads.
    if (g_fire.smoke && !fireSpots.empty()) {
        std::vector<const void*> cars;
        for (const FireSpot& spot : fireSpots) {
            if (std::find(cars.begin(), cars.end(), spot.car) == cars.end()) cars.push_back(spot.car);
        }
        for (const void* car : cars) {
            std::vector<const FireSpot*> mine;
            for (const FireSpot& spot : fireSpots) {
                if (spot.car == car) mine.push_back(&spot);
            }
            const FireSpot& at = *mine[static_cast<size_t>(SkidRand() * static_cast<float>(mine.size())) % mine.size()];
            SpawnFireSmoke(at.x, at.y, at.z, at.size);
        }
    }
    if (g_fire.flames && !fireSpots.empty()) {
        // The rate is per burning car, shared out over the spots the game shows flame at.
        std::vector<const void*> burning;
        for (const FireSpot& spot : fireSpots) {
            if (std::find(burning.begin(), burning.end(), spot.car) == burning.end()) burning.push_back(spot.car);
        }
        for (const void* car : burning) {
            int spots = 0;
            for (const FireSpot& spot : fireSpots) spots += spot.car == car ? 1 : 0;
            for (const FireSpot& spot : fireSpots) {
                if (spot.car != car) continue;
                SpawnFlames(spot.x, spot.y, spot.z, spot.size, 1.0f / static_cast<float>(spots));
            }
        }
    }
    DrawScorch(device, blending, blending ? 1u : static_cast<DWORD>(gta2::GetAlphaRef()));
    DrawFlames(device, blending, blending ? 1u : static_cast<DWORD>(gta2::GetAlphaRef()));
    DrawFireSmoke(device, blending, blending ? 1u : static_cast<DWORD>(gta2::GetAlphaRef()));
    if (fxUpright) {
        // QB-19: fireball, flash, shock ring, sparks and the smoke column of every blast.
        ExplosionFxDraw(device, g_viewForward, kWorldFvf);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, blending ? TRUE : FALSE);
        device->SetRenderState(D3DRS_ALPHAREF, blending ? 1u : static_cast<DWORD>(gta2::GetAlphaRef()));
    }
    if (g_pedFigures && fxUpright) {
        ShotFxImpacts();
        ShotFxDraw(device, g_puffDt);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, blending ? TRUE : FALSE);
        device->SetRenderState(D3DRS_ALPHAREF, blending ? 1u : static_cast<DWORD>(gta2::GetAlphaRef()));
    }
    effectQuads_ = static_cast<int>(effects.size());
    g_effectBatches = effectQuads_;

    if (!boarders.empty() && width > 0 && height > 0) {
        // How bright the unlit layer is: full by day, dimmed to g_boardingUiNight as the sun
        // goes below the horizon.
        float elevation = 30.0f, rotation = 0.0f;
        TimeOfDayAngles(&elevation, &rotation);
        const float day = (std::max)(0.0f, (std::min)(1.0f, (elevation + 4.0f) / 24.0f));
        const float level = g_boardingUiNight + (1.0f - g_boardingUiNight) * day;
        const DWORD grey = static_cast<DWORD>(level * 255.0f + 0.5f);
        const DWORD colour = D3DCOLOR_ARGB(255, grey, grey, grey);

        struct UiVertex { float x, y, z, rhw; DWORD colour; float u, v; };
        constexpr DWORD kUiFvf = D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_TEX1;
        device->SetFVF(kUiFvf);
        device->SetRenderState(D3DRS_ZENABLE, D3DZB_FALSE);
        device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
        device->SetRenderState(D3DRS_SEPARATEALPHABLENDENABLE, TRUE);
        device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
        device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
        device->SetRenderState(D3DRS_SRCBLENDALPHA, D3DBLEND_ONE);
        device->SetRenderState(D3DRS_DESTBLENDALPHA, D3DBLEND_INVSRCALPHA);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
        device->SetRenderState(D3DRS_ALPHAFUNC, D3DCMP_GREATEREQUAL);
        device->SetRenderState(D3DRS_ALPHAREF, 1u);
        device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
        device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
        device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
        device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
        device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
        device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
        static const uint16_t kUiQuad[6] = {0, 1, 2, 0, 2, 3};
        static int uiLogged = 0;
        for (const Drawable& d : boarders) {
            const float (*w)[4] = d.sprite->objectToWorld.m;
            UiVertex out[4];
            bool ok = true;
            for (int i = 0; i < 4 && ok; ++i) {
                const Vertex& lv = d.sprite->local[i];
                float p[4] = {0, 0, 0, 1}, wv[4], vv[4], cv[4];
                for (int j = 0; j < 4; ++j) wv[j] = lv.x * w[0][j] + lv.y * w[1][j] + lv.z * w[2][j] + w[3][j];
                for (int j = 0; j < 4; ++j) vv[j] = wv[0] * view.m[0][j] + wv[1] * view.m[1][j] + wv[2] * view.m[2][j] + wv[3] * view.m[3][j];
                for (int j = 0; j < 4; ++j) cv[j] = vv[0] * projection.m[0][j] + vv[1] * projection.m[1][j] + vv[2] * projection.m[2][j] + vv[3] * projection.m[3][j];
                (void)p;
                if (cv[3] < 0.001f) { ok = false; break; }
                out[i].x = (cv[0] / cv[3] * 0.5f + 0.5f) * static_cast<float>(width) - 0.5f;
                out[i].y = (0.5f - cv[1] / cv[3] * 0.5f) * static_cast<float>(height) - 0.5f;
                out[i].z = 0.0f;
                out[i].rhw = 1.0f;
                out[i].colour = colour;
                out[i].u = lv.u;
                out[i].v = lv.v;
            }
            if (!ok) continue;
            if (uiLogged < 40) {
                ++uiLogged;
                Log("boarding UI: pedestrian quad at %.0f,%.0f to %.0f,%.0f of %dx%d, level %.2f, %zu in all",
                    out[0].x, out[0].y, out[2].x, out[2].y, width, height, level, boarders.size());
            }
            const D3DTEXTUREFILTERTYPE filter = d.enlarged ? D3DTEXF_LINEAR : D3DTEXF_POINT;
            device->SetSamplerState(0, D3DSAMP_MAGFILTER, filter);
            device->SetSamplerState(0, D3DSAMP_MINFILTER, filter);
            device->SetTexture(0, d.texture);
            UiVertex list[6];
            for (int i = 0; i < 6; ++i) list[i] = out[kUiQuad[i]];
            device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 2, list, sizeof(UiVertex));
        }
        device->SetRenderState(D3DRS_SEPARATEALPHABLENDENABLE, FALSE);
        device->SetRenderState(D3DRS_ZENABLE, D3DZB_TRUE);
        device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
        device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
        device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
        device->SetFVF(kWorldFvf);
        drops_.drawn += static_cast<int>(boarders.size());
    }

    device->SetTexture(0, nullptr);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    // Left as we found it, so the next pass that assumes a world matrix - and the
    // static mesh does - is not drawing at the last sprite's position.
    const gta2::Mat4 identity = gta2::Identity();
    memcpy(&matrix, identity.m, sizeof(matrix));
    device->SetTransform(D3DTS_WORLD, &matrix);
}

void LiveGeometry::ReleaseResources() {
    sprites_.clear();
    shells_.clear();
    ReleaseCarMaterials();
    ReleaseLampTextures();
    g_lampDevice = nullptr;
    ReleaseSmoothTextures();
    g_smoothDevice = nullptr;
    ReleaseHdLogos();
    g_hdLogoDevice = nullptr;
    ReleaseSkidTextures();
    ClearSkidGhosts();
    g_skidDevice = nullptr;
    g_puffs.clear();
    g_skidSeen.clear();
    ReleaseTyreTexture();
    g_steer.clear();
    spriteQuads_ = 0;
    effectQuads_ = 0;
    // The shapes are keyed by texture record, and a new level hands out new ones.
    g_shapes.clear();
}

}  // namespace gta2dx9

namespace gta2dx9 {
void ShotLightsSubmit() {
    for (size_t i = 0; i < g_shotLights.size();) {
        if (g_carFrame - g_shotLights[i].frame > 1) { g_shotLights[i] = g_shotLights.back(); g_shotLights.pop_back(); continue; }
        LightsSubmitExtra(g_shotLights[i].desc);
        ++i;
    }
}
const char* WeaponName(int weapon) {
    return weapon > 0 && weapon < kWpnCount ? kWeapons[weapon].name : (weapon == 0 ? "none" : "?");
}
uint32_t LiveDrawFrame() { return g_carFrame; }
}  // namespace gta2dx9
