// Models imported by tools/import_assets.py: a flat file of nodes, meshes and
// node animations (see the importer for the layout), with a TGA texture beside
// it. Loaded from gta2dx9_models\ next to the game and drawn through the same
// fixed-function path as everything else, so RTX Remix path traces them like
// the rest of the world.
//
// This is the runtime half of the asset pipeline: which game object gets which
// model is the manifest's business (manifest.json in the same folder), written
// by the importer from the list it was given. Cars are matched by the sprite
// number the game draws them with; pedestrians share one character.
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>

#include <cstdint>
#include <string>
#include <vector>

#include "../../src/math3d.h"

namespace gta2dx9 {

struct ModelNode {
    char name[32];
    int parent;
    gta2::Vec3 translation;
    float rotation[4];   // x y z w
    gta2::Vec3 scale;
    int mesh;
};

struct ModelVertex {
    float x, y, z, nx, ny, nz, u, v;
};

// Four joints and their weights for one skinned vertex.
struct ModelSkinWeight {
    uint16_t joint[4];
    float weight[4];
};

struct ModelMesh {
    std::vector<ModelVertex> vertices;
    std::vector<uint32_t> indices;
    std::string texture;
    int skin = -1;                         // index into Model::skins, or -1 for a rigid mesh
    std::vector<ModelSkinWeight> weights;  // one per vertex when skinned
};

// A skin: the joint nodes and the inverse bind matrix of each.
struct ModelSkin {
    std::vector<int> joints;
    std::vector<gta2::Mat4> inverseBind;
};

struct ModelChannel {
    int node;
    int path;   // 0 translation, 1 rotation, 2 scale
    std::vector<float> times;
    std::vector<float> values;   // 3 or 4 per key
};

struct ModelAnimation {
    std::string name;
    std::vector<ModelChannel> channels;
    float length = 0.0f;
};

struct Model {
    std::string name;
    std::vector<ModelNode> nodes;
    std::vector<ModelMesh> meshes;
    std::vector<ModelAnimation> animations;
    std::vector<ModelSkin> skins;
    bool skinned = false;
    // Of the rest pose, in the model's own units after the importer's scale.
    gta2::Vec3 boundsMin, boundsMax;
    float Length() const { return boundsMax.z - boundsMin.z; }
    float Width() const { return boundsMax.x - boundsMin.x; }
    float Height() const { return boundsMax.y - boundsMin.y; }
    // +1 when the model faces +z, -1 when -z (the importer works it out from
    // the wheels, the manifest can say).
    float forward = 1.0f;
    // A car model's own paint colour (0-255), as its "_paint" textures are painted:
    // the game's paint divides by it to make the tint ("paint_rgb" in the manifest).
    // Near-white by default, for models whose paint is left neutral.
    float paintRgb[3] = {235.0f, 235.0f, 235.0f};
    // The ground the walk animation covers per cycle, in model units (its
    // root motion was stripped on import); 0 when unknown.
    float stride = 0.0f;
    const ModelAnimation* Animation(const char* name) const;
};

// Reads the folder's manifest and every model it names. Safe to call again;
// does nothing after the first time. `folder` is beside the game.
void ModelsLoad(const char* folder);
bool ModelsAvailable();
// The model for a car sprite number, or null; the pedestrian model, or null.
const Model* ModelForCar(int sprite);
// The model for a vehicle by its game model number (the manifest's
// cars.by_model map), falling back to its sprite (cars.by_sprite); null when
// neither names one - the car is then built from its sprite (car_bodies.h).
const Model* ModelForVehicle(int modelNumber, int sprite);
// Meshes whose texture name contains "_paint" are multiplied by this factor
// (0..2 per channel) in ModelDraw until it is cleared with null: a car's repaint.
void ModelSetPaintTint(const float* rgb);
const Model* ModelForPedestrian();
// One of the pedestrian models, chosen by a seed (the same seed always gives
// the same model, so a pedestrian keeps his look); null when there are none.
const Model* ModelForPedestrian(uint32_t seed);
// Street furniture by role: "lamp", "hydrant", "bin", "bench", "shrub"; null
// when the manifest names none.
const Model* ModelForProp(const char* role);
// The map's own lamp positions, renderer frame (x east, y up, z north), set
// when a level loads; the lamp posts stand on them.
void SetMapLamps(const std::vector<gta2::Vec3>& lamps);
const std::vector<gta2::Vec3>& MapLamps();

// Draws a model with `placement` (row-vector D3D convention: the model's own
// space into the world), posed by `animation` at `time` seconds (null for the
// rest pose). Textures are created on first use and kept.
void ModelDraw(IDirect3DDevice9* device, const Model& model, const gta2::Mat4& placement,
               const ModelAnimation* animation, float time);
void ModelsReleaseDevice();
int ModelsDrawnThisFrame();
void ModelsBeginFrame();

}  // namespace gta2dx9
