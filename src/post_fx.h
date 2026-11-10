// The plain renderer's modern look (docs/visuals-plain.md).
//
// GTA2's street views are drawn fixed-function: textured, a directional sun and an
// ambient term per vertex, linear fog. This adds, in the street views only and never
// under RTX Remix (which lights the scene itself):
//
//   - cascaded sun shadow maps (2-3 cascades, PCF, texel-snapped), cast by the world
//     mesh and by every depth-writing model drawn after it (cars, people, props), which
//     are recorded from the device's draw calls and replayed from the sun;
//   - a hemisphere sky term and the shadows applied over the finished frame from its
//     depth (deferred shadowing: no draw path of the other subsystems changes);
//   - screen-space ambient occlusion at half resolution;
//   - the night's street lamps, neon and car lamps as point and spot lights added in
//     screen space from the light lists the Remix path already keeps;
//   - bloom with a soft threshold and a filmic shoulder at a fixed exposure.
//
// The frame is drawn into an FP16 target with an INTZ depth texture while the post
// is active; Resolve() puts the result on the back buffer before the 2D layer.
#pragma once

#include <d3d9.h>

#include <cstdint>
#include <vector>

#include "gta2_style.h"
#include "math3d.h"
#include "world_mesh.h"

namespace gta2 {

struct VisualsSettings {
    bool enabled = false;     // the whole stack ([visuals] enabled); off until verified
    bool shadows = true;
    bool ssao = true;
    bool bloom = true;
    bool tonemap = true;
    bool lights = true;       // night lights as real lights
    bool hemisphere = true;
    int quality = 1;          // 0 low, 1 medium, 2 high
    float shadowStrength = 1.35f;   // 1 = the sun's share of the fixed-function light
    float aoStrength = 0.75f;
    float bloomStrength = 0.55f;
    float bloomThreshold = 0.80f;
    float exposure = 1.0f;
    float saturation = 1.10f;
    float lightIntensity = 1.0f;
    float sunBoost = 1.5f;    // the world's sun light, times this, while the post is on
    float ambientScale = 0.84f;   // and its ambient
    int hdr = 1;              // FP16 scene target (0: 8-bit)
    bool shadowStagger = true;   // far cascades refreshed on alternate frames
    bool carShadowBlend = true;  // feel29: the driven car's shadow eased over ~10 frames (stencil-marked pixels)
    int debug = 0;            // 1: final shows the raw scene target
};
VisualsSettings& VisualsConfig();

// A light for the night pass, in world units (+X east, +Y up, +Z north).
struct VisualLight {
    float pos[3];
    float rgb[3];        // 0..1, times intensity
    float intensity;
    float radius;        // reach in blocks
    bool spot;
    float dir[3];        // spot direction, unit
    float coneDeg;       // spot half angle
    float day;           // share kept in full daylight (0: a night light; a fire keeps some)
};
// The DLL side (dll/src/visuals.cpp) supplies the lights and re-reads the ini; the
// renderer calls these once per street-view frame. Either may be null.
using VisualLightProvider = void (*)(std::vector<VisualLight>* out);
using VisualsPollFn = void (*)();
void SetVisualLightProvider(VisualLightProvider fn);
// FIX-FIGURE-16 (qav19): the summed night lights at the eye last street-view frame, bounded the way
// ps_light_apply bounds them (0 with the lights off or under Remix), for the first-person hands, which
// take them through their own light instead of the frame's light pass (stencil bit 0x40, see below).
void VisualLightAtEye(float rgb[3]);
// The view model's pixels carry stencil bit kViewModelStencil; the light pass leaves them alone.
constexpr unsigned kViewModelStencil = 0x40u;
bool ViewModelLightMaskOn();
void SetVisualsPoll(VisualsPollFn fn);
void VisualsPoll();
// FIX-COCKPIT-CAB-4 (qav12, dg2 band): in first person at the wheel the DLL gives the cockpit's reach (view depth, blocks;
// 0 = none) each frame; nearer pixels (cab, bonnet, his arms) take no AO and no hemisphere tint: both come from normals
// rebuilt from the depth buffer, which at the cockpit's range and grazing angles are noise.
void SetPostCockpitReach(float viewDepth);

// What a frame of the post needs to know about the street view's light.
struct PostFrame {
    Vec3 sunDir{0.0f, 1.0f, 0.0f};   // toward the sun
    float sunLevel = 0.0f;            // scalar sun light on a face squarely facing it (after rebalance)
    float ambientLevel = 1.0f;        // scalar ambient (after rebalance)
    Vec3 fogColour;
    float fogStart = 30.0f, fogEnd = 140.0f;
    float blend = 1.0f;               // the view transition's weight
    float day = 1.0f;                 // 1 full daylight .. 0 night
    Vec3 skyTint{1.0f, 1.0f, 1.0f};   // hemisphere colours
    Vec3 groundTint{1.0f, 1.0f, 1.0f};
};

struct PostStats {
    double cpuShadowMs = 0.0, cpuPostMs = 0.0;   // this frame
    double gpuShadowMs = -1.0, gpuPostMs = -1.0; // a few frames late; -1 unknown
    int casters = 0, casterDraws = 0, worldDraws = 0, lights = 0, cascades = 0, cascadesReused = 0;
};

class PostFx {
public:
    ~PostFx() { Release(); }
    // remix: the device is RTX Remix's; nothing here ever runs then.
    void Init(IDirect3DDevice9* device, int width, int height, bool remix);
    void Release();
    void ReleaseWorld();
    // The world's shadow copy: the same vertex buffer, an index buffer by map chunk, and
    // an atlas of the cutout tiles' alpha.
    void BuildWorld(const WorldMesh& mesh, const Style& style, IDirect3DVertexBuffer9* worldVb);

    bool Available() const { return device_ && !remix_ && ok_; }
    // Switches the frame to the post's targets; false leaves everything as it was.
    bool BeginScene(const PostFrame& frame);
    bool Active() const { return active_; }
    void SetCamera(const Mat4& view, const Mat4& proj, const Vec3& eye, float fovY, float aspect);
    // The sky's colours for the hemisphere term (Renderer::DrawSky).
    void SetSky(const Vec3& zenith, const Vec3& horizon, float day);
    void StartRecording();
    // The puddle map for the wet-road pass (weather_fx.h); not owned.
    void SetPuddles(IDirect3DTexture9* puddles) { puddles_ = puddles; }
    // Shadows, AO, composite, lights, bloom, tonemap onto the saved back buffer.
    void Resolve();
    const PostStats& Stats() const { return stats_; }

    // Called from the draw hook.
    void Record(IDirect3DDevice9* d, bool indexed, D3DPRIMITIVETYPE type, INT base, UINT minIdx, UINT numVerts,
                UINT start, UINT prims);
    bool recording_ = false;

private:
    struct Caster {
        IDirect3DVertexBuffer9* vb = nullptr;
        IDirect3DIndexBuffer9* ib = nullptr;
        IDirect3DVertexDeclaration9* decl = nullptr;
        IDirect3DBaseTexture9* tex = nullptr;
        UINT offset = 0, stride = 0;
        DWORD fvf = 0;
        D3DMATRIX world;
        float alphaRef = 0.0f;
        D3DPRIMITIVETYPE type = D3DPT_TRIANGLELIST;
        INT base = 0;
        UINT minIdx = 0, numVerts = 0, start = 0, prims = 0;
        bool indexed = true;
        bool anywhere = false;   // no usable position: drawn into every cascade
        Vec3 centre;
    };
    struct Chunk {
        uint32_t start = 0, count = 0;   // in the shadow index buffer
        float lo[3], hi[3];
    };
    struct Cascade {
        Mat4 lightVP;         // world -> light clip
        Mat4 viewToAtlas;     // view -> atlas uv/depth
        float radius = 0.0f, texelWorld = 0.0f, farZ = 0.0f;
        Vec3 centre;
        Mat4 lightView;
        int qx = 0, qy = 0;
        // What the map in this cell was drawn with (the staggered refresh keeps it a frame).
        bool valid = false;
        uint32_t renderedFrame = 0;
        Vec3 sunDir;
        float renderedRadius = 0.0f;
    };

    bool EnsureTargets();
    void ReleaseTargets();
    void ClearCasters();
    void RenderShadows(int cascades, const Vec3& sunDir);
    void DrawQuad(int w, int h);
    void SetTarget(IDirect3DSurface9* s, int w, int h);
    void Timestamp(int slot);
    void ReadTimestamps();

    IDirect3DDevice9* device_ = nullptr;
    int width_ = 0, height_ = 0;
    bool remix_ = false;
    bool ok_ = true;            // resources could be made (false: never try again)
    bool active_ = false;
    bool loggedFormats_ = false;

    PostFrame frame_;
    Mat4 view_, proj_, invView_;
    Vec3 eye_;
    float fovY_ = 0.7f, aspect_ = 1.0f;

    // Targets.
    IDirect3DTexture9* sceneTex_ = nullptr;  IDirect3DSurface9* sceneSurf_ = nullptr;
    IDirect3DTexture9* depthTex_ = nullptr;  IDirect3DSurface9* depthSurf_ = nullptr;
    IDirect3DTexture9* litTex_ = nullptr;    IDirect3DSurface9* litSurf_ = nullptr;
    IDirect3DTexture9* aoTex_ = nullptr;     IDirect3DSurface9* aoSurf_ = nullptr;
    IDirect3DTexture9* aoBlurTex_ = nullptr; IDirect3DSurface9* aoBlurSurf_ = nullptr;
    IDirect3DTexture9* bloomTex_[4] = {};    IDirect3DSurface9* bloomSurf_[4] = {};   // quarter a/b, eighth a/b
    IDirect3DTexture9* shadowTex_ = nullptr; IDirect3DSurface9* shadowSurf_ = nullptr;
    IDirect3DSurface9* shadowDepth_ = nullptr;
    IDirect3DTexture9* blackTex_ = nullptr;
    IDirect3DTexture9* whiteTex_ = nullptr;
    IDirect3DTexture9* maskTex_ = nullptr;  IDirect3DSurface9* maskSurf_ = nullptr;
    IDirect3DTexture9* maskHistTex_ = nullptr;  IDirect3DSurface9* maskHistSurf_ = nullptr;   // feel29: eased mask
    bool maskHistFresh_ = true;
    // Wet roads (weather_fx.h): made on first use, while it rains.
    IDirect3DTexture9* wetTex_ = nullptr;   IDirect3DSurface9* wetSurf_ = nullptr;
    IDirect3DPixelShader9* psWet_ = nullptr;
    // Night lights' sum (FIX-FX): made on first use, at night.
    IDirect3DTexture9* lightSumTex_ = nullptr; IDirect3DSurface9* lightSumSurf_ = nullptr;
    IDirect3DPixelShader9* psLightApply_ = nullptr;
    bool lightSumFailed_ = false;
    bool lightWarm_ = false;   // FIX-FIGURE-6: the light path drawn once (see the warm-up in the lights pass)
    IDirect3DTexture9* puddles_ = nullptr;
    bool wetFailed_ = false;
    Vec3 skyZenith_{0.35f, 0.55f, 0.85f}, skyHorizon_{0.70f, 0.78f, 0.88f};
    IDirect3DSurface9* savedTarget_ = nullptr;
    IDirect3DSurface9* savedDepth_ = nullptr;
    IDirect3DStateBlock9* stateBlock_ = nullptr;
    int shadowSize_ = 2048;
    D3DFORMAT hdrFormat_ = D3DFMT_A16B16G16R16F;
    int hdrWanted_ = -1;

    // Shaders.
    IDirect3DVertexShader9* vsShadowWorld_ = nullptr;
    IDirect3DVertexShader9* vsShadowModel_ = nullptr;
    IDirect3DVertexShader9* vsQuad_ = nullptr;
    IDirect3DVertexShader9* vsLight_ = nullptr;
    IDirect3DPixelShader9* psShadowWorld_ = nullptr;
    IDirect3DPixelShader9* psShadowSolid_ = nullptr;
    IDirect3DPixelShader9* psShadowCutout_ = nullptr;
    IDirect3DPixelShader9* psShadowmask_ = nullptr;
    IDirect3DPixelShader9* psComposite_ = nullptr;
    IDirect3DPixelShader9* psSsao8_ = nullptr;
    IDirect3DPixelShader9* psSsao12_ = nullptr;
    IDirect3DPixelShader9* psAoBlur_ = nullptr;
    IDirect3DPixelShader9* psLight_ = nullptr;
    IDirect3DPixelShader9* psBright_ = nullptr;
    IDirect3DPixelShader9* psBlur_ = nullptr;
    IDirect3DPixelShader9* psFinal_ = nullptr;
    IDirect3DVertexDeclaration9* quadDecl_ = nullptr;
    IDirect3DVertexDeclaration9* lightDecl_ = nullptr;
    IDirect3DVertexDeclaration9* shadowWorldDecl_ = nullptr;

    // The world's shadow geometry.
    IDirect3DVertexBuffer9* worldVb_ = nullptr;    // the renderer's (AddRef'd; debug=9 draws the shadows from it)
    // The shadow pass's own copy (FVF XYZ|TEX1): position and the uv already moved into the
    // alpha atlas. The first version read the cell as a second interpolated texcoord; under
    // Wine 9 every triangle through that shader was clipped, so the world cast no shadow.
    IDirect3DVertexBuffer9* cellVb_ = nullptr;
    IDirect3DIndexBuffer9* shadowIb_ = nullptr;
    IDirect3DTexture9* alphaAtlas_ = nullptr;
    float atlasCell_ = 1.0f;
    UINT worldVertexCount_ = 0;
    UINT worldIndexCount_ = 0;
    std::vector<Chunk> chunks_;
    int chunksX_ = 0, chunksZ_ = 0;

    std::vector<Caster> casters_;
    Cascade cascades_[3];
    int cascadeCount_ = 0;
    std::vector<VisualLight> lights_;

    // Timing.
    IDirect3DQuery9* tsQuery_[4][4] = {};
    IDirect3DQuery9* tsDisjoint_[4] = {};
    IDirect3DQuery9* tsFreq_[4] = {};
    bool tsIssued_[4] = {};
    int tsFrame_ = 0;
    bool tsOk_ = true;
    PostStats stats_;
    uint32_t frames_ = 0;
    std::vector<float> histCpu_, histGpu_;
};

}  // namespace gta2
