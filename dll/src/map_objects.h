// The game's own objects - phone boxes, cones, bins, crates, benches - stood up
// as 3D models in the street-level views. The game draws each one as a flat
// sprite quad; when the models manifest maps that sprite ("objects":
// {"<base>:<number>": "model"}) the quad is left out and the model is drawn on
// its footprint instead. The classic top-down view is untouched.
#pragma once
#include <cstdint>
#include <vector>
#include "live_geometry.h"

namespace gta2dx9 {
struct Model;

// The model mapped to this sprite object, or null. Every new (base, number)
// pair that is neither a car nor a pedestrian is logged once, with its quad's
// size in tiles, so the manifest can be filled in from a run's log.
const Model* MapObjectModel(const void* spriteObject, const LiveGeometry::Vertex* local, int corners,
                            const gta2::Mat4& objectToWorld);
// Draws the objects collected this frame (the sprites whose objectModel is set).
void MapObjectsDraw(IDirect3DDevice9* device, const std::vector<LiveGeometry::SpriteType>& sprites);
// The footprints of the standing objects drawn last frame (phone boxes, traffic
// lights: not the floating pickups), for the first-person eye's push-out.
const std::vector<PropFootprint>& MapObjectFootprints();
// The same for every standing object the game drew this frame, including those
// outside the picture (behind the chase camera, where it may be about to go):
// read-only, for the camera's clearance (view_modes.cpp).
const std::vector<PropFootprint>& MapObjectObstacles();

// QB-50: the floating pickups drawn this frame (renderer frame, the model's centre a hand
// above the ground), with the label the HUD floats over each ("PISTOL", "POWER-UP"), the
// game's sprite object (stable while the pickup lies there) and its distance to the eye.
struct PickupSpot { float x, y, z, eyeDistance; uintptr_t object; const char* label; };
const std::vector<PickupSpot>& MapObjectPickups();
uint32_t MapObjectPickupsFrame();   // bumped by every MapObjectsDraw
// The projection of a world point with the view and projection MapObjectsDraw drew
// with, as a fraction of the viewport (0..1 across and down); false behind the eye or
// before the first street-view frame. `depth` (optional) is the distance along the view.
bool MapObjectsProject(float x, float y, float z, float* sx, float* sy, float* depth = nullptr);
// The eye MapObjectsDraw last drew from and its view direction (renderer frame, 3 floats
// each); false before the first frame.
bool MapObjectsEye(float* eye, float* dir);
// QB-49: how many objects were drawn faded (closer to the eye than the fade range) in
// the last frame, for the log.
int MapObjectsFadedLastFrame();
// FIX-ARTEFACTS: the share of the frame (0..1) a model's bounding box covers with the device's
// current view and projection (1 when the box straddles the eye's plane; eyeGap: its nearest
// corner's distance from the eye), and a rate-limited 'artefact probe:' log line for a
// see-through draw that covers more than a twentieth of the frame.
float ModelScreenShare(IDirect3DDevice9* device, const Model& model, const gta2::Mat4& placement, float* eyeGap = nullptr);
void LogLargeSeeThrough(IDirect3DDevice9* device, const char* kind, const Model& model, const gta2::Mat4& placement, float alpha);
}  // namespace gta2dx9
