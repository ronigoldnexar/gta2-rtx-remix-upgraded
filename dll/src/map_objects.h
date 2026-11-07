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
}  // namespace gta2dx9
