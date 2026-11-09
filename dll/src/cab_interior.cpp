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
enum Mat { kDash, kDashDark, kTrim, kHeader, kWheel, kGaugeFace, kGaugeRim, kNeedle, kGlass, kMatCount };

struct V { float x, y, z, nx, ny, nz; };

struct Builder {
    std::vector<V> tris[kMatCount];
    Vec3 eye;
    // A flat triangle, its normal turned toward the eye (everything here is seen from the seat).
    void Tri(int m, const Vec3& a, const Vec3& b, const Vec3& c) {
        Vec3 n = gta2::Normalize(gta2::Cross(b - a, c - a));
        const Vec3 centre = (a + b + c) * (1.0f / 3.0f);
        if (gta2::Dot(n, eye - centre) < 0.0f) n = n * -1.0f;
        tris[m].push_back({a.x, a.y, a.z, n.x, n.y, n.z});
        tris[m].push_back({b.x, b.y, b.z, n.x, n.y, n.z});
        tris[m].push_back({c.x, c.y, c.z, n.x, n.y, n.z});
    }
    void Quad(int m, const Vec3& a, const Vec3& b, const Vec3& c, const Vec3& d) { Tri(m, a, b, c); Tri(m, a, c, d); }
    // A disc about `c` in the plane of (u, v) (unit vectors).
    void Disc(int m, const Vec3& c, const Vec3& u, const Vec3& v, float r, int seg = 18) {
        for (int i = 0; i < seg; ++i) {
            const float a0 = 2.0f * kPi * i / seg, a1 = 2.0f * kPi * (i + 1) / seg;
            Tri(m, c, c + u * (r * std::cos(a0)) + v * (r * std::sin(a0)), c + u * (r * std::cos(a1)) + v * (r * std::sin(a1)));
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
                for (int k : order) tris[m].push_back({p[k].x, p[k].y, p[k].z, n[k].x, n[k].y, n[k].z});
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
    float dash[3], dashDark[3], trim[3], header[3], wheel[3];
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
        case CabClass::Car:
            // A dark vinyl top with a touch of the body colour (the painted metal dash of the old cars).
            for (int k = 0; k < 3; ++k) s.dash[k] = 0.16f + 0.22f * paint[k];
            set(s.dashDark, 0.07f, 0.07f, 0.08f);
            set(s.trim, 0.13f, 0.13f, 0.14f);
            set(s.header, 0.62f, 0.58f, 0.52f);
            set(s.wheel, 0.08f, 0.08f, 0.09f);
            s.wheelR = 0.019f; s.wheelRake = 25.0f * kPi / 180.0f; s.wheelTube = 0.0017f;
            s.binnacleHalf = 0.020f; s.gauges = 2;
            s.headerAngle = 30.0f; s.mirrorW = 0.024f; s.mirrorH = 0.0075f; s.sideMirrorH = 0.006f;
            break;
        case CabClass::Van:
            set(s.dash, 0.30f, 0.30f, 0.31f);
            set(s.dashDark, 0.10f, 0.10f, 0.11f);
            set(s.trim, 0.20f, 0.20f, 0.21f);
            set(s.header, 0.55f, 0.55f, 0.53f);
            set(s.wheel, 0.10f, 0.10f, 0.11f);
            s.wheelR = 0.021f; s.wheelRake = 38.0f * kPi / 180.0f; s.wheelTube = 0.0018f;
            s.binnacleHalf = 0.022f; s.gauges = 2;
            s.headerAngle = 29.5f; s.mirrorW = 0.026f; s.mirrorH = 0.008f; s.sideMirrorH = 0.009f;
            break;
        case CabClass::Truck:
            set(s.dash, 0.13f, 0.12f, 0.11f);
            set(s.dashDark, 0.05f, 0.05f, 0.05f);
            set(s.trim, 0.30f, 0.30f, 0.32f);
            set(s.header, 0.32f, 0.27f, 0.22f);
            set(s.wheel, 0.06f, 0.06f, 0.06f);
            s.wheelR = 0.025f; s.wheelRake = 55.0f * kPi / 180.0f; s.wheelTube = 0.0020f;
            s.binnacleHalf = 0.027f; s.gauges = 3;
            s.headerAngle = 29.0f; s.mirrorW = 0.026f; s.mirrorH = 0.008f; s.sideMirrorH = 0.016f;
            break;
        case CabClass::Bus:
            set(s.dash, 0.30f, 0.34f, 0.30f);
            set(s.dashDark, 0.09f, 0.10f, 0.09f);
            set(s.trim, 0.42f, 0.42f, 0.40f);
            set(s.header, 0.70f, 0.70f, 0.66f);
            set(s.wheel, 0.07f, 0.07f, 0.07f);
            s.wheelR = 0.028f; s.wheelRake = 62.0f * kPi / 180.0f; s.wheelTube = 0.0020f;
            s.binnacleHalf = 0.029f; s.gauges = 3;
            s.headerAngle = 28.5f; s.mirrorW = 0.034f; s.mirrorH = 0.009f; s.sideMirrorH = 0.018f;
            break;
    }
    return s;
}

}  // namespace

CabClass CabClassFor(int m, bool flatFront) {
    if (flatFront) return CabClass::Bus;
    switch (m) {
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

const char* CabClassName(CabClass c) {
    switch (c) {
        case CabClass::Car: return "car";
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
    // The dashboard's line: the hood copy's, under the cut a hand below the eye; a
    // bonnet far below the eye (a truck's) gets a dash no deeper than a hand and a half.
    const float top = (std::min)(ey - 0.043f, (std::max)(p.dashTop, ey - 0.075f));
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
        const float bw = st.binnacleHalf, xa = ex - bw, xb = ex + bw;
        const float dBack = dRear + 0.004f, dFront = dBack + 0.014f, dNose = dFront + 0.008f;
        const float hTop = 0.011f;
        b.Quad(kDashDark, P(xa, dBack, hTop), P(xb, dBack, hTop), P(xb, dFront, hTop), P(xa, dFront, hTop));      // cowl top
        b.Quad(kDashDark, P(xa, dFront, hTop), P(xb, dFront, hTop), P(xb, dNose, 0.003f), P(xa, dNose, 0.003f));  // its front slope
        b.Quad(kTrim, P(xa, dBack, hTop), P(xb, dBack, hTop), P(xb, dBack + 0.001f, hTop - 0.004f), P(xa, dBack + 0.001f, hTop - 0.004f));  // the lip
        for (float x : {xa, xb}) {
            b.Quad(kDashDark, P(x, dBack, hTop), P(x, dFront, hTop), P(x, dFront, 0.0f), P(x, dBack, 0.0f));
            b.Tri(kDashDark, P(x, dFront, hTop), P(x, dNose, 0.003f), P(x, dFront, 0.0f));
        }
        // The cluster's backplate and the gauges on it, facing the eye.
        const float dPlate = dBack + 0.008f;
        b.Quad(kDashDark, P(xa + 0.001f, dPlate, -0.002f), P(xb - 0.001f, dPlate, -0.002f), P(xb - 0.001f, dPlate, hTop - 0.001f), P(xa + 0.001f, dPlate, hTop - 0.001f));
        const Vec3 toEye = gta2::Normalize(b.eye - P(ex, dPlate, 0.006f));
        const Vec3 u = gta2::Normalize(gta2::Cross(Vec3{0.0f, 1.0f, 0.0f}, toEye));
        const Vec3 v = gta2::Normalize(gta2::Cross(toEye, u));
        const int n = st.gauges;
        const float r = (std::min)(0.0036f, (2.0f * bw - 0.004f) / (2.0f * n) * 0.8f);
        const float sp = (std::min)(1.0f, std::fabs(p.speed) / 9.0f);
        for (int i = 0; i < n; ++i) {
            const float gx = xa + 0.002f + (2.0f * bw - 0.004f) * (i + 0.5f) / n;
            const Vec3 c = P(gx, dPlate - 0.0003f, 0.0062f);
            b.Disc(kGaugeRim, c + toEye * 0.0001f, u, v, r * 1.15f);
            b.Disc(kGaugeFace, c + toEye * 0.0003f, u, v, r);
            // Speed on the big dial (the one nearest the middle), revs on the others, fuel steady.
            const bool speedo = i == n / 2 || (n == 2 && i == 1);
            float frac = speedo ? sp : (i == 0 ? (std::min)(1.0f, 0.18f + 0.7f * sp + 0.08f * std::sin(p.speed * 3.0f)) : 0.62f);
            const float a = (225.0f - 270.0f * frac) * kPi / 180.0f;
            const Vec3 dir = u * std::cos(a) + v * std::sin(a);
            const Vec3 base = c + toEye * 0.0005f;
            const Vec3 perp = u * -std::sin(a) + v * std::cos(a);
            b.Tri(kNeedle, base + perp * 0.0004f, base - perp * 0.0004f, base + dir * (r * 0.85f));
        }
    }
    // 3. The steering wheel, its rim's top just over the dash's rear edge; turned
    // with the front wheels (a few turns lock to lock).
    {
        const float R = st.wheelR, rake = st.wheelRake;
        const float dTop = dRear - 0.008f;
        const Vec3 rimTop = P(ex, dTop, 0.011f);
        const Vec3 up{0.0f, std::cos(rake), -std::sin(rake)};      // in the wheel's plane, toward its top
        const Vec3 axis{0.0f, std::sin(rake), std::cos(rake)};     // its column, away from the driver
        const Vec3 across{1.0f, 0.0f, 0.0f};
        const Vec3 c = rimTop - up * R;
        const float turn = (std::max)(-2.6f, (std::min)(2.6f, p.steer * 6.0f));
        const float cs = std::cos(turn), sn = std::sin(turn);
        const Vec3 u = across * cs + up * sn, v = up * cs - across * sn;
        b.Torus(kWheel, c, u, v, axis, R, st.wheelTube);
        // Three spokes (left, right, down) to a hub.
        for (float a : {0.0f, kPi, 1.5f * kPi}) {
            const Vec3 dir = u * std::cos(a) + v * std::sin(a);
            b.Bar(kWheel, c + dir * (0.24f * R) + axis * 0.0015f, c + dir * (R - st.wheelTube), st.wheelTube * 0.6f);
        }
        b.Disc(kTrim, c - axis * 0.0008f, u, v, 0.24f * R, 12);
    }
    // 4. The windscreen header across the top of the view and the rear-view mirror under it.
    const float tanH = std::tan(st.headerAngle * kPi / 180.0f);
    const float dH = dc + 0.02f, hHeader = tanH * dH;   // over the eye
    {
        const float hx0 = x0 - 0.06f, hx1 = x1 + 0.06f;
        const Vec3 a0{hx0, ey + hHeader, ez + dH}, a1{hx1, ey + hHeader, ez + dH};
        const Vec3 b0{hx0, ey + hHeader + 0.08f, ez + dH + 0.10f}, b1{hx1, ey + hHeader + 0.08f, ez + dH + 0.10f};
        b.Quad(kHeader, a0, a1, b1, b0);
        // A darker seal along its lower edge, where the glass meets it.
        b.Quad(kTrim, a0, a1, a1 + Vec3{0.0f, 0.004f, 0.005f}, a0 + Vec3{0.0f, 0.004f, 0.005f});
        // The mirror: toward the middle of the car, below the header.
        const float dM = dc + 0.04f;
        const Vec3 mc{ex * 0.50f, ey + tanH * dM * 0.72f, ez + dM};
        const Vec3 toEye = gta2::Normalize(b.eye - mc);
        const Vec3 mu = gta2::Normalize(gta2::Cross(Vec3{0.0f, 1.0f, 0.0f}, toEye));
        const Vec3 mv = gta2::Normalize(gta2::Cross(toEye, mu));
        const float w = 0.5f * st.mirrorW, h = 0.5f * st.mirrorH;
        b.Quad(kTrim, mc + mu * -w + mv * -h, mc + mu * w + mv * -h, mc + mu * w + mv * h, mc + mu * -w + mv * h);
        const float g = 0.0012f;
        const Vec3 gc = mc + toEye * 0.0006f;
        b.Quad(kGlass, gc + mu * (g - w) + mv * (g - h), gc + mu * (w - g) + mv * (g - h), gc + mu * (w - g) + mv * (h - g), gc + mu * (g - w) + mv * (h - g));
        const Vec3 mount{mc.x, ey + tanH * (dH + 0.012f) + 0.010f, ez + dH + 0.012f};
        b.Bar(kTrim, mc + mv * h - toEye * 0.001f, mount, 0.0010f);
    }
    // 5. The A-pillar on the driver's side, from the dash's corner to the header,
    // and the door mirror beyond it.
    {
        const float reach = (std::min)(std::fabs((side > 0 ? x1 : x0) - ex), 0.105f);
        const float px = ex + side * reach, w = 0.009f;
        const Vec3 f0{px, top, ez + dc}, f1{px + side * w, top, ez + dc + 0.004f};
        const Vec3 t0{px - side * 0.002f, ey + hHeader + 0.002f, ez + dH}, t1{px + side * (w - 0.002f), ey + hHeader + 0.002f, ez + dH + 0.004f};
        b.Quad(kTrim, f0, f1, t1, t0);
        // The door mirror: on an arm out past the pillar, its glass turned toward the eye.
        const bool tall = p.cls == CabClass::Truck || p.cls == CabClass::Bus;
        const float dSM = tall ? dc + 0.08f : dc + 0.035f;
        const float mx = ex + side * (reach + (tall ? 0.020f : 0.013f));
        const Vec3 mc{mx, top + (tall ? 0.012f : 0.005f), ez + dSM};
        const Vec3 toEye = gta2::Normalize(b.eye - mc);
        const Vec3 mu = gta2::Normalize(gta2::Cross(Vec3{0.0f, 1.0f, 0.0f}, toEye));
        const Vec3 mv = gta2::Normalize(gta2::Cross(toEye, mu));
        const float w2 = tall ? 0.005f : 0.006f, h2 = 0.5f * st.sideMirrorH;
        b.Quad(kTrim, mc + mu * -w2 + mv * -h2, mc + mu * w2 + mv * -h2, mc + mu * w2 + mv * h2, mc + mu * -w2 + mv * h2);
        const Vec3 gc = mc + toEye * 0.001f;
        const float g = 0.0008f;
        b.Quad(kGlass, gc + mu * (g - w2) + mv * (g - h2), gc + mu * (w2 - g) + mv * (g - h2), gc + mu * (w2 - g) + mv * (h2 - g), gc + mu * (g - w2) + mv * (h2 - g));
        const Vec3 arm0{px + side * w * 0.5f, top + 0.006f, ez + dc + 0.006f};
        b.Bar(kTrim, arm0, mc - mv * (h2 * 0.5f), 0.0009f);
        if (tall) b.Bar(kTrim, Vec3{arm0.x, top + 0.024f, arm0.z + 0.003f}, mc + mv * (h2 * 0.5f), 0.0008f);
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
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    device->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL);
    const float needle[3] = {0.85f, 0.22f, 0.10f};
    const float face[3] = {0.80f, 0.78f, 0.68f};
    const float rim[3] = {0.55f, 0.56f, 0.58f};
    const float glass[3] = {0.48f, 0.55f, 0.62f};
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
            q = {w.x, w.y, w.z, n.x, n.y, n.z};
        }
        const float* c = m == kDash ? st.dash : m == kDashDark ? st.dashDark : m == kTrim ? st.trim : m == kHeader ? st.header
                       : m == kWheel ? st.wheel : m == kGaugeFace ? face : m == kGaugeRim ? rim : m == kNeedle ? needle : glass;
        D3DMATERIAL9 mat = restore;
        mat.Diffuse = {c[0], c[1], c[2], 1.0f};
        mat.Ambient = mat.Diffuse;
        mat.Specular = {0.0f, 0.0f, 0.0f, 0.0f};
        mat.Emissive = {0.0f, 0.0f, 0.0f, 0.0f};
        // Lit gauges at night; the mirrors' glass always gives back some of the sky.
        if (m == kGaugeFace && p.night) mat.Emissive = {0.45f, 0.40f, 0.28f, 1.0f};
        if (m == kNeedle && p.night) mat.Emissive = {0.6f, 0.15f, 0.05f, 1.0f};
        if (m == kGlass) mat.Emissive = {0.22f, 0.25f, 0.30f, 1.0f};
        device->SetMaterial(&mat);
        device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(t.size() / 3), t.data(), sizeof(V));
    }
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
