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
    // VEHICLE-ART-4 (playfeel1): an authored car body's driver's seat, model frame (blocks, as in the
    // .mesh: +z the nose, y up from the lowest point): the hip's distance from the centre line, the
    // cushion's top, the hip along the car, the headliner over it. Manifest "driver_seat"
    // (tools/vehicle_art/seat_anchor.py); without it the seat comes from the sprite (boarding.cpp).
    bool hasDriverSeat = false;
    float driverSeat[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    // A car model's own paint colour (0-255), as its "_paint" textures are painted:
    // the game's paint divides by it to make the tint ("paint_rgb" in the manifest).
    // Near-white by default, for models whose paint is left neutral.
    float paintRgb[3] = {235.0f, 235.0f, 235.0f};
    // Whether any mesh uses a "_paint" texture (a split body/paint texture that
    // needs alpha testing to look whole, tinted or not).
    bool splitPaint = false;
    // ASSET-PEDS: a pedestrian whose clothes come in tintable zones (importer
    // "ped_zones": nodes "...#pt" the top, "...#pb" the bottom, their texture neutral
    // grey at zoneRef), the zones' own colours (top, bottom, hair; 0 = unknown).
    bool pedZones = false;
    float zoneRef = 128.0f;
    float zoneRgb[3][3] = {};
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
// VEHICLE-GLASS (vr-generated-bodies-hard-facets-crumpled-bonnets-close-range): the car bodies' vertex
// normals welded across their UV seams at load (angle-weighted face normals, kept apart only over a
// crease of `creaseDeg`), so a bonnet shades as one panel instead of a mosaic of charts. Set before
// ModelsLoad; [renderer] car_smooth_normals=1, car_crease_deg=60.
void ModelSetCarSmoothing(int enabled, int creaseDeg);
bool ModelsAvailable();
// True for every Model* the store has handed out (they never move or die); a
// pointer that fails this came from stale or uninitialised memory and must not be used.
bool ModelIsKnown(const Model* model);
// Adds a model derived from another (a hood-only copy of a car body, say) to the
// store, so it is drawn and cached like the rest; returns its stable address.
// dynamicBuffers: its meshes are drawn from dynamic default-pool buffers (for a
// model made while the game runs, whose first draw is mid-frame; see BuffersFor).
const Model* ModelRegisterDerived(Model&& model, bool dynamicBuffers = false);
// FIX-PERF-3: the rigid buffers of `model`'s drawn meshes made ahead of its first draw, at most `budget` new
// ones this call (*made: how many); true when all exist. Spreads a derived copy's buffers over frames.
bool ModelPrepareBuffers(IDirect3DDevice9* device, const Model& model, int budget, int* made = nullptr);
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
// [devtools] ini path for the live Remix paint-factor toggle (remix_tint_linear)
void ModelSetDevIni(const char* ini);
// FIX-CAR-IDENTITY: a car model's own paint (0-255), the mean of the texels its "_paint" meshes cover in
// the shipped files; cached. False (rgb = paintRgb) when it has no paint meshes. identity.cpp divides by it.
// mean (optional): the plain mean of the same texels (for a sprite paint measured from its remap's texels).
bool ModelOwnPaint(const Model& model, float rgb[3], float mean[3] = nullptr);
// FIX-CAR-IDENTITY-4 (feel25): the model's lit body panels: the mean colour of the paint texels at or over half
// the 90th-percentile luminance (not the windows, tyres and trim an opaque paint atlas also covers), and the
// 97th-percentile luminance (the brightest panel level a tint must not push past white).
bool ModelOwnPaintPanel(const Model& model, float panel[3], float* top);
// FIX-PERF-3: every car model's own paint measured on a low-priority thread from now on (once a session;
// the classic view calls it a few seconds into a level, so the first street frame with cars waits for none).
void ModelsOwnPaintAhead();
// FIX-CAR-RENDER: soft car paint masks (renderer.car_paint_soft_mask, default on; never
// under Remix): car "_paint" textures get a coverage alpha and are drawn in one pass,
// texel * lerp(1, tint, coverage). Set before the first car texture is read.
void ModelSetSoftPaintMasks(bool on);
// Whether car paint is drawn soft (known once the first car texture has been read).
bool ModelSoftPaintActive();
// A model texture's mean luminance and alpha (0..255) around (u, v), from a 64x64
// CPU copy read from its file (no device needed); false when it cannot be read.
bool ModelTextureSample(const std::string& file, float u, float v, float* luma, float* alpha);
// FIX-PERF-3: the samples of every texture of `model` made now (any thread), not at the first sample.
void ModelTextureSampleWarm(const Model& model);
// A twist of the upper body about the model's up axis at "Bip01 Spine1",
// radians, applied to every pose drawn until it is set back to 0: the aim
// turned off the walk. Quantise it (it keys the pose cache).
// FIX-FIGURE-5: the hips (Bip01 Pelvis) turned about the vertical by `twist` radians and shifted by
// (dx, dy, dz) in model space, for every pose until set back to zeros (part of the pose cache key).
void ModelSetHipShift(float twist, float dx, float dy, float dz);
void ModelSetTorsoTwist(float radians);
float ModelTorsoTwist();
// CROWD: a turn of the head about the model's up axis, radians, shared 40/60
// between "Bip01 Neck" and "Bip01 Head" (a glance, a look at the player); on
// top of the clip and the torso twist, until set back to 0. Quantise it (it
// keys the pose cache).
void ModelSetHeadTurn(float radians);
// REMIX-3D-QUALITY: while on, model draws bind a per-texture copy whose Remix hash
// is in rtx.playerModelTextures (hidden from the eye, still casting shadows); for
// the player's own figure in first person under Remix. Set it back to false.
void ModelSetPlayerTextures(bool on);
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
// ANIM-BLEND-AUDIT: up to kModelLayers more clips blended over the pair (after it, before
// the overlay) when `model` is drawn or its nodes asked for: in order, each written over a
// copy of the pose so far and blended in by its weight (pose = lerp(pose, clip at time, w)),
// so a chain of them makes any mix of clips with continuous weights (the locomotion:
// walk/run/sprint/idle/turn/start/stop/fidget, see DrawPedFigures). Clips with weight 0 are
// skipped; count 0 (or a null model) clears. Part of the pose cache key; clear it after the draw.
constexpr int kModelLayers = 6;
void ModelSetLayers(const Model* model, const ModelAnimation* const* clips, const float* times, const float* weights, int count);
// ANIM-VEHICLE-ENTRY: two-bone IK over every pose drawn or queried until cleared:
// limb 0 left arm, 1 right arm (the hand onto `target`), 2 left leg, 3 right leg (the
// foot), in model space, the elbow or knee bent toward `pole` (a direction; null: the
// way the clip bends it), blended in by `weight` (0..1; null target or 0 clears that
// limb). The end joint keeps the clip's orientation. Part of the pose cache key.
void ModelSetLimbTarget(int limb, const float* target, const float* pole, float weight);
void ModelClearLimbTargets();
// What of a limb's target the last pose could not reach (target minus where the end
// joint got to, model space); false when that limb has no target.
bool ModelLimbResidual(int limb, float out[3]);
// Bytes of model textures created so far (managed pool), and how many.
size_t ModelsTextureBytes(int* count);
// IDENTITY-SYSTEM: a texture factor (0..2, x2 stage) over the nodes whose name starts with
// `nodePrefix` in the next draws (null: off), and the mean colour of such a node's texture
// (its opaque texels), so a caller can take the texture to a colour (factor = want / mean).
void ModelSetNodeTint(const char* nodePrefix, const float* rgb);
// IDENTITY-SYSTEM: the zone and clothing tints of the next draws baked into texture copies instead
// of the stage-1 texture factor (the figures under RTX Remix; identity.h IdentityBakeTints).
void ModelSetBakeTints(bool on);
bool ModelNodeTextureMean(IDirect3DDevice9* device, const Model& model, const char* nodePrefix, float rgb[3]);
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
// ASSET-PEDS: the tints of a zoned avatar's top, bottom and hair for a remap's
// outfit (the manifest's "ped_outfits", read from the sprite's palettes), as
// multipliers (0..2) for ModelSetZoneTints; a zone the outfit leaves open keeps
// the avatar's own colour, the hair stays untinted (hairTint false). False when
// the model has no zones or the remap's type is not tinted.
// ASSET-PEDS-2: the pedestrian type's build (scale, width), 1 and 1 for the crowd's; true when it differs.
bool PedTypeBuild(int remap, float* scale, float* width);
bool PedZoneTints(int remap, const Model& model, float tints[3][3], bool* hairTint);
bool PedRemapHasType(int remap);   // a ped type lists this remap (53: the SWAT/FBI body)
// Meshes of a zoned avatar drawn with these factors (top, bottom; hair on the
// hair cards, "_opacity" textures) until cleared with nullptr; overrides the
// paint tint for those meshes.
void ModelSetZoneTints(const float* top, const float* bottom, const float* hair);
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
// Where the street views stand each lamp's post (x, z; y is the lamp's own height):
// moved off the cell's walking line to the kerb or the wall (DrawProps, defect
// pt-player-walks-through-street-lamps). One entry per MapLamps() entry, in the same
// order, with x = NaN where no post is drawn (a lamp over the roadway with no kerb).
// Empty until DrawProps has run on the level; callers fall back to MapLamps().
void SetMapLampPosts(const std::vector<gta2::Vec3>& posts);
const std::vector<gta2::Vec3>& MapLampPosts();
// The lamp post under a map lamp at `at` whose floor is at `floor`: false when no post
// stands there (the lamp is not 0.3..3.5 above the floor), else the post's scale.
// DrawProps places the posts by this; the Remix lights fit the lamp's light to it.
bool LampPostScale(const Model& lamp, float lampY, float floor, float* scale);
// Where that post's lantern is, renderer frame: the glass's centre and radius, and
// the bottom of the dish under the glass. False when no post stands there.
struct LampHead { gta2::Vec3 centre; float glassRadius = 0.0f; float dishBottom = 0.0f; };
bool LampPostHead(const Model& lamp, const gta2::Vec3& at, float floor, LampHead* out);

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
// Puts a model's textures and buffers at the front of that warm-up (the player's avatar).
void ModelsWarmFirst(const Model* model);
// Draws a prop, the avatar and a car once under the caller's states, into targets nothing shows,
// so the driver has their GL programs before the first street view (FIX-PERF-VSWITCH).
void ModelsGhostDraws(IDirect3DDevice9* device, const gta2::Mat4& at);
// VEHICLE-ART-3: makes the first of the model's textures not made yet (one per call, so a caller
// can spread a derived model's textures over frames); false when all are made.
bool ModelPrepareOneTexture(IDirect3DDevice9* device, const Model& model);
// Binds a texture in a draw that writes no pixels, for the driver to upload it.
void WarmTexture(IDirect3DDevice9* device, IDirect3DTexture9* texture);
void ModelsBeginFrame();

}  // namespace gta2dx9
