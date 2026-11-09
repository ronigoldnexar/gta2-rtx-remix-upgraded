#pragma once
// FIX-COLLISION: the street props of the 3D views (DrawProps: lamp posts, hydrants, bins,
// benches, mailboxes, meters, signs, shelters, trees, dock containers and cranes, roof
// units) and the game's own objects drawn as models are solid for the player on foot.
//
// The game does not know the rule-placed props, so it walks him through them. Each frame
// in a 3D view the props near him publish their footprints here (circles for posts,
// hydrants, bins and trunks; boxes turned with the prop for benches, mailboxes, containers;
// the parts of a shelter or a crane), and the solver below moves the player's body out of
// any it entered, writing the game's own ped position (WritePlayerGroundPosition, as the
// developer warp does), so the game carries on from there: he stops against a post and
// slides round it when walking at an angle, as against the game's own walls. In first
// person his eye (ahead of the body) keeps clear too, so it never enters a post.
// Light props (bins) are shoved instead: pushed along, sliding on a little and settling;
// against a wall or another prop they hold and block him.
// The classic view has no 3D props and is never touched (nothing here runs there).
// GTA2DX9_PROP_COLLIDE=0 turns it off (the earlier see-through fade only, for a before/after).

#include <cstdint>
#include <string>
#include <vector>

namespace gta2dx9 {

struct Model;

// One solid piece in the renderer frame (x east, y up, z north).
struct CollisionShape {
    float cx, cz;     // centre
    float ax, az;     // a box's first axis (unit); the second is (-az, ax)
    float ha, hb;     // a box's half extents along its axes; hb < 0: a circle of radius ha
    float y0, y1;     // vertical span
    int pushable;     // index into the pushables, -1 when fixed
    const char* kind; // the model's name, for the log
};

bool PropCollisionEnabled();

// Called by DrawProps each frame: the shapes near the player, replacing the last frame's.
void PropCollisionBeginFrame();
// A placed prop by its draw placement (foot point, yaw, scale): its footprint shapes are
// added from the model (cached per model). Returns the pushable index for a light prop.
void PropCollisionAddPlaced(const Model* model, float x, float y, float z, float yaw, float scale, bool pushable,
                            int pushIndex);
// A game object drawn as a model (map_objects.cpp) that stands in the way (by the model's
// name, PropCollisionSolidObject), by its draw placement like a prop.
bool PropCollisionSolidObject(const char* modelName);
void PropCollisionAddObject(const Model* model, float x, float y, float z, float yaw, float scale);
// The start of the objects' pass: what the last pass added becomes the objects' list.
void PropCollisionObjectsDone();

// The light props' displacement since they were placed (by base placement), for the draw:
// registers one the first time it is asked for. Returns its index.
int PropPushableAt(float baseX, float baseY, float baseZ, float radius, float height, float* dx, float* dz, float* dyaw);

// Once a frame in a 3D view: integrates the shoved props, then moves the player's body
// (x, z in the renderer frame, level y; facing fx, fz) out of what it entered. `walled`
// tells a point inside the map's walls (the body is never pushed into one). Returns true
// when he was moved; *x, *z then hold where to.
bool PropCollisionResolvePlayer(float* x, float* z, float y, float fx, float fz, bool firstPerson, float eyeAhead,
                                float dt, bool (*walled)(void*, float, float, float), void* context);
// This frame's move of the player (renderer frame), for his drawn figure: the game drew
// him before the move. Cleared at each resolve; false when he was not moved.
bool PropCollisionPlayerCorrection(float* dx, float* dz);
void PropCollisionSetPlayerCorrection(float dx, float dz);
// Passers-by (FIX-COLLISION): the game's pedestrians on foot drawn this frame, noted while
// their sprites come in (live_geometry.cpp), taken once a frame and each moved out of the
// props like the player (no eye), in the game's own position.
struct PedBody { void* ped; float x, y, z; };   // renderer frame, y the level
void PropCollisionNotePed(void* ped, float x, float y, float z);
std::vector<PedBody> PropCollisionTakePeds();
bool PropCollisionResolvePed(float* x, float* z, float y, float dt, bool (*walled)(void*, float, float, float), void* context);
// The light props alone, when the player is not on foot (they still settle).
void PropCollisionStepPushables(float dt, bool (*walled)(void*, float, float, float), void* context);

// Developer log: GTA2DX9_LOG_PROPS_NEAR=1 writes the shapes within 5 blocks of the player
// every 60 frames ("collide: near ..."), for the probes that walk into each kind.
void PropCollisionLogNear(float x, float z, float y);

}  // namespace gta2dx9
