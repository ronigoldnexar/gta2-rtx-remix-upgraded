#include "remix_lights.h"

#include "ground.h"
#include "log.h"
#include "model_store.h"
#include "remix_api.h"
#include "time_of_day.h"

#include "../../src/gta2_map.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unordered_map>
#include <unordered_set>

namespace gta2dx9 {
namespace {

RemixLightSettings g_settings;
const GroundSampler* g_ground = nullptr;
std::unordered_set<uint64_t> g_mapLights;   // MapLightKey of every lamp in the map file
std::unordered_set<uint64_t> g_listedMapKeys;   // the map lamps the game listed in its last list
struct MapLampRecord { float pos[3]; float rgb[3]; float intensity; float radius; uint64_t key; };
std::vector<MapLampRecord> g_mapLampRecords;   // every steady lamp of the map file, decoded like the game's
int g_farLampsLastFrame = 0;
float g_farLampWeight = 0.0f;   // this frame's fade of the far lamps (0 when none were submitted)
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
constexpr float kLampPoolEmitter = 0.05f;          // tiles; less on a short post
constexpr float kLampPoolGap = 0.01f;              // between the dish and the sphere
// The pool's power over a default-size lamp's: it hangs 1-3 tiles over the paving where
// the facade lamps sit half a tile from their wall, and at 1x (fxr_lamp_after) the post
// was lit and the paving under it barely.
constexpr float kLampPoolGain = 4.0f;
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

// Where a tracked light goes, its colour and the factor its colour is scaled by
// (everything Apply describes to Remix but the emitter shape). Shared with the
// strongest-lights log.
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
    if (t.def.source == kLightSourceGame) scale *= GameClassDaylight(t.gameClass);

    // A wide coloured map light: warm white at the same luminance (see
    // wideNeonRadius in remix_lights.h). An override's own colour wins.
    if (t.def.source == kLightSourceGame && !t.moving && t.gameClass == kGameLightNeon &&
        g_settings.wideNeonRadius > 0.0f && t.def.radius >= g_settings.wideNeonRadius &&
        !(ov && ov->recolor)) {
        static const float kWarm[3] = {1.0f, 0.80f, 0.58f};
        const float lumaWarm = 0.2126f * kWarm[0] + 0.7152f * kWarm[1] + 0.0722f * kWarm[2];
        const float luma = 0.2126f * rgb[0] + 0.7152f * rgb[1] + 0.0722f * rgb[2];
        for (int i = 0; i < 3; ++i) rgb[i] = kWarm[i] * luma / lumaWarm;
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
    if (t.def.spot) {
        sphere.shaping_hasvalue = 1;
        sphere.shaping_value.direction = ToRemix(t.def.dir);
        sphere.shaping_value.coneAngleDegrees = t.def.coneAngleDeg;
        sphere.shaping_value.coneSoftness =
            t.def.coneSoftness >= 0.0f ? t.def.coneSoftness : g_settings.coneSoftness;
        sphere.shaping_value.focusExponent = 0.0f;
    }
    info.pNext = &sphere;

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

    const float level = g_ambient * g_settings.ambientFillScale;
    if (!g_settings.enabled || !g_settings.ambientFill || level <= 0.0f) {
        DestroyHandle(g_ambientHandle);
        return;
    }

    remixapi_LightInfo info = {};
    info.sType = REMIXAPI_STRUCT_TYPE_LIGHT_INFO;
    info.hash = kAmbientFillId;
    info.radiance = remixapi_Float3D{level, level, level};
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
        && a.coneSoftness == b.coneSoftness && a.buriedLift == b.buriedLift
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

float g_lastEye[3] = {0, 0, 0};
bool g_haveEye = false;

void LightsSubmitMapLampsNear(const float* eye, float radius, int cap, float weight) {
    g_farLampsLastFrame = 0;
    weight = weight < 0.0f ? 0.0f : (weight > 1.0f ? 1.0f : weight);
    g_farLampWeight = weight;
    memcpy(g_lastEye, eye, sizeof(g_lastEye)); g_haveEye = true;
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

float GameClassDaylight(uint8_t klass) {
    if (klass >= kGameLightClassCount) return 1.0f;
    return g_classDaylight[klass];
}

void RefreshClassDaylight() {
    for (int i = 0; i < kGameLightClassCount; ++i) {
        const float now = DaylightGateFactor(g_settings.gameClass[i].gate);
        g_classDaylight[i] = now;
        g_classMoved[i] = !g_classDaylightReady || std::fabs(now - g_classApplied[i]) >= kGateStep;
        if (g_classMoved[i]) g_classApplied[i] = now;
    }
    g_classDaylightReady = true;
}

void FitLampsToPosts() {
    g_lampPoolsLastFrame = 0;
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
        const float r = (std::min)(kLampPoolEmitter, 0.5f * head.glassRadius);
        pool.emitterRadius = r;
        pool.pos[0] = head.centre.x;
        pool.pos[1] = head.dishBottom - r - kLampPoolGap;
        pool.pos[2] = head.centre.z;
        pool.intensity = lampIntensity * kLampPoolGain * (reference / r) * (reference / r);
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
            if (g_classDaylight[t.gameClass] > kGateFloor
                && g_settings.gameClass[t.gameClass].enabled) {
                ++g_stats.litByClass[t.gameClass];
            }
        }
        // The sun has moved this kind of light far enough to be worth resending.
        if (t.def.source == kLightSourceGame && g_classMoved[t.gameClass]) t.dirty = true;

        const RemixLightOverride* ov = LightsFindOverride(t.key);
        const bool identified = t.key != 0 && t.key == g_identify;

        bool suppressed = false;
        if (ov && ov->disabled && !identified) {
            ++g_stats.suppressedByOverride;
            suppressed = true;
        } else if (t.def.source == kLightSourceGame
                   && (!(t.moving ? g_settings.injectMoving : g_settings.injectStatic)
                       || !g_settings.gameClass[t.gameClass].enabled
                       || GameClassDaylight(t.gameClass) <= kGateFloor)) {
            // Only the game's own lights are filtered this way. Ours are gated by
            // their category, upstream, and never reach here when switched off.
            // A light the sun has put out is dropped rather than dimmed to
            // nothing: an invisible light is still a handle on the far side of
            // the bridge and still a light the path tracer samples.
            ++g_stats.suppressedByClass;
            if (GameClassDaylight(t.gameClass) <= kGateFloor) ++g_stats.suppressedByDaylight;
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
