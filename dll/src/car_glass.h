// VEHICLE-GLASS (vr-car-glass-opaque-baked-no-interior-through-windows): the generated car bodies
// are sealed hulls whose windows are painted on (the image-to-3D bake keeps whatever the concept
// showed through the glass as opaque albedo). This makes their windows glass in the plain
// renderer's street views, for every model at once, with no change to the model files:
//
//  - a glass mask per body texture, found once per model on a worker thread: the texels that lie
//    in the model's glasshouse (side windows under the roof, the windscreen and rear screen, from
//    the mesh's own geometry) and are not the body's paint colours (pillars stay metal);
//  - the hull drawn with those texels cut out (one extra texture stage, alpha tested);
//  - a dark cabin shell behind them (floor, headliner, side walls, a dash and seat backs) so the
//    windows show an interior and the seated driver (FIX-SEATED), not the street through the car;
//  - the glass itself drawn after the figures: tinted, translucent, reflecting the sky (a cube
//    map of this frame's sky colours) and catching the sun's specular.
//
// Not in the classic view (no car models there), not the first-person own car (the cockpit), not
// wrecks or open tops. Under Remix (which ignores the extra stage) the hull is cut by geometry and
// the panes and cabin carry shared textures of their own for the gta2hd layer (docs/car-glass.md 5).
// [renderer] car_glass=1 (0 off), car_glass_alpha=62 (percent), car_glass_range=40 (blocks).
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>

#include <cstdint>
#include <string>
#include <vector>

#include "../../src/math3d.h"

namespace gta2dx9 {

struct Model;

void CarGlassSettings(int enabled, int alphaPercent, int rangeBlocks);
bool CarGlassOn();
void CarGlassSetEnabled(int enabled);   // [devtools] car_glass=0|1 (re-read once a second; A/B frames)

// Starts (once) the mask build for `base`'s body textures; true when its glass is ready to use.
bool CarGlassReady(IDirect3DDevice9* device, const Model& base);

// VEHICLE-ART-3: the glass masks for a wreck's charred textures (model_store.cpp). Starts the
// mask build for `base` whatever car_glass says (the wreck uses the masks, not the glass pass);
// then the mask of one body texture (size x size, 255 = glass): 1 found, 0 a build is still
// running, -1 no mask for it (an authored body with its own glass, or no glass found).
void CarGlassRequestMasks(const Model& base);
int CarGlassMaskForTexture(const std::string& texture, std::vector<uint8_t>* out, int* size);

// Whether the model's rear screen was found (a seated car without one keeps FIX-SEATED's band).
bool CarGlassHasRear(const Model& base);

// Cut mode, set around one car's hull draws: ModelDraw calls in between bind the mask on a free
// stage (CarGlassCutMask) and queue themselves for the glass pass (CarGlassCutQueue).
void CarGlassBeginCut(const Model& base, float distance);
void CarGlassEndCut();
IDirect3DTexture9* CarGlassCutMask(const std::string& texture);
// VEHICLE-GLASS-2: under Remix, in cut mode, the mesh's triangles less its glass panes (an index
// buffer over the mesh's own vertices, 32-bit indices, *triangles of them); null otherwise. The
// mask stage is then not bound (Remix ignores it): the panes are drawn by CarGlassFlush.
struct ModelMesh;
IDirect3DIndexBuffer9* CarGlassCutIndexBuffer(IDirect3DDevice9* device, const ModelMesh& mesh, UINT* triangles);
void CarGlassCutQueue(const Model& model, const gta2::Mat4& placement);

// The cabin shell inside `base` (floor, headliner, walls, dash, seat backs), placed like its hull.
void CarGlassDrawInterior(IDirect3DDevice9* device, const Model& base, const gta2::Mat4& placement, bool night);

// Draws (and clears) this frame's queued glass: after the figures, before the effects.
void CarGlassFlush(IDirect3DDevice9* device);
void CarGlassReleaseDevice();

}  // namespace gta2dx9
