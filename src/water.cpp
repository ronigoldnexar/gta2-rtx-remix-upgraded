// See water.h and docs/water.md.
#include "water.h"

#include <algorithm>
#include <cmath>
#include <cstring>

#include "renderer.h"
#include "world_mesh.h"
#include "shaders/water_gen.h"

namespace gta2 {

void RendererTrace(const char* format, ...);   // renderer.cpp

namespace {

bool g_waterShader = true;
float g_waves = 1.0f, g_reflection = 1.0f, g_foam = 1.0f;

constexpr int kWaveSize = 256;
constexpr int kShoreSize = 256;      // one texel per map cell (the map is 256 x 256)
constexpr float kShoreCap = 4.0f;    // cells; the texture stores distance / kShoreCap

float Clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }

// A tileable wave height field: a few long-crested waves (whole periods across the
// tile, so it wraps) under value noise for the chop. Returns heights 0..1.
std::vector<float> WaveHeights() {
    const int n = kWaveSize;
    std::vector<float> h(static_cast<size_t>(n) * n, 0.0f);
    uint32_t seed = 0x5EA5EA11u;
    auto rnd = [&]() { seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5; return static_cast<float>(seed & 0xFFFF) / 65535.0f; };
    for (int octave = 0; octave < 4; ++octave) {
        const int cells = 8 << octave;
        const float amp = 0.55f / static_cast<float>(1 << octave);
        std::vector<float> lattice(static_cast<size_t>(cells) * cells);
        for (float& l : lattice) l = rnd();
        for (int y = 0; y < n; ++y) {
            for (int x = 0; x < n; ++x) {
                const float fx = static_cast<float>(x) * cells / n, fy = static_cast<float>(y) * cells / n;
                const int x0 = static_cast<int>(fx) % cells, y0 = static_cast<int>(fy) % cells;
                const int x1 = (x0 + 1) % cells, y1 = (y0 + 1) % cells;
                float tx = fx - std::floor(fx), ty = fy - std::floor(fy);
                tx = tx * tx * (3.0f - 2.0f * tx); ty = ty * ty * (3.0f - 2.0f * ty);
                const float a = lattice[static_cast<size_t>(y0) * cells + x0], b = lattice[static_cast<size_t>(y0) * cells + x1];
                const float c = lattice[static_cast<size_t>(y1) * cells + x0], d = lattice[static_cast<size_t>(y1) * cells + x1];
                h[static_cast<size_t>(y) * n + x] += amp * ((a + (b - a) * tx) * (1.0f - ty) + (c + (d - c) * tx) * ty);
            }
        }
    }
    // Directional swells: integer wave numbers keep the tile seamless.
    const struct { int kx, ky; float amp; } swells[] = {{3, 1, 0.30f}, {-2, 3, 0.22f}, {5, -2, 0.12f}, {1, 6, 0.08f}};
    for (int y = 0; y < n; ++y) {
        for (int x = 0; x < n; ++x) {
            float s = 0.0f;
            for (const auto& w : swells) {
                const float phase = 6.2831853f * (static_cast<float>(w.kx * x + w.ky * y) / n);
                // Sharpened crests, rounder troughs, as a water wave has.
                const float c = 0.5f + 0.5f * std::sin(phase);
                s += w.amp * (c * c * 2.0f - 0.5f);
            }
            h[static_cast<size_t>(y) * n + x] += s;
        }
    }
    float lo = 1e9f, hi = -1e9f;
    for (float f : h) { lo = std::min(lo, f); hi = std::max(hi, f); }
    for (float& f : h) f = (f - lo) / std::max(hi - lo, 1e-6f);
    return h;
}

IDirect3DTexture9* MakeWaveMap(IDirect3DDevice9* device) {
    const int n = kWaveSize;
    const std::vector<float> h = WaveHeights();
    auto at = [&](int x, int y) { return h[static_cast<size_t>((y + n) % n) * n + static_cast<size_t>((x + n) % n)]; };
    // Slopes by central differences; the gain puts the steepest faces near the
    // ends of the 0..1 range (0.5 = flat).
    std::vector<float> sx(h.size()), sy(h.size());
    float peak = 1e-6f;
    for (int y = 0; y < n; ++y) {
        for (int x = 0; x < n; ++x) {
            const size_t i = static_cast<size_t>(y) * n + x;
            sx[i] = at(x + 1, y) - at(x - 1, y);
            sy[i] = at(x, y + 1) - at(x, y - 1);
            peak = std::max(peak, std::max(std::fabs(sx[i]), std::fabs(sy[i])));
        }
    }
    std::vector<uint32_t> level(h.size());
    for (size_t i = 0; i < h.size(); ++i) {
        const int r = static_cast<int>(Clamp01(0.5f + 0.48f * sx[i] / peak) * 255.0f + 0.5f);
        const int g = static_cast<int>(Clamp01(0.5f + 0.48f * sy[i] / peak) * 255.0f + 0.5f);
        const int a = static_cast<int>(Clamp01(h[i]) * 255.0f + 0.5f);
        level[i] = (static_cast<uint32_t>(a) << 24) | (static_cast<uint32_t>(r) << 16) | (static_cast<uint32_t>(g) << 8) | 0x80u;
    }
    IDirect3DTexture9* texture = nullptr;
    if (FAILED(device->CreateTexture(n, n, 0, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &texture, nullptr))) return nullptr;
    // A box-filtered mip chain: distant water averages its slopes toward flat,
    // so it calms instead of shimmering.
    int w = n;
    for (DWORD mip = 0; mip < texture->GetLevelCount(); ++mip) {
        D3DLOCKED_RECT rect;
        if (FAILED(texture->LockRect(mip, &rect, nullptr, 0))) break;
        for (int y = 0; y < w; ++y) memcpy(static_cast<uint8_t*>(rect.pBits) + static_cast<size_t>(y) * rect.Pitch, &level[static_cast<size_t>(y) * w], static_cast<size_t>(w) * 4);
        texture->UnlockRect(mip);
        if (w == 1) break;
        const int hw = w / 2;
        std::vector<uint32_t> half(static_cast<size_t>(hw) * hw);
        for (int y = 0; y < hw; ++y) {
            for (int x = 0; x < hw; ++x) {
                uint32_t out = 0;
                for (int shift = 0; shift < 32; shift += 8) {
                    uint32_t sum = 0;
                    for (int dy = 0; dy < 2; ++dy) for (int dx = 0; dx < 2; ++dx) sum += (level[static_cast<size_t>(y * 2 + dy) * w + (x * 2 + dx)] >> shift) & 0xFFu;
                    out |= ((sum + 2) / 4) << shift;
                }
                half[static_cast<size_t>(y) * hw + x] = out;
            }
        }
        level.swap(half);
        w = hw;
    }
    return texture;
}

void SetVec(IDirect3DDevice9* device, UINT reg, float x, float y, float z, float w) {
    const float v[4] = {x, y, z, w};
    device->SetPixelShaderConstantF(reg, v, 1);
}

Mat4 Mul(const Mat4& a, const Mat4& b) {
    Mat4 r;
    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j) {
            float s = 0.0f;
            for (int k = 0; k < 4; ++k) s += a.m[i][k] * b.m[k][j];
            r.m[i][j] = s;
        }
    return r;
}

}  // namespace

void SetWaterShader(bool on) { g_waterShader = on; }
bool WaterShaderEnabled() { return g_waterShader; }
void SetWaterTuning(float waves, float reflection, float foam) {
    auto c = [](float v) { return v < 0.0f ? 0.0f : (v > 2.0f ? 2.0f : v); };
    g_waves = c(waves);
    g_reflection = c(reflection);
    g_foam = c(foam);
}

bool WaterFx::Init(IDirect3DDevice9* device, bool remix) {
    Release();
    device_ = device;
    if (!device || remix || !g_waterShader) return false;
    D3DCAPS9 caps = {};
    if (FAILED(device->GetDeviceCaps(&caps)) || caps.PixelShaderVersion < D3DPS_VERSION(3, 0) || caps.VertexShaderVersion < D3DVS_VERSION(3, 0)) {
        RendererTrace("water: no shader model 3, the fixed-function ripple stays");
        return false;
    }
    if (FAILED(device->CreateVertexShader(k_vs_water, &vs_)) || FAILED(device->CreatePixelShader(k_ps_water, &ps_))) {
        RendererTrace("water: shader creation failed, the fixed-function ripple stays");
        Release();
        device_ = device;
        return false;
    }
    wave_ = MakeWaveMap(device);
    ready_ = wave_ != nullptr;
    RendererTrace("water: shader surface %s (waves %.2f, reflection %.2f, foam %.2f)", ready_ ? "ready" : "failed (no wave map)", g_waves, g_reflection, g_foam);
    return ready_;
}

void WaterFx::Release() {
    if (vs_) { vs_->Release(); vs_ = nullptr; }
    if (ps_) { ps_->Release(); ps_ = nullptr; }
    if (wave_) { wave_->Release(); wave_ = nullptr; }
    if (shore_) { shore_->Release(); shore_ = nullptr; }
    ready_ = false;
}

void WaterFx::BuildShore(const WorldMesh& mesh, const std::vector<uint8_t>& waterTile) {
    if (shore_) { shore_->Release(); shore_ = nullptr; }
    if (!ready_ || !device_) return;
    const int n = kShoreSize;
    std::vector<float> dist(static_cast<size_t>(n) * n, 0.0f);
    int cells = 0;
    for (const TileBatch& b : mesh.batches) {
        if (b.tile < 0 || b.tile >= static_cast<int>(waterTile.size()) || !waterTile[static_cast<size_t>(b.tile)]) continue;
        if (b.streetOnly) continue;   // the apron past the edge is not the map's water
        for (uint32_t k = b.indexStart; k + 2 < b.indexStart + b.indexCount && k + 2 < mesh.indices.size(); k += 3) {
            const uint32_t i0 = mesh.indices[k], i1 = mesh.indices[k + 1], i2 = mesh.indices[k + 2];
            if (i0 >= mesh.vertices.size() || i1 >= mesh.vertices.size() || i2 >= mesh.vertices.size()) continue;
            const Vertex& a = mesh.vertices[i0];
            if (a.ny < 0.5f) continue;   // a water tile on a wall is a picture of water
            const Vertex& v1 = mesh.vertices[i1];
            const Vertex& v2 = mesh.vertices[i2];
            const int cx = static_cast<int>(std::floor((a.x + v1.x + v2.x) / 3.0f));
            const int cz = static_cast<int>(std::floor((a.z + v1.z + v2.z) / 3.0f));
            if (cx < 0 || cz < 0 || cx >= n || cz >= n) continue;
            float& d = dist[static_cast<size_t>(cz) * n + cx];
            if (d == 0.0f) { d = kShoreCap; ++cells; }
        }
    }
    // Two-pass chamfer distance (1, sqrt 2) from the nearest cell that is not water.
    const float diag = 1.41421356f;
    auto relax = [&](int x, int y, int dx, int dy, float step) {
        const int nx = x + dx, ny = y + dy;
        float& d = dist[static_cast<size_t>(y) * n + x];
        const float other = (nx < 0 || ny < 0 || nx >= n || ny >= n) ? kShoreCap : dist[static_cast<size_t>(ny) * n + nx];
        d = std::min(d, other + step);
    };
    for (int y = 0; y < n; ++y)
        for (int x = 0; x < n; ++x) {
            if (dist[static_cast<size_t>(y) * n + x] == 0.0f) continue;
            relax(x, y, -1, 0, 1.0f); relax(x, y, 0, -1, 1.0f); relax(x, y, -1, -1, diag); relax(x, y, 1, -1, diag);
        }
    for (int y = n - 1; y >= 0; --y)
        for (int x = n - 1; x >= 0; --x) {
            if (dist[static_cast<size_t>(y) * n + x] == 0.0f) continue;
            relax(x, y, 1, 0, 1.0f); relax(x, y, 0, 1, 1.0f); relax(x, y, 1, 1, diag); relax(x, y, -1, 1, diag);
        }
    if (FAILED(device_->CreateTexture(n, n, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &shore_, nullptr))) {
        shore_ = nullptr;
        RendererTrace("water: shore map creation failed, the fixed-function ripple stays");
        return;
    }
    D3DLOCKED_RECT rect;
    if (FAILED(shore_->LockRect(0, &rect, nullptr, 0))) { shore_->Release(); shore_ = nullptr; return; }
    for (int y = 0; y < n; ++y) {
        uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(rect.pBits) + static_cast<size_t>(y) * rect.Pitch);
        for (int x = 0; x < n; ++x) {
            const uint32_t v = static_cast<uint32_t>(Clamp01(dist[static_cast<size_t>(y) * n + x] / kShoreCap) * 255.0f + 0.5f);
            row[x] = 0xFF000000u | (v << 16) | (v << 8) | v;
        }
    }
    shore_->UnlockRect(0);
    RendererTrace("water: %d water cells, shore map built", cells);
}

void WaterFx::Begin(const Mat4& view, const Mat4& proj, const Vec3& eye, const WorldShading& shading, double seconds) {
    IDirect3DDevice9* d = device_;
    const Mat4 vp = Mul(view, proj);
    d->SetVertexShaderConstantF(0, &vp.m[0][0], 4);
    const float viewZ[4] = {view.m[0][2], view.m[1][2], view.m[2][2], view.m[3][2]};
    d->SetVertexShaderConstantF(4, viewZ, 1);

    // The clock wraps every ~15 minutes, so the scroll offsets keep float precision.
    const float t = static_cast<float>(std::fmod(seconds, 900.0));
    SetVec(d, 0, eye.x, eye.y, eye.z, t);
    const float glint = shading.sun ? Clamp01(shading.sunDir.y * 4.0f) : 0.0f;
    SetVec(d, 1, shading.sunDir.x, shading.sunDir.y, shading.sunDir.z, glint);
    if (shading.sun) {
        SetVec(d, 2, shading.sunColour.x, shading.sunColour.y, shading.sunColour.z, 0.0f);
        SetVec(d, 3, shading.ambient.x, shading.ambient.y, shading.ambient.z, 0.0f);
    } else {
        SetVec(d, 2, 0.0f, 0.0f, 0.0f, 0.0f);
        SetVec(d, 3, 1.0f, 1.0f, 1.0f, 0.0f);
    }
    const Vec3 horizon = haveSky_ ? horizon_ : (shading.fog ? shading.fogColour : horizon_);
    SetVec(d, 4, zenith_.x, zenith_.y, zenith_.z, 0.0f);
    SetVec(d, 5, horizon.x, horizon.y, horizon.z, 0.0f);
    SetVec(d, 6, shading.fogColour.x, shading.fogColour.y, shading.fogColour.z, shading.fog ? 1.0f : 0.0f);
    const float span = std::max(1.0f, shading.fogEnd - shading.fogStart);
    SetVec(d, 7, shading.fogStart, shading.fogEnd, 1.0f / span, 0.0f);
    SetVec(d, 8, 0.65f * g_waves, 0.9f * g_reflection, g_foam, 0.95f);

    d->SetVertexShader(vs_);
    d->SetPixelShader(ps_);
    d->SetTexture(1, wave_);
    d->SetTexture(2, shore_);
    for (DWORD s = 1; s <= 2; ++s) {
        d->SetSamplerState(s, D3DSAMP_ADDRESSU, s == 1 ? D3DTADDRESS_WRAP : D3DTADDRESS_CLAMP);
        d->SetSamplerState(s, D3DSAMP_ADDRESSV, s == 1 ? D3DTADDRESS_WRAP : D3DTADDRESS_CLAMP);
        d->SetSamplerState(s, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
        d->SetSamplerState(s, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
        d->SetSamplerState(s, D3DSAMP_MIPFILTER, s == 1 ? D3DTEXF_LINEAR : D3DTEXF_NONE);
    }
    // ps_3_0 does its own fog; the fixed-function fog is off for the draw.
    d->GetRenderState(D3DRS_FOGENABLE, &savedFog_);
    d->SetRenderState(D3DRS_FOGENABLE, FALSE);
}

void WaterFx::End() {
    IDirect3DDevice9* d = device_;
    d->SetVertexShader(nullptr);
    d->SetPixelShader(nullptr);
    d->SetTexture(1, nullptr);
    d->SetTexture(2, nullptr);
    d->SetSamplerState(2, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
    d->SetSamplerState(2, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
    d->SetRenderState(D3DRS_FOGENABLE, savedFog_);
}

}  // namespace gta2
