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
    // Whether any mesh uses a "_paint" texture (a split body/paint texture that
    // needs alpha testing to look whole, tinted or not).
    bool splitPaint = false;
    // The ground the walk animation covers per cycle, in model units (its
    // root motion was stripped on import); 0 when unknown.
    float stride = 0.0f;
    // The same for the run cycle ("run_stride"); 0 when the model has no run clip.
    float runStride = 0.0f;
    // QB-20: the mocap locomotion clips' tables (the manifest's "loco", written by
    // tools/locomotion_meta.py): per clip, sampled 15 times a second, the ground its
    // stripped root motion covered (model units) and its foot phase on its reference
    // cycle (the walk for walking clips and the run, the run for running ones).
    struct Loco {
        std::string name;
        std::vector<float> dist, phase;
        float Length() const { return dist.empty() ? 0.0f : static_cast<float>(dist.size() - 1) / 15.0f; }
        float Covered() const { return dist.empty() ? 0.0f : dist.back(); }
        float PhaseAt(float t) const;      // interpolated on the circle
        float TimeAtDist(float d) const;   // the first time the clip has covered d
    };
    std::vector<Loco> loco;
    const Loco* LocoFor(const char* name) const;
    const ModelAnimation* Animation(const char* name) const;
};

// Reads the folder's manifest and every model it names. Safe to call again;
// does nothing after the first time. `folder` is beside the game.
void ModelsLoad(const char* folder);
bool ModelsAvailable();
// True for every Model* the store has handed out (they never move or die); a
// pointer that fails this came from stale or uninitialised memory and must not be used.
bool ModelIsKnown(const Model* model);
// Adds a model derived from another (a hood-only copy of a car body, say) to the
// store, so it is drawn and cached like the rest; returns its stable address.
// dynamicBuffers: its meshes are drawn from dynamic default-pool buffers (for a
// model made while the game runs, whose first draw is mid-frame; see BuffersFor).
const Model* ModelRegisterDerived(Model&& model, bool dynamicBuffers = false);
// The world matrix of every node in the rest pose.
void ModelRestNodeWorlds(const Model& model, std::vector<gta2::Mat4>* out);
// The model for a car sprite number, or null; the pedestrian model, or null.
const Model* ModelForCar(int sprite);
// The model for a vehicle by its game model number (the manifest's
// cars.by_model map), falling back to its sprite (cars.by_sprite); null when
// neither names one - the car is then built from its sprite (car_bodies.h).
const Model* ModelForVehicle(int modelNumber, int sprite);
// Meshes whose texture name contains "_paint" are multiplied by this factor
// (0..2 per channel) in ModelDraw until it is cleared with null: a car's repaint.
void ModelSetPaintTint(const float* rgb);
// A twist of the upper body about the model's up axis at "Bip01 Spine1",
// radians, applied to every pose drawn until it is set back to 0: the aim
// turned off the walk. Quantise it (it keys the pose cache).
void ModelSetTorsoTwist(float radians);
float ModelTorsoTwist();
// CROWD: a turn of the head about the model's up axis, radians, shared 40/60
// between "Bip01 Neck" and "Bip01 Head" (a glance, a look at the player); on
// top of the clip and the torso twist, until set back to 0. Quantise it (it
// keys the pose cache).
void ModelSetHeadTurn(float radians);
// QB-27: a hook run on the node matrices of every pose built until cleared (a
// ragdoll writes its own); `key` tells the pose cache which pose it is (0: none).
using ModelPoseHookFn = void (*)(const Model& model, std::vector<gta2::Mat4>* worlds, void* context);
void ModelSetPoseHook(ModelPoseHookFn fn, void* context, uint64_t key);
// The node matrices (model space) of a pose, as ModelDrawBlend would build them
// with the current overlay and torso twist (no pose hook).
void ModelPoseWorlds(const Model& model, const ModelAnimation* animation, float time, const ModelAnimation* second,
                     float secondTime, float weight, std::vector<gta2::Mat4>* out);
// A third clip over the two that ModelDraw / ModelDrawBlend / ModelNodeWorld blend:
// sampled over a copy of their pose (a joint it has no channel for keeps theirs, so
// an upper-body layer leaves the legs to the pair) and blended in by `weight`
// (0..1). Applies to every pose until it is cleared (null or weight 0); part of the
// pose cache key, so quantise the time and weight. ACTIONS-3D-4: the action layer
// over the locomotion pair (idle/walk/run/sprint/turn_step).
void ModelSetOverlay(const ModelAnimation* clip, float time, float weight);
// Bytes of model textures created so far (managed pool), and how many.
size_t ModelsTextureBytes(int* count);
const Model* ModelForPedestrian();
// One of the pedestrian models, chosen by a seed (the same seed always gives
// the same model, so a pedestrian keeps his look); null when there are none.
const Model* ModelForPedestrian(uint32_t seed);
// The same, within the pedestrian type the game's remap palette gives him
// (the manifest's "ped_types": police, army, fireman, medic, the gangs, the
// civilian outfits); remap -1 or an unlisted remap falls back to the plain list.
const Model* ModelForPedestrian(uint32_t seed, int remap);
// The style's physical palette for each ped remap (index = remap), set when a
// level loads, so a ped sprite's texture palette gives its remap back.
void PedRemapsSetPalettes(const std::vector<int>& physicalByRemap);
int PedRemapForPalette(int physicalPalette);   // -1 when unknown
// Developer aid ([devtools] ped_remap_override): -1 off, 0..52 every pedestrian
// as that remap, -2 the typed remaps dealt out by seed. Applied by PedRemapEffective.
void PedRemapOverride(int mode);
int PedRemapEffective(int remap, uint32_t seed);
// Whether a pedestrian of this remap is drawn with his clothing tinted to the
// remap's own colour, and the tint for this model (the remap colour over the
// model's measured clothing colour, "paint_rgb"); false when not tinted.
bool PedRemapTint(int remap, const Model& model, float rgb[3]);
// Street furniture by role: "lamp", "hydrant", "bin", "bench", "shrub"; null
// when the manifest names none.
const Model* ModelForProp(const char* role);
// A model by its manifest name, or null; and the folder the manifest was read from.
const Model* ModelByName(const char* name);
const char* ModelsFolder();
// The map's own lamp positions, renderer frame (x east, y up, z north), set
// when a level loads; the lamp posts stand on them.
void SetMapLamps(const std::vector<gta2::Vec3>& lamps);
const std::vector<gta2::Vec3>& MapLamps();

// Draws a model with `placement` (row-vector D3D convention: the model's own
// space into the world), posed by `animation` at `time` seconds (null for the
// rest pose). Textures are created on first use and kept.
void ModelDraw(IDirect3DDevice9* device, const Model& model, const gta2::Mat4& placement,
               const ModelAnimation* animation, float time);
// The same, blended: `animation` at `time` weighted (1 - weight) with `second`
// at `secondTime` weighted `weight` (0..1; the plain pose at 0, `second` alone
// at 1). Posed skinned meshes are cached by (model, both clips, both times,
// weight), so callers that want cache hits should quantise the times.
void ModelDrawBlend(IDirect3DDevice9* device, const Model& model, const gta2::Mat4& placement,
                    const ModelAnimation* animation, float time, const ModelAnimation* second,
                    float secondTime, float weight);
// The posed world matrix (model space, row vectors) of the node called `name`
// under the same blend ModelDrawBlend would use, for attaching things to a
// joint (a weapon in a hand). False when the model has no such node.
bool ModelNodeWorld(const Model& model, const char* name, const ModelAnimation* animation, float time,
                    const ModelAnimation* second, float secondTime, float weight, gta2::Mat4* out);
// A synthetic looping animation that spins every node whose name contains
// `nodeSubstring` about `axis` (0 x, 1 y, 2 z) once per `period` seconds, kept
// with the model (made once, returned again after). Null when no node matches.
const ModelAnimation* ModelSpinAnimation(const Model& model, const char* nodeSubstring, int axis, float period);
void ModelsReleaseDevice();
int ModelsDrawnThisFrame();
// This frame's ModelDraw costs: {posing ms, buffer fill ms, whole ms, draws, skinned draws, unused}.
const double* ModelDrawStats();
// Creates and uploads up to `perFrame` of the models' textures that have not
// been used yet (no visible draw), so a model's first appearance costs nothing
// extra. Returns how many are still to do; call every frame until it is 0.
int ModelsWarmTextures(IDirect3DDevice9* device, int perFrame, double budgetMs = 2.0);
// Binds a texture in a draw that writes no pixels, for the driver to upload it.
void WarmTexture(IDirect3DDevice9* device, IDirect3DTexture9* texture);
void ModelsBeginFrame();

}  // namespace gta2dx9
