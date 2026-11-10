#pragma once
// FIX-CAR-SHADING-1: the car paint's coat on the plain renderer (src/shaders/car_coat.hlsl,
// docs/vehicle-shading.md). A second pass over each car body mesh, right after its fixed-function
// draw: clear-coat Fresnel reflection of the sky and street with a horizon line, a per-pixel sun
// highlight, the base coat's sheen with a faint flake, and crease darkening from the curvature.
// Never under RTX Remix (the layer's PBR maps do it there) and never in the classic view (no car
// bodies are drawn there). The paint's colour stays identity.cpp's: the coat adds light, not tint.
#include <windows.h>
#include <d3d9.h>
#include "../../src/math3d.h"

namespace gta2dx9 {

struct CarCoatFrame {
    float sunDir[3] = {0.0f, 1.0f, 0.0f};   // toward the sun
    float sunCol[3] = {0.78f, 0.78f, 0.78f};
    float sunStrength = 1.0f;               // the coat highlight (0 at night)
    float zenith[3] = {0.35f, 0.50f, 0.75f};
    float horizon[3] = {0.70f, 0.75f, 0.80f};
    float ground[3] = {0.16f, 0.16f, 0.17f};
};

// [renderer] car_coat* keys (package/gta2dx9.ini), read once at load.
void CarCoatConfigure(const char* ini);
// The share of car_bodies' fixed-function specular lobe kept under the coat ([renderer] car_coat_ffp_spec_percent).
float CarCoatFfpSpecKeep();
// [devtools] car_coat=0|1 (re-read live by car_bodies for same-session A/B); -1 = the ini's.
void CarCoatSetLive(int on);
// On for this frame: the setting, shader model 3, not under Remix.
bool CarCoatActive(IDirect3DDevice9* device);
void CarCoatSetFrame(const CarCoatFrame& frame);
// The coat's weight on the car being drawn (1 a clean car, less when dented or burning, 0 off: the
// wheels, a wreck, anything that is not a car body). car_bodies sets it per car.
void CarCoatSetWeight(float weight);
float CarCoatWeight();

// One mesh draw to coat: the same buffers (or user pointers) the fixed-function draw used.
struct CarCoatDraw {
    IDirect3DVertexBuffer9* vb = nullptr;
    IDirect3DIndexBuffer9* ib = nullptr;
    UINT verts = 0, prims = 0, stride = 0;
    const void* upVerts = nullptr;           // DrawIndexedPrimitiveUP when vb is null
    const void* upIndices = nullptr;         // 32-bit
    IDirect3DBaseTexture9* glassMask = nullptr;   // VEHICLE-GLASS's cut mask on this draw
    IDirect3DTexture9* body = nullptr;       // the texture the draw sampled (its size: the panel gap detector)
    bool softPaint = false;                  // the soft-paint stages: coverage alpha = paint
    bool paint = false;                      // a "_paint" mesh (else the rest of the body)
    const float* tint = nullptr;             // the paint tint (x2 stage) or null (1)
};
// Called by ModelDraw right after a car mesh's draw, with the world matrix it was drawn with.
void CarCoatOverlay(IDirect3DDevice9* device, const gta2::Mat4& world, const CarCoatDraw& d);
// Frame statistics for the body pass (draws coated, ms) and a reset.
void CarCoatStats(int* draws, double* ms);

}  // namespace gta2dx9
