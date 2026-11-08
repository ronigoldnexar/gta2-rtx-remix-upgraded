// See post_fx.h and docs/visuals-plain.md.
#include "post_fx.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "shaders/visuals_gen.h"

namespace gta2 {

void RendererTrace(const char* format, ...);   // renderer.cpp

namespace {

VisualsSettings g_visuals;
VisualLightProvider g_lightProvider = nullptr;
VisualsPollFn g_poll = nullptr;

constexpr D3DFORMAT kIntz = static_cast<D3DFORMAT>(MAKEFOURCC('I', 'N', 'T', 'Z'));
constexpr int kChunk = 16;             // blocks per side of a shadow chunk
constexpr int kMaxCasters = 900;
constexpr int kCellPx = 64;            // the game's tile size
constexpr int kShadowVertexFloats = 5;  // the world's shadow vertex: x y z, and u v in the alpha atlas
constexpr DWORD kShadowWorldFvf = D3DFVF_XYZ | D3DFVF_TEX1;

// --- Matrices (row vectors, m[row][col], as math3d.h) ------------------------
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
// Inverse of a rigid transform (rotation + translation), which every view matrix here is.
Mat4 InverseRigid(const Mat4& v) {
    Mat4 r;
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j) r.m[i][j] = v.m[j][i];
    for (int j = 0; j < 3; ++j) r.m[3][j] = -(v.m[3][0] * r.m[0][j] + v.m[3][1] * r.m[1][j] + v.m[3][2] * r.m[2][j]);
    r.m[3][3] = 1.0f;
    return r;
}
Vec3 XformPoint(const Mat4& m, const Vec3& p) {
    return {p.x * m.m[0][0] + p.y * m.m[1][0] + p.z * m.m[2][0] + m.m[3][0],
            p.x * m.m[0][1] + p.y * m.m[1][1] + p.z * m.m[2][1] + m.m[3][1],
            p.x * m.m[0][2] + p.y * m.m[1][2] + p.z * m.m[2][2] + m.m[3][2]};
}
Vec3 XformDir(const Mat4& m, const Vec3& p) {
    return {p.x * m.m[0][0] + p.y * m.m[1][0] + p.z * m.m[2][0], p.x * m.m[0][1] + p.y * m.m[1][1] + p.z * m.m[2][1],
            p.x * m.m[0][2] + p.y * m.m[1][2] + p.z * m.m[2][2]};
}
float Smooth(float a, float b, float x) {
    float t = (x - a) / (b - a);
    t = t < 0.0f ? 0.0f : (t > 1.0f ? 1.0f : t);
    return t * t * (3.0f - 2.0f * t);
}
double NowMs() {
    static double toMs = 0.0;
    LARGE_INTEGER t;
    if (toMs == 0.0) { QueryPerformanceFrequency(&t); toMs = 1000.0 / static_cast<double>(t.QuadPart); }
    QueryPerformanceCounter(&t);
    return static_cast<double>(t.QuadPart) * toMs;
}

// --- The draw hook ---------------------------------------------------------
// Draw calls are recorded between StartRecording and Resolve: every depth-writing
// triangle draw of the cars, people and props, to be replayed from the sun. The
// slots are IDirect3DDevice9's DrawPrimitive (81) and DrawIndexedPrimitive (82);
// frame_log.cpp patches the same table and chains in either order.
using DipFn = HRESULT(WINAPI*)(IDirect3DDevice9*, D3DPRIMITIVETYPE, INT, UINT, UINT, UINT, UINT);
using DpFn = HRESULT(WINAPI*)(IDirect3DDevice9*, D3DPRIMITIVETYPE, UINT, UINT);
DipFn g_origDip = nullptr;
DpFn g_origDp = nullptr;
PostFx* g_recorder = nullptr;
void** g_hookedVtbl = nullptr;

HRESULT WINAPI HookDip(IDirect3DDevice9* d, D3DPRIMITIVETYPE t, INT base, UINT minIdx, UINT nv, UINT start, UINT prims) {
    if (g_recorder && g_recorder->recording_) g_recorder->Record(d, true, t, base, minIdx, nv, start, prims);
    return g_origDip(d, t, base, minIdx, nv, start, prims);
}
HRESULT WINAPI HookDp(IDirect3DDevice9* d, D3DPRIMITIVETYPE t, UINT start, UINT prims) {
    if (g_recorder && g_recorder->recording_) g_recorder->Record(d, false, t, 0, 0, 0, start, prims);
    return g_origDp(d, t, start, prims);
}
void InstallHook(IDirect3DDevice9* device) {
    void** vt = *reinterpret_cast<void***>(device);
    if (vt == g_hookedVtbl) return;
    DWORD old = 0;
    if (!VirtualProtect(&vt[81], sizeof(void*) * 2, PAGE_EXECUTE_READWRITE, &old)) {
        RendererTrace("visuals: the device's draw table is not writable; shadows from the world only");
        return;
    }
    if (vt[82] != reinterpret_cast<void*>(&HookDip)) { g_origDip = reinterpret_cast<DipFn>(vt[82]); vt[82] = reinterpret_cast<void*>(&HookDip); }
    if (vt[81] != reinterpret_cast<void*>(&HookDp)) { g_origDp = reinterpret_cast<DpFn>(vt[81]); vt[81] = reinterpret_cast<void*>(&HookDp); }
    VirtualProtect(&vt[81], sizeof(void*) * 2, old, &old);
    g_hookedVtbl = vt;
}

template <typename T> void SafeRelease(T*& p) { if (p) { p->Release(); p = nullptr; } }

struct QuadVertex { float x, y, z, w, u, v; };
struct LightVertex { float x, y, z, w; float p[4]; float c[4]; float s[4]; };

}  // namespace

VisualsSettings& VisualsConfig() { return g_visuals; }
void SetVisualLightProvider(VisualLightProvider fn) { g_lightProvider = fn; }
void SetVisualsPoll(VisualsPollFn fn) { g_poll = fn; }
void VisualsPoll() { if (g_poll) g_poll(); }

void PostFx::Init(IDirect3DDevice9* device, int width, int height, bool remix) {
    if (device_ != device) Release();
    device_ = device;
    width_ = width;
    height_ = height;
    remix_ = remix;
    if (remix) {
        RendererTrace("visuals: RTX Remix device: shadows, AO, bloom and the night lights stay off (Remix lights the scene)");
        return;
    }
    InstallHook(device);
    g_recorder = this;
}

void PostFx::ReleaseTargets() {
    SafeRelease(sceneSurf_); SafeRelease(sceneTex_);
    SafeRelease(depthSurf_); SafeRelease(depthTex_);
    SafeRelease(litSurf_); SafeRelease(litTex_);
    SafeRelease(aoSurf_); SafeRelease(aoTex_);
    SafeRelease(aoBlurSurf_); SafeRelease(aoBlurTex_);
    for (int i = 0; i < 4; ++i) { SafeRelease(bloomSurf_[i]); SafeRelease(bloomTex_[i]); }
    SafeRelease(shadowSurf_); SafeRelease(shadowTex_); SafeRelease(shadowDepth_);
    SafeRelease(blackTex_);
    SafeRelease(whiteTex_);
    SafeRelease(maskSurf_); SafeRelease(maskTex_);
    SafeRelease(psShadowmask_);
    SafeRelease(stateBlock_);
    SafeRelease(vsShadowWorld_); SafeRelease(vsShadowModel_); SafeRelease(vsQuad_); SafeRelease(vsLight_);
    SafeRelease(psShadowWorld_); SafeRelease(psShadowSolid_); SafeRelease(psShadowCutout_);
    SafeRelease(psComposite_); SafeRelease(psSsao8_); SafeRelease(psSsao12_); SafeRelease(psAoBlur_);
    SafeRelease(psLight_); SafeRelease(psBright_); SafeRelease(psBlur_); SafeRelease(psFinal_);
    SafeRelease(quadDecl_); SafeRelease(lightDecl_); SafeRelease(shadowWorldDecl_);
    for (int f = 0; f < 4; ++f) {
        for (int s = 0; s < 4; ++s) SafeRelease(tsQuery_[f][s]);
        SafeRelease(tsDisjoint_[f]); SafeRelease(tsFreq_[f]);
        tsIssued_[f] = false;
    }
}

void PostFx::ReleaseWorld() {
    SafeRelease(worldVb_);
    SafeRelease(cellVb_);
    SafeRelease(shadowIb_);
    SafeRelease(alphaAtlas_);
    chunks_.clear();
    worldVertexCount_ = 0;
    worldIndexCount_ = 0;
}

void PostFx::Release() {
    ClearCasters();
    SafeRelease(savedTarget_);
    SafeRelease(savedDepth_);
    ReleaseTargets();
    ReleaseWorld();
    if (g_recorder == this) g_recorder = nullptr;
    active_ = false;
    recording_ = false;
    device_ = nullptr;
}

void PostFx::ClearCasters() {
    for (Caster& c : casters_) {
        SafeRelease(c.vb); SafeRelease(c.ib); SafeRelease(c.decl); SafeRelease(c.tex);
    }
    casters_.clear();
}

bool PostFx::EnsureTargets() {
    if (sceneTex_ && hdrWanted_ != g_visuals.hdr) ReleaseTargets();
    if (sceneTex_) return true;
    hdrWanted_ = g_visuals.hdr;
    if (!ok_) return false;
    IDirect3D9* d3d = nullptr;
    device_->GetDirect3D(&d3d);
    D3DDISPLAYMODE mode = {};
    device_->GetDisplayMode(0, &mode);
    const D3DFORMAT adapterFormat = mode.Format != D3DFMT_UNKNOWN ? mode.Format : D3DFMT_X8R8G8B8;
    auto supports = [&](DWORD usage, D3DRESOURCETYPE type, D3DFORMAT f) {
        return d3d && SUCCEEDED(d3d->CheckDeviceFormat(D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, adapterFormat, usage, type, f));
    };
    const bool intz = supports(D3DUSAGE_DEPTHSTENCIL, D3DRTYPE_TEXTURE, kIntz);
    const bool fp16 = supports(D3DUSAGE_RENDERTARGET, D3DRTYPE_TEXTURE, D3DFMT_A16B16G16R16F);
    const bool r32f = supports(D3DUSAGE_RENDERTARGET, D3DRTYPE_TEXTURE, D3DFMT_R32F);
    if (d3d) d3d->Release();
    if (!loggedFormats_) {
        loggedFormats_ = true;
        RendererTrace("visuals: formats INTZ %s, FP16 target %s, R32F target %s", intz ? "yes" : "no", fp16 ? "yes" : "no",
                      r32f ? "yes" : "no");
    }
    if (!intz) {
        ok_ = false;
        RendererTrace("visuals: no INTZ depth texture on this device; the plain renderer's post passes stay off");
        return false;
    }
    hdrFormat_ = fp16 && g_visuals.hdr ? D3DFMT_A16B16G16R16F : D3DFMT_A8R8G8B8;
    const int w = width_, h = height_;
    const int qw = std::max(1, w / 4), qh = std::max(1, h / 4), ew = std::max(1, w / 8), eh = std::max(1, h / 8);
    bool good = true;
    auto rt = [&](int tw, int th, D3DFORMAT f, IDirect3DTexture9** t, IDirect3DSurface9** s) {
        if (!good) return;
        if (FAILED(device_->CreateTexture(tw, th, 1, D3DUSAGE_RENDERTARGET, f, D3DPOOL_DEFAULT, t, nullptr)) ||
            FAILED((*t)->GetSurfaceLevel(0, s))) good = false;
    };
    rt(w, h, hdrFormat_, &sceneTex_, &sceneSurf_);
    rt(w, h, hdrFormat_, &litTex_, &litSurf_);
    rt(w, h, D3DFMT_A8R8G8B8, &maskTex_, &maskSurf_);
    rt(w / 2, h / 2, D3DFMT_A8R8G8B8, &aoTex_, &aoSurf_);
    rt(w / 2, h / 2, D3DFMT_A8R8G8B8, &aoBlurTex_, &aoBlurSurf_);
    rt(qw, qh, hdrFormat_, &bloomTex_[0], &bloomSurf_[0]);
    rt(qw, qh, hdrFormat_, &bloomTex_[1], &bloomSurf_[1]);
    rt(ew, eh, hdrFormat_, &bloomTex_[2], &bloomSurf_[2]);
    rt(ew, eh, hdrFormat_, &bloomTex_[3], &bloomSurf_[3]);
    rt(shadowSize_, shadowSize_, r32f ? D3DFMT_R32F : D3DFMT_A16B16G16R16F, &shadowTex_, &shadowSurf_);
    if (good && (FAILED(device_->CreateTexture(w, h, 1, D3DUSAGE_DEPTHSTENCIL, kIntz, D3DPOOL_DEFAULT, &depthTex_, nullptr)) ||
                 FAILED(depthTex_->GetSurfaceLevel(0, &depthSurf_)))) good = false;
    if (good && FAILED(device_->CreateDepthStencilSurface(shadowSize_, shadowSize_, D3DFMT_D24X8, D3DMULTISAMPLE_NONE, 0, TRUE,
                                                          &shadowDepth_, nullptr))) good = false;
    auto solid = [&](IDirect3DTexture9** t, DWORD colour) {
        if (good && SUCCEEDED(device_->CreateTexture(1, 1, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, t, nullptr))) {
            D3DLOCKED_RECT r;
            if (SUCCEEDED((*t)->LockRect(0, &r, nullptr, 0))) { *static_cast<DWORD*>(r.pBits) = colour; (*t)->UnlockRect(0); }
        }
    };
    solid(&blackTex_, 0xFF000000u);
    solid(&whiteTex_, 0xFFFFFFFFu);
    auto vs = [&](const DWORD* code, IDirect3DVertexShader9** out) { if (good && FAILED(device_->CreateVertexShader(code, out))) good = false; };
    auto ps = [&](const DWORD* code, IDirect3DPixelShader9** out) { if (good && FAILED(device_->CreatePixelShader(code, out))) good = false; };
    vs(k_vs_shadow_world, &vsShadowWorld_);
    vs(k_vs_shadow_model, &vsShadowModel_);
    vs(k_vs_quad, &vsQuad_);
    vs(k_vs_light, &vsLight_);
    ps(k_ps_shadow_world, &psShadowWorld_);
    ps(k_ps_shadow_solid, &psShadowSolid_);
    ps(k_ps_shadow_cutout, &psShadowCutout_);
    ps(k_ps_shadowmask, &psShadowmask_);
    ps(k_ps_composite, &psComposite_);
    ps(k_ps_ssao8, &psSsao8_);
    ps(k_ps_ssao12, &psSsao12_);
    ps(k_ps_ao_blur, &psAoBlur_);
    ps(k_ps_light, &psLight_);
    ps(k_ps_bright, &psBright_);
    ps(k_ps_blur, &psBlur_);
    ps(k_ps_final, &psFinal_);
    const D3DVERTEXELEMENT9 quad[] = {{0, 0, D3DDECLTYPE_FLOAT4, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_POSITION, 0},
                                      {0, 16, D3DDECLTYPE_FLOAT2, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_TEXCOORD, 0},
                                      D3DDECL_END()};
    const D3DVERTEXELEMENT9 light[] = {{0, 0, D3DDECLTYPE_FLOAT4, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_POSITION, 0},
                                       {0, 16, D3DDECLTYPE_FLOAT4, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_TEXCOORD, 0},
                                       {0, 32, D3DDECLTYPE_FLOAT4, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_TEXCOORD, 1},
                                       {0, 48, D3DDECLTYPE_FLOAT4, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_TEXCOORD, 2},
                                       D3DDECL_END()};
    const D3DVERTEXELEMENT9 world[] = {{0, 0, D3DDECLTYPE_FLOAT3, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_POSITION, 0},
                                       {0, 12, D3DDECLTYPE_FLOAT2, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_TEXCOORD, 0},
                                       {0, 20, D3DDECLTYPE_FLOAT2, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_TEXCOORD, 1},
                                       D3DDECL_END()};
    if (good && FAILED(device_->CreateVertexDeclaration(quad, &quadDecl_))) good = false;
    if (good && FAILED(device_->CreateVertexDeclaration(light, &lightDecl_))) good = false;
    if (good && FAILED(device_->CreateVertexDeclaration(world, &shadowWorldDecl_))) good = false;
    if (good && FAILED(device_->CreateStateBlock(D3DSBT_ALL, &stateBlock_))) good = false;
    if (!good) {
        RendererTrace("visuals: could not create the post targets or shaders; the post passes stay off");
        ReleaseTargets();
        ok_ = false;
        return false;
    }
    for (int f = 0; f < 4 && tsOk_; ++f) {
        for (int s = 0; s < 4; ++s)
            if (FAILED(device_->CreateQuery(D3DQUERYTYPE_TIMESTAMP, &tsQuery_[f][s]))) tsOk_ = false;
        if (FAILED(device_->CreateQuery(D3DQUERYTYPE_TIMESTAMPDISJOINT, &tsDisjoint_[f])) ||
            FAILED(device_->CreateQuery(D3DQUERYTYPE_TIMESTAMPFREQ, &tsFreq_[f]))) tsOk_ = false;
    }
    RendererTrace("visuals: post targets %dx%d (%s), shadow atlas %d px, GPU timestamps %s", w, h,
                  hdrFormat_ == D3DFMT_A16B16G16R16F ? "FP16" : "8-bit", shadowSize_, tsOk_ ? "on" : "unavailable");
    return true;
}

// --- The world's shadow copy ------------------------------------------------
void PostFx::BuildWorld(const WorldMesh& mesh, const Style& style, IDirect3DVertexBuffer9* worldVb) {
    ReleaseWorld();
    if (!device_ || remix_ || !worldVb || mesh.vertices.empty()) return;
    const double t0 = NowMs();
    worldVb_ = worldVb;
    worldVb_->AddRef();
    worldVertexCount_ = static_cast<UINT>(mesh.vertices.size());

    // Cutout tiles get a cell of the alpha atlas; cell 0 is solid.
    std::vector<int> cellOf;
    std::vector<int> cutoutTiles;
    for (const TileBatch& b : mesh.batches) {
        if (!b.needsAlphaTest || b.tile < 0 || b.tile >= style.TileCount()) continue;
        if (b.tile >= static_cast<int>(cellOf.size())) cellOf.resize(static_cast<size_t>(b.tile) + 1, -1);
        if (cellOf[static_cast<size_t>(b.tile)] < 0) {
            cellOf[static_cast<size_t>(b.tile)] = static_cast<int>(cutoutTiles.size()) + 1;
            cutoutTiles.push_back(b.tile);
        }
    }
    int side = 1;
    while (side * side < static_cast<int>(cutoutTiles.size()) + 1) side *= 2;
    const int atlasPx = side * kCellPx;
    atlasCell_ = 1.0f / static_cast<float>(side);
    if (SUCCEEDED(device_->CreateTexture(atlasPx, atlasPx, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &alphaAtlas_, nullptr))) {
        D3DLOCKED_RECT r;
        if (SUCCEEDED(alphaAtlas_->LockRect(0, &r, nullptr, 0))) {
            for (int y = 0; y < atlasPx; ++y) memset(static_cast<uint8_t*>(r.pBits) + y * r.Pitch, 0xFF, static_cast<size_t>(atlasPx) * 4);
            for (size_t i = 0; i < cutoutTiles.size(); ++i) {
                const Tile& t = style.GetTile(cutoutTiles[i]);
                if (t.pixels.size() < static_cast<size_t>(kCellPx) * kCellPx) continue;
                const int c = static_cast<int>(i) + 1, cx = (c % side) * kCellPx, cy = (c / side) * kCellPx;
                for (int y = 0; y < kCellPx; ++y) {
                    uint32_t* row = reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(r.pBits) + (cy + y) * r.Pitch) + cx;
                    for (int x = 0; x < kCellPx; ++x) row[x] = (t.pixels[static_cast<size_t>(y) * kCellPx + x] & 0xFF000000u) | 0x00FFFFFFu;
                }
            }
            alphaAtlas_->UnlockRect(0);
        }
    }
    // The shadow copy of the vertices: position and the uv already moved into the alpha
    // atlas, (cell + clamp(uv, 0.01, 0.99)) * cell size, so the pass needs no per-vertex cell
    // (the first version interpolated the cell as a second texcoord and, under Wine 9, every
    // cutout triangle was clipped: fences cast nothing, out/vp2_dbg5). A face's uv stays within
    // its tile, so the interpolated atlas uv stays inside the cell. Solid vertices sample cell 0
    // (opaque) but are drawn with the plain depth shader anyway.
    const float cellSize = 1.0f / static_cast<float>(side);
    std::vector<float> cells(mesh.vertices.size() * kShadowVertexFloats, 0.0f);
    std::vector<uint8_t> cutVertex(mesh.vertices.size(), 0);
    for (size_t v = 0; v < mesh.vertices.size(); ++v) {
        const Vertex& src = mesh.vertices[v];
        float* d = &cells[v * kShadowVertexFloats];
        d[0] = src.x; d[1] = src.y; d[2] = src.z;
        d[3] = std::min(0.99f, std::max(0.01f, src.u)) * cellSize;
        d[4] = std::min(0.99f, std::max(0.01f, src.v)) * cellSize;
    }
    for (const TileBatch& b : mesh.batches) {
        if (!b.needsAlphaTest || b.tile < 0 || b.tile >= static_cast<int>(cellOf.size()) || cellOf[static_cast<size_t>(b.tile)] < 0) continue;
        const int c = cellOf[static_cast<size_t>(b.tile)];
        for (uint32_t v = b.vertexStart; v < b.vertexStart + b.vertexCount && v < mesh.vertices.size(); ++v) {
            cells[v * kShadowVertexFloats + 3] += static_cast<float>(c % side) * cellSize;
            cells[v * kShadowVertexFloats + 4] += static_cast<float>(c / side) * cellSize;
            cutVertex[v] = 1;
        }
    }
    // Triangles by map chunk (of the centroid), row by row.
    float lo[3] = {1e9f, 1e9f, 1e9f}, hi[3] = {-1e9f, -1e9f, -1e9f};
    for (const Vertex& v : mesh.vertices) {
        lo[0] = std::min(lo[0], v.x); lo[1] = std::min(lo[1], v.y); lo[2] = std::min(lo[2], v.z);
        hi[0] = std::max(hi[0], v.x); hi[1] = std::max(hi[1], v.y); hi[2] = std::max(hi[2], v.z);
    }
    const float ox = std::floor(lo[0]), oz = std::floor(lo[2]);
    chunksX_ = std::max(1, static_cast<int>(std::ceil((hi[0] - ox) / kChunk)) + 1);
    chunksZ_ = std::max(1, static_cast<int>(std::ceil((hi[2] - oz) / kChunk)) + 1);
    const size_t triCount = mesh.indices.size() / 3;
    // Two sets of chunks: the solid triangles (drawn without a texture fetch), then the
    // cutout ones (fences, grilles: the alpha atlas). Each set is in chunk order, so the
    // chunks a cascade touches still merge into runs.
    const size_t nChunks = static_cast<size_t>(chunksX_) * chunksZ_;
    std::vector<int> chunkOf(triCount);
    std::vector<uint32_t> perChunk(nChunks * 2 + 1, 0);
    size_t cutoutTris = 0;
    for (size_t t = 0; t < triCount; ++t) {
        const Vertex& a = mesh.vertices[mesh.indices[t * 3]];
        const Vertex& b = mesh.vertices[mesh.indices[t * 3 + 1]];
        const Vertex& c = mesh.vertices[mesh.indices[t * 3 + 2]];
        const int cx = std::min(chunksX_ - 1, std::max(0, static_cast<int>(((a.x + b.x + c.x) / 3.0f - ox) / kChunk)));
        const int cz = std::min(chunksZ_ - 1, std::max(0, static_cast<int>(((a.z + b.z + c.z) / 3.0f - oz) / kChunk)));
        const bool cut = cutVertex[mesh.indices[t * 3]] != 0;
        cutoutTris += cut ? 1 : 0;
        chunkOf[t] = (cut ? static_cast<int>(nChunks) : 0) + cz * chunksX_ + cx;
        ++perChunk[static_cast<size_t>(chunkOf[t])];
    }
    chunks_.assign(nChunks * 2, Chunk{});
    uint32_t run = 0;
    for (size_t i = 0; i < chunks_.size(); ++i) {
        chunks_[i].start = run;
        chunks_[i].count = 0;
        run += perChunk[i] * 3;
        for (int k = 0; k < 3; ++k) { chunks_[i].lo[k] = 1e9f; chunks_[i].hi[k] = -1e9f; }
    }
    std::vector<uint32_t> sorted(mesh.indices.size());
    for (size_t t = 0; t < triCount; ++t) {
        Chunk& ch = chunks_[static_cast<size_t>(chunkOf[t])];
        for (int k = 0; k < 3; ++k) {
            const uint32_t idx = mesh.indices[t * 3 + k];
            sorted[ch.start + ch.count++] = idx;
            const Vertex& v = mesh.vertices[idx];
            ch.lo[0] = std::min(ch.lo[0], v.x); ch.lo[1] = std::min(ch.lo[1], v.y); ch.lo[2] = std::min(ch.lo[2], v.z);
            ch.hi[0] = std::max(ch.hi[0], v.x); ch.hi[1] = std::max(ch.hi[1], v.y); ch.hi[2] = std::max(ch.hi[2], v.z);
        }
    }
    bool good = true;
    void* dest = nullptr;
    if (FAILED(device_->CreateVertexBuffer(static_cast<UINT>(cells.size() * sizeof(float)), D3DUSAGE_WRITEONLY, kShadowWorldFvf, D3DPOOL_MANAGED,
                                           &cellVb_, nullptr)) || FAILED(cellVb_->Lock(0, 0, &dest, 0))) {
        good = false;
    } else {
        memcpy(dest, cells.data(), cells.size() * sizeof(float));
        cellVb_->Unlock();
    }
    if (good && (FAILED(device_->CreateIndexBuffer(static_cast<UINT>(sorted.size() * 4), D3DUSAGE_WRITEONLY, D3DFMT_INDEX32,
                                                   D3DPOOL_MANAGED, &shadowIb_, nullptr)) || FAILED(shadowIb_->Lock(0, 0, &dest, 0)))) {
        good = false;
    } else if (good) {
        memcpy(dest, sorted.data(), sorted.size() * 4);
        shadowIb_->Unlock();
    }
    if (!good || !alphaAtlas_) {
        RendererTrace("visuals: the world's shadow copy could not be built; shadows off for this level");
        ReleaseWorld();
        return;
    }
    worldIndexCount_ = static_cast<UINT>(sorted.size());
    // Read the alpha atlas back: cell 0 must be opaque, or every world triangle is cut away.
    int solidAlpha = -1;
    double cutCover = -1.0;
    {
        D3DLOCKED_RECT r;
        if (SUCCEEDED(alphaAtlas_->LockRect(0, &r, nullptr, D3DLOCK_READONLY))) {
            solidAlpha = static_cast<int>(reinterpret_cast<const uint32_t*>(r.pBits)[kCellPx / 2 + (kCellPx / 2) * (r.Pitch / 4)] >> 24);
            if (!cutoutTiles.empty()) {
                size_t opaque = 0;
                for (int y = 0; y < kCellPx; ++y)
                    for (int x = 0; x < kCellPx; ++x)
                        opaque += (reinterpret_cast<const uint32_t*>(static_cast<const uint8_t*>(r.pBits) + y * r.Pitch)[kCellPx + x] >> 24) >= 128;
                cutCover = 100.0 * static_cast<double>(opaque) / (kCellPx * kCellPx);
            }
            alphaAtlas_->UnlockRect(0);
        }
    }
    RendererTrace("visuals: world shadow copy: %u vertices, %zu triangles (%zu cutout) in %dx%d chunks, %zu cutout tiles in a %d px alpha atlas "
                  "(solid cell alpha %d, first cutout cell %.0f%% opaque), %.0f ms",
                  worldVertexCount_, triCount, cutoutTris, chunksX_, chunksZ_, cutoutTiles.size(), atlasPx, solidAlpha, cutCover, NowMs() - t0);
}

// --- A frame ---------------------------------------------------------------
bool PostFx::BeginScene(const PostFrame& frame) {
    active_ = false;
    recording_ = false;
    if (!Available() || !g_visuals.enabled || frame.blend <= 0.002f) return false;
    if (!EnsureTargets()) return false;
    SafeRelease(savedTarget_);
    SafeRelease(savedDepth_);
    if (FAILED(device_->GetRenderTarget(0, &savedTarget_))) return false;
    device_->GetDepthStencilSurface(&savedDepth_);
    device_->SetRenderTarget(0, sceneSurf_);
    device_->SetDepthStencilSurface(depthSurf_);
    // The city sweep's diagnostic clear (Renderer::BeginFrame) holds here too.
    static int magenta = -1;
    if (magenta < 0) { char buf[8] = {}; magenta = GetEnvironmentVariableA("GTA2DX9_CLEAR_MAGENTA", buf, sizeof buf) && buf[0] == '1'; }
    device_->Clear(0, nullptr, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, magenta ? 0xFFFF00FFu : 0xFF000000u, 1.0f, 0);
    frame_ = frame;
    ClearCasters();
    active_ = true;
    return true;
}

void PostFx::SetCamera(const Mat4& view, const Mat4& proj, const Vec3& eye, float fovY, float aspect) {
    view_ = view;
    proj_ = proj;
    invView_ = InverseRigid(view);
    eye_ = eye;
    fovY_ = fovY;
    aspect_ = aspect;
}

void PostFx::SetSky(const Vec3& zenith, const Vec3& horizon, float day) {
    // From above, the sky's own hue at unit brightness, half way to white; from below
    // a warm bounce off the street. Both near 1, so the term tints rather than darkens.
    const Vec3 sky = zenith * 0.6f + horizon * 0.4f;
    const float l = std::max(0.02f, 0.2126f * sky.x + 0.7152f * sky.y + 0.0722f * sky.z);
    const Vec3 hue = sky * (1.0f / l);
    const Vec3 white{1.0f, 1.0f, 1.0f};
    frame_.skyTint = (white * 0.55f + hue * 0.45f) * 1.04f;
    frame_.groundTint = Vec3{1.0f, 0.93f, 0.84f} * (0.80f + 0.06f * day);
    frame_.day = day;
}

void PostFx::StartRecording() {
    recording_ = active_ && g_visuals.shadows && frame_.sunLevel > 0.01f && frame_.sunDir.y > -0.02f;
}

void PostFx::Record(IDirect3DDevice9* d, bool indexed, D3DPRIMITIVETYPE type, INT base, UINT minIdx, UINT numVerts,
                    UINT start, UINT prims) {
    if (d != device_ || prims == 0 || static_cast<int>(casters_.size()) >= kMaxCasters) return;
    if (type != D3DPT_TRIANGLELIST && type != D3DPT_TRIANGLESTRIP && type != D3DPT_TRIANGLEFAN) return;
    DWORD z = 0, zw = 0, blend = 0, atest = 0, aref = 0;
    d->GetRenderState(D3DRS_ZENABLE, &z);
    d->GetRenderState(D3DRS_ZWRITEENABLE, &zw);
    if (!z || !zw) return;   // glows, decals, overlays: no shadow
    d->GetRenderState(D3DRS_ALPHABLENDENABLE, &blend);
    d->GetRenderState(D3DRS_ALPHATESTENABLE, &atest);
    if (blend && !atest) return;
    IDirect3DVertexShader9* shader = nullptr;
    d->GetVertexShader(&shader);
    if (shader) { shader->Release(); return; }
    Caster c;
    d->GetFVF(&c.fvf);
    if (c.fvf) {
        if ((c.fvf & D3DFVF_POSITION_MASK) != D3DFVF_XYZ) return;
    } else {
        d->GetVertexDeclaration(&c.decl);
        if (!c.decl) return;
    }
    if (FAILED(d->GetStreamSource(0, &c.vb, &c.offset, &c.stride)) || !c.vb) { SafeRelease(c.decl); return; }
    if (indexed && (FAILED(d->GetIndices(&c.ib)) || !c.ib)) { SafeRelease(c.decl); SafeRelease(c.vb); return; }
    if (atest) {
        d->GetRenderState(D3DRS_ALPHAREF, &aref);
        d->GetTexture(0, &c.tex);
        c.alphaRef = static_cast<float>(aref) / 255.0f;
    }
    d->GetTransform(D3DTS_WORLD, &c.world);
    c.centre = {c.world._41, c.world._42, c.world._43};
    c.anywhere = std::fabs(c.world._41) + std::fabs(c.world._42) + std::fabs(c.world._43) < 1e-3f;
    c.type = type;
    c.base = base;
    c.minIdx = minIdx;
    c.numVerts = numVerts;
    c.start = start;
    c.prims = prims;
    c.indexed = indexed;
    casters_.push_back(c);
}

void PostFx::SetTarget(IDirect3DSurface9* s, int w, int h) {
    device_->SetRenderTarget(0, s);
    D3DVIEWPORT9 vp = {0, 0, static_cast<DWORD>(w), static_cast<DWORD>(h), 0.0f, 1.0f};
    device_->SetViewport(&vp);
}

void PostFx::DrawQuad(int w, int h) {
    const float dx = 1.0f / static_cast<float>(w), dy = 1.0f / static_cast<float>(h);
    const QuadVertex q[4] = {{-1.0f - dx, 1.0f + dy, 0.5f, 1.0f, 0.0f, 0.0f},
                             {1.0f - dx, 1.0f + dy, 0.5f, 1.0f, 1.0f, 0.0f},
                             {-1.0f - dx, -1.0f + dy, 0.5f, 1.0f, 0.0f, 1.0f},
                             {1.0f - dx, -1.0f + dy, 0.5f, 1.0f, 1.0f, 1.0f}};
    device_->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, q, sizeof(QuadVertex));
}

void PostFx::Timestamp(int slot) {
    if (!tsOk_ || !tsQuery_[tsFrame_ & 3][slot]) return;
    tsQuery_[tsFrame_ & 3][slot]->Issue(D3DISSUE_END);
}

void PostFx::ReadTimestamps() {
    if (!tsOk_) return;
    const int f = (tsFrame_ + 1) & 3;   // the oldest of the ring: issued three frames ago
    if (!tsIssued_[f]) return;
    tsIssued_[f] = false;
    BOOL disjoint = TRUE;
    UINT64 freq = 0, t[3] = {};
    if (tsDisjoint_[f]->GetData(&disjoint, sizeof disjoint, 0) != S_OK || disjoint) return;
    if (tsFreq_[f]->GetData(&freq, sizeof freq, 0) != S_OK || !freq) return;
    for (int s = 0; s < 3; ++s)
        if (tsQuery_[f][s]->GetData(&t[s], sizeof t[s], 0) != S_OK) return;
    stats_.gpuShadowMs = static_cast<double>(t[1] - t[0]) * 1000.0 / static_cast<double>(freq);
    stats_.gpuPostMs = static_cast<double>(t[2] - t[1]) * 1000.0 / static_cast<double>(freq);
}

void PostFx::RenderShadows(int cascades, const Vec3& sunDirIn) {
    // The shadows' sun never lies flatter than 10 degrees: lower, every street is in
    // shadow anyway and the maps would only stretch.
    Vec3 sunDir = sunDirIn;
    const float minY = std::sin(10.0f * 3.14159265f / 180.0f);
    if (sunDir.y < minY) {
        const float h = std::sqrt(std::max(1e-6f, sunDir.x * sunDir.x + sunDir.z * sunDir.z));
        const float c = std::sqrt(1.0f - minY * minY);
        sunDir = {sunDir.x / h * c, minY, sunDir.z / h * c};
    }
    static const float kSplits[3][3] = {{30.0f, 0.0f, 0.0f}, {14.0f, 56.0f, 0.0f}, {9.0f, 28.0f, 85.0f}};
    const int q = std::max(0, std::min(2, g_visuals.quality));
    const int cell = shadowSize_ / 2;
    const float tanY = std::tan(fovY_ * 0.5f), tanX = tanY * aspect_;
    const float k2 = tanX * tanX + tanY * tanY;
    const Vec3 fwd = Normalize(Vec3{invView_.m[2][0], invView_.m[2][1], invView_.m[2][2]});
    const Vec3 up0 = std::fabs(sunDir.y) > 0.99f ? Vec3{0.0f, 0.0f, 1.0f} : Vec3{0.0f, 1.0f, 0.0f};
    const Mat4 rot = LookAtLH(Vec3{0.0f, 0.0f, 0.0f}, sunDir * -1.0f, up0);

    device_->SetDepthStencilSurface(shadowDepth_);
    SetTarget(shadowSurf_, shadowSize_, shadowSize_);
    device_->Clear(0, nullptr, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, 0xFFFFFFFFu, 1.0f, 0);
    device_->SetRenderState(D3DRS_ZENABLE, D3DZB_TRUE);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, TRUE);
    device_->SetRenderState(D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    device_->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device_->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device_->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device_->SetRenderState(D3DRS_FOGENABLE, FALSE);
    device_->SetRenderState(D3DRS_STENCILENABLE, FALSE);
    device_->SetRenderState(D3DRS_SCISSORTESTENABLE, FALSE);
    device_->SetRenderState(D3DRS_CLIPPLANEENABLE, 0);
    device_->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
    device_->SetRenderState(D3DRS_FILLMODE, D3DFILL_SOLID);
    device_->SetRenderState(D3DRS_DEPTHBIAS, 0);
    device_->SetRenderState(D3DRS_SLOPESCALEDEPTHBIAS, 0);
    for (DWORD s = 0; s < 4; ++s) {
        device_->SetSamplerState(s, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
        device_->SetSamplerState(s, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
        device_->SetSamplerState(s, D3DSAMP_MINFILTER, D3DTEXF_POINT);
        device_->SetSamplerState(s, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
        device_->SetSamplerState(s, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
        device_->SetSamplerState(s, D3DSAMP_SRGBTEXTURE, FALSE);
    }

    stats_.cascades = cascades;
    float nearZ = 0.05f;
    for (int k = 0; k < cascades; ++k) {
        Cascade& cs = cascades_[k];
        const float f = kSplits[q][k];
        float c = (nearZ + f) * (1.0f + k2) * 0.5f, r;
        if (c >= f) { c = f; r = f * std::sqrt(k2); }
        else r = std::sqrt((f - c) * (f - c) + f * f * k2);
        r = std::ceil(r * 2.0f) * 0.5f + 0.5f;   // quantised: the map's scale never creeps with the FOV
        cs.radius = r;
        cs.farZ = f;
        cs.texelWorld = 2.0f * r / static_cast<float>(cell);
        const Vec3 centre = eye_ + fwd * c;
        Vec3 ls = XformPoint(rot, centre);
        ls.x = std::floor(ls.x / cs.texelWorld) * cs.texelWorld;
        ls.y = std::floor(ls.y / cs.texelWorld) * cs.texelWorld;
        const float back = r + 60.0f;   // room toward the sun for casters outside the slice
        const float range = back + r + 12.0f;
        Mat4 view = rot;
        view.m[3][0] = -ls.x;
        view.m[3][1] = -ls.y;
        view.m[3][2] = -(ls.z - back);
        Mat4 ortho;
        ortho.m[0][0] = 1.0f / r;
        ortho.m[1][1] = 1.0f / r;
        ortho.m[2][2] = 1.0f / range;
        ortho.m[3][3] = 1.0f;
        cs.lightView = view;
        cs.lightVP = Mul(view, ortho);
        cs.qx = k % 2;
        cs.qy = k / 2;
        const float s = 0.5f;   // a cell's share of the atlas
        Mat4 toAtlas;
        toAtlas.m[0][0] = 0.5f * s;
        toAtlas.m[1][1] = -0.5f * s;
        toAtlas.m[2][2] = 1.0f;
        toAtlas.m[3][0] = 0.5f * s + cs.qx * s;
        toAtlas.m[3][1] = 0.5f * s + cs.qy * s;
        toAtlas.m[3][3] = 1.0f;
        cs.viewToAtlas = Mul(Mul(invView_, cs.lightVP), toAtlas);
        nearZ = f;

        D3DVIEWPORT9 vp = {static_cast<DWORD>(cs.qx * cell), static_cast<DWORD>(cs.qy * cell), static_cast<DWORD>(cell),
                           static_cast<DWORD>(cell), 0.0f, 1.0f};
        device_->SetViewport(&vp);
        device_->SetVertexShaderConstantF(0, &cs.lightVP.m[0][0], 4);

        // The world: runs of consecutive chunks whose box reaches the cascade; the solid set
        // with the plain depth shader, then the cutout set through the alpha atlas.
        if (shadowIb_ && cellVb_ && worldVb_) {
            const int dbg = g_visuals.debug & 15;
            if (dbg == 9 || dbg == 11) {   // debug: the renderer's own buffer through the model path (no cutouts)
                device_->SetFVF(D3DFVF_XYZ | D3DFVF_NORMAL | D3DFVF_TEX1);
                device_->SetVertexShader(vsShadowModel_);
                const Mat4 ident = Identity();
                device_->SetVertexShaderConstantF(4, &ident.m[0][0], 4);
                device_->SetStreamSource(0, worldVb_, 0, sizeof(Vertex));
            } else {
                // The same path as a recorded cutout caster: FVF, the model shader, identity.
                device_->SetFVF(kShadowWorldFvf);
                device_->SetVertexShader(vsShadowModel_);
                const Mat4 ident = Identity();
                device_->SetVertexShaderConstantF(4, &ident.m[0][0], 4);
                device_->SetStreamSource(0, cellVb_, 0, kShadowVertexFloats * sizeof(float));
            }
            const float psc[4] = {0.0f, 0.5f, 0.0f, 0.0f};   // y: alpha reference of ps_shadow_cutout
            device_->SetPixelShaderConstantF(0, psc, 1);
            device_->SetTexture(0, alphaAtlas_);
            device_->SetIndices(shadowIb_);
            const size_t nChunks = chunks_.size() / 2;
            if (dbg == 10 || dbg == 11) {   // debug: the whole world in one draw, no chunk culling, no cutouts
                device_->SetPixelShader(psShadowSolid_);
                device_->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, 0, worldVertexCount_, 0, worldIndexCount_ / 3);
                ++stats_.worldDraws;
            } else {
                for (int set = 0; set < 2; ++set) {
                    // debug 8: everything solid; 12: the cutout set left out
                    if (set == 1 && dbg == 12) break;
                    device_->SetPixelShader(set == 0 || dbg == 8 || dbg == 9 ? psShadowSolid_ : psShadowCutout_);
                    uint32_t runStart = 0, runCount = 0;
                    auto flush = [&]() {
                        if (runCount) {
                            device_->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, 0, worldVertexCount_, runStart, runCount / 3);
                            ++stats_.worldDraws;
                        }
                        runCount = 0;
                    };
                    for (size_t ci = set * nChunks; ci < (set + 1) * nChunks; ++ci) {
                        const Chunk& ch = chunks_[ci];
                        bool hit = false;
                        if (ch.count) {
                            float mn[3] = {1e9f, 1e9f, 1e9f}, mx[3] = {-1e9f, -1e9f, -1e9f};
                            for (int i = 0; i < 8; ++i) {
                                const Vec3 p = XformPoint(view, Vec3{(i & 1) ? ch.hi[0] : ch.lo[0], (i & 2) ? ch.hi[1] : ch.lo[1],
                                                                     (i & 4) ? ch.hi[2] : ch.lo[2]});
                                mn[0] = std::min(mn[0], p.x); mn[1] = std::min(mn[1], p.y); mn[2] = std::min(mn[2], p.z);
                                mx[0] = std::max(mx[0], p.x); mx[1] = std::max(mx[1], p.y); mx[2] = std::max(mx[2], p.z);
                            }
                            hit = mx[0] >= -r && mn[0] <= r && mx[1] >= -r && mn[1] <= r && mx[2] >= 0.0f && mn[2] <= range;
                        }
                        if (hit && runCount && runStart + runCount == ch.start) runCount += ch.count;
                        else if (hit) { flush(); runStart = ch.start; runCount = ch.count; }
                        else flush();
                    }
                    flush();
                }
            }
        }

        // The recorded models.
        device_->SetVertexShader(vsShadowModel_);
        for (const Caster& m : casters_) {
            if (!m.anywhere) {
                const Vec3 p = XformPoint(view, m.centre);
                const float margin = 3.0f;
                if (p.x < -r - margin || p.x > r + margin || p.y < -r - margin || p.y > r + margin || p.z < -margin || p.z > range) continue;
            }
            if (m.decl) device_->SetVertexDeclaration(m.decl);
            else device_->SetFVF(m.fvf);
            device_->SetStreamSource(0, m.vb, m.offset, m.stride);
            device_->SetVertexShaderConstantF(4, &m.world._11, 4);
            if (m.tex && m.alphaRef > 0.0f) {
                device_->SetPixelShader(psShadowCutout_);
                const float psc[4] = {0.0f, std::max(m.alphaRef, 0.05f), 0.0f, 0.0f};
                device_->SetPixelShaderConstantF(0, psc, 1);
                device_->SetTexture(0, m.tex);
                device_->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
                device_->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
            } else {
                device_->SetPixelShader(psShadowSolid_);
            }
            if (m.indexed) {
                device_->SetIndices(m.ib);
                device_->DrawIndexedPrimitive(m.type, m.base, m.minIdx, m.numVerts, m.start, m.prims);
            } else {
                device_->DrawPrimitive(m.type, m.start, m.prims);
            }
            ++stats_.casterDraws;
        }
    }
    device_->SetTexture(0, nullptr);
}

void PostFx::Resolve() {
    if (!active_) return;
    active_ = false;
    recording_ = false;
    const double t0 = NowMs();
    const VisualsSettings& cfg = g_visuals;
    const int q = std::max(0, std::min(2, cfg.quality));
    stats_.casters = static_cast<int>(casters_.size());
    stats_.casterDraws = 0;
    stats_.worldDraws = 0;
    stats_.lights = 0;
    stats_.cascades = 0;
    ReadTimestamps();
    stateBlock_->Capture();
    if (tsOk_) tsDisjoint_[tsFrame_ & 3]->Issue(D3DISSUE_BEGIN);
    Timestamp(0);

    const float night = 1.0f - Smooth(0.25f, 0.75f, frame_.day);
    const bool shadows = cfg.shadows && frame_.sunLevel > 0.01f && frame_.sunDir.y > -0.02f && shadowTex_;
    const int cascades = shadows ? q + 1 : 0;
    if (shadows) RenderShadows(cascades, frame_.sunDir);
    Timestamp(1);
    const double t1 = NowMs();
    // debug=7: write the shadow atlas once to GTA2DX9_VISUALS_LOG's folder as atlas.pgm (depth 0..1 as grey).
    // debug with bit 16 (16, 24, 25, ...): the same, once per value, as atlas_<debug>.pgm.
    static int dumped = 0;
    const bool dumpNow = shadows && ((cfg.debug == 7 && dumped != 7) || ((cfg.debug & 16) && dumped != cfg.debug));
    if (!(cfg.debug & 16) && cfg.debug != 7) dumped = 0;
    if (dumpNow) {
        dumped = cfg.debug;
        IDirect3DSurface9* sys = nullptr;
        D3DSURFACE_DESC sd = {};
        shadowSurf_->GetDesc(&sd);
        char path[MAX_PATH] = {};
        if (GetEnvironmentVariableA("GTA2DX9_VISUALS_LOG", path, sizeof path) && strrchr(path, '\\')) sprintf(strrchr(path, '\\') + 1, "atlas_%d.pgm", cfg.debug);
        else sprintf(path, "atlas_%d.pgm", cfg.debug);
        if (SUCCEEDED(device_->CreateOffscreenPlainSurface(shadowSize_, shadowSize_, sd.Format, D3DPOOL_SYSTEMMEM, &sys, nullptr)) &&
            SUCCEEDED(device_->GetRenderTargetData(shadowSurf_, sys))) {
            D3DLOCKED_RECT r;
            if (SUCCEEDED(sys->LockRect(&r, nullptr, D3DLOCK_READONLY))) {
                if (FILE* f = fopen(path, "wb")) {
                    fprintf(f, "P5\n%d %d\n255\n", shadowSize_ / 2, shadowSize_ / 2);
                    for (int y = 0; y < shadowSize_; y += 2) for (int x = 0; x < shadowSize_; x += 2) {
                        const float v = sd.Format == D3DFMT_R32F ? reinterpret_cast<const float*>(static_cast<const uint8_t*>(r.pBits) + y * r.Pitch)[x] : 0.5f;
                        fputc(static_cast<int>(std::min(1.0f, std::max(0.0f, v)) * 255.0f), f);
                    }
                    fclose(f);
                }
                sys->UnlockRect();
            }
        }
        SafeRelease(sys);
        RendererTrace("visuals: shadow atlas written to %s (world runs %d, caster draws %d)", path, stats_.worldDraws, stats_.casterDraws);
    }

    // Everything from here reads the scene's depth, so it is no longer the depth target.
    device_->SetDepthStencilSurface(nullptr);
    device_->SetVertexShader(vsQuad_);
    device_->SetVertexDeclaration(quadDecl_);
    device_->SetRenderState(D3DRS_ZENABLE, D3DZB_FALSE);
    device_->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device_->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device_->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    device_->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    device_->SetRenderState(D3DRS_FOGENABLE, FALSE);
    device_->SetRenderState(D3DRS_STENCILENABLE, FALSE);
    device_->SetRenderState(D3DRS_SCISSORTESTENABLE, FALSE);
    device_->SetRenderState(D3DRS_CLIPPLANEENABLE, 0);
    device_->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
    device_->SetRenderState(D3DRS_SRGBWRITEENABLE, FALSE);
    device_->SetRenderState(D3DRS_FILLMODE, D3DFILL_SOLID);
    auto sampler = [&](DWORD s, IDirect3DBaseTexture9* t, bool linear) {
        device_->SetTexture(s, t);
        device_->SetSamplerState(s, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
        device_->SetSamplerState(s, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
        device_->SetSamplerState(s, D3DSAMP_MINFILTER, linear ? D3DTEXF_LINEAR : D3DTEXF_POINT);
        device_->SetSamplerState(s, D3DSAMP_MAGFILTER, linear ? D3DTEXF_LINEAR : D3DTEXF_POINT);
        device_->SetSamplerState(s, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
        device_->SetSamplerState(s, D3DSAMP_SRGBTEXTURE, FALSE);
    };
    const int w = width_, h = height_, hw = w / 2, hh = h / 2;
    const int qw = std::max(1, w / 4), qh = std::max(1, h / 4), ew = std::max(1, w / 8), eh = std::max(1, h / 8);
    const float proj[4] = {proj_.m[2][2], proj_.m[3][2], 1.0f / proj_.m[0][0], 1.0f / proj_.m[1][1]};
    const float screen[4] = {1.0f / w, 1.0f / h, static_cast<float>(w), static_cast<float>(h)};
    device_->SetPixelShaderConstantF(0, proj, 1);
    device_->SetPixelShaderConstantF(1, screen, 1);

    // Ambient occlusion.
    const bool ssao = cfg.ssao && q >= 1 && cfg.aoStrength > 0.0f;
    if (ssao) {
        SetTarget(aoSurf_, hw, hh);
        device_->SetPixelShader(q >= 2 ? psSsao12_ : psSsao8_);
        const float ao[4] = {0.38f, 0.03f, 1.25f, 45.0f};
        device_->SetPixelShaderConstantF(2, ao, 1);
        sampler(1, depthTex_, false);
        DrawQuad(hw, hh);
        SetTarget(aoBlurSurf_, hw, hh);
        device_->SetPixelShader(psAoBlur_);
        const float blur[4] = {1.0f / hw, 1.0f / hh, 0.0f, 0.0f};
        device_->SetPixelShaderConstantF(2, blur, 1);
        sampler(4, aoTex_, false);
        DrawQuad(hw, hh);
    }

    // Sun shadow mask: one draw per cascade, each clipped to its own slice of depth.
    if (shadows) {
        SetTarget(maskSurf_, w, h);
        device_->Clear(0, nullptr, D3DCLEAR_TARGET, 0xFFFFFFFFu, 1.0f, 0);
        device_->SetPixelShader(psShadowmask_);
        sampler(1, depthTex_, false);
        sampler(2, shadowTex_, false);
        const Vec3 sunV = Normalize(XformDir(view_, frame_.sunDir));
        static const float kSplits[3][3] = {{30.0f, 1e6f, 1e6f}, {14.0f, 56.0f, 1e6f}, {9.0f, 28.0f, 85.0f}};
        float nearZ = 0.0f;
        for (int k = 0; k < cascades; ++k) {
            const float farZ = kSplits[q][k];
            const bool last = k == cascades - 1;
            const Mat4& m = cascades_[k].viewToAtlas;
            float c[9][4] = {};
            c[0][0] = sunV.x; c[0][1] = sunV.y; c[0][2] = sunV.z;
            c[1][0] = nearZ; c[1][1] = farZ; c[1][2] = last ? farZ * 0.8f : 1e9f; c[1][3] = last ? 1.0f / (farZ * 0.2f) : 0.0f;
            for (int col = 0; col < 3; ++col)
                for (int row = 0; row < 4; ++row) c[2 + col][row] = m.m[row][col];
            c[5][0] = 1.0f / shadowSize_; c[5][1] = static_cast<float>(shadowSize_);
            c[5][2] = 0.00015f;   // depth bias, in the map's 0..1 range (~0.01-0.03 blocks)
            c[5][3] = cascades_[k].texelWorld * 1.6f;   // normal offset
            c[6][0] = frame_.ambientLevel; c[6][1] = frame_.sunLevel; c[6][2] = cfg.shadowStrength; c[6][3] = q >= 1 ? 1.0f : 0.0f;
            device_->SetPixelShaderConstantF(2, &c[0][0], 7);
            DrawQuad(w, h);
            nearZ = farZ;
        }
    }

    // Composite: the shadow mask, AO, hemisphere.
    {
        SetTarget(litSurf_, w, h);
        device_->SetPixelShader(psComposite_);
        sampler(4, sceneTex_, false);
        sampler(1, depthTex_, false);
        sampler(2, shadows ? static_cast<IDirect3DBaseTexture9*>(maskTex_) : whiteTex_, false);
        sampler(3, ssao ? aoBlurTex_ : whiteTex_, true);
        const Vec3 upV = Normalize(XformDir(view_, Vec3{0.0f, 1.0f, 0.0f}));
        float c[4][4] = {};
        c[0][0] = frame_.fogStart; c[0][1] = 1.0f / std::max(1.0f, frame_.fogEnd - frame_.fogStart);
        c[0][2] = ssao ? cfg.aoStrength : 0.0f; c[0][3] = frame_.blend;
        c[1][0] = frame_.skyTint.x; c[1][1] = frame_.skyTint.y; c[1][2] = frame_.skyTint.z; c[1][3] = cfg.hemisphere ? 0.30f : 0.0f;
        c[2][0] = frame_.groundTint.x; c[2][1] = frame_.groundTint.y; c[2][2] = frame_.groundTint.z;
        c[3][0] = upV.x; c[3][1] = upV.y; c[3][2] = upV.z;
        device_->SetPixelShaderConstantF(2, &c[0][0], 4);
        DrawQuad(w, h);
    }

    // debug=4 (8-bit targets, hdr=0): read back the scene and the composite now and then and
    // log their mean chroma, to see where colour goes.
    if (cfg.debug == 4 && hdrFormat_ == D3DFMT_A8R8G8B8 && (frames_ % 30u) == 0u) {
        auto chroma = [&](IDirect3DSurface9* src) -> double {
            IDirect3DSurface9* sys = nullptr;
            double sum = 0.0; int n = 0;
            if (SUCCEEDED(device_->CreateOffscreenPlainSurface(w, h, D3DFMT_A8R8G8B8, D3DPOOL_SYSTEMMEM, &sys, nullptr)) &&
                SUCCEEDED(device_->GetRenderTargetData(src, sys))) {
                D3DLOCKED_RECT r;
                if (SUCCEEDED(sys->LockRect(&r, nullptr, D3DLOCK_READONLY))) {
                    for (int y = 0; y < h; y += 16) for (int x = 0; x < w; x += 16) {
                        const DWORD p = static_cast<const DWORD*>(static_cast<const void*>(static_cast<const uint8_t*>(r.pBits) + y * r.Pitch))[x];
                        const int R = (p >> 16) & 255, G = (p >> 8) & 255, B = p & 255;
                        sum += std::max(R, std::max(G, B)) - std::min(R, std::min(G, B)); ++n;
                    }
                    sys->UnlockRect();
                }
            }
            SafeRelease(sys);
            return n ? sum / n : -1.0;
        };
        RendererTrace("visuals dbg: chroma scene %.1f composite %.1f", chroma(sceneSurf_), chroma(litSurf_));
    }

    // Night lights, added in one draw of a quad each.
    if (cfg.lights && night > 0.02f && g_lightProvider) {
        lights_.clear();
        g_lightProvider(&lights_);
        struct Pick { float d2; int i; };
        std::vector<Pick> picks;
        const float tanY = std::tan(fovY_ * 0.5f), tanX = tanY * aspect_;
        for (size_t i = 0; i < lights_.size(); ++i) {
            const VisualLight& l = lights_[i];
            const float r = l.radius;
            const Vec3 v = XformPoint(view_, Vec3{l.pos[0], l.pos[1], l.pos[2]});
            if (v.z < -r || v.z - r > frame_.fogEnd) continue;
            if (std::fabs(v.x) > v.z * tanX + r * 1.5f || std::fabs(v.y) > v.z * tanY + r * 1.5f) continue;
            picks.push_back({v.x * v.x + v.y * v.y + v.z * v.z, static_cast<int>(i)});
        }
        const size_t cap = q == 0 ? 16 : (q == 1 ? 32 : 64);
        if (picks.size() > cap) {
            std::nth_element(picks.begin(), picks.begin() + static_cast<long>(cap), picks.end(), [](const Pick& a, const Pick& b) { return a.d2 < b.d2; });
            picks.resize(cap);
        }
        std::vector<LightVertex> verts;
        verts.reserve(picks.size() * 6);
        for (const Pick& p : picks) {
            const VisualLight& l = lights_[static_cast<size_t>(p.i)];
            const float r = l.radius;
            const Vec3 v = XformPoint(view_, Vec3{l.pos[0], l.pos[1], l.pos[2]});
            float x0 = -1.0f, x1 = 1.0f, y0 = -1.0f, y1 = 1.0f;
            if (v.z - r > 0.2f) {   // the box's corners on screen; the whole screen when it reaches the eye
                x0 = y0 = 1e9f; x1 = y1 = -1e9f;
                for (int i = 0; i < 8; ++i) {
                    const float cx = v.x + ((i & 1) ? r : -r), cy = v.y + ((i & 2) ? r : -r), cz = v.z + ((i & 4) ? r : -r);
                    const float sx = cx * proj_.m[0][0] / cz, sy = cy * proj_.m[1][1] / cz;
                    x0 = std::min(x0, sx); x1 = std::max(x1, sx); y0 = std::min(y0, sy); y1 = std::max(y1, sy);
                }
                x0 = std::max(x0, -1.0f); y0 = std::max(y0, -1.0f); x1 = std::min(x1, 1.0f); y1 = std::min(y1, 1.0f);
                if (x0 >= x1 || y0 >= y1) continue;
            }
            LightVertex base = {};
            base.p[0] = v.x; base.p[1] = v.y; base.p[2] = v.z; base.p[3] = r;
            const float k = l.intensity * cfg.lightIntensity * night * frame_.blend;
            base.c[0] = l.rgb[0] * k; base.c[1] = l.rgb[1] * k; base.c[2] = l.rgb[2] * k;
            if (l.spot) {
                const Vec3 d = Normalize(XformDir(view_, Vec3{l.dir[0], l.dir[1], l.dir[2]}));
                base.s[0] = d.x; base.s[1] = d.y; base.s[2] = d.z; base.s[3] = std::cos(l.coneDeg * 3.14159265f / 180.0f);
            } else {
                base.s[3] = -2.0f;
            }
            const float xs[6] = {x0, x1, x0, x0, x1, x1}, ys[6] = {y1, y1, y0, y0, y1, y0};
            for (int i = 0; i < 6; ++i) {
                LightVertex lv = base;
                lv.x = xs[i]; lv.y = ys[i]; lv.z = 0.5f; lv.w = 1.0f;
                verts.push_back(lv);
            }
        }
        stats_.lights = static_cast<int>(verts.size() / 6);
        if (!verts.empty()) {
            device_->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
            device_->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);
            device_->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_ONE);
            device_->SetRenderState(D3DRS_BLENDOP, D3DBLENDOP_ADD);
            device_->SetRenderState(D3DRS_SEPARATEALPHABLENDENABLE, FALSE);
            device_->SetVertexDeclaration(lightDecl_);
            device_->SetVertexShader(vsLight_);
            device_->SetPixelShader(psLight_);
            const float amb = std::max(0.15f, frame_.ambientLevel);
            const float lc[4] = {1.0f / amb, 0.8f, frame_.fogStart, 1.0f / std::max(1.0f, frame_.fogEnd - frame_.fogStart)};
            device_->SetPixelShaderConstantF(2, lc, 1);
            device_->DrawPrimitiveUP(D3DPT_TRIANGLELIST, static_cast<UINT>(verts.size() / 3), verts.data(), sizeof(LightVertex));
            device_->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
            device_->SetVertexShader(vsQuad_);
            device_->SetVertexDeclaration(quadDecl_);
        }
    }

    // Bloom: bright pass to a quarter, blurred there; the high tier adds an eighth.
    const bool bloom = cfg.bloom && cfg.bloomStrength > 0.0f;
    const bool bloom2 = bloom && q >= 2;
    if (bloom) {
        SetTarget(bloomSurf_[0], qw, qh);
        device_->SetPixelShader(psBright_);
        const float thr = cfg.bloomThreshold * (hdrFormat_ == D3DFMT_A8R8G8B8 ? 0.9f : 1.0f);
        const float br[4] = {thr, 0.25f, 1.0f / w, 1.0f / h};
        device_->SetPixelShaderConstantF(0, br, 1);
        sampler(4, litTex_, true);
        DrawQuad(qw, qh);
        device_->SetPixelShader(psBlur_);
        auto blurPass = [&](IDirect3DTexture9* src, IDirect3DSurface9* dst, int tw, int th, float dx, float dy) {
            SetTarget(dst, tw, th);
            const float d[4] = {dx, dy, 0.0f, 0.0f};
            device_->SetPixelShaderConstantF(0, d, 1);
            sampler(4, src, true);
            DrawQuad(tw, th);
        };
        blurPass(bloomTex_[0], bloomSurf_[1], qw, qh, 1.0f / qw, 0.0f);
        blurPass(bloomTex_[1], bloomSurf_[0], qw, qh, 0.0f, 1.0f / qh);
        if (bloom2) {
            blurPass(bloomTex_[0], bloomSurf_[2], ew, eh, 1.0f / ew, 0.0f);
            blurPass(bloomTex_[2], bloomSurf_[3], ew, eh, 0.0f, 1.0f / eh);
            blurPass(bloomTex_[3], bloomSurf_[2], ew, eh, 1.0f / ew, 0.0f);
            blurPass(bloomTex_[2], bloomSurf_[3], ew, eh, 0.0f, 1.0f / eh);
        }
    }

    // Final: tonemap onto the back buffer.
    {
        D3DSURFACE_DESC bd = {};
        savedTarget_->GetDesc(&bd);
        SetTarget(savedTarget_, static_cast<int>(bd.Width), static_cast<int>(bd.Height));
        device_->SetPixelShader(psFinal_);
        sampler(4, litTex_, false);
        sampler(1, bloom ? static_cast<IDirect3DBaseTexture9*>(bloomTex_[0]) : blackTex_, true);
        // debug 1: the raw scene, 2: the shadow mask, 3: the shadow atlas
        sampler(2, cfg.debug == 2 && shadows ? static_cast<IDirect3DBaseTexture9*>(maskTex_) : (cfg.debug == 3 && shadows ? static_cast<IDirect3DBaseTexture9*>(shadowTex_) : sceneTex_), false);
        sampler(3, bloom2 ? static_cast<IDirect3DBaseTexture9*>(bloomTex_[3]) : blackTex_, true);
        const float exposure = cfg.exposure * (1.0f + 0.12f * night);
        const float fin[8] = {exposure, bloom ? cfg.bloomStrength : 0.0f, cfg.saturation, cfg.debug >= 1 && cfg.debug <= 3 ? 0.0f : frame_.blend,
                              0.78f, 0.10f, cfg.tonemap ? 1.0f : 0.0f, bloom2 ? cfg.bloomStrength * 0.6f : 0.0f};
        device_->SetPixelShaderConstantF(0, fin, 2);
        DrawQuad(static_cast<int>(bd.Width), static_cast<int>(bd.Height));
    }
    Timestamp(2);
    if (tsOk_) {
        tsDisjoint_[tsFrame_ & 3]->Issue(D3DISSUE_END);
        tsFreq_[tsFrame_ & 3]->Issue(D3DISSUE_END);
        tsIssued_[tsFrame_ & 3] = true;
        ++tsFrame_;
    }

    for (DWORD s = 0; s < 5; ++s) device_->SetTexture(s, nullptr);
    device_->SetRenderTarget(0, savedTarget_);
    device_->SetDepthStencilSurface(savedDepth_);
    stateBlock_->Apply();
    device_->SetPixelShader(nullptr);
    device_->SetVertexShader(nullptr);
    SafeRelease(savedTarget_);
    SafeRelease(savedDepth_);
    ClearCasters();

    const double t2 = NowMs();
    stats_.cpuShadowMs = t1 - t0;
    stats_.cpuPostMs = t2 - t1;

    // A line a frame to GTA2DX9_VISUALS_LOG, and a summary every 256 frames.
    static FILE* log = nullptr;
    static int logState = -1;
    if (logState < 0) {
        char path[MAX_PATH] = {};
        logState = 0;
        if (GetEnvironmentVariableA("GTA2DX9_VISUALS_LOG", path, sizeof path) && path[0] && (log = fopen(path, "w"))) {
            logState = 1;
            setvbuf(log, nullptr, _IOFBF, 1 << 16);
            fprintf(log, "n\tt_ms\tquality\tcpu_shadow\tcpu_post\tgpu_shadow\tgpu_post\tcasters\tcaster_draws\tworld_draws\tlights\tcascades\tday\n");
        }
    }
    ++frames_;
    if (logState == 1) {
        fprintf(log, "%u\t%.1f\t%d\t%.3f\t%.3f\t%.3f\t%.3f\t%d\t%d\t%d\t%d\t%d\t%.2f\n", frames_, t2, q, stats_.cpuShadowMs, stats_.cpuPostMs,
                stats_.gpuShadowMs, stats_.gpuPostMs, stats_.casters, stats_.casterDraws, stats_.worldDraws, stats_.lights,
                stats_.cascades, frame_.day);
    }
    histCpu_.push_back(static_cast<float>(t2 - t0));
    if (stats_.gpuShadowMs >= 0.0) histGpu_.push_back(static_cast<float>(stats_.gpuShadowMs + stats_.gpuPostMs));
    if (histCpu_.size() >= 256) {
        auto pct = [](std::vector<float> v, float p) {
            if (v.empty()) return -1.0f;
            std::sort(v.begin(), v.end());
            return v[std::min(v.size() - 1, static_cast<size_t>(p * static_cast<float>(v.size())))];
        };
        RendererTrace("visuals: quality %d, cpu ms p50 %.2f p99 %.2f, gpu ms p50 %.2f p99 %.2f, casters %d (%d draws), world runs %d, lights %d, cascades %d",
                      q, pct(histCpu_, 0.5f), pct(histCpu_, 0.99f), pct(histGpu_, 0.5f), pct(histGpu_, 0.99f), stats_.casters,
                      stats_.casterDraws, stats_.worldDraws, stats_.lights, stats_.cascades);
        histCpu_.clear();
        histGpu_.clear();
        if (logState == 1) fflush(log);
    }
}

}  // namespace gta2
