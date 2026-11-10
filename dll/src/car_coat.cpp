// FIX-CAR-SHADING-1: the car paint's coat (see car_coat.h, src/shaders/car_coat.hlsl, docs/vehicle-shading.md).
#include "car_coat.h"

#include <algorithm>
#include <cmath>
#include <cstring>

#include "log.h"
#include "remix_api.h"
#include "../../src/shaders/car_coat_gen.h"

namespace gta2dx9 {
namespace {

struct CoatSettings {
    int enabled = 1;
    float f0 = 0.04f;          // the clear coat's reflectance facing the eye
    float reflect = 1.0f;      // reflection strength (x Fresnel)
    float power = 350.0f;      // the coat's sun highlight (Blinn exponent)
    float crease = 1.0f;       // crease darkening / edge strength
    float creaseScale = 0.025f;   // curvature (1/blocks) x this = 1: a 0.025-block radius is a full crease
    float flake = 0.5f;
    float sheenPower = 24.0f;  // the base coat's broad lobe in the paint's colour
    float sheen = 0.10f;
    float rest = 0.35f;        // the coat on the body's non-paint texels (trim, lamps, baked glass)
    float ffpSpec = 0.0f;      // car_bodies' per-vertex lobe kept under the coat
    float sky = 1.8f;
    float gaps = 1.0f;         // panel gap strength
    float gapThreshold = 0.12f;   // the texture's line contrast where a gap starts          // the reflected sky's radiance over the paint's (the frame is LDR, the sky is not)
};
CoatSettings g_set;
int g_live = -1;
CarCoatFrame g_frame;

float g_weight = 0.0f;
IDirect3DDevice9* g_dev = nullptr;
IDirect3DVertexShader9* g_vs = nullptr;
IDirect3DPixelShader9* g_ps = nullptr;
int g_caps = -1;   // -1 unknown, 0 no, 1 yes
int g_draws = 0;
double g_ms = 0.0;

float PercentKey(const char* ini, const char* key, int def) { return GetPrivateProfileIntA("renderer", key, def, ini) / 100.0f; }

double NowMs() {
    static LARGE_INTEGER f = {};
    if (!f.QuadPart) QueryPerformanceFrequency(&f);
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return static_cast<double>(t.QuadPart) * 1000.0 / static_cast<double>(f.QuadPart);
}

gta2::Mat4 Mul(const gta2::Mat4& a, const gta2::Mat4& b) {
    gta2::Mat4 o;
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c) {
            float s = 0.0f;
            for (int k = 0; k < 4; ++k) s += a.m[r][k] * b.m[k][c];
            o.m[r][c] = s;
        }
    return o;
}

// General 4x4 inverse (cofactors); false when singular.
bool Invert(const gta2::Mat4& in, gta2::Mat4* out) {
    const float* m = &in.m[0][0];
    float inv[16];
    inv[0] = m[5] * m[10] * m[15] - m[5] * m[11] * m[14] - m[9] * m[6] * m[15] + m[9] * m[7] * m[14] + m[13] * m[6] * m[11] - m[13] * m[7] * m[10];
    inv[4] = -m[4] * m[10] * m[15] + m[4] * m[11] * m[14] + m[8] * m[6] * m[15] - m[8] * m[7] * m[14] - m[12] * m[6] * m[11] + m[12] * m[7] * m[10];
    inv[8] = m[4] * m[9] * m[15] - m[4] * m[11] * m[13] - m[8] * m[5] * m[15] + m[8] * m[7] * m[13] + m[12] * m[5] * m[11] - m[12] * m[7] * m[9];
    inv[12] = -m[4] * m[9] * m[14] + m[4] * m[10] * m[13] + m[8] * m[5] * m[14] - m[8] * m[6] * m[13] - m[12] * m[5] * m[10] + m[12] * m[6] * m[9];
    inv[1] = -m[1] * m[10] * m[15] + m[1] * m[11] * m[14] + m[9] * m[2] * m[15] - m[9] * m[3] * m[14] - m[13] * m[2] * m[11] + m[13] * m[3] * m[10];
    inv[5] = m[0] * m[10] * m[15] - m[0] * m[11] * m[14] - m[8] * m[2] * m[15] + m[8] * m[3] * m[14] + m[12] * m[2] * m[11] - m[12] * m[3] * m[10];
    inv[9] = -m[0] * m[9] * m[15] + m[0] * m[11] * m[13] + m[8] * m[1] * m[15] - m[8] * m[3] * m[13] - m[12] * m[1] * m[11] + m[12] * m[3] * m[9];
    inv[13] = m[0] * m[9] * m[14] - m[0] * m[10] * m[13] - m[8] * m[1] * m[14] + m[8] * m[2] * m[13] + m[12] * m[1] * m[10] - m[12] * m[2] * m[9];
    inv[2] = m[1] * m[6] * m[15] - m[1] * m[7] * m[14] - m[5] * m[2] * m[15] + m[5] * m[3] * m[14] + m[13] * m[2] * m[7] - m[13] * m[3] * m[6];
    inv[6] = -m[0] * m[6] * m[15] + m[0] * m[7] * m[14] + m[4] * m[2] * m[15] - m[4] * m[3] * m[14] - m[12] * m[2] * m[7] + m[12] * m[3] * m[6];
    inv[10] = m[0] * m[5] * m[15] - m[0] * m[7] * m[13] - m[4] * m[1] * m[15] + m[4] * m[3] * m[13] + m[12] * m[1] * m[7] - m[12] * m[3] * m[5];
    inv[14] = -m[0] * m[5] * m[14] + m[0] * m[6] * m[13] + m[4] * m[1] * m[14] - m[4] * m[2] * m[13] - m[12] * m[1] * m[6] + m[12] * m[2] * m[5];
    inv[3] = -m[1] * m[6] * m[11] + m[1] * m[7] * m[10] + m[5] * m[2] * m[11] - m[5] * m[3] * m[10] - m[9] * m[2] * m[7] + m[9] * m[3] * m[6];
    inv[7] = m[0] * m[6] * m[11] - m[0] * m[7] * m[10] - m[4] * m[2] * m[11] + m[4] * m[3] * m[10] + m[8] * m[2] * m[7] - m[8] * m[3] * m[6];
    inv[11] = -m[0] * m[5] * m[11] + m[0] * m[7] * m[9] + m[4] * m[1] * m[11] - m[4] * m[3] * m[9] - m[8] * m[1] * m[7] + m[8] * m[3] * m[5];
    inv[15] = m[0] * m[5] * m[10] - m[0] * m[6] * m[9] - m[4] * m[1] * m[10] + m[4] * m[2] * m[9] + m[8] * m[1] * m[6] - m[8] * m[2] * m[5];
    const float det = m[0] * inv[0] + m[1] * inv[4] + m[2] * inv[8] + m[3] * inv[12];
    if (std::fabs(det) < 1e-20f) return false;
    for (int i = 0; i < 16; ++i) (&out->m[0][0])[i] = inv[i] / det;
    return true;
}

bool Ready(IDirect3DDevice9* device) {
    if (g_dev != device) {
        if (g_vs) g_vs->Release();
        if (g_ps) g_ps->Release();
        g_vs = nullptr; g_ps = nullptr; g_caps = -1;
        g_dev = device;
    }
    if (g_caps < 0) {
        D3DCAPS9 caps = {};
        const bool sm3 = SUCCEEDED(device->GetDeviceCaps(&caps)) && caps.VertexShaderVersion >= D3DVS_VERSION(3, 0) &&
                         caps.PixelShaderVersion >= D3DPS_VERSION(3, 0);
        g_caps = sm3 && SUCCEEDED(device->CreateVertexShader(k_vs_coat, &g_vs)) && SUCCEEDED(device->CreatePixelShader(k_ps_coat, &g_ps)) ? 1 : 0;
        Log("car coat: %s (shader model 3 %s; [renderer] car_coat=%d, f0 %.3f, reflect %.2f, power %.0f, crease %.2f, flake %.2f)",
            g_caps ? "ready" : "unavailable", sm3 ? "yes" : "no", g_set.enabled, g_set.f0, g_set.reflect, g_set.power, g_set.crease, g_set.flake);
    }
    return g_caps == 1;
}

}  // namespace

void CarCoatConfigure(const char* ini) {
    g_set.enabled = GetPrivateProfileIntA("renderer", "car_coat", 1, ini);
    g_set.f0 = PercentKey(ini, "car_coat_f0_percent", 4);
    g_set.reflect = PercentKey(ini, "car_coat_reflect_percent", 100);
    g_set.power = static_cast<float>((std::max)(8, static_cast<int>(GetPrivateProfileIntA("renderer", "car_coat_power", 350, ini))));
    g_set.crease = PercentKey(ini, "car_coat_crease_percent", 100);
    g_set.flake = PercentKey(ini, "car_coat_flake_percent", 50);
    g_set.sheen = PercentKey(ini, "car_coat_sheen_percent", 10);
    g_set.rest = PercentKey(ini, "car_coat_rest_percent", 35);
    g_set.ffpSpec = PercentKey(ini, "car_coat_ffp_spec_percent", 0);
    g_set.sky = PercentKey(ini, "car_coat_sky_percent", 180);
    g_set.gaps = PercentKey(ini, "car_coat_gaps_percent", 100);
}

float CarCoatFfpSpecKeep() { return g_set.ffpSpec; }

void CarCoatSetLive(int on) { g_live = on; }

bool CarCoatActive(IDirect3DDevice9* device) {
    const int on = g_live >= 0 ? g_live : g_set.enabled;
    return on && !RemixApiAvailable() && Ready(device);
}

void CarCoatSetFrame(const CarCoatFrame& frame) { g_frame = frame; }

void CarCoatSetWeight(float weight) { g_weight = (std::max)(0.0f, weight); }
float CarCoatWeight() { return g_weight; }

void CarCoatStats(int* draws, double* ms) {
    if (draws) *draws = g_draws;
    if (ms) *ms = g_ms;
    g_draws = 0;
    g_ms = 0.0;
}

void CarCoatOverlay(IDirect3DDevice9* device, const gta2::Mat4& world, const CarCoatDraw& d) {
    if (g_weight <= 0.0f || g_caps != 1 || g_dev != device || !g_vs || !g_ps) return;
    DWORD blend = FALSE;
    device->GetRenderState(D3DRS_ALPHABLENDENABLE, &blend);
    if (blend) return;   // a translucent draw (FIX-SEATED's band): no coat over it
    const double t0 = NowMs();
    DWORD aTest = FALSE, clip = 0, zw = TRUE, zfunc = D3DCMP_LESSEQUAL, src = D3DBLEND_ONE, dst = D3DBLEND_ZERO, fog = FALSE, fogColor = 0;
    DWORD fogStart = 0, fogEnd = 0, bias = 0, slope = 0;
    device->GetRenderState(D3DRS_ALPHATESTENABLE, &aTest);
    device->GetRenderState(D3DRS_CLIPPLANEENABLE, &clip);
    device->GetRenderState(D3DRS_ZWRITEENABLE, &zw);
    device->GetRenderState(D3DRS_ZFUNC, &zfunc);
    device->GetRenderState(D3DRS_SRCBLEND, &src);
    device->GetRenderState(D3DRS_DESTBLEND, &dst);
    device->GetRenderState(D3DRS_FOGENABLE, &fog);
    device->GetRenderState(D3DRS_FOGCOLOR, &fogColor);
    device->GetRenderState(D3DRS_FOGSTART, &fogStart);
    device->GetRenderState(D3DRS_FOGEND, &fogEnd);
    device->GetRenderState(D3DRS_DEPTHBIAS, &bias);
    device->GetRenderState(D3DRS_SLOPESCALEDEPTHBIAS, &slope);
    D3DMATRIX dv, dp;
    device->GetTransform(D3DTS_VIEW, &dv);
    device->GetTransform(D3DTS_PROJECTION, &dp);
    gta2::Mat4 view, proj;
    memcpy(view.m, &dv, sizeof(view.m));
    memcpy(proj.m, &dp, sizeof(proj.m));
    const gta2::Mat4 vp = Mul(view, proj);
    const gta2::Mat4 wvp = Mul(world, vp);
    // User clip planes are in clip space while a vertex shader is bound: Q = inverse(VP) P.
    float planes[6][4] = {};
    if (clip) {
        gta2::Mat4 inv;
        if (!Invert(vp, &inv)) return;
        for (int k = 0; k < 6; ++k) {
            if (!(clip & (1u << k))) continue;
            device->GetClipPlane(k, planes[k]);
            float q[4];
            for (int j = 0; j < 4; ++j) q[j] = inv.m[j][0] * planes[k][0] + inv.m[j][1] * planes[k][1] + inv.m[j][2] * planes[k][2] + inv.m[j][3] * planes[k][3];
            device->SetClipPlane(k, q);
        }
    }
    // The normals: the inverse transpose of the world's 3x3 (the fit scales the model unevenly).
    float nrm[12] = {};
    {
        const float (*a)[4] = world.m;
        const float c00 = a[1][1] * a[2][2] - a[1][2] * a[2][1], c01 = a[1][2] * a[2][0] - a[1][0] * a[2][2], c02 = a[1][0] * a[2][1] - a[1][1] * a[2][0];
        const float c10 = a[0][2] * a[2][1] - a[0][1] * a[2][2], c11 = a[0][0] * a[2][2] - a[0][2] * a[2][0], c12 = a[0][1] * a[2][0] - a[0][0] * a[2][1];
        const float c20 = a[0][1] * a[1][2] - a[0][2] * a[1][1], c21 = a[0][2] * a[1][0] - a[0][0] * a[1][2], c22 = a[0][0] * a[1][1] - a[0][1] * a[1][0];
        // Row vectors: n' = n * inverse(A)^T = n * (cofactor matrix) / det; the scale is normalised away in the shader.
        const float cof[3][3] = {{c00, c01, c02}, {c10, c11, c12}, {c20, c21, c22}};
        for (int r = 0; r < 3; ++r) for (int c = 0; c < 3; ++c) nrm[r * 4 + c] = cof[r][c];
        const float det = a[0][0] * c00 + a[0][1] * c01 + a[0][2] * c02;
        if (det < 0.0f) for (float& v : nrm) v = -v;
    }
    float vsc[48] = {};
    memcpy(vsc, wvp.m, 64);
    memcpy(vsc + 16, world.m, 64);
    memcpy(vsc + 32, nrm, 48);
    vsc[44] = view.m[0][2]; vsc[45] = view.m[1][2]; vsc[46] = view.m[2][2]; vsc[47] = view.m[3][2];
    // The eye: view = [R 0; t 1] (row vectors), eye = -t R^T.
    const float ex = -(view.m[3][0] * view.m[0][0] + view.m[3][1] * view.m[0][1] + view.m[3][2] * view.m[0][2]);
    const float ey = -(view.m[3][0] * view.m[1][0] + view.m[3][1] * view.m[1][1] + view.m[3][2] * view.m[1][2]);
    const float ez = -(view.m[3][0] * view.m[2][0] + view.m[3][1] * view.m[2][1] + view.m[3][2] * view.m[2][2]);
    float fs = 0.0f, fe = 1.0f;
    memcpy(&fs, &fogStart, 4);
    memcpy(&fe, &fogEnd, 4);
    // The gap detector's taps 1.5 texels apart (the atlases' painted seams are 1-3 texels wide).
    float texel[2] = {0.0f, 0.0f};
    if (d.body) {
        D3DSURFACE_DESC desc = {};
        if (SUCCEEDED(d.body->GetLevelDesc(0, &desc)) && desc.Width && desc.Height) { texel[0] = 1.5f / desc.Width; texel[1] = 1.5f / desc.Height; }
    }
    const float tint[3] = {d.tint ? d.tint[0] : 1.0f, d.tint ? d.tint[1] : 1.0f, d.tint ? d.tint[2] : 1.0f};
    const float w = g_weight;
    const float psc[56] = {
        ex, ey, ez, 1.0f,
        g_frame.sunDir[0], g_frame.sunDir[1], g_frame.sunDir[2], g_frame.sunStrength,
        g_frame.sunCol[0], g_frame.sunCol[1], g_frame.sunCol[2], 1.0f,
        g_frame.zenith[0], g_frame.zenith[1], g_frame.zenith[2], 1.0f,
        g_frame.horizon[0], g_frame.horizon[1], g_frame.horizon[2], 1.0f,
        g_frame.ground[0], g_frame.ground[1], g_frame.ground[2], g_set.sky,
        ((fogColor >> 16) & 0xFF) / 255.0f, ((fogColor >> 8) & 0xFF) / 255.0f, (fogColor & 0xFF) / 255.0f, fog ? 1.0f : 0.0f,
        fs, fe, 1.0f / (std::max)(1e-3f, fe - fs), 0.0f,
        tint[0], tint[1], tint[2], w * (d.paint || d.softPaint ? 1.0f : g_set.rest),
        g_set.f0, g_set.reflect, g_set.power, g_set.crease,
        aTest ? 1.0f : 0.0f, d.softPaint ? 1.0f : 0.0f, d.glassMask ? 1.0f : 0.0f, g_set.flake,
        g_set.sheenPower, g_set.sheen, g_set.creaseScale, d.softPaint ? g_set.rest : 1.0f,
        g_live == 2 ? 1.0f : 0.0f, 0.0f, 0.0f, 0.0f,
        texel[0], texel[1], g_live == 3 ? 0.0f : g_set.gaps, g_set.gapThreshold,
    };
    IDirect3DBaseTexture9* s1 = nullptr;
    DWORD s1u = 0, s1v = 0, s1min = 0, s1mag = 0, s1mip = 0;
    if (d.glassMask) {
        device->GetTexture(1, &s1);
        device->GetSamplerState(1, D3DSAMP_ADDRESSU, &s1u);
        device->GetSamplerState(1, D3DSAMP_ADDRESSV, &s1v);
        device->GetSamplerState(1, D3DSAMP_MINFILTER, &s1min);
        device->GetSamplerState(1, D3DSAMP_MAGFILTER, &s1mag);
        device->GetSamplerState(1, D3DSAMP_MIPFILTER, &s1mip);
        device->SetTexture(1, d.glassMask);
        device->SetSamplerState(1, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
        device->SetSamplerState(1, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
        device->SetSamplerState(1, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
        device->SetSamplerState(1, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
        device->SetSamplerState(1, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
    }
    device->SetVertexShader(g_vs);
    device->SetPixelShader(g_ps);
    device->SetVertexShaderConstantF(0, vsc, 12);
    device->SetPixelShaderConstantF(0, psc, 14);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    device->SetRenderState(D3DRS_FOGENABLE, FALSE);
    // The same triangles again: pulled a hair toward the eye so the shader's transform wins the depth test.
    const float b = -0.000004f, s = -1.0f;
    device->SetRenderState(D3DRS_DEPTHBIAS, *reinterpret_cast<const DWORD*>(&b));
    device->SetRenderState(D3DRS_SLOPESCALEDEPTHBIAS, *reinterpret_cast<const DWORD*>(&s));
    if (d.vb) {
        device->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, 0, d.verts, 0, d.prims);
    } else if (d.upVerts && d.upIndices) {
        device->DrawIndexedPrimitiveUP(D3DPT_TRIANGLELIST, 0, d.verts, d.prims, d.upIndices, D3DFMT_INDEX32, d.upVerts, d.stride);
    }
    device->SetVertexShader(nullptr);
    device->SetPixelShader(nullptr);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, blend);
    device->SetRenderState(D3DRS_SRCBLEND, src);
    device->SetRenderState(D3DRS_DESTBLEND, dst);
    device->SetRenderState(D3DRS_ALPHATESTENABLE, aTest);
    device->SetRenderState(D3DRS_ZWRITEENABLE, zw);
    device->SetRenderState(D3DRS_ZFUNC, zfunc);
    device->SetRenderState(D3DRS_FOGENABLE, fog);
    device->SetRenderState(D3DRS_DEPTHBIAS, bias);
    device->SetRenderState(D3DRS_SLOPESCALEDEPTHBIAS, slope);
    if (clip) for (int k = 0; k < 6; ++k) if (clip & (1u << k)) device->SetClipPlane(k, planes[k]);
    if (d.glassMask) {
        device->SetTexture(1, s1);
        if (s1) s1->Release();
        device->SetSamplerState(1, D3DSAMP_ADDRESSU, s1u);
        device->SetSamplerState(1, D3DSAMP_ADDRESSV, s1v);
        device->SetSamplerState(1, D3DSAMP_MINFILTER, s1min);
        device->SetSamplerState(1, D3DSAMP_MAGFILTER, s1mag);
        device->SetSamplerState(1, D3DSAMP_MIPFILTER, s1mip);
    }
    ++g_draws;
    g_ms += NowMs() - t0;
}

}  // namespace gta2dx9
