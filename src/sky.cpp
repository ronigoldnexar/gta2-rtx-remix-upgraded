#include "sky.h"

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace gta2 {
namespace {

constexpr float kPi = 3.14159265f;
constexpr float kDomeRadius = 900.0f;      // well inside the camera's 2000 far plane
constexpr int kDomeSegments = 36;
// Ring elevations in degrees, denser near the horizon where the gradient does
// its work; the last is the zenith, the first a skirt below the horizon so the
// fogged edge of the map meets a sky-coloured band rather than black.
constexpr float kRingElevations[] = {-16.0f, -6.0f, 0.0f, 2.5f, 6.0f, 10.0f, 15.0f, 21.0f,
                                     28.0f, 37.0f, 48.0f, 62.0f, 78.0f, 90.0f};
constexpr int kRings = static_cast<int>(sizeof(kRingElevations) / sizeof(kRingElevations[0]));
constexpr int kCloudSize = 256;
constexpr int kGlowSize = 64;
constexpr DWORD kSkyFvf = D3DFVF_XYZ | D3DFVF_DIFFUSE | D3DFVF_TEX1;

SkySettings g_settings;

float Clamp01(float v) { return v < 0.0f ? 0.0f : v > 1.0f ? 1.0f : v; }
float Smooth(float a, float b, float x) {
    const float t = Clamp01((x - a) / (b - a));
    return t * t * (3.0f - 2.0f * t);
}
Vec3 Lerp(const Vec3& a, const Vec3& b, float t) { return a + (b - a) * t; }
Vec3 Mul(const Vec3& a, const Vec3& b) { return {a.x * b.x, a.y * b.y, a.z * b.z}; }
DWORD ToColour(const Vec3& c, float alpha) {
    const auto byte = [](float v) { return static_cast<DWORD>(Clamp01(v) * 255.0f + 0.5f); };
    return (byte(alpha) << 24) | (byte(c.x) << 16) | (byte(c.y) << 8) | byte(c.z);
}

// Tileable value noise: a lattice of fixed pseudo-random values, smoothly
// interpolated, summed over octaves. Fixed numbers, so the clouds are the same
// on every run.
float Lattice(int x, int y, int period, uint32_t seed) {
    x &= period - 1;
    y &= period - 1;
    uint32_t h = static_cast<uint32_t>(x) * 374761393u + static_cast<uint32_t>(y) * 668265263u + seed * 2246822519u;
    h = (h ^ (h >> 13)) * 1274126177u;
    h ^= h >> 16;
    return static_cast<float>(h & 0xFFFF) / 65535.0f;
}
float Noise(float x, float y, int period, uint32_t seed) {
    const int x0 = static_cast<int>(std::floor(x)), y0 = static_cast<int>(std::floor(y));
    const float fx = x - static_cast<float>(x0), fy = y - static_cast<float>(y0);
    const float sx = fx * fx * (3.0f - 2.0f * fx), sy = fy * fy * (3.0f - 2.0f * fy);
    const float a = Lattice(x0, y0, period, seed), b = Lattice(x0 + 1, y0, period, seed);
    const float c = Lattice(x0, y0 + 1, period, seed), d = Lattice(x0 + 1, y0 + 1, period, seed);
    return (a + (b - a) * sx) + ((c + (d - c) * sx) - (a + (b - a) * sx)) * sy;
}
float Fbm(float u, float v) {   // u, v in 0..1, tileable
    float sum = 0.0f, amp = 0.5f, norm = 0.0f;
    int period = 4;
    for (int octave = 0; octave < 6; ++octave) {
        sum += Noise(u * static_cast<float>(period), v * static_cast<float>(period), period, 17u + octave * 7u) * amp;
        norm += amp;
        amp *= 0.55f;
        period *= 2;
    }
    return sum / norm;
}

}  // namespace

SkySettings& SkyConfig() { return g_settings; }

// A small analytic sky: a day look, a warm dusk band as the sun nears the
// horizon, and a dark blue night, mixed by the sun's elevation. Colours are
// display values, not radiometric ones - the rest of the picture is unlit
// texture, so these are tuned to sit beside it.
SkyColours ComputeSkyColours(float sunElevationDeg, float sunAzimuthDeg) {
    SkyColours out;
    const float el = sunElevationDeg * kPi / 180.0f;
    const float az = sunAzimuthDeg * kPi / 180.0f;
    out.sunDir = Normalize(Vec3{std::sin(az) * std::cos(el), std::sin(el), std::cos(az) * std::cos(el)});

    const float day = Smooth(-8.0f, 12.0f, sunElevationDeg);
    const float low = std::exp(-((sunElevationDeg - 2.0f) * (sunElevationDeg - 2.0f)) / (2.0f * 9.0f * 9.0f));
    const float dusk = low * (1.0f - Smooth(20.0f, 40.0f, sunElevationDeg));
    out.day = day;

    const Vec3 zenithDay{0.21f, 0.41f, 0.78f}, zenithNight{0.015f, 0.02f, 0.05f};
    const Vec3 horizonDay{0.72f, 0.80f, 0.90f}, horizonDusk{0.96f, 0.60f, 0.34f}, horizonNight{0.06f, 0.065f, 0.10f};
    out.zenith = Lerp(zenithNight, Lerp(zenithDay, Vec3{0.30f, 0.38f, 0.62f}, dusk * 0.6f), day);
    out.horizon = Lerp(horizonNight, Lerp(horizonDay, horizonDusk, dusk * 0.8f), day);
    const float warm = Smooth(0.0f, 25.0f, sunElevationDeg);
    out.sunColour = Lerp(Vec3{1.0f, 0.50f, 0.22f}, Vec3{1.0f, 0.96f, 0.86f}, warm) * Smooth(-3.0f, 2.0f, sunElevationDeg);
    out.fog = out.horizon * 0.97f;
    // The ambient tint: cool from the sky by day, barely tinted at night.
    out.ambient = Lerp(Vec3{0.92f, 0.94f, 1.0f}, Lerp(Vec3{0.98f, 0.985f, 1.0f}, Vec3{1.0f, 0.93f, 0.86f}, dusk * 0.5f), day);
    return out;
}

Sky::~Sky() { Release(); }

void Sky::Release() {
    if (clouds_) clouds_->Release();
    if (glow_) glow_->Release();
    clouds_ = nullptr;
    glow_ = nullptr;
    device_ = nullptr;
}

void Sky::BuildDome() {
    domeDirs_.clear();
    domeElevation_.clear();
    domeIndices_.clear();
    for (int ring = 0; ring < kRings; ++ring) {
        const float el = kRingElevations[ring] * kPi / 180.0f;
        for (int seg = 0; seg <= kDomeSegments; ++seg) {   // one extra column so the seam's UVs wrap cleanly
            const float az = static_cast<float>(seg) / static_cast<float>(kDomeSegments) * 2.0f * kPi;
            domeDirs_.push_back({std::sin(az) * std::cos(el), std::sin(el), std::cos(az) * std::cos(el)});
            domeElevation_.push_back(el);
        }
    }
    const int cols = kDomeSegments + 1;
    for (int ring = 0; ring + 1 < kRings; ++ring) {
        for (int seg = 0; seg < kDomeSegments; ++seg) {
            const uint16_t a = static_cast<uint16_t>(ring * cols + seg);
            const uint16_t b = static_cast<uint16_t>(a + 1);
            const uint16_t c = static_cast<uint16_t>(a + cols);
            const uint16_t d = static_cast<uint16_t>(c + 1);
            domeIndices_.insert(domeIndices_.end(), {a, c, b, b, c, d});
        }
    }
    // A floor under the skirt, so looking down past the last block never shows black.
    const uint16_t nadir = static_cast<uint16_t>(domeDirs_.size());
    domeDirs_.push_back({0.0f, -1.0f, 0.0f});
    domeElevation_.push_back(-kPi * 0.5f);
    for (int seg = 0; seg < kDomeSegments; ++seg) {
        domeIndices_.insert(domeIndices_.end(),
                            {nadir, static_cast<uint16_t>(seg + 1), static_cast<uint16_t>(seg)});
    }
    domeScratch_.resize(domeDirs_.size());
}

bool Sky::Ensure(IDirect3DDevice9* device) {
    if (device_ != device) Release();
    device_ = device;
    if (domeDirs_.empty()) BuildDome();
    if (!clouds_) {
        if (FAILED(device->CreateTexture(kCloudSize, kCloudSize, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &clouds_, nullptr))) {
            clouds_ = nullptr;
            return false;
        }
        D3DLOCKED_RECT rect;
        if (SUCCEEDED(clouds_->LockRect(0, &rect, nullptr, 0))) {
            for (int y = 0; y < kCloudSize; ++y) {
                DWORD* row = reinterpret_cast<DWORD*>(static_cast<uint8_t*>(rect.pBits) + y * rect.Pitch);
                for (int x = 0; x < kCloudSize; ++x) {
                    const float u = (static_cast<float>(x) + 0.5f) / kCloudSize;
                    const float v = (static_cast<float>(y) + 0.5f) / kCloudSize;
                    const float n = Fbm(u, v);
                    // Density: the cover setting moves the threshold at draw
                    // time through the alpha, so the texture holds the raw
                    // field in A and a lit/shaded brightness in RGB: thicker
                    // cloud is a little greyer underneath.
                    const float thick = Clamp01((n - 0.45f) / 0.35f);
                    const float bright = 1.0f - 0.28f * thick * thick;
                    const DWORD b = static_cast<DWORD>(bright * 255.0f + 0.5f);
                    row[x] = (static_cast<DWORD>(Clamp01(n) * 255.0f + 0.5f) << 24) | (b << 16) | (b << 8) | b;
                }
            }
            clouds_->UnlockRect(0);
        }
    }
    if (!glow_) {
        if (FAILED(device->CreateTexture(kGlowSize, kGlowSize, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &glow_, nullptr))) {
            glow_ = nullptr;
            return false;
        }
        D3DLOCKED_RECT rect;
        if (SUCCEEDED(glow_->LockRect(0, &rect, nullptr, 0))) {
            for (int y = 0; y < kGlowSize; ++y) {
                DWORD* row = reinterpret_cast<DWORD*>(static_cast<uint8_t*>(rect.pBits) + y * rect.Pitch);
                for (int x = 0; x < kGlowSize; ++x) {
                    const float dx = (static_cast<float>(x) + 0.5f) / kGlowSize * 2.0f - 1.0f;
                    const float dy = (static_cast<float>(y) + 0.5f) / kGlowSize * 2.0f - 1.0f;
                    const float r = std::sqrt(dx * dx + dy * dy);
                    const float f = r >= 1.0f ? 0.0f : (1.0f - r) * (1.0f - r);
                    const DWORD b = static_cast<DWORD>(f * 255.0f + 0.5f);
                    row[x] = (b << 24) | (b << 16) | (b << 8) | b;
                }
            }
            glow_->UnlockRect(0);
        }
    }
    return true;
}

void Sky::Draw(IDirect3DDevice9* device, const Camera& camera, float aspect, const SkySettings& settings,
               const SkyColours& colours, float blend, double seconds) {
    if (!device || blend <= 0.002f || !Ensure(device)) return;
    blend = Clamp01(blend);

    // Around the camera, with its own view and projection.
    Mat4 world = Identity();
    world.m[3][0] = camera.Position().x;
    world.m[3][1] = camera.Position().y;
    world.m[3][2] = camera.Position().z;
    const Mat4 view = camera.ViewMatrix();
    const Mat4 proj = camera.ProjectionMatrix(aspect);
    device->SetTransform(D3DTS_WORLD, reinterpret_cast<const D3DMATRIX*>(&world));
    device->SetTransform(D3DTS_VIEW, reinterpret_cast<const D3DMATRIX*>(&view));
    device->SetTransform(D3DTS_PROJECTION, reinterpret_cast<const D3DMATRIX*>(&proj));

    device->SetRenderState(D3DRS_ZENABLE, D3DZB_FALSE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_FOGENABLE, FALSE);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_FILLMODE, D3DFILL_SOLID);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device->SetFVF(kSkyFvf);

    // --- The gradient -------------------------------------------------------
    // Horizon to zenith by elevation, the sun's glow added where the sky is
    // near it: a tight bright core and a wide soft halo, both bigger and
    // warmer the lower the sun. Below the horizon the skirt is fog-coloured.
    const Vec3& sun = colours.sunDir;
    const float sunEl = std::asin(std::max(-1.0f, std::min(1.0f, sun.y)));
    const float lowSun = 1.0f - Smooth(0.0f, 0.6f, sunEl);
    const float haloWidth = 0.45f + 0.5f * lowSun;
    const float haloGain = 0.22f + 0.30f * lowSun;
    for (size_t i = 0; i < domeDirs_.size(); ++i) {
        const Vec3& d = domeDirs_[i];
        const float el = domeElevation_[i];
        Vec3 c;
        if (el < 0.0f) {
            // From the horizon colour down to a slightly darker haze.
            c = colours.fog * (1.0f - 0.18f * Clamp01(-el / 0.3f));
        } else {
            const float t = std::pow(Clamp01(std::sin(el)), 0.55f);
            c = Lerp(colours.horizon, colours.zenith, t);
        }
        const float angle = std::acos(std::max(-1.0f, std::min(1.0f, Dot(d, sun))));
        const float halo = std::exp(-angle * angle / (2.0f * haloWidth * haloWidth)) * haloGain;
        const float core = std::exp(-angle * angle / (2.0f * 0.09f * 0.09f)) * 0.9f;
        c = c + colours.sunColour * (halo + core) * (el < 0.0f ? 0.35f : 1.0f);
        DomeVertex& v = domeScratch_[i];
        v.x = d.x * kDomeRadius;
        v.y = d.y * kDomeRadius;
        v.z = d.z * kDomeRadius;
        v.colour = ToColour(c, blend);
        v.u = v.v = 0.0f;
    }
    device->SetTexture(0, nullptr);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(domeScratch_.size()),
                                   static_cast<UINT>(domeIndices_.size() / 3), domeIndices_.data(), D3DFMT_INDEX16,
                                   domeScratch_.data(), sizeof(DomeVertex));

    // --- The sun -------------------------------------------------------------
    // Two additive billboards on the glow texture: the disc, and a wide halo.
    if (colours.sunColour.x + colours.sunColour.y + colours.sunColour.z > 0.01f && sun.y > -0.05f) {
        const Vec3 up0 = std::abs(sun.y) > 0.99f ? Vec3{0.0f, 0.0f, 1.0f} : Vec3{0.0f, 1.0f, 0.0f};
        const Vec3 right = Normalize(Cross(up0, sun));
        const Vec3 up = Cross(sun, right);
        const float dist = kDomeRadius * 0.95f;
        const Vec3 centre = sun * dist;
        device->SetTexture(0, glow_);
        device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
        device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
        device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
        device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
        device->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
        device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
        device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
        device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
        device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
        device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_ONE);
        const auto quad = [&](float halfAngleDeg, const Vec3& colour) {
            const float h = dist * std::tan(halfAngleDeg * kPi / 180.0f);
            const DWORD col = ToColour(colour, 1.0f);
            DomeVertex q[4];
            const Vec3 p0 = centre - right * h + up * h, p1 = centre + right * h + up * h;
            const Vec3 p2 = centre + right * h - up * h, p3 = centre - right * h - up * h;
            q[0] = {p0.x, p0.y, p0.z, col, 0.0f, 0.0f};
            q[1] = {p1.x, p1.y, p1.z, col, 1.0f, 0.0f};
            q[2] = {p2.x, p2.y, p2.z, col, 1.0f, 1.0f};
            q[3] = {p3.x, p3.y, p3.z, col, 0.0f, 1.0f};
            device->DrawPrimitiveUP(D3DPT_TRIANGLEFAN, 2, q, sizeof(DomeVertex));
        };
        quad(13.0f, colours.sunColour * (0.16f + 0.12f * lowSun) * blend);
        quad(2.2f, colours.sunColour * 1.0f * blend);
        quad(1.1f, Vec3{1.0f, 1.0f, 1.0f} * 0.8f * blend);
        device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
        device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    }

    // --- The clouds ----------------------------------------------------------
    // The dome again, textured with the noise projected from above (so the
    // clouds flatten toward the horizon the way a layer at one height does),
    // drifting slowly, faded out just above the horizon where the haze is.
    if (settings.cloudCover > 0.01f) {
        const float cover = Clamp01(settings.cloudCover);
        // Cloud colour: white in the sun by day, grey-blue underneath, warm at
        // dusk, near-black at night.
        const Vec3 lit = Lerp(Vec3{0.10f, 0.11f, 0.15f},
                              Lerp(Vec3{0.98f, 0.98f, 1.0f}, colours.sunColour, 0.35f * lowSun), colours.day);
        const float scroll = static_cast<float>(std::fmod(seconds * 0.0025, 1.0));
        for (size_t i = 0; i < domeDirs_.size(); ++i) {
            const Vec3& d = domeDirs_[i];
            const float el = domeElevation_[i];
            DomeVertex& v = domeScratch_[i];
            const float fade = Smooth(0.03f, 0.22f, el);        // none at and below the horizon
            const float denom = std::max(d.y, 0.02f) + 0.10f;
            v.u = d.x / denom * 0.9f + scroll;
            v.v = d.z / denom * 0.9f + scroll * 0.4f;
            v.colour = ToColour(lit, blend * fade);
        }
        device->SetTexture(0, clouds_);
        device->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
        device->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
        device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
        device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
        device->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
        // Alpha = (noise - threshold) scaled: done with the alpha test-free
        // trick of a texture factor: alpha = tex.a * diffuse.a passes through
        // the threshold in the texture itself, so the cover setting selects a
        // second-stage subtract. Two stages: stage 0 takes the texture alpha
        // minus the threshold (TFACTOR), stage 1 scales by the vertex alpha.
        const DWORD threshold = ToColour(Vec3{1.0f, 1.0f, 1.0f}, 1.0f - cover * 0.9f - 0.05f);
        device->SetRenderState(D3DRS_TEXTUREFACTOR, threshold);
        device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
        device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
        device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SUBTRACT);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
        device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_TFACTOR);
        device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
        device->SetTextureStageState(1, D3DTSS_COLORARG1, D3DTA_CURRENT);
        device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_MODULATE4X);
        device->SetTextureStageState(1, D3DTSS_ALPHAARG1, D3DTA_CURRENT);
        device->SetTextureStageState(1, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
        device->SetTexture(1, nullptr);
        device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, static_cast<UINT>(domeScratch_.size()),
                                       static_cast<UINT>(domeIndices_.size() / 3), domeIndices_.data(),
                                       D3DFMT_INDEX16, domeScratch_.data(), sizeof(DomeVertex));
        device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
        device->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    }

    device->SetTexture(0, nullptr);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device->SetRenderState(D3DRS_ZENABLE, D3DZB_TRUE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
}

}  // namespace gta2
