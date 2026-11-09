// Explosions in the street views (QB-19). See explosion_fx.h.
#include "explosion_fx.h"

#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <vector>

#include "log.h"

namespace gta2dx9 {
namespace {

ExplosionSettings g_set;

enum Kind : uint8_t { kFire, kSmoke, kDust, kSpark, kBit };

struct Particle {
    float x, y, z, vx, vy, vz;
    float age, life, size0, size1, roll, spin, drag, lift;
    float r, g, b, a;      // colour at birth; a: opacity (blended) or brightness (additive)
    float groundY;
    float glow;            // smoke only: how much fire light it carries at birth
    Kind kind;
    uint8_t cell;          // which of the four billows in the atlas
    bool leftSmoke;        // fire only: has dropped its smoke billow
};

struct Blast {
    float x, y, z, k;      // y: the ground; k: the blast's scale
    double born, lastSeen;
    float smokeDue;        // smoke column: puffs owed
};

std::vector<Particle> g_parts;
std::vector<Blast> g_blasts;
constexpr size_t kMaxParticles = 1600;
constexpr size_t kMaxBlasts = 12;

IDirect3DDevice9* g_texDevice = nullptr;
IDirect3DTexture9* g_billowTex = nullptr;   // fire: grey density, additive
IDirect3DTexture9* g_smokeTex = nullptr;    // smoke: top-lit shade, alpha density
IDirect3DTexture9* g_glowTex = nullptr;     // round soft glow
IDirect3DTexture9* g_ringTex = nullptr;     // shock ring
double g_lastDraw = -10.0;
double g_lastStep = 0.0;
uint32_t g_seed = 0x9E3779B9u;

double Now() {
    static LARGE_INTEGER freq = {};
    if (!freq.QuadPart) QueryPerformanceFrequency(&freq);
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return static_cast<double>(t.QuadPart) / static_cast<double>(freq.QuadPart);
}

float Rand() {
    g_seed ^= g_seed << 13; g_seed ^= g_seed >> 17; g_seed ^= g_seed << 5;
    return static_cast<float>(g_seed & 0xFFFFFF) / 16777216.0f;
}
float Rand(float lo, float hi) { return lo + (hi - lo) * Rand(); }

float Hash(int x, int y, int salt) {
    uint32_t h = static_cast<uint32_t>(x) * 374761393u + static_cast<uint32_t>(y) * 668265263u +
                 static_cast<uint32_t>(salt) * 2246822519u;
    h = (h ^ (h >> 13)) * 1274126177u;
    return static_cast<float>((h ^ (h >> 16)) & 0xFFFF) / 65535.0f;
}
float Noise(float x, float y, int salt) {
    const int ix = static_cast<int>(std::floor(x)), iy = static_cast<int>(std::floor(y));
    float fx = x - ix, fy = y - iy;
    fx = fx * fx * (3.0f - 2.0f * fx);
    fy = fy * fy * (3.0f - 2.0f * fy);
    const float a = Hash(ix, iy, salt), b = Hash(ix + 1, iy, salt);
    const float c = Hash(ix, iy + 1, salt), d = Hash(ix + 1, iy + 1, salt);
    return (a + (b - a) * fx) + ((c + (d - c) * fx) - (a + (b - a) * fx)) * fy;
}
float Fbm(float x, float y, int salt) {
    return 0.5f * Noise(x, y, salt) + 0.3f * Noise(x * 2.03f, y * 2.03f, salt + 1) +
           0.2f * Noise(x * 4.1f, y * 4.1f, salt + 2);
}
float Clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }

void ReleaseTextures() {
    for (IDirect3DTexture9** t : {&g_billowTex, &g_smokeTex, &g_glowTex, &g_ringTex}) {
        if (*t) { (*t)->Release(); *t = nullptr; }
    }
}

// fill(u, v, cell, &argb) for every texel; u, v in -1..1 across one cell.
template <typename Fill>
IDirect3DTexture9* MakeTexture(IDirect3DDevice9* device, int size, int cells, Fill fill) {
    IDirect3DTexture9* t = nullptr;
    if (FAILED(device->CreateTexture(size, size, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &t, nullptr)) || !t) return nullptr;
    D3DLOCKED_RECT lr;
    if (FAILED(t->LockRect(0, &lr, nullptr, 0))) { t->Release(); return nullptr; }
    const int cellSize = size / cells;
    for (int y = 0; y < size; ++y) {
        uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
        for (int x = 0; x < size; ++x) {
            const int cell = (y / cellSize) * cells + (x / cellSize);
            const float u = ((x % cellSize) + 0.5f) / cellSize * 2.0f - 1.0f;
            const float v = ((y % cellSize) + 0.5f) / cellSize * 2.0f - 1.0f;
            float rgb = 0.0f, a = 0.0f;
            fill(u, v, cell, &rgb, &a);
            const uint32_t c = static_cast<uint32_t>(Clamp01(rgb) * 255.0f + 0.5f);
            const uint32_t al = static_cast<uint32_t>(Clamp01(a) * 255.0f + 0.5f);
            row[x] = (al << 24) | (c << 16) | (c << 8) | c;
        }
    }
    t->UnlockRect(0);
    return t;
}

// A billow: a cauliflower blob, its edge pushed about by noise, denser in the middle.
float BillowDensity(float u, float v, int cell) {
    const float r = std::sqrt(u * u + v * v);
    const float ang = std::atan2(v, u);
    const float lobes = 0.06f * std::sin(ang * (2.0f + cell) + cell * 1.7f);
    const float edge = 0.86f + lobes + 0.12f * (Fbm(u * 2.0f + cell * 7.0f, v * 2.0f + cell * 3.0f, 11 + cell) - 0.5f) * 2.0f;
    float d = Clamp01(1.0f - r / (std::max)(0.2f, edge));
    // Soft all the way out: a hard rim is what makes a billboard read as a cut-out.
    d = d * d * (1.6f - 0.6f * d);
    const float grain = 0.65f + 0.35f * Fbm(u * 5.0f + cell * 13.0f, v * 5.0f + cell * 5.0f, 31 + cell);
    return d * grain;
}

bool EnsureTextures(IDirect3DDevice9* device) {
    if (g_texDevice != device) { ReleaseTextures(); g_texDevice = device; }
    if (!g_billowTex) {
        g_billowTex = MakeTexture(device, 256, 2, [](float u, float v, int cell, float* rgb, float* a) {
            const float d = BillowDensity(u, v, cell);
            // A hotter core: brightness climbs faster than coverage.
            *rgb = std::pow(d, 0.8f);
            *a = d;
        });
    }
    if (!g_smokeTex) {
        g_smokeTex = MakeTexture(device, 256, 2, [](float u, float v, int cell, float* rgb, float* a) {
            const float d = BillowDensity(u, v, cell);
            // Lit from above: the top of each billow paler, its underside in its own shadow,
            // with the noise breaking it into lumps - what makes a flat quad read as a volume.
            const float lump = Fbm(u * 3.0f + 40.0f + cell, v * 3.0f + 9.0f, 51 + cell);
            *rgb = 0.42f + 0.58f * Clamp01(0.55f - 0.55f * v + 0.5f * (lump - 0.5f));
            *a = Clamp01(d * 1.25f);
        });
    }
    if (!g_glowTex) {
        g_glowTex = MakeTexture(device, 64, 1, [](float u, float v, int, float* rgb, float* a) {
            const float r2 = u * u + v * v;
            const float g = r2 >= 1.0f ? 0.0f : std::exp(-r2 * 4.5f) * (1.0f - r2);
            *rgb = g; *a = g;
        });
    }
    if (!g_ringTex) {
        g_ringTex = MakeTexture(device, 128, 1, [](float u, float v, int, float* rgb, float* a) {
            const float r = std::sqrt(u * u + v * v);
            const float ring = std::exp(-((r - 0.86f) / 0.07f) * ((r - 0.86f) / 0.07f));
            const float inner = r < 0.86f ? 0.18f * (r / 0.86f) * (r / 0.86f) : 0.0f;
            const float ragged = 0.7f + 0.3f * Noise(std::atan2(v, u) * 6.0f + 20.0f, 0.0f, 71);
            const float g = r >= 1.0f ? 0.0f : (ring + inner) * ragged;
            *rgb = g; *a = g;
        });
    }
    return g_billowTex && g_smokeTex && g_glowTex && g_ringTex;
}

void Push(const Particle& p) {
    if (g_parts.size() >= kMaxParticles) {
        // Full: the oldest smoke goes first, it is the least missed.
        size_t victim = 0;
        float oldest = -1.0f;
        for (size_t i = 0; i < g_parts.size(); ++i) {
            if (g_parts[i].kind == kSmoke && g_parts[i].age / g_parts[i].life > oldest) {
                oldest = g_parts[i].age / g_parts[i].life;
                victim = i;
            }
        }
        g_parts[victim] = p;
        return;
    }
    g_parts.push_back(p);
}

Particle Base(Kind kind, float x, float y, float z, float groundY) {
    Particle p = {};
    p.kind = kind;
    p.x = x; p.y = y; p.z = z;
    p.groundY = groundY;
    p.cell = static_cast<uint8_t>(Rand() * 3.999f);
    p.roll = Rand(0.0f, 6.2831853f);
    p.r = p.g = p.b = p.a = 1.0f;
    return p;
}

void SpawnSmoke(float x, float y, float z, float groundY, float k, float size, float glow, bool column) {
    Particle p = Base(kSmoke, x, y, z, groundY);
    p.vx = Rand(-0.12f, 0.12f) * k;
    p.vz = Rand(-0.12f, 0.12f) * k;
    p.vy = column ? Rand(0.55f, 0.85f) * k : Rand(0.25f, 0.5f) * k;
    p.drag = 0.25f;
    p.lift = column ? 0.05f : 0.35f * k;
    p.size0 = size * 1.3f;
    p.size1 = size * (column ? 3.4f : 3.0f);
    p.life = column ? Rand(4.0f, 6.5f) : Rand(3.0f, 4.5f);
    p.roll = Rand(-0.35f, 0.35f);      // the shading is lit from above: little roll
    p.spin = Rand(-0.15f, 0.15f);
    const float grey = Rand(0.16f, 0.26f);
    p.r = grey; p.g = grey * 0.96f; p.b = grey * 0.92f;
    p.a = column ? 0.55f : 0.62f;
    p.glow = glow;
    Push(p);
}

void SpawnBlast(Blast& b) {
    const float k = b.k;
    const float cy = b.y + 0.32f * k;
    // The fireball.
    const int fire = 44;
    for (int i = 0; i < fire; ++i) {
        // Over the upper hemisphere, flattened a little: a car blast spreads more than it climbs.
        const float th = Rand(0.0f, 6.2831853f);
        const float up = std::pow(Rand(), 0.7f);
        const float hz = std::sqrt((std::max)(0.0f, 1.0f - up * up));
        const float dx = std::cos(th) * hz, dz = std::sin(th) * hz, dy = up * 0.85f + 0.1f;
        Particle p = Base(kFire, b.x + dx * 0.15f * k, cy + dy * 0.1f * k, b.z + dz * 0.15f * k, b.y);
        const float speed = Rand(1.4f, 3.4f) * k;
        p.vx = dx * speed; p.vy = dy * speed; p.vz = dz * speed;
        p.drag = Rand(3.0f, 4.5f);
        p.lift = Rand(0.5f, 1.1f) * k;
        p.size0 = Rand(0.35f, 0.6f) * k;
        p.size1 = Rand(1.0f, 1.5f) * k;
        p.life = Rand(0.8f, 1.6f);
        p.spin = Rand(-1.2f, 1.2f);
        p.a = Rand(0.30f, 0.50f);
        Push(p);
    }
    // A core that stays put and burns longest: the ball keeps a heart while it rolls up.
    for (int i = 0; i < 8; ++i) {
        Particle p = Base(kFire, b.x + Rand(-0.2f, 0.2f) * k, cy + Rand(0.0f, 0.2f) * k, b.z + Rand(-0.2f, 0.2f) * k, b.y);
        p.vy = Rand(0.3f, 0.7f) * k;
        p.drag = 1.5f;
        p.lift = 0.6f * k;
        p.size0 = 0.7f * k; p.size1 = 1.3f * k;
        p.life = Rand(1.4f, 2.0f);
        p.spin = Rand(-0.6f, 0.6f);
        p.a = 0.38f;
        Push(p);
    }
    // Dust kicked out along the ground by the shock.
    for (int i = 0; i < 28; ++i) {
        const float th = (i + Rand()) / 28.0f * 6.2831853f;
        Particle p = Base(kDust, b.x + std::cos(th) * 0.3f * k, b.y + 0.18f * k, b.z + std::sin(th) * 0.3f * k, b.y);
        const float speed = Rand(2.4f, 4.0f) * k;
        p.vx = std::cos(th) * speed; p.vz = std::sin(th) * speed; p.vy = Rand(0.05f, 0.3f) * k;
        p.drag = 2.6f;
        p.lift = 0.05f;
        p.size0 = 0.3f * k; p.size1 = Rand(1.0f, 1.5f) * k;
        p.life = Rand(1.4f, 2.4f);
        p.roll = Rand(-0.3f, 0.3f);
        p.spin = Rand(-0.3f, 0.3f);
        p.r = 0.50f; p.g = 0.45f; p.b = 0.40f;
        p.a = 0.42f;
        Push(p);
    }
    // Sparks and burning bits on ballistic arcs.
    for (int i = 0; i < 56; ++i) {
        const bool bit = i < 12;
        const float th = Rand(0.0f, 6.2831853f);
        const float up = Rand(0.25f, 1.0f);
        const float hz = std::sqrt(1.0f - up * up * 0.8f);
        Particle p = Base(bit ? kBit : kSpark, b.x, cy, b.z, b.y);
        const float speed = (bit ? Rand(2.0f, 3.6f) : Rand(3.0f, 6.5f)) * k;
        p.vx = std::cos(th) * hz * speed; p.vz = std::sin(th) * hz * speed; p.vy = up * speed;
        p.drag = bit ? 0.4f : 0.9f;
        p.lift = -3.0f;   // gravity, tiles/s^2
        p.size0 = bit ? 0.07f : 0.022f;
        p.size1 = bit ? 0.05f : 0.016f;
        p.life = bit ? Rand(1.6f, 2.8f) : Rand(0.5f, 1.3f);
        p.r = 1.0f; p.g = bit ? 0.55f : 0.78f; p.b = bit ? 0.18f : 0.40f;
        Push(p);
    }
}

// The flash and the fire's glow at a blast's age, 0.. (2.5 at the very flash).
float FlashLevel(float age) {
    return 2.2f * std::exp(-age / 0.16f) + 0.8f * Clamp01(1.0f - age / 1.6f);
}

void Step(float dt) {
    for (size_t i = 0; i < g_parts.size();) {
        Particle& p = g_parts[i];
        p.age += dt;
        if (p.age >= p.life) { p = g_parts.back(); g_parts.pop_back(); continue; }
        const float damp = std::exp(-p.drag * dt);
        p.vx *= damp; p.vz *= damp;
        p.vy = p.vy * damp + p.lift * dt;
        p.x += p.vx * dt; p.y += p.vy * dt; p.z += p.vz * dt;
        if (p.kind == kSpark || p.kind == kBit) {
            if (p.y < p.groundY + 0.01f && p.vy < 0.0f) {
                p.y = p.groundY + 0.01f;
                p.vy = -p.vy * 0.3f;
                p.vx *= 0.5f; p.vz *= 0.5f;
            }
        } else if (p.kind == kFire && !p.leftSmoke && p.age > p.life * 0.4f) {
            // Burning out: it leaves a billow of smoke where it was, lit by the fire still in it.
            p.leftSmoke = true;
            if (Rand() < 0.8f) {
                const float t = p.age / p.life;
                SpawnSmoke(p.x, p.y, p.z, p.groundY, p.size1 / 1.25f, (p.size0 + (p.size1 - p.size0) * t) * 0.9f, 1.0f, false);
            }
        }
        ++i;
    }
}

float g_eye[3] = {0, 0, 0};
bool g_eyeSet = false;

struct PV { float x, y, z; DWORD c; float u, v; };

DWORD Colour(float r, float g, float b, float a) {
    auto q = [](float v) { return static_cast<DWORD>(Clamp01(v) * 255.0f + 0.5f); };
    return (q(a) << 24) | (q(r) << 16) | (q(g) << 8) | q(b);
}

struct Batch {
    std::vector<PV> v;
    std::vector<uint16_t> ix;
    // A quad centred at c with half-axes a and b (b: towards the top of the texture).
    void Quad(const float* c, const float* a, const float* b, DWORD colour, int cell, int cells) {
        if (v.size() > 65000) return;
        const float cs = 1.0f / cells;
        const float u0 = (cell % cells) * cs, v0 = (cell / cells) * cs;
        const uint16_t base = static_cast<uint16_t>(v.size());
        v.push_back({c[0] - a[0] - b[0], c[1] - a[1] - b[1], c[2] - a[2] - b[2], colour, u0, v0 + cs});
        v.push_back({c[0] - a[0] + b[0], c[1] - a[1] + b[1], c[2] - a[2] + b[2], colour, u0, v0});
        v.push_back({c[0] + a[0] + b[0], c[1] + a[1] + b[1], c[2] + a[2] + b[2], colour, u0 + cs, v0});
        v.push_back({c[0] + a[0] - b[0], c[1] + a[1] - b[1], c[2] + a[2] - b[2], colour, u0 + cs, v0 + cs});
        static const uint16_t q[6] = {0, 1, 2, 0, 2, 3};
        for (uint16_t i : q) ix.push_back(static_cast<uint16_t>(base + i));
    }
    void Draw(IDirect3DDevice9* device, IDirect3DTexture9* tex, bool additive) {
        if (v.empty()) return;
        device->SetTexture(0, tex);
        device->SetRenderState(D3DRS_SRCBLEND, additive ? D3DBLEND_ONE : D3DBLEND_SRCALPHA);
        device->SetRenderState(D3DRS_DESTBLEND, additive ? D3DBLEND_ONE : D3DBLEND_INVSRCALPHA);
        device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(v.size()), static_cast<UINT>(ix.size() / 3),
                                       ix.data(), D3DFMT_INDEX16, v.data(), sizeof(PV));
    }
};

}  // namespace

ExplosionSettings& ExplosionFx() { return g_set; }
void ExplosionFxSetEye(float x, float y, float z) { g_eye[0] = x; g_eye[1] = y; g_eye[2] = z; g_eyeSet = true; }

void ExplosionFxLoad(const char* iniPath) {
    if (iniPath && *iniPath) {
        auto num = [&](const char* key, int fallback) {
            return static_cast<int>(GetPrivateProfileIntA("explosions", key, fallback, iniPath));
        };
        g_set.enabled = num("enabled", 1) != 0;
        g_set.size = (std::max)(10, (std::min)(400, num("size_percent", 100))) / 100.0f;
        g_set.flash = (std::max)(0, (std::min)(400, num("flash_percent", 100))) / 100.0f;
        g_set.smokeSeconds = static_cast<float>((std::max)(0, (std::min)(120, num("smoke_seconds", 10))));
        g_set.spriteBright = (std::max)(0, (std::min)(100, num("sprite_percent", 35))) / 100.0f;
        g_set.carLight = num("car_light", 1) != 0;
    }
    char buf[8] = {};
    if (GetEnvironmentVariableA("GTA2DX9_EXPLOSION_FX", buf, sizeof buf) && buf[0] == '0') g_set.enabled = false;
    Log("explosions: %s, size %.2f, flash %.2f, smoke %.0f s, game sprite %.2f, car light %d",
        g_set.enabled ? "on" : "off", g_set.size, g_set.flash, g_set.smokeSeconds, g_set.spriteBright, g_set.carLight ? 1 : 0);
}

void ExplosionFxNote(float x, float groundY, float z, float size) {
    if (!g_set.enabled) return;
    const double now = Now();
    for (Blast& b : g_blasts) {
        const float dx = b.x - x, dz = b.z - z;
        // The sprite comes and goes while it plays: one blast for 1.6 s from its first sight.
        if ((now - b.lastSeen < 0.5 || now - b.born < 1.6) && dx * dx + dz * dz < 1.5f * 1.5f) {
            b.lastSeen = now;
            return;
        }
    }
    if (g_blasts.size() >= kMaxBlasts) g_blasts.erase(g_blasts.begin());
    Blast b = {};
    b.x = x; b.y = groundY; b.z = z;
    // The game's blast sprite is about 1.5 tiles at its first frames; a bigger one is a bigger bang.
    b.k = g_set.size * (std::max)(0.85f, (std::min)(1.4f, 0.7f + 0.2f * size));
    b.born = b.lastSeen = now;
    g_blasts.push_back(b);
    SpawnBlast(g_blasts.back());
    Log("explosions: blast at %.2f,%.2f,%.2f (sprite %.2f tiles, scale %.2f), %d particles",
        x, groundY, z, size, b.k, static_cast<int>(g_parts.size()));
}

void ExplosionFxDraw(IDirect3DDevice9* device, const gta2::Vec3& f, DWORD fvf) {
    const double now = Now();
    float dt = static_cast<float>(now - g_lastStep);
    g_lastStep = now;
    if (dt < 0.0f || dt > 0.1f) dt = 0.1f;
    if (!g_set.enabled || (g_parts.empty() && g_blasts.empty())) return;
    g_lastDraw = now;

    // The smoke column off each blast, and blasts that are over.
    for (size_t i = 0; i < g_blasts.size();) {
        Blast& b = g_blasts[i];
        const float age = static_cast<float>(now - b.born);
        if (age > g_set.smokeSeconds + 1.0f && age > 2.0f) { g_blasts.erase(g_blasts.begin() + static_cast<std::ptrdiff_t>(i)); continue; }
        if (age > 0.6f && age < g_set.smokeSeconds) {
            const float rate = 3.0f + 7.0f * std::sqrt(1.0f - age / g_set.smokeSeconds);
            b.smokeDue += rate * dt;
            while (b.smokeDue >= 1.0f) {
                b.smokeDue -= 1.0f;
                const float glow = Clamp01(1.0f - (age - 0.6f) / 2.0f);
                SpawnSmoke(b.x + Rand(-0.25f, 0.25f) * b.k, b.y + Rand(0.3f, 0.6f) * b.k, b.z + Rand(-0.25f, 0.25f) * b.k,
                           b.y, b.k, Rand(0.45f, 0.7f) * b.k, glow, true);
            }
        }
        ++i;
    }
    Step(dt);
    if (!EnsureTextures(device)) return;

    // Camera-facing axes: right is level, up follows the view.
    float rx = f.z, rz = -f.x;
    const float rl = (std::max)(1e-4f, std::sqrt(rx * rx + rz * rz));
    rx /= rl; rz /= rl;
    const float ux = -rz * f.y, uy = rz * f.x - rx * f.z, uz = rx * f.y;

    Batch ground, ring, smoke, fire, glow;
    // Ground light and shock ring.
    for (const Blast& b : g_blasts) {
        const float age = static_cast<float>(now - b.born);
        const float light = g_set.flash * 0.30f * FlashLevel(age);
        if (light > 0.01f) {
            const float c[3] = {b.x, b.y + 0.035f, b.z};
            const float s = 3.6f * b.k;
            const float a[3] = {s, 0.0f, 0.0f}, bb[3] = {0.0f, 0.0f, s};
            ground.Quad(c, a, bb, Colour(light, light * 0.55f, light * 0.22f, 1.0f), 0, 1);
        }
        if (age < 0.55f) {
            const float u = age / 0.55f;
            const float radius = (0.4f + 4.6f * (1.0f - (1.0f - u) * (1.0f - u))) * b.k;
            const float level = 0.55f * (1.0f - u) * (1.0f - u) * (std::min)(1.0f, g_set.flash);
            const float c[3] = {b.x, b.y + 0.04f, b.z};
            const float a[3] = {radius, 0.0f, 0.0f}, bb[3] = {0.0f, 0.0f, radius};
            ring.Quad(c, a, bb, Colour(level, level * 0.85f, level * 0.65f, 1.0f), 0, 1);
        }
        // The flash: a glow over the blast.
        const float flash = g_set.flash * (0.8f * std::exp(-age / 0.10f) + 0.18f * Clamp01(1.0f - age / 1.4f));
        float flashK = 1.0f;
        if (g_eyeSet) {
            const float s0 = 2.2f * b.k;
            const float dx = b.x - g_eye[0], dy = b.y + 0.55f * b.k - g_eye[1], dz = b.z - g_eye[2];
            const float t = Clamp01((std::sqrt(dx * dx + dy * dy + dz * dz) / s0 - 0.4f) / 1.2f);
            flashK = 0.25f + 0.75f * t * t * (3.0f - 2.0f * t);
        }
        if (flash * flashK > 0.01f) {
            const float c[3] = {b.x, b.y + 0.55f * b.k, b.z};
            const float s = 2.2f * b.k * (0.7f + 0.3f * Clamp01(age / 0.15f));
            const float a[3] = {rx * s, 0.0f, rz * s}, bb[3] = {ux * s, uy * s, uz * s};
            glow.Quad(c, a, bb, Colour(flash * flashK, flash * flashK * 0.78f, flash * flashK * 0.5f, 1.0f), 0, 1);
        }
    }

    // Smoke and dust, far to near.
    std::vector<const Particle*> soft;
    soft.reserve(g_parts.size());
    for (const Particle& p : g_parts) if (p.kind == kSmoke || p.kind == kDust) soft.push_back(&p);
    std::sort(soft.begin(), soft.end(), [&](const Particle* a, const Particle* b) {
        return a->x * f.x + a->y * f.y + a->z * f.z > b->x * f.x + b->y * f.y + b->z * f.z;
    });
    // A particle the eye is in or beside (first person at the wheel of a burning car) would fill the
    // frame with one flat quad: it fades out over the last stretch of its approach. 1 at 1.8 sizes
    // away or more, 0 inside half a size.
    auto nearFade = [&](const Particle& p, float size) {
        if (!g_eyeSet) return 1.0f;
        const float dx = p.x - g_eye[0], dy = p.y - g_eye[1], dz = p.z - g_eye[2];
        const float d = std::sqrt(dx * dx + dy * dy + dz * dz) / (std::max)(0.05f, size);
        const float t = Clamp01((d - 0.5f) / 1.3f);
        return t * t * (3.0f - 2.0f * t);
    };
    auto billboard = [&](Batch& batch, const Particle& p, float size, DWORD colour, bool keepUp) {
        const float roll = p.roll + p.spin * p.age;
        const float cr = std::cos(roll) * size, sr = std::sin(roll) * size;
        const float a[3] = {rx * cr + ux * sr, uy * sr, rz * cr + uz * sr};
        const float b[3] = {-rx * sr + ux * cr, uy * cr, -rz * sr + uz * cr};
        float c[3] = {p.x, p.y, p.z};
        // Kept out of the road: a billow cut by the ground shows a hard line.
        if (keepUp) c[1] = (std::max)(c[1], p.groundY + size * 0.55f);
        batch.Quad(c, a, b, colour, p.cell, 2);
    };
    for (const Particle* pp : soft) {
        const Particle& p = *pp;
        const float t = p.age / p.life;
        const float grow = 1.0f - (1.0f - t) * (1.0f - t);
        const float size = 0.5f * (p.size0 + (p.size1 - p.size0) * grow);
        const float in = Clamp01(p.age / 0.45f);
        float alpha = p.a * in * std::pow(1.0f - t, 1.4f) * nearFade(p, size);
        if (alpha < 0.01f) continue;
        // Fire light on the underside of fresh smoke, fading as it rises and cools.
        const float warm = p.glow * Clamp01(1.0f - p.age / 1.2f);
        const float r = p.r + warm * 0.55f, g = p.g + warm * 0.22f, b = p.b + warm * 0.06f;
        billboard(smoke, p, size, Colour(r, g, b, alpha), true);
    }
    for (const Particle& p : g_parts) {
        const float t = p.age / p.life;
        if (p.kind == kFire) {
            // White-hot, then yellow, orange, red, out.
            float r, g, b;
            if (t < 0.05f) { const float s = t / 0.05f; r = 1.0f; g = 0.95f - 0.2f * s; b = 0.75f - 0.45f * s; }
            else if (t < 0.35f) { const float s = (t - 0.05f) / 0.30f; r = 1.0f; g = 0.75f - 0.33f * s; b = 0.30f - 0.21f * s; }
            else { const float s = (t - 0.35f) / 0.65f; r = 1.0f - 0.45f * s; g = 0.42f - 0.3f * s; b = 0.09f - 0.07f * s; }
            float level = p.a * Clamp01(p.age / 0.03f) * std::pow(1.0f - t, 1.3f) * (0.88f + 0.12f * std::sin(p.age * 23.0f + p.roll * 4.0f));
            const float grow = 1.0f - (1.0f - t) * (1.0f - t) * (1.0f - t);
            const float size = 0.5f * (p.size0 + (p.size1 - p.size0) * grow);
            level *= nearFade(p, size);
            if (level < 0.01f) continue;
            billboard(fire, p, size, Colour(r * level, g * level, b * level, 1.0f), true);
        } else if (p.kind == kSpark || p.kind == kBit) {
            const float level = p.kind == kBit ? (1.0f - t * t) : (1.0f - t);
            if (level < 0.01f) continue;
            const float size = p.size0 + (p.size1 - p.size0) * t;
            // A streak along its motion.
            float a[3] = {rx * size, 0.0f, rz * size}, b[3] = {ux * size, uy * size, uz * size};
            const float vl = std::sqrt(p.vx * p.vx + p.vy * p.vy + p.vz * p.vz);
            if (vl > 0.05f) {
                const float st = (std::min)(p.kind == kBit ? 3.0f : 9.0f, 1.0f + vl * (p.kind == kBit ? 0.4f : 1.6f));
                b[0] = p.vx / vl * size * st; b[1] = p.vy / vl * size * st; b[2] = p.vz / vl * size * st;
                a[0] = b[1] * f.z - b[2] * f.y; a[1] = b[2] * f.x - b[0] * f.z; a[2] = b[0] * f.y - b[1] * f.x;
                const float al = (std::max)(1e-5f, std::sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]));
                a[0] = a[0] / al * size; a[1] = a[1] / al * size; a[2] = a[2] / al * size;
            }
            const float c[3] = {p.x, p.y, p.z};
            glow.Quad(c, a, b, Colour(p.r * level, p.g * level, p.b * level, 1.0f), 0, 1);
        }
    }

    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_DIFFUSE | D3DFVF_TEX1);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    // Fog would add its own colour to every additive quad and turn a far blast grey.
    DWORD fogWas = FALSE;
    device->GetRenderState(D3DRS_FOGENABLE, &fogWas);
    device->SetRenderState(D3DRS_FOGENABLE, FALSE);
    ground.Draw(device, g_glowTex, true);
    ring.Draw(device, g_ringTex, true);
    smoke.Draw(device, g_smokeTex, false);
    fire.Draw(device, g_billowTex, true);
    glow.Draw(device, g_glowTex, true);

    device->SetRenderState(D3DRS_FOGENABLE, fogWas);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetTexture(0, nullptr);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
    device->SetFVF(fvf);
}

bool ExplosionFxLight(float pos[3], float rgb[3], float* range) {
    if (!g_set.enabled || !g_set.carLight || g_blasts.empty()) return false;
    const double now = Now();
    if (now - g_lastDraw > 0.25) return false;   // not in a street view
    float best = 0.0f;
    for (const Blast& b : g_blasts) {
        const float level = g_set.flash * FlashLevel(static_cast<float>(now - b.born));
        if (level > best) {
            best = level;
            pos[0] = b.x; pos[1] = b.y + 0.6f * b.k; pos[2] = b.z;
            *range = 5.0f * b.k;
        }
    }
    if (best < 0.03f) return false;
    rgb[0] = best; rgb[1] = best * 0.58f; rgb[2] = best * 0.24f;
    return true;
}

int ExplosionFxBlasts() { return static_cast<int>(g_blasts.size()); }
int ExplosionFxParticles() { return static_cast<int>(g_parts.size()); }

}  // namespace gta2dx9
