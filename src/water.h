// The street views' water surface: a small SM3 shader for the water tiles'
// batches (src/shaders/water.hlsl) - three drifting wave layers, a Fresnel sky
// reflection, a sun glint, foam along quays and banks, the scene's fog.
//
// Off in the classic view (the renderer only calls it when the street shading
// is on) and on an RTX Remix device (Remix wants the fixed-function draw and
// lights the water itself). With it off or unavailable the renderer falls back
// to the older fixed-function ripple (renderer.cpp, water_effect).
// docs/water.md has the picture, the cost and the ini keys.
#pragma once

#include <d3d9.h>

#include <cstdint>
#include <vector>

#include "math3d.h"

namespace gta2 {

struct WorldShading;   // renderer.h
struct WorldMesh;      // world_mesh.h

// [renderer] water_shader: 0 off, 1 on (the default in the street views).
void SetWaterShader(bool on);
bool WaterShaderEnabled();
// [renderer] water_waves / water_reflection / water_foam: strengths, 0..2 (1 = default).
void SetWaterTuning(float waves, float reflection, float foam);

class WaterFx {
public:
    // Builds the shaders and the wave map; false (and stays unused) if the device refuses.
    bool Init(IDirect3DDevice9* device, bool remix);
    void Release();
    // The distance-to-shore map for a new world, from the water tiles' upward faces.
    void BuildShore(const WorldMesh& mesh, const std::vector<uint8_t>& waterTile);
    bool Ready() const { return ready_ && shore_ != nullptr; }

    // Per frame, before the world is drawn.
    void SetSky(const Vec3& zenith, const Vec3& horizon) { zenith_ = zenith; horizon_ = horizon; haveSky_ = true; }

    // Around a water batch's draw (stage 0 already holds the tile's texture).
    void Begin(const Mat4& view, const Mat4& proj, const Vec3& eye, const WorldShading& shading, double seconds);
    void End();

private:
    IDirect3DDevice9* device_ = nullptr;
    IDirect3DVertexShader9* vs_ = nullptr;
    IDirect3DPixelShader9* ps_ = nullptr;
    IDirect3DTexture9* wave_ = nullptr;
    IDirect3DTexture9* shore_ = nullptr;
    bool ready_ = false;
    bool haveSky_ = false;
    Vec3 zenith_{0.35f, 0.55f, 0.85f};
    Vec3 horizon_{0.70f, 0.78f, 0.88f};
    DWORD savedFog_ = FALSE;
};

}  // namespace gta2
