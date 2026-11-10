// See vehicle_fx.h.
#include "mem_stats.h"
#include "vehicle_fx.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <unordered_map>
#include <vector>

#include "ground.h"
#include "log.h"
#include "model_store.h"
#include "../../src/sky.h"

namespace gta2dx9 {
namespace {

constexpr float kPi = 3.14159265358979f;
constexpr float kStep = 1.0f / 30.0f;      // one game frame
constexpr size_t kMaxParticles = 640;
constexpr size_t kMaxSkids = 1400;
constexpr size_t kMaxParts = 6;
constexpr int kMaxCones = 10;
constexpr float kSkidHold = 25.0f, kSkidFade = 15.0f;   // seconds: full, then fading out

bool g_on = true;
bool g_physics = true;   // VEHICLE-PHYSICS: the load-transfer model (0: the first feel's springs)
// FIX-VEHICLES: the drawn lean over the springs' (percent / 100). A few degrees of
// physical pitch moved a van's tail by ~6 pixels in the chase view (PLAYTEST-FEEL read
// the body as rigid), so the picture leans more than the model: [renderer]
// car_body_pitch / car_body_roll, re-read with the devtools keys.
float g_pitchGain = 2.2f, g_rollGain = 1.7f;
// FIX-VEHICLE-FEEL-2: the bounded suspension pass ([devtools] vehicle_feel2, GTA2DX9_VEHICLE_FEEL2).
bool g_feel2 = true;
// [devtools] force_body_pitch_deg / force_body_roll_deg: every live car drawn at this lean (before the
// wheels' bound), for same-spot frames of a stopped car (pmy1 wheels-in-arches check). 0 = off.
float g_forcePitch = 0.0f, g_forceRoll = 0.0f;
// The player's car, for the camera (VehicleFxPlayerMotion).
VehicleFxMotion g_player;
uint32_t g_newestFrame = 0;   // the newest frame VehicleFxUpdate saw
float g_firstRide = 1.0f;
bool g_envRead = false;
bool g_dark = false;
int g_logFeel = -1;   // GTA2DX9_LOG_VEHICLE_FEEL=1: the player's car's numbers every 3 frames
const GroundSampler* g_ground = nullptr;

LARGE_INTEGER g_freq = {};
double NowMs() {
    if (!g_freq.QuadPart) QueryPerformanceFrequency(&g_freq);
    LARGE_INTEGER t; QueryPerformanceCounter(&t);
    return 1000.0 * static_cast<double>(t.QuadPart) / static_cast<double>(g_freq.QuadPart);
}
double g_updateMs = 0.0, g_lastMs = 0.0, g_worstMs = 0.0, g_sumMs = 0.0;
int g_sumFrames = 0;
uint32_t g_clockFrame = 0;   // the frame of the last draw: the effects' clock

uint32_t g_rng = 0x2545F491u;
float Rand() { g_rng = g_rng * 1664525u + 1013904223u; return static_cast<float>((g_rng >> 8) & 0xFFFFu) / 65535.0f; }
float Rand(float a, float b) { return a + (b - a) * Rand(); }
inline float Clamp(float v, float lo, float hi) { return (std::max)(lo, (std::min)(hi, v)); }
inline float Smooth(float t) { t = Clamp(t, 0.0f, 1.0f); return t * t * (3.0f - 2.0f * t); }
float WrapAngle(float a) {
    while (a > kPi) a -= 2.0f * kPi;
    while (a < -kPi) a += 2.0f * kPi;
    return a;
}

gta2::Mat4 Mul(const gta2::Mat4& a, const gta2::Mat4& b) {
    gta2::Mat4 out;
    for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) {
        float s = 0.0f;
        for (int k = 0; k < 4; ++k) s += a.m[r][k] * b.m[k][c];
        out.m[r][c] = s;
    }
    return out;
}
gta2::Mat4 Translate(float x, float y, float z) {
    gta2::Mat4 m = gta2::Identity();
    m.m[3][0] = x; m.m[3][1] = y; m.m[3][2] = z;
    return m;
}
// Row-vector rotations (v' = v M).
gta2::Mat4 RotX(float a) {   // +a: +y toward +z
    gta2::Mat4 m = gta2::Identity();
    const float c = std::cos(a), s = std::sin(a);
    m.m[1][1] = c; m.m[1][2] = s; m.m[2][1] = -s; m.m[2][2] = c;
    return m;
}
gta2::Mat4 RotZ(float a) {   // +a: +x toward +y (the top toward -x)
    gta2::Mat4 m = gta2::Identity();
    const float c = std::cos(a), s = std::sin(a);
    m.m[0][0] = c; m.m[0][1] = s; m.m[1][0] = -s; m.m[1][1] = c;
    return m;
}
gta2::Mat4 RotY(float a) {   // the same sense as the sprite bodies' steered wheels
    gta2::Mat4 m = gta2::Identity();
    const float c = std::cos(a), s = std::sin(a);
    m.m[0][0] = c; m.m[0][2] = s; m.m[2][0] = -s; m.m[2][2] = c;
    return m;
}
gta2::Vec3 Point(const gta2::Mat4& m, float x, float y, float z) {
    return {x * m.m[0][0] + y * m.m[1][0] + z * m.m[2][0] + m.m[3][0],
            x * m.m[0][1] + y * m.m[1][1] + z * m.m[2][1] + m.m[3][1],
            x * m.m[0][2] + y * m.m[1][2] + z * m.m[2][2] + m.m[3][2]};
}
gta2::Vec3 Axis(const gta2::Mat4& m, int row) {
    return gta2::Normalize(gta2::Vec3{m.m[row][0], m.m[row][1], m.m[row][2]});
}

// ---- the map's ground type under a point (1 road, 2 pavement, 3 field; 0 none)
int GroundTypeAt(float x, float z, float ceiling) {
    if (!g_ground || !g_ground->Ready()) return 0;
    const gta2::Map* map = g_ground->MapData();
    const int bx = static_cast<int>(std::floor(x));
    const int by = static_cast<int>(std::floor(static_cast<float>(gta2::kMapHeight) - z));
    if (bx < 0 || bx >= gta2::kMapWidth || by < 0 || by >= gta2::kMapHeight) return 0;
    const gta2::Column& column = map->ColumnAt(bx, by);
    int best = 0, bestLevel = -1;
    for (size_t i = 0; i < column.blocks.size(); ++i) {
        const uint32_t index = column.blocks[i];
        if (index >= map->BlockCount()) continue;
        const gta2::Block& block = map->BlockAt(index);
        if (!block.lid) continue;
        const int level = column.offset + static_cast<int>(i);
        if (static_cast<float>(level) > ceiling) continue;
        if (level > bestLevel) { bestLevel = level; best = block.GroundType(); }
    }
    return best;
}

// ---- per car ---------------------------------------------------------------
struct Spring {
    float x = 0.0f, v = 0.0f;
    void Step(float target, float hz, float zeta, float dt) {
        const float w = 2.0f * kPi * hz;
        const int n = (std::max)(1, static_cast<int>(std::ceil(dt * 120.0f)));
        const float h = dt / static_cast<float>(n);
        for (int i = 0; i < n; ++i) {
            const float a = w * w * (target - x) - 2.0f * zeta * w * v;
            v += a * h;
            x += v * h;
        }
    }
};

struct CarState {
    uint32_t frame = 0, born = 0;
    float x = 0, y = 0, z = 0, yaw = 0;
    float vx = 0, vy = 0, vz = 0;          // smoothed world velocity, blocks/s
    float rvx = 0, rvz = 0;                // last raw velocity
    float aF = 0, aL = 0, aY = 0;          // smoothed acceleration in the car frame
    float yawRate = 0;                     // smoothed, rad/s
    Spring roll, pitch, heave;
    // VEHICLE-PHYSICS: the body's give on its mounts after a hit (blocks, car frame x, z),
    // the damage each corner has taken (0 FL, 1 FR, 2 RL, 3 RR), a kerb strike's wheel
    // lift (seconds left), the time since the last hit, and the telemetry of the last step.
    Spring shoveX, shoveZ;
    float zone[4] = {0, 0, 0, 0};
    float kerbT[4] = {0, 0, 0, 0}, kerbH[4] = {0, 0, 0, 0};
    float sinceHit = 99.0f;
    float load[4] = {0.25f, 0.25f, 0.25f, 0.25f}, use[4] = {0, 0, 0, 0}, slip[4] = {0, 0, 0, 0};
    float steamT = 0;
    float spin = 0, steer = 0;
    float brake = 0, reverse = 0;
    int damage = -1;
    bool wreck = false, exploded = false;
    uint32_t aliveFrame = 0;               // last frame seen as a whole car
    int ground[4] = {0, 0, 0, 0};
    float exhaustT = 0, smokeT = 0;
    bool skidOn[4] = {};
    gta2::Vec3 skidLast[4];
    float sparkT = 0;
    float drawRoll = 0;                    // FIX-VEHICLE-FEEL-2: last drawn roll (the manoeuvre's slew limit)
    VehicleFeel feel;
};
std::unordered_map<uintptr_t, CarState> g_cars;

// ---- particles -------------------------------------------------------------
enum Kind : uint8_t { kSmoke, kExhaust, kSpark, kDebris };
struct Particle {
    float x, y, z, vx, vy, vz;
    float age, life;
    float size0, size1;
    float rot, rotV;
    float r, g, b, a;
    float groundY;
    uint8_t kind;
    uint8_t cell = 0;   // debris: which shard of the atlas
    bool hot = false;   // debris: a burning bit, glowing for its first second
};
std::vector<Particle> g_particles;

void Emit(const Particle& p) {
    if (g_particles.size() >= kMaxParticles) {
        // The pool is full: the oldest smoke gives way (sparks and debris are short or few).
        size_t oldest = 0; float best = -1.0f;
        for (size_t i = 0; i < g_particles.size(); ++i) {
            const float f = g_particles[i].age / g_particles[i].life;
            if (f > best) { best = f; oldest = i; }
        }
        g_particles[oldest] = p;
        return;
    }
    g_particles.push_back(p);
}

void EmitSmoke(const gta2::Vec3& at, float groundY, const gta2::Vec3& drift, float amount, bool exhaust) {
    Particle p{};
    p.kind = exhaust ? kExhaust : kSmoke;
    p.x = at.x + Rand(-0.02f, 0.02f); p.y = at.y; p.z = at.z + Rand(-0.02f, 0.02f);
    p.vx = drift.x + Rand(-0.08f, 0.08f); p.vy = drift.y + (exhaust ? Rand(0.05f, 0.10f) : Rand(0.08f, 0.18f)); p.vz = drift.z + Rand(-0.08f, 0.08f);
    p.life = exhaust ? Rand(1.3f, 1.9f) : Rand(1.4f, 2.4f);
    p.size0 = exhaust ? 0.035f : 0.07f;
    p.size1 = exhaust ? Rand(0.16f, 0.22f) : Rand(0.38f, 0.60f);
    p.rot = Rand(0.0f, 2.0f * kPi); p.rotV = Rand(-0.8f, 0.8f);
    const float grey = exhaust ? Rand(0.70f, 0.80f) : Rand(0.80f, 0.90f);
    p.r = p.g = p.b = grey;
    p.a = exhaust ? 0.20f : 0.30f * Clamp(amount, 0.3f, 1.0f);
    p.groundY = groundY;
    Emit(p);
}

// Steam (white, thin) from a hurt engine, dark smoke from a badly hurt one.
void EmitEngineSmoke(const gta2::Vec3& at, float groundY, const gta2::Vec3& drift, float dark) {
    Particle p{};
    p.kind = kSmoke;
    p.x = at.x + Rand(-0.03f, 0.03f); p.y = at.y; p.z = at.z + Rand(-0.03f, 0.03f);
    p.vx = drift.x + Rand(-0.05f, 0.05f); p.vy = Rand(0.22f, 0.40f); p.vz = drift.z + Rand(-0.05f, 0.05f);
    p.life = Rand(1.2f, 2.0f) + dark;
    p.size0 = 0.05f; p.size1 = Rand(0.30f, 0.45f) + 0.25f * dark;
    p.rot = Rand(0.0f, 2.0f * kPi); p.rotV = Rand(-0.6f, 0.6f);
    const float grey = 0.88f - 0.68f * dark + Rand(-0.04f, 0.04f);
    p.r = p.g = p.b = grey;
    // White steam on a grey road needs more than the tyre smoke's 0.3; a plume of dark smoke is
    // dozens of puffs deep, so each is thinner and the column keeps some light through it.
    p.a = 0.34f - 0.10f * dark;
    p.groundY = groundY;
    Emit(p);
}

void EmitSparks(const gta2::Vec3& at, float groundY, const gta2::Vec3& along, const gta2::Vec3& out, int count) {
    for (int i = 0; i < count; ++i) {
        Particle p{};
        p.kind = kSpark;
        p.x = at.x; p.y = at.y; p.z = at.z;
        const float s = Rand(0.6f, 1.0f);
        p.vx = along.x * Rand(0.4f, 1.0f) + out.x * Rand(0.5f, 2.2f) * s + Rand(-0.6f, 0.6f);
        p.vz = along.z * Rand(0.4f, 1.0f) + out.z * Rand(0.5f, 2.2f) * s + Rand(-0.6f, 0.6f);
        p.vy = Rand(0.4f, 1.8f);
        p.life = Rand(0.22f, 0.55f);
        p.size0 = p.size1 = Rand(0.008f, 0.014f);
        p.r = 1.0f; p.g = Rand(0.62f, 0.85f); p.b = Rand(0.25f, 0.40f); p.a = 1.0f;
        p.groundY = groundY;
        Emit(p);
    }
}

void EmitDebris(const gta2::Vec3& at, float groundY, const float paint[3], int count, float power) {
    for (int i = 0; i < count; ++i) {
        Particle p{};
        p.kind = kDebris;
        p.x = at.x + Rand(-0.15f, 0.15f); p.y = at.y + Rand(0.05f, 0.25f); p.z = at.z + Rand(-0.25f, 0.25f);
        const float ang = Rand(0.0f, 2.0f * kPi), sp = Rand(0.8f, 2.6f) * power;
        p.vx = std::cos(ang) * sp; p.vz = std::sin(ang) * sp; p.vy = Rand(1.5f, 3.8f) * power;
        p.life = Rand(5.0f, 9.0f);
        // FIX-FX-2 (pm10): fragments a hand or two across (0.05-0.12 block), not plates half a metre wide.
        p.size0 = p.size1 = Rand(0.018f, 0.045f);
        p.rot = Rand(0.0f, 2.0f * kPi); p.rotV = Rand(-9.0f, 9.0f);
        p.cell = static_cast<uint8_t>(Rand() * 3.999f);
        p.hot = Rand() < 0.3f;
        // Panels in the car's (scorched) paint, the rest dark metal and glass.
        const float k = Rand();
        if (k < 0.55f) { const float d = Rand(0.45f, 0.7f); p.r = paint[0] * d; p.g = paint[1] * d; p.b = paint[2] * d; }
        else if (k < 0.85f) { p.r = p.g = p.b = Rand(0.24f, 0.36f); }
        else { p.r = 0.50f; p.g = 0.56f; p.b = 0.60f; }
        p.a = 1.0f;
        p.groundY = groundY;
        Emit(p);
    }
}

// ---- skid marks --------------------------------------------------------------
struct Skid { float p[4][3]; float born; float alpha; };
std::vector<Skid> g_skids;
size_t g_skidNext = 0;

void AddSkid(const gta2::Vec3& a, const gta2::Vec3& b, float halfWidth, float alpha, float now) {
    const float dx = b.x - a.x, dz = b.z - a.z;
    const float l = std::sqrt(dx * dx + dz * dz);
    if (l < 1e-4f) return;
    const float sx = -dz / l * halfWidth, sz = dx / l * halfWidth;
    Skid s;
    const float y0 = a.y + 0.006f, y1 = b.y + 0.006f;
    const float pts[4][3] = {{a.x - sx, y0, a.z - sz}, {a.x + sx, y0, a.z + sz}, {b.x + sx, y1, b.z + sz}, {b.x - sx, y1, b.z - sz}};
    memcpy(s.p, pts, sizeof pts);
    s.born = now; s.alpha = alpha;
    if (g_skids.size() < kMaxSkids) g_skids.push_back(s);
    else { g_skids[g_skidNext] = s; g_skidNext = (g_skidNext + 1) % kMaxSkids; }
}

// ---- flying parts (a wheel off an exploding car) -----------------------------
struct Part {
    const Model* model;
    gta2::Mat4 fit;
    gta2::Vec3 centre;
    float x, y, z, vx, vy, vz;
    float ax, ay, wx, wy;
    float groundY, radius, age;
};
std::vector<Part> g_parts;

// ---- head-lamp pools -----------------------------------------------------------
struct Cone { gta2::Mat4 carToWorld; float length, width; };
std::vector<Cone> g_cones;

// ---- textures ------------------------------------------------------------------
IDirect3DDevice9* g_device = nullptr;
IDirect3DTexture9* g_puffTex = nullptr;
IDirect3DTexture9* g_glowTex = nullptr;
IDirect3DTexture9* g_stripTex = nullptr;
IDirect3DTexture9* g_coneTex = nullptr;
IDirect3DTexture9* g_shardTex = nullptr;
// FIX-REMIX-NIGHT (pt-remix-night-smoke-puff-opaque-clay-lump): under Remix the puffs' opacity
// (0.2-0.34, in the vertex colour's alpha) was lost, and a blended texel's colour came out scaled by its
// texture alpha: each puff was a dark ring of grain round a lit core where the texture is opaque (a
// hard tan lump under a lamp at night). With the opacity moved into the texture (out/rn_night4..7) the
// puffs were soft but black, tagged as particles or not, with or without Remix's emissive-blend or
// stochastic-alpha options. What Remix does light correctly is an opaque texel. So under Remix a puff
// is a dithered cut-out: per opacity step a texture whose covered share of texels is the opacity, drawn
// alpha-tested; the spin of each puff and the runtime's temporal filter turn the grain into
// translucency. The plain renderer is unchanged.
constexpr int kPuffLevels = 8;
constexpr float kPuffLevelStep = 0.045f;    // level k holds opacity (k + 1) * step: 0.045 .. 0.36
constexpr int kPuffDitherSize = 128;
constexpr int kPuffSeeds = 4;           // noise patterns per step, cycled by frame: the grain moves and the temporal filter averages it
IDirect3DTexture9* g_puffLevelTex[kPuffLevels * kPuffSeeds] = {};
bool g_puffLevelsOn = true;   // [devtools] remix_puff_levels=0: the old way, for a before/after in one session
// FIX-REMIX-NIGHT-5 (ptrmx20 white squares under a braking car's bumper, pt-remix-first-white-firefly-speck-
// clouds): the dither above covers a per-texel hash, so a puff of opacity 0.2-0.3 is 70-80 % isolated holes
// and 20-30 % isolated texels. The path tracer lights each covered texel as a little opaque card: far off a
// cloud of white specks over the road behind every idling car, close to the eye (point sampling, 128 texels
// across a puff a metre wide) a handful of hard white squares. Remix puff mode 1 (the default): the same
// coverage per step, but from a coherent noise (wisps a tenth of the puff across, ranked so the covered
// share is unchanged), stored as a smooth field and sampled bilinear under the alpha test, so the cut-out's
// edge is a smooth curve at any magnification; and each puff keeps its pattern for its life (the seed per
// frame made every texel flicker). Mode 0 the old dither, 2 no puffs under Remix, 3 mode 1 without the
// exhaust. [devtools] remix_puff_mode, read in remix_lights.cpp.
int g_remixPuffMode = 1;
IDirect3DTexture9* g_puffWispTex[kPuffLevels * kPuffSeeds] = {};
float PuffTexel(float u, float v) {
    const float dx = u - 0.5f, dy = v - 0.5f;
    const float r = std::sqrt(dx * dx + dy * dy) * 2.0f;
    const float ang = std::atan2(dy, dx);
    const float lump = 0.88f + 0.12f * std::sin(ang * 5.0f + 1.3f) * std::sin(ang * 3.0f);
    float a = Clamp(1.0f - r / lump, 0.0f, 1.0f);
    return a * a * (3.0f - 2.0f * a);
}

template <typename F>
IDirect3DTexture9* MakeTexture(IDirect3DDevice9* device, int w, int h, F texel) {
    // Dynamic, default pool, written with DISCARD: a managed texture's create and lock
    // made wined3d wait for the frame's queued GL work (85-590 ms a texture on a busy host).
    IDirect3DTexture9* tex = nullptr;
    DWORD lockFlags = D3DLOCK_DISCARD;
    if (FAILED(device->CreateTexture(w, h, 1, D3DUSAGE_DYNAMIC, D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT, &tex, nullptr))) {
        lockFlags = 0;
        if (FAILED(device->CreateTexture(w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &tex, nullptr))) return nullptr;
    }
    D3DLOCKED_RECT lr;
    if (SUCCEEDED(tex->LockRect(0, &lr, nullptr, lockFlags))) {
        for (int y = 0; y < h; ++y) {
            uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
            for (int x = 0; x < w; ++x) row[x] = texel((x + 0.5f) / w, (y + 0.5f) / h);
        }
        tex->UnlockRect(0);
    }
    return tex;
}
uint32_t Argb(float a, float r, float g, float b) {
    auto c = [](float v) { return static_cast<uint32_t>(Clamp(v, 0.0f, 1.0f) * 255.0f + 0.5f); };
    return (c(a) << 24) | (c(r) << 16) | (c(g) << 8) | c(b);
}
float Hash2(int x, int y) {
    uint32_t h = static_cast<uint32_t>(x) * 374761393u + static_cast<uint32_t>(y) * 668265263u;
    h = (h ^ (h >> 13)) * 1274126177u;
    return static_cast<float>((h ^ (h >> 16)) & 0xFFFFu) / 65535.0f;
}

// One texture a frame (a managed texture's first upload costs tens of ms under wined3d;
// five at once made a 150 ms frame). Until all are made the effects wait.
bool EnsureTextures(IDirect3DDevice9* device) {
    if (g_device != device) { VehicleFxReleaseDevice(); g_device = device; }
    if (g_puffTex && g_glowTex && g_stripTex && g_coneTex && g_shardTex) return true;
    if (!g_puffTex) {
        // A soft puff with a little lumpiness, so overlapping puffs do not read as discs.
        g_puffTex = MakeTexture(device, 64, 64, [](float u, float v) { return Argb(PuffTexel(u, v), 1.0f, 1.0f, 1.0f); });
    }
    else if (!g_glowTex) {
        g_glowTex = MakeTexture(device, 32, 32, [](float u, float v) {
            const float dx = u - 0.5f, dy = v - 0.5f;
            const float r = std::sqrt(dx * dx + dy * dy) * 2.0f;
            const float a = Clamp(1.0f - r, 0.0f, 1.0f);
            const float k = a * a;
            return Argb(k, k, k, k);
        });
    }
    else if (!g_stripTex) {
        // Across a skid mark (u): soft shoulders and a grainy rubber middle.
        g_stripTex = MakeTexture(device, 16, 64, [](float u, float v) {
            const float edge = Smooth(Clamp((0.5f - std::fabs(u - 0.5f)) * 5.0f, 0.0f, 1.0f));
            const float grain = 0.75f + 0.25f * Hash2(static_cast<int>(u * 16), static_cast<int>(v * 64));
            return Argb(edge * grain, 1.0f, 1.0f, 1.0f);
        });
    }
    else if (!g_coneTex) {
        // A head-lamp pool, u across, v along (0 at the bumper): brightest a little
        // ahead of the car, falling off with distance, soft at the sides.
        // FIX-REMIX-NIGHT-8 (qav1 detached wedge): the pool faded in over the first tenth of its 2.6-tile reach,
        // 0.26 tile of dark road between the bumper and the light (a wedge laid on the road ahead of the car). It
        // now comes up within 0.05 tile of the bumper. GTA2DX9_CONE_NEAR_OLD=1: the old ramp.
        static const float nearSpan = [] { const char* e = getenv("GTA2DX9_CONE_NEAR_OLD"); return (e && e[0] == '1') ? 0.10f : 0.02f; }();
        g_coneTex = MakeTexture(device, 64, 64, [](float u, float v) {
            const float across = std::fabs(u - 0.5f) * 2.0f;
            const float side = 1.0f - Smooth((across - 0.55f) / 0.45f);
            const float nearRamp = Smooth(v / nearSpan);
            const float fall = std::pow(Clamp(1.0f - v, 0.0f, 1.0f), 1.6f);
            const float hot = 1.0f + 0.35f * std::exp(-across * across * 6.0f);
            const float k = Clamp(side * nearRamp * fall * hot, 0.0f, 1.0f);
            return Argb(k, k, k, k);
        });
    }
    else if (!g_shardTex) {
        // FIX-FX-2 (pm10): four irregular shards in a 2x2 atlas - bent panel, trim strip, glass
        // splinter, torn corner - each a convex polygon of 4-5 uneven corners, with a lit edge
        // and a darker fold across it. The single seven-pointed shard before was radially
        // symmetric: at a street-level camera a shower of them read as black and white flowers.
        g_shardTex = MakeTexture(device, 64, 64, [](float u, float v) {
            static const float kPoly[4][5][2] = {
                {{-0.95f, -0.40f}, {0.20f, -0.85f}, {0.90f, -0.10f}, {0.35f, 0.80f}, {-0.70f, 0.55f}},
                {{-0.95f, -0.25f}, {0.95f, -0.45f}, {0.85f, -0.05f}, {-0.80f, 0.30f}, {-0.80f, 0.30f}},
                {{-0.15f, -0.95f}, {0.55f, 0.10f}, {0.10f, 0.95f}, {-0.45f, 0.20f}, {-0.45f, 0.20f}},
                {{-0.80f, -0.80f}, {0.75f, -0.60f}, {0.15f, 0.85f}, {-0.60f, 0.40f}, {-0.60f, 0.40f}},
            };
            const int cell = (v < 0.5f ? 0 : 2) + (u < 0.5f ? 0 : 1);
            // 10 % margin: the cells are sampled bilinearly and must not bleed into each other.
            const float x = ((u < 0.5f ? u : u - 0.5f) * 4.0f - 1.0f) * 1.12f, y = ((v < 0.5f ? v : v - 0.5f) * 4.0f - 1.0f) * 1.12f;
            // Signed distance inside a convex polygon: the least of the edge distances, measured
            // toward the interior whichever way the corners wind.
            const float (*P)[2] = kPoly[cell];
            float cross = 0.0f;
            for (int i = 0; i < 5; ++i) cross += P[i][0] * P[(i + 1) % 5][1] - P[i][1] * P[(i + 1) % 5][0];
            const float wind = cross > 0.0f ? -1.0f : 1.0f;
            float inside = 1e9f;
            for (int i = 0; i < 5; ++i) {
                const float* a = P[i]; const float* b = P[(i + 1) % 5];
                const float ex = b[0] - a[0], ey = b[1] - a[1];
                const float el = std::sqrt(ex * ex + ey * ey);
                if (el < 1e-4f) continue;
                inside = (std::min)(inside, wind * ((x - a[0]) * ey - (y - a[1]) * ex) / el);
            }
            const float a = Clamp(inside * 16.0f + 0.5f, 0.0f, 1.0f);
            // A bevel lit from the top left, a fold across the middle.
            const float rim = Clamp(1.0f - inside * 8.0f, 0.0f, 1.0f);
            const float fold = (x * 0.6f + y * 0.8f) > 0.1f ? 0.82f : 1.0f;
            const float shade = Clamp((0.86f + 0.14f * (-x - y) * 0.5f) * fold + 0.25f * rim * (y < 0.0f ? 1.0f : 0.2f), 0.0f, 1.0f);
            return Argb(a, shade, shade, shade);
        });
    }
    return false;
}

struct FxVertex { float x, y, z; DWORD color; float u, v; };
constexpr DWORD kFxFvf = D3DFVF_XYZ | D3DFVF_DIFFUSE | D3DFVF_TEX1;
std::vector<FxVertex> g_verts;
std::vector<uint16_t> g_index;

DWORD Colour(float r, float g, float b, float a) {
    auto c = [](float v) { return static_cast<DWORD>(Clamp(v, 0.0f, 1.0f) * 255.0f + 0.5f); };
    return (c(a) << 24) | (c(r) << 16) | (c(g) << 8) | c(b);
}

void Quad(const gta2::Vec3& c, const gta2::Vec3& a, const gta2::Vec3& b, DWORD col) {
    if (g_verts.size() + 4 > 65532) return;
    const uint16_t base = static_cast<uint16_t>(g_verts.size());
    const float uv[4][2] = {{0, 1}, {1, 1}, {1, 0}, {0, 0}};
    const float s[4][2] = {{-1, -1}, {1, -1}, {1, 1}, {-1, 1}};
    for (int k = 0; k < 4; ++k) {
        FxVertex v;
        v.x = c.x + s[k][0] * a.x + s[k][1] * b.x;
        v.y = c.y + s[k][0] * a.y + s[k][1] * b.y;
        v.z = c.z + s[k][0] * a.z + s[k][1] * b.z;
        v.color = col; v.u = uv[k][0]; v.v = uv[k][1];
        g_verts.push_back(v);
    }
    const uint16_t t[6] = {base, static_cast<uint16_t>(base + 1), static_cast<uint16_t>(base + 2), base, static_cast<uint16_t>(base + 2), static_cast<uint16_t>(base + 3)};
    g_index.insert(g_index.end(), t, t + 6);
}

// A quad showing one cell of a 2x2 atlas (the debris shards).
void QuadCell(const gta2::Vec3& c, const gta2::Vec3& a, const gta2::Vec3& b, DWORD col, int cell) {
    const size_t first = g_verts.size();
    Quad(c, a, b, col);
    if (g_verts.size() == first) return;
    const float u0 = (cell & 1) ? 0.5f : 0.0f, v0 = (cell & 2) ? 0.5f : 0.0f;
    for (size_t i = first; i < g_verts.size(); ++i) { g_verts[i].u = u0 + g_verts[i].u * 0.5f; g_verts[i].v = v0 + g_verts[i].v * 0.5f; }
}

// Every effect is quads, so they draw from one dynamic vertex buffer (written with
// DISCARD / NOOVERWRITE, as PERF-3 found wined3d wants) and a fixed index buffer of the
// quad pattern; UP draws of a few thousand vertices stalled a frame now and then.
constexpr UINT kVbQuads = 4096;
IDirect3DVertexBuffer9* g_vb = nullptr;
IDirect3DIndexBuffer9* g_ib = nullptr;
UINT g_vbUsed = kVbQuads;   // quads written since the last DISCARD
bool g_vbFailed = false;
bool Buffers(IDirect3DDevice9* device) {
    if (g_vb && g_ib) return true;
    if (g_vbFailed) return false;
    if (FAILED(device->CreateVertexBuffer(kVbQuads * 4 * sizeof(FxVertex), D3DUSAGE_DYNAMIC | D3DUSAGE_WRITEONLY, kFxFvf, D3DPOOL_DEFAULT, &g_vb, nullptr)) ||
        FAILED(device->CreateIndexBuffer(kVbQuads * 6 * sizeof(uint16_t), D3DUSAGE_WRITEONLY, D3DFMT_INDEX16, D3DPOOL_MANAGED, &g_ib, nullptr))) {
        if (g_vb) { g_vb->Release(); g_vb = nullptr; }
        if (g_ib) { g_ib->Release(); g_ib = nullptr; }
        g_vbFailed = true;
        Log("vehicle feel: no dynamic buffers; drawing from memory");
        return false;
    }
    void* p = nullptr;
    if (SUCCEEDED(g_ib->Lock(0, 0, &p, 0))) {
        uint16_t* idx = static_cast<uint16_t*>(p);
        for (UINT q = 0; q < kVbQuads; ++q) {
            const uint16_t b = static_cast<uint16_t>(q * 4);
            const uint16_t t[6] = {b, static_cast<uint16_t>(b + 1), static_cast<uint16_t>(b + 2), b, static_cast<uint16_t>(b + 2), static_cast<uint16_t>(b + 3)};
            memcpy(idx + q * 6, t, sizeof t);
        }
        g_ib->Unlock();
    }
    g_vbUsed = kVbQuads;
    return true;
}

void Flush(IDirect3DDevice9* device, IDirect3DTexture9* tex) {
    if (!g_index.empty() && tex) {
        device->SetTexture(0, tex);
        const UINT quads = static_cast<UINT>(g_verts.size() / 4);
        bool drawn = false;
        if (Buffers(device) && quads <= kVbQuads) {
            const bool discard = g_vbUsed + quads > kVbQuads;
            const UINT first = discard ? 0 : g_vbUsed;
            void* p = nullptr;
            // FIX-PERF-4: wined3d answers a map it cannot back (address space full) with S_OK and null.
            if (SUCCEEDED(g_vb->Lock(first * 4 * sizeof(FxVertex), quads * 4 * sizeof(FxVertex), &p, discard ? D3DLOCK_DISCARD : D3DLOCK_NOOVERWRITE)) &&
                (p || (g_vb->Unlock(), false))) {
                memcpy(p, g_verts.data(), quads * 4 * sizeof(FxVertex));
                g_vb->Unlock();
                g_vbUsed = first + quads;
                device->SetStreamSource(0, g_vb, 0, sizeof(FxVertex));
                device->SetIndices(g_ib);
                device->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, static_cast<INT>(first * 4), 0, quads * 4, 0, quads * 2);
                device->SetStreamSource(0, nullptr, 0, 0);
                device->SetIndices(nullptr);
                drawn = true;
            }
        }
        if (!drawn) {
            device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(g_verts.size()), static_cast<UINT>(g_index.size() / 3),
                                           g_index.data(), D3DFMT_INDEX16, g_verts.data(), sizeof(FxVertex));
        }
    }
    g_verts.clear();
    g_index.clear();
}

void ReadEnv() {
    if (g_envRead) return;
    g_envRead = true;
    char v[16] = {};
    if (GetEnvironmentVariableA("GTA2DX9_VEHICLE_FEEL", v, sizeof v) && v[0] == '0') g_on = false;
    v[0] = 0;
    if (GetEnvironmentVariableA("GTA2DX9_VEHICLE_PHYSICS", v, sizeof v) && v[0] == '0') g_physics = false;
    v[0] = 0;
    if (GetEnvironmentVariableA("GTA2DX9_VEHICLE_FEEL2", v, sizeof v) && v[0] == '0') g_feel2 = false;
    v[0] = 0;
    g_logFeel = GetEnvironmentVariableA("GTA2DX9_LOG_VEHICLE_FEEL", v, sizeof v) ? atoi(v) : 0;
    g_particles.reserve(kMaxParticles);
    g_skids.reserve(kMaxSkids);
    Log("vehicle feel: %s (sprung bodies, turning wheels, lamps, smoke, skid marks, sparks, debris); physics %s", g_on ? "on" : "off",
        g_physics ? "on (load transfer, tyre grip, impacts, corner damage)" : "off");
}

}  // namespace

void VehicleFxSetGround(const GroundSampler* ground) { g_ground = ground; }
void VehicleFxSetEnabled(bool on) {
    ReadEnv();
    if (on != g_on) Log("vehicle feel: %s", on ? "on" : "off");
    g_on = on;
}
bool VehicleFxEnabled() { ReadEnv(); return g_on; }
void VehicleFxSetPhysics(int mode) {
    ReadEnv();
    if (mode < 0) return;
    if ((mode != 0) != g_physics) Log("vehicle feel: physics %s", mode ? "on" : "off");
    g_physics = mode != 0;
}
void VehicleFxSetDark(bool dark) { g_dark = dark; }
void VehicleFxSetFeel2(int mode) {
    ReadEnv();
    if (mode < 0) return;
    if ((mode != 0) != g_feel2) Log("vehicle feel: bounded suspension (feel2) %s", mode ? "on" : "off");
    g_feel2 = mode != 0;
}
bool VehicleFxFeel2() { ReadEnv(); return g_feel2; }
void VehicleFxForceLean(int pitchDeg, int rollDeg) {
    const float p = static_cast<float>(pitchDeg) * kPi / 180.0f, r = static_cast<float>(rollDeg) * kPi / 180.0f;
    if (p != g_forcePitch || r != g_forceRoll) Log("vehicle feel: forced lean pitch %d, roll %d degrees", pitchDeg, rollDeg);
    g_forcePitch = p; g_forceRoll = r;
}
static bool g_smooth = false;
void VehicleFxSetSmooth(bool on) { g_smooth = on; }
void VehicleFxSetLean(int pitchPercent, int rollPercent) {
    const float p = Clamp(pitchPercent / 100.0f, 0.0f, 4.0f), r = Clamp(rollPercent / 100.0f, 0.0f, 4.0f);
    if (p != g_pitchGain || r != g_rollGain) Log("vehicle feel: drawn lean pitch %d%%, roll %d%%", pitchPercent, rollPercent);
    g_pitchGain = p; g_rollGain = r;
}
void VehicleFxSetFirstRide(float share) { g_firstRide = Clamp(share, 0.0f, 1.0f); }
float VehicleFxFirstRide() { return g_firstRide; }
bool VehicleFxPlayerMotion(VehicleFxMotion* out) {
    if (!g_on || !g_player.frame || g_newestFrame - g_player.frame > 3) { g_player.impulse = 0.0f; return false; }
    *out = g_player;
    g_player.impulse = 0.0f;
    return true;
}

gta2::Mat4 VehicleFxWreckPose(int lost, float length, float width, float wheelRadius) {
    if (!lost) return Translate(0.0f, -0.25f * wheelRadius, 0.0f);   // flat tyres
    // Each corner without its wheel drops onto its hub; the body tilts to the average.
    float drop[4];
    for (int i = 0; i < 4; ++i) drop[i] = (lost & (1 << i)) ? 0.85f * wheelRadius : 0.25f * wheelRadius;
    const float front = 0.5f * (drop[0] + drop[1]), rear = 0.5f * (drop[2] + drop[3]);
    const float left = 0.5f * (drop[0] + drop[2]), right = 0.5f * (drop[1] + drop[3]);
    const float wb = (std::max)(0.3f, 0.62f * length), track = (std::max)(0.2f, 0.84f * width);
    const float pitch = std::atan2(front - rear, wb);     // front lower: nose down (RotX +)
    const float roll = std::atan2(right - left, track);   // right lower: top toward +x (RotZ -)
    const float heave = -0.25f * (drop[0] + drop[1] + drop[2] + drop[3]);
    return Mul(Mul(RotX(pitch), RotZ(-roll)), Translate(0.0f, heave, 0.0f));
}

void VehicleFxQueueHeadlamps(const gta2::Mat4& carToWorld, float length, float width) {
    if (!g_on || static_cast<int>(g_cones.size()) >= 64) return;
    g_cones.push_back(Cone{carToWorld, length, width});
}

const VehicleFeel& VehicleFxUpdate(const VehicleFxCar& car, uint32_t frame) {
    ReadEnv();
    const double t0 = NowMs();
    CarState& st = g_cars[car.object];
    VehicleFeel& feel = st.feel;
    feel.on = g_on;
    if (!car.carToWorld) { feel.pose = gta2::Identity(); return feel; }
    const gta2::Mat4& w = *car.carToWorld;
    const gta2::Vec3 f = Axis(w, 2), r = Axis(w, 0), up = Axis(w, 1);
    const float x = w.m[3][0], y = w.m[3][1], z = w.m[3][2];
    const float yaw = std::atan2(f.z, f.x);
    const float now = static_cast<float>(frame) * kStep;
    if (frame > g_newestFrame || g_newestFrame - frame > 1000) g_newestFrame = frame;
    if (st.frame == frame && st.born) return feel;   // drawn twice this frame (a mirror, a second pass)
    const bool fresh = !st.born || frame - st.frame > 10 || frame < st.frame ||
                       (x - st.x) * (x - st.x) + (z - st.z) * (z - st.z) > 2.25f;   // a respawn or a warp
    if (fresh) {
        const bool keepWreck = st.born && st.exploded;
        st = CarState{};
        st.born = frame ? frame : 1;
        st.exploded = keepWreck;
        st.x = x; st.y = y; st.z = z; st.yaw = yaw; st.frame = frame;
        st.damage = car.damage;
        st.wreck = car.wreck;
        st.aliveFrame = car.wreck ? 0 : frame;
        st.feel.on = g_on;
        st.feel.pose = gta2::Identity();
        g_updateMs += NowMs() - t0;
        return st.feel;
    }
    const float dt = static_cast<float>(frame - st.frame) * kStep;
    // Velocity from the positions, smoothed a little (the game moves in whole steps).
    const float rvx = (x - st.x) / dt, rvy = (y - st.y) / dt, rvz = (z - st.z) / dt;
    const float kv = Clamp(dt / 0.05f, 0.0f, 1.0f);
    const float nvx = st.vx + (rvx - st.vx) * kv, nvy = st.vy + (rvy - st.vy) * kv, nvz = st.vz + (rvz - st.vz) * kv;
    const float ax = (nvx - st.vx) / dt, ay = (nvy - st.vy) / dt, az = (nvz - st.vz) / dt;
    const float ka = Clamp(dt / 0.08f, 0.0f, 1.0f);
    const float aF = ax * f.x + az * f.z, aL = ax * r.x + az * r.z;
    st.aF += (aF - st.aF) * ka;
    st.aL += (aL - st.aL) * ka;
    st.aY += (ay - st.aY) * ka;
    // The raw jolt, for impacts: how hard the velocity jumped this step.
    const float jx = (rvx - st.rvx) / dt, jz = (rvz - st.rvz) / dt;
    const float jolt = std::sqrt(jx * jx + jz * jz);
    // An impact takes speed away; GTA2's traffic pulling off from a stop jumps the
    // other way (4-7 blocks/s in one step, seen in vp_1), which is not a hit.
    const float lostSpeed = std::sqrt(st.rvx * st.rvx + st.rvz * st.rvz) - std::sqrt(rvx * rvx + rvz * rvz);
    const bool joltHit = jolt > 45.0f && (!g_physics || lostSpeed > 0.3f * jolt * dt);
    st.rvx = rvx; st.rvz = rvz;
    st.vx = nvx; st.vy = nvy; st.vz = nvz;
    const float vF = st.vx * f.x + st.vz * f.z, vL = st.vx * r.x + st.vz * r.z;
    const float speed = std::sqrt(st.vx * st.vx + st.vz * st.vz);
    const float dyaw = WrapAngle(yaw - st.yaw);
    const float ds = (x - st.x) * f.x + (z - st.z) * f.z;
    st.yawRate += (dyaw / dt - st.yawRate) * ka;
    st.x = x; st.y = y; st.z = z; st.yaw = yaw; st.frame = frame;
    const float halfL = 0.5f * car.length, halfW = 0.5f * car.width;
    const float groundY = y;

    // Steering, as the sprite bodies have it: the wheel angle that turns the car by
    // the heading change over the distance covered.
    {
        float target = st.steer * 0.92f;
        if (std::fabs(ds) > 0.004f && std::fabs(ds) < 1.0f) target = Clamp(std::atan(car.wheelbase * dyaw / ds), -0.6f, 0.6f);
        if (g_physics && g_on && std::fabs(vF) > 0.8f) {
            // VEHICLE-PHYSICS: the front wheels point along the front axle's own velocity
            // (the car's sideways velocity plus the yaw's swing of the nose), so a car
            // whose tail slides out shows counter-steer instead of full lock into the turn.
            // s maps the yaw's sense onto the car's x axis (the same convention as above:
            // with the rear axle not sliding this is atan(wheelbase * yaw rate / speed)).
            const float s = -f.z * r.x + f.x * r.z;
            const float vLr = s * vL - 0.5f * car.wheelbase * st.yawRate;
            // While the rear grips, vLr ~ 0 and this is the kinematic steer; GTA2's
            // measured vL is noisy, so the slide term only counts past 0.5 blocks/s.
            const float rearSlide = std::fabs(vLr) > 0.5f ? vLr - (vLr > 0 ? 0.5f : -0.5f) : 0.0f;
            target = Clamp(std::atan((car.wheelbase * st.yawRate + rearSlide) / vF), -0.6f, 0.6f);
        }
        st.steer += (target - st.steer) * 0.3f;
    }
    st.spin = std::fmod(st.spin + ds / (std::max)(0.03f, car.wheelRadius), 2.0f * kPi);

    // Lamps: brake while slowing (either way) or backing, reverse lamps while backing.
    {
        const bool slowing = speed > 0.6f && ((vF > 0.0f && st.aF < -2.5f) || (vF < 0.0f && st.aF > 2.5f));
        const bool backing = vF < -0.35f;
        const float wantB = (slowing || backing) && !car.wreck ? 1.0f : 0.0f;
        st.brake += (wantB - st.brake) * Clamp(dt / (wantB > st.brake ? 0.05f : 0.30f), 0.0f, 1.0f);
        const float wantR = backing && !car.wreck ? 1.0f : 0.0f;
        st.reverse += (wantR - st.reverse) * Clamp(dt / 0.12f, 0.0f, 1.0f);
    }

    const bool live = !car.wreck && g_on;
    // The car's chassis for the load-transfer model (VEHICLE-PHYSICS), from its body:
    // track and wheelbase, the centre of mass at 0.38 of the body height, a ride
    // frequency from how tall the body is for its width (GTA2's cars are 1960s designs on
    // soft springs: a low coupe ~1.6 Hz, a sedan ~1.45, a van or a bus ~1.25), the static
    // spring deflection that frequency means (g / w^2, in blocks at 1.8 m to the car's
    // width), roll stiffened a little by anti-roll bars.
    const float track = (std::max)(0.2f, 0.84f * car.width);
    const float wb = (std::max)(0.25f, car.wheelbase);
    const float cgH = 0.38f * (std::max)(0.15f, car.roof);
    const float rideHz = Clamp(1.50f - 0.40f * (car.roof / (std::max)(0.2f, car.width) - 0.75f), 1.25f, 1.75f);
    const float mPerBlock = 1.8f / (std::max)(0.2f, car.width);
    const float wRide = 2.0f * kPi * rideHz;
    const float staticDefl = (9.81f / (wRide * wRide)) / mPerBlock;   // blocks
    const float travel = 1.25f * staticDefl;                          // to the bump stop, each way
    constexpr float kG = 9.0f;            // GTA2's 1 g, blocks/s^2 (its hardest turns pull ~8, its brakes ~10-15)
    constexpr float kMu = 1.0f;           // tyre peak friction, in those g
    constexpr float kFront = 0.52f;       // static front axle share (engine in front)
    constexpr float kRollFront = 0.56f;   // front share of the roll stiffness (the front bar is stiffer)
    constexpr float kRollMul = 1.2f;      // roll stiffness over the springs alone (a period front bar)
    // Wear: the damage softens the dampers, so a beaten car bounces longer.
    const float wear = Smooth((static_cast<float>(car.damage) - 4000.0f) / 16000.0f);
    st.sinceHit += dt;
    for (int i = 0; i < 4; ++i) feel.wheelLift[i] = feel.wheelCamber[i] = feel.wheelToe[i] = 0.0f;
    float axT = 0.0f, ayT = 0.0f;   // the accelerations the tyres carry, g
    if (live && g_physics) {
        const float wheelX[4] = {-0.40f * car.width, 0.40f * car.width, -0.40f * car.width, 0.40f * car.width};
        const float wheelZ[4] = {0.5f * wb, 0.5f * wb, -0.5f * wb, -0.5f * wb};
        // ---- load transfer: what the tyres carry, capped by what they can carry
        // (an impact's deceleration comes from the wall, not the tyres: for 0.25 s after
        // a hit the accelerations do not load the springs).
        float ax = st.aF / kG, ay = st.aL / kG;
        if (st.sinceHit < 0.25f) { ax = 0.0f; ay = 0.0f; }
        // FIX-SEAT-ENTRY-2 (feel30): nor while it is held against a wall (hit again and again,
        // barely moving): GTA2 pushes a car under throttle into the wall and back each few frames,
        // and that jitter of its velocity read as hard braking and launching, rocking the body
        // (and the first-person cockpit with it) by degrees every few frames at a standstill.
        else if (st.sinceHit < 0.8f && speed < 1.0f) { ax = 0.0f; ay = 0.0f; }
        const float demand = std::sqrt(ax * ax + ay * ay);
        float carried = demand;
        if (demand > 0.8f * kMu) carried = 0.8f * kMu + 0.25f * kMu * std::tanh((demand - 0.8f * kMu) / (0.25f * kMu));
        if (demand > 1e-4f) { axT = ax * carried / demand; ayT = ay * carried / demand; }
        // Longitudinal: braking (ax < 0) moves load to the front; anti-dive and anti-squat
        // geometry take a little of it out of the springs.
        const float dLong = -axT * cgH / wb;
        const float springLong = dLong * 0.85f;
        // Lateral: a right-hand pull (ay > 0) loads the left wheels by ay h / t of the weight.
        const float dLat = ayT * cgH / track;
        const float ns[4] = {0.5f * kFront, 0.5f * kFront, 0.5f * (1.0f - kFront), 0.5f * (1.0f - kFront)};
        float n[4];
        for (int i = 0; i < 4; ++i) {
            const float lon = (i < 2 ? 0.5f : -0.5f) * dLong;
            const float lat = ((i & 1) ? -1.0f : 1.0f) * (i < 2 ? kRollFront : 1.0f - kRollFront) * dLat;
            n[i] = ns[i] + lon + lat;
            st.load[i] = n[i];
        }
        // Spring compression of each corner (blocks, + compressed) as the modal targets:
        // roll (left side down +), pitch (nose down +), heave.
        float c[4];
        for (int i = 0; i < 4; ++i) {
            const float lon = (i < 2 ? 0.5f : -0.5f) * springLong;
            const float lat = ((i & 1) ? -1.0f : 1.0f) * (i < 2 ? kRollFront : 1.0f - kRollFront) * dLat / kRollMul;
            c[i] = (lon + lat) / ns[i] * staticDefl;
        }
        const float left = 0.5f * (c[0] + c[2]), right = 0.5f * (c[1] + c[3]);
        const float front = 0.5f * (c[0] + c[1]), rear = 0.5f * (c[2] + c[3]);
        // The quality bar's ceiling: 6 degrees of roll, 3 of pitch from manoeuvres
        // (a tall van would roll more on these springs; real vans have stiffer bars).
        float rollTarget = Clamp(std::atan2(left - right, track), -0.105f, 0.105f);
        float pitchTarget = Clamp(std::atan2(front - rear, wb), -0.052f, 0.052f);
        float heaveTarget = Clamp(-0.0035f * st.aY, -0.03f, 0.03f);
        // Progressive damage: a corner that has taken hits sits lower (bent mounts, a
        // broken spring), up to half a wheel radius, and the body leans to match.
        float sag[4];
        for (int i = 0; i < 4; ++i) sag[i] = Smooth((st.zone[i] - 4000.0f) / 12000.0f) * 0.45f * car.wheelRadius;
        rollTarget += std::atan2(0.5f * (sag[0] + sag[2]) - 0.5f * (sag[1] + sag[3]), track);
        pitchTarget += std::atan2(0.5f * (sag[0] + sag[1]) - 0.5f * (sag[2] + sag[3]), wb);
        heaveTarget -= 0.25f * (sag[0] + sag[1] + sag[2] + sag[3]);
        // Bump stops: no more than the travel each way at any corner.
        const float maxRoll = std::atan2(2.0f * travel, track), maxPitch = std::atan2(2.0f * travel, wb);

        // ---- kerbs: the wheel rides up the step (a short lift of that wheel), the
        // corner's spring passes it to the body.
        if (speed > 0.5f && g_ground) {
            for (int i = 0; i < 4; ++i) {
                const float sx = (i & 1) ? 0.42f * car.width : -0.42f * car.width;
                const float sz = (i < 2) ? 0.5f * wb : -0.5f * wb;
                const float wx = x + r.x * sx + f.x * sz, wz = z + r.z * sx + f.z * sz;
                const int type = GroundTypeAt(wx, wz, y + 0.5f);
                if (type && st.ground[i] && type != st.ground[i] && (type == 1 || st.ground[i] == 1)) {
                    const float k = Clamp(speed / 4.0f, 0.25f, 1.0f);
                    st.kerbT[i] = 0.14f;
                    st.kerbH[i] = 0.018f * k;
                    const float vUp = 0.30f * k;   // blocks/s the corner is pushed up
                    st.heave.v += 0.30f * vUp;
                    st.pitch.v += (i < 2 ? -1.0f : 1.0f) * 0.5f * vUp / wb;
                    st.roll.v += ((i & 1) ? 1.0f : -1.0f) * 0.5f * vUp / track;
                }
                if (type) st.ground[i] = type;
            }
        }
        for (int i = 0; i < 4; ++i) {
            if (st.kerbT[i] > 0.0f) {
                st.kerbT[i] -= dt;
                const float ph = Clamp(1.0f - st.kerbT[i] / 0.14f, 0.0f, 1.0f);
                feel.wheelLift[i] = st.kerbH[i] * std::sin(ph * kPi);
            }
        }

        // ---- impacts: the velocity's jump is the impulse (per unit mass). The sprung
        // body keeps going while the wheels and the bumper stop: it pitches or rolls
        // about the axles by dv h / k^2 (k the radius of gyration, ~0.3 of the length or
        // the width), gives on its mounts against the push, and the corner that met
        // the wall keeps the damage.
        const int dDamage = (st.damage >= 0 && car.damage > st.damage) ? car.damage - st.damage : 0;
        const bool hit = (dDamage > 0 && speed + std::sqrt(st.rvx * st.rvx + st.rvz * st.rvz) > 0.3f) || joltHit;
        if (hit) {
            const float dvF = jx * f.x * dt + jz * f.z * dt, dvL = (jx * r.x + jz * r.z) * dt;   // blocks/s, car frame
            const float dv = std::sqrt(dvF * dvF + dvL * dvL);
            const float kP = 0.3f * car.length, kR = 0.35f * car.width;
            // FIX-SEAT-ENTRY-2 (feel30): the first contact gives the kick; a car held against the wall
            // (another small hit within 0.8 s of the last) only a tenth of it, so a van pressed into a
            // wall dips once and settles instead of rolling ~5 degrees every few frames.
            const float kick = (st.sinceHit < 0.8f && dv < 1.2f) ? 0.1f : 1.0f;
            const float sprung = 0.35f * kick;   // the share of the jump the body feels before the springs take it
            st.pitch.v += Clamp(-dvF * cgH / (kP * kP) * sprung, -3.0f, 3.0f);
            st.roll.v += Clamp(dvL * cgH / (kR * kR) * sprung, -3.0f, 3.0f);
            st.heave.v += Clamp(0.05f * dv * kick, 0.0f, 0.25f);
            st.shoveX.v += Clamp(-dvL * 0.10f * kick, -0.6f, 0.6f);
            st.shoveZ.v += Clamp(-dvF * 0.10f * kick, -0.6f, 0.6f);
            // Where it struck: the body's edge on the side the push came from.
            float jF = dvF, jL = dvL;
            const float jl = std::sqrt(jF * jF + jL * jL);
            if (jl > 1e-3f) { jF /= jl; jL /= jl; } else { jF = vF >= 0.0f ? -1.0f : 1.0f; jL = 0.0f; }
            const float cx = -jL, cz = -jF;
            const float tx = std::fabs(cx) > 1e-3f ? halfW / std::fabs(cx) : 1e9f, tz = std::fabs(cz) > 1e-3f ? halfL / std::fabs(cz) : 1e9f;
            const float t = (std::min)(tx, tz);
            const float lx = cx * t, lz = cz * t;
            const int corner = (lz >= 0.0f ? 0 : 2) + (lx >= 0.0f ? 1 : 0);
            if (dDamage > 0) {
                // 70 % to the corner, the rest to its neighbours along the end and the side.
                st.zone[corner] += 0.70f * dDamage;
                st.zone[corner ^ 1] += 0.15f * dDamage;
                st.zone[corner ^ 2] += 0.15f * dDamage;
            }
            if (st.sparkT <= 0.0f) {
                const float k = Clamp((dDamage > 0 ? dDamage / 1500.0f : 0.0f) + (jolt - 30.0f) / 120.0f, 0.2f, 1.0f);
                const gta2::Vec3 at = Point(w, lx, 0.12f, lz);
                const gta2::Vec3 along{st.vx * 0.5f, 0.0f, st.vz * 0.5f};
                const gta2::Vec3 out{-(r.x * cx + f.x * cz), 0.0f, -(r.z * cx + f.z * cz)};
                EmitSparks(at, groundY, along, out, 8 + static_cast<int>(22.0f * k));
                st.sparkT = 0.08f;
            }
            if (car.driven) g_player.impulse += dv * kick;
            if (st.sinceHit > 0.3f && (car.driven || g_logFeel > 0))
                Log("vehicle physics: impact%s dv=%.2f blocks/s (along %.2f, across %.2f) at corner %d, damage +%d -> %d, corners %.0f %.0f %.0f %.0f",
                    car.driven ? " (player)" : "", dv, dvF, dvL, corner, dDamage, car.damage, st.zone[0], st.zone[1], st.zone[2], st.zone[3]);
            st.sinceHit = 0.0f;
        } else if (dDamage > 0 && dDamage < 400 && speed > 1.0f) {
            // A scrape: the damage creeps up while sliding along a wall; the side we lean
            // into takes it, front and back alike.
            const int side = vL >= 0.0f ? 1 : 0;
            st.zone[side] += 0.5f * dDamage; st.zone[2 + side] += 0.5f * dDamage;
        }
        if (dDamage > 0 && speed > 1.0f && st.sparkT <= 0.0f) {
            const float side = (vL >= 0.0f) ? 1.0f : -1.0f;
            const gta2::Vec3 at = Point(w, side * halfW, 0.10f, Rand(-0.3f, 0.3f) * halfL);
            EmitSparks(at, groundY, gta2::Vec3{-st.vx * 0.3f, 0.0f, -st.vz * 0.3f}, gta2::Vec3{r.x * side, 0.0f, r.z * side}, 6);
            st.sparkT = 0.05f;
        }
        st.sparkT -= dt;

        // ---- the springs: ride frequency, roll and pitch a little stiffer; damping
        // falls from ~0.6 of critical (a small overshoot, settled in ~0.4 s) to ~0.3
        // as the car is beaten.
        const float zeta = 0.60f * (1.0f - 0.5f * wear);
        // FIX-VEHICLE-FEEL-2 (feel10): a tall body rolls on a slower mode (its roll inertia grows with
        // the height squared), so it leans in over ~0.5 s instead of snapping over.
        const float tallHz = g_feel2 ? 1.0f - 0.35f * Smooth((car.roof / (std::max)(0.2f, car.width) - 0.95f) / 0.45f) : 1.0f;
        st.roll.Step(rollTarget, rideHz * 1.20f * tallHz, zeta, dt);
        st.pitch.Step(pitchTarget, rideHz * 1.10f, zeta, dt);
        st.heave.Step(heaveTarget, rideHz, zeta * 0.85f, dt);
        st.shoveX.Step(0.0f, 4.0f, 0.30f, dt);
        st.shoveZ.Step(0.0f, 4.0f, 0.30f, dt);
        if (std::fabs(st.roll.x) > maxRoll + 0.02f) { st.roll.x = Clamp(st.roll.x, -maxRoll - 0.02f, maxRoll + 0.02f); st.roll.v *= -0.3f; }
        if (std::fabs(st.pitch.x) > maxPitch + 0.02f) { st.pitch.x = Clamp(st.pitch.x, -maxPitch - 0.02f, maxPitch + 0.02f); st.pitch.v *= -0.3f; }
        st.heave.x = Clamp(st.heave.x, -travel - 0.02f, travel + 0.01f);
        st.shoveX.x = Clamp(st.shoveX.x, -0.03f, 0.03f);
        st.shoveZ.x = Clamp(st.shoveZ.x, -0.035f, 0.035f);
        // A wheel leaves the road when its corner rises past full droop (a tall van
        // in a hard turn): it hangs from the body.
        for (int i = 0; i < 4; ++i) {
            const float rise = ((i & 1) ? 0.5f : -0.5f) * track * std::sin(st.roll.x) + (i < 2 ? -0.5f : 0.5f) * wb * std::sin(st.pitch.x) + st.heave.x;
            if (rise > travel) feel.wheelLift[i] = (std::max)(feel.wheelLift[i], rise - travel);
        }

        // ---- tyres: a friction circle each. Braking force split by the axle loads
        // (a little front-biased so the fronts lock first), drive on the rear axle,
        // cornering force shared by load; a tyre's grip falls a little as it is loaded
        // more (load sensitivity). Over ~0.95 of its grip it squeals and marks, past it
        // it slides: skids, smoke.
        float tyre[4];
        {
            const float frontAxle = n[0] + n[1], rearAxle = n[2] + n[3];
            const float bias = Clamp(frontAxle + 0.05f, 0.5f, 0.85f);
            const float rawAx = st.sinceHit < 0.25f ? 0.0f : st.aF / kG, rawAy = st.sinceHit < 0.25f ? 0.0f : st.aL / kG;
            for (int i = 0; i < 4; ++i) {
                const bool fr = i < 2;
                const float axle = fr ? frontAxle : rearAxle;
                const float fx = rawAx < 0.0f ? rawAx * (fr ? bias : 1.0f - bias) * 0.5f : (fr ? 0.0f : rawAx * 0.5f);
                const float fy = rawAy * (fr ? kFront : 1.0f - kFront) * Clamp(n[i] / (std::max)(axle, 0.05f), 0.0f, 1.0f);
                const float ni = (std::max)(n[i], 0.0f);
                const float mu = kMu * Clamp(1.0f - 0.25f * (ni / 0.25f - 1.0f), 0.6f, 1.2f);
                const float cap = (std::max)(mu * ni, 0.01f);
                st.use[i] = std::sqrt(fx * fx + fy * fy) / cap;
                tyre[i] = Smooth((st.use[i] - 0.95f) / 0.35f) * Smooth((speed - 0.8f) / 1.2f);
            }
        }
        // GTA2 keeps the velocity close to the heading even in a handbrake turn, so a
        // slide also shows as the heading swinging faster than a cornering car's: the
        // rear tyres are past their grip.
        const float slide = (std::max)(Smooth((std::fabs(vL) - 0.9f) / 1.2f), Smooth((std::fabs(st.yawRate) - 1.9f) / 1.0f)) *
                            Smooth((speed - 1.2f) / 1.5f);
        for (int i = 0; i < 4; ++i) {
            tyre[i] = (std::max)(tyre[i], i < 2 ? slide * 0.6f : slide);
            st.slip[i] = tyre[i];
        }
        float tyreMax = 0.0f;
        for (int i = 0; i < 4; ++i) {
            tyreMax = (std::max)(tyreMax, tyre[i]);
            const gta2::Vec3 at = Point(w, wheelX[i], 0.0f, wheelZ[i]);
            if (tyre[i] > 0.30f) {
                if (st.skidOn[i]) {
                    const float dx = at.x - st.skidLast[i].x, dz = at.z - st.skidLast[i].z;
                    if (dx * dx + dz * dz > 0.0025f) {
                        AddSkid(st.skidLast[i], at, 0.024f, 0.55f * Clamp(tyre[i], 0.0f, 1.0f), now);
                        st.skidLast[i] = at;
                    }
                } else {
                    st.skidOn[i] = true;
                    st.skidLast[i] = at;
                }
            } else {
                st.skidOn[i] = false;
            }
        }
        if (tyreMax > 0.25f) {
            st.smokeT -= dt * (8.0f + 22.0f * tyreMax);
            while (st.smokeT <= 0.0f) {
                st.smokeT += 1.0f;
                // From the wheel that slides most (two picks, the harder one).
                int i = static_cast<int>(Rand() * 3.99f), j = static_cast<int>(Rand() * 3.99f);
                if (tyre[j] > tyre[i]) i = j;
                const gta2::Vec3 at = Point(w, wheelX[i] * 1.05f, 0.04f, wheelZ[i]);
                EmitSmoke(at, groundY, gta2::Vec3{st.vx * 0.15f, 0.0f, st.vz * 0.15f}, tyre[i], false);
            }
        }

        // ---- the wheels of a hurt corner: camber (top out) and a bent toe that
        // wobbles with the spin.
        for (int i = 0; i < 4; ++i) {
            const float bent = Smooth((st.zone[i] - 5000.0f) / 12000.0f);
            feel.wheelCamber[i] = 0.14f * bent;
            const float rim = Smooth((st.zone[i] - 7000.0f) / 14000.0f);
            feel.wheelToe[i] = rim * (0.03f + 0.05f * std::sin(st.spin + 1.7f * static_cast<float>(i)));
        }
        // ---- the engine: steam past 7000 (more with a hurt front), dark smoke past 16000.
        {
            const float frontHurt = 0.5f * (st.zone[0] + st.zone[1]);
            const float level = (std::max)(Smooth((static_cast<float>(car.damage) - 7000.0f) / 9000.0f),
                                           Smooth((frontHurt - 4000.0f) / 6000.0f));
            if (level > 0.02f) {
                // The game sets a car alight at 16000: its smoke is dark from there, not pale steam
                // (FIX-FX: a burning car's plume read as a flat white-grey column).
                const float dark = Smooth((static_cast<float>(car.damage) - 13000.0f) / 3500.0f);
                st.steamT -= dt * (3.0f + 7.0f * level + 4.0f * dark);
                while (st.steamT <= 0.0f) {
                    st.steamT += 1.0f;
                    const gta2::Vec3 at = Point(w, Rand(-0.25f, 0.25f) * car.width, 0.85f * car.roof, 0.30f * car.length);
                    EmitEngineSmoke(at, groundY, gta2::Vec3{-st.vx * 0.4f, 0.0f, -st.vz * 0.4f}, dark);
                }
            }
        }
        // Exhaust at idle on a cold night (and on a hard launch at night).
        if (g_dark && (speed < 0.3f || st.aF > 5.0f)) {
            st.exhaustT -= dt;
            if (st.exhaustT <= 0.0f) {
                st.exhaustT = speed < 0.3f ? Rand(0.35f, 0.65f) : 0.12f;
                const gta2::Vec3 at = Point(w, 0.28f * car.width, 0.06f, -halfL - 0.03f);
                EmitSmoke(at, groundY, gta2::Vec3{-f.x * 0.22f, 0.0f, -f.z * 0.22f}, 1.0f, true);
            }
        }
    } else if (live) {
        // The sprung body: it leans against the acceleration (out of a turn, onto the
        // nose under braking, back under power), on springs that overshoot a little.
        // GTA2's turns pull up to ~6 blocks/s^2 sideways and its brakes ~15 forward
        // (measured, GTA2DX9_LOG_VEHICLE_FEEL): 4 degrees of roll, 4 of dive at most.
        const float rollTarget = Clamp(0.013f * st.aL, -0.075f, 0.075f);
        const float pitchTarget = Clamp(-0.0055f * st.aF, -0.065f, 0.065f);
        const float heaveTarget = Clamp(-0.0035f * st.aY, -0.03f, 0.03f);

        // Kerbs: a wheel going between road and pavement (or verge) bumps its corner.
        if (speed > 0.5f && g_ground) {
            for (int i = 0; i < 4; ++i) {
                const float sx = (i & 1) ? 0.42f * car.width : -0.42f * car.width;
                const float sz = (i < 2) ? 0.5f * car.wheelbase : -0.5f * car.wheelbase;
                const float wx = x + r.x * sx + f.x * sz, wz = z + r.z * sx + f.z * sz;
                const int type = GroundTypeAt(wx, wz, y + 0.5f);
                if (type && st.ground[i] && type != st.ground[i] && (type == 1 || st.ground[i] == 1)) {
                    const float k = Clamp(speed / 4.0f, 0.25f, 1.0f);
                    st.heave.v += 0.32f * k;
                    st.pitch.v += (i < 2 ? -0.55f : 0.45f) * k;   // the front up first (nose up), then the rear
                    st.roll.v += ((i & 1) ? 0.55f : -0.55f) * k;  // that side up
                }
                if (type) st.ground[i] = type;
            }
        }
        // Impacts: the damage word went up, or the velocity jumped harder than any brake.
        const int dDamage = (st.damage >= 0 && car.damage > st.damage) ? car.damage - st.damage : 0;
        const bool hit = (dDamage > 0 && speed + std::sqrt(st.rvx * st.rvx + st.rvz * st.rvz) > 0.3f) || jolt > 45.0f;
        if (hit) {
            const float k = Clamp((dDamage > 0 ? dDamage / 1500.0f : 0.0f) + (jolt - 30.0f) / 120.0f, 0.2f, 1.0f);
            if (car.driven) g_player.impulse += jolt * dt;
            // The jolt's direction in the car frame: where the push came from.
            float jF = jx * f.x + jz * f.z, jL = jx * r.x + jz * r.z;
            const float jl = std::sqrt(jF * jF + jL * jL);
            if (jl > 1e-3f) { jF /= jl; jL /= jl; } else { jF = vF >= 0.0f ? -1.0f : 1.0f; jL = 0.0f; }
            st.heave.v += 0.25f * k;
            st.roll.v += 1.1f * k * jL;
            st.pitch.v += -0.9f * k * jF;
            // Sparks where the body met the wall: on the side the push came from.
            if (st.sparkT <= 0.0f) {
                const float cx = -jL, cz = -jF;
                const float tx = std::fabs(cx) > 1e-3f ? halfW / std::fabs(cx) : 1e9f, tz = std::fabs(cz) > 1e-3f ? halfL / std::fabs(cz) : 1e9f;
                const float t = (std::min)(tx, tz);
                const float lx = cx * t, lz = cz * t;
                const gta2::Vec3 at = Point(w, lx, 0.12f, lz);
                const gta2::Vec3 along{st.vx * 0.5f, 0.0f, st.vz * 0.5f};
                const gta2::Vec3 out{-(r.x * cx + f.x * cz), 0.0f, -(r.z * cx + f.z * cz)};
                EmitSparks(at, groundY, along, out, 8 + static_cast<int>(22.0f * k));
                st.sparkT = 0.08f;
            }
        }
        // A scrape: sliding along a wall loses speed sideways in steps while the damage
        // creeps up; the spark rate follows the speed.
        if (dDamage > 0 && speed > 1.0f && st.sparkT <= 0.0f) {
            const float side = (vL >= 0.0f) ? 1.0f : -1.0f;
            const gta2::Vec3 at = Point(w, side * halfW, 0.10f, Rand(-0.3f, 0.3f) * halfL);
            EmitSparks(at, groundY, gta2::Vec3{-st.vx * 0.3f, 0.0f, -st.vz * 0.3f}, gta2::Vec3{r.x * side, 0.0f, r.z * side}, 6);
            st.sparkT = 0.05f;
        }
        st.sparkT -= dt;
        st.roll.Step(rollTarget, 1.5f, 0.45f, dt);
        st.pitch.Step(pitchTarget, 1.7f, 0.45f, dt);
        st.heave.Step(heaveTarget, 2.4f, 0.35f, dt);
        st.roll.x = Clamp(st.roll.x, -0.13f, 0.13f);
        st.pitch.x = Clamp(st.pitch.x, -0.10f, 0.10f);
        st.heave.x = Clamp(st.heave.x, -0.04f, 0.05f);

        // Tyres: smoke and marks while they slide (handbrake turns, lateral slip),
        // lock (hard braking) or spin (a hard launch).
        // GTA2 keeps the velocity close to the heading even in a handbrake turn, so a
        // slide shows as the heading swinging faster than the turn rate of a cornering car.
        const float slide = (std::max)(Smooth((std::fabs(vL) - 0.9f) / 1.2f), Smooth((std::fabs(st.yawRate) - 1.9f) / 1.0f)) *
                            Smooth((speed - 1.2f) / 1.5f);
        const float lock = Smooth((-st.aF - 7.0f) / 6.0f) * Smooth((vF - 1.5f) / 1.5f);
        const float launch = Smooth((st.aF - 6.0f) / 5.0f) * (1.0f - Smooth((std::fabs(vF) - 2.5f) / 1.0f));
        const float tyre = (std::max)(slide, (std::max)(lock, launch));
        const float wheelX[4] = {-0.40f * car.width, 0.40f * car.width, -0.40f * car.width, 0.40f * car.width};
        const float wheelZ[4] = {0.5f * car.wheelbase, 0.5f * car.wheelbase, -0.5f * car.wheelbase, -0.5f * car.wheelbase};
        for (int i = 0; i < 4; ++i) {
            const bool front = i < 2;
            const float want = front ? (std::max)(lock, slide * 0.6f) : tyre;
            const gta2::Vec3 at = Point(w, wheelX[i], 0.0f, wheelZ[i]);
            if (want > 0.30f) {
                if (st.skidOn[i]) {
                    const float dx = at.x - st.skidLast[i].x, dz = at.z - st.skidLast[i].z;
                    if (dx * dx + dz * dz > 0.0025f) {
                        AddSkid(st.skidLast[i], at, 0.024f, 0.55f * Clamp(want, 0.0f, 1.0f), now);
                        st.skidLast[i] = at;
                    }
                } else {
                    st.skidOn[i] = true;
                    st.skidLast[i] = at;
                }
            } else {
                st.skidOn[i] = false;
            }
        }
        if (tyre > 0.25f) {
            st.smokeT -= dt * (8.0f + 22.0f * tyre);
            while (st.smokeT <= 0.0f) {
                st.smokeT += 1.0f;
                const int i = 2 + static_cast<int>(Rand() * 1.99f);
                const gta2::Vec3 at = Point(w, wheelX[i] * 1.05f, 0.04f, wheelZ[i]);
                EmitSmoke(at, groundY, gta2::Vec3{st.vx * 0.15f, 0.0f, st.vz * 0.15f}, tyre, false);
            }
        }
        // Exhaust at idle on a cold night (and on a hard launch at night).
        if (g_dark && (speed < 0.3f || st.aF > 5.0f)) {
            st.exhaustT -= dt;
            if (st.exhaustT <= 0.0f) {
                st.exhaustT = speed < 0.3f ? Rand(0.35f, 0.65f) : 0.12f;
                const gta2::Vec3 at = Point(w, 0.28f * car.width, 0.06f, -halfL - 0.03f);
                EmitSmoke(at, groundY, gta2::Vec3{-f.x * 0.22f, 0.0f, -f.z * 0.22f}, 1.0f, true);
            }
        }
    } else {
        st.roll.x = st.pitch.x = st.heave.x = st.shoveX.x = st.shoveZ.x = 0.0f;
        st.roll.v = st.pitch.v = st.heave.v = st.shoveX.v = st.shoveZ.v = 0.0f;
    }

    // Blown up: the car became a wreck (or its damage reached 32000) since we last saw
    // it whole. Debris, a shower of sparks and one wheel off.
    const bool blowing = (car.wreck && st.aliveFrame && frame - st.aliveFrame < 45) || (car.damage >= 32000 && st.damage >= 0 && st.damage < 32000);
    if (g_on && blowing && !st.exploded) {
        st.exploded = true;
        const gta2::Vec3 c = Point(w, 0.0f, 0.15f, 0.0f);
        EmitDebris(c, groundY, car.paint, 22, 1.0f);
        EmitSparks(c, groundY, gta2::Vec3{}, gta2::Vec3{f.x, 0.0f, f.z}, 30);
        for (int i = 0; i < 6; ++i) EmitSmoke(Point(w, Rand(-halfW, halfW), 0.2f, Rand(-halfL, halfL)), groundY, gta2::Vec3{0.0f, 0.3f, 0.0f}, 1.0f, false);
        if (car.wheelPart && ModelIsKnown(car.wheelPart) && g_parts.size() < kMaxParts) {
            Part p{};
            p.model = car.wheelPart; p.fit = car.fit; p.centre = car.wheelCentre;
            const gta2::Vec3 at = Point(w, car.wheelCentre.x, car.wheelCentre.y, car.wheelCentre.z);
            p.x = at.x; p.y = at.y; p.z = at.z;
            const float side = car.wheelCentre.x >= 0.0f ? 1.0f : -1.0f;
            p.vx = r.x * side * Rand(1.2f, 2.0f) + f.x * Rand(-0.6f, 0.6f);
            p.vz = r.z * side * Rand(1.2f, 2.0f) + f.z * Rand(-0.6f, 0.6f);
            p.vy = Rand(2.8f, 3.6f);
            p.wx = Rand(-14.0f, 14.0f); p.wy = Rand(-6.0f, 6.0f);
            p.groundY = groundY; p.radius = car.wheelRadius;
            g_parts.push_back(p);
        }
        Log("vehicle feel: car %p blew up at %.1f,%.1f: debris, sparks%s", reinterpret_cast<const void*>(car.object), x, z,
            car.wheelPart ? " and a wheel off" : "");
    }
    if (!car.wreck) st.aliveFrame = frame;
    st.wreck = car.wreck;
    st.damage = car.damage;

    // The body's pose about a point a little above the road. FIX-VEHICLES: it pitches
    // about a point a quarter of the length ahead of the middle (the anti-dive front
    // geometry's pitch centre, stylised): seen from the chase camera behind, the tail
    // lifts under braking and squats on a launch, which is what reads from there; about
    // the middle a few degrees moved the tail by a few pixels. The drawn angles are the
    // model's times [renderer] car_body_pitch / car_body_roll, at most 7 and 8 degrees
    // (an impact's kick included).
    //
    // FIX-VEHICLE-FEEL-2 (feel2, on by default): the lean is bounded by what the wheels allow. The
    // angles about a point a quarter ahead moved the rear axle by ~0.07 block at the 7 degree cap
    // (pmy1: the rear wheel hung below the sill, the front one stood outside its arch). Now the body
    // pitches about the middle of the wheelbase (nose dips and tail lifts alike) and the pose is
    // scaled down until no axle moves more than the suspension's visible travel against its wheel:
    // half a wheel radius where the wheels are cut and hung from the body (car_bodies.cpp eases each
    // back onto the road within that travel), 0.3 of it where the tyres are part of the body's mesh (a
    // shell: they tilt with it, so the bound is how far a tyre may sink into or lift off the road).
    // A tall body (a van, a truck cab) rolls less and slower, and outside a hit the drawn roll cannot
    // swing faster than a heavy body would (feel10: a jacked cab lurched over and back in a second).
    float pivotY = 0.30f * car.roof, pivotZ = 0.25f * car.length;
    gta2::Mat4 pose = gta2::Identity();
    const float tall = Smooth((car.roof / (std::max)(0.2f, car.width) - 0.95f) / 0.45f);
    float drawRoll = Clamp(st.roll.x * g_rollGain * (g_feel2 ? 1.0f - 0.35f * tall : 1.0f), -0.14f, 0.14f);
    float drawPitch = Clamp(st.pitch.x * g_pitchGain, -0.122f, 0.122f);
    float drawHeave = st.heave.x;
    if (g_forcePitch != 0.0f || g_forceRoll != 0.0f) { drawPitch = g_forcePitch; drawRoll = g_forceRoll; st.drawRoll = drawRoll; }
    float wheelTravel = 0.0f;
    if (live && g_feel2) {
        if (st.sinceHit > 0.35f && g_forcePitch == 0.0f && g_forceRoll == 0.0f) {
            const float slew = (0.75f - 0.35f * tall) * dt;   // rad a step: ~43 deg/s, a tall cab ~23
            drawRoll = Clamp(drawRoll, st.drawRoll - slew, st.drawRoll + slew);
        }
        st.drawRoll = drawRoll;
        pivotZ = 0.0f;
        wheelTravel = car.rigidWheels ? Clamp(0.30f * car.wheelRadius, 0.015f, 0.035f) : Clamp(0.50f * car.wheelRadius, 0.022f, 0.050f);
        wheelTravel *= 1.0f - 0.35f * tall;   // a tall cab's tyres are in its mesh too: <5 degrees of roll
        const float wx = 0.42f * car.width, wz = 0.5f * (std::max)(0.25f, car.wheelbase), wy = car.wheelRadius;
        auto worst = [&](float rl, float pt, float hv) {
            const gta2::Mat4 m = Mul(Mul(Mul(Translate(0.0f, -pivotY, 0.0f), RotZ(rl)), RotX(pt)), Translate(0.0f, pivotY + hv, 0.0f));
            float d = 0.0f;
            for (int i = 0; i < 4; ++i) {
                const float px = (i & 1) ? wx : -wx, pz = i < 2 ? wz : -wz;
                d = (std::max)(d, std::fabs(px * m.m[0][1] + wy * m.m[1][1] + pz * m.m[2][1] + m.m[3][1] - wy));
            }
            return d;
        };
        const float d = worst(drawRoll, drawPitch, drawHeave);
        if (d > wheelTravel) {
            const float k = wheelTravel / d;
            drawRoll *= k; drawPitch *= k; drawHeave *= k;
        }
    } else if (live) st.drawRoll = drawRoll;
    if (live) {
        pose = Mul(Mul(Mul(Translate(0.0f, -pivotY, -pivotZ), RotZ(drawRoll)), RotX(drawPitch)),
                   Translate(g_physics ? st.shoveX.x : 0.0f, pivotY + drawHeave, pivotZ + (g_physics ? st.shoveZ.x : 0.0f)));
    }
    feel.pose = pose;
    feel.wheelTravel = wheelTravel;
    feel.steer = st.steer;
    feel.spin = st.spin;
    feel.brake = st.brake;
    feel.reverse = st.reverse;
    feel.speed = vF;
    if (car.driven) {
        g_player.frame = frame;
        g_player.pitch = live ? drawPitch : 0.0f;
        g_player.roll = live ? drawRoll : 0.0f;
        g_player.heave = live ? drawHeave : 0.0f;
    }
    if (g_logFeel > 0 && car.driven && frame % 3 == 0) {
        Log("vehicle feel: player car v=%.2f lat=%.2f yawr=%.2f aF=%.1f aL=%.1f jolt=%.0f roll=%.1f pitch=%.1f heave=%.3f steer=%.2f brake=%.2f rev=%.2f dmg=%d ground=%d%d%d%d",
            vF, vL, st.yawRate, st.aF, st.aL, jolt, drawRoll * 180.0f / kPi, drawPitch * 180.0f / kPi, st.heave.x, st.steer, st.brake, st.reverse, car.damage,
            st.ground[0], st.ground[1], st.ground[2], st.ground[3]);
        if (frame % 90 == 0)
            Log("vehicle feel: player car dims L=%.2f W=%.2f roof=%.2f wb=%.2f r=%.3f rigid=%d tall=%.2f travel=%.3f feel2=%d model roll=%.1f pitch=%.1f",
                car.length, car.width, car.roof, car.wheelbase, car.wheelRadius, car.rigidWheels ? 1 : 0, tall, wheelTravel, g_feel2 ? 1 : 0,
                st.roll.x * 180.0f / kPi, st.pitch.x * 180.0f / kPi);
        if (g_physics && live)
            Log("vehicle physics: player car load=%.2f %.2f %.2f %.2f use=%.2f %.2f %.2f %.2f slip=%.2f %.2f %.2f %.2f carried=%.2f,%.2f g "
                "shove=%.3f,%.3f lift=%.3f %.3f %.3f %.3f camber=%.1f %.1f %.1f %.1f corners=%.0f %.0f %.0f %.0f wear=%.2f ride=%.2fHz defl=%.4f",
                st.load[0], st.load[1], st.load[2], st.load[3], st.use[0], st.use[1], st.use[2], st.use[3],
                st.slip[0], st.slip[1], st.slip[2], st.slip[3], axT, ayT, st.shoveX.x, st.shoveZ.x,
                feel.wheelLift[0], feel.wheelLift[1], feel.wheelLift[2], feel.wheelLift[3],
                feel.wheelCamber[0] * 180.0f / kPi, feel.wheelCamber[1] * 180.0f / kPi, feel.wheelCamber[2] * 180.0f / kPi, feel.wheelCamber[3] * 180.0f / kPi,
                st.zone[0], st.zone[1], st.zone[2], st.zone[3], wear, rideHz, staticDefl);
    }
    (void)up;
    g_updateMs += NowMs() - t0;
    return feel;
}

namespace {
struct PuffQuad { gta2::Vec3 c, a, b; DWORD colour; DWORD opaque; int level; int seed; };   // opaque: alpha 1, the opacity in the level texture
std::vector<PuffQuad> g_puffQuads;

// The dithered steps of the puff (see g_puffLevelTex), managed, one a frame like EnsureTextures.
bool PuffLevelsReady(IDirect3DDevice9* device) {
    static bool failed = false;
    constexpr int kCount = kPuffLevels * kPuffSeeds;
    if (g_puffLevelTex[kCount - 1]) return true;
    if (failed) return false;
    for (int i = 0; i < kCount; ++i) {
        if (g_puffLevelTex[i]) continue;
        const int k = i % kPuffLevels, seed = i / kPuffLevels;
        IDirect3DTexture9* tex = nullptr;
        constexpr int N = kPuffDitherSize;
        if (FAILED(device->CreateTexture(N, N, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &tex, nullptr))) { failed = true; return false; }
        D3DLOCKED_RECT lr;
        if (SUCCEEDED(tex->LockRect(0, &lr, nullptr, 0))) {
            const float level = (k + 1) * kPuffLevelStep;
            for (int y = 0; y < N; ++y) {
                uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
                for (int x = 0; x < N; ++x) {
                    // Covered or not: the opacity as the share of covered texels (one noise per seed for
                    // every step, so a thicker step covers what a thinner one does and more).
                    const float cover = PuffTexel((x + 0.5f) / N, (y + 0.5f) / N) * level;
                    row[x] = cover > Hash2(x + seed * 977, y + seed * 631) ? Argb(1.0f, 1.0f, 1.0f, 1.0f) : Argb(0.0f, 1.0f, 1.0f, 1.0f);
                }
            }
            tex->UnlockRect(0);
        }
        g_puffLevelTex[i] = tex;
        if (i < kCount - 1) return false;
    }
    return true;
}

// Mode 1's steps: a coherent noise per seed, ranked to a uniform [0,1) so a texel is covered with the old
// probability (PuffTexel * level), the field written as alpha 0.5 + gain * (cover - noise): its 0.5 level
// line, which the bilinear alpha test cuts along, is the covered set's smooth edge.
float ValueNoise(float x, float y, int period, int seed) {
    const int x0 = static_cast<int>(std::floor(x)), y0 = static_cast<int>(std::floor(y));
    const float fx = x - x0, fy = y - y0;
    const float sx = fx * fx * (3.0f - 2.0f * fx), sy = fy * fy * (3.0f - 2.0f * fy);
    auto h = [&](int i, int j) { return Hash2(((i % period) + period) % period + seed * 7919, ((j % period) + period) % period + seed * 104729); };
    const float a = h(x0, y0) + (h(x0 + 1, y0) - h(x0, y0)) * sx;
    const float b = h(x0, y0 + 1) + (h(x0 + 1, y0 + 1) - h(x0, y0 + 1)) * sx;
    return a + (b - a) * sy;
}

bool PuffWispsReady(IDirect3DDevice9* device) {
    static bool failed = false;
    constexpr int kCount = kPuffLevels * kPuffSeeds;
    if (g_puffWispTex[kCount - 1]) return true;
    if (failed) return false;
    constexpr int N = kPuffDitherSize;
    static std::vector<float> rank[kPuffSeeds];
    for (int i = 0; i < kCount; ++i) {
        if (g_puffWispTex[i]) continue;
        const int k = i % kPuffLevels, seed = i / kPuffLevels;
        if (rank[seed].empty()) {
            std::vector<float> f(N * N);
            for (int y = 0; y < N; ++y)
                for (int x = 0; x < N; ++x) {
                    const float u = (x + 0.5f) / N * 16.0f, v = (y + 0.5f) / N * 16.0f;
                    f[y * N + x] = 0.55f * ValueNoise(u, v, 16, seed + 11) + 0.30f * ValueNoise(u * 2.0f, v * 2.0f, 32, seed + 31)
                                 + 0.15f * ValueNoise(u * 4.0f, v * 4.0f, 64, seed + 53);
                }
            std::vector<int> order(N * N);
            for (int j = 0; j < N * N; ++j) order[j] = j;
            std::sort(order.begin(), order.end(), [&](int a, int b) { return f[a] < f[b]; });
            rank[seed].assign(N * N, 0.0f);
            for (int j = 0; j < N * N; ++j) rank[seed][order[j]] = (j + 0.5f) / (N * N);
        }
        IDirect3DTexture9* tex = nullptr;
        if (FAILED(device->CreateTexture(N, N, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &tex, nullptr))) { failed = true; return false; }
        D3DLOCKED_RECT lr;
        if (SUCCEEDED(tex->LockRect(0, &lr, nullptr, 0))) {
            const float level = (k + 1) * kPuffLevelStep;
            for (int y = 0; y < N; ++y) {
                uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
                for (int x = 0; x < N; ++x) {
                    const float cover = PuffTexel((x + 0.5f) / N, (y + 0.5f) / N) * level;
                    // Shading in the albedo (Remix lights each covered texel as a flat card): a wisp is lighter
                    // where it is thick (far inside its edge) and towards the puff's middle, darker at its rim.
                    const float depth = Clamp((cover - rank[seed][y * N + x]) * 10.0f, 0.0f, 1.0f);
                    const float shade = (0.62f + 0.38f * depth) * (0.82f + 0.18f * PuffTexel((x + 0.5f) / N, (y + 0.5f) / N));
                    row[x] = Argb(0.5f + 6.0f * (cover - rank[seed][y * N + x]), shade, shade, shade);
                }
            }
            tex->UnlockRect(0);
        }
        g_puffWispTex[i] = tex;
        if (i < kCount - 1) return false;
    }
    return true;
}

}  // namespace

void VehicleFxSetPuffLevels(bool on) { g_puffLevelsOn = on; }
void VehicleFxSetRemixPuffMode(int mode) { g_remixPuffMode = mode; }

// [devtools] spawn_smoke (FIX-REMIX-NIGHT): a tyre-smoke puff and a steam puff at `at`, every frame it is called.
void VehicleFxProbeSmoke(const gta2::Vec3& at, float groundY) {
    EmitSmoke(at, groundY, gta2::Vec3{0.0f, 0.0f, 0.0f}, 1.0f, false);
    EmitEngineSmoke(gta2::Vec3{at.x + 0.6f, at.y, at.z}, groundY, gta2::Vec3{0.0f, 0.0f, 0.0f}, 0.0f);
}

void VehicleFxDraw(IDirect3DDevice9* device, const gta2::Vec3& eye, uint32_t frame, bool remix) {
    ReadEnv();
    const double t0 = NowMs();
    const float dt = (g_clockFrame && frame > g_clockFrame) ? (std::min)(6u, frame - g_clockFrame) * kStep : 0.0f;
    g_clockFrame = frame;
    const float now = static_cast<float>(frame) * kStep;
    if (frame % 300 == 0) {
        for (auto it = g_cars.begin(); it != g_cars.end();) it = (frame - it->second.frame > 600) ? g_cars.erase(it) : std::next(it);
    }
    const bool hadTextures = g_shardTex != nullptr;
    if (!EnsureTextures(device)) g_cones.clear();
    double mark[8] = {};
    int nm = 0;
    mark[nm++] = NowMs();

    // Simulate.
    for (size_t i = 0; i < g_particles.size();) {
        Particle& p = g_particles[i];
        p.age += dt;
        if (p.age >= p.life) { p = g_particles.back(); g_particles.pop_back(); continue; }
        switch (p.kind) {
            case kSmoke: case kExhaust: {
                const float drag = std::exp(-1.6f * dt);
                p.vx *= drag; p.vz *= drag; p.vy = p.vy * std::exp(-0.6f * dt) + 0.02f * dt;
                break;
            }
            case kSpark: {
                p.vy -= 7.0f * dt;
                const float drag = std::exp(-1.2f * dt);
                p.vx *= drag; p.vz *= drag;
                if (p.y + p.vy * dt < p.groundY + 0.01f && p.vy < 0.0f) { p.vy = -p.vy * 0.35f; p.vx *= 0.6f; p.vz *= 0.6f; }
                break;
            }
            case kDebris: {
                p.vy -= 7.0f * dt;
                if (p.y + p.vy * dt < p.groundY + 0.012f && p.vy < 0.0f) {
                    p.vy = -p.vy * 0.30f; p.vx *= 0.5f; p.vz *= 0.5f; p.rotV *= 0.5f;
                    if (std::fabs(p.vy) < 0.3f) { p.vy = 0.0f; p.y = p.groundY + 0.012f; p.vx *= 0.3f; p.vz *= 0.3f; p.rotV = 0.0f; }
                }
                break;
            }
        }
        p.x += p.vx * dt; p.y += p.vy * dt; p.z += p.vz * dt;
        p.rot += p.rotV * dt;
        ++i;
    }
    for (size_t i = 0; i < g_parts.size();) {
        Part& p = g_parts[i];
        p.age += dt;
        if (p.age > 30.0f || !ModelIsKnown(p.model)) { p = g_parts.back(); g_parts.pop_back(); continue; }
        p.vy -= 7.0f * dt;
        p.x += p.vx * dt; p.y += p.vy * dt; p.z += p.vz * dt;
        p.ax += p.wx * dt; p.ay += p.wy * dt;
        if (p.y < p.groundY + p.radius * 0.35f && p.vy < 0.0f) {
            p.y = p.groundY + p.radius * 0.35f;
            p.vy = -p.vy * 0.35f;
            p.vx *= 0.6f; p.vz *= 0.6f; p.wx *= 0.6f; p.wy *= 0.5f;
            if (p.vy < 0.4f) {
                // Down: it falls flat on its side and stays.
                p.vy = 0.0f; p.vx *= 0.5f; p.vz *= 0.5f; p.wx = 0.0f; p.wy = 0.0f;
            }
        }
        ++i;
    }

    mark[nm++] = NowMs();
    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;

    // Flying parts first: lit like the bodies (the caller's light and material are still set).
    if (!g_parts.empty()) {
        for (const Part& p : g_parts) {
            float ax = p.ax;
            // Resting: lying on its side (a quarter turn about the car's forward axis).
            const bool resting = p.vy == 0.0f && p.wx == 0.0f;
            gta2::Mat4 m = Mul(Translate(-p.centre.x, -p.centre.y, -p.centre.z), RotX(ax));
            m = Mul(m, resting ? RotZ(kPi * 0.5f) : RotZ(0.0f));
            m = Mul(m, RotY(p.ay));
            m = Mul(m, Translate(p.x, p.y, p.z));
            ModelDraw(device, *p.model, Mul(p.fit, m), nullptr, 0.0f);
        }
        device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
    }

    device->SetTransform(D3DTS_WORLD, &identity);
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
    device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    if (g_smooth) {
        device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
        device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    }
    device->SetFVF(kFxFvf);
    DWORD fogColour = 0;
    device->GetRenderState(D3DRS_FOGCOLOR, &fogColour);

    // Skid marks: dark rubber on the road, fading after kSkidHold seconds.
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    for (const Skid& s : g_skids) {
        const float age = now - s.born;
        if (age < 0.0f || age > kSkidHold + kSkidFade) continue;
        const float dx = s.p[0][0] - eye.x, dz = s.p[0][2] - eye.z;
        if (dx * dx + dz * dz > 60.0f * 60.0f) continue;
        const float a = s.alpha * (age < kSkidHold ? 1.0f : 1.0f - (age - kSkidHold) / kSkidFade);
        const DWORD col = Colour(0.06f, 0.06f, 0.06f, a);
        if (g_verts.size() + 4 > 65532) break;
        const uint16_t base = static_cast<uint16_t>(g_verts.size());
        const float uv[4][2] = {{0, 0}, {1, 0}, {1, 1}, {0, 1}};
        for (int k = 0; k < 4; ++k) g_verts.push_back(FxVertex{s.p[k][0], s.p[k][1], s.p[k][2], col, uv[k][0], uv[k][1]});
        const uint16_t t[6] = {base, static_cast<uint16_t>(base + 1), static_cast<uint16_t>(base + 2), base, static_cast<uint16_t>(base + 2), static_cast<uint16_t>(base + 3)};
        g_index.insert(g_index.end(), t, t + 6);
    }
    Flush(device, g_stripTex);
    mark[nm++] = NowMs();

    // Head-lamp pools on the road (plain renderer: under Remix the lamps are lights).
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_ONE);
    device->SetRenderState(D3DRS_FOGCOLOR, 0x00000000u);   // additive: fog must fade it to nothing, not to haze
    if (g_on && !remix && g_dark && !g_cones.empty()) {
        // The nearest few.
        auto dist = [&](const Cone& c) { const float dx = c.carToWorld.m[3][0] - eye.x, dz = c.carToWorld.m[3][2] - eye.z; return dx * dx + dz * dz; };
        if (static_cast<int>(g_cones.size()) > kMaxCones) {
            std::partial_sort(g_cones.begin(), g_cones.begin() + kMaxCones, g_cones.end(), [&](const Cone& a, const Cone& b) { return dist(a) < dist(b); });
            g_cones.resize(kMaxCones);
        }
        for (const Cone& c : g_cones) {
            if (dist(c) > 40.0f * 40.0f) continue;
            const gta2::Mat4& w = c.carToWorld;
            const float nose = 0.5f * c.length - 0.02f, reach = 2.6f;
            const float nearHalf = 0.42f * c.width, farHalf = 0.85f;
            const gta2::Vec3 p[4] = {Point(w, -nearHalf, 0.012f, nose), Point(w, nearHalf, 0.012f, nose),
                                     Point(w, farHalf, 0.012f, nose + reach), Point(w, -farHalf, 0.012f, nose + reach)};
            const DWORD col = Colour(0.62f, 0.57f, 0.47f, 1.0f);
            if (g_verts.size() + 4 > 65532) break;
            const uint16_t base = static_cast<uint16_t>(g_verts.size());
            const float uv[4][2] = {{0, 0}, {1, 0}, {1, 1}, {0, 1}};
            for (int k = 0; k < 4; ++k) g_verts.push_back(FxVertex{p[k].x, p[k].y, p[k].z, col, uv[k][0], uv[k][1]});
            const uint16_t t[6] = {base, static_cast<uint16_t>(base + 1), static_cast<uint16_t>(base + 2), base, static_cast<uint16_t>(base + 2), static_cast<uint16_t>(base + 3)};
            g_index.insert(g_index.end(), t, t + 6);
        }
        Flush(device, g_coneTex);
    }
    g_cones.clear();
    mark[nm++] = NowMs();

    // Sparks: short additive streaks along their flight.
    const gta2::Vec3 worldUp{0.0f, 1.0f, 0.0f};
    for (const Particle& p : g_particles) {
        if (p.kind != kSpark) continue;
        const gta2::Vec3 c{p.x, p.y, p.z};
        const gta2::Vec3 toEye = gta2::Normalize(eye - c);
        gta2::Vec3 dir{p.vx, p.vy, p.vz};
        const float sp = std::sqrt(gta2::Dot(dir, dir));
        dir = sp > 1e-4f ? dir * (1.0f / sp) : worldUp;
        const float len = Clamp(sp * 0.03f, 0.015f, 0.09f);
        gta2::Vec3 side = gta2::Normalize(gta2::Cross(dir, toEye));
        const float fade = 1.0f - p.age / p.life;
        Quad(c, dir * len, side * p.size0, Colour(p.r * fade, p.g * fade, p.b * fade, 1.0f));
    }
    Flush(device, g_glowTex);
    device->SetRenderState(D3DRS_FOGCOLOR, fogColour);
    mark[nm++] = NowMs();

    // Smoke and exhaust: soft puffs that grow, pale and thin out.
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    // FIX-FX (pm7): the puffs take the scene's light (a third of it at night, a quarter of the
    // sky's tint), and thin out as the eye gets into them, so a plume the chase camera passes
    // through stays local haze instead of a flat white-grey veil over the whole frame.
    float shade[3] = {1.0f, 1.0f, 1.0f};
    {
        const float el = gta2::SkyConfig().sunElevationDeg;
        const float day = Smooth((el + 4.0f) / 14.0f);
        const float level = 0.36f + 0.64f * day;
        const float fc[3] = {((fogColour >> 16) & 255) / 255.0f, ((fogColour >> 8) & 255) / 255.0f, (fogColour & 255) / 255.0f};
        const float fm = (std::max)(0.05f, (fc[0] + fc[1] + fc[2]) / 3.0f);
        for (int c = 0; c < 3; ++c) shade[c] = (std::min)(1.0f, level * (0.75f + 0.25f * fc[c] / fm));
    }
    for (const Particle& p : g_particles) {
        if (p.kind != kSmoke && p.kind != kExhaust) continue;
        const gta2::Vec3 c{p.x, p.y, p.z};
        const gta2::Vec3 toEye = gta2::Normalize(eye - c);
        gta2::Vec3 right = gta2::Cross(worldUp, toEye);
        if (gta2::Dot(right, right) < 1e-6f) right = {1.0f, 0.0f, 0.0f};
        right = gta2::Normalize(right);
        const gta2::Vec3 up = gta2::Cross(toEye, right);
        const float t = p.age / p.life;
        const float size = p.size0 + (p.size1 - p.size0) * (1.0f - (1.0f - t) * (1.0f - t));
        const float cs = std::cos(p.rot) * size, sn = std::sin(p.rot) * size;
        const gta2::Vec3 a = right * cs + up * sn, b = up * cs - right * sn;
        const float eyeD = std::sqrt(gta2::Dot(eye - c, eye - c));
        const float nearK = Smooth((eyeD / (std::max)(0.02f, size) - 0.6f) / 2.4f);
        const float alpha = p.a * Smooth(t / 0.12f) * (1.0f - Smooth((t - 0.35f) / 0.65f)) * nearK;
        if (alpha < 0.004f) continue;
        const float grey = p.r + (1.0f - p.r) * 0.3f * t;
        const int level = static_cast<int>(Clamp(std::floor(alpha / kPuffLevelStep + 0.5f) - 1.0f, 0.0f, kPuffLevels - 1.0f));
        if (remix && g_remixPuffMode == 3 && p.kind == kExhaust) continue;
        // Mode 0: a new pattern every frame; mode 1: one per puff for its life (its size1 is its own random draw).
        uint32_t own;
        std::memcpy(&own, &p.size1, sizeof own);
        const int seed = g_remixPuffMode == 0 ? static_cast<int>((frame + g_puffQuads.size()) % kPuffSeeds)
                                              : static_cast<int>((own ^ (own >> 7) ^ (own >> 15)) % kPuffSeeds);
        g_puffQuads.push_back({c, a, b, Colour(grey * shade[0], grey * shade[1], grey * 1.02f * shade[2], alpha),
                               Colour(grey * shade[0], grey * shade[1], grey * 1.02f * shade[2], 1.0f), level, seed});
    }
    const bool wisps = remix && g_remixPuffMode != 0;
    if (remix && g_remixPuffMode == 2) {
        // [devtools] remix_puff_mode=2: no puffs under Remix (the A/B for the firefly specks).
    } else if (remix && g_puffLevelsOn && (wisps ? PuffWispsReady(device) : PuffLevelsReady(device))) {
        // One batch per opacity step, the opacity in the texture (see g_puffLevelTex).
        // With normals: a camera-facing quad with none gets its normal from its winding, level with the
        // ground, and in the path tracer it took almost no sun or lamp light (black puffs at noon). A puff
        // is lit like a cloud: from above, a little towards the eye.
        struct LitVertex { float x, y, z, nx, ny, nz; DWORD color; float u, v; };
        static std::vector<LitVertex> lit;
        static std::vector<uint16_t> idx;
        device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_DIFFUSE | D3DFVF_TEX1);
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
        device->SetRenderState(D3DRS_ALPHAREF, 128u);
        device->SetRenderState(D3DRS_ALPHAFUNC, D3DCMP_GREATEREQUAL);
        const D3DTEXTUREFILTERTYPE filter = wisps ? D3DTEXF_LINEAR : D3DTEXF_POINT;
        device->SetSamplerState(0, D3DSAMP_MAGFILTER, filter);
        device->SetSamplerState(0, D3DSAMP_MINFILTER, filter);
        for (int k = 0; k < kPuffLevels * kPuffSeeds; ++k) {
            lit.clear(); idx.clear();
            for (const PuffQuad& q : g_puffQuads) {
                if (q.level + kPuffLevels * q.seed != k || lit.size() + 4 > 65532) continue;
                gta2::Vec3 n = gta2::Normalize(gta2::Normalize(eye - q.c) * 0.35f + worldUp);
                const uint16_t base = static_cast<uint16_t>(lit.size());
                const float uv[4][2] = {{0, 1}, {1, 1}, {1, 0}, {0, 0}};
                const float sg[4][2] = {{-1, -1}, {1, -1}, {1, 1}, {-1, 1}};
                for (int v = 0; v < 4; ++v)
                    lit.push_back({q.c.x + sg[v][0] * q.a.x + sg[v][1] * q.b.x, q.c.y + sg[v][0] * q.a.y + sg[v][1] * q.b.y,
                                   q.c.z + sg[v][0] * q.a.z + sg[v][1] * q.b.z, n.x, n.y, n.z, q.opaque, uv[v][0], uv[v][1]});
                const uint16_t t[6] = {base, static_cast<uint16_t>(base + 1), static_cast<uint16_t>(base + 2), base,
                                       static_cast<uint16_t>(base + 2), static_cast<uint16_t>(base + 3)};
                idx.insert(idx.end(), t, t + 6);
            }
            if (idx.empty()) continue;
            device->SetTexture(0, wisps ? g_puffWispTex[k] : g_puffLevelTex[k]);
            device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(lit.size()), static_cast<UINT>(idx.size() / 3),
                                           idx.data(), D3DFMT_INDEX16, lit.data(), sizeof(LitVertex));
        }
        device->SetFVF(kFxFvf);
        device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
        const D3DTEXTUREFILTERTYPE back = g_smooth ? D3DTEXF_LINEAR : D3DTEXF_POINT;
        device->SetSamplerState(0, D3DSAMP_MAGFILTER, back);
        device->SetSamplerState(0, D3DSAMP_MINFILTER, back);
    } else {
        for (const PuffQuad& q : g_puffQuads) Quad(q.c, q.a, q.b, q.colour);
        Flush(device, g_puffTex);
    }
    g_puffQuads.clear();
    mark[nm++] = NowMs();

    // Debris: tumbling shards of panel, trim and glass.
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHAREF, 128u);
    device->SetRenderState(D3DRS_ALPHAFUNC, D3DCMP_GREATEREQUAL);
    for (const Particle& p : g_particles) {
        if (p.kind != kDebris) continue;
        const gta2::Vec3 c{p.x, p.y, p.z};
        const gta2::Vec3 toEye = gta2::Normalize(eye - c);
        gta2::Vec3 right = gta2::Cross(worldUp, toEye);
        if (gta2::Dot(right, right) < 1e-6f) right = {1.0f, 0.0f, 0.0f};
        right = gta2::Normalize(right);
        const gta2::Vec3 up = gta2::Cross(toEye, right);
        // Tumbling: the shard foreshortens as it turns.
        const float squash = 0.35f + 0.65f * std::fabs(std::cos(p.rot * 0.7f));
        // FIX-FX-2: a shard flying past the eye (the death camera a block off the blast) was a
        // plate a fifth of the screen wide: it shrinks away inside half a block of the eye.
        const gta2::Vec3 toE = eye - c;
        const float nearK = Clamp((std::sqrt(gta2::Dot(toE, toE)) - 0.10f) / 0.40f, 0.0f, 1.0f);
        if (nearK < 0.05f) continue;
        const float cs = std::cos(p.rot) * p.size0 * nearK, sn = std::sin(p.rot) * p.size0 * nearK;
        const gta2::Vec3 a = right * cs + up * sn, b = (up * cs - right * sn) * squash;
        const float fade = p.life - p.age < 1.0f ? (p.life - p.age) : 1.0f;
        // FIX-FX-2 (pm10): lit like the smoke (the scene's light), brighter when a face turns
        // to the eye (the squash is that turn), and a burning bit glows for its first second.
        const float glint = 0.55f + 0.45f * squash * squash;
        const float heat = p.hot ? Clamp(1.0f - p.age / 1.1f, 0.0f, 1.0f) : 0.0f;
        const float hr = p.r * shade[0] * glint + 0.95f * heat, hg = p.g * shade[1] * glint + 0.42f * heat,
                    hb = p.b * shade[2] * glint + 0.10f * heat;
        QuadCell(c, a, b, Colour(hr, hg, hb, fade), p.cell);
    }
    Flush(device, g_shardTex);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    mark[nm++] = NowMs();

    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetTexture(0, nullptr);
    if (g_smooth) {
        device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
        device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
    }

    g_lastMs = g_updateMs + (NowMs() - t0);
    static int slowLogged = 0;
    if (g_lastMs > 8.0 && slowLogged < 40) {
        // Where a slow effects pass went: the car updates, textures, simulation, parts,
        // skid marks, lamp pools, sparks, smoke, debris (ms).
        ++slowLogged;
        Log("vehicle feel: slow frame %.1f ms: updates %.1f, textures %.1f%s, sim %.1f, parts+skids %.1f, pools %.1f, sparks %.1f, smoke %.1f, debris %.1f",
            g_lastMs, g_updateMs, mark[0] - t0, hadTextures ? "" : " (made)", mark[1] - mark[0], mark[2] - mark[1], mark[3] - mark[2],
            mark[4] - mark[3], mark[5] - mark[4], mark[6] - mark[5]);
    }
    g_updateMs = 0.0;
    g_sumMs += g_lastMs; ++g_sumFrames;
    g_worstMs = (std::max)(g_worstMs, g_lastMs);
    if (frame % 900 == 0 && g_sumFrames) {
        Log("vehicle feel: %zu cars tracked, %zu particles, %zu skid segments, %zu flying parts; %.3f ms a frame (worst %.2f) over %d frames",
            g_cars.size(), g_particles.size(), g_skids.size(), g_parts.size(), g_sumMs / g_sumFrames, g_worstMs, g_sumFrames);
        g_sumMs = 0.0; g_sumFrames = 0; g_worstMs = 0.0;
    }
}

void VehicleFxReleaseDevice() {
    for (IDirect3DTexture9** t : {&g_puffTex, &g_glowTex, &g_stripTex, &g_coneTex, &g_shardTex}) {
        if (*t) { (*t)->Release(); *t = nullptr; }
    }
    for (IDirect3DTexture9*& t : g_puffLevelTex) {
        if (t) { t->Release(); t = nullptr; }
    }
    for (IDirect3DTexture9*& t : g_puffWispTex) {
        if (t) { t->Release(); t = nullptr; }
    }
    if (g_vb) { g_vb->Release(); g_vb = nullptr; }
    if (g_ib) { g_ib->Release(); g_ib = nullptr; }
    g_vbFailed = false;
    g_device = nullptr;
}

void VehicleFxStats(int* particles, int* skids, double* ms) {
    if (particles) *particles = static_cast<int>(g_particles.size());
    if (skids) *skids = static_cast<int>(g_skids.size());
    if (ms) *ms = g_lastMs;
}

// FIX-PERF-4: this module's caches for the `mem:` lines (mem_stats.h).
void VehicleFxMemGauges() {
    MemGauge("vf.cars", static_cast<double>(g_cars.size()));
    MemGauge("vf.skids", static_cast<double>(g_skids.size()));
    MemGauge("vf.particles", static_cast<double>(g_particles.size() + g_parts.size()));
}

}  // namespace gta2dx9
