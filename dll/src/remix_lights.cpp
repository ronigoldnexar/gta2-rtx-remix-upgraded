#include "remix_lights.h"

#include "ground.h"
#include "live_geometry.h"   // SetCarLamps (FIX-REMIX-NIGHT-8 probe)
#include "log.h"
#include "model_store.h"
#include "remix_api.h"
#include "time_of_day.h"
#include "synthetic_lights.h"
#include "vehicle_fx.h"
#include "world_view.h"   // StreetPresentation (FIX-REMIX-3)

#include "../../src/gta2_map.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <array>
#include <initializer_list>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unordered_map>
#include <unordered_set>

namespace gta2dx9 {
extern float g_lastEye[3];   // defined below (the eye the far lamps are chosen from)
extern bool g_haveEye;
namespace {

RemixLightSettings g_settings;
const GroundSampler* g_ground = nullptr;
std::unordered_set<uint64_t> g_mapLights;   // MapLightKey of every lamp in the map file
std::unordered_set<uint64_t> g_listedMapKeys;   // the map lamps the game listed in its last list
struct MapLampRecord { float pos[3]; float rgb[3]; float intensity; float radius; uint64_t key; };
std::vector<MapLampRecord> g_mapLampRecords;   // every steady lamp of the map file, decoded like the game's
int g_farLampsLastFrame = 0;
float g_farLampWeight = 0.0f;   // this frame's fade of the far lamps (0 when none were submitted)
int g_probeMask = 0;              // [devtools] remix_lights_probe (see GameClassDaylight)
int g_trafficLiftMilli = 650;     // [devtools] remix_traffic_lift_milli (FIX-REMIX-NIGHT-5; default 650 since FIX-REMIX-NIGHT-6, frn6_p6)
int g_lowBounceWarm = 1;          // [devtools] remix_low_bounce_warm (FIX-REMIX-NIGHT-5)
int g_wideNeonTenths = -1;       // [devtools] remix_wide_neon_tenths (-1 = the setting wideNeonRadius, 0 = off)
int g_poolGainPct = -1;          // LIGHTING-V1 [devtools] remix_pool_gain_pct: the lamp pools' strength, % of kLampPoolGain (-1 = kPoolGainDefaultPct)
int g_poolCone = -1;             // [devtools] remix_pool_cone: PoolConeDegrees, live (-1 = the setting, 0 = sphere)
int g_nightFillMilli = -1;       // [devtools] remix_night_fill_milli: NightSkyFill x1000, live (-1 = the setting)
int g_dayFillMilli = -1;        // [devtools] remix_day_fill_milli: DayBounceFill x1000, live (-1 = the setting, 0 = off)
int g_sodiumWhite = 1;          // [devtools] remix_sodium_white=0: sodium map lights keep #FF8000 in the street views (A/B)
// FIX-REMIX-NIGHT-7 (prmx bil night olive wash): live tuning of the night palette, milli per channel / percent.
// [devtools] remix_moon_rgb=R,G,B (x1000): the night sky fill's colour; remix_sodium_rgb=R,G,B: the street views'
// sodium amber; remix_sodium_pct: the sodium lamps' strength in the street views. Absent = the compiled defaults.
float g_moonRgb[3] = {0.36f, 0.48f, 1.0f};
int g_moonFillMilli = -1;        // [devtools] remix_moon_fill_milli: the night's moon fill x1000 (-1 = 140, 0 = the NIGHT-6 fill)
float g_sodiumRgb[3] = {1.0f, 0.74f, 0.46f};
int g_sodiumPct = 100;
int g_windowPct = 100;           // [devtools] remix_window_pct: lit-window room lights, % of default (0 = off; FIX-REMIX-NIGHT-6)
int g_windowOutMilli = 250;
int g_signFloodPct = 100;        // [devtools] remix_sign_flood_pct: wil rooftop sign plates floodlit at night, % (0 = off; FIX-REMIX-NIGHT-7)
int g_gantryPct = 100;           // [devtools] remix_gantry_pct: the wil gantry signal lenses' night glow, % (0 = off; FIX-REMIX-NIGHT-6)      // [devtools] remix_window_out_milli: how far in front of the pane they hang (tiles x1000)
int g_trafficOld = 0;            // [devtools] remix_traffic_old=1: the junction signals as before (A/B)
int g_trafficPct = 35;           // [devtools] remix_traffic_pct: a signal's light at night, % of the old
int g_trafficDayPct = 10;        // [devtools] remix_traffic_day_pct: by day, % of the night's
int g_signLights = 1;
int g_signWall = 1;              // [devtools] remix_sign_wall: a sign light on a wall shines away from it (FIX-REMIX-NIGHT-6)
int g_signRedPct = 35;           // [devtools] remix_sign_red_pct: share of the sign's own colour kept by the warm-white rule (frn6_p7)

int g_duskFillDeg = -1;          // [devtools] remix_dusk_fill_deg: DuskFillDegrees, live (-1 = the setting, 0 = off)            // [devtools] remix_sign_lights=0: red/pink map lights as sodium lamps again (A/B)
bool g_reliftPending = false;

uint64_t MapLightKey(uint32_t x, uint32_t y, uint32_t z) {
    return static_cast<uint64_t>(x) | static_cast<uint64_t>(y) << 16 | static_cast<uint64_t>(z) << 32;
}

// Whether a light stands exactly where the map file puts one of its lamps. The
// game's positions are the file's 1/128 units converted exactly, so a map lamp
// matches to the bit and nothing else lands on one by chance.
bool MapLightKeyOf(const float* pos, uint64_t* key) {
    // Back from the mesh axes to the game's: x east, y south, z up.
    const float game[3] = {pos[0], static_cast<float>(gta2::kMapHeight) - pos[2], pos[1]};
    uint32_t units[3];
    for (int i = 0; i < 3; ++i) {
        const float u = game[i] * 128.0f;
        if (u < 0.0f || u > 65535.0f || u != std::floor(u)) return false;
        units[i] = static_cast<uint32_t>(u);
    }
    *key = MapLightKey(units[0], units[1], units[2]);
    return true;
}

bool IsMapLight(const float* pos) {
    uint64_t key = 0;
    return MapLightKeyOf(pos, &key) && g_mapLights.count(key) != 0;
}

// Half the map's lights are inside the ground.
//
// The maps put a lamp at the middle of the block whose lid is the street, half
// a block *under* the road: in ste.gmp the white street lamps along x 182 stand
// at z 1.5 on a road at 2.0, and about half of all map lights in every district
// sit like that. The original renderer never noticed - it lights each vertex by
// its distance to the light (d3ddll.dll!FUN_00E02A80) and nothing in between
// counts - so the road above was lit all the same. A path tracer finds the lid
// in the way and the lamp lights nothing.
//
// So a map lamp inside a block that has a lid above it is put
// g_settings.buriedLift above that lid instead - by default a tile, which
// spreads it into a softer pool than the hard disc a lamp just off the road
// makes. A light in open air is never moved. Only the block the light is in
// counts, so a bridge or a roof a storey up does not pull a lamp onto it.
//
// What is overhead does count: under an overpass a tile up can be inside the
// deck, with the lamp's sphere showing through its sides. There the light goes
// no higher than kUndersideClearance below the underside. A gap lower than
// kMinimumGap is no gap: the lamp is inside a wall or a building that stands on
// the surface, lifting cannot get it out, and it is left where the map put it.
//
// Done where a light is described to Remix, not where the game lists it: the
// tracking works on the game's own positions, which do not change when the
// floors arrive a frame after the first lights or when the lift is retuned - a
// lamp that seemed to move would be taken for a car's. And only to the map's
// own lamps (IsMapLight): a car's lamps sit on the road, and on a ramp or next
// to a partial block our floor can read a hair above them.
constexpr float kUndersideClearance = 0.25f;
constexpr float kMinimumGap = 0.5f;

void LiftOutOfGround(float x, float* y, float z) {
    if (g_settings.buriedLift <= 0.0f || !g_ground || !g_ground->Ready()) return;
    const float level = std::floor(*y);
    float surface = 0.0f;
    if (!g_ground->SurfaceAt(x, z, level + 1.0f, &surface)) return;
    if (surface <= *y || surface < level) return;

    float lifted = surface + g_settings.buriedLift;
    float underside = 0.0f;
    if (g_ground->UndersideAbove(x, z, surface, &underside)) {
        if (underside - surface < kMinimumGap) return;
        const float highest = underside - kUndersideClearance;
        if (lifted > highest) lifted = highest;
    }
    *y = lifted;
}

// The street lamps of the ground views stand on a post (DrawProps, LampPostScale)
// whose lantern is drawn opaque, as everything through D3D9 is to Remix: the map
// puts the lamp at the bulb, inside the glass, and the glass, the dish under it and
// the roof over it shut the light in. The glass glowed and nothing under the lamp
// was lit (defect pt-remix-lamp-posts-cast-no-light). So for a map lamp with a post
// under it the lamp's own sphere is shrunk to fit inside the glass (the lantern
// still glows), and a second sphere just under the dish lights the post, the
// pavement and the road: the pool. Its sphere is smaller than the lamps' default
// emitter, and Remix's radiance is per area of the emitter, so it burns hotter by
// the area ratio to give the power a lamp of the default size gives.
// Where DrawProps moved the post off the lamp to a kerb or a wall (MapLampPosts),
// the lamp itself is put out and the glow and the pool both go to the moved lantern.
constexpr float kLampPoolEmitter = 0.12f;          // tiles; less on a short post
constexpr float kLampPoolGap = 0.01f;              // between the dish and the sphere
// The pool's power over a default-size lamp's: it hangs 1-3 tiles over the paving where
// the facade lamps sit half a tile from their wall, and at 1x (fxr_lamp_after) the post
// was lit and the paving under it barely.
constexpr float kLampPoolGain = 4.0f;
// LIGHTING-V1 (gate B, owner: "the street lamps barely make pools"): the pools at this share of kLampPoolGain by default.
constexpr int kPoolGainDefaultPct = 350;   // lt_b1_rmx: 100 / 200 / 350 / 350 + sodium 150; 350 lays a clear warm pool round each post
int g_lampPoolsLastFrame = 0;

std::vector<RemixLightDesc>            g_working;     // forward: FitLampsToPosts works on this frame's set
void FitLampsToPosts();

std::vector<RemixTrackedLight>         g_tracked;
std::vector<RemixLightDesc>            g_pending;     // this frame's list, as the game gave it
std::vector<RemixLightDesc>            g_extra;       // this frame's invented lights
std::map<uint64_t, RemixLightOverride> g_overrides;   // ordered: the menu lists these

RemixLightStats g_stats;
RemixLightSettings g_applied;      // what the tracked lights were last built from
uint32_t g_settingsDirtyAt = 0;

uint32_t g_frame = 0;
uint32_t g_collects = 0;           // gbh_ResetLights calls seen
uint32_t g_collectsAtLastReconcile = 0;
uint32_t g_framesSinceCollect = 0;
bool     g_collecting = false;

float    g_ambient = 0.0f;
uint64_t g_identify = 0;
uint64_t g_nextId = 1;
uint64_t g_sceneSalt = 0;
char     g_sceneName[64] = "";

bool g_overridesDirty = false;
char g_overridePath[MAX_PATH] = "gta2dx9_lights.ini";

void* g_ambientHandle = nullptr;
const uint64_t kAmbientFillId = 0xA33B1E27F111ULL;

// A light the game stopped listing is gone, but a frame of slack keeps one that
// arrives slightly out of step from flickering. GTA2 lists its lights once per
// world render; menus and load screens list none at all, and those must expire.
const uint32_t kExpireFrames = 2;

// How far a light may move between frames and still be recognised as the same
// one. A car at full speed covers well under a tile per frame; two lamps that
// close together are indistinguishable anyway.
const float kMoveMatchDistance = 3.0f;

// Radiance the identify highlight burns at - findable in a lit street without
// washing the street out.
const float kIdentifyRadiance = 40.0f;

uint64_t HashBytes(const void* data, size_t size, uint64_t seed = 0xCBF29CE484222325ULL) {
    const uint8_t* p = static_cast<const uint8_t*>(data);
    uint64_t h = seed;
    for (size_t i = 0; i < size; ++i) {
        h ^= p[i];
        h *= 0x100000001B3ULL;
    }
    return h;
}

// Positions come from the game's 16.14 fixed point, so they are exact; the
// quantisation is only insurance against a float round-trip.
int64_t Quantise(float v) { return static_cast<int64_t>(std::floor(v * 256.0f + 0.5f)); }

// Identity that survives a restart: where the light stands, how far it reaches,
// and which district it is in. Deliberately not the colour - a traffic light
// keeps its identity through red, amber and green.
uint64_t StableKey(const RemixLightDesc& d) {
    int64_t parts[4] = {Quantise(d.pos[0]), Quantise(d.pos[1]), Quantise(d.pos[2]),
                        Quantise(d.radius)};
    return HashBytes(parts, sizeof(parts), g_sceneSalt ? g_sceneSalt : 0xCBF29CE484222325ULL);
}

// Match key for the current frame: position alone. Static lights never move, so
// this pairs them up exactly; anything left over is matched by proximity.
uint64_t PositionKey(const RemixLightDesc& d) {
    int64_t parts[3] = {Quantise(d.pos[0]), Quantise(d.pos[1]), Quantise(d.pos[2])};
    return HashBytes(parts, sizeof(parts));
}

bool SameColourAndRadius(const RemixLightDesc& a, const RemixLightDesc& b) {
    return a.source == b.source && a.rgb[0] == b.rgb[0] && a.rgb[1] == b.rgb[1]
        && a.rgb[2] == b.rgb[2] && a.radius == b.radius;
}

bool SameDesc(const RemixLightDesc& a, const RemixLightDesc& b) {
    return SameColourAndRadius(a, b) && a.intensity == b.intensity && a.pos[0] == b.pos[0]
        && a.pos[1] == b.pos[1] && a.pos[2] == b.pos[2] && a.spot == b.spot
        && a.coneAngleDeg == b.coneAngleDeg && a.dir[0] == b.dir[0] && a.dir[1] == b.dir[1]
        && a.dir[2] == b.dir[2] && a.emitterRadius == b.emitterRadius
        && a.coneSoftness == b.coneSoftness;
}

float DistanceSquared(const float* a, const float* b) {
    const float dx = a[0] - b[0], dy = a[1] - b[1], dz = a[2] - b[2];
    return dx * dx + dy * dy + dz * dz;
}

remixapi_Float3D ToRemix(const float* v) {
    remixapi_Float3D out;
    out.x = v[0];
    out.y = v[1];
    out.z = v[2];
    return out;
}

void DestroyHandle(void*& handle) {
    if (!handle) return;
    if (const remixapi_Interface* api = RemixApi()) {
        api->DestroyLight(static_cast<remixapi_LightHandle>(handle));
    }
    handle = nullptr;
    ++g_stats.destroyed;
}

void ClearAll() {
    for (RemixTrackedLight& t : g_tracked) {
        DestroyHandle(t.handle);
        t.drawn = false;
    }
    g_tracked.clear();
    DestroyHandle(g_ambientHandle);
}

// Remix derives a light's handle from the hash in its info and overwrites a
// matching entry, so redefining a light means describing it again under the same
// hash. There is no update call, and destroying first would remove the very
// light being redefined - the light would blink out for a frame.
// Defined further down, next to the per-frame cache it reads; declared here
// because Apply is the first thing that wants it.
float GameClassDaylight(uint8_t klass);
float LightDaylight(const RemixTrackedLight& t);   // LIGHTING-V1: per light, staggered

// A sodium/amber lamp's colour: red leads and green is well up and clear of blue (#FF8000,
// #FF8040, #FF9224, #FFFF00). A pure or pinkish red (#FF0000, #FF8080) is not.
// A junction signal drawn the street views' way (see Describe).
bool TrafficShaped(const RemixTrackedLight& t) {
    return !g_trafficOld && t.def.source == kLightSourceGame && !t.moving && t.gameClass == kGameLightTraffic &&
           StreetPresentation();
}

bool SodiumLike(const float* rgb) {
    return rgb[0] > 0.0f && rgb[1] >= 0.3f * rgb[0] && rgb[1] - rgb[2] >= 0.15f * rgb[0];
}

// Where a tracked light goes, its colour and the factor its colour is scaled by
// (everything Apply describes to Remix but the emitter shape). Shared with the
// strongest-lights log.
// FIX-REMIX-NIGHT-6 (pt-remix-night-red-neon-sign-floods-courtyard-saturated-red, triage pass 194 residual): the map
// puts a sign's light in front of the sign (wil JESUS SAVES: the letters are the flat faces 742/743 on the y = 139
// plane, its #FF0000 r 5 light 1.5 tiles south of them at 160.01,140.50,3.5). Once the wide-sign rule made that light
// warm white it lit the letters themselves white from the front, and they read pale pink-white over their red
// emission (triage tri14_rxw). A sign or neon map light with a lit-sign face (the curated emissive sign tiles of
// tools/remix_emissive.py, ids only) within kSignWallReach is turned into a half-space lamp shining away from that
// sign (out and a little down, 80 deg either side): the street in front is lit as before, the letters only by their
// own emission. The light also moves kSignWallOut further from the sign. [devtools] remix_sign_wall=0: as before.
constexpr float kSignWallReach = 2.0f;
constexpr float kSignWallOut = 0.12f;
struct SignTiles { const char* style; std::initializer_list<int> tiles; };
const SignTiles kSignTiles[] = {
    {"wil", {566, 574, 728, 729, 730, 739, 742, 743, 754, 756, 759, 760, 761, 763, 764, 767, 782, 825, 826, 827}},
    {"bil", {384, 385, 386, 387, 389, 390, 392, 394, 395, 396, 397, 398, 399, 400, 401, 402, 403, 404, 405, 406, 407, 408,
             409, 410, 411, 412, 413, 414, 415}},
    {"ste", {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 27, 28, 29, 30, 31, 345, 347, 363,
             372, 374}},
};
bool IsSignTile(int tile) {
    for (const SignTiles& s : kSignTiles) {
        if (strcmp(s.style, g_sceneName) != 0) continue;
        for (int t : s.tiles) if (t == tile) return true;
    }
    return false;
}
bool SignWallNormal(const RemixTrackedLight& t, float* normal) {
    if (!g_signWall || t.def.source != kLightSourceGame || t.moving || !StreetPresentation()) return false;
    if (!(t.gameClass == kGameLightNeon || (g_signLights && t.gameClass == kGameLightStreet && !SodiumLike(t.def.rgb)))) return false;
    const gta2::Map* map = g_ground && g_ground->Ready() ? g_ground->MapData() : nullptr;
    if (!map) return false;
    const float gx = t.def.pos[0], gy = static_cast<float>(gta2::kMapHeight) - t.def.pos[2];
    const int level = static_cast<int>(std::floor(t.def.pos[1]));
    normal[0] = normal[1] = normal[2] = 0.0f;
    float best = kSignWallReach;
    const int cx = static_cast<int>(std::floor(gx)), cy = static_cast<int>(std::floor(gy));
    auto sign = [](const gta2::Face& f) { return f && IsSignTile(f.Tile()); };
    for (int lv = level - 1; lv <= level + 1; ++lv) {
        auto at = [&](int x, int y) -> const gta2::Block* {
            if (x < 0 || y < 0 || x >= gta2::kMapWidth || y >= gta2::kMapHeight) return nullptr;
            const gta2::Column& c = map->ColumnAt(x, y);
            const int i = lv - c.offset;
            if (i < 0 || i >= static_cast<int>(c.blocks.size()) || c.blocks[static_cast<size_t>(i)] >= map->BlockCount()) return nullptr;
            return &map->BlockAt(c.blocks[static_cast<size_t>(i)]);
        };
        // Sign faces on the planes x = cx+1+k / cx-k and y = cy+1+k / cy-k, within a tile either side across.
        for (int k = 0; k <= 1; ++k) {
            for (int side = -1; side <= 1; ++side) {
                for (int e = 0; e < 2; ++e) {
                    const int p = e == 0 ? cx + 1 + k : cx - k;
                    const float dx = std::fabs(static_cast<float>(p) - gx), across = side == 0 ? 0.0f : std::fabs(cy + 0.5f + side - gy) - 0.5f;
                    const float d = std::sqrt(dx * dx + (across > 0.0f ? across * across : 0.0f));
                    if (d >= best) continue;
                    const gta2::Block* west = at(p - 1, cy + side);
                    const gta2::Block* east = at(p, cy + side);
                    if ((west && sign(west->right)) || (east && sign(east->left))) { best = d; normal[0] = e == 0 ? -1.0f : 1.0f; normal[2] = 0.0f; }
                }
                for (int e = 0; e < 2; ++e) {
                    const int p = e == 0 ? cy + 1 + k : cy - k;
                    const float dy = std::fabs(static_cast<float>(p) - gy), across = side == 0 ? 0.0f : std::fabs(cx + 0.5f + side - gx) - 0.5f;
                    const float d = std::sqrt(dy * dy + (across > 0.0f ? across * across : 0.0f));
                    if (d >= best) continue;
                    const gta2::Block* north = at(cx + side, p - 1);   // its bottom (south) face is on the plane
                    const gta2::Block* south = at(cx + side, p);       // its top (north) face is on the plane
                    // The normal points from the sign to the light: a sign south of it (game +y) -> north, renderer +Z.
                    if ((north && sign(north->bottom)) || (south && sign(south->top))) { best = d; normal[0] = 0.0f; normal[2] = e == 0 ? 1.0f : -1.0f; }
                }
            }
        }
    }
    {
        static int logged = 0;
        if (logged < 24 && (normal[0] != 0.0f || normal[2] != 0.0f)) {
            ++logged;
            Log("remix lights: sign light at %.2f,%.2f,%.2f (game %.2f,%.2f) faces away from its sign %.2f tile off, normal %.0f,%.0f",
                t.def.pos[0], t.def.pos[1], t.def.pos[2], gx, gy, best, normal[0], normal[2]);
        }
    }
    return normal[0] != 0.0f || normal[2] != 0.0f;
}

void Describe(const RemixTrackedLight& t, float* pos, float* rgb, float* scaleOut) {
    const RemixLightOverride* ov = LightsFindOverride(t.key);
    const bool identified = t.key != 0 && t.key == g_identify;
    pos[0] = t.def.pos[0]; pos[1] = t.def.pos[1]; pos[2] = t.def.pos[2];
    if (t.def.source == kLightSourceGame && !t.moving && IsMapLight(pos)) {
        LiftOutOfGround(pos[0], &pos[1], pos[2]);
    }
    for (int i = 0; i < 3; ++i) {
        pos[i] += ov ? ov->offset[i] : 0.0f;
        rgb[i] = (ov && ov->recolor) ? ov->color[i] : t.def.rgb[i];
    }
    {
        float n[3];
        if (SignWallNormal(t, n)) { pos[0] += n[0] * kSignWallOut; pos[2] += n[2] * kSignWallOut; }
    }

    // The game's radius is the light's reach, not its size. Feeding it to the
    // emitter radius would put a glowing ball the width of the street around
    // every lamp, so it drives brightness instead and the path tracer's own
    // inverse-square falloff replaces GTA2's linear ramp and hard cutoff.
    float scale = t.def.intensity * g_settings.radianceScale;
    if (t.def.radius > 0.0f && g_settings.referenceRadius > 0.0f
        && g_settings.radiusExponent != 0.0f) {
        scale *= std::pow(t.def.radius / g_settings.referenceRadius, g_settings.radiusExponent);
    }
    if (t.moving) scale *= g_settings.movingScale;
    if (ov) scale *= ov->intensity;
    // Dusk and dawn. Only the game's own lights are gated here; ours are scaled
    // where they are submitted, in synthetic_lights.cpp.
    if (t.def.source == kLightSourceGame) scale *= LightDaylight(t);

    // A wide coloured map light: warm white at the same luminance (see
    // wideNeonRadius in remix_lights.h). An override's own colour wins.
    // FIX-REMIX-NIGHT-2 (pt-remix-night-red-neon-sign-floods-courtyard-saturated-red): in the street
    // views a red or pink map light (#FF0000, #FF8080: r leads, g and b level) is a sign, not a sodium
    // lamp; ClassifyGameLight's r >= g >= b test called it Street, so a radius-5 red light kept its
    // full red over the Wil courtyard's walls and stairs. The classic view keeps the game's classes.
    const bool signLike = t.gameClass == kGameLightNeon ||
                          (g_signLights && t.gameClass == kGameLightStreet && StreetPresentation() && !SodiumLike(t.def.rgb));
    // [devtools] remix_wide_neon_tenths (FIX-REMIX-NIGHT-5): the threshold live, 0 = the rule off (the
    // look before f9d219f, for the traffic-slab repro), -1 = the setting.
    const float wideNeon = g_wideNeonTenths >= 0 ? (g_wideNeonTenths > 0 ? g_wideNeonTenths / 10.0f : 0.0f) : g_settings.wideNeonRadius;
    if (t.def.source == kLightSourceGame && !t.moving && signLike &&
        wideNeon > 0.0f && t.def.radius >= wideNeon &&
        !(ov && ov->recolor)) {
        static const float kWarm[3] = {1.0f, 0.80f, 0.58f};
        const float lumaWarm = 0.2126f * kWarm[0] + 0.7152f * kWarm[1] + 0.0722f * kWarm[2];
        const float luma = 0.2126f * rgb[0] + 0.7152f * rgb[1] + 0.0722f * rgb[2];
        // [devtools] remix_sign_red_pct (FIX-REMIX-NIGHT-6): keep this share of the sign's own colour (same luminance).
        const float keep = static_cast<float>(g_signRedPct < 0 ? 0 : (g_signRedPct > 100 ? 100 : g_signRedPct)) / 100.0f;
        float own[3];
        for (int i = 0; i < 3; ++i) own[i] = rgb[i];
        for (int i = 0; i < 3; ++i) rgb[i] = (1.0f - keep) * kWarm[i] * luma / lumaWarm + keep * own[i];
    }

    // FIX-REMIX-NIGHT-4 (pt-remix-night-wall-flat-pure-orange-wash-blue-channel-zero): the map's sodium
    // lamps are #FF8000 (blue exactly 0). Under a path tracer that is a monochrome light: a wall it reaches
    // keeps only its red and green, every texel lands on one orange line (B = 0) and the brick reads as a
    // flat orange slab beside walls no lamp reaches. A real high-pressure sodium lamp has a broad spectrum
    // (a warm amber white), so in the street views it is that amber at the light's own luminance, and its
    // lamp-post pool with it. [devtools] remix_sodium_white=0: the game's colour (same-session A/B).
    if (g_sodiumWhite && t.def.source == kLightSourceGame && !t.moving && StreetPresentation() &&
        SodiumLike(t.def.rgb) && !(ov && ov->recolor)) {
        const float* kAmber = g_sodiumRgb;
        const float lumaAmber = 0.2126f * kAmber[0] + 0.7152f * kAmber[1] + 0.0722f * kAmber[2];
        const float luma = 0.2126f * rgb[0] + 0.7152f * rgb[1] + 0.0722f * rgb[2];
        for (int i = 0; i < 3; ++i) rgb[i] = kAmber[i] * luma / lumaAmber;
        scale *= static_cast<float>(g_sodiumPct) / 100.0f;
    }

    // FIX-REMIX-NIGHT-2 (pt-remix-traffic-light-green-wash-slab-and-grainy-red-crosswalk-pool): in
    // the street views a junction signal is a small lamp shining down at the road (Apply gives it the
    // cone), not a bare sphere of pure green that washed the facade beside it flat and threw a grainy
    // red disc on the crossing: a third of the power at night, a tenth of that by day (the lens is
    // what reads by day), and its colour pulled a third of the way to white.
    if (TrafficShaped(t)) {
        // FIX-REMIX-NIGHT-5: the game builds a signal's light at the post's foot, so the cone's apex sat on the
        // asphalt and every phase threw a hot core onto the crossing (ste 108.0,117.4, frn5_p4: an amber disc
        // blown white in its middle). In the street views it shines from head height on the post, the pool
        // spread and even under it. [devtools] remix_traffic_lift_milli (tiles x1000; 0 = at the foot).
        pos[1] += static_cast<float>(g_trafficLiftMilli) / 1000.0f;
        DaylightGate gate;
        gate.enabled = true;
        const float night = DaylightGateFactor(gate);
        const float day = static_cast<float>(g_trafficDayPct) / 100.0f;
        scale *= static_cast<float>(g_trafficPct) / 100.0f * (day + (1.0f - day) * night);
        const float luma = 0.2126f * rgb[0] + 0.7152f * rgb[1] + 0.0722f * rgb[2];
        for (int i = 0; i < 3; ++i) rgb[i] = luma + (rgb[i] - luma) * 0.67f;
    }

    // Pull towards luminance rather than towards grey: mixing in white would
    // brighten as it desaturates, and every light would drift lighter as the
    // slider comes down.
    if (g_settings.saturation != 1.0f) {
        const float luma = 0.2126f * rgb[0] + 0.7152f * rgb[1] + 0.0722f * rgb[2];
        for (int i = 0; i < 3; ++i) {
            rgb[i] = luma + (rgb[i] - luma) * g_settings.saturation;
            if (rgb[i] < 0.0f) rgb[i] = 0.0f;   // saturation above 1 can overshoot
            if (rgb[i] > 1.0f) rgb[i] = 1.0f;
        }
    }

    if (identified) {
        rgb[0] = 1.0f; rgb[1] = 0.0f; rgb[2] = 1.0f;
        scale = kIdentifyRadiance;
    }

    *scaleOut = scale;
}

void Apply(RemixTrackedLight& t) {
    const remixapi_Interface* api = RemixApi();
    if (!api) return;
    const RemixLightOverride* ov = LightsFindOverride(t.key);
    float pos[3], rgb[3], scale = 0.0f;
    Describe(t, pos, rgb, &scale);

    float emitter = (ov && ov->emitterRadius > 0.0f)  ? ov->emitterRadius
                    : t.def.emitterRadius > 0.0f      ? t.def.emitterRadius
                                                      : g_settings.emitterRadius;

    remixapi_LightInfo info = {};
    info.sType = REMIXAPI_STRUCT_TYPE_LIGHT_INFO;
    info.hash = t.id;
    info.radiance = remixapi_Float3D{rgb[0] * scale, rgb[1] * scale, rgb[2] * scale};
    // Remix puts a light it considers static to sleep after a few frames, as a
    // defence against games that ramp intensity every frame. GTA2's street lamps
    // genuinely never move, which is exactly the case that would silently go
    // dark, so every light is declared dynamic.
    info.isDynamic = 1;

    remixapi_LightInfoSphereEXT sphere = {};
    sphere.sType = REMIXAPI_STRUCT_TYPE_LIGHT_INFO_SPHERE_EXT;
    sphere.position = ToRemix(pos);
    sphere.radius = emitter;
    sphere.volumetricRadianceScale = 1.0f;
    // A headlight is a cone, not a bare bulb. Remix calls that shaping, and it
    // is the one thing here the game's own light model had no way to express.
    if (TrafficShaped(t)) {
        // Down and out over the road, 75 degrees either side of straight down, soft edged.
        sphere.shaping_hasvalue = 1;
        sphere.shaping_value.direction = remixapi_Float3D{0.0f, -1.0f, 0.0f};
        sphere.shaping_value.coneAngleDegrees = 75.0f;
        sphere.shaping_value.coneSoftness = 0.5f;
        sphere.shaping_value.focusExponent = 0.0f;
    } else if (float n[3]; SignWallNormal(t, n)) {
        // Away from the wall the sign hangs on, a little down, 80 degrees either side (see SignWallNormal).
        sphere.shaping_hasvalue = 1;
        sphere.shaping_value.direction = ToRemix(std::array<float, 3>{n[0] * 0.94f, -0.34f, n[2] * 0.94f}.data());
        sphere.shaping_value.coneAngleDegrees = 80.0f;
        sphere.shaping_value.coneSoftness = 0.3f;
        sphere.shaping_value.focusExponent = 0.0f;
    } else if (t.def.spot) {
        sphere.shaping_hasvalue = 1;
        sphere.shaping_value.direction = ToRemix(t.def.dir);
        sphere.shaping_value.coneAngleDegrees = t.def.coneAngleDeg;
        sphere.shaping_value.coneSoftness =
            t.def.coneSoftness >= 0.0f ? t.def.coneSoftness : g_settings.coneSoftness;
        sphere.shaping_value.focusExponent = 0.0f;
    }
    info.pNext = &sphere;
    // GTA2DX9_LOG_HEADLIGHTS=1 (FIX-REMIX-NIGHT-8 diagnostic): every 128th headlight apply, what Remix is given.
    static int logHead = -1;
    if (logHead < 0) { const char* e = getenv("GTA2DX9_LOG_HEADLIGHTS"); logHead = e && *e == '1' ? 1 : 0; }
    if (logHead && t.def.source == kLightSourceHeadlight) {
        const float ex = pos[0] - g_lastEye[0], ez = pos[2] - g_lastEye[2];
        if (g_haveEye && (!t.handle || (g_frame & 63) == 0) && ex * ex + ez * ez < 36.0f)
            Log("remix headlight: pos %.2f,%.2f,%.2f (remix %.2f,%.2f,%.2f) radiance %.1f,%.1f,%.1f emitter %.3f cone %d dir %.2f,%.2f,%.2f angle %.1f moving %d",
                pos[0], pos[1], pos[2], sphere.position.x, sphere.position.y, sphere.position.z,
                info.radiance.x, info.radiance.y, info.radiance.z, sphere.radius, sphere.shaping_hasvalue,
                sphere.shaping_value.direction.x, sphere.shaping_value.direction.y, sphere.shaping_value.direction.z,
                sphere.shaping_value.coneAngleDegrees, t.moving ? 1 : 0);
    }

    const bool existed = t.handle != nullptr;
    remixapi_LightHandle handle = static_cast<remixapi_LightHandle>(t.handle);
    const remixapi_ErrorCode rc = api->CreateLight(&info, &handle);
    if (rc != REMIXAPI_ERROR_CODE_SUCCESS) {
        // Keep whatever handle the light already had: it is still live in Remix
        // and still needs destroying later. Latch the failure so a broken API
        // costs one call per light rather than one per frame.
        t.applyFailed = true;
        ++g_stats.applyFailures;
        g_stats.lastApplyError = static_cast<int>(rc);
        return;
    }
    t.applyFailed = false;
    t.handle = handle;
    if (existed) {
        ++t.updates;
        ++g_stats.updated;
    } else {
        ++g_stats.created;
    }
}

// GTA2's ambient is a constant added to every lit vertex, which a path tracer
// has no equivalent for. This stands one dim overhead distant light in for it,
// which is not what the game did but is the nearest honest approximation.
void ApplyAmbientFill() {
    const remixapi_Interface* api = RemixApi();
    if (!api) return;

    const float level = g_settings.ambientFill ? g_ambient * g_settings.ambientFillScale : 0.0f;
    // The night sky's fill (nightSkyFill in remix_lights.h): a moonlit sky's blue-grey, by the lamps' clock.
    float night = 0.0f, moonShare = 0.0f;
    {
        DaylightGate gate;
        gate.enabled = true;
        const float fill = g_nightFillMilli >= 0 ? static_cast<float>(g_nightFillMilli) / 1000.0f : g_settings.nightSkyFill;
        // Only with Remix's sky following the clock: without it DaylightGateFactor is 1 at every hour.
        if (fill > 0.0f && !((g_probeMask >> 8) & 1) && RemixApiHasAtmosphere()) {   // probe bit 8: the night fill out
            float share = DaylightGateFactor(gate);
            // FIX-REMIX-NIGHT-3 (pt-remix-dusk-props-near-black-no-sky-ambient): from the sun's DuskFillDegrees
            // above the horizon down to the horizon the fill comes up with the dusk (smoothly, to the night's
            // level at sunset): at 17:00 the sun is low and behind the blocks, the street's props and shaded
            // faces had nothing but a dim sky and read as black cut-outs. 0 by day (sun higher).
            const float start = g_duskFillDeg >= 0 ? static_cast<float>(g_duskFillDeg) : g_settings.duskFillDeg;
            if (start > 0.0f && TimeOfDayPushed()) {
                float elev = 90.0f;
                TimeOfDayAngles(&elev, nullptr);
                float t = (std::max)(0.0f, (std::min)(1.0f, (start - elev) / start));
                t = t * t * (3.0f - 2.0f * t);
                share = (std::max)(share, t);
            }
            night = fill * share;
            moonShare = DaylightGateFactor(gate);   // the lamps' clock alone: 0 through the dusk ramp, 1 at night
        }
    }
    // FIX-REMIX-NIGHT-7 (prmx-remix-bil-night-third-street-and-hero-wash-sulphur-olive-...): at night (by the lamps'
    // clock) the fill was a 0.06 pale blue-grey, too weak against the sodium lamps and the warm player fill: between
    // the lamps the bil streets read olive-brown (the asphalt's own green-yellow under warm light: B < R), the hero's
    // navy tee near black-khaki. A moonlit street's shade is a dark blue-grey: the night share is now a stronger,
    // bluer moon fill (0.14 x 0.36,0.48,1.0; out frn7_t1: road between lamps 41,42,33 -> blue >= red at about the same
    // luminance). The dusk ramp before the lamps' hour keeps the old fill and colour (no cobalt shade at 17:00), and the
    // classic view keeps the old fill at every hour.
    // [devtools] remix_moon_fill_milli=0: the NIGHT-6 fill at night too (A/B); remix_moon_rgb=R,G,B (x1000) live.
    static const float kDuskSky[3] = {0.78f, 0.86f, 1.0f};
    // LIGHTING-V1: gate A raised it to 0.20 (nights read murky); gate B 0.12 for contrast (owner: "an evenly lit dim
    // day"), with stronger lamp pools carrying the light. Probe lt_probe1 variant f (0.28)
    // lifted the shade between lamps most, 0.20 keeps the lamp pools the brighter thing on the street.
    const float moonFill = g_moonFillMilli >= 0 ? static_cast<float>(g_moonFillMilli) / 1000.0f : 0.12f;
    float nightRgb[3];
    for (int i = 0; i < 3; ++i) nightRgb[i] = night * kDuskSky[i];
    // Street views only: the classic view's night light list is as before.
    if (moonFill > 0.0f && moonShare > 0.0f && night > 0.0f && StreetPresentation()) {
        const float fill = g_nightFillMilli >= 0 ? static_cast<float>(g_nightFillMilli) / 1000.0f : g_settings.nightSkyFill;
        const float share = night / fill, w = (std::min)(1.0f, moonShare);
        for (int i = 0; i < 3; ++i) nightRgb[i] = share * ((1.0f - w) * fill * kDuskSky[i] + w * moonFill * g_moonRgb[i]);
    }
    // FIX-REMIX-NIGHT-4 (pt-remix-morning-dusk-shade-cobalt-blue-roads-and-facades): the day look scales the
    // sky's indirect light 3x (so shade is not black), and the sky is blue: at 07:00 and 16:30 the shaded roads
    // and lower storeys went saturated cobalt (sat 0.40-0.53, hue 210) beside cream sunlit faces. What a real
    // street adds there is bounce off sunlit stone and asphalt: a warm grey fill from above while the sun is up
    // (DayBounceFill, faded in over the sun's first 20 degrees). Street views only: the classic view's daytime
    // light list is as before.
    float day = 0.0f, bounceElev = 90.0f;
    {
        const float bounce = g_dayFillMilli >= 0 ? static_cast<float>(g_dayFillMilli) / 1000.0f : g_settings.dayBounceFill;
        if (bounce > 0.0f && StreetPresentation() && RemixApiHasAtmosphere() && TimeOfDayPushed()) {
            float elev = -90.0f;
            TimeOfDayAngles(&elev, nullptr);
            // Smoothly over the sun's first 20 degrees: a dawn sun at 5 degrees is weak and the full fill
            // swamped it (06:30 ste courtyard 2.5x brighter, the hero's crown 39 -> 97, frn4_s1).
            float u = (std::max)(0.0f, (std::min)(1.0f, elev / 20.0f));
            day = bounce * u * u * (3.0f - 2.0f * u);
            bounceElev = elev;
        }
    }
    // FIX-REMIX-NIGHT-5 (NIGHT-4's open item: low-sun shade grey-teal, not warm): a low sun lights the stone
    // and asphalt it reaches gold, so what bounces into the shade is golden too, and the dusk ramp's cool sky
    // fill rises under it at the same hour. The bounce goes from a golden (1, 0.78, 0.55) with the sun under
    // 8 degrees to the noon warm grey above 30, at the same luminance. [devtools] remix_low_bounce_warm=0: the
    // NIGHT-4 colour at every height.
    float kBounce[3] = {1.0f, 0.93f, 0.82f};
    if (g_lowBounceWarm && day > 0.0f) {
        static const float kGold[3] = {1.0f, 0.78f, 0.55f};
        const float lumaGold = 0.2126f * kGold[0] + 0.7152f * kGold[1] + 0.0722f * kGold[2];
        const float lumaNoon = 0.2126f * kBounce[0] + 0.7152f * kBounce[1] + 0.0722f * kBounce[2];
        float w = (std::max)(0.0f, (std::min)(1.0f, (30.0f - bounceElev) / 22.0f));
        w = w * w * (3.0f - 2.0f * w);
        for (int i = 0; i < 3; ++i) kBounce[i] += (kGold[i] * lumaNoon / lumaGold - kBounce[i]) * w;
    }
    if (!g_settings.enabled || level + night + day <= 0.0f) {
        DestroyHandle(g_ambientHandle);
        return;
    }

    remixapi_LightInfo info = {};
    info.sType = REMIXAPI_STRUCT_TYPE_LIGHT_INFO;
    info.hash = kAmbientFillId;
    info.radiance = remixapi_Float3D{level + nightRgb[0] + day * kBounce[0], level + nightRgb[1] + day * kBounce[1],
                                     level + nightRgb[2] + day * kBounce[2]};
    info.isDynamic = 1;

    remixapi_LightInfoDistantEXT distant = {};
    distant.sType = REMIXAPI_STRUCT_TYPE_LIGHT_INFO_DISTANT_EXT;
    distant.direction = remixapi_Float3D{0.0f, -1.0f, 0.0f};   // straight down
    distant.angularDiameterDegrees = 60.0f;                    // broad and soft
    distant.volumetricRadianceScale = 1.0f;
    info.pNext = &distant;

    remixapi_LightHandle handle = static_cast<remixapi_LightHandle>(g_ambientHandle);
    if (api->CreateLight(&info, &handle) == REMIXAPI_ERROR_CODE_SUCCESS) {
        g_ambientHandle = handle;
    }
}

bool SameSettings(const RemixLightSettings& a, const RemixLightSettings& b) {
    // Field by field rather than memcmp: the struct has padding between its
    // bools and floats that nothing ever writes.
    return a.enabled == b.enabled && a.injectStatic == b.injectStatic
        && a.injectMoving == b.injectMoving && a.radianceScale == b.radianceScale
        && a.movingScale == b.movingScale && a.referenceRadius == b.referenceRadius
        && a.radiusExponent == b.radiusExponent && a.emitterRadius == b.emitterRadius
        && a.minIntensity == b.minIntensity && a.saturation == b.saturation
        && a.wideNeonRadius == b.wideNeonRadius
        && a.ambientFill == b.ambientFill && a.ambientFillScale == b.ambientFillScale
        && a.nightSkyFill == b.nightSkyFill && a.duskFillDeg == b.duskFillDeg && a.dayBounceFill == b.dayBounceFill
        && a.coneSoftness == b.coneSoftness && a.buriedLift == b.buriedLift && a.poolConeDeg == b.poolConeDeg
        && memcmp(a.gameClass, b.gameClass, sizeof(a.gameClass)) == 0;
}

char* TrimInPlace(char* s) {
    while (*s == ' ' || *s == '\t') ++s;
    char* e = s + strlen(s);
    while (e > s && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\r' || e[-1] == '\n')) *--e = '\0';
    return s;
}

}  // namespace

bool RemixLightOverride::IsDefault() const {
    // The note alone is worth keeping: it is how a light gets labelled before
    // anything is actually changed about it.
    return !disabled && intensity == 1.0f && !recolor && emitterRadius == 0.0f
        && offset[0] == 0.0f && offset[1] == 0.0f && offset[2] == 0.0f && note.empty();
}

void LightsInit(const char* overridePath) {
    if (overridePath && *overridePath) {
        strncpy(g_overridePath, overridePath, sizeof(g_overridePath) - 1);
        g_overridePath[sizeof(g_overridePath) - 1] = '\0';
    }
    g_applied = g_settings;
    LightsLoadOverrides();
}

void LightsShutdown() {
    // Deliberately not saved here. Quitting is not a decision to keep what was
    // being tried out; the Save button is.
    ClearAll();
    g_pending.clear();
    g_extra.clear();
    g_working.clear();
}

RemixLightSettings& LightsSettings() { return g_settings; }

void LightsBeginCollect() {
    g_pending.clear();
    g_listedMapKeys.clear();
    g_collecting = true;
    ++g_collects;
}

void LightsAddRaw(const void* descriptor) {
    if (!descriptor || !g_collecting) return;

    // 20 bytes, laid out by gta2.exe!FUN_00461400 and decoded by
    // d3ddll.dll!gbh_AddLight. See docs/lighting-analysis.md.
    const uint8_t* p = static_cast<const uint8_t*>(descriptor);
    uint32_t packed = 0, rgb = 0;
    float x = 0.0f, y = 0.0f, z = 0.0f;
    memcpy(&packed, p + 0x00, 4);
    memcpy(&x, p + 0x04, 4);
    memcpy(&y, p + 0x08, 4);
    memcpy(&z, p + 0x0C, 4);
    memcpy(&rgb, p + 0x10, 4);

    // The original renderer skips anything without bit 0x10000 set and bit
    // 0x20000 clear. Nothing in the game ever sets 0x20000, but honouring the
    // test costs nothing and keeps us equivalent.
    if ((packed & 0x30000u) != 0x10000u) return;

    RemixLightDesc d;
    d.intensity = static_cast<float>(packed & 0xFFu) / 255.0f;
    // The renderer's own conversion: the byte holds radius*32, and 255 maps to
    // the 8-tile maximum.
    d.radius = static_cast<float>((packed >> 8) & 0xFFu) / 255.0f * 8.0f;
    // The byte is the radius times 32, stored without a clamp
    // (gta2.exe!FUN_00463EF0), so a light the map gives the largest radius, 8
    // tiles, wraps to 256 = 0 and lights nothing - in the original renderer as
    // well. That is 145 of the 1743 lights in ste.gmp, several of the lamps in
    // two of the Downtown bonus maps, and a handful elsewhere. No shipped map
    // light has a radius small enough to quantise to 0 honestly, so 0 is read
    // as the 8 tiles it was.
    if (((packed >> 8) & 0xFFu) == 0) d.radius = 8.0f;
    d.rgb[0] = static_cast<float>((rgb >> 16) & 0xFFu) / 255.0f;
    d.rgb[1] = static_cast<float>((rgb >> 8) & 0xFFu) / 255.0f;
    d.rgb[2] = static_cast<float>(rgb & 0xFFu) / 255.0f;

    // Same axis mapping the sprite path uses: the game's x is east, y is south
    // and z is the map level, while the world mesh is +X east, +Y up, +Z north
    // with the rows mirrored.
    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) return;
    if (x < -8.0f || x > gta2::kMapWidth + 8.0f || y < -8.0f || y > gta2::kMapHeight + 8.0f
        || z < -4.0f || z > 12.0f) {
        return;
    }
    d.pos[0] = x;
    d.pos[1] = z;
    d.pos[2] = static_cast<float>(gta2::kMapHeight) - y;

    uint64_t key = 0;
    if (MapLightKeyOf(d.pos, &key)) g_listedMapKeys.insert(key);
    g_pending.push_back(d);
}

void LightsSetMapLightRecords(const std::vector<uint8_t>& lght) {
    g_mapLampRecords.clear();
    int blinking = 0;
    for (size_t i = 0; i + 16 <= lght.size(); i += 16) {
        uint32_t argb = 0;
        uint16_t v[4];
        memcpy(&argb, &lght[i], 4);
        memcpy(v, &lght[i + 4], sizeof(v));   // x, y, z, radius at 128 to a tile
        const uint8_t intensity = lght[i + 12], onTime = lght[i + 14], offTime = lght[i + 15];
        if (onTime || offTime) { ++blinking; continue; }
        MapLampRecord r;
        // The same frame the game's descriptors land in (LightsAddRaw).
        r.pos[0] = v[0] / 128.0f;
        r.pos[1] = v[2] / 128.0f;
        r.pos[2] = static_cast<float>(gta2::kMapHeight) - v[1] / 128.0f;
        r.rgb[0] = static_cast<float>((argb >> 16) & 0xFFu) / 255.0f;
        r.rgb[1] = static_cast<float>((argb >> 8) & 0xFFu) / 255.0f;
        r.rgb[2] = static_cast<float>(argb & 0xFFu) / 255.0f;
        r.intensity = intensity / 255.0f;
        // The game packs the reach as radius*32 in a byte and the renderer reads
        // 255 as 8 tiles (see LightsAddRaw); the file's own value, in tiles.
        r.radius = v[3] / 128.0f;
        if (r.radius <= 0.0f || r.radius > 8.0f) r.radius = 8.0f;
        r.key = MapLightKey(v[0], v[1], v[2]);
        if (r.intensity <= 0.0f) continue;
        g_mapLampRecords.push_back(r);
    }
    Log("remix lights: %u steady map lamps decoded for the street views (%d blinking left to the game)",
        static_cast<unsigned>(g_mapLampRecords.size()), blinking);
}

namespace {
// --- Lit windows (FIX-REMIX-NIGHT-6, ptrmx25) --------------------------------
//
// The districts' lit-window wall tiles (amber or warm panes painted into the art: ste 961/962/983, the
// pale yellow panes on the blue offices 493/505-508, wil's strip windows 100/125/127, bil 243/246...)
// glowed under Remix by their albedo alone and lit nothing: the wall under the sill, the ledge and the
// pavement stayed as dark as a blank wall (defect ptrmx25). Each such face now gets a small warm room
// light hung just in front of the pane band, shaped down and out (a window lights the wall below it
// and the pavement, not the eaves), at night only (the street lamps' clock), in the street views only
// (weighted by the same sky blend as the far lamps, so the classic view gets none) and only on a Remix
// device (the plain renderer reads the tracked list: it must not gain lights). Nearest first, capped,
// so a facade of windows is a row of small pools, not a flood.
// The tile list was picked by eye from a warm-pane scan of the HD tiles (tile ids and the pane band's
// height only, no art): v is the pane band's centre from the top of the tile, share the lit fraction.
struct LitWindowTile { const char* style; int tile; float v; float share; };
const LitWindowTile kLitWindowTiles[] = {
    {"ste", 276, 0.41f, 0.05f}, {"ste", 281, 0.58f, 0.10f}, {"ste", 311, 0.61f, 0.06f}, {"ste", 480, 0.42f, 0.04f},
    {"ste", 493, 0.16f, 0.19f}, {"ste", 505, 0.13f, 0.09f}, {"ste", 506, 0.72f, 0.17f}, {"ste", 507, 0.73f, 0.09f},
    {"ste", 508, 0.16f, 0.14f}, {"ste", 961, 0.30f, 0.22f}, {"ste", 962, 0.30f, 0.23f}, {"ste", 983, 0.28f, 0.09f},
    {"wil", 100, 0.59f, 0.05f}, {"wil", 125, 0.61f, 0.14f}, {"wil", 127, 0.58f, 0.07f}, {"wil", 498, 0.45f, 0.07f},
    {"wil", 810, 0.42f, 0.05f}, {"wil", 815, 0.58f, 0.12f},
    {"bil", 243, 0.23f, 0.12f}, {"bil", 246, 0.25f, 0.13f}, {"bil", 293, 0.42f, 0.08f}, {"bil", 788, 0.42f, 0.05f},
    {"bil", 793, 0.58f, 0.11f},
};
struct WindowLight { float pos[3]; float dir[3]; float share; float centre[3]; uint64_t id; bool lamp = false; bool flood = false; };
std::vector<WindowLight> g_windowLights;     // every lit-window face of the district, renderer frame
const gta2::Map* g_windowMap = nullptr;
size_t g_windowMapBlocks = 0;
char g_windowScene[64] = "";
int g_windowOutBuilt = -1;
int g_windowsLastFrame = 0;
constexpr float kWindowRadius = 18.0f;       // tiles from the eye
constexpr int kWindowCap = 40;

const gta2::Block* BlockAtLevel(const gta2::Map& map, int x, int y, int z) {
    if (x < 0 || y < 0 || x >= gta2::kMapWidth || y >= gta2::kMapHeight) return nullptr;
    const gta2::Column& c = map.ColumnAt(x, y);
    const int i = z - c.offset;
    if (i < 0 || i >= static_cast<int>(c.blocks.size())) return nullptr;
    const uint32_t b = c.blocks[static_cast<size_t>(i)];
    return b < map.BlockCount() ? &map.BlockAt(b) : nullptr;
}

void BuildWindowLights() {
    const gta2::Map* map = g_ground && g_ground->Ready() ? g_ground->MapData() : nullptr;
    if (!map) return;
    if (map == g_windowMap && map->BlockCount() == g_windowMapBlocks && g_windowOutBuilt == g_windowOutMilli &&
        strcmp(g_windowScene, g_sceneName) == 0) return;
    g_windowMap = map; g_windowMapBlocks = map->BlockCount(); g_windowOutBuilt = g_windowOutMilli;
    strncpy(g_windowScene, g_sceneName, sizeof(g_windowScene) - 1);
    g_windowLights.clear();
    const LitWindowTile* byTile[1024] = {};
    for (const LitWindowTile& t : kLitWindowTiles) {
        if (strcmp(t.style, g_sceneName) == 0 && t.tile > 0 && t.tile < 1024) byTile[t.tile] = &t;
    }
    const float out = static_cast<float>(g_windowOutMilli) / 1000.0f;
    int skippedHidden = 0;
    for (int y = 0; y < gta2::kMapHeight; ++y) {
        for (int x = 0; x < gta2::kMapWidth; ++x) {
            const gta2::Column& c = map->ColumnAt(x, y);
            for (size_t i = 0; i < c.blocks.size(); ++i) {
                if (c.blocks[i] >= map->BlockCount()) continue;
                const gta2::Block& b = map->BlockAt(c.blocks[i]);
                const int z = c.offset + static_cast<int>(i);
                // left (-x), right (+x), top (north: game -y, renderer +Z), bottom (game +y, renderer -Z)
                const gta2::Face faces[4] = {b.left, b.right, b.top, b.bottom};
                static const int kDx[4] = {-1, 1, 0, 0}, kDy[4] = {0, 0, -1, 1}, kOpp[4] = {1, 0, 3, 2};
                for (int k = 0; k < 4; ++k) {
                    const int tile = faces[k].Tile();
                    if (!tile || !byTile[tile]) continue;
                    // A pane that faces a solid neighbour (one with a lid at this level, or its own face back
                    // against this one) is inside the block mass: nobody sees it, and a light there would
                    // glow through the seam.
                    const gta2::Block* nb = BlockAtLevel(*map, x + kDx[k], y + kDy[k], z);
                    if (nb) {
                        const gta2::Face nf[4] = {nb->left, nb->right, nb->top, nb->bottom};
                        if (nb->lid || nf[kOpp[k]]) { ++skippedHidden; continue; }
                    }
                    const LitWindowTile& t = *byTile[tile];
                    float v = t.v;
                    if (faces[k].Rotation() == 2) v = 1.0f - v; else if (faces[k].Rotation() & 1) v = 0.5f;
                    // The face's centre in the renderer frame: +X east, +Y up, +Z = 256 - game y.
                    float cx = x + 0.5f, cz = static_cast<float>(gta2::kMapHeight) - (y + 0.5f), nx = 0.0f, nz = 0.0f;
                    if (k == 0) { cx = static_cast<float>(x); nx = -1.0f; }
                    if (k == 1) { cx = static_cast<float>(x + 1); nx = 1.0f; }
                    if (k == 2) { cz = static_cast<float>(gta2::kMapHeight - y); nz = 1.0f; }
                    if (k == 3) { cz = static_cast<float>(gta2::kMapHeight - y - 1); nz = -1.0f; }
                    const float cy = static_cast<float>(z) + 1.0f - v;
                    WindowLight w;
                    w.centre[0] = cx; w.centre[1] = cy; w.centre[2] = cz;
                    w.pos[0] = cx + nx * out; w.pos[1] = cy - 0.05f; w.pos[2] = cz + nz * out;
                    // Down and out: 56 degrees below the outward horizontal.
                    w.dir[0] = nx * 0.56f; w.dir[1] = -0.83f; w.dir[2] = nz * 0.56f;
                    w.share = t.share;
                    w.id = 0x57494E0000000000ULL ^ (static_cast<uint64_t>(x) << 24) ^ (static_cast<uint64_t>(y) << 12) ^
                           (static_cast<uint64_t>(z) << 4) ^ static_cast<uint64_t>(k) ^ (g_sceneSalt & 0xFF00000000ULL);
                    g_windowLights.push_back(w);
                }
            }
        }
    }
    // FIX-REMIX-NIGHT-6 (ptrmx22, lit-lens half): Downtown's gantry signal slabs (slope 53/54, both side panels flat,
    // the east one wil tile 753, the game's round teal lamp; FIX-WORLD-8 f4494c6 draws it in the street views as a
    // 0.17-block plate at the slab's middle, top 0.98 over the level) get a dim lamp of the lens's own teal at night,
    // just east of the lens: the lens reads lit and the bar and the road under it take a faint glow. The game runs no
    // phase for this tile and lists no light there, so the colour is fixed. Positions are read from the same map the
    // same way world_mesh's SignalSlab does (GTA2DX9_SIGNAL_HEADS=0 puts the plates back and leaves these where the
    // lens was drawn small). [devtools] remix_gantry_pct (0 off).
    int gantries = 0;
    if (strcmp(g_sceneName, "wil") == 0) {
        for (int y = 0; y < gta2::kMapHeight; ++y) {
            for (int x = 0; x < gta2::kMapWidth; ++x) {
                const gta2::Column& c = map->ColumnAt(x, y);
                for (size_t i = 0; i < c.blocks.size(); ++i) {
                    if (c.blocks[i] >= map->BlockCount()) continue;
                    const gta2::Block& b = map->BlockAt(c.blocks[i]);
                    const int type = b.SlopeType();
                    if ((type != 53 && type != 54) || !b.left || !b.right || !b.left.IsFlat() || !b.right.IsFlat() ||
                        b.right.Tile() != 753) continue;
                    const int z = c.offset + static_cast<int>(i);
                    WindowLight w;
                    w.lamp = true;
                    w.centre[0] = static_cast<float>(x) + (type == 54 ? 0.87f : 0.13f);
                    w.centre[1] = static_cast<float>(z) + 0.90f;
                    w.centre[2] = static_cast<float>(gta2::kMapHeight) - (y + 0.5f);
                    memcpy(w.pos, w.centre, sizeof(w.pos));
                    w.pos[0] += 0.07f;   // in front of the east (lens) face
                    w.dir[0] = 1.0f; w.dir[1] = 0.0f; w.dir[2] = 0.0f;
                    w.share = 0.15f;
                    w.id = 0x47414E0000000000ULL ^ (static_cast<uint64_t>(x) << 24) ^ (static_cast<uint64_t>(y) << 12) ^
                           (static_cast<uint64_t>(z) << 4);
                    g_windowLights.push_back(w);
                    ++gantries;
                }
            }
        }
    }
    Log("remix lights: %d gantry signal lenses lit at night in '%s'", gantries, g_sceneName);
    // FIX-REMIX-NIGHT-7 (prx2-remix-wil-round-atom-wall-sign-...-night-dead-grey-disc): Downtown's rooftop sign plates
    // (flat, double-sided faces standing in the air: tiles 62/63 the yellow atom disc, 61 FUTURO RADIO) have no map
    // light and no emissive, so at night under Remix they were a dead grey-brown disc darker than the wall behind.
    // Each such face now gets a small warm floodlight at night, half a tile out from its plane on its own side and a
    // little below, aimed back at the plate's centre: the sign reads floodlit from the street. [devtools]
    // remix_sign_flood_pct (0 off). An emissive prim for the atom lines is a material item (note beside the order).
    int floods = 0;
    if (strcmp(g_sceneName, "wil") == 0) {
        for (int y = 0; y < gta2::kMapHeight; ++y) {
            for (int x = 0; x < gta2::kMapWidth; ++x) {
                const gta2::Column& c = map->ColumnAt(x, y);
                for (size_t i = 0; i < c.blocks.size(); ++i) {
                    if (c.blocks[i] >= map->BlockCount()) continue;
                    const gta2::Block& b = map->BlockAt(c.blocks[i]);
                    const int z = c.offset + static_cast<int>(i);
                    const gta2::Face faces[4] = {b.left, b.right, b.top, b.bottom};
                    static const int kDx[4] = {-1, 1, 0, 0}, kDy[4] = {0, 0, -1, 1}, kOpp[4] = {1, 0, 3, 2};
                    for (int k = 0; k < 4; ++k) {
                        const int tile = faces[k].Tile();
                        if (tile < 61 || tile > 63) continue;
                        const gta2::Block* nb = BlockAtLevel(*map, x + kDx[k], y + kDy[k], z);
                        if (nb) {
                            const gta2::Face nf[4] = {nb->left, nb->right, nb->top, nb->bottom};
                            if (nb->lid || nf[kOpp[k]]) continue;
                        }
                        float cx = x + 0.5f, cz = static_cast<float>(gta2::kMapHeight) - (y + 0.5f), nx = 0.0f, nz = 0.0f;
                        if (k == 0) { cx = static_cast<float>(x); nx = -1.0f; }
                        if (k == 1) { cx = static_cast<float>(x + 1); nx = 1.0f; }
                        if (k == 2) { cz = static_cast<float>(gta2::kMapHeight - y); nz = 1.0f; }
                        if (k == 3) { cz = static_cast<float>(gta2::kMapHeight - y - 1); nz = -1.0f; }
                        WindowLight w;
                        w.flood = true;
                        w.centre[0] = cx; w.centre[1] = static_cast<float>(z) + 0.5f; w.centre[2] = cz;
                        w.pos[0] = cx + nx * 0.5f; w.pos[1] = w.centre[1] - 0.3f; w.pos[2] = cz + nz * 0.5f;
                        float d[3] = {w.centre[0] - w.pos[0], w.centre[1] - w.pos[1], w.centre[2] - w.pos[2]};
                        const float dl = std::sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
                        for (int j = 0; j < 3; ++j) w.dir[j] = d[j] / dl;
                        w.share = 0.15f;
                        w.id = 0x464C4F0000000000ULL ^ (static_cast<uint64_t>(x) << 24) ^ (static_cast<uint64_t>(y) << 12) ^
                               (static_cast<uint64_t>(z) << 4) ^ static_cast<uint64_t>(k);
                        g_windowLights.push_back(w);
                        ++floods;
                    }
                }
            }
        }
    }
    Log("remix lights: %d rooftop sign plates floodlit at night in '%s'", floods, g_sceneName);
    Log("remix lights: %u lit-window faces in '%s' (%d facing a solid neighbour skipped), out %.2f tile",
        static_cast<unsigned>(g_windowLights.size()), g_sceneName, skippedHidden, out);
}

void SubmitWindowLightsNear(const float* eye, float weight) {
    g_windowsLastFrame = 0;
    if ((g_windowPct <= 0 && g_gantryPct <= 0 && g_signFloodPct <= 0) || weight <= 0.0f || ((g_probeMask >> 9) & 1) || !RemixApi()) return;
    if (!g_settings.enabled || !g_settings.injectStatic) return;
    BuildWindowLights();
    if (g_windowLights.empty()) return;
    DaylightGate gate;
    gate.enabled = true;
    const float night = DaylightGateFactor(gate);
    // LIGHTING-V1: each window has its own switching time (DaylightGateFactorKeyed); the shared clock above is
    // only the early-out (nothing lit until the first light of the stagger).
    const float spreadH = TimeOfDay().lightsStaggerMinutes / 60.0f;
    if (night <= 0.001f && DaylightGateFactorKeyedAtHour(gate, 0, TimeOfDayHour() + 0.25f * spreadH) <= 0.001f &&
        DaylightGateFactorKeyedAtHour(gate, 0, TimeOfDayHour() - 0.5f * spreadH) <= 0.001f) return;
    struct Near { float d2; const WindowLight* w; };
    std::vector<Near> found;
    const float r2 = kWindowRadius * kWindowRadius;
    for (const WindowLight& w : g_windowLights) {
        const float dx = w.centre[0] - eye[0], dy = w.centre[1] - eye[1], dz = w.centre[2] - eye[2];
        const float d2 = dx * dx + dy * dy + dz * dz;
        if (d2 <= r2) found.push_back({d2, &w});
    }
    if (found.size() > static_cast<size_t>(kWindowCap)) {
        std::nth_element(found.begin(), found.begin() + kWindowCap, found.end(),
                         [](const Near& a, const Near& b) { return a.d2 < b.d2; });
        found.resize(kWindowCap);
    }
    // A warm tungsten room light; the lit fraction of the tile scales it (a strip of panes gives less than a
    // whole shopfront), bounded so the brightest tile is 1.3x and the dimmest 0.5x of the 0.15-share one.
    static const float kRoom[3] = {1.0f, 0.71f, 0.42f};
    const float pct = static_cast<float>(g_windowPct) / 100.0f;
    for (const Near& n : found) {
        float share = n.w->share / 0.15f;
        share = share < 0.5f ? 0.5f : (share > 1.3f ? 1.3f : share);
        RemixLightDesc d;
        memcpy(d.pos, n.w->pos, sizeof(d.pos));
        const float own = DaylightGateFactorKeyed(gate, n.w->id);
        if (own <= 0.001f) continue;
        const float level0 = std::floor(own * weight * 32.0f + 0.5f) / 32.0f;
        if (n.w->lamp) {
            // The gantry lens: its own teal, a small dim sphere a few centimetres off the plate.
            static const float kTeal[3] = {0.45f, 1.0f, 0.90f};
            if (g_gantryPct <= 0) continue;
            memcpy(d.rgb, kTeal, sizeof(d.rgb));
            d.intensity = 0.09f * static_cast<float>(g_gantryPct) / 100.0f * level0;   // frn6_p3: 0.06 lit the lens G 21->55 of 255
            d.radius = 2.0f;
            d.emitterRadius = 0.035f;
            d.source = kLightSourceWindow;
            d.explicitId = n.w->id;
            if (d.intensity > 0.0005f) g_extra.push_back(d);
            continue;
        }
        if (n.w->flood) {
            // FIX-REMIX-NIGHT-7: a warm-white floodlight aimed back at a rooftop sign plate.
            static const float kFlood[3] = {1.0f, 0.88f, 0.70f};
            if (g_signFloodPct <= 0) continue;
            memcpy(d.rgb, kFlood, sizeof(d.rgb));
            // frn7_x1: 0.5 at a 0.05 emitter lifted the disc 59 -> 61 of 255 (radiance is per emitter area); frn7_x2 at
            // 0.08: 6 -> disc luma 53 -> 80, 12 -> 101 (lit from below, not clipped); 9 between.
            d.intensity = 9.0f * static_cast<float>(g_signFloodPct) / 100.0f * level0;
            d.radius = 2.0f;
            d.emitterRadius = 0.08f;
            d.spot = true;
            memcpy(d.dir, n.w->dir, sizeof(d.dir));
            d.coneAngleDeg = 50.0f;
            d.coneSoftness = 0.5f;
            d.source = kLightSourceWindow;
            d.explicitId = n.w->id;
            if (d.intensity > 0.0005f) g_extra.push_back(d);
            continue;
        }
        if (g_windowPct <= 0) continue;
        memcpy(d.rgb, kRoom, sizeof(d.rgb));
        // Quantised so the per-frame blend does not redefine 40 lights every frame.
        const float level = level0;
        d.intensity = 0.45f * share * pct * level;   // frn6_p1: 0.25 lit the ledges +0.04 luma, 0.62 +0.09; 0.45 between
        d.radius = 2.0f;
        d.emitterRadius = 0.12f;
        d.spot = true;
        memcpy(d.dir, n.w->dir, sizeof(d.dir));
        d.coneAngleDeg = 80.0f;
        d.coneSoftness = 0.5f;
        d.source = kLightSourceWindow;
        d.explicitId = n.w->id;
        if (d.intensity > 0.0005f) g_extra.push_back(d);
    }
    g_windowsLastFrame = static_cast<int>(found.size());
    static uint32_t logged = 0;
    if ((g_frame & 255u) == 0 && g_frame != logged) {
        logged = g_frame;
        Log("remix lights: %d lit-window lights within %.0f tiles (night %.2f, blend %.2f, %d%%)", g_windowsLastFrame,
            kWindowRadius, night, weight, g_windowPct);
    }
}

}  // namespace

float g_lastEye[3] = {0, 0, 0};
bool g_haveEye = false;

void LightsSubmitMapLampsNear(const float* eye, float radius, int cap, float weight) {
    g_farLampsLastFrame = 0;
    weight = weight < 0.0f ? 0.0f : (weight > 1.0f ? 1.0f : weight);
    g_farLampWeight = weight;
    memcpy(g_lastEye, eye, sizeof(g_lastEye)); g_haveEye = true;
    {   // LIGHTING-V1 probe, GTA2DX9_LOG_REMIX_LAMPS=1: every 256 frames the game lights (lamps, lanterns, pools, far lamps)
        // within 9 tiles of the eye as Remix gets them: why one lamp pools and another does not.
        static const bool logLamps = [] { const char* e = getenv("GTA2DX9_LOG_REMIX_LAMPS"); return e && e[0] == '1'; }();
        if (logLamps && (g_frame & 255u) == 7u) {
            int n = 0;
            for (const RemixTrackedLight& t : g_tracked) {
                if (t.def.source != kLightSourceGame) continue;
                const float dx = t.def.pos[0] - eye[0], dy = t.def.pos[1] - eye[1], dz = t.def.pos[2] - eye[2];
                const float d = std::sqrt(dx * dx + dy * dy + dz * dz);
                if (d > 9.0f || n >= 24) continue;
                ++n;
                Log("remix lamps: d %.1f at %.2f,%.2f,%.2f class %d rgb %.2f,%.2f,%.2f i %.3f r %.2f emitter %.3f spot %d cone %.0f day %.2f %s%s",
                    d, t.def.pos[0], t.def.pos[1], t.def.pos[2], t.gameClass, t.def.rgb[0], t.def.rgb[1], t.def.rgb[2], t.def.intensity,
                    t.def.radius, t.def.emitterRadius, t.def.spot ? 1 : 0, t.def.coneAngleDeg, LightDaylight(t), t.moving ? "moving " : "",
                    t.drawn ? "drawn" : "not drawn");
            }
        }
    }
    SubmitWindowLightsNear(eye, weight);   // FIX-REMIX-NIGHT-6: lit windows (own probe bit 9, key remix_window_pct)
    if ((g_probeMask >> 5) & 1) return;
    if (!g_settings.enabled || !g_settings.injectStatic || g_mapLampRecords.empty() || cap <= 0) {
        static bool said = false;
        if (!said) { said = true; Log("remix lights: far lamps off (enabled %d injectStatic %d records %u)", g_settings.enabled ? 1 : 0, g_settings.injectStatic ? 1 : 0, static_cast<unsigned>(g_mapLampRecords.size())); }
        return;
    }
    struct NearLamp { float d2; const MapLampRecord* r; };
    std::vector<NearLamp> found;
    const float r2 = radius * radius;
    for (const MapLampRecord& r : g_mapLampRecords) {
        if (g_listedMapKeys.count(r.key)) continue;   // the game has this one this frame
        const float dx = r.pos[0] - eye[0], dy = r.pos[1] - eye[1], dz = r.pos[2] - eye[2];
        const float d2 = dx * dx + dy * dy + dz * dz;
        if (d2 > r2) continue;
        found.push_back({d2, &r});
    }
    if (found.size() > static_cast<size_t>(cap)) {
        std::nth_element(found.begin(), found.begin() + cap, found.end(),
                         [](const NearLamp& a, const NearLamp& b) { return a.d2 < b.d2; });
        found.resize(cap);
    }
    for (const NearLamp& n : found) {
        RemixLightDesc d;
        memcpy(d.pos, n.r->pos, sizeof(d.pos));
        memcpy(d.rgb, n.r->rgb, sizeof(d.rgb));
        d.intensity = n.r->intensity * weight;
        d.radius = n.r->radius;
        d.source = kLightSourceGame;   // matched by position like the game's own, lifted and gated the same
        d.stagger = n.r->key;          // LIGHTING-V1: switches with the game's lamp it stands in for
        g_extra.push_back(d);
    }
    g_farLampsLastFrame = static_cast<int>(found.size());
    static uint32_t logged = 0;
    if ((g_frame & 255u) == 0 && g_frame != logged) {
        logged = g_frame;
        Log("remix lights: far lamps %d within %.0f tiles of eye %.1f,%.1f,%.1f (game listed %u map lamps; %d lamp pools under posts)",
            g_farLampsLastFrame, radius, eye[0], eye[1], eye[2], static_cast<unsigned>(g_listedMapKeys.size()), g_lampPoolsLastFrame);
    }
}

int LightsFarLampsLastFrame() { return g_farLampsLastFrame; }

float LightsTrackedDaylight(const RemixTrackedLight& t) {
    if (t.def.source != kLightSourceGame || t.gameClass >= kGameLightClassCount || !g_settings.gameClass[t.gameClass].gate.enabled)
        return -1.0f;
    return LightDaylight(t);
}

void LightsSetAmbient(float ambient) { g_ambient = ambient; }

void LightsSetGround(const GroundSampler* ground) { g_ground = ground; }

void LightsSetMapLights(const std::vector<uint16_t>& xyz) {
    g_mapLights.clear();
    for (size_t i = 0; i + 3 <= xyz.size(); i += 3) {
        g_mapLights.insert(MapLightKey(xyz[i], xyz[i + 1], xyz[i + 2]));
    }
    g_reliftPending = true;
}

void LightsBeginExtra() {
    g_extra.clear();
    g_farLampsLastFrame = 0;   // until LightsSubmitMapLampsNear says otherwise this frame
    g_farLampWeight = 0.0f;
}

void LightsSubmitExtra(const RemixLightDesc& desc) { g_extra.push_back(desc); }

const char* GameLightClassName(uint8_t klass) {
    switch (klass) {
        case kGameLightStreet: return "Street";
        case kGameLightNeon: return "Neon";
        case kGameLightWhite: return "White";
        case kGameLightTraffic: return "Traffic";
        case kGameLightVehicle: return "Vehicle";
        default: return "?";
    }
}

// See the note in remix_lights.h for where each of these tests comes from.
uint8_t ClassifyGameLight(const RemixLightDesc& d, bool moving) {
    // A light that has been seen in two places is attached to something that
    // drives. FUN_00424700 hangs up to four on every vehicle at spawn.
    if (moving) return kGameLightVehicle;

    const float r = d.rgb[0], g = d.rgb[1], b = d.rgb[2];
    const float top = r > g ? (r > b ? r : b) : (g > b ? g : b);
    const float bottom = r < g ? (r < b ? r : b) : (g < b ? g : b);

    // Traffic signals are built at runtime rather than read from the map, at a
    // hard-coded intensity of 200 and one of exactly three colours the phase
    // machine cycles through. A map light lands on 200/255 only by accident, and
    // essentially never in one of those three colours as well.
    if (std::fabs(d.intensity - 200.0f / 255.0f) < 0.002f) {
        const bool red = r > 0.9f && g < 0.05f && b < 0.05f;
        const bool amber = r > 0.9f && g > 0.4f && g < 0.6f && b < 0.05f;
        const bool green = g > 0.9f && r < 0.05f && b < 0.05f;
        if (red || amber || green) return kGameLightTraffic;
    }

    // Near-neutral is a window or an interior. The threshold is deliberately
    // generous: #FFDB5E, the warm white 500 map lights use, has to land here
    // rather than with the sodium lamps.
    const float saturation = top > 0.0f ? (top - bottom) / top : 0.0f;
    if (saturation < 0.45f) return kGameLightWhite;

    // Sodium and amber: red leads, green follows, blue trails. That is #FF8000,
    // #FF8040, #FF9224 and #FFFF00 - a fifth of every light in the game.
    if (r >= g && g >= b && r > 0.75f) return kGameLightStreet;

    // Everything else saturated is signage: the greens, cyans, blues and
    // magentas GTA2 uses for neon and nothing else uses at all.
    return kGameLightNeon;
}

const char* LightSourceName(uint8_t source) {
    switch (source) {
        case kLightSourceGame: return "game";
        case kLightSourceMuzzle: return "muzzle";
        case kLightSourceBullet: return "bullet";
        case kLightSourceSpark: return "spark";
        case kLightSourceCigarette: return "cigarette";
        case kLightSourceFire: return "fire";
        case kLightSourceHeadlight: return "headlight";
        case kLightSourceBrake: return "brake";
        case kLightSourceElectric: return "electric";
        case kLightSourceCarLamp: return "car lamp";
        case kLightSourceFlame: return "flamethrower";
        case kLightSourceSiren: return "siren";
        case kLightSourcePlayerFill: return "player fill";
        case kLightSourceWindow: return "window";
        default: return "?";
    }
}

void LightsSetScene(const char* name) {
    const char* safe = name ? name : "";
    if (strncmp(safe, g_sceneName, sizeof(g_sceneName) - 1) == 0) return;
    strncpy(g_sceneName, safe, sizeof(g_sceneName) - 1);
    g_sceneName[sizeof(g_sceneName) - 1] = '\0';
    g_sceneSalt = *safe ? HashBytes(safe, strlen(safe)) : 0;
    // The old district's lights belong to a world that is no longer there.
    ClearAll();
    Log("remix lights: district '%s'", g_sceneName);
}

float LightsAmbient() { return g_ambient; }
const char* LightsScene() { return g_sceneName; }

namespace {

// The daylight factor per class, worked out once a frame rather than per light.
//
// Redefining a light is a round trip across the 32-bit bridge, so a factor that
// slides continuously would redefine every lamp in the district every frame for
// the half-minute dusk takes. It is only acted on in steps: at a hundredth of
// full brightness there are fifty steps across the whole fade, which is far
// smoother than the eye and a fiftieth of the traffic.
constexpr float kGateStep = 0.02f;
// Below this a light is not worth a handle at all - it is a hundredth of its
// brightness and the sun is up.
constexpr float kGateFloor = 0.01f;

float g_classDaylight[kGameLightClassCount];
float g_classApplied[kGameLightClassCount];
bool  g_classMoved[kGameLightClassCount];
bool  g_classDaylightReady = false;

// [devtools] remix_lights_probe=mask (FIX-REMIX-NIGHT): bit i puts the game's light class i out
// (0 street, 1 neon, 2 white, 4 vehicle), bit 5 the far lamps, bit 6 the lamp pools, bit 7 the lanterns on
// posts, for a live A/B of what lights a scene.

float GameClassDaylight(uint8_t klass) {
    if (klass >= kGameLightClassCount) return 1.0f;
    return g_classDaylight[klass];
}

// LIGHTING-V1: one game light's share, at its own switching time within the stagger (a fixed light's
// placement key; see RemixLightDesc::stagger). Moving lights and ungated classes take the class value.
uint64_t StaggerKey(const RemixTrackedLight& t) {
    if (t.def.stagger) return t.def.stagger;
    if (t.moving) return 0;
    uint64_t key = 0;
    if (MapLightKeyOf(t.def.pos, &key)) return key;
    return t.key ? t.key : t.id;
}

float LightDaylight(const RemixTrackedLight& t) {
    const uint8_t klass = t.gameClass;
    if (t.def.source != kLightSourceGame || klass >= kGameLightClassCount) return 1.0f;
    if ((g_probeMask >> klass) & 1) return 0.0f;
    const DaylightGate& gate = g_settings.gameClass[klass].gate;
    if (!gate.enabled) return g_classDaylight[klass];
    return DaylightGateFactorKeyed(gate, StaggerKey(t));
}

void RefreshClassDaylight() {
    for (int i = 0; i < kGameLightClassCount; ++i) {
        const float now = (g_probeMask >> i) & 1 ? 0.0f : DaylightGateFactor(g_settings.gameClass[i].gate);
        g_classDaylight[i] = now;
        g_classMoved[i] = !g_classDaylightReady || std::fabs(now - g_classApplied[i]) >= kGateStep;
        if (g_classMoved[i]) g_classApplied[i] = now;
    }
    g_classDaylightReady = true;
}

void FitLampsToPosts() {
    g_lampPoolsLastFrame = 0;
    // FIX-REMIX-3 (pt-remix-classic-lit-state-flips-after-3d-roundtrip): only while the picture
    // presents the street views, where the posts are drawn. The posts are placed by the first
    // street frame and stay placed, so this used to fit the lamps and add their pools in the
    // classic view too, from the first V on: the classic light set went from the game's lamps
    // (28 lights at the Wil spawn) to lamps plus pools at 4x (60), and the same classic frame
    // came back twice as bright after a trip to the 3D views (out/fr3_lab1: mean luma 15 -> 32).
    // The classic view keeps the game's own lamps at every visit, as before the first V.
    if (!StreetPresentation()) return;
    if (!g_ground || !g_ground->Ready()) return;
    const Model* lamp = ModelForProp("lamp");
    if (!lamp) return;
    // Which post stands for which lamp: MapLampPosts() runs parallel to MapLamps(), with
    // the post moved to the kerb or a wall (FIX-PROPS) or NaN where none is drawn. Empty
    // until DrawProps has placed them: no pools before that, so a pool never jumps.
    const std::vector<gta2::Vec3>& lamps = MapLamps();
    const std::vector<gta2::Vec3>& posts = MapLampPosts();
    if (lamps.empty() || posts.size() != lamps.size()) return;
    static std::unordered_map<uint64_t, size_t> s_index;
    static const gta2::Vec3* s_indexed = nullptr;
    static size_t s_indexedCount = 0;
    if (s_indexed != lamps.data() || s_indexedCount != lamps.size()) {
        s_index.clear();
        for (size_t i = 0; i < lamps.size(); ++i) {
            const float at[3] = {lamps[i].x, lamps[i].y, lamps[i].z};
            uint64_t key = 0;
            if (MapLightKeyOf(at, &key)) s_index.emplace(key, i);
        }
        s_indexed = lamps.data();
        s_indexedCount = lamps.size();
    }
    const float reference = g_settings.emitterRadius > 0.0f ? g_settings.emitterRadius : 0.15f;
    const size_t count = g_working.size();
    for (size_t i = 0; i < count; ++i) {
        RemixLightDesc& d = g_working[i];
        if (d.source != kLightSourceGame || d.spot || d.explicitId) continue;
        uint64_t key = 0;
        if (!MapLightKeyOf(d.pos, &key)) continue;
        const auto found = s_index.find(key);
        if (found == s_index.end()) continue;
        const gta2::Vec3& post = posts[found->second];
        if (std::isnan(post.x)) continue;
        // The floor DrawProps stands the post on.
        float floor = 0.0f;
        if (!g_ground->SurfaceAt(post.x, post.z, d.pos[1] + 0.5f, &floor)) continue;
        LampHead head;
        if (!LampPostHead(*lamp, gta2::Vec3{post.x, d.pos[1], post.z}, floor, &head)) continue;
        const float lampIntensity = d.intensity;
        d.stagger = key;   // LIGHTING-V1: the lamp, its glow and its pool switch together
        // The glow in the glass. The lamp keeps its place (its identity is its position,
        // and a light seen to move turns into a car's); where the post was moved off it,
        // the lamp is put out and a copy glows in the moved lantern instead.
        const float off = std::sqrt((d.pos[0] - head.centre.x) * (d.pos[0] - head.centre.x) +
                                    (d.pos[1] - head.centre.y) * (d.pos[1] - head.centre.y) +
                                    (d.pos[2] - head.centre.z) * (d.pos[2] - head.centre.z));
        RemixLightDesc glow = d;
        const bool moved = off > 0.5f * head.glassRadius;
        glow.emitterRadius = (std::max)(0.005f, 0.8f * (moved ? 0.6f * head.glassRadius : head.glassRadius - off));
        // Its power kept: the same radiance from a smaller sphere would dim the glass.
        glow.intensity = lampIntensity * (reference / glow.emitterRadius) * (reference / glow.emitterRadius);
        if (moved) {
            glow.pos[0] = head.centre.x; glow.pos[1] = head.centre.y; glow.pos[2] = head.centre.z;
            d.intensity = 0.0f;   // under minIntensity: tracked, not drawn
        } else {
            d.emitterRadius = glow.emitterRadius;
            d.intensity = glow.intensity;
        }
        RemixLightDesc pool = glow;
        // FIX-REMIX-NIGHT-2: a lantern on a post is a white lamp whatever the map light it stands
        // for: a saturated colour (a sign's red, a neon green) poured down by the pool at 4x flooded
        // the paving and stairs under it in that colour. The pool is warm white at the light's own
        // luminance; the glow in the glass and the light itself keep their colour.
        if (g_signLights) {
            const float* c = d.rgb;
            const float top = (std::max)(c[0], (std::max)(c[1], c[2])), bottom = (std::min)(c[0], (std::min)(c[1], c[2]));
            if (top > 0.0f && (top - bottom) / top >= 0.45f && !SodiumLike(c)) {
                static const float kWarm[3] = {1.0f, 0.86f, 0.70f};
                const float luma = 0.2126f * c[0] + 0.7152f * c[1] + 0.0722f * c[2];
                const float lumaWarm = 0.2126f * kWarm[0] + 0.7152f * kWarm[1] + 0.0722f * kWarm[2];
                for (int k = 0; k < 3; ++k) pool.rgb[k] = kWarm[k] * luma / lumaWarm;
            }
        }
        // LIGHTING-V1 (gate B: a lamp threw a crisp, long, sun-like shadow of a van across the plaza): the pool's emitter
        // was capped by the lantern glass (0.018 block), a point source; it now sits under the dish at 0.12, so its
        // shadows are soft. Its power is kept by the (reference / r)^2 term below.
        const float r = kLampPoolEmitter;
        pool.emitterRadius = r;
        pool.pos[0] = head.centre.x;
        pool.pos[1] = head.dishBottom - r - kLampPoolGap;
        pool.pos[2] = head.centre.z;
        pool.intensity = lampIntensity * kLampPoolGain * static_cast<float>(g_poolGainPct >= 0 ? g_poolGainPct : kPoolGainDefaultPct) / 100.0f *
                         (reference / r) * (reference / r);
        {
            // Shining down (see poolConeDeg in remix_lights.h).
            const float cone = g_poolCone >= 0 ? static_cast<float>(g_poolCone) : g_settings.poolConeDeg;
            if (cone > 0.0f && cone < 180.0f) {
                pool.spot = true;
                pool.dir[0] = 0.0f; pool.dir[1] = -1.0f; pool.dir[2] = 0.0f;
                pool.coneAngleDeg = cone;
                pool.coneSoftness = 0.5f;
            }
        }
        if ((g_probeMask >> 6) & 1) pool.intensity = 0.0f;   // [devtools] remix_lights_probe bit 6: the pools out
        if ((g_probeMask >> 7) & 1) { glow.intensity = 0.0f; if (!moved) d.intensity = 0.0f; }   // bit 7: the lanterns out
        // d is not used past here (push_back may move the vector).
        if (moved) g_working.push_back(glow);
        g_working.push_back(pool);
        ++g_lampPoolsLastFrame;
    }
}

}  // namespace

void LightsReconcile() {
    ++g_frame;
    // [devtools] set_hour_tenths=N (REMIX-3, a developer check for the lights): the
    // clock is set to N/10 hours whenever the value changes, re-read once a second,
    // so one scripted Remix session can show the same street by day, at dusk and at
    // night. -1 (or absent) leaves the clock alone.
    if ((g_frame % 60u) == 1u) {
        static char ini[MAX_PATH] = "";
        static int lastHour = -1;
        if (!ini[0]) {
            GetModuleFileNameA(nullptr, ini, MAX_PATH);
            char* slash = strrchr(ini, '\\');
            if (slash) strcpy(slash + 1, "gta2dx9.ini"); else strcpy(ini, "gta2dx9.ini");
        }
        const int tenths = GetPrivateProfileIntA("devtools", "set_hour_tenths", -1, ini);
        if (tenths >= 0 && tenths != lastHour) {
            TimeOfDaySetHour(static_cast<float>(tenths) / 10.0f);
            Log("devtools: clock set to %.1f h", static_cast<float>(tenths) / 10.0f);
        }
        lastHour = tenths;
        // [devtools] remix_lights_off=1: none of our lights reach Remix (the game's lamps,
        // the far lamps, the synthetic lights), to see what lights a scene without them.
        static int lastOff = -1;
        const int off = GetPrivateProfileIntA("devtools", "remix_lights_off", 0, ini);
        if (off != lastOff) {
            if (lastOff >= 0 || off) { g_settings.enabled = off == 0; Log("devtools: our Remix lights %s", off ? "off" : "on"); }
            lastOff = off;
        }
        {
            const int mask = GetPrivateProfileIntA("devtools", "remix_lights_probe", 0, ini);
            if (mask != g_probeMask) { g_probeMask = mask; Log("devtools: remix lights probe mask %d", mask); }
            const int cone = GetPrivateProfileIntA("devtools", "remix_pool_cone", -1, ini);
            if (cone != g_poolCone) { g_poolCone = cone; Log("devtools: lamp pools in a %d deg cone", cone); }
            const int gainPct = GetPrivateProfileIntA("devtools", "remix_pool_gain_pct", -1, ini);
            if (gainPct != g_poolGainPct) { g_poolGainPct = gainPct; g_reliftPending = true; Log("devtools: lamp pools at %d%% (-1: %d%%)", gainPct, kPoolGainDefaultPct); }
            const int fill = GetPrivateProfileIntA("devtools", "remix_night_fill_milli", -1, ini);
            if (fill != g_nightFillMilli) { g_nightFillMilli = fill; Log("devtools: night sky fill %d/1000 (-1: the setting %.3f)", fill, g_settings.nightSkyFill); }
            const int tOld = GetPrivateProfileIntA("devtools", "remix_traffic_old", 0, ini);
            const int tPct = GetPrivateProfileIntA("devtools", "remix_traffic_pct", 35, ini);
            const int tDay = GetPrivateProfileIntA("devtools", "remix_traffic_day_pct", 10, ini);
            if (tOld != g_trafficOld || tPct != g_trafficPct || tDay != g_trafficDayPct) {
                g_trafficOld = tOld; g_trafficPct = tPct; g_trafficDayPct = tDay; g_reliftPending = true;
                Log("devtools: junction signals %s, %d%% at night, %d%% of that by day", tOld ? "as before" : "shaped", tPct, tDay);
            }
            const int dusk = GetPrivateProfileIntA("devtools", "remix_dusk_fill_deg", -1, ini);
            if (dusk != g_duskFillDeg) { g_duskFillDeg = dusk; Log("devtools: dusk fill from %d deg (-1: the setting %.1f)", dusk, g_settings.duskFillDeg); }
            const int wn = GetPrivateProfileIntA("devtools", "remix_wide_neon_tenths", -1, ini);
            if (wn != g_wideNeonTenths) { g_wideNeonTenths = wn; g_reliftPending = true; Log("devtools: wide neon warm-white from %d tenths of a tile (-1 setting, 0 off)", wn); }
            static int lastBulb = -2;
            const int bulb = GetPrivateProfileIntA("devtools", "remix_bulb_pct", -1, ini);
            if (bulb != lastBulb) {
                lastBulb = bulb; SyntheticSetStreetBulbPct(bulb >= 0 ? bulb : 100);
                Log("devtools: street-view headlamp/beacon emitters at %d%% (-1: default 100)", bulb);
            }
            static int lastBeam = -2, lastCarLamps = -2;
            const int beam = GetPrivateProfileIntA("devtools", "remix_beam_mode", -1, ini);
            if (beam != lastBeam) {
                lastBeam = beam; SyntheticSetStreetBeamMode(beam >= 0 ? beam : 1);
                Log("devtools: street-view headlamp beams mode %d (-1: default 1; 0 = the game's lamp bits, emitter inside the body)", beam);
            }
            // FIX-REMIX-NIGHT-8 probe: [renderer] car_lamps live (-1: leave it as the ini started it).
            const int carLamps = GetPrivateProfileIntA("devtools", "remix_car_lamps", -1, ini);
            if (carLamps != lastCarLamps) {
                if (carLamps >= 0) SetCarLamps(carLamps);
                else if (lastCarLamps >= 0) SetCarLamps(GetPrivateProfileIntA("renderer", "car_lamps", 1, ini));
                lastCarLamps = carLamps;
                Log("devtools: car body lamps %d (-1: the [renderer] setting)", carLamps);
            }
            const int lbw = GetPrivateProfileIntA("devtools", "remix_low_bounce_warm", 1, ini);
            if (lbw != g_lowBounceWarm) { g_lowBounceWarm = lbw; Log("devtools: low-sun golden bounce %s", lbw ? "on" : "off"); }
            const int tl = GetPrivateProfileIntA("devtools", "remix_traffic_lift_milli", 650, ini);
            if (tl != g_trafficLiftMilli) { g_trafficLiftMilli = tl; g_reliftPending = true; Log("devtools: junction signals lifted %d/1000 tile", tl); }
            static int lastPuff = -1;
            const int puff = GetPrivateProfileIntA("devtools", "remix_puff_mode", 4, ini);   // FIX-FX-6: 4 soft by default
            if (puff != lastPuff) {
                lastPuff = puff; VehicleFxSetRemixPuffMode(puff);
                Log("devtools: Remix smoke puffs mode %d (0 dither, 1 wisps, 2 none, 3 wisps without exhaust, 4 soft blended)", puff);
            }
            static int lastTones = -1;
            const int tones = GetPrivateProfileIntA("devtools", "remix_puff_tones", 1, ini);
            if (tones != lastTones) {
                lastTones = tones; VehicleFxSetRemixPuffTones(tones);
                Log("devtools: Remix smoke puff grey tones %s", tones ? "on (dark smoke dark)" : "off (old: every puff light)");
            }
            static int lastFlatLamps = -1;
            const int flatLamps = GetPrivateProfileIntA("devtools", "remix_flat_lamps", 0, ini);
            if (flatLamps != lastFlatLamps) {
                lastFlatLamps = flatLamps; SetRemixFlatLamps(flatLamps);
                Log("devtools: Remix flat lamp quads under 3D car models %s", flatLamps ? "on (old: white squares on the road)" : "off");
            }
            static int lastSpecks = -1;
            const int specks = GetPrivateProfileIntA("devtools", "remix_game_specks", 0, ini);
            if (specks != lastSpecks) {
                lastSpecks = specks; SetRemixGameSpecks(specks);
                Log("devtools: Remix game smoke specks (< 0.06 block) %s", specks ? "on (old: dotted bead columns)" : "off");
            }
            {
                // FIX-REMIX-NIGHT-7: the night palette live (see g_moonRgb).
                auto rgbKey = [&](const char* key, float* out, const float* def) {
                    char buf[64] = {};
                    GetPrivateProfileStringA("devtools", key, "", buf, sizeof buf, ini);
                    float v[3] = {def[0], def[1], def[2]};
                    int a = 0, b = 0, c = 0;
                    if (buf[0] && sscanf(buf, "%d,%d,%d", &a, &b, &c) == 3) { v[0] = a / 1000.0f; v[1] = b / 1000.0f; v[2] = c / 1000.0f; }
                    if (v[0] != out[0] || v[1] != out[1] || v[2] != out[2]) {
                        for (int i = 0; i < 3; ++i) out[i] = v[i];
                        Log("devtools: %s %.3f,%.3f,%.3f", key, out[0], out[1], out[2]);
                        return true;
                    }
                    return false;
                };
                static const float kMoonDef[3] = {0.36f, 0.48f, 1.0f};
                static const float kSodiumDef[3] = {1.0f, 0.74f, 0.46f};
                rgbKey("remix_moon_rgb", g_moonRgb, kMoonDef);
                if (rgbKey("remix_sodium_rgb", g_sodiumRgb, kSodiumDef)) g_reliftPending = true;
                const int mf = GetPrivateProfileIntA("devtools", "remix_moon_fill_milli", -1, ini);
                if (mf != g_moonFillMilli) { g_moonFillMilli = mf; Log("devtools: night moon fill %d/1000 (-1: 140, 0: the NIGHT-6 fill)", mf); }
                const int sp = GetPrivateProfileIntA("devtools", "remix_sodium_pct", 100, ini);
                if (sp != g_sodiumPct) { g_sodiumPct = sp; g_reliftPending = true; Log("devtools: sodium lamps %d%% in the street views", sp); }
            }
            const int sodium = GetPrivateProfileIntA("devtools", "remix_sodium_white", 1, ini);
            if (sodium != g_sodiumWhite) { g_sodiumWhite = sodium; g_reliftPending = true; Log("devtools: sodium lamps as amber white %s", sodium ? "on" : "off"); }
            const int dayFill = GetPrivateProfileIntA("devtools", "remix_day_fill_milli", -1, ini);
            if (dayFill != g_dayFillMilli) { g_dayFillMilli = dayFill; Log("devtools: day bounce fill %d/1000 (-1: the setting %.3f)", dayFill, g_settings.dayBounceFill); }
            const int win = GetPrivateProfileIntA("devtools", "remix_window_pct", 100, ini);
            const int winOut = GetPrivateProfileIntA("devtools", "remix_window_out_milli", 250, ini);
            const int sf = GetPrivateProfileIntA("devtools", "remix_sign_flood_pct", 100, ini);
            if (sf != g_signFloodPct) { g_signFloodPct = sf; Log("devtools: rooftop sign floodlights %d%% (0 off)", sf); }
            const int gp = GetPrivateProfileIntA("devtools", "remix_gantry_pct", 100, ini);
            if (gp != g_gantryPct) { g_gantryPct = gp; Log("devtools: gantry signal lens glow %d%% (0 off)", gp); }
            if (win != g_windowPct || winOut != g_windowOutMilli) {
                g_windowPct = win; g_windowOutMilli = winOut;
                Log("devtools: lit-window room lights %d%% (0 off), %d/1000 tile in front of the pane", win, winOut);
            }
            const int sw = GetPrivateProfileIntA("devtools", "remix_sign_wall", 1, ini);
            const int sr = GetPrivateProfileIntA("devtools", "remix_sign_red_pct", 35, ini);
            if (sw != g_signWall || sr != g_signRedPct) {
                g_signWall = sw; g_signRedPct = sr; g_reliftPending = true;
                Log("devtools: sign lights on a wall %s, %d%% of their own colour kept", sw ? "shine away from it" : "as before", sr);
            }
            const int signs = GetPrivateProfileIntA("devtools", "remix_sign_lights", 1, ini);
            if (signs != g_signLights) { g_signLights = signs; g_reliftPending = true; Log("devtools: red/pink map lights as signs %s", signs ? "on" : "off"); }
        }
        // [devtools] remix_config=key=value|key=value: pushed to the runtime whenever the
        // line changes (A/B checks of runtime options within one session).
        static char lastConfig[512] = "";
        char config[512] = "";
        GetPrivateProfileStringA("devtools", "remix_config", "", config, sizeof(config), ini);
        if (strcmp(config, lastConfig) != 0) {
            strcpy(lastConfig, config);
            char work[512];
            strcpy(work, config);
            for (char* item = strtok(work, "|"); item; item = strtok(nullptr, "|")) {
                char* eq = strchr(item, '=');
                if (!eq) continue;
                *eq = 0;
                const bool ok = RemixSetConfig(item, eq + 1);
                Log("devtools: remix config %s = %s (%s)", item, eq + 1, ok ? "set" : "refused");
            }
        }
    }
    RefreshClassDaylight();

    if (!g_settings.enabled) {
        if (!g_tracked.empty() || g_ambientHandle) ClearAll();
        g_stats.tracked = 0;
        g_stats.drawnLastFrame = 0;
        g_stats.submittedLastFrame = 0;
        return;
    }

    // Did the game open a list since the last time round? In menus and on load
    // screens gbh_ResetLights is never called, and the previous frame's lights
    // must not linger there. A frame of slack absorbs any jitter between the
    // game's world pass and ours.
    const bool fresh = g_collects != g_collectsAtLastReconcile;
    if (fresh) {
        g_collectsAtLastReconcile = g_collects;
        g_framesSinceCollect = 0;
    } else {
        ++g_framesSinceCollect;
    }
    const bool listValid = fresh || g_framesSinceCollect <= kExpireFrames;
    if (!listValid) g_pending.clear();

    // The game's list plus the ones we invented. Merged into one working set so
    // both go through the same matching, handle and expiry path.
    g_working.clear();
    g_working.insert(g_working.end(), g_pending.begin(), g_pending.end());
    g_working.insert(g_working.end(), g_extra.begin(), g_extra.end());
    g_extra.clear();
    FitLampsToPosts();

    g_stats.submittedLastFrame = static_cast<int>(g_working.size());
    g_stats.suppressedByClass = 0;
    g_stats.suppressedByDaylight = 0;
    g_stats.suppressedByIntensity = 0;

    // --- Match this frame's list onto the tracked set ---------------------
    //
    // Three passes, most specific first. A light that carries its own identity
    // takes it. Otherwise position, which is exact and unique for almost every
    // static light and keeps a traffic light's identity through a colour change.
    // Whatever is left has moved - a headlight, a bullet - and goes to the
    // nearest tracked light of the same kind, colour and reach.
    std::vector<bool> claimed(g_tracked.size(), false);
    std::vector<int> match(g_working.size(), -1);

    std::unordered_map<uint64_t, size_t> byExplicitId;
    std::unordered_multimap<uint64_t, size_t> byPosition;
    byPosition.reserve(g_tracked.size() * 2);
    for (size_t i = 0; i < g_tracked.size(); ++i) {
        if (g_tracked[i].def.explicitId) byExplicitId[g_tracked[i].def.explicitId] = i;
        byPosition.emplace(PositionKey(g_tracked[i].def), i);
    }

    for (size_t p = 0; p < g_working.size(); ++p) {
        if (!g_working[p].explicitId) continue;
        auto it = byExplicitId.find(g_working[p].explicitId);
        if (it == byExplicitId.end() || claimed[it->second]) continue;
        match[p] = static_cast<int>(it->second);
        claimed[it->second] = true;
    }

    for (size_t p = 0; p < g_working.size(); ++p) {
        if (match[p] >= 0 || g_working[p].explicitId) continue;
        const uint64_t key = PositionKey(g_working[p]);
        auto range = byPosition.equal_range(key);
        int fallback = -1;
        for (auto it = range.first; it != range.second; ++it) {
            const size_t i = it->second;
            if (claimed[i] || g_tracked[i].def.explicitId) continue;
            if (SameColourAndRadius(g_tracked[i].def, g_working[p])) {
                match[p] = static_cast<int>(i);
                break;
            }
            // Same spot but recoloured - a traffic light changing phase. Take it
            // only if no exact candidate turns up.
            if (fallback < 0 && g_tracked[i].def.source == g_working[p].source) {
                fallback = static_cast<int>(i);
            }
        }
        if (match[p] < 0 && fallback >= 0) match[p] = fallback;
        if (match[p] >= 0) claimed[match[p]] = true;
    }

    for (size_t p = 0; p < g_working.size(); ++p) {
        if (match[p] >= 0 || g_working[p].explicitId) continue;
        int best = -1;
        float bestDistance = kMoveMatchDistance * kMoveMatchDistance;
        for (size_t i = 0; i < g_tracked.size(); ++i) {
            if (claimed[i] || g_tracked[i].def.explicitId) continue;
            if (!SameColourAndRadius(g_tracked[i].def, g_working[p])) continue;
            const float d2 = DistanceSquared(g_tracked[i].def.pos, g_working[p].pos);
            if (d2 < bestDistance) {
                bestDistance = d2;
                best = static_cast<int>(i);
            }
        }
        if (best >= 0) {
            match[p] = best;
            claimed[best] = true;
        }
    }

    // --- Fold the matches in ----------------------------------------------
    for (size_t p = 0; p < g_working.size(); ++p) {
        if (match[p] >= 0) {
            RemixTrackedLight& t = g_tracked[match[p]];
            if (!SameDesc(t.def, g_working[p])) {
                // A light that has been seen somewhere else is a moving one, and
                // moving lights get no persistent override key: there is nothing
                // stable to hang one on.
                if (t.def.pos[0] != g_working[p].pos[0] || t.def.pos[1] != g_working[p].pos[1]
                    || t.def.pos[2] != g_working[p].pos[2]) {
                    t.moving = true;
                    t.key = 0;
                }
                t.def = g_working[p];
                // A traffic light changing phase changes colour, and a light
                // that has just been seen to move has become a vehicle lamp, so
                // this is re-read rather than settled once at creation.
                t.gameClass = ClassifyGameLight(t.def, t.moving);
                t.dirty = true;
            }
            t.lastSeenFrame = g_frame;
            continue;
        }
        RemixTrackedLight t;
        t.id = g_nextId++;
        t.def = g_working[p];
        // Only the game's own static lights get an identity that survives a
        // restart. Ours are transient by nature and there is nothing to pin one
        // to; the per-category controls are what tunes those.
        t.key = t.def.source == kLightSourceGame && !t.def.explicitId ? StableKey(t.def) : 0;
        t.moving = t.def.explicitId != 0;
        t.gameClass = ClassifyGameLight(t.def, t.moving);
        t.lastSeenFrame = g_frame;
        t.firstFrame = g_frame;
        g_tracked.push_back(t);
    }

    // --- Expire ------------------------------------------------------------
    for (size_t i = 0; i < g_tracked.size();) {
        // A muzzle flash, a bullet or a spark is over the moment the game stops listing it: the
        // frame of slack that keeps a street lamp from flickering would hold a flash on for
        // two frames after its last.
        const uint8_t source = g_tracked[i].def.source;
        const uint32_t slack = (source >= kLightSourceMuzzle && source <= kLightSourceSpark) ? 0 : kExpireFrames;
        if (g_tracked[i].lastSeenFrame + slack < g_frame) {
            DestroyHandle(g_tracked[i].handle);
            g_tracked[i] = g_tracked.back();
            g_tracked.pop_back();
        } else {
            ++i;
        }
    }

    // Global tuning is not attached to any one light, so a change here means
    // every light has to be described again. Dragging a slider changes it on
    // most frames; redefining hundreds of lights that often would flood the
    // bridge, so the work is coalesced into one pass every 50 ms. That is still
    // twenty updates a second, which reads as immediate.
    const uint32_t now = GetTickCount();
    if (!SameSettings(g_settings, g_applied)) {
        g_applied = g_settings;
        if (!g_settingsDirtyAt) g_settingsDirtyAt = now ? now : 1;
    }
    bool applyAll = false;
    if (g_settingsDirtyAt && now - g_settingsDirtyAt >= 50) {
        g_settingsDirtyAt = 0;
        applyAll = true;
    }
    // A new map's lamps and floors: lift every light again from those.
    if (g_reliftPending) {
        g_reliftPending = false;
        applyAll = true;
    }
    // FIX-REMIX-NIGHT-2: the sign rule (Describe) differs between the classic view and the street
    // views: describe every light again when the picture changes between them.
    {
        static int lastStreet = -1;
        const int street = StreetPresentation() ? 1 : 0;
        if (street != lastStreet) { if (lastStreet >= 0) applyAll = true; lastStreet = street; }
    }

    // --- Create, redefine, suppress ----------------------------------------
    g_stats.suppressedByOverride = 0;
    g_stats.moving = 0;
    for (int i = 0; i < kLightSourceCount; ++i) g_stats.bySource[i] = 0;
    for (int i = 0; i < kGameLightClassCount; ++i) {
        g_stats.byClass[i] = 0;
        g_stats.litByClass[i] = 0;
    }
    for (RemixTrackedLight& t : g_tracked) {
        if (t.moving) ++g_stats.moving;
        if (t.def.source < kLightSourceCount) ++g_stats.bySource[t.def.source];
        if (t.def.source == kLightSourceGame && t.gameClass < kGameLightClassCount) {
            ++g_stats.byClass[t.gameClass];
            if (LightDaylight(t) > kGateFloor
                && g_settings.gameClass[t.gameClass].enabled) {
                ++g_stats.litByClass[t.gameClass];
            }
        }
        // The sun has moved this light far enough to be worth resending (LIGHTING-V1: each light by its own
        // staggered time, so the street comes on lamp by lamp).
        float gameDaylight = 1.0f;
        if (t.def.source == kLightSourceGame) {
            gameDaylight = LightDaylight(t);
            if (g_classMoved[t.gameClass] || t.gateApplied < 0.0f || std::fabs(gameDaylight - t.gateApplied) >= kGateStep ||
                (gameDaylight <= kGateFloor) != (t.gateApplied <= kGateFloor)) {
                t.gateApplied = gameDaylight;
                t.dirty = true;
            }
        }

        const RemixLightOverride* ov = LightsFindOverride(t.key);
        const bool identified = t.key != 0 && t.key == g_identify;

        bool suppressed = false;
        if (ov && ov->disabled && !identified) {
            ++g_stats.suppressedByOverride;
            suppressed = true;
        } else if (t.def.source == kLightSourceGame
                   && (!(t.moving ? g_settings.injectMoving : g_settings.injectStatic)
                       || !g_settings.gameClass[t.gameClass].enabled
                       || gameDaylight <= kGateFloor)) {
            // Only the game's own lights are filtered this way. Ours are gated by
            // their category, upstream, and never reach here when switched off.
            // A light the sun has put out is dropped rather than dimmed to
            // nothing: an invisible light is still a handle on the far side of
            // the bridge and still a light the path tracer samples.
            ++g_stats.suppressedByClass;
            if (gameDaylight <= kGateFloor) ++g_stats.suppressedByDaylight;
            suppressed = true;
        } else if (t.def.intensity < g_settings.minIntensity && !identified) {
            // The game blinks a light by taking its intensity to zero, so this is
            // how a traffic light stops glowing on all three colours at once.
            ++g_stats.suppressedByIntensity;
            suppressed = true;
        }

        if (suppressed) {
            DestroyHandle(t.handle);
            t.drawn = false;
            t.dirty = true;   // so it comes straight back when it is allowed to
            continue;
        }

        if (!t.handle || t.dirty || applyAll) {
            if (!t.handle && t.applyFailed) continue;  // refused once; do not hammer the bridge
            Apply(t);
            t.dirty = false;
        }
    }

    ApplyAmbientFill();

    g_stats.tracked = static_cast<int>(g_tracked.size());
    g_stats.collectsSeen = g_collects;
    g_stats.framesSinceCollect = g_framesSinceCollect;

    g_stats.minIntensitySeen = g_tracked.empty() ? 0.0f : 1.0f;
    g_stats.maxIntensitySeen = 0.0f;
    g_stats.atFullIntensity = 0;
    for (const RemixTrackedLight& t : g_tracked) {
        if (t.def.intensity < g_stats.minIntensitySeen) g_stats.minIntensitySeen = t.def.intensity;
        if (t.def.intensity > g_stats.maxIntensitySeen) g_stats.maxIntensitySeen = t.def.intensity;
        if (t.def.intensity >= 1.0f) ++g_stats.atFullIntensity;
    }

    // The first light through is the moment the whole path is proven, and its
    // position is the one thing that cannot be checked from inside the game: a
    // wrong axis mapping would light the far side of the city with no error
    // anywhere. Logged once, then periodically, so it can be lined up against
    // the camera bounds already in the log.
    static bool announced = false;
    if (!announced && !g_tracked.empty()) {
        announced = true;
        const RemixTrackedLight& t = g_tracked.front();
        Log("remix lights: first light -- pos %.2f,%.2f,%.2f rgb %.2f,%.2f,%.2f intensity %.2f "
            "reach %.2f tiles (%d submitted, Remix %s)",
            t.def.pos[0], t.def.pos[1], t.def.pos[2], t.def.rgb[0], t.def.rgb[1], t.def.rgb[2],
            t.def.intensity, t.def.radius, g_stats.submittedLastFrame,
            RemixApiAvailable() ? "available" : "ABSENT");
    }
    // GTA2DX9_LOG_REMIX_LIGHTS=1: every 256 frames, the ten lights that light the
    // ground under the eye most (radiance over the squared distance from the point
    // below the eye), to find which lamp makes a scene look floodlit (REMIX-3).
    static int logStrong = -1;
    if (logStrong < 0) { const char* e = getenv("GTA2DX9_LOG_REMIX_LIGHTS"); logStrong = e && *e == '1' ? 1 : 0; }
    if (logStrong && g_haveEye && (g_frame & 0xFF) == 0x80) {
        struct Strong { float score, scale, d; const RemixTrackedLight* t; float pos[3]; };
        std::vector<Strong> list;
        const float gx = g_lastEye[0], gy = g_lastEye[1] - 1.5f, gz = g_lastEye[2];
        for (const RemixTrackedLight& t : g_tracked) {
            if (!t.handle || t.def.spot) continue;   // the cones (headlights) aim along the road
            Strong s{}; float rgb[3];
            Describe(t, s.pos, rgb, &s.scale);
            const float lum = 0.2126f * rgb[0] + 0.7152f * rgb[1] + 0.0722f * rgb[2];
            const float dx = s.pos[0] - gx, dy = s.pos[1] - gy, dz = s.pos[2] - gz;
            const float d2 = dx * dx + dy * dy + dz * dz;
            s.d = std::sqrt(d2); s.score = s.scale * lum / (std::max)(d2, 0.25f); s.t = &t;
            list.push_back(s);
        }
        std::sort(list.begin(), list.end(), [](const Strong& a, const Strong& b) { return a.score > b.score; });
        Log("remix lights: strongest at the eye %.1f,%.1f,%.1f (%zu lit):", g_lastEye[0], g_lastEye[1], g_lastEye[2], list.size());
        for (size_t i = 0; i < list.size() && i < 10; ++i) {
            const Strong& s = list[i];
            Log("  #%zu %s/%s pos %.2f,%.2f,%.2f (game %.2f,%.2f,%.2f) rgb %.2f,%.2f,%.2f int %.2f reach %.2f scale %.1f emitter %.2f d %.1f score %.2f%s",
                i, LightSourceName(s.t->def.source), s.t->def.source == kLightSourceGame ? GameLightClassName(s.t->gameClass) : "-",
                s.pos[0], s.pos[1], s.pos[2], s.t->def.pos[0], s.t->def.pos[1], s.t->def.pos[2],
                s.t->def.rgb[0], s.t->def.rgb[1], s.t->def.rgb[2], s.t->def.intensity, s.t->def.radius, s.scale,
                s.t->def.emitterRadius, s.d, s.score, s.t->moving ? " moving" : "");
        }
    }
    // GTA2DX9_LOG_LIGHTS_EVERY=N: this line every N frames instead of every 256 (the
    // view-switch continuity check reads the light set frame by frame, REMIX-3D-PARITY).
    static int logEvery = -1;
    if (logEvery < 0) { const char* e = getenv("GTA2DX9_LOG_LIGHTS_EVERY"); logEvery = e && atoi(e) > 0 ? atoi(e) : 256; }
    if ((g_frame % static_cast<uint32_t>(logEvery)) == 0 && (g_stats.submittedLastFrame || g_stats.tracked)) {
        // A map lamp counted as moving would be lit and gated as a car's.
        int movingLamps = 0;
        for (const RemixTrackedLight& t : g_tracked) {
            if (t.moving && t.def.source == kLightSourceGame && IsMapLight(t.def.pos)) ++movingLamps;
        }
        Log("remix lights @%u: submitted %d, tracked %d (%d moving, %d of them map lamps), "
            "drawn %d, ambient %.3f, created %u updated %u destroyed %u failures %u, far %d x%.2f",
            g_frame, g_stats.submittedLastFrame, g_stats.tracked, g_stats.moving, movingLamps,
            g_stats.drawnLastFrame, g_ambient, g_stats.created, g_stats.updated,
            g_stats.destroyed, g_stats.applyFailures, g_farLampsLastFrame, g_farLampWeight);
    }
}

void LightsDraw() {
    const remixapi_Interface* api = RemixApi();
    if (!api || !g_settings.enabled) {
        g_stats.drawnLastFrame = 0;
        return;
    }
    int drawn = 0;
    for (RemixTrackedLight& t : g_tracked) {
        if (!t.handle) {
            t.drawn = false;
            continue;
        }
        api->DrawLightInstance(static_cast<remixapi_LightHandle>(t.handle));
        t.drawn = true;
        ++drawn;
    }
    if (g_ambientHandle) {
        api->DrawLightInstance(static_cast<remixapi_LightHandle>(g_ambientHandle));
    }
    g_stats.drawnLastFrame = drawn;
}

const std::vector<RemixTrackedLight>& LightsTracked() { return g_tracked; }

RemixLightOverride* LightsFindOverride(uint64_t key) {
    if (key == 0) return nullptr;
    auto it = g_overrides.find(key);
    return it == g_overrides.end() ? nullptr : &it->second;
}

RemixLightOverride& LightsEditOverride(uint64_t key) {
    g_overridesDirty = true;
    return g_overrides[key];
}

void LightsEraseOverride(uint64_t key) {
    if (g_overrides.erase(key)) g_overridesDirty = true;
}

void LightsClearOverrides() {
    if (!g_overrides.empty()) {
        g_overrides.clear();
        g_overridesDirty = true;
    }
}

const std::map<uint64_t, RemixLightOverride>& LightsOverrides() { return g_overrides; }
bool LightsOverridesDirty() { return g_overridesDirty; }
const char* LightsOverridePath() { return g_overridePath; }

void LightsInvalidate(uint64_t key) {
    for (RemixTrackedLight& t : g_tracked) {
        if (key == 0 || t.key == key) {
            t.dirty = true;
            t.applyFailed = false;
        }
    }
}

void LightsIdentify(uint64_t key) {
    if (g_identify == key) return;
    // Both the old and the new light need redefining: one to drop the highlight,
    // one to take it.
    for (RemixTrackedLight& t : g_tracked) {
        if (t.key == g_identify || t.key == key) {
            t.dirty = true;
            t.applyFailed = false;
        }
    }
    g_identify = key;
}

uint64_t LightsIdentified() { return g_identify; }

const RemixLightStats& LightsStats() { return g_stats; }

void LightsLoadOverrides() {
    g_overrides.clear();
    g_overridesDirty = false;

    FILE* f = fopen(g_overridePath, "r");
    if (!f) return;   // first run, not a failure

    RemixLightOverride* current = nullptr;
    char line[512];
    while (fgets(line, sizeof(line), f)) {
        char* s = TrimInPlace(line);
        if (!*s || *s == ';' || *s == '#') continue;
        if (*s == '[') {
            char* close = strchr(s, ']');
            if (!close) continue;
            *close = '\0';
            const uint64_t key = _strtoui64(s + 1, nullptr, 16);
            current = key ? &g_overrides[key] : nullptr;
            continue;
        }
        char* eq = strchr(s, '=');
        if (!eq || !current) continue;
        *eq = '\0';
        const char* name = TrimInPlace(s);
        char* value = TrimInPlace(eq + 1);

        if (_stricmp(name, "Disabled") == 0) {
            current->disabled = atoi(value) != 0;
        } else if (_stricmp(name, "Intensity") == 0) {
            current->intensity = static_cast<float>(atof(value));
        } else if (_stricmp(name, "Offset") == 0) {
            sscanf(value, "%f %f %f", &current->offset[0], &current->offset[1],
                   &current->offset[2]);
        } else if (_stricmp(name, "Color") == 0) {
            current->recolor = true;
            sscanf(value, "%f %f %f", &current->color[0], &current->color[1], &current->color[2]);
        } else if (_stricmp(name, "EmitterRadius") == 0) {
            current->emitterRadius = static_cast<float>(atof(value));
        } else if (_stricmp(name, "Note") == 0) {
            current->note = value;
        }
    }
    fclose(f);
    Log("remix lights: loaded %d override(s) from %s", static_cast<int>(g_overrides.size()),
        g_overridePath);
}

void LightsSaveOverrides() {
    // An entry carrying nothing is indistinguishable from no entry, and keeping
    // it would grow the file every time a light is merely inspected.
    for (auto it = g_overrides.begin(); it != g_overrides.end();) {
        it = it->second.IsDefault() ? g_overrides.erase(it) : ++it;
    }

    FILE* f = fopen(g_overridePath, "w");
    if (!f) {
        Log("remix lights: could not write %s", g_overridePath);
        return;
    }

    fprintf(f, "; GTA2 RTX Remix -- per-light overrides.\n");
    fprintf(f, ";\n");
    fprintf(f, "; Each section is a hash of one light's district, position and reach, so an\n");
    fprintf(f, "; entry keeps pointing at the same lamp across sessions. Lights that move --\n");
    fprintf(f, "; headlights, muzzle flashes -- have no stable identity and cannot be given\n");
    fprintf(f, "; one of these; tune those with the global sliders instead.\n");
    fprintf(f, ";\n");
    fprintf(f, "; Written only when Save is pressed in the F4 menu, so experiments are not\n");
    fprintf(f, "; kept by accident. Hand edits are picked up by Reload; anything left at its\n");
    fprintf(f, "; default is dropped.\n");
    fprintf(f, ";\n");
    fprintf(f, ";   Disabled=1              remove the light from the scene\n");
    fprintf(f, ";   Intensity=1.500         multiplier on the game's brightness\n");
    fprintf(f, ";   Offset=0 0.5 0          world-space nudge, in map tiles\n");
    fprintf(f, ";   Color=1.0 0.8 0.6       replaces the game's colour, 0..1\n");
    fprintf(f, ";   EmitterRadius=0.30      sphere size for this light only, in tiles\n");
    fprintf(f, ";   Note=text               free text, shown in the menu\n");

    for (const auto& entry : g_overrides) {
        const RemixLightOverride& ov = entry.second;
        fprintf(f, "\n[%016llX]\n", static_cast<unsigned long long>(entry.first));
        if (!ov.note.empty()) fprintf(f, "Note=%s\n", ov.note.c_str());
        if (ov.disabled) fprintf(f, "Disabled=1\n");
        if (ov.intensity != 1.0f) fprintf(f, "Intensity=%.3f\n", ov.intensity);
        if (ov.offset[0] || ov.offset[1] || ov.offset[2]) {
            fprintf(f, "Offset=%.3f %.3f %.3f\n", ov.offset[0], ov.offset[1], ov.offset[2]);
        }
        if (ov.recolor) {
            fprintf(f, "Color=%.4f %.4f %.4f\n", ov.color[0], ov.color[1], ov.color[2]);
        }
        if (ov.emitterRadius > 0.0f) fprintf(f, "EmitterRadius=%.3f\n", ov.emitterRadius);
    }
    fclose(f);
    g_overridesDirty = false;
    Log("remix lights: saved %d override(s) to %s", static_cast<int>(g_overrides.size()),
        g_overridePath);
}

}  // namespace gta2dx9
