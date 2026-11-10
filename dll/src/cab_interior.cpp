// QB-31: the cab seen from the driver's seat, per vehicle class (see cab_interior.h).
#include "cab_interior.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <map>
#include <vector>

#include "identity.h"
#include "log.h"
#include "model_store.h"

namespace gta2dx9 {
namespace {

using gta2::Vec3;

constexpr float kPi = 3.14159265f;

// The parts by surface: each is one draw with its own material.
enum Mat { kDash, kDashDark, kTrim, kHeader, kWheel, kGaugeFace, kGaugeRim, kNeedle, kGlass, kPanel, kMeter, kGlassLow, kLower, kMatCount };

struct V { float x, y, z, nx, ny, nz, u, v; };

// FIX-FIGURE (pm2-fp-cockpit-flat-untextured-placeholder-boxes): a texture per surface,
// made here (no art files): vinyl grain on the dash, fine-grained plastic, brushed
// trim, headliner cloth, a stitched leather wheel, gauge faces with a tick ring.
// Planar UVs from the car-frame position (a tile every kUvTile blocks), so the
// grain stays put on the dash; discs and the wheel's torus map their own.
constexpr float kUvTile = 0.025f;
IDirect3DDevice9* g_texDevice = nullptr;
IDirect3DTexture9* g_tex[16] = {};
// FIX-FP-2 (pm19 first-person half): the wheel as last built, car frame, for the hands on it.
struct WheelPose { bool valid; Vec3 c, u, v, axis; float R, tube, turn; };
WheelPose g_wheel{};
// FIX-COCKPIT-BODY: the driver's pose as the last seat-view cab built it (CabLastDriverPose), and when his
// body was last drawn from the eye (CabNoteDriverBody).
CabDriverPose g_driver{};
ULONGLONG g_driverStamp = 0, g_bodyStamp = 0;

uint32_t Hash(uint32_t x, uint32_t y, uint32_t seed) {
    uint32_t h = x * 374761393u + y * 668265263u + seed * 2246822519u;
    h = (h ^ (h >> 13)) * 1274126177u;
    return h ^ (h >> 16);
}
float Noise01(int x, int y, uint32_t seed) { return (Hash(static_cast<uint32_t>(x) & 63u, static_cast<uint32_t>(y) & 63u, seed) & 0xFFFF) / 65535.0f; }
// A smoothed value noise at `cell` texels, tiling over 64.
float Smooth(int x, int y, int cell, uint32_t seed) {
    const int cx = x / cell, cy = y / cell, n = 64 / cell;
    const float fx = (x % cell) / static_cast<float>(cell), fy = (y % cell) / static_cast<float>(cell);
    auto at = [&](int i, int j) { return (Hash(static_cast<uint32_t>((i % n + n) % n), static_cast<uint32_t>((j % n + n) % n), seed) & 0xFFFF) / 65535.0f; };
    const float sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
    const float a = at(cx, cy) + (at(cx + 1, cy) - at(cx, cy)) * sx;
    const float b = at(cx, cy + 1) + (at(cx + 1, cy + 1) - at(cx, cy + 1)) * sx;
    return a + (b - a) * sy;
}
// Brightness 0..1 of texel (x, y) of surface `kind` (multiplies the material colour).
float Texel(int kind, int x, int y) {
    switch (kind) {
        case 0: {   // vinyl: pebbled grain, a little mottle
            const float g = 0.5f * Smooth(x, y, 2, 11) + 0.3f * Smooth(x, y, 4, 12) + 0.2f * Smooth(x, y, 16, 13);
            return 0.74f + 0.34f * g;
        }
        case 1: return 0.86f + 0.16f * Smooth(x, y, 2, 21) + 0.04f * Noise01(x, y, 22);                 // plastic
        case 2: return 0.82f + 0.12f * Smooth(x, y / 16, 1, 31) + 0.10f * Noise01(x, y, 32);             // brushed (streaks along u)
        case 3: return ((x + y) % 4 < 2 ? 0.90f : 0.98f) + 0.06f * Smooth(x, y, 8, 41);                   // headliner weave
        case 4: {   // leather: grain, a stitched seam every 16 texels across
            const float g = 0.82f + 0.22f * Smooth(x, y, 2, 51);
            return (y % 16 == 0 && (x % 4) < 2) ? g * 0.55f : g;
        }
        case 5: {   // gauge face: the disc's UV (0..1); a tick ring and a darker centre
            const float dx = (x + 0.5f) / 64.0f - 0.5f, dy = (y + 0.5f) / 64.0f - 0.5f;
            const float r = std::sqrt(dx * dx + dy * dy) * 2.0f;
            const float ang = std::atan2(dy, dx) * 180.0f / kPi;
            const float rel = std::fmod(ang + 360.0f + 45.0f, 360.0f);   // the dial's 270 degrees
            const bool onArc = rel < 270.0f;
            const bool major = onArc && std::fmod(rel, 27.0f) < 3.5f, minor = onArc && std::fmod(rel, 13.5f) < 1.8f;
            if (r > 0.70f && r < 0.92f && major) return 0.10f;
            if (r > 0.80f && r < 0.92f && minor) return 0.25f;
            if (r < 0.14f) return 0.20f;   // the hub cap
            return r > 0.94f ? 0.75f : 1.0f;
        }
        default: return 1.0f;
    }
}
IDirect3DTexture9* SurfaceTexture(IDirect3DDevice9* device, int kind) {
    if (device != g_texDevice) { CabInteriorReleaseDevice(); g_texDevice = device; }
    if (kind < 0 || kind >= 16) return nullptr;
    if (g_tex[kind]) return g_tex[kind];
    IDirect3DTexture9* t = nullptr;
    if (FAILED(device->CreateTexture(64, 64, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &t, nullptr)) || !t) return nullptr;
    D3DLOCKED_RECT lr;
    if (SUCCEEDED(t->LockRect(0, &lr, nullptr, 0))) {
        for (int y = 0; y < 64; ++y) {
            uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
            for (int x = 0; x < 64; ++x) {
                const float b = (std::max)(0.0f, (std::min)(1.0f, Texel(kind, x, y)));
                const uint32_t c = static_cast<uint32_t>(b * 255.0f + 0.5f);
                row[x] = 0xFF000000u | (c << 16) | (c << 8) | c;
            }
        }
        t->UnlockRect(0);
    }
    g_tex[kind] = t;
    return t;
}

// FIX-REMIX-NIGHT-2 (pt-remix-fp-cabin-flat-white-slabs-day-glow-cream-at-night): Remix reads a draw's
// albedo from its texture only: the D3D material colour (where these surfaces carry their colour) and
// vertex colour (rtx.ignoreAllVertexColorBakedLighting) never reach the path tracer, so the cab's grey
// 0.74..1.0 grain textures came out a white cab (cream under the night's warm lamps). Under Remix each
// surface draws with its grain multiplied by its colour, baked into the texture (colour quantised to
// 1/64 so a car's paint-tinted dash makes one texture, not one per frame).
bool g_remixAlbedo = false;      // set by the renderer: Remix is up and [devtools] remix_cab_albedo != 0
std::map<uint32_t, IDirect3DTexture9*> g_tintTex;
IDirect3DTexture9* SurfaceTextureTinted(IDirect3DDevice9* device, int kind, const float c[3]) {
    if (device != g_texDevice) { CabInteriorReleaseDevice(); g_texDevice = device; }
    if (kind < 0 || kind >= 16) return nullptr;
    int q[3];
    for (int k = 0; k < 3; ++k) q[k] = static_cast<int>((std::max)(0.0f, (std::min)(1.0f, c[k])) * 63.0f + 0.5f);
    const uint32_t key = static_cast<uint32_t>(kind) << 18 | static_cast<uint32_t>(q[0]) << 12 | static_cast<uint32_t>(q[1]) << 6 | static_cast<uint32_t>(q[2]);
    auto it = g_tintTex.find(key);
    if (it != g_tintTex.end()) return it->second;
    IDirect3DTexture9* t = nullptr;
    if (FAILED(device->CreateTexture(64, 64, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &t, nullptr)) || !t) return nullptr;
    D3DLOCKED_RECT lr;
    if (SUCCEEDED(t->LockRect(0, &lr, nullptr, 0))) {
        for (int y = 0; y < 64; ++y) {
            uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
            for (int x = 0; x < 64; ++x) {
                const float b = (std::max)(0.0f, (std::min)(1.0f, Texel(kind, x, y)));
                uint32_t px = 0xFF000000u;
                for (int k = 0; k < 3; ++k)
                    px |= static_cast<uint32_t>((std::min)(1.0f, b * q[k] / 63.0f) * 255.0f + 0.5f) << (16 - 8 * k);
                row[x] = px;
            }
        }
        t->UnlockRect(0);
    }
    g_tintTex[key] = t;
    if (g_tintTex.size() == 1 || g_tintTex.size() % 32 == 0) Log("cab interior: %u colour textures for Remix", static_cast<unsigned>(g_tintTex.size()));
    return t;
}

struct Builder {
    std::vector<V> tris[kMatCount];
    Vec3 eye;
    // A flat triangle, its normal turned toward the eye (everything here is seen from the seat).
    void Tri(int m, const Vec3& a, const Vec3& b, const Vec3& c) {
        Vec3 n = gta2::Normalize(gta2::Cross(b - a, c - a));
        const Vec3 centre = (a + b + c) * (1.0f / 3.0f);
        if (gta2::Dot(n, eye - centre) < 0.0f) n = n * -1.0f;
        // Planar UV on the plane the face is most nearly in.
        const float ax = std::fabs(n.x), ay = std::fabs(n.y), az = std::fabs(n.z);
        auto uv = [&](const Vec3& p, float* u, float* v) {
            if (ay >= ax && ay >= az) { *u = p.x / kUvTile; *v = p.z / kUvTile; }
            else if (ax >= az) { *u = p.z / kUvTile; *v = p.y / kUvTile; }
            else { *u = p.x / kUvTile; *v = p.y / kUvTile; }
        };
        float u[3], v[3];
        uv(a, &u[0], &v[0]); uv(b, &u[1], &v[1]); uv(c, &u[2], &v[2]);
        tris[m].push_back({a.x, a.y, a.z, n.x, n.y, n.z, u[0], v[0]});
        tris[m].push_back({b.x, b.y, b.z, n.x, n.y, n.z, u[1], v[1]});
        tris[m].push_back({c.x, c.y, c.z, n.x, n.y, n.z, u[2], v[2]});
    }
    // A triangle with its own UVs (discs: the gauge faces).
    void TriUv(int m, const Vec3& a, const Vec3& b, const Vec3& c, const float* uv) {
        Vec3 n = gta2::Normalize(gta2::Cross(b - a, c - a));
        if (gta2::Dot(n, eye - (a + b + c) * (1.0f / 3.0f)) < 0.0f) n = n * -1.0f;
        tris[m].push_back({a.x, a.y, a.z, n.x, n.y, n.z, uv[0], uv[1]});
        tris[m].push_back({b.x, b.y, b.z, n.x, n.y, n.z, uv[2], uv[3]});
        tris[m].push_back({c.x, c.y, c.z, n.x, n.y, n.z, uv[4], uv[5]});
    }
    void Quad(int m, const Vec3& a, const Vec3& b, const Vec3& c, const Vec3& d) { Tri(m, a, b, c); Tri(m, a, c, d); }
    // A disc about `c` in the plane of (u, v) (unit vectors).
    void Disc(int m, const Vec3& c, const Vec3& u, const Vec3& v, float r, int seg = 18) {
        for (int i = 0; i < seg; ++i) {
            const float a0 = 2.0f * kPi * i / seg, a1 = 2.0f * kPi * (i + 1) / seg;
            const float uv[6] = {0.5f, 0.5f, 0.5f + 0.5f * std::cos(a0), 0.5f - 0.5f * std::sin(a0), 0.5f + 0.5f * std::cos(a1), 0.5f - 0.5f * std::sin(a1)};
            TriUv(m, c, c + u * (r * std::cos(a0)) + v * (r * std::sin(a0)), c + u * (r * std::cos(a1)) + v * (r * std::sin(a1)), uv);
        }
    }
    // A torus (the wheel rim) about `c`: in-plane axes u, v, axis w; smooth normals.
    void Torus(int m, const Vec3& c, const Vec3& u, const Vec3& v, const Vec3& w, float R, float r, int segU = 36, int segV = 8) {
        auto at = [&](int i, int j, Vec3* n) {
            const float a = 2.0f * kPi * i / segU, b = 2.0f * kPi * j / segV;
            const Vec3 radial = u * std::cos(a) + v * std::sin(a);
            *n = radial * std::cos(b) + w * std::sin(b);
            return c + radial * R + *n * r;
        };
        for (int i = 0; i < segU; ++i)
            for (int j = 0; j < segV; ++j) {
                Vec3 n[4];
                const Vec3 p[4] = {at(i, j, &n[0]), at(i + 1, j, &n[1]), at(i + 1, j + 1, &n[2]), at(i, j + 1, &n[3])};
                const int order[6] = {0, 1, 2, 0, 2, 3};
                const float tu[4] = {16.0f * i / segU, 16.0f * (i + 1) / segU, 16.0f * (i + 1) / segU, 16.0f * i / segU};
                const float tv[4] = {static_cast<float>(j) / segV, static_cast<float>(j) / segV, static_cast<float>(j + 1) / segV, static_cast<float>(j + 1) / segV};
                for (int k : order) tris[m].push_back({p[k].x, p[k].y, p[k].z, n[k].x, n[k].y, n[k].z, tu[k], tv[k]});
            }
    }
    // A bar of square section from a to b (spokes, the mirror stem).
    void Bar(int m, const Vec3& a, const Vec3& b, float half) {
        const Vec3 d = gta2::Normalize(b - a);
        Vec3 s = gta2::Cross(d, Vec3{0.0f, 1.0f, 0.0f});
        if (gta2::Dot(s, s) < 1e-6f) s = gta2::Cross(d, Vec3{1.0f, 0.0f, 0.0f});
        s = gta2::Normalize(s) * half;
        const Vec3 t = gta2::Normalize(gta2::Cross(s, d)) * half;
        const Vec3 o[4] = {s + t, s - t, s * -1.0f - t, t - s};
        for (int i = 0; i < 4; ++i) {
            const Vec3& p = o[i];
            const Vec3& q = o[(i + 1) % 4];
            Quad(m, a + p, a + q, b + q, b + p);
        }
    }
};

struct Style {
    float dash[3], dashDark[3], trim[3], header[3], wheel[3], panel[3], lower[3];
    float wheelR, wheelRake, wheelTube;   // blocks, radians from upright, blocks
    float binnacleHalf;                   // half width of the cluster
    int gauges;
    float headerAngle;                    // degrees over the horizon of the header's lower edge
    float mirrorW, mirrorH;               // the rear-view mirror
    float sideMirrorH;                    // the door mirror's height (a truck's west-coast mirror is tall)
};

Style StyleFor(CabClass c, const float paint[3]) {
    Style s{};
    auto set = [](float* d, float r, float g, float b) { d[0] = r; d[1] = g; d[2] = b; };
    switch (c) {
        case CabClass::Sports:
            // Black leather and brushed aluminium, a small thick-rimmed wheel, three dials.
            set(s.dash, 0.20f, 0.17f, 0.15f);
            set(s.dashDark, 0.07f, 0.07f, 0.07f);
            set(s.trim, 0.62f, 0.62f, 0.64f);
            set(s.header, 0.16f, 0.15f, 0.15f);
            set(s.wheel, 0.10f, 0.08f, 0.07f);
            s.wheelR = 0.016f; s.wheelRake = 18.0f * kPi / 180.0f; s.wheelTube = 0.0022f;
            s.binnacleHalf = 0.024f; s.gauges = 3;
            s.headerAngle = 24.0f; s.mirrorW = 0.020f; s.mirrorH = 0.0065f; s.sideMirrorH = 0.0055f;
            break;
        case CabClass::Car:
            // A dark vinyl top with a touch of the body colour (the painted metal dash of the old cars).
            for (int k = 0; k < 3; ++k) s.dash[k] = 0.16f + 0.22f * paint[k];
            set(s.dashDark, 0.07f, 0.07f, 0.08f);
            set(s.trim, 0.13f, 0.13f, 0.14f);
            set(s.header, 0.62f, 0.58f, 0.52f);
            set(s.wheel, 0.13f, 0.12f, 0.12f);
            s.wheelR = 0.019f; s.wheelRake = 25.0f * kPi / 180.0f; s.wheelTube = 0.0017f;
            s.binnacleHalf = 0.020f; s.gauges = 2;
            s.headerAngle = 30.0f; s.mirrorW = 0.024f; s.mirrorH = 0.0075f; s.sideMirrorH = 0.006f;
            break;
        case CabClass::Van:
            set(s.dash, 0.30f, 0.30f, 0.31f);
            set(s.dashDark, 0.10f, 0.10f, 0.11f);
            set(s.trim, 0.20f, 0.20f, 0.21f);
            set(s.header, 0.55f, 0.55f, 0.53f);
            set(s.wheel, 0.15f, 0.15f, 0.16f);
            s.wheelR = 0.021f; s.wheelRake = 38.0f * kPi / 180.0f; s.wheelTube = 0.0018f;
            s.binnacleHalf = 0.022f; s.gauges = 2;
            s.headerAngle = 29.5f; s.mirrorW = 0.026f; s.mirrorH = 0.008f; s.sideMirrorH = 0.009f;
            break;
        case CabClass::Truck:
            set(s.dash, 0.26f, 0.23f, 0.20f);
            set(s.dashDark, 0.10f, 0.09f, 0.08f);
            set(s.trim, 0.34f, 0.34f, 0.36f);
            set(s.header, 0.46f, 0.40f, 0.33f);
            set(s.wheel, 0.15f, 0.14f, 0.13f);
            s.wheelR = 0.025f; s.wheelRake = 55.0f * kPi / 180.0f; s.wheelTube = 0.0020f;
            s.binnacleHalf = 0.027f; s.gauges = 3;
            s.headerAngle = 29.0f; s.mirrorW = 0.026f; s.mirrorH = 0.008f; s.sideMirrorH = 0.016f;
            break;
        case CabClass::Bus:
            set(s.dash, 0.30f, 0.34f, 0.30f);
            set(s.dashDark, 0.09f, 0.10f, 0.09f);
            set(s.trim, 0.42f, 0.42f, 0.40f);
            set(s.header, 0.70f, 0.70f, 0.66f);
            set(s.wheel, 0.15f, 0.15f, 0.15f);
            s.wheelR = 0.028f; s.wheelRake = 62.0f * kPi / 180.0f; s.wheelTube = 0.0020f;
            s.binnacleHalf = 0.029f; s.gauges = 3;
            s.headerAngle = 28.5f; s.mirrorW = 0.034f; s.mirrorH = 0.009f; s.sideMirrorH = 0.018f;
            break;
    }
    // FIX-FP-2 (pm30-bil-fp-sedan-cockpit-lower-third-flat-black-void): the car, van and truck
    // dash top is painted metal in the body's own colour (the colour the classic view shows,
    // held between a dark and a light floor so a black or white car still has a shaded dash),
    // and no shade is near-black: at 0.07 the dash's face toward the driver, which fills the
    // bottom of the view, read as a hole (under the cab's fill light, below, it still lands darkest).
    if (c == CabClass::Car || c == CabClass::Van || c == CabClass::Truck) {
        const float lum = 0.30f * paint[0] + 0.59f * paint[1] + 0.11f * paint[2];
        const float want = (std::max)(0.24f, (std::min)(0.40f, lum));
        const float k0 = lum > 1e-3f ? want / lum : 0.0f;
        for (int k = 0; k < 3; ++k) {
            const float painted = lum > 1e-3f ? (std::min)(1.0f, paint[k] * k0) : want;
            s.dash[k] = 0.70f * painted + 0.30f * s.dash[k];
        }
    }
    for (int k = 0; k < 3; ++k) {
        s.dashDark[k] = (std::max)(s.dashDark[k], 0.16f + 0.25f * (s.dash[k] - 0.16f));
        s.trim[k] = (std::max)(s.trim[k], 0.20f);
        s.wheel[k] = (std::max)(s.wheel[k], 0.12f);
    }
    // The centre stack and the glovebox lid: the dash's dark shade lifted toward the trim.
    for (int k = 0; k < 3; ++k) s.panel[k] = 0.6f * s.dashDark[k] + 0.4f * s.trim[k];
    // The lower dash and the door card: the dash's colour, darker (vinyl).
    for (int k = 0; k < 3; ++k) s.lower[k] = 0.55f * s.dash[k] + 0.45f * s.dashDark[k];
    return s;
}

}  // namespace

void CabInteriorSetRemixAlbedo(bool on) { g_remixAlbedo = on; }

void CabInteriorReleaseDevice() {
    for (IDirect3DTexture9*& t : g_tex) { if (t) t->Release(); t = nullptr; }
    for (auto& kv : g_tintTex) if (kv.second) kv.second->Release();
    g_tintTex.clear();
    g_texDevice = nullptr;
}

CabClass CabClassFor(int m, bool flatFront) {
    if (flatFront) return CabClass::Bus;
    switch (m) {
        // The sports cars and roadsters (CARI order): Aniston BD4, Shark, GT-A1, Miara,
        // Arachnid, Stinger, Meteor (both), Hachura, Michelli Roadster, Trance-Am, Z-Type,
        // Rumbler, Jagular XK, Furore GT, the special agent car.
        case 2: case 18: case 19: case 37: case 44: case 46: case 47: case 48: case 49: case 53: case 62: case 70:
        case 71: case 82: case 83: case 84:
            return CabClass::Sports;
        case 11: case 86: case 6: case 59: case 60: case 61:
            return CabClass::Bus;
        case 7: case 17: case 21: case 54: case 55: case 58: case 63: case 64: case 65: case 66: case 69:
            return CabClass::Truck;
        case 3: case 4: case 22: case 23: case 24: case 25: case 26: case 27: case 30: case 34: case 35:
        case 38: case 41: case 52: case 67: case 68: case 85:
            return CabClass::Van;
        default:
            return CabClass::Car;
    }
}

// Open-top bodies: no roof lining. The manifest keeps no body type; this is the list the car
// scorer uses (tools/score_car_model.py OPEN_TOP_MODELS): jeeps and roadsters.
// FIX-FP (pm16-ste-fp-convertible-...): 44 Arachnid is a Giulietta Spider, open (docs/vehicle-art-review.md
// card_044); with a lining it was the dark slab across the top of the view.
bool CabOpenTop(int m) {
    return m == 22 || m == 30 || m == 31 || m == 39 || m == 44 || m == 45 || m == 53;
}

const char* CabClassName(CabClass c) {
    switch (c) {
        case CabClass::Car: return "car";
        case CabClass::Sports: return "sports";
        case CabClass::Van: return "van";
        case CabClass::Truck: return "truck";
        case CabClass::Bus: return "bus";
    }
    return "?";
}

float g_headerBottom = -1.0f;      // CabHeaderScreenBottom
unsigned long long g_headerStamp = 0;

bool CabLastDriverPose(CabDriverPose* out) {
    if (!g_driverStamp || GetTickCount64() - g_driverStamp > 250) return false;
    if (out) *out = g_driver;
    return true;
}
void CabNoteDriverBody() { g_bodyStamp = GetTickCount64(); }
float g_gripPhi = 0.52f;   // FIX-COCKPIT-BODY-2: the body's grips above the rim's horizontal (radians; 5c0ee78: 0.30)
namespace { float g_wristFwd[2] = {1.0f, 1.0f}; ULONGLONG g_wristStamp[2] = {0, 0}; }
void CabReportWristFwd(int grip, float fwd) { if (grip == 0 || grip == 1) { g_wristFwd[grip] = fwd; g_wristStamp[grip] = GetTickCount64(); } }
void CabSetGripAngle(float radians) { g_gripPhi = (std::max)(0.0f, (std::min)(1.2f, radians)); }
bool CabDriverBodyRecent() { return g_bodyStamp && GetTickCount64() - g_bodyStamp < 250; }

bool CabHeaderScreenBottom(float* fraction) {
    if (g_headerBottom < 0.0f || GetTickCount64() - g_headerStamp > 250) return false;
    if (fraction) *fraction = (std::min)(1.0f, g_headerBottom);
    return true;
}

// FIX-FP-2 (pm19-convertible-driver-absent-third-and-fp, the first-person half): the driver's
// hands on the wheel built just before (g_wheel), at ten to two, turning with it (the grip slides
// past +-0.7 rad, the way hands shuffle on a rim). The view model's right fist (tools/gen_weapons.py
// fp_arm_right: closed round a grip along +y at the origin, the forearm back and down toward the
// eye, the shirt's sleeve at the elbow) on each side, mirrored for the left; sleeves in the
// player's shirt colour as on foot. Sized to the rim: a fist about a quarter of the wheel across.
void DrawCabHands(IDirect3DDevice9* device, const gta2::Mat4& carToWorld, const CabInteriorParams& p, const D3DMATERIAL9& restore) {
    if (!g_wheel.valid || !p.hands || CabDriverBodyRecent()) return;   // FIX-COCKPIT-BODY: his body's own hands
    const Model* arm = ModelByName("fp_arm_right");
    if (!arm) return;
    auto toWorldP = [&](const Vec3& q) {
        return Vec3{q.x * carToWorld.m[0][0] + q.y * carToWorld.m[1][0] + q.z * carToWorld.m[2][0] + carToWorld.m[3][0],
                    q.x * carToWorld.m[0][1] + q.y * carToWorld.m[1][1] + q.z * carToWorld.m[2][1] + carToWorld.m[3][1],
                    q.x * carToWorld.m[0][2] + q.y * carToWorld.m[1][2] + q.z * carToWorld.m[2][2] + carToWorld.m[3][2]};
    };
    auto toWorldV = [&](const Vec3& q) {
        return gta2::Normalize(Vec3{q.x * carToWorld.m[0][0] + q.y * carToWorld.m[1][0] + q.z * carToWorld.m[2][0],
                                    q.x * carToWorld.m[0][1] + q.y * carToWorld.m[1][1] + q.z * carToWorld.m[2][1],
                                    q.x * carToWorld.m[0][2] + q.y * carToWorld.m[1][2] + q.z * carToWorld.m[2][2]});
    };
    const WheelPose& w = g_wheel;
    // The unturned frame: u, v are the turned rim's; back out the turn, then let the grip follow
    // part of it.
    const float cs = std::cos(w.turn), sn = std::sin(w.turn);
    const Vec3 across = w.u * cs - w.v * sn, up = w.u * sn + w.v * cs;
    // FIX-COCKPIT-BODY: the grips go round with the rim (the turn is at most 100 degrees), no sliding.
    const float hold = w.turn;
    const float k = 26.0f * w.R;   // the fist (0.0124 model units across) about a sixth of the wheel
    const IdentityRecord& hero = IdentityForPlayer();
    float mean[3];
    if (hero.model && ModelNodeTextureMean(device, *arm, "sleeve", mean)) {
        float t[3];
        for (int c = 0; c < 3; ++c) t[c] = hero.shownTop[c] / (std::max)(mean[c], 8.0f);
        ModelSetNodeTint("sleeve", t);
    }
    D3DMATERIAL9 mat = restore;
    mat.Diffuse = {1.0f, 1.0f, 1.0f, 1.0f};
    mat.Ambient = {1.0f, 1.0f, 1.0f, 1.0f};
    mat.Specular = {0.0f, 0.0f, 0.0f, 0.0f};
    const float fill = p.night ? 0.12f : 0.30f;
    mat.Emissive = {fill, fill, fill, 1.0f};
    device->SetMaterial(&mat);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
    // FIX-FP-ENTRY (pfeel32): each forearm points from its grip on the rim back to a shoulder fixed
    // by the seat's eye (car frame), so the arm follows the driver's body, not the rim: a grip at the
    // wheel's top under full lock, a cabin rolled 25 degrees on a kerb, kept the forearm aimed at the
    // shoulder. Before, the forearm lay along the rim's tangent (flipped by sign at the top), so at
    // lock one arm became a long stick across the dash and the other a stub pointing at the roof.
    // The arm is the rigid view model: never stretched; where the shoulder is nearer than the
    // forearm the sleeve runs past it, behind the eye.
    const Vec3 eyeW = toWorldP(Vec3{p.eyeX, p.eyeY, p.eyeZ});
    const Vec3 carRight = toWorldV(Vec3{1.0f, 0.0f, 0.0f}), carUp = toWorldV(Vec3{0.0f, 1.0f, 0.0f}),
               carFwd = toWorldV(Vec3{0.0f, 0.0f, 1.0f});
    // the model's forearm, grip to elbow (tools/gen_weapons.py fp_arm right: wrist .0045,-.021,-.024, elbow .030,-.070,-.160)
    const Vec3 dmR = gta2::Normalize(Vec3{0.0255f, -0.049f, -0.136f});
    // FIX-FIGURE-8 (pfeel32) probe: GTA2DX9_FP_ARM_LOG=1 logs per frame the camera's real eye in the
    // posed car's frame against the eye the cab was built for, the body's up axis, and each grip's
    // distance to its shoulder (in fists).
    static const bool armLog = [] { char b[4] = {}; return GetEnvironmentVariableA("GTA2DX9_FP_ARM_LOG", b, sizeof b) && b[0] == '1'; }();
    float gripShoulder[2] = {0.0f, 0.0f};
    for (int h = 0; h < 2; ++h) {
        const float phi0 = h == 0 ? 0.80f : kPi - 0.80f;
        const float phi = phi0 + hold;   // ten to two (the fist sits a little under its grip point)
        const Vec3 radial = across * std::cos(phi) + up * std::sin(phi);
        const Vec3 grip = toWorldP(w.c + radial * w.R);
        // which hand: the old rule at the straight-ahead grip (once per hand, so no flip with the turn)
        bool mirror;
        {
            const Vec3 r0 = across * std::cos(phi0) + up * std::sin(phi0);
            Vec3 t0 = up * std::cos(phi0) - across * std::sin(phi0);
            if (gta2::Dot(t0, up) < 0.0f) t0 = t0 * -1.0f;
            const Vec3 Y0 = toWorldV(t0), Z0 = toWorldV(w.axis);
            mirror = gta2::Dot(gta2::Normalize(gta2::Cross(Y0, Z0)), toWorldV(r0)) < 0.0f;
        }
        // the grip's +y along the rim, the same way round for the whole turn (toward the top at ten to two)
        Vec3 tangent = up * std::cos(phi) - across * std::sin(phi);
        if (h == 1) tangent = tangent * -1.0f;
        // the shoulder: beside the eye on the hand's side, below and a little behind it
        const float sideSign = gta2::Dot(grip - eyeW, carRight) >= 0.0f ? 1.0f : -1.0f;
        // sized by the fist (0.0124 k, a real ~0.1 m): shoulders 2 fists either side of the eye, 2.5 under it, 1 behind
        const float fist = 0.0124f * k;
        const Vec3 shoulder = eyeW + carRight * (sideSign * 2.0f * fist) - carUp * (2.5f * fist) - carFwd * fist;
        Vec3 d = shoulder - grip;
        gripShoulder[h] = std::sqrt(gta2::Dot(d, d)) / fist;
        if (gta2::Dot(d, d) < 1e-10f) d = carFwd * -1.0f;
        d = gta2::Normalize(d);
        const Vec3 tW = toWorldV(tangent);
        Vec3 t2 = tW - d * gta2::Dot(tW, d);
        if (gta2::Dot(t2, t2) < 1e-8f) t2 = carUp - d * gta2::Dot(carUp, d);
        t2 = gta2::Normalize(t2);
        const Vec3 b2 = gta2::Cross(d, t2);
        // the model's own frame: forearm, grip axis (+y) square to it, their cross
        const Vec3 dm = mirror ? Vec3{-dmR.x, dmR.y, dmR.z} : dmR;
        Vec3 ym = Vec3{0.0f, 1.0f, 0.0f} - dm * dm.y;
        ym = gta2::Normalize(ym);
        const Vec3 bm = gta2::Cross(dm, ym);
        // a model axis e goes to sum_i (M_i . e) W_i
        auto image = [&](const Vec3& e) {
            return d * gta2::Dot(dm, e) + t2 * gta2::Dot(ym, e) + b2 * gta2::Dot(bm, e);
        };
        Vec3 X = image(Vec3{1.0f, 0.0f, 0.0f}), Y = image(Vec3{0.0f, 1.0f, 0.0f}), Z = image(Vec3{0.0f, 0.0f, 1.0f});
        if (mirror) X = X * -1.0f;   // the right hand's model, mirrored for the left
        gta2::Mat4 m;
        for (int c = 0; c < 3; ++c) {
            m.m[0][c] = (&X.x)[c] * k; m.m[1][c] = (&Y.x)[c] * k; m.m[2][c] = (&Z.x)[c] * k;
            m.m[3][c] = (&grip.x)[c];
        }
        m.m[3][3] = 1.0f;
        ModelDraw(device, *arm, m, nullptr, 0.0f);
    }
    ModelSetNodeTint(nullptr, nullptr);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    if (armLog) {
        D3DMATRIX v;
        if (SUCCEEDED(device->GetTransform(D3DTS_VIEW, &v))) {
            float c[3];
            for (int j = 0; j < 3; ++j) c[j] = -(v.m[3][0] * v.m[j][0] + v.m[3][1] * v.m[j][1] + v.m[3][2] * v.m[j][2]);
            float l[3];
            for (int a = 0; a < 3; ++a) {
                const float* ax = carToWorld.m[a];
                const float al = ax[0] * ax[0] + ax[1] * ax[1] + ax[2] * ax[2];
                l[a] = al > 1e-10f ? ((c[0] - carToWorld.m[3][0]) * ax[0] + (c[1] - carToWorld.m[3][1]) * ax[1] + (c[2] - carToWorld.m[3][2]) * ax[2]) / al : 0.0f;
            }
            const float* u = carToWorld.m[1];
            const float level = u[1] / (std::max)(1e-6f, std::sqrt(u[0] * u[0] + u[1] * u[1] + u[2] * u[2]));
            Log("fp arm: eyeLocal %.3f,%.3f,%.3f cam %.3f,%.3f,%.3f d %.3f,%.3f,%.3f up %.3f,%.3f,%.3f level %.3f turn %.2f grip-shoulder %.2f %.2f fists",
                p.eyeX, p.eyeY, p.eyeZ, l[0], l[1], l[2], l[0] - p.eyeX, l[1] - p.eyeY, l[2] - p.eyeZ,
                carRight.y, carUp.y, carFwd.y, level, w.turn, gripShoulder[0], gripShoulder[1]);
        }
    }
    static bool logged = false;
    if (!logged) { logged = true; Log("cab: hands on the wheel (fp_arm_right x2, fist %.3f of the rim's %.3f)", 0.0124f * k, 2.0f * w.R); }
}

void DrawCabInterior(IDirect3DDevice9* device, const gta2::Mat4& carToWorld, const CabInteriorParams& p,
                     const D3DMATERIAL9& restore) {
    const Style st = StyleFor(p.cls, p.paint);
    g_wheel.valid = false;
    Builder b;
    b.eye = {p.eyeX, p.eyeY, p.eyeZ};
    const float ex = p.eyeX, ey = p.eyeY, ez = p.eyeZ;
    const float side = ex >= 0.0f ? 1.0f : -1.0f;   // the driver's side of the car
    // The dashboard's line: the hood copy's, under the cut a hand below the eye. Where
    // the copy keeps nothing high just ahead of the cut (a van's bonnet that falls away,
    // the eye lifted over a Schmidt's tall lamps), the dash stays at most 0.047 under
    // the eye: lower, the wheel and the gauges left the bottom of the view (run
    // qa_qb31c, the van) and with the dash at the copy's line the road showed where the
    // dash should be (qa_qb31b, the Schmidt). Every class then frames the same way.
    const float top = (std::min)(ey - 0.043f, (std::max)(p.dashTop, ey - 0.047f));
    const float dc = (std::max)(0.06f, p.zCut - ez);   // the windscreen's foot, ahead of the eye
    const float x0 = p.dashX0 - 0.01f, x1 = p.dashX1 + 0.01f;
    auto P = [&](float x, float d, float h) { return Vec3{x, top + h, ez + d}; };   // d ahead of the eye, h over the dash line
    Vec3 pedalAt[2] = {Vec3{ex, top - 0.15f, ez + 0.05f}, Vec3{ex, top - 0.15f, ez + 0.05f}};   // FIX-COCKPIT-BODY (set below)

    // 1. The dashboard: from the windscreen's foot up to a crest, back to a rolled
    // edge toward the driver, then down (out of view under the wheel).
    const float dCrest = dc - 0.018f, dRear = dc - 0.036f;
    const float hCrest = p.cls == CabClass::Car ? 0.004f : 0.006f;
    b.Quad(kDash, P(x0, dc + 0.004f, 0.0f), P(x1, dc + 0.004f, 0.0f), P(x1, dCrest, hCrest), P(x0, dCrest, hCrest));
    b.Quad(kDash, P(x0, dCrest, hCrest), P(x1, dCrest, hCrest), P(x1, dRear, 0.002f), P(x0, dRear, 0.002f));
    b.Quad(kLower, P(x0, dRear, 0.002f), P(x1, dRear, 0.002f), P(x1, dRear - 0.006f, -0.012f), P(x0, dRear - 0.006f, -0.012f));
    // FIX-FP-2 (pm30): the face toward the driver, down past the bottom of the view: a trim seam
    // under the rolled edge, the lower dash in the dash's own colour (the centre stack's plane),
    // then the knee panel sloping away under it (kept ahead of the near plane, 0.05).
    // Before, one near-black face ended 0.08 under the dash line: a black band, and in a tall
    // cab the frame's bottom edge under it (pm30 garbage truck).
    b.Quad(kTrim, P(x0, dRear - 0.0062f, -0.012f), P(x1, dRear - 0.0062f, -0.012f), P(x1, dRear - 0.0065f, -0.0155f), P(x0, dRear - 0.0065f, -0.0155f));
    b.Quad(kLower, P(x0, dRear - 0.006f, -0.015f), P(x1, dRear - 0.006f, -0.015f), P(x1, dRear - 0.008f, -0.08f), P(x0, dRear - 0.008f, -0.08f));
    b.Quad(kLower, P(x0, dRear - 0.008f, -0.08f), P(x1, dRear - 0.008f, -0.08f), P(x1, dRear + 0.014f, -0.28f), P(x0, dRear + 0.014f, -0.28f));
    // The knee panel's upper edge: a darker roll across, so the two faces read as a padded edge.
    b.Quad(kDashDark, P(x0, dRear - 0.0083f, -0.076f), P(x1, dRear - 0.0083f, -0.076f), P(x1, dRear - 0.0080f, -0.088f), P(x0, dRear - 0.0080f, -0.088f));
    // The defroster vents along the windscreen: dark slots on the slope.
    {
        const float va = dc - 0.003f, vb = dc - 0.009f;
        auto onSlope = [&](float d) { return 0.0008f + hCrest * (dc + 0.004f - d) / (dc + 0.004f - dCrest); };
        const int slots = p.cls == CabClass::Car ? 2 : 3;
        const float span = (x1 - x0) - 0.08f;
        for (int i = 0; i < slots; ++i) {
            const float a = x0 + 0.04f + span * (i + 0.08f) / slots, c = x0 + 0.04f + span * (i + 0.92f) / slots;
            b.Quad(kDashDark, P(a, va, onSlope(va)), P(c, va, onSlope(va)), P(c, vb, onSlope(vb)), P(a, vb, onSlope(vb)));
        }
    }
    // 2. The binnacle in front of the driver: a cowl over the gauges. (FIX-COCKPIT-BODY: not in the dashcam
    // view, a camera on the windscreen over the dash top: the gauges stood up at the bottom of its frame.)
    if (!p.dashcam) {
        // The cluster tilted up toward the eye at the binnacle's back, a visor over its far
        // half: from the seat the eye looks down on the dash at a steep angle (the dash
        // stands a hand ahead and under the eye), so gauges under an overhanging cowl hid.
        const float bw = st.binnacleHalf, xa = ex - bw, xb = ex + bw;
        const float dBack = dRear + 0.004f, dPlateTop = dBack + 0.010f, dFront = dPlateTop + 0.012f, dNose = dFront + 0.008f;
        const float hPlate0 = 0.002f, hPlate1 = 0.009f, hTop = 0.0115f;
        b.Quad(kDashDark, P(xa, dPlateTop, hTop), P(xb, dPlateTop, hTop), P(xb, dFront, hTop), P(xa, dFront, hTop));   // visor top
        b.Quad(kDashDark, P(xa, dFront, hTop), P(xb, dFront, hTop), P(xb, dNose, 0.003f), P(xa, dNose, 0.003f));       // its front slope
        b.Quad(kTrim, P(xa, dPlateTop, hTop), P(xb, dPlateTop, hTop), P(xb, dPlateTop - 0.0005f, hPlate1), P(xa, dPlateTop - 0.0005f, hPlate1));  // the lip
        for (float x : {xa, xb}) {
            const Vec3 o[5] = {P(x, dBack, hPlate0 - 0.002f), P(x, dPlateTop, hTop), P(x, dFront, hTop), P(x, dNose, 0.003f), P(x, dNose, 0.0f)};
            for (int k = 1; k + 1 < 5; ++k) b.Tri(kDashDark, o[0], o[k], o[k + 1]);
        }
        // The plate and the gauges on it.
        const Vec3 p0 = P(xa, dBack, hPlate0), p1 = P(xb, dBack, hPlate0), p2 = P(xb, dPlateTop, hPlate1), p3 = P(xa, dPlateTop, hPlate1);
        b.Quad(kDashDark, p0, p1, p2, p3);
        const Vec3 u{1.0f, 0.0f, 0.0f};
        const Vec3 v = gta2::Normalize(p3 - p0);
        Vec3 nrm = gta2::Normalize(gta2::Cross(u, v));
        if (gta2::Dot(nrm, b.eye - p0) < 0.0f) nrm = nrm * -1.0f;
        const int n = st.gauges;
        const float slant = std::sqrt(gta2::Dot(p3 - p0, p3 - p0));
        const float r = (std::min)(0.40f * slant, (2.0f * bw - 0.004f) / (2.0f * n) * 0.8f);
        const float sp = (std::min)(1.0f, std::fabs(p.speed) / 9.0f);
        for (int i = 0; i < n; ++i) {
            const float gx = xa + 0.002f + (2.0f * bw - 0.004f) * (i + 0.5f) / n;
            const Vec3 c{gx, (p0.y + p3.y) * 0.5f, (p0.z + p3.z) * 0.5f};
            b.Disc(kGaugeRim, c + nrm * 0.0002f, u, v, r * 1.15f);
            b.Disc(kGaugeFace, c + nrm * 0.0004f, u, v, r);
            // Speed on the big dial (the one nearest the middle), revs on the others, fuel steady.
            const bool speedo = i == n / 2 || (n == 2 && i == 1);
            float frac = speedo ? sp : (i == 0 ? (std::min)(1.0f, 0.18f + 0.7f * sp + 0.08f * std::sin(p.speed * 3.0f)) : 0.62f);
            const float a = (225.0f - 270.0f * frac) * kPi / 180.0f;
            const Vec3 dir = u * std::cos(a) + v * std::sin(a);
            const Vec3 base = c + nrm * 0.0006f;
            const Vec3 perp = u * -std::sin(a) + v * std::cos(a);
            b.Tri(kNeedle, base + perp * 0.0004f, base - perp * 0.0004f, base + dir * (r * 0.85f));
        }
    }
    // 3. The steering wheel, its rim's top just over the dash's rear edge; turned
    // with the front wheels (a few turns lock to lock). FIX-COCKPIT-BODY (owner item 3): not in the dashcam
    // view (nor its column, nor the hands on it).
    if (!p.dashcam) {
        const float R = st.wheelR, rake = st.wheelRake;
        const float dTop = dRear - 0.008f;
        // FIX-FIGURE: the rim's top higher than QB-31's 0.011 (the hub and spokes sat
        // under the bottom of the view; only an arc showed): the gauges seen through
        // the wheel's upper half, the hub just over the dash's rear edge.
        const Vec3 rimTop = P(ex, dTop, 0.011f + 0.6f * R);
        const Vec3 up{0.0f, std::cos(rake), -std::sin(rake)};      // in the wheel's plane, toward its top
        const Vec3 axis{0.0f, std::sin(rake), std::cos(rake)};     // its column, away from the driver
        const Vec3 across{1.0f, 0.0f, 0.0f};
        // FIX-DRIVER-GEOM-2 (dg2_dgh2): on a cab whose wheel sits close to the eye (the 042: both wrists 0.050..0.052 ahead
        // of the eye at ten to two, against the 0.05 near plane) the fists were cut open and read as pale see-through
        // shapes. The wheel (rim, hub, column) is moved along its column, away from the driver, by what the seat needs:
        // learned while both hands are at home from where live_geometry put his wrists (CabReportWristFwd), eased, at most
        // kPushMax; a new seat starts again from none. The van (0.060) and the fire truck (0.057) need little or nothing.
        // GTA2DX9_FP_GRIP_NEAR_OLD=1: no push (A/B).
        static float wheelPush = 0.0f;
        static ULONGLONG pushStamp = 0;
        static bool handsHome = false;   // last frame's grips both at home, not moving (set below)
        {
            static const bool pushOff = [] { char b[4] = {}; return GetEnvironmentVariableA("GTA2DX9_FP_GRIP_NEAR_OLD", b, sizeof b) && b[0] == '1'; }();
            constexpr float kWristWant = 0.058f, kPushMax = 0.012f;
            const ULONGLONG now = GetTickCount64();
            if (!p.warm) {
                if (!pushStamp || now - pushStamp > 500) wheelPush = 0.0f;
                pushStamp = now;
                const float sc = std::sqrt(carToWorld.m[2][0] * carToWorld.m[2][0] + carToWorld.m[2][1] * carToWorld.m[2][1] + carToWorld.m[2][2] * carToWorld.m[2][2]);
                if (!pushOff && handsHome && sc > 1e-6f && now - g_wristStamp[0] < 200 && now - g_wristStamp[1] < 200) {
                    const float f = (std::min)(g_wristFwd[0], g_wristFwd[1]);
                    const float want = (std::max)(0.0f, (std::min)(kPushMax, wheelPush + (kWristWant - f) / sc));
                    wheelPush += (want - wheelPush) * 0.25f;
                    static float loggedPush = 0.0f;
                    if (std::fabs(wheelPush - loggedPush) > 0.002f) { loggedPush = wheelPush; Log("cab: wheel moved %.4f along its column (wrist %.3f from the eye)", wheelPush, f); }
                }
            }
        }
        const Vec3 c = rimTop - up * R + axis * wheelPush;
        // FIX-SEAT-ENTRY (pfeel41 f11-24): the wheel turns with the front wheels as the driver would
        // turn it, not with every flicker of the game's heading. The steer the bodies measure (the
        // heading change over the distance a frame) jumps by a tenth of a radian on a straight road;
        // times six on the rim that swung the hands between the rim's sides, its top and its foot
        // every few frames. A dead band of 0.035 rad of steer, then eased in over ~0.12 s and no
        // faster than 4 rad/s of rim.
        static float shownSteer = 0.0f;
        static ULONGLONG steerStamp = 0;
        if (!p.warm) {
            const ULONGLONG now = GetTickCount64();
            const float dt = steerStamp ? (std::min)(0.1f, static_cast<float>(now - steerStamp) / 1000.0f) : 0.0f;
            const float dead = 0.035f;
            const float want = std::fabs(p.steer) < dead ? 0.0f : p.steer - (p.steer > 0.0f ? dead : -dead);
            if (!steerStamp || now - steerStamp > 500) shownSteer = want;
            else {
                const float k = 1.0f - std::exp(-dt / 0.12f);
                const float step = (want - shownSteer) * k, cap = (4.0f / 6.0f) * dt;
                shownSteer += (std::max)(-cap, (std::min)(cap, step));
            }
            steerStamp = now;
        }
        // FIX-COCKPIT-BODY (owner item 2, "the steering wheel rotates opposite to the car's turns"). The steer is + to
        // the car's left (vehicle_fx: atan(wheelbase * dyaw / ds)); a + turn takes the rim's +x end up and its top
        // toward -x, and +x is the screen's right from the seat, so the rim's sign was right (verified with the
        // twelve o'clock band below, run cb_rec1: a left turn takes the band left). What read as the wrong way: the
        // rim turned up to 150 degrees with nothing on it to follow (a three-spoke hub past 90 degrees reads as
        // turning back) while the hands slid on it, held to 40 degrees. Now at most 100 degrees, a pale band at
        // twelve o'clock, and the hands (his body's, or the fists) go round with the rim.
        // FIX-COCKPIT-BODY-2 (owner item 2 re-verified on HEAD 5c0ee78, run cb2_v1): the band went RIGHT on a held Left
        // and left on a held Right on all three cars (068 at 30 fps: the band clockwise from the first frame of the
        // Left hold). The cab's +x is the screen's LEFT from the seat (the grips: grip 0 at +x is the left hand), so
        // a + steer (a left turn) must turn the rim's top toward +x. GTA2DX9_FP_WHEEL_OLD_SIGN=1: the 5c0ee78 sign.
        static const float wheelSign = [] { char b[4] = {}; return GetEnvironmentVariableA("GTA2DX9_FP_WHEEL_OLD_SIGN", b, sizeof b) && b[0] == '1' ? 1.0f : -1.0f; }();
        // GTA2DX9_FP_WHEEL_TURN_MILLI=N (probe): the rim held at N/1000 rad whatever the steer (+ takes the top toward -x).
        static const int forcedTurn = [] { char b[16] = {}; return GetEnvironmentVariableA("GTA2DX9_FP_WHEEL_TURN_MILLI", b, sizeof b) ? atoi(b) : 0; }();
        const float turn = forcedTurn ? forcedTurn / 1000.0f
                                      : (std::max)(-1.75f, (std::min)(1.75f, (p.warm ? 0.0f : shownSteer) * 6.0f * wheelSign));
        const float cs = std::cos(turn), sn = std::sin(turn);
        const Vec3 u = across * cs + up * sn, v = up * cs - across * sn;
        b.Torus(kWheel, c, u, v, axis, R, st.wheelTube);
        // Three spokes (left and right, a little drooped, and down) to a hub with a horn pad.
        for (float a : {-0.22f, kPi + 0.22f, 1.5f * kPi}) {
            const Vec3 dir = u * std::cos(a) + v * std::sin(a);
            b.Bar(kGaugeRim, c + dir * (0.28f * R) + axis * 0.0015f, c + dir * (R - st.wheelTube), st.wheelTube * 0.40f);
        }
        // FIX-COCKPIT-BODY: a pale leather band at the rim's twelve o'clock, as many wheels have: which way the
        // rim turns reads at a glance.
        b.Bar(kGaugeRim, c + v * (R - 1.25f * st.wheelTube), c + v * (R + 1.25f * st.wheelTube), st.wheelTube * 0.75f);
        b.Disc(kWheel, c - axis * 0.0006f, u, v, 0.34f * R, 16);
        b.Disc(kTrim, c - axis * 0.0010f, u, v, 0.12f * R, 10);
        // FIX-FP-2 (pm30 garbage truck: "a wheel not attached to anything"): the column, from
        // behind the hub down into the binnacle's foot, with a shroud where it meets the dash.
        const Vec3 colEnd = P(ex, dRear + 0.022f, -0.004f);
        b.Bar(kDashDark, c + axis * 0.0008f, colEnd, 0.10f * R + 0.0006f);
        b.Bar(kDashDark, c + (colEnd - c) * 0.55f, colEnd, 0.16f * R + 0.0008f);
        g_wheel = {true, c, u, v, axis, R, st.wheelTube, turn};
        if (!p.warm) {
            // FIX-COCKPIT-BODY: the seat as built, world space, for his body (CabLastDriverPose).
            auto W = [&](const Vec3& q) {
                return Vec3{q.x * carToWorld.m[0][0] + q.y * carToWorld.m[1][0] + q.z * carToWorld.m[2][0] + carToWorld.m[3][0],
                            q.x * carToWorld.m[0][1] + q.y * carToWorld.m[1][1] + q.z * carToWorld.m[2][1] + carToWorld.m[3][1],
                            q.x * carToWorld.m[0][2] + q.y * carToWorld.m[1][2] + q.z * carToWorld.m[2][2] + carToWorld.m[3][2]};
            };
            auto WV = [&](const Vec3& q) { const Vec3 o = W(Vec3{0.0f, 0.0f, 0.0f}); return gta2::Normalize(W(q) - o); };
            g_driver.eye = W(b.eye);
            g_driver.right = WV(Vec3{1.0f, 0.0f, 0.0f});   // the car's +x (the screen's LEFT from the seat: FIX-COCKPIT-BODY-2, run cb2_t1)
            g_driver.up = WV(Vec3{0.0f, 1.0f, 0.0f});
            g_driver.fwd = WV(Vec3{0.0f, 0.0f, 1.0f});
            // FIX-DRIVER-GEOM (pmab1, pfl71): hand over hand. Turned with the rim through its travel (5c0ee78; cd5bb11
            // let the lower hand slide at -0.2 rad but took the upper one to 2.3), past ~45 degrees one hand rode onto
            // the rim's top (on a van's or a truck's flat wheel, the stretch nearest the eye: a fist as wide as the
            // gauges, dgh_head) and the other went to the frame's bottom edge or behind the binnacle. Each hand holds
            // the rim at its own place (gripOff, the rim's frame) and turns with it while it stays in its arc, 0.30..1.05
            // rad over the rim's horizontal on its own side (lower, a steep sports wheel's hand left the frame's bottom and
            // a flat wheel's lay as a flat palm drooping over the gauges; higher, a van's fist read as a palm as wide as
            // the gauges: dgh_4, dgh_5); leaving the arc it lets go and
            // takes the rim again at home (ten to two, g_gripPhi), lifted a little off it on the way (0.22 s). One hand
            // moves at a time, each at most every 0.35 s (a noisy steer swung them back and forth); one waiting for the
            // other is held at its arc's end (the rim slides through it); with the wheel near the middle a hand away from
            // home goes back to it. GTA2DX9_FP_REGRIP=0: cd5bb11's clamped grips. GTA2DX9_FP_GRIP_LOG=1: the grips.
            static const bool regripOn = [] { char b[4] = {}; return !(GetEnvironmentVariableA("GTA2DX9_FP_REGRIP", b, sizeof b) && b[0] == '0'); }();
            const float kHome = g_gripPhi;
            constexpr float kLow = 0.30f, kHigh = 1.05f, kMove = 0.22f, kRest = 0.35f;
            struct GripMove { bool on = false; float from = 0.0f, t = 0.0f, since = 10.0f; };
            static float gripOff[2] = {0.52f, kPi - 0.52f};
            static GripMove move[2];
            static ULONGLONG gripStamp = 0;
            static int regrips = 0;
            const ULONGLONG gnow = GetTickCount64();
            const float gdt = gripStamp ? (std::min)(0.1f, static_cast<float>(gnow - gripStamp) / 1000.0f) : 0.0f;
            // FIX-DRIVER-GEOM-2: each hand's own arc end, lowered for this seat where its wrist was drawn within kWristMin of
            // the eye (a sports wheel close to the eye: the 042's fist at 1.0 rad cut open with its wrist at 0.047, dg2_dgh1)
            constexpr float kWristMin = 0.0495f;
            static float handHigh[2] = {kHigh, kHigh};
            if (!gripStamp || gnow - gripStamp > 500) {   // a new seat (or after a gap): both hands at home
                gripOff[0] = kHome - turn; gripOff[1] = kPi - kHome - turn; move[0] = move[1] = GripMove{};
                handHigh[0] = handHigh[1] = kHigh;
            }
            gripStamp = gnow;
            // FIX-DRIVER-GEOM-2 (demo2_dep1, pmab1/pfl71 re-open): on a raked wheel (a van's, a truck's) the rim's top is the
            // stretch nearest the eye: a hand held at 1.05 rad, or one lifted radially outward mid-regrip, put its wrist at
            // 0.050 from the eye (dg2_rep1 'arms as drawn'), on the 0.05 near plane: the fist was cut open and read as a huge
            // see-through palm. Each hand's arc now ends where its grip would come nearer the eye (along the car's forward)
            // than its home grip by more than kNearer (world blocks), and a regrip lifts the hand along the column, away from
            // the eye. GTA2DX9_FP_GRIP_NEAR_OLD=1: a0dcb09's fixed arc and radial lift (A/B).
            static const bool nearOld = [] { char b[4] = {}; return GetEnvironmentVariableA("GTA2DX9_FP_GRIP_NEAR_OLD", b, sizeof b) && b[0] == '1'; }();
            constexpr float kNearer = 0.003f;
            float high = kHigh;
            if (!nearOld) {
                auto fwdOf = [&](float a) { return gta2::Dot(W(c + (across * std::cos(a) + up * std::sin(a)) * R) - g_driver.eye, g_driver.fwd); };
                const float f0 = fwdOf(kHome);
                for (float a = kHome; a <= kHigh + 1e-4f; a += 0.025f) { if (fwdOf(a) < f0 - kNearer) break; high = a; }
                high = (std::max)(kHome + 0.10f, high);
                static float lastHigh = -1.0f;
                if (std::fabs(high - lastHigh) > 0.04f) { lastHigh = high; Log("cab: grip arc %.2f..%.2f rad (rim top nearer the eye)", kLow, high); }
            }
            for (int h = 0; h < 2; ++h) {
                const float home = h == 0 ? kHome : kPi - kHome;
                auto side = [&](float a) { return h == 0 ? a : kPi - a; };   // an angle on this hand's side, as seen from hand 0's
                float phi = gripOff[h] + turn, lift = 0.0f;
                move[h].since += gdt;
                if (!regripOn) {
                    phi = h == 0 ? (std::max)(-0.2f, (std::min)(2.3f, kHome + turn)) : (std::max)(kPi - 2.3f, (std::min)(kPi + 0.2f, kPi - kHome + turn));
                } else if (move[h].on) {
                    move[h].t += gdt / kMove;
                    const float k = (std::min)(1.0f, move[h].t), s = k * k * (3.0f - 2.0f * k);
                    phi = move[h].from + (home - move[h].from) * s;
                    lift = std::sin(kPi * k);
                    if (k >= 1.0f) { move[h].on = false; move[h].since = 0.0f; gripOff[h] = home - turn; phi = home; lift = 0.0f; }
                } else {
                    const float a = side(phi);
                    if (!nearOld && gnow - g_wristStamp[h] < 200 && g_wristFwd[h] < kWristMin && a > kHome + 0.06f && a - 0.06f < handHigh[h]) {
                        handHigh[h] = (std::max)(kHome + 0.06f, a - 0.06f);
                        static int nearLogs = 0;
                        if (nearLogs < 30) { ++nearLogs; Log("cab: hand %d wrist %.3f from the eye at %.2f rad: its arc ends at %.2f", h, g_wristFwd[h], a, handHigh[h]); }
                    }
                    const float hi = nearOld ? high : (std::min)(high, handHigh[h]);
                    const bool out = a < kLow || a > hi;
                    const bool away = std::fabs(turn) < 0.20f && std::fabs(a - kHome) > 0.30f;
                    const bool free = !move[1 - h].on && move[h].since > kRest;
                    if ((out || away) && free) {   // let go, take the rim again at home
                        move[h].on = true; move[h].t = 0.0f;
                        move[h].from = side((std::max)(kLow, (std::min)(hi, a)));
                        phi = move[h].from;
                        ++regrips;
                        static int regripLogs = 0;
                        if (regripLogs < 60) { ++regripLogs; Log("cab: regrip hand %d at %.2f rad (turn %.2f, %s), %d so far", h, a, turn, out ? "out of its arc" : "back home", regrips); }
                    } else if (out) {   // waiting for the other hand: held at its arc's end
                        const float held = side((std::max)(kLow, (std::min)(hi, a)));
                        gripOff[h] = held - turn; phi = held;
                    }
                }
                {
                    static const bool gripLog = [] { char b[4] = {}; return GetEnvironmentVariableA("GTA2DX9_FP_GRIP_LOG", b, sizeof b) && b[0] == '1'; }();
                    static unsigned gripN = 0;
                    if (gripLog && h == 1 && (++gripN % 10) == 0)
                        Log("cab: grips turn %.2f hand0 %.2f%s hand1 %.2f%s (own side)", turn, gripOff[0] + turn, move[0].on ? " moving" : "",
                            kPi - (gripOff[1] + turn), move[1].on ? " moving" : "");
                }
                const Vec3 radial = across * std::cos(phi) + up * std::sin(phi);
                // mid-move the hand rides a little off the rim, outward only (toward the eye it met the 0.05 near plane on a
                // van's flat wheel and was cut open, see-through: dg_pfl71)
                g_driver.grip[h] = nearOld ? W(c + radial * (R * (1.0f + 0.12f * lift)))
                                           : W(c + radial * R + axis * (0.6f * st.wheelTube * lift));
                g_driver.rimTangent[h] = WV(up * std::cos(phi) - across * std::sin(phi));
            }
            handsHome = !move[0].on && !move[1].on && std::fabs(gripOff[0] + turn - kHome) < 0.05f && std::fabs(kPi - (gripOff[1] + turn) - kHome) < 0.05f;
            {   // FIX-DRIVER-GEOM (pfl71): which side grip 0 belongs to, from its home on the rim, not where it is now
                const Vec3 h0 = W(c + (across * std::cos(kHome) + up * std::sin(kHome)) * R), h1 = W(c + (across * std::cos(kPi - kHome) + up * std::sin(kPi - kHome)) * R);
                g_driver.grip0Right = gta2::Dot(h0 - h1, g_driver.right) > 0.0f;
            }
            g_driver.wheelCentre = W(c);
            g_driver.wheelAxis = WV(axis);
            g_driver.wheelR = R;
            g_driver.turn = turn;
            g_driver.dashBelow = ey - top;
            g_driverStamp = GetTickCount64();
        }
    }
    // FIX-FIGURE: the centre stack (radio slot, vents) and the glovebox lid on the dash's
    // rear face, and a taxi's fare meter on the dash top.
    {
        const float cx0 = -0.022f, cx1 = 0.022f;
        const float hA = -0.012f, hB = -0.060f, dA = dRear - 0.0055f, dB = dRear - 0.0075f;
        b.Quad(kPanel, P(cx0, dA, hA), P(cx1, dA, hA), P(cx1, dB, hB), P(cx0, dB, hB));
        auto onFace = [&](float h) { return dA + (dB - dA) * (h - hA) / (hB - hA) - 0.0004f; };
        for (int k = 0; k < 2; ++k) {   // two vents side by side, then the radio
            const float a = k ? 0.002f : -0.018f, c2 = k ? 0.018f : -0.002f;
            b.Quad(kDashDark, P(a, onFace(-0.015f), -0.015f), P(c2, onFace(-0.015f), -0.015f), P(c2, onFace(-0.024f), -0.024f), P(a, onFace(-0.024f), -0.024f));
        }
        b.Quad(kTrim, P(-0.016f, onFace(-0.029f), -0.029f), P(0.016f, onFace(-0.029f), -0.029f), P(0.016f, onFace(-0.036f), -0.036f), P(-0.016f, onFace(-0.036f), -0.036f));
        // The glovebox: on the passenger's side.
        const float gx0 = -side * 0.06f, gx1 = -side * (std::min)(0.16f, std::fabs(side > 0 ? x0 : x1) - 0.02f);
        if (std::fabs(gx1) > std::fabs(gx0) + 0.02f) {
            const float ga = -0.016f, gb = -0.034f;
            b.Quad(kPanel, P(gx0, onFace(ga), ga), P(gx1, onFace(ga), ga), P(gx1, onFace(gb), gb), P(gx0, onFace(gb), gb));
            const float gm = 0.5f * (gx0 + gx1);
            b.Quad(kTrim, P(gm - 0.006f, onFace(ga - 0.003f) - 0.0003f, ga - 0.003f), P(gm + 0.006f, onFace(ga - 0.003f) - 0.0003f, ga - 0.003f),
                   P(gm + 0.006f, onFace(ga - 0.005f) - 0.0003f, ga - 0.005f), P(gm - 0.006f, onFace(ga - 0.005f) - 0.0003f, ga - 0.005f));
        }
        if (p.taxi) {
            const float mx = ex * 0.40f, md = dCrest - 0.002f, mw = 0.0055f, mh = 0.0040f, mdp = 0.0045f;
            const Vec3 f0 = P(mx - mw, md - mdp, hCrest), f1 = P(mx + mw, md - mdp, hCrest), f2 = P(mx + mw, md - mdp, hCrest + mh), f3 = P(mx - mw, md - mdp, hCrest + mh);
            const Vec3 k0 = P(mx - mw, md, hCrest), k1 = P(mx + mw, md, hCrest), k2 = P(mx + mw, md, hCrest + mh), k3 = P(mx - mw, md, hCrest + mh);
            b.Quad(kDashDark, f0, f1, f2, f3);
            b.Quad(kDashDark, f3, f2, k2, k3);
            b.Quad(kDashDark, f0, f3, k3, k0);
            b.Quad(kDashDark, f1, f2, k2, k1);
            const Vec3 off{0.0f, 0.0f, -0.0004f};
            b.Quad(kMeter, P(mx - mw * 0.7f, md - mdp, hCrest + mh * 0.45f) + off, P(mx + mw * 0.7f, md - mdp, hCrest + mh * 0.45f) + off,
                   P(mx + mw * 0.7f, md - mdp, hCrest + mh * 0.80f) + off, P(mx - mw * 0.7f, md - mdp, hCrest + mh * 0.80f) + off);
        }
    }
    // 4. The windscreen header across the top of the view and the rear-view mirror under it.
    // FIX-COCKPIT-2: a closed car's header is the roof's lining; an open-top car (roadster,
    // jeep: CabOpenTop) has only the windscreen frame's top rail, with the sky above it.
    // The mirror hangs on a stalk with a base plate screwed to the header (or the rail) at
    // the middle of the car, locked to the car's frame like the rest of the cab.
    const float tanH = std::tan(st.headerAngle * kPi / 180.0f);
    // FIX-COCKPIT-BODY-2 (pfl54 "thin flat sticks and a wide roof slab, the same on every car; the pillar feet in
    // the hood"): the windscreen rakes per body class: its top edge (the header) nearer the eye than its foot by
    // the class's rake (a coupe's well back over the dash, a van's and a truck's nearly over the foot), the header
    // kept at the class's angle over the eye. GTA2DX9_FP_PILLARS_OLD=1: the 5c0ee78 frame (the header 0.02 beyond
    // the foot on every class, flat pillar strips).
    static const bool pillarsOld = [] { char b[4] = {}; return GetEnvironmentVariableA("GTA2DX9_FP_PILLARS_OLD", b, sizeof b) && b[0] == '1'; }();
    float rake = 1.2f;
    if (!pillarsOld) {
        switch (p.cls) {
            case CabClass::Sports: rake = 0.52f; break;
            case CabClass::Car: rake = 0.64f; break;
            case CabClass::Van: rake = 0.86f; break;
            case CabClass::Truck: rake = 0.93f; break;
            case CabClass::Bus: rake = 0.96f; break;
        }
        if (p.openTop) rake = (std::max)(rake, 0.70f);
    }
    const float dH = pillarsOld ? dc + 0.02f : dc * rake, hHeader = tanH * dH;   // over the eye
    const float nearK = pillarsOld ? 1.0f : dH / (dc + 0.02f);   // the mirror kept at its old angular size
    // FIX-COCKPIT-BODY-2 (owner item 3, "a clean forward-facing view, like a real dashcam"): the dashcam sits on the
    // glass behind the mirror, so it sees no header lining, no mirror and no A-pillars (cb2_v3 t_dc_dashcam: thick
    // posts at both edges and the lining across the top). GTA2DX9_DASHCAM_FRAME=1: the 5c0ee78 dashcam (the frame drawn).
    static const bool dashFrame = [] { char b[4] = {}; return GetEnvironmentVariableA("GTA2DX9_DASHCAM_FRAME", b, sizeof b) && b[0] == '1'; }();
    const bool cleanDash = p.dashcam && !dashFrame;
    if (!cleanDash) {
        const float hx0 = x0 - 0.40f, hx1 = x1 + 0.40f;
        const Vec3 a0{hx0, ey + hHeader, ez + dH}, a1{hx1, ey + hHeader, ez + dH};
        const float roofUp = p.openTop ? 0.0090f : 0.08f, roofFwd = p.openTop ? 0.0112f : 0.10f;   // the lining's, or the rail's, depth
        const Vec3 b0{hx0, ey + hHeader + roofUp, ez + dH + roofFwd}, b1{hx1, ey + hHeader + roofUp, ez + dH + roofFwd};
        b.Quad(p.openTop ? kTrim : kHeader, a0, a1, b1, b0);
        // A darker seal along its lower edge, where the glass meets it.
        b.Quad(kTrim, a0, a1, a1 + Vec3{0.0f, 0.004f, 0.005f}, a0 + Vec3{0.0f, 0.004f, 0.005f});
        // The mirror: at the middle of the windscreen (the car's centre line), hung from the header.
        const float w = 0.5f * st.mirrorW * nearK, h = 0.5f * st.mirrorH * nearK;
        const float dMount = dH + 0.006f;
        // The seat is compressed (the pillars stand a hand either side of the eye), so the car's
        // centre line is off to one side of the view; the mirror takes the middle between the pillars.
        const float pxA = ex + side * (std::min)(std::fabs((side > 0 ? x1 : x0) - ex), 0.105f);
        const float pxB = ex - side * (std::min)(std::fabs((side > 0 ? x0 : x1) - ex), 0.95f * dc);
        const float mirX = 0.5f * (pxA + pxB);
        const Vec3 mount{mirX, ey + tanH * dMount + 0.0006f, ez + dMount};
        const Vec3 mc = mount + Vec3{0.0f, -(h + 0.0075f * nearK), 0.0045f * nearK};
        const Vec3 toEye = gta2::Normalize(b.eye - mc);
        const Vec3 mu = gta2::Normalize(gta2::Cross(Vec3{0.0f, 1.0f, 0.0f}, toEye));
        const Vec3 mv = gta2::Normalize(gta2::Cross(toEye, mu));
        b.Quad(kTrim, mc + mu * -w + mv * -h, mc + mu * w + mv * -h, mc + mu * w + mv * h, mc + mu * -w + mv * h);
        const float g = 0.0012f;
        const Vec3 gc = mc + toEye * 0.0006f;
        // The glass shows the sky above and the road below.
        const Vec3 gm0 = gc + mu * (g - w) + mv * 0.15f * h, gm1 = gc + mu * (w - g) + mv * 0.15f * h;
        b.Quad(kGlass, gm0, gm1, gc + mu * (w - g) + mv * (h - g), gc + mu * (g - w) + mv * (h - g));
        b.Quad(kGlassLow, gc + mu * (g - w) + mv * (g - h), gc + mu * (w - g) + mv * (g - h), gm1, gm0);
        b.Bar(kTrim, mc + mv * h - toEye * 0.001f, mount, 0.0016f);
        const float pl = 0.0045f;   // the base plate on the header
        b.Quad(kTrim, mount + Vec3{-pl, 0.0f, 0.0f}, mount + Vec3{pl, 0.0f, 0.0f}, mount + Vec3{pl, 0.0025f, 0.0030f}, mount + Vec3{-pl, 0.0025f, 0.0030f});
    }
    // 5. The A-pillars, from the dash's corners to the header, each with a door mirror on an
    // arm from its base (FIX-COCKPIT-2: both sides, the arm bolted to the pillar's foot).
    auto wingMirror = [&](float out, float footX, float footZ) {
        const bool tall = p.cls == CabClass::Truck || p.cls == CabClass::Bus;
        const float mx = footX + out * (tall ? 0.017f : 0.010f);
        const Vec3 mc{mx, top + (tall ? 0.020f : 0.012f), footZ + (tall ? 0.035f : 0.014f)};
        const Vec3 toEye = gta2::Normalize(b.eye - mc);
        const Vec3 mu = gta2::Normalize(gta2::Cross(Vec3{0.0f, 1.0f, 0.0f}, toEye));
        const Vec3 mv = gta2::Normalize(gta2::Cross(toEye, mu));
        const float w2 = tall ? 0.005f : 0.006f, h2 = 0.5f * st.sideMirrorH;
        b.Quad(kTrim, mc + mu * -w2 + mv * -h2, mc + mu * w2 + mv * -h2, mc + mu * w2 + mv * h2, mc + mu * -w2 + mv * h2);
        const Vec3 gc = mc + toEye * 0.001f;
        const float g = 0.0008f;
        const Vec3 gm0 = gc + mu * (g - w2) + mv * 0.15f * h2, gm1 = gc + mu * (w2 - g) + mv * 0.15f * h2;
        b.Quad(kGlass, gm0, gm1, gc + mu * (w2 - g) + mv * (h2 - g), gc + mu * (g - w2) + mv * (h2 - g));
        b.Quad(kGlassLow, gc + mu * (g - w2) + mv * (g - h2), gc + mu * (w2 - g) + mv * (g - h2), gm1, gm0);
        const Vec3 arm0{footX + out * 0.002f, top + 0.008f, footZ + 0.004f};
        b.Bar(kTrim, arm0, mc - mv * (h2 * 0.5f), 0.0014f);
        if (tall) b.Bar(kTrim, Vec3{arm0.x, top + 0.024f, arm0.z + 0.003f}, mc + mv * (h2 * 0.5f), 0.0012f);
        // The mount: a small block on the pillar's foot where the arm starts.
        const Vec3 k0 = arm0 + Vec3{out * -0.003f, -0.002f, -0.002f}, k1 = arm0 + Vec3{out * 0.003f, 0.003f, 0.002f};
        b.Quad(kTrim, Vec3{k0.x, k0.y, k0.z}, Vec3{k1.x, k0.y, k0.z}, Vec3{k1.x, k1.y, k1.z}, Vec3{k0.x, k1.y, k1.z});
    };
    if (cleanDash) {
        // (the dashcam: no pillars, no door mirrors)
    } else if (pillarsOld) {
        {
            const float reach = (std::min)(std::fabs((side > 0 ? x1 : x0) - ex), 0.105f);
            const float px = ex + side * reach, w = 0.009f;
            const Vec3 f0{px, top, ez + dc}, f1{px + side * w, top, ez + dc + 0.004f};
            const Vec3 t0{px - side * 0.002f, ey + hHeader + 0.002f, ez + dH}, t1{px + side * (w - 0.002f), ey + hHeader + 0.002f, ez + dH + 0.004f};
            b.Quad(kTrim, f0, f1, t1, t0);
            wingMirror(side, px + side * w * 0.5f, ez + dc + 0.006f);
            // FIX-FIGURE: the passenger's A-pillar, from the far dash corner to the header (a
            // pillar of some thickness: inner face, and the face toward the eye).
            // The seat is compressed (the dash a hand ahead): at its true reach the far pillar
            // stood outside the view; kept within ~45 degrees of the nose, at the frame's edge.
            const float reach2 = (std::min)(std::fabs((side > 0 ? x0 : x1) - ex), 0.95f * dc);
            const float qx = ex - side * reach2, w2p = 0.012f;
            const Vec3 g0{qx, top, ez + dc}, g1{qx - side * w2p, top, ez + dc + 0.006f};
            const Vec3 u0{qx + side * 0.004f, ey + hHeader + 0.002f, ez + dH}, u1{qx - side * (w2p - 0.004f), ey + hHeader + 0.002f, ez + dH + 0.006f};
            b.Quad(kTrim, g0, g1, u1, u0);
            b.Quad(kHeader, g0, u0, u0 + Vec3{-side * 0.004f, 0.0f, -0.004f}, g0 + Vec3{-side * 0.004f, 0.0f, -0.004f});
            wingMirror(-side, qx - side * w2p * 0.5f, ez + dc + 0.006f);
            // The driver's pillar gets the same inner face.
            b.Quad(kHeader, f0, t0, t0 + Vec3{side * 0.004f, 0.0f, -0.004f}, f0 + Vec3{side * 0.004f, 0.0f, -0.004f});
        }
    } else {
        // FIX-COCKPIT-BODY-2: each A-pillar a tapered post of some depth (the face toward the eye, a side face toward
        // the cabin and a dark rubber seal along the glass), from a foot on the cowl at the windscreen's base (a
        // gusset into the door's top rail, which runs back past the eye on both sides: the pillar stands on the
        // door, not on the bonnet) to the header at the class's rake, leaning in a little at the top.
        auto pillar = [&](float out, float footX, float wFoot) {
            const float zF = ez + dc, zT = ez + dH, yF = top + 0.0015f, yT = ey + hHeader + 0.0015f;
            const float wTop = wFoot * (0.55f + 0.45f * nearK), lean = 0.10f * (dc - dH);
            const Vec3 fI{footX, yF, zF}, fO{footX + out * wFoot, yF, zF - 0.003f};
            const Vec3 tI{footX - out * lean, yT, zT}, tO{footX - out * lean + out * wTop, yT, zT - 0.002f};
            b.Quad(kHeader, fI, fO, tO, tI);                                                     // the face toward the eye
            const Vec3 back{0.0f, -0.0010f, -0.0060f};
            b.Quad(kDashDark, fI, tI, tI + back - Vec3{out * 0.0015f, 0.0f, 0.0f}, fI + back - Vec3{out * 0.0015f, 0.0f, 0.0f});   // its side, toward the cabin
            const Vec3 seal{-out * 0.0018f, 0.0f, 0.0015f};
            b.Quad(kTrim, fI, tI, tI + seal, fI + seal);                                         // the glass's rubber
            b.Quad(kTrim, fO, tO, tO + Vec3{out * 0.0012f, 0.0f, 0.0008f}, fO + Vec3{out * 0.0012f, 0.0f, 0.0008f});   // the door frame's edge
            // the gusset: the foot widening into the cowl and the door's top rail
            b.Tri(kHeader, fI, fO + Vec3{out * 0.006f, -0.0005f, -0.012f}, fO);
            b.Quad(kTrim, fI + Vec3{0.0f, 0.0f, 0.004f}, fI + Vec3{-out * 0.012f, 0.0f, 0.004f}, fI + Vec3{-out * 0.012f, 0.0025f, 0.004f}, fI + Vec3{0.0f, 0.0025f, 0.004f});
        };
        const float reach = (std::min)(std::fabs((side > 0 ? x1 : x0) - ex), 0.105f);
        const float px = ex + side * reach;
        pillar(side, px, 0.013f);
        wingMirror(side, px + side * 0.0065f, ez + dc + 0.006f);
        const float reach2 = (std::min)(std::fabs((side > 0 ? x0 : x1) - ex), 0.95f * dc);
        const float qx = ex - side * reach2;
        pillar(-side, qx, 0.015f);
        wingMirror(-side, qx - side * 0.0075f, ez + dc + 0.006f);
        // the passenger's door: its top rail (the sill at the window line) and card, from the pillar's foot back past the eye
        const float qd = qx - side * 0.006f;
        auto Q = [&](float d, float h, float in) { return Vec3{qd + side * in, top + h, ez + d}; };
        b.Quad(kTrim, Q(dc, 0.004f, 0.0f), Q(-0.08f, 0.004f, 0.0f), Q(-0.08f, 0.004f, 0.014f), Q(dc, 0.004f, 0.014f));
        b.Quad(kLower, Q(dc, 0.004f, 0.014f), Q(-0.08f, 0.004f, 0.014f), Q(-0.08f, -0.30f, 0.010f), Q(dc, -0.30f, 0.010f));
        // the cowl: a dark lip along the windscreen's base between the pillars' feet, where the glass meets the dash
        b.Quad(kTrim, Vec3{qx, top + 0.0005f, ez + dc + 0.002f}, Vec3{px, top + 0.0005f, ez + dc + 0.002f},
               Vec3{px, top + 0.0030f, ez + dc + 0.004f}, Vec3{qx, top + 0.0030f, ez + dc + 0.004f});
    }
    // FIX-FP-2 (pm30): the driver's door card under the window line, beside and behind the
    // dash: the sill, the card in the lower dash's vinyl and an armrest. In the frame's lower
    // corner on the driver's side (the seat is compressed: kept at the A-pillar's reach).
    {
        const float reach = (std::min)(std::fabs((side > 0 ? x1 : x0) - ex), 0.105f);
        const float dx = ex + side * (reach + 0.006f);
        const float dF = dc, dB = -0.08f, hSill = 0.004f;
        auto D = [&](float d, float h, float in) { return Vec3{dx - side * in, top + h, ez + d}; };
        b.Quad(kTrim, D(dF, hSill, 0.0f), D(dB, hSill, 0.0f), D(dB, hSill, 0.014f), D(dF, hSill, 0.014f));            // the sill
        b.Quad(kLower, D(dF, hSill, 0.014f), D(dB, hSill, 0.014f), D(dB, -0.30f, 0.010f), D(dF, -0.30f, 0.010f));     // the card
        const float aT = -0.055f, aB = -0.070f, aF = 0.045f, aBk = -0.06f;
        b.Quad(kDashDark, D(aF, aT, 0.014f), D(aBk, aT, 0.014f), D(aBk, aT, 0.030f), D(aF, aT, 0.030f));             // armrest top
        b.Quad(kDashDark, D(aF, aT, 0.030f), D(aBk, aT, 0.030f), D(aBk, aB, 0.028f), D(aF, aB, 0.028f));             // its face
        b.Quad(kTrim, D(0.030f, -0.030f, 0.0145f), D(0.012f, -0.030f, 0.0145f), D(0.012f, -0.037f, 0.0145f), D(0.030f, -0.037f, 0.0145f));   // the handle
    }
    // FIX-COCKPIT-BODY: the floor, the pedals and the driver's seat cushion. Looking down from the seat at his
    // own lap showed the road through the cab (nothing was built under the dash line but the dash's face and the
    // door card). A carpeted floor 0.20 under the eye (where his feet go), from the footwell under the dash back
    // past the seat, two pedals in the footwell and the seat's cushion under his hips (0.14 under the eye).
    {
        const float hFloor = (ey - 0.20f) - top, hSeat = (ey - 0.14f) - top;
        const float fx0 = x0 + 0.004f, fx1 = x1 - 0.004f;
        b.Quad(kDashDark, P(fx0, dRear + 0.002f, hFloor), P(fx1, dRear + 0.002f, hFloor), P(fx1, -0.16f, hFloor), P(fx0, -0.16f, hFloor));
        for (int k = 0; k < 2; ++k) {   // brake (inboard) and accelerator, raised a little off the floor, leaning back
            const float px = ex - side * (k == 0 ? 0.004f : -0.016f) - side * 0.006f, pw = k == 0 ? 0.007f : 0.005f;
            const float dF = dRear - 0.006f, dB = dRear - 0.020f;
            b.Quad(kTrim, P(px - pw, dF, hFloor + 0.022f), P(px + pw, dF, hFloor + 0.022f), P(px + pw, dB, hFloor + 0.004f), P(px - pw, dB, hFloor + 0.004f));
            pedalAt[k] = P(px, 0.5f * (dF + dB), hFloor + 0.013f);
        }
        const float sx0 = ex - 0.045f, sx1 = ex + 0.045f, sF = -0.012f, sB = -0.13f;
        b.Quad(kLower, P(sx0, sF, hSeat), P(sx1, sF, hSeat), P(sx1, sB, hSeat - 0.006f), P(sx0, sB, hSeat - 0.006f));   // cushion
        b.Quad(kDashDark, P(sx0, sF, hSeat), P(sx1, sF, hSeat), P(sx1, sF + 0.004f, hFloor), P(sx0, sF + 0.004f, hFloor));   // its front
        b.Quad(kTrim, P(sx0, sF - 0.001f, hSeat + 0.001f), P(sx1, sF - 0.001f, hSeat + 0.001f), P(sx1, sF + 0.001f, hSeat - 0.004f), P(sx0, sF + 0.001f, hSeat - 0.004f));   // piping
    }

    // FIX-HUD pm2: where the lining's lower edge lands on screen, for the HUD's top plates: the
    // edge a0-a1 sampled across the middle third of the view (about +-17 degrees from the eye's
    // line), projected through the view and projection the cab is drawn with.
    const float keptHeaderBottom = g_headerBottom;
    g_headerBottom = -1.0f;
    if (!p.openTop && !cleanDash) {
        D3DMATRIX view = {}, proj = {};
        if (SUCCEEDED(device->GetTransform(D3DTS_VIEW, &view)) && SUCCEEDED(device->GetTransform(D3DTS_PROJECTION, &proj))) {
            for (int i = -2; i <= 2; ++i) {
                const Vec3 q{ex + 0.15f * dH * i, ey + hHeader, ez + dH};
                const float wx = q.x * carToWorld.m[0][0] + q.y * carToWorld.m[1][0] + q.z * carToWorld.m[2][0] + carToWorld.m[3][0];
                const float wy = q.x * carToWorld.m[0][1] + q.y * carToWorld.m[1][1] + q.z * carToWorld.m[2][1] + carToWorld.m[3][1];
                const float wz = q.x * carToWorld.m[0][2] + q.y * carToWorld.m[1][2] + q.z * carToWorld.m[2][2] + carToWorld.m[3][2];
                const float vx = wx * view._11 + wy * view._21 + wz * view._31 + view._41;
                const float vy = wx * view._12 + wy * view._22 + wz * view._32 + view._42;
                const float vz = wx * view._13 + wy * view._23 + wz * view._33 + view._43;
                const float vw = wx * view._14 + wy * view._24 + wz * view._34 + view._44;
                const float cy = vx * proj._12 + vy * proj._22 + vz * proj._32 + vw * proj._42;
                const float cw = vx * proj._14 + vy * proj._24 + vz * proj._34 + vw * proj._44;
                if (cw <= 1e-4f) continue;
                g_headerBottom = (std::max)(g_headerBottom, 0.5f * (1.0f - cy / cw));
            }
        }
    }
    if (p.warm) g_headerBottom = keptHeaderBottom;   // FIX-SEAT-ENTRY-2: an unseen draw moves no HUD plate
    else g_headerStamp = GetTickCount64();

    // To the world, and draw: one call per surface.
    D3DMATRIX identity = {};
    identity._11 = identity._22 = identity._33 = identity._44 = 1.0f;
    device->SetTransform(D3DTS_WORLD, &identity);
    DWORD clip = 0, cull = 0, alphaTest = 0;
    device->GetRenderState(D3DRS_CLIPPLANEENABLE, &clip);
    device->GetRenderState(D3DRS_CULLMODE, &cull);
    device->GetRenderState(D3DRS_ALPHATESTENABLE, &alphaTest);
    device->SetRenderState(D3DRS_CLIPPLANEENABLE, 0u);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetTexture(0, nullptr);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    DWORD addrU = 0, addrV = 0, minF = 0, magF = 0;
    device->GetSamplerState(0, D3DSAMP_ADDRESSU, &addrU);
    device->GetSamplerState(0, D3DSAMP_ADDRESSV, &addrV);
    device->GetSamplerState(0, D3DSAMP_MINFILTER, &minF);
    device->GetSamplerState(0, D3DSAMP_MAGFILTER, &magF);
    device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
    device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
    device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
    const float needle[3] = {0.85f, 0.22f, 0.10f};
    const float face[3] = {0.80f, 0.78f, 0.68f};
    const float rim[3] = {0.55f, 0.56f, 0.58f};
    const float glass[3] = {0.48f, 0.55f, 0.62f};
    const float glassLow[3] = {0.20f, 0.21f, 0.22f};   // the road in a mirror
    for (int m = 0; m < kMatCount; ++m) {
        std::vector<V>& t = b.tris[m];
        if (t.empty()) continue;
        for (V& q : t) {
            const Vec3 w{q.x * carToWorld.m[0][0] + q.y * carToWorld.m[1][0] + q.z * carToWorld.m[2][0] + carToWorld.m[3][0],
                         q.x * carToWorld.m[0][1] + q.y * carToWorld.m[1][1] + q.z * carToWorld.m[2][1] + carToWorld.m[3][1],
                         q.x * carToWorld.m[0][2] + q.y * carToWorld.m[1][2] + q.z * carToWorld.m[2][2] + carToWorld.m[3][2]};
            const Vec3 n = gta2::Normalize(Vec3{q.nx * carToWorld.m[0][0] + q.ny * carToWorld.m[1][0] + q.nz * carToWorld.m[2][0],
                                                q.nx * carToWorld.m[0][1] + q.ny * carToWorld.m[1][1] + q.nz * carToWorld.m[2][1],
                                                q.nx * carToWorld.m[0][2] + q.ny * carToWorld.m[1][2] + q.nz * carToWorld.m[2][2]});
            q = {w.x, w.y, w.z, n.x, n.y, n.z, q.u, q.v};
        }
        const float meter[3] = {0.95f, 0.18f, 0.10f};
        const float* c = m == kDash ? st.dash : m == kDashDark ? st.dashDark : m == kTrim ? st.trim : m == kHeader ? st.header
                       : m == kWheel ? st.wheel : m == kGaugeFace ? face : m == kGaugeRim ? rim : m == kNeedle ? needle
                       : m == kPanel ? st.panel : m == kMeter ? meter : m == kGlassLow ? glassLow : m == kLower ? st.lower : glass;
        D3DMATERIAL9 mat = restore;
        mat.Diffuse = {c[0], c[1], c[2], 1.0f};
        mat.Ambient = mat.Diffuse;
        mat.Specular = {0.0f, 0.0f, 0.0f, 0.0f};
        mat.Emissive = {0.0f, 0.0f, 0.0f, 0.0f};
        // Lit gauges at night; the mirrors' glass always gives back some of the sky.
        // FIX-FP-2 (pm30): the cab's own fill (light through the glass, off the seats): the faces
        // turned from the sun (the dash's face toward the driver, the door card) keep their shade
        // and texture instead of going black under the scene's ambient alone.
        {
            const float fill = p.night ? 0.10f : 0.22f;
            mat.Emissive = {c[0] * fill, c[1] * fill, c[2] * fill, 1.0f};
        }
        if (m == kGaugeFace && p.night) mat.Emissive = {0.45f, 0.40f, 0.28f, 1.0f};
        if (m == kNeedle && p.night) mat.Emissive = {0.6f, 0.15f, 0.05f, 1.0f};
        if (m == kGlassLow) mat.Emissive = {0.07f, 0.07f, 0.075f, 1.0f};
        if (m == kGlass) mat.Emissive = {0.22f, 0.25f, 0.30f, 1.0f};
        if (m == kMeter) mat.Emissive = {0.55f, 0.08f, 0.04f, 1.0f};   // the fare's red digits glow
        device->SetMaterial(&mat);
        static const int kKind[kMatCount] = {0, 1, 2, 3, 4, 5, 2, 15, 15, 1, 15, 15, 0};
        // A painted metal dash top (car, van, truck) is smooth: the plastic grain, not the vinyl.
        const bool paintedDash = m == kDash && (p.cls == CabClass::Car || p.cls == CabClass::Van || p.cls == CabClass::Truck);
        const int kind = paintedDash ? 1 : kKind[m];
        device->SetTexture(0, g_remixAlbedo ? SurfaceTextureTinted(device, kind, c) : SurfaceTexture(device, kind));
        device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(t.size() / 3), t.data(), sizeof(V));
    }
    device->SetTexture(0, nullptr);
    if (!p.warm && g_wheel.valid) {   // FIX-COCKPIT-BODY: the pedals for his feet (CabLastDriverPose)
        for (int k = 0; k < 2; ++k) {
            const Vec3& q = pedalAt[k];
            g_driver.pedal[k] = {q.x * carToWorld.m[0][0] + q.y * carToWorld.m[1][0] + q.z * carToWorld.m[2][0] + carToWorld.m[3][0],
                                 q.x * carToWorld.m[0][1] + q.y * carToWorld.m[1][1] + q.z * carToWorld.m[2][1] + carToWorld.m[3][1],
                                 q.x * carToWorld.m[0][2] + q.y * carToWorld.m[1][2] + q.z * carToWorld.m[2][2] + carToWorld.m[3][2]};
        }
    }
    DrawCabHands(device, carToWorld, p, restore);
    device->SetSamplerState(0, D3DSAMP_ADDRESSU, addrU);
    device->SetSamplerState(0, D3DSAMP_ADDRESSV, addrV);
    device->SetSamplerState(0, D3DSAMP_MINFILTER, minF);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, magF);
    device->SetMaterial(&restore);
    device->SetRenderState(D3DRS_CLIPPLANEENABLE, clip);
    device->SetRenderState(D3DRS_CULLMODE, cull);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, alphaTest);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
}

}  // namespace gta2dx9
