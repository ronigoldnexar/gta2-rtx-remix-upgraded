// See vehicle_fx.h.
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
        p.size0 = p.size1 = Rand(0.03f, 0.075f);
        p.rot = Rand(0.0f, 2.0f * kPi); p.rotV = Rand(-9.0f, 9.0f);
        // Panels in the car's (scorched) paint, the rest dark metal and glass.
        const float k = Rand();
        if (k < 0.55f) { const float d = Rand(0.35f, 0.6f); p.r = paint[0] * d; p.g = paint[1] * d; p.b = paint[2] * d; }
        else if (k < 0.85f) { p.r = p.g = p.b = Rand(0.10f, 0.22f); }
        else { p.r = 0.55f; p.g = 0.62f; p.b = 0.66f; }
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

template <typename F>
IDirect3DTexture9* MakeTexture(IDirect3DDevice9* device, int w, int h, F texel) {
    IDirect3DTexture9* tex = nullptr;
    if (FAILED(device->CreateTexture(w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &tex, nullptr))) return nullptr;
    D3DLOCKED_RECT lr;
    if (SUCCEEDED(tex->LockRect(0, &lr, nullptr, 0))) {
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
        g_puffTex = MakeTexture(device, 64, 64, [](float u, float v) {
            const float dx = u - 0.5f, dy = v - 0.5f;
            const float r = std::sqrt(dx * dx + dy * dy) * 2.0f;
            const float ang = std::atan2(dy, dx);
            const float lump = 0.88f + 0.12f * std::sin(ang * 5.0f + 1.3f) * std::sin(ang * 3.0f);
            float a = Clamp(1.0f - r / lump, 0.0f, 1.0f);
            a = a * a * (3.0f - 2.0f * a);
            return Argb(a, 1.0f, 1.0f, 1.0f);
        });
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
        g_coneTex = MakeTexture(device, 64, 64, [](float u, float v) {
            const float across = std::fabs(u - 0.5f) * 2.0f;
            const float side = 1.0f - Smooth((across - 0.55f) / 0.45f);
            const float nearRamp = Smooth(v / 0.10f);
            const float fall = std::pow(Clamp(1.0f - v, 0.0f, 1.0f), 1.6f);
            const float hot = 1.0f + 0.35f * std::exp(-across * across * 6.0f);
            const float k = Clamp(side * nearRamp * fall * hot, 0.0f, 1.0f);
            return Argb(k, k, k, k);
        });
    }
    else if (!g_shardTex) {
        // A jagged shard: a seven-sided polygon with uneven corners, hard-edged.
        g_shardTex = MakeTexture(device, 32, 32, [](float u, float v) {
            const float dx = u - 0.5f, dy = v - 0.5f;
            const float ang = std::atan2(dy, dx);
            const float r = std::sqrt(dx * dx + dy * dy) * 2.0f;
            const float lim = 0.62f + 0.30f * std::fabs(std::sin(ang * 3.5f + 0.7f));
            const float a = r < lim ? 1.0f : 0.0f;
            const float shade = 0.80f + 0.20f * (dx - dy);
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
            if (SUCCEEDED(g_vb->Lock(first * 4 * sizeof(FxVertex), quads * 4 * sizeof(FxVertex), &p, discard ? D3DLOCK_DISCARD : D3DLOCK_NOOVERWRITE))) {
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
    g_logFeel = GetEnvironmentVariableA("GTA2DX9_LOG_VEHICLE_FEEL", v, sizeof v) ? atoi(v) : 0;
    g_particles.reserve(kMaxParticles);
    g_skids.reserve(kMaxSkids);
    Log("vehicle feel: %s (sprung bodies, turning wheels, lamps, smoke, skid marks, sparks, debris)", g_on ? "on" : "off");
}

}  // namespace

void VehicleFxSetGround(const GroundSampler* ground) { g_ground = ground; }
void VehicleFxSetEnabled(bool on) {
    ReadEnv();
    if (on != g_on) Log("vehicle feel: %s", on ? "on" : "off");
    g_on = on;
}
bool VehicleFxEnabled() { ReadEnv(); return g_on; }
void VehicleFxSetDark(bool dark) { g_dark = dark; }

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
    if (live) {
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
        st.roll.x = st.pitch.x = st.heave.x = 0.0f;
        st.roll.v = st.pitch.v = st.heave.v = 0.0f;
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

    // The body's pose about a point a little above the road, under the middle.
    const float pivotY = 0.30f * car.roof;
    gta2::Mat4 pose = gta2::Identity();
    if (live) {
        pose = Mul(Mul(Mul(Translate(0.0f, -pivotY, 0.0f), RotZ(st.roll.x)), RotX(st.pitch.x)),
                   Translate(0.0f, pivotY + st.heave.x, 0.0f));
    }
    feel.pose = pose;
    feel.steer = st.steer;
    feel.spin = st.spin;
    feel.brake = st.brake;
    feel.reverse = st.reverse;
    feel.speed = vF;
    if (g_logFeel > 0 && car.driven && frame % 3 == 0) {
        Log("vehicle feel: player car v=%.2f lat=%.2f yawr=%.2f aF=%.1f aL=%.1f jolt=%.0f roll=%.1f pitch=%.1f heave=%.3f steer=%.2f brake=%.2f rev=%.2f dmg=%d ground=%d%d%d%d",
            vF, vL, st.yawRate, st.aF, st.aL, jolt, st.roll.x * 180.0f / kPi, st.pitch.x * 180.0f / kPi, st.heave.x, st.steer, st.brake, st.reverse, car.damage,
            st.ground[0], st.ground[1], st.ground[2], st.ground[3]);
    }
    (void)up;
    g_updateMs += NowMs() - t0;
    return feel;
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
        const float alpha = p.a * Smooth(t / 0.12f) * (1.0f - Smooth((t - 0.35f) / 0.65f));
        const float grey = p.r + (1.0f - p.r) * 0.3f * t;
        Quad(c, a, b, Colour(grey, grey, grey * 1.02f, alpha));
    }
    Flush(device, g_puffTex);
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
        const float cs = std::cos(p.rot) * p.size0, sn = std::sin(p.rot) * p.size0;
        const gta2::Vec3 a = right * cs + up * sn, b = (up * cs - right * sn) * squash;
        const float fade = p.life - p.age < 1.0f ? (p.life - p.age) : 1.0f;
        Quad(c, a, b, Colour(p.r, p.g, p.b, fade));
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

}  // namespace gta2dx9
