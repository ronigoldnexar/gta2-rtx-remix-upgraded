// See weather_fx.h and docs/weather.md.
#include "weather_fx.h"
#include <cstring>
#include "post_fx.h"

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
float g_blend = 0.0f;
gta2::WeatherCoverFn g_cover = nullptr;
std::vector<gta2::ScreenRainLight> g_srLights;      // the view transition's weight, from the shading

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
    g_fogHere = Clamp01(g_now.fog * (0.70f + 0.60f * bank));
    g_overcast = Clamp01(std::max(g_now.cloud, std::max(g_now.rain * 0.9f, g_fogHere * 0.6f)));
    const float oc = g_overcast, rain = g_now.rain, fog = g_fogHere;

    // The sun goes behind the cloud; the sky's diffuse light partly makes up for it.
    s->sunColour = s->sunColour * (1.0f - 0.85f * oc);
    s->ambient = Grey(s->ambient, 0.5f * oc) * (1.0f + 0.10f * oc - 0.16f * rain);
    s->fogColour = FogTint(s->fogColour);
    // The haze pulled in: a fog bank leaves a few blocks of street, rain a few dozen.
    float start = s->fogStart, end = s->fogEnd;
    // Eased so that a moderate fog already closes the view in (fog 0.5 -> end ~40 blocks).
    const float fe = 1.0f - (1.0f - fog) * (1.0f - fog);
    start = start + (1.0f - start) * fe;
    end = end + (12.0f - end) * fe;
    start *= 1.0f - 0.5f * rain;
    end = end + (std::max(start + 6.0f, end * 0.55f) - end) * rain;
    s->fogStart = start;
    s->fogEnd = std::max(end, start + 4.0f);
    // WEATHER-V2 phase 2: lightning lights the street from the sky (cool white), and the fog with it.
    if (g_now.flash > 0.0f) {
        const float f = std::min(1.5f, g_now.flash);
        s->ambient = s->ambient + Vec3{0.50f, 0.54f, 0.62f} * f;
        s->fogColour = s->fogColour + Vec3{0.30f, 0.32f, 0.38f} * f;
    }
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
    // A cloud deck is grey, not white: the dome darkens with the cover as well as greying.
    c->zenith = Grey(c->zenith, 0.85f * oc) * (1.0f - 0.22f * oc - 0.25f * rain);
    c->horizon = Grey(c->horizon, 0.70f * oc) * (1.0f - 0.12f * oc - 0.15f * rain);
    c->fog = FogTint(c->fog);
    // In a fog bank the whole dome is the fog.
    c->horizon = Lerp(c->horizon, c->fog, g_fogHere);
    c->zenith = Lerp(c->zenith, c->fog, g_fogHere * 0.8f);
    c->sunColour = c->sunColour * (1.0f - 0.92f * oc);
    c->ambient = Grey(c->ambient, 0.5f * oc);
    if (g_now.flash > 0.0f) {   // WEATHER-V2 phase 2: the cloud deck lit from inside
        const float f = std::min(1.0f, g_now.flash * 0.8f);
        c->zenith = Lerp(c->zenith, Vec3{0.78f, 0.80f, 0.90f}, f);
        c->horizon = Lerp(c->horizon, Vec3{0.70f, 0.72f, 0.82f}, f * 0.8f);
        c->fog = Lerp(c->fog, Vec3{0.60f, 0.62f, 0.70f}, f * 0.6f);
    }
    if (settings) {
        settings->cloudCover = std::max(settings->cloudCover, oc);
        settings->cloudShade = Clamp01(0.6f * oc + 0.4f * rain);
    }
}

void WeatherFx::Init(IDirect3DDevice9* device, bool remix) {
    if (device_ != device) Release();
    device_ = device;
    remix_ = remix;
}

void WeatherFx::Release() {
    if (dropTex_) { dropTex_->Release(); dropTex_ = nullptr; }
    if (dropMask_) { dropMask_->Release(); dropMask_ = nullptr; }
    if (sceneCopy_) { sceneCopy_->Release(); sceneCopy_ = nullptr; }
    for (auto& t : remixRain_) { if (t) { t->Release(); t = nullptr; } }
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

IDirect3DTexture9* WeatherFx::PuddleField() {
    if (fieldSize_ > 0 && !fieldTex_ && device_ && !remix_) {
        if (SUCCEEDED(device_->CreateTexture(fieldSize_, fieldSize_, 1, 0, D3DFMT_L8, D3DPOOL_MANAGED, &fieldTex_, nullptr))) {
            D3DLOCKED_RECT lr;
            if (SUCCEEDED(fieldTex_->LockRect(0, &lr, nullptr, 0))) {
                for (int y = 0; y < fieldSize_; ++y)
                    memcpy(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch, &field_[static_cast<size_t>(y) * fieldSize_], fieldSize_);
                fieldTex_->UnlockRect(0);
            }
            RendererTrace("weather: puddle field %dx%d (whole map, same as Remix)", fieldSize_, fieldSize_);
        } else {
            fieldTex_ = nullptr;
        }
    }
    return fieldTex_;
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
    if (device_ && remix_ && w.remixStreaks && haveCamera_ && w.active && w.streaks && w.rain >= 0.02f && g_blend >= 0.02f) { DrawRainRemix(w); return; }
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
    const float len = 0.55f + 0.25f * w.wind;
    // Lit by the scene's light, never brighter than the street at night.
    const float light = std::min(1.1f, std::max(0.22f, (shading.ambient.x + shading.ambient.y + shading.ambient.z) / 3.0f +
                                                          0.5f * (shading.sunColour.x + shading.sunColour.y + shading.sunColour.z) / 3.0f));
    // Brighter than the air behind them: a streak is light caught by a falling drop.
    // Night (trailer dry run 13 Nov: "a white curtain"): away from the lamps the streaks are barely there - the floor
    // of 0.22 read as grey on the near-black street - and the lamps and head lamps carry them (below).
    const float nightK = Clamp01(w.night);
    const Vec3 tint = Vec3{0.80f, 0.84f, 0.90f} * (light * (1.25f - 0.45f * nightK) + 0.08f * (1.0f - nightK));
    auto wrap = [](float v, float L) { return v - L * std::floor(v / L + 0.5f); };

    // The night lights within the rain box's reach (at most 16, nearest first).
    std::vector<const VisualLight*> nearL;
    if (lights_) {
        std::vector<std::pair<float, const VisualLight*>> c;
        for (const VisualLight& L : *lights_) {
            if (L.intensity <= 0.01f) continue;
            const float dx = L.pos[0] - eye_.x, dy = L.pos[1] - eye_.y, dz = L.pos[2] - eye_.z;
            const float d = std::sqrt(dx * dx + dy * dy + dz * dz);
            if (d < R + L.radius) c.push_back({d, &L});
        }
        std::sort(c.begin(), c.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
        for (size_t i = 0; i < c.size() && i < 16; ++i) nearL.push_back(c[i].second);
    }
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
        if (WeatherCovered(p.x, p.y, p.z)) continue;
        // Fewer, fainter streaks at the box's edge and right in front of the eye.
        const float fade = Clamp01((R - dist) / 3.0f) * Clamp01((dist - 0.35f) / 0.8f);
        if (fade <= 0.01f) continue;
        const Vec3 top = p - dir * (len * (0.8f + 0.4f * Hash01(s + 5)));
        Vec3 side = Cross(dir, toEye);
        const float sl = std::sqrt(Dot(side, side));
        if (sl < 1e-4f) continue;
        side = side * (std::max(0.009f, dist * 0.0030f) / sl);
        float a = (0.30f + 0.25f * w.rain) * fade * g_blend * (1.0f - 0.45f * nightK);
        // Light caught from the nearest night lights (lamps, head lamps), by distance and the beam's cone.
        Vec3 lit{0.0f, 0.0f, 0.0f};
        if (nearL.size()) {
            for (const VisualLight* L : nearL) {
                const Vec3 d{p.x - L->pos[0], p.y - L->pos[1], p.z - L->pos[2]};
                const float dd = std::sqrt(Dot(d, d));
                const float r = std::max(0.5f, L->radius);
                if (dd > r) continue;
                float k = (1.0f - dd / r); k *= k;
                if (L->spot && dd > 1e-3f) {
                    const float c = (d.x * L->dir[0] + d.y * L->dir[1] + d.z * L->dir[2]) / dd;
                    const float c0 = std::cos(L->coneDeg * 0.0174533f);
                    k *= Clamp01((c - c0) / std::max(0.05f, 1.0f - c0) * 2.0f);
                }
                lit = lit + Vec3{L->rgb[0], L->rgb[1], L->rgb[2]} * (k * L->intensity * 1.6f);
            }
        }
        const Vec3 col{std::min(1.0f, tint.x + lit.x), std::min(1.0f, tint.y + lit.y), std::min(1.0f, tint.z + lit.z)};
        const float litLum = std::min(1.0f, (lit.x + lit.y + lit.z) / 3.0f);
        // At night a drop out of every light is mostly not drawn at all (fewer, fainter): rain is seen where light catches it.
        if (nightK > 0.0f && litLum < 0.04f && Hash01(s * 7u + 40503u) < 0.35f * nightK) continue;
        a = std::min(0.85f, a * (1.0f + (1.5f + 4.0f * nightK) * litLum));
        const DWORD cBottom = D3DCOLOR_ARGB(static_cast<int>(a * 255.0f), static_cast<int>(col.x * 255.0f),
                                            static_cast<int>(col.y * 255.0f), static_cast<int>(col.z * 255.0f));
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


void SetWeatherCover(WeatherCoverFn fn) { g_cover = fn; }
void SetScreenRainLights(const std::vector<ScreenRainLight>& lights) { g_srLights = lights; }
bool WeatherCovered(float x, float y, float z) { return g_cover && g_cover(x, y, z); }

void WeatherFx::SetPuddleField(const std::vector<uint8_t>& texels, int size) {
    field_ = texels; fieldSize_ = size;
    if (fieldTex_) { fieldTex_->Release(); fieldTex_ = nullptr; }
}

void WeatherFx::SetRemixFrame(const Mat4& view, const Mat4& proj, const Vec3& eye, float blend) {
    SetCamera(view, proj, eye);
    g_blend = Clamp01(blend);
}

void WeatherFx::DrawRainRemix(const WeatherState& w) {
    static const float kLevelAlpha[kRemixRainLevels] = {0.35f, 0.55f, 0.80f};
    if (!remixRain_[0]) {
        const int TW = 8, TH = 64;
        for (int l = 0; l < kRemixRainLevels; ++l) {
            if (FAILED(device_->CreateTexture(TW, TH, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &remixRain_[l], nullptr))) { remixRain_[l] = nullptr; continue; }
            D3DLOCKED_RECT lr;
            std::vector<uint32_t> texels(static_cast<size_t>(TW) * TH);
            for (int y = 0; y < TH; ++y) {
                for (int x = 0; x < TW; ++x) {
                    const float u = (x + 0.5f) / TW, v = (y + 0.5f) / TH;          // v 0 tail .. 1 head
                    const float across = std::exp(-((u - 0.5f) * (u - 0.5f)) / (2.0f * 0.18f * 0.18f));
                    const float along = v * v * (3.0f - 2.0f * v);
                    const float a = std::min(1.0f, kLevelAlpha[l] * across * along);
                    const int A = static_cast<int>(a * 255.0f + 0.5f);
                    texels[static_cast<size_t>(y) * TW + x] = (static_cast<uint32_t>(A) << 24) | (0xD9u << 16) | (0xE0u << 8) | 0xF0u;
                }
            }
            if (SUCCEEDED(remixRain_[l]->LockRect(0, &lr, nullptr, 0))) {
                for (int y = 0; y < TH; ++y) memcpy(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch, &texels[static_cast<size_t>(y) * TW], TW * 4);
                remixRain_[l]->UnlockRect(0);
            }
            RendererTrace("weather: Remix rain streak texture %d (alpha %.2f) %dx%d, fixed content", l, kLevelAlpha[l], TW, TH);
        }
    }
    const int count = std::max(0, std::min(4000, static_cast<int>(static_cast<float>(w.drops) * 1.0f * w.rain)));
    const float R = 9.0f, H = 7.0f, speed = 7.5f;
    const float t = static_cast<float>(std::fmod(w.seconds, 3600.0));
    const float windX = w.windDir[0] * w.wind * 3.5f, windZ = w.windDir[1] * w.wind * 3.5f;
    const Vec3 dir = Normalize(Vec3{windX, -speed, windZ});
    const float len = 0.85f + 0.25f * w.wind;
    auto wrap = [](float v, float L) { return v - L * std::floor(v / L + 0.5f); };
    for (auto& v : texVerts_) v.clear();
    for (int i = 0; i < count; ++i) {
        const uint32_t s0 = static_cast<uint32_t>(i) * 3u;
        const float sp = speed * (0.85f + 0.3f * Hash01(s0 + 2));
        const float fall = std::fmod(Hash01(s0 + 1) * H + t * sp, H);
        const float bx = Hash01(s0) * 2.0f * R + windX * t * 0.8f;
        const float bz = Hash01(s0 + 7777u) * 2.0f * R + windZ * t * 0.8f;
        const Vec3 p{eye_.x + wrap(bx - eye_.x, 2.0f * R), eye_.y + H * 0.5f - fall, eye_.z + wrap(bz - eye_.z, 2.0f * R)};
        const Vec3 toEye = p - eye_;
        const float dist = std::sqrt(Dot(toEye, toEye));
        if (dist < 0.6f) continue;
        if (WeatherCovered(p.x, p.y, p.z)) continue;
        const float fade = Clamp01((R - dist) / 3.0f) * Clamp01((dist - 0.6f) / 1.0f) * g_blend * (0.55f + 0.45f * w.rain);
        if (fade < 0.15f) continue;
        const int level = fade < 0.45f ? 0 : (fade < 0.8f ? 1 : 2);
        const Vec3 top = p - dir * (len * (0.8f + 0.4f * Hash01(s0 + 5)));
        Vec3 side = Cross(dir, toEye);
        const float sl = std::sqrt(Dot(side, side));
        if (sl < 1e-4f) continue;
        side = side * (std::max(0.022f, dist * 0.0065f) / sl);
        const RainTexVertex v0{p.x - side.x, p.y - side.y, p.z - side.z, 0.0f, 1.0f};
        const RainTexVertex v1{p.x + side.x, p.y + side.y, p.z + side.z, 1.0f, 1.0f};
        const RainTexVertex v2{top.x - side.x, top.y - side.y, top.z - side.z, 0.0f, 0.0f};
        const RainTexVertex v3{top.x + side.x, top.y + side.y, top.z + side.z, 1.0f, 0.0f};
        auto& out = texVerts_[level];
        out.push_back(v0); out.push_back(v1); out.push_back(v2);
        out.push_back(v2); out.push_back(v1); out.push_back(v3);
    }
    if (!saved_ && FAILED(device_->CreateStateBlock(D3DSBT_ALL, &saved_))) saved_ = nullptr;
    if (saved_) saved_->Capture();
    device_->SetVertexShader(nullptr);
    device_->SetPixelShader(nullptr);
    device_->SetFVF(D3DFVF_XYZ | D3DFVF_TEX1);
    const Mat4 identity = Identity();
    device_->SetTransform(D3DTS_WORLD, reinterpret_cast<const D3DMATRIX*>(&identity));
    device_->SetTransform(D3DTS_VIEW, reinterpret_cast<const D3DMATRIX*>(&view_));
    device_->SetTransform(D3DTS_PROJECTION, reinterpret_cast<const D3DMATRIX*>(&proj_));
    device_->SetRenderState(D3DRS_LIGHTING, FALSE);
    device_->SetRenderState(D3DRS_ZENABLE, D3DZB_TRUE);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device_->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device_->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device_->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device_->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device_->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device_->SetRenderState(D3DRS_BLENDOP, D3DBLENDOP_ADD);
    device_->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device_->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device_->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device_->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device_->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device_->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    device_->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    device_->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    device_->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    device_->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    for (int l = 0; l < kRemixRainLevels; ++l) {
        if (!remixRain_[l] || texVerts_[l].empty()) continue;
        device_->SetTexture(0, remixRain_[l]);
        device_->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(texVerts_[l].size() / 3), texVerts_[l].data(), sizeof(RainTexVertex));
    }
    device_->SetTexture(0, nullptr);
    if (saved_) saved_->Apply();
}


void WeatherFx::DrawLensDrops(int width, int height, float weight, IDirect3DSurface9* scene) {
    const WeatherState& w = g_now;
    if (!device_ || width <= 0 || height <= 0) return;
    const double now = w.seconds;
    const float dt = lensClock_ < 0.0 ? 0.0f : static_cast<float>(std::min(0.25, std::max(0.0, now - lensClock_)));
    lensClock_ = now;
    auto rnd = [this]() { lensSeed_ ^= lensSeed_ << 13; lensSeed_ ^= lensSeed_ >> 17; lensSeed_ ^= lensSeed_ << 5; return (lensSeed_ & 0xFFFFFF) / 16777215.0f; };
    // New drops while it rains and the view is first person; old ones run their course either way.
    const float rate = (w.active && w.rain > 0.05f && weight > 0.5f && !WeatherCovered(eye_.x, eye_.y, eye_.z)) ? 3.0f * w.rain : 0.0f;
    lensSpawn_ += rate * dt;
    while (lensSpawn_ >= 1.0f && lensDrops_.size() < 28) {
        lensSpawn_ -= 1.0f;
        LensDrop d;
        // Mostly at the edges: a spot in the middle of the view is taken one time in six.
        do { d.x = rnd(); d.y = rnd() * 0.9f; } while (std::fabs(d.x - 0.5f) < 0.26f && std::fabs(d.y - 0.45f) < 0.28f && rnd() < 0.83f);
        d.r = 0.016f + 0.026f * rnd() * rnd();
        d.born = static_cast<float>(now); d.life = 3.0f + 4.0f * rnd();
        d.slide = d.r > 0.026f && rnd() < 0.6f ? 1.0f : 0.0f;
        d.vy = 0.0f;
        lensDrops_.push_back(d);
    }
    if (lensSpawn_ > 1.0f) lensSpawn_ = 1.0f;
    for (size_t i = 0; i < lensDrops_.size();) {
        LensDrop& d = lensDrops_[i];
        const float age = static_cast<float>(now) - d.born;
        if (age > d.life || d.y > 1.1f) { lensDrops_[i] = lensDrops_.back(); lensDrops_.pop_back(); continue; }
        if (d.slide > 0.0f && age > 0.8f) { d.vy = std::min(0.35f, d.vy + 0.25f * dt); d.y += d.vy * dt; d.x += 0.01f * dt * (rnd() - 0.5f); }
        ++i;
    }
    if (lensDrops_.empty() || weight < 0.01f) return;
    if (!dropTex_) {
        const int N = 64;
        if (FAILED(device_->CreateTexture(N, N, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &dropTex_, nullptr)) ||
            FAILED(device_->CreateTexture(N, N, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &dropMask_, nullptr))) return;
        D3DLOCKED_RECT lr, lm;
        if (SUCCEEDED(dropTex_->LockRect(0, &lr, nullptr, 0)) && SUCCEEDED(dropMask_->LockRect(0, &lm, nullptr, 0))) {
            for (int y = 0; y < N; ++y) {
                uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lr.pBits) + y * lr.Pitch);
                uint32_t* mrow = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(lm.pBits) + y * lm.Pitch);
                for (int x = 0; x < N; ++x) {
                    const float u = (x + 0.5f) / N * 2.0f - 1.0f, v = (y + 0.5f) / N * 2.0f - 1.0f;
                    const float r = std::sqrt(u * u + v * v);
                    float a = 0.0f, l = 0.0f, m = 0.0f, ml = 1.0f;
                    if (r < 1.0f) {
                        const float edge = Clamp01((1.0f - r) / 0.10f);
                        const float rim = Clamp01((r - 0.72f) / 0.20f) * edge;
                        const float spec = std::exp(-((u + 0.32f) * (u + 0.32f) + (v + 0.38f) * (v + 0.38f)) / 0.015f);
                        // Shaded drop (Remix): the sky inverted in it, lighter below, a dark rim, the highlight.
                        const float below = Clamp01(0.5f + 0.6f * v);
                        a = edge * (0.36f + 0.40f * rim) + 0.7f * spec;
                        l = (0.35f + 0.45f * below) * (1.0f - 0.55f * rim) + 0.6f * spec;
                        // Mask (plain refraction): the drop's body, its dark rim and the highlight in the colour.
                        m = edge * 0.95f;
                        ml = (1.0f - 0.45f * rim) + 1.2f * spec;
                    }
                    auto px = [](float al, float lu) {
                        const int A = static_cast<int>(Clamp01(al) * 255.0f + 0.5f), L = static_cast<int>(Clamp01(lu * 0.5f) * 255.0f + 0.5f);
                        return (static_cast<uint32_t>(A) << 24) | (static_cast<uint32_t>(L) << 16) | (static_cast<uint32_t>(L) << 8) | static_cast<uint32_t>(L);
                    };
                    row[x] = px(a, l * 2.0f);
                    mrow[x] = px(m, ml);   // colour stored halved: modulate-2x restores it
                }
            }
            dropTex_->UnlockRect(0);
            dropMask_->UnlockRect(0);
        }
    }
    // Plain: the frame under the UI, at half size (a drop sees it out of focus).
    const bool refract = scene != nullptr;
    if (refract && (!sceneCopy_ || sceneW_ != width / 2 || sceneH_ != height / 2)) {
        if (sceneCopy_) { sceneCopy_->Release(); sceneCopy_ = nullptr; }
        sceneW_ = width / 2; sceneH_ = height / 2;
        if (FAILED(device_->CreateTexture(sceneW_, sceneH_, 1, D3DUSAGE_RENDERTARGET, D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT, &sceneCopy_, nullptr))) sceneCopy_ = nullptr;
    }
    if (refract && sceneCopy_) {
        IDirect3DSurface9* dst = nullptr;
        if (SUCCEEDED(sceneCopy_->GetSurfaceLevel(0, &dst))) { device_->StretchRect(scene, nullptr, dst, nullptr, D3DTEXF_LINEAR); dst->Release(); }
    }
    const bool useRefract = refract && sceneCopy_;
    struct V { float x, y, z, rhw; DWORD c; float u, v, u2, v2; };
    std::vector<V> v;
    v.reserve(lensDrops_.size() * 6);
    const float H = static_cast<float>(height), Wd = static_cast<float>(width);
    for (const LensDrop& d : lensDrops_) {
        const float age = static_cast<float>(now) - d.born;
        const float fade = Clamp01(age / 0.25f) * Clamp01((d.life - age) / 1.2f) * weight;
        if (fade < 0.01f) continue;
        const float rx = d.r * H, ry = d.r * H * (1.0f + 0.6f * std::min(1.0f, d.vy * 6.0f));   // a running drop stretches
        const float cx = d.x * Wd, cy = d.y * H;
        const DWORD c = (static_cast<DWORD>(fade * 255.0f + 0.5f) << 24) | 0x00FFFFFFu;
        // Refraction: the drop shows its surroundings upside down and a little magnified (stage 0, the scene),
        // cut out by the mask (stage 1). The shaded drop uses the drop texture in stage 0 alone.
        const float k = 1.8f, su0 = (cx + rx * k) / Wd, su1 = (cx - rx * k) / Wd, sv0 = (cy + ry * k) / H, sv1 = (cy - ry * k) / H;
        const V q[4] = {{cx - rx, cy - ry, 0, 1, c, useRefract ? su0 : 0, useRefract ? sv0 : 0, 0, 0},
                        {cx + rx, cy - ry, 0, 1, c, useRefract ? su1 : 1, useRefract ? sv0 : 0, 1, 0},
                        {cx - rx, cy + ry, 0, 1, c, useRefract ? su0 : 0, useRefract ? sv1 : 1, 0, 1},
                        {cx + rx, cy + ry, 0, 1, c, useRefract ? su1 : 1, useRefract ? sv1 : 1, 1, 1}};
        v.push_back(q[0]); v.push_back(q[1]); v.push_back(q[2]); v.push_back(q[2]); v.push_back(q[1]); v.push_back(q[3]);
    }
    if (v.empty()) return;
    if (!saved_ && FAILED(device_->CreateStateBlock(D3DSBT_ALL, &saved_))) saved_ = nullptr;
    if (saved_) saved_->Capture();
    device_->SetVertexShader(nullptr);
    device_->SetPixelShader(nullptr);
    device_->SetFVF(D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_TEX2);
    device_->SetRenderState(D3DRS_LIGHTING, FALSE);
    device_->SetRenderState(D3DRS_ZENABLE, D3DZB_FALSE);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device_->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device_->SetRenderState(D3DRS_FOGENABLE, FALSE);
    device_->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device_->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device_->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device_->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    for (DWORD st = 0; st < 2; ++st) {
        device_->SetSamplerState(st, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
        device_->SetSamplerState(st, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
        device_->SetSamplerState(st, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
        device_->SetSamplerState(st, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
        device_->SetSamplerState(st, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    }
    if (useRefract) {
        device_->SetTexture(0, sceneCopy_);
        device_->SetTextureStageState(0, D3DTSS_TEXCOORDINDEX, 0);
        device_->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
        device_->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        device_->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
        device_->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
        device_->SetTexture(1, dropMask_);
        device_->SetTextureStageState(1, D3DTSS_TEXCOORDINDEX, 1);
        device_->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_MODULATE2X);
        device_->SetTextureStageState(1, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        device_->SetTextureStageState(1, D3DTSS_COLORARG2, D3DTA_CURRENT);
        device_->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
        device_->SetTextureStageState(1, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
        device_->SetTextureStageState(1, D3DTSS_ALPHAARG2, D3DTA_CURRENT);
        device_->SetTextureStageState(2, D3DTSS_COLOROP, D3DTOP_DISABLE);
    } else {
        device_->SetTexture(0, dropTex_);
        device_->SetTextureStageState(0, D3DTSS_TEXCOORDINDEX, 0);
        device_->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
        device_->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        device_->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
        device_->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
        device_->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
        device_->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
        device_->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    }
    device_->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(v.size() / 3), v.data(), sizeof(V));
    device_->SetTexture(0, nullptr);
    device_->SetTexture(1, nullptr);
    if (saved_) saved_->Apply();
}


void WeatherFx::DrawScreenRain(int width, int height, float weight) {
    const WeatherState& w = g_now;
    if (!device_ || !remix_ || !haveCamera_ || !w.active || !w.remixScreenRain || w.rain < 0.05f || weight < 0.5f) return;
    if (WeatherCovered(eye_.x, eye_.y + 0.3f, eye_.z)) return;
    const float R = 3.0f, H = 4.0f, speed = 7.5f;
    const int count = static_cast<int>(420.0f * w.rain);
    const float t = static_cast<float>(std::fmod(w.seconds, 3600.0));
    const float windX = w.windDir[0] * w.wind * 3.5f, windZ = w.windDir[1] * w.wind * 3.5f;
    const Vec3 dir = Normalize(Vec3{windX, -speed, windZ});
    auto wrap = [](float v, float L) { return v - L * std::floor(v / L + 0.5f); };
    auto project = [&](const Vec3& p, float* sx, float* sy, float* sw) {
        // row vectors: p * view * proj
        float q[4], c[4];
        const float in[4] = {p.x, p.y, p.z, 1.0f};
        for (int k = 0; k < 4; ++k) q[k] = in[0] * view_.m[0][k] + in[1] * view_.m[1][k] + in[2] * view_.m[2][k] + in[3] * view_.m[3][k];
        for (int k = 0; k < 4; ++k) c[k] = q[0] * proj_.m[0][k] + q[1] * proj_.m[1][k] + q[2] * proj_.m[2][k] + q[3] * proj_.m[3][k];
        if (c[3] < 0.05f) return false;
        *sx = (c[0] / c[3] * 0.5f + 0.5f) * width; *sy = (0.5f - c[1] / c[3] * 0.5f) * height; *sw = c[3];
        return true;
    };
    struct V { float x, y, z, rhw; DWORD c; };
    std::vector<V> v;
    v.reserve(static_cast<size_t>(count) * 6);
    for (int i = 0; i < count; ++i) {
        const uint32_t s0 = static_cast<uint32_t>(i) * 5u + 91u;
        const float sp = speed * (0.85f + 0.3f * Hash01(s0 + 2));
        const float fall = std::fmod(Hash01(s0 + 1) * H + t * sp, H);
        const float bx = Hash01(s0) * 2.0f * R + windX * t * 0.8f, bz = Hash01(s0 + 7777u) * 2.0f * R + windZ * t * 0.8f;
        const Vec3 p{eye_.x + wrap(bx - eye_.x, 2.0f * R), eye_.y + H * 0.5f - fall, eye_.z + wrap(bz - eye_.z, 2.0f * R)};
        const Vec3 d = p - eye_;
        const float dist = std::sqrt(Dot(d, d));
        if (dist < 0.6f || dist > R) continue;
        // Light caught: the nearby lights, by distance (a streak by a lamp or in a head lamp glints).
        Vec3 lit{0.0f, 0.0f, 0.0f};
        for (const ScreenRainLight& L : g_srLights) {
            const float dx = p.x - L.pos[0], dy = p.y - L.pos[1], dz = p.z - L.pos[2];
            float k = 0.0f;
            if (L.spot) {
                // A head lamp's beam: along it up to 6 blocks, inside its cone (soft edge).
                const float along = dx * L.dir[0] + dy * L.dir[1] + dz * L.dir[2];
                if (along > 0.1f && along < 6.0f) {
                    const float px = dx - L.dir[0] * along, py = dy - L.dir[1] * along, pz = dz - L.dir[2] * along;
                    const float off = std::sqrt(px * px + py * py + pz * pz);
                    const float rad = along * std::tan(std::max(8.0f, std::min(45.0f, L.coneDeg)) * 0.0174533f) + 0.1f;
                    const float in = Clamp01(1.0f - off / rad);
                    k = in * in * (1.0f - along / 6.0f) * L.intensity * 1.6f;
                }
            } else {
                const float dd = std::sqrt(dx * dx + dy * dy + dz * dz), r = std::max(1.0f, L.radius);
                if (dd < r) { k = 1.0f - dd / r; k *= k * L.intensity; }
            }
            if (k > 0.0f) lit = lit + Vec3{L.rgb[0], L.rgb[1], L.rgb[2]} * k;
        }
        const float li = std::min(1.0f, (lit.x + lit.y + lit.z) / 3.0f);
        const float fade = Clamp01((R - dist) / 1.0f) * Clamp01((dist - 0.6f) / 0.4f);
        const float a = (0.05f + 0.17f * (1.0f - w.night) + 0.35f * li) * fade * weight * (0.6f + 0.4f * w.rain);
        if (a < 0.01f) continue;
        const Vec3 top = p - dir * (0.35f + 0.15f * Hash01(s0 + 5));
        float x0, y0, w0, x1, y1, w1;
        if (!project(p, &x0, &y0, &w0) || !project(top, &x1, &y1, &w1)) continue;
        float nx = y1 - y0, ny = x0 - x1;
        const float nl = std::sqrt(nx * nx + ny * ny);
        if (nl < 1.0f) continue;
        nx *= 0.75f / nl; ny *= 0.75f / nl;   // 1.5 px wide
        const float day = 0.14f * (1.0f - w.night);   // by day the streaks are whiter than the asphalt and sky glare
        const float cr = std::min(1.0f, 0.75f + day + lit.x), cg = std::min(1.0f, 0.78f + day + lit.y), cb = std::min(1.0f, 0.84f + day + lit.z);
        const DWORD c0 = D3DCOLOR_ARGB(static_cast<int>(a * 255.0f), static_cast<int>(cr * 255.0f), static_cast<int>(cg * 255.0f), static_cast<int>(cb * 255.0f));
        const DWORD c1 = c0 & 0x00FFFFFFu;
        const V q[4] = {{x0 - nx, y0 - ny, 0, 1, c0}, {x0 + nx, y0 + ny, 0, 1, c0}, {x1 - nx, y1 - ny, 0, 1, c1}, {x1 + nx, y1 + ny, 0, 1, c1}};
        v.push_back(q[0]); v.push_back(q[1]); v.push_back(q[2]); v.push_back(q[2]); v.push_back(q[1]); v.push_back(q[3]);
    }
    if (v.empty()) return;
    if (!saved_ && FAILED(device_->CreateStateBlock(D3DSBT_ALL, &saved_))) saved_ = nullptr;
    if (saved_) saved_->Capture();
    device_->SetVertexShader(nullptr);
    device_->SetPixelShader(nullptr);
    device_->SetFVF(D3DFVF_XYZRHW | D3DFVF_DIFFUSE);
    device_->SetRenderState(D3DRS_LIGHTING, FALSE);
    device_->SetRenderState(D3DRS_ZENABLE, D3DZB_FALSE);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device_->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device_->SetRenderState(D3DRS_FOGENABLE, FALSE);
    device_->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device_->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device_->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device_->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device_->SetTexture(0, nullptr);
    device_->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device_->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    device_->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device_->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    device_->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device_->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(v.size() / 3), v.data(), sizeof(V));
    if (saved_) saved_->Apply();
}

}  // namespace gta2
