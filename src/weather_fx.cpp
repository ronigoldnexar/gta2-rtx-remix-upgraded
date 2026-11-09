// See weather_fx.h and docs/weather.md.
#include "weather_fx.h"

#include <algorithm>
#include <cmath>
#include <cstdint>

#include "renderer.h"
#include "sky.h"

namespace gta2 {

void RendererTrace(const char* format, ...);   // renderer.cpp

namespace {

WeatherState g_now;
WeatherPollFn g_poll = nullptr;
Vec3 g_eye{128.0f, 3.0f, 128.0f};
float g_fogHere = 0.0f;     // this frame's fog at the eye (the bank noise applied)
float g_overcast = 0.0f;
float g_blend = 0.0f;      // the view transition's weight, from the shading

float Clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }
Vec3 Lerp(const Vec3& a, const Vec3& b, float t) { return a + (b - a) * t; }
float Luma(const Vec3& c) { return 0.30f * c.x + 0.59f * c.y + 0.11f * c.z; }
// Towards a cool grey of the same brightness: what cloud does to a colour.
Vec3 Grey(const Vec3& c, float k) {
    const float l = Luma(c);
    return Lerp(c, Vec3{l * 0.96f, l * 0.99f, l * 1.05f}, Clamp01(k));
}

uint32_t Hash(uint32_t x) {
    x ^= x >> 16; x *= 0x7feb352du; x ^= x >> 15; x *= 0x846ca68bu; x ^= x >> 16;
    return x;
}
float Hash01(uint32_t x) { return static_cast<float>(Hash(x) & 0xFFFFFF) / 16777215.0f; }

// Smooth value noise on a 2D lattice, for where the fog banks lie.
float Noise2(float x, float y) {
    const float fx = std::floor(x), fy = std::floor(y);
    const int ix = static_cast<int>(fx), iy = static_cast<int>(fy);
    float tx = x - fx, ty = y - fy;
    tx = tx * tx * (3.0f - 2.0f * tx); ty = ty * ty * (3.0f - 2.0f * ty);
    auto h = [](int a, int b) { return Hash01(static_cast<uint32_t>(a) * 73856093u ^ static_cast<uint32_t>(b) * 19349663u); };
    const float a = h(ix, iy), b = h(ix + 1, iy), c = h(ix, iy + 1), d = h(ix + 1, iy + 1);
    return (a + (b - a) * tx) * (1.0f - ty) + (c + (d - c) * tx) * ty;
}

// The fog colour under this weather: the sky's haze greyed by the cloud, darker in rain.
Vec3 FogTint(const Vec3& fog) {
    const float k = std::max(g_overcast * 0.75f, g_fogHere * 0.85f);
    return Grey(fog, k) * (1.0f - 0.18f * g_now.rain);
}

template <typename T> void SafeRelease(T*& p) { if (p) { p->Release(); p = nullptr; } }

}  // namespace

WeatherState& WeatherNow() { return g_now; }
void SetWeatherPoll(WeatherPollFn fn) { g_poll = fn; }
void WeatherPoll() { if (g_poll) g_poll(); }

void WeatherAdjustShading(WorldShading* s, float blend) {
    if (!s || !s->fog) return;
    g_blend = Clamp01(blend);
    if (!g_now.active) { g_fogHere = 0.0f; g_overcast = 0.0f; return; }
    const WorldShading before = *s;
    // Fog banks: the fog thickens and thins as the eye moves through the city and as
    // the banks drift (a slow noise over the map, ~40 blocks across).
    const float drift = static_cast<float>(g_now.seconds * 0.02);
    const float bank = Noise2(g_eye.x / 40.0f + drift * g_now.windDir[0], g_eye.z / 40.0f + drift * g_now.windDir[1]);
    g_fogHere = Clamp01(g_now.fog * (0.45f + 0.9f * bank));
    g_overcast = Clamp01(std::max(g_now.cloud, std::max(g_now.rain * 0.9f, g_fogHere * 0.6f)));
    const float oc = g_overcast, rain = g_now.rain, fog = g_fogHere;

    // The sun goes behind the cloud; the sky's diffuse light partly makes up for it.
    s->sunColour = s->sunColour * (1.0f - 0.85f * oc);
    s->ambient = Grey(s->ambient, 0.5f * oc) * (1.0f + 0.10f * oc - 0.16f * rain);
    s->fogColour = FogTint(s->fogColour);
    // The haze pulled in: a fog bank leaves a few blocks of street, rain a few dozen.
    float start = s->fogStart, end = s->fogEnd;
    start = start + (1.5f - start) * fog;
    end = end + (16.0f - end) * fog;
    start *= 1.0f - 0.5f * rain;
    end = end + (std::max(start + 6.0f, end * 0.55f) - end) * rain;
    s->fogStart = start;
    s->fogEnd = std::max(end, start + 4.0f);
    // Eased in with the view transition, like the sky.
    s->sunColour = Lerp(before.sunColour, s->sunColour, g_blend);
    s->ambient = Lerp(before.ambient, s->ambient, g_blend);
    s->fogColour = Lerp(before.fogColour, s->fogColour, g_blend);
    s->fogStart = before.fogStart + (s->fogStart - before.fogStart) * g_blend;
    s->fogEnd = before.fogEnd + (s->fogEnd - before.fogEnd) * g_blend;
}

void WeatherAdjustSky(SkyColours* c, SkySettings* settings) {
    if (!c || !g_now.active) return;
    const float oc = g_overcast, rain = g_now.rain;
    c->zenith = Grey(c->zenith, 0.85f * oc) * (1.0f - 0.30f * rain);
    c->horizon = Grey(c->horizon, 0.70f * oc) * (1.0f - 0.18f * rain);
    c->fog = FogTint(c->fog);
    // In a fog bank the whole dome is the fog.
    c->horizon = Lerp(c->horizon, c->fog, g_fogHere);
    c->zenith = Lerp(c->zenith, c->fog, g_fogHere * 0.8f);
    c->sunColour = c->sunColour * (1.0f - 0.92f * oc);
    c->ambient = Grey(c->ambient, 0.5f * oc);
    if (settings) settings->cloudCover = std::max(settings->cloudCover, oc);
}

void WeatherFx::Init(IDirect3DDevice9* device, bool remix) {
    if (device_ != device) Release();
    device_ = device;
    remix_ = remix;
}

void WeatherFx::Release() {
    SafeRelease(puddles_);
    SafeRelease(saved_);
    device_ = nullptr;
    haveCamera_ = false;
}

void WeatherFx::SetCamera(const Mat4& view, const Mat4& proj, const Vec3& eye) {
    view_ = view;
    proj_ = proj;
    eye_ = eye;
    g_eye = eye;
    haveCamera_ = true;
}

IDirect3DTexture9* WeatherFx::Puddles() {
    if (puddles_ || !device_ || remix_) return puddles_;
    // 256 px of tiling value noise, four octaves; the wet pass thresholds it into
    // puddles (one texel ~ 1/8 block at the shader's scale of 1/32 per block).
    constexpr int n = 256;
    std::vector<float> h(static_cast<size_t>(n) * n, 0.0f);
    for (int o = 0; o < 4; ++o) {
        const int cells = 4 << o;
        const float amp = 1.0f / static_cast<float>(1 << o);
        for (int y = 0; y < n; ++y) {
            for (int x = 0; x < n; ++x) {
                const float fx = static_cast<float>(x) * cells / n, fy = static_cast<float>(y) * cells / n;
                const int x0 = static_cast<int>(fx) % cells, y0 = static_cast<int>(fy) % cells;
                const int x1 = (x0 + 1) % cells, y1 = (y0 + 1) % cells;
                float tx = fx - std::floor(fx), ty = fy - std::floor(fy);
                tx = tx * tx * (3.0f - 2.0f * tx); ty = ty * ty * (3.0f - 2.0f * ty);
                auto l = [&](int a, int b) { return Hash01(static_cast<uint32_t>(o * 7919 + b * cells + a) * 2654435761u); };
                h[static_cast<size_t>(y) * n + x] += amp * ((l(x0, y0) + (l(x1, y0) - l(x0, y0)) * tx) * (1.0f - ty) +
                                                            (l(x0, y1) + (l(x1, y1) - l(x0, y1)) * tx) * ty);
            }
        }
    }
    float lo = 1e9f, hi = -1e9f;
    for (float f : h) { lo = std::min(lo, f); hi = std::max(hi, f); }
    if (FAILED(device_->CreateTexture(n, n, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &puddles_, nullptr))) {
        puddles_ = nullptr;
        return nullptr;
    }
    D3DLOCKED_RECT r;
    if (SUCCEEDED(puddles_->LockRect(0, &r, nullptr, 0))) {
        for (int y = 0; y < n; ++y) {
            DWORD* row = reinterpret_cast<DWORD*>(static_cast<uint8_t*>(r.pBits) + y * r.Pitch);
            for (int x = 0; x < n; ++x) {
                const int v = static_cast<int>((h[static_cast<size_t>(y) * n + x] - lo) / std::max(hi - lo, 1e-6f) * 255.0f + 0.5f);
                // r: the puddle field; g: the same field shifted (ripple distortion's second axis).
                const int g = static_cast<int>((h[static_cast<size_t>((y + 97) % n) * n + (x + 41) % n] - lo) / std::max(hi - lo, 1e-6f) * 255.0f + 0.5f);
                row[x] = D3DCOLOR_ARGB(255, v, g, v);
            }
        }
        puddles_->UnlockRect(0);
    }
    RendererTrace("weather: puddle map built (%d px)", n);
    return puddles_;
}

void WeatherFx::DrawRain(const WorldShading& shading) {
    const WeatherState& w = g_now;
    if (!device_ || remix_ || !haveCamera_ || !w.active || !w.streaks || w.rain < 0.02f || !shading.fog || g_blend < 0.02f) return;
    const int count = std::max(0, std::min(6000, static_cast<int>(static_cast<float>(w.drops) * w.rain)));
    if (count == 0) return;

    // The box the drops live in, around the eye; they keep their place in the world
    // (wrapped into the box), so walking through the rain passes them.
    const float R = 9.0f, H = 7.0f;
    const float speed = 7.5f;                        // blocks per second
    const float t = static_cast<float>(std::fmod(w.seconds, 3600.0));
    const float windX = w.windDir[0] * w.wind * 3.5f, windZ = w.windDir[1] * w.wind * 3.5f;
    Vec3 dir = Normalize(Vec3{windX, -speed, windZ});
    const float len = 0.42f + 0.25f * w.wind;
    // Lit by the scene's light, never brighter than the street at night.
    const float light = std::min(1.1f, std::max(0.22f, (shading.ambient.x + shading.ambient.y + shading.ambient.z) / 3.0f +
                                                          0.5f * (shading.sunColour.x + shading.sunColour.y + shading.sunColour.z) / 3.0f));
    const Vec3 tint = Vec3{0.78f, 0.81f, 0.86f} * light;
    auto wrap = [](float v, float L) { return v - L * std::floor(v / L + 0.5f); };

    verts_.clear();
    verts_.reserve(static_cast<size_t>(count) * 6);
    for (int i = 0; i < count; ++i) {
        const uint32_t s = static_cast<uint32_t>(i) * 3u;
        const float sp = speed * (0.85f + 0.3f * Hash01(s + 2));
        const float fall = std::fmod(Hash01(s + 1) * H + t * sp, H);
        const float bx = Hash01(s) * 2.0f * R + windX * t * 0.8f;
        const float bz = Hash01(s + 7777u) * 2.0f * R + windZ * t * 0.8f;
        Vec3 p{eye_.x + wrap(bx - eye_.x, 2.0f * R), eye_.y + H * 0.5f - fall, eye_.z + wrap(bz - eye_.z, 2.0f * R)};
        const Vec3 toEye = p - eye_;
        const float dist = std::sqrt(Dot(toEye, toEye));
        if (dist < 0.35f) continue;
        // Fewer, fainter streaks at the box's edge and right in front of the eye.
        const float fade = Clamp01((R - dist) / 3.0f) * Clamp01((dist - 0.35f) / 0.8f);
        if (fade <= 0.01f) continue;
        const Vec3 top = p - dir * (len * (0.8f + 0.4f * Hash01(s + 5)));
        Vec3 side = Cross(dir, toEye);
        const float sl = std::sqrt(Dot(side, side));
        if (sl < 1e-4f) continue;
        side = side * (std::max(0.006f, dist * 0.0019f) / sl);
        const float a = (0.20f + 0.16f * w.rain) * fade * g_blend;
        const DWORD cBottom = D3DCOLOR_ARGB(static_cast<int>(a * 255.0f), static_cast<int>(std::min(1.0f, tint.x) * 255.0f),
                                            static_cast<int>(std::min(1.0f, tint.y) * 255.0f), static_cast<int>(std::min(1.0f, tint.z) * 255.0f));
        const DWORD cTop = cBottom & 0x00FFFFFFu;   // the tail fades out
        const RainVertex v0{p.x - side.x, p.y - side.y, p.z - side.z, cBottom};
        const RainVertex v1{p.x + side.x, p.y + side.y, p.z + side.z, cBottom};
        const RainVertex v2{top.x - side.x, top.y - side.y, top.z - side.z, cTop};
        const RainVertex v3{top.x + side.x, top.y + side.y, top.z + side.z, cTop};
        verts_.push_back(v0); verts_.push_back(v1); verts_.push_back(v2);
        verts_.push_back(v2); verts_.push_back(v1); verts_.push_back(v3);
    }
    if (verts_.empty()) return;

    if (!saved_ && FAILED(device_->CreateStateBlock(D3DSBT_ALL, &saved_))) saved_ = nullptr;
    if (saved_) saved_->Capture();
    device_->SetVertexShader(nullptr);
    device_->SetPixelShader(nullptr);
    device_->SetFVF(D3DFVF_XYZ | D3DFVF_DIFFUSE);
    const Mat4 identity = Identity();
    device_->SetTransform(D3DTS_WORLD, reinterpret_cast<const D3DMATRIX*>(&identity));
    device_->SetTransform(D3DTS_VIEW, reinterpret_cast<const D3DMATRIX*>(&view_));
    device_->SetTransform(D3DTS_PROJECTION, reinterpret_cast<const D3DMATRIX*>(&proj_));
    device_->SetRenderState(D3DRS_LIGHTING, FALSE);
    device_->SetRenderState(D3DRS_ZENABLE, D3DZB_TRUE);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device_->SetRenderState(D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    device_->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device_->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device_->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device_->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device_->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device_->SetRenderState(D3DRS_BLENDOP, D3DBLENDOP_ADD);
    device_->SetTexture(0, nullptr);
    device_->SetTexture(1, nullptr);
    device_->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device_->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    device_->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device_->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    device_->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device_->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    device_->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(verts_.size() / 3), verts_.data(), sizeof(RainVertex));
    if (saved_) saved_->Apply();
}

}  // namespace gta2
