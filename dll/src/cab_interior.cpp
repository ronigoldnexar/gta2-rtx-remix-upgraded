// QB-31: the cab seen from the driver's seat, per vehicle class (see cab_interior.h).
#include "cab_interior.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

namespace gta2dx9 {
namespace {

using gta2::Vec3;

constexpr float kPi = 3.14159265f;

// The parts by surface: each is one draw with its own material.
enum Mat { kDash, kDashDark, kTrim, kHeader, kWheel, kGaugeFace, kGaugeRim, kNeedle, kGlass, kPanel, kMeter, kGlassLow, kMatCount };

struct V { float x, y, z, nx, ny, nz, u, v; };

// FIX-FIGURE (pm2-fp-cockpit-flat-untextured-placeholder-boxes): a texture per surface,
// made here (no art files): vinyl grain on the dash, fine-grained plastic, brushed
// trim, headliner cloth, a stitched leather wheel, gauge faces with a tick ring.
// Planar UVs from the car-frame position (a tile every kUvTile blocks), so the
// grain stays put on the dash; discs and the wheel's torus map their own.
constexpr float kUvTile = 0.025f;
IDirect3DDevice9* g_texDevice = nullptr;
IDirect3DTexture9* g_tex[16] = {};

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
            return 0.62f + 0.55f * g;
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
    float dash[3], dashDark[3], trim[3], header[3], wheel[3], panel[3];
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
    // The centre stack and the glovebox lid: the dash's dark shade lifted toward the trim.
    for (int k = 0; k < 3; ++k) s.panel[k] = 0.6f * s.dashDark[k] + 0.4f * s.trim[k];
    return s;
}

}  // namespace

void CabInteriorReleaseDevice() {
    for (IDirect3DTexture9*& t : g_tex) { if (t) t->Release(); t = nullptr; }
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
bool CabOpenTop(int m) {
    return m == 22 || m == 30 || m == 31 || m == 39 || m == 45 || m == 53;
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

void DrawCabInterior(IDirect3DDevice9* device, const gta2::Mat4& carToWorld, const CabInteriorParams& p,
                     const D3DMATERIAL9& restore) {
    const Style st = StyleFor(p.cls, p.paint);
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

    // 1. The dashboard: from the windscreen's foot up to a crest, back to a rolled
    // edge toward the driver, then down (out of view under the wheel).
    const float dCrest = dc - 0.018f, dRear = dc - 0.036f;
    const float hCrest = p.cls == CabClass::Car ? 0.004f : 0.006f;
    b.Quad(kDash, P(x0, dc + 0.004f, 0.0f), P(x1, dc + 0.004f, 0.0f), P(x1, dCrest, hCrest), P(x0, dCrest, hCrest));
    b.Quad(kDash, P(x0, dCrest, hCrest), P(x1, dCrest, hCrest), P(x1, dRear, 0.002f), P(x0, dRear, 0.002f));
    b.Quad(kDashDark, P(x0, dRear, 0.002f), P(x1, dRear, 0.002f), P(x1, dRear - 0.006f, -0.012f), P(x0, dRear - 0.006f, -0.012f));
    b.Quad(kDashDark, P(x0, dRear - 0.006f, -0.012f), P(x1, dRear - 0.006f, -0.012f), P(x1, dRear - 0.008f, -0.08f), P(x0, dRear - 0.008f, -0.08f));
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
    // 2. The binnacle in front of the driver: a cowl over the gauges.
    {
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
    // with the front wheels (a few turns lock to lock).
    {
        const float R = st.wheelR, rake = st.wheelRake;
        const float dTop = dRear - 0.008f;
        // FIX-FIGURE: the rim's top higher than QB-31's 0.011 (the hub and spokes sat
        // under the bottom of the view; only an arc showed): the gauges seen through
        // the wheel's upper half, the hub just over the dash's rear edge.
        const Vec3 rimTop = P(ex, dTop, 0.011f + 0.6f * R);
        const Vec3 up{0.0f, std::cos(rake), -std::sin(rake)};      // in the wheel's plane, toward its top
        const Vec3 axis{0.0f, std::sin(rake), std::cos(rake)};     // its column, away from the driver
        const Vec3 across{1.0f, 0.0f, 0.0f};
        const Vec3 c = rimTop - up * R;
        const float turn = (std::max)(-2.6f, (std::min)(2.6f, p.steer * 6.0f));
        const float cs = std::cos(turn), sn = std::sin(turn);
        const Vec3 u = across * cs + up * sn, v = up * cs - across * sn;
        b.Torus(kWheel, c, u, v, axis, R, st.wheelTube);
        // Three spokes (left and right, a little drooped, and down) to a hub with a horn pad.
        for (float a : {-0.22f, kPi + 0.22f, 1.5f * kPi}) {
            const Vec3 dir = u * std::cos(a) + v * std::sin(a);
            b.Bar(kGaugeRim, c + dir * (0.28f * R) + axis * 0.0015f, c + dir * (R - st.wheelTube), st.wheelTube * 0.40f);
        }
        b.Disc(kWheel, c - axis * 0.0006f, u, v, 0.34f * R, 16);
        b.Disc(kTrim, c - axis * 0.0010f, u, v, 0.12f * R, 10);
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
    const float dH = dc + 0.02f, hHeader = tanH * dH;   // over the eye
    {
        const float hx0 = x0 - 0.40f, hx1 = x1 + 0.40f;
        const Vec3 a0{hx0, ey + hHeader, ez + dH}, a1{hx1, ey + hHeader, ez + dH};
        const float roofUp = p.openTop ? 0.0090f : 0.08f, roofFwd = p.openTop ? 0.0112f : 0.10f;   // the lining's, or the rail's, depth
        const Vec3 b0{hx0, ey + hHeader + roofUp, ez + dH + roofFwd}, b1{hx1, ey + hHeader + roofUp, ez + dH + roofFwd};
        b.Quad(p.openTop ? kTrim : kHeader, a0, a1, b1, b0);
        // A darker seal along its lower edge, where the glass meets it.
        b.Quad(kTrim, a0, a1, a1 + Vec3{0.0f, 0.004f, 0.005f}, a0 + Vec3{0.0f, 0.004f, 0.005f});
        // The mirror: at the middle of the windscreen (the car's centre line), hung from the header.
        const float w = 0.5f * st.mirrorW, h = 0.5f * st.mirrorH;
        const float dMount = dH + 0.006f;
        // The seat is compressed (the pillars stand a hand either side of the eye), so the car's
        // centre line is off to one side of the view; the mirror takes the middle between the pillars.
        const float pxA = ex + side * (std::min)(std::fabs((side > 0 ? x1 : x0) - ex), 0.105f);
        const float pxB = ex - side * (std::min)(std::fabs((side > 0 ? x0 : x1) - ex), 0.95f * dc);
        const float mirX = 0.5f * (pxA + pxB);
        const Vec3 mount{mirX, ey + tanH * dMount + 0.0006f, ez + dMount};
        const Vec3 mc = mount + Vec3{0.0f, -(h + 0.0075f), 0.0045f};
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
                       : m == kPanel ? st.panel : m == kMeter ? meter : m == kGlassLow ? glassLow : glass;
        D3DMATERIAL9 mat = restore;
        mat.Diffuse = {c[0], c[1], c[2], 1.0f};
        mat.Ambient = mat.Diffuse;
        mat.Specular = {0.0f, 0.0f, 0.0f, 0.0f};
        mat.Emissive = {0.0f, 0.0f, 0.0f, 0.0f};
        // Lit gauges at night; the mirrors' glass always gives back some of the sky.
        if (m == kGaugeFace && p.night) mat.Emissive = {0.45f, 0.40f, 0.28f, 1.0f};
        if (m == kNeedle && p.night) mat.Emissive = {0.6f, 0.15f, 0.05f, 1.0f};
        if (m == kGlassLow) mat.Emissive = {0.07f, 0.07f, 0.075f, 1.0f};
        if (m == kGlass) mat.Emissive = {0.22f, 0.25f, 0.30f, 1.0f};
        if (m == kMeter) mat.Emissive = {0.55f, 0.08f, 0.04f, 1.0f};   // the fare's red digits glow
        device->SetMaterial(&mat);
        static const int kKind[kMatCount] = {0, 1, 2, 3, 4, 5, 2, 15, 15, 1, 15, 15};
        device->SetTexture(0, SurfaceTexture(device, kKind[m]));
        device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(t.size() / 3), t.data(), sizeof(V));
    }
    device->SetTexture(0, nullptr);
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
