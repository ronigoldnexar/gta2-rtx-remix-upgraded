// QB-27: ragdolls for people run over or blown off their feet (street views).
//
// A small position-based solver: 17 particles on the avatar's Bip01 joints
// (pelvis, chest, neck, head, head top, shoulders, elbows, hands, hips, knees,
// feet), a rigid torso, distance-kept limbs with hinge limits on the knees and
// elbows, gravity, the ground under the body with friction, the walls of the
// map, and the car that hit him as a moving box (bonnet and cabin) for the
// first half second. Seeded from the pose being drawn at the moment he goes
// down and thrown by what put him there: the hitting car's own velocity
// (legs swept at its speed, the upper body lagging, lifted at speed, so a fast
// car throws him over the bonnet and a slow one knocks him under), or away
// from the blast. The solved joints drive the skeleton through a pose hook in
// model_store; once still, the body keeps its last pose (one cached pose).
// Off with [renderer] ragdoll=0 in gta2dx9.ini or GTA2DX9_RAGDOLL=0.
#pragma once

#include <cstdint>

#include "../../src/math3d.h"

namespace gta2dx9 {

struct Model;
struct ModelAnimation;

bool RagdollEnabled();
// FIX-KNOCKDOWN: the full knock-down (fall, lying beat, get-up) for car and blast knock-downs, and holding
// the player's movement, fire and enter keys while it plays in the street views. [renderer] knockdown_full=1,
// knockdown_hold_input=1 in gta2dx9.ini; GTA2DX9_KNOCKDOWN=0/1 overrides the first (A/B).
bool KnockdownFullEnabled();
bool KnockdownHoldInputEnabled();
// A car body drawn this frame: its four corners in the world (x, y, z each).
void RagdollNoteCar(uintptr_t object, const float corners[4][3], uint32_t frame);
// A blast seen this frame (the scorch it leaves): centre and size in blocks.
void RagdollNoteBlast(float x, float y, float z, float size, uint32_t frame);
// One figure's frame. `kind` is what put him down (1 a car, 2 a blast, 0
// neither: no ragdoll), `down` whether he is down now (lying, not getting up).
// The pose pair is what the caller is about to draw (the seed). Returns true
// when the ragdoll drives this draw: the model_store pose hook is set until
// RagdollDone(), called after the draw.
bool RagdollFigure(uintptr_t ped, int kind, bool down, const Model& model, const gta2::Mat4& world, float groundX,
                   float groundY, float groundZ, float heading, float dt, uint32_t frame, const ModelAnimation* a,
                   float ta, const ModelAnimation* b, float tb, float w);
void RagdollDone();
// FIX-KNOCKDOWN: how a body lies (world space): still or not, seconds since the impact, the pelvis and the
// head, and whether the chest faces up (on his back). False when the figure has no ragdoll.
struct RagdollInfo {
    bool settled = false, faceUp = true, releasing = false;
    float age = 0.0f;
    float chestUp = 1.0f;   // the chest's facing, upward part: 1 flat on his back, -1 flat on his front
    float pelvis[3] = {0.0f, 0.0f, 0.0f}, head[3] = {0.0f, 0.0f, 0.0f};
};
bool RagdollQuery(uintptr_t ped, RagdollInfo* out);
// FIX-KNOCKDOWN: a body lying on its back rolls over onto its front (to get up from there): a turn about its
// long axis given to the joints, the solver doing the rest (the ground, the limbs, the walls).
bool RagdollRollOver(uintptr_t ped);
// FIX-KNOCKDOWN: the first-person eye through the player's own knock-down: his head in the world and how
// much of the eye it takes (0 standing .. 1 the head), on his back or his front. Set by the figure's draw
// once a frame while the sequence runs; read by the camera (stale after 150 ms).
struct KnockdownEye {
    float x = 0.0f, y = 0.0f, z = 0.0f, groundY = 0.0f;
    float weight = 0.0f;
    float chestUp = 1.0f;   // 1 on his back (the gaze up), -1 on his front (down at the road)
    bool faceUp = true;
};
void KnockdownSetEye(const KnockdownEye& eye);
bool KnockdownPlayerEye(KnockdownEye* eye);
// FIX-KNOCKDOWN (kd_t3 #4): where his drawn body is on the ground through the whole sequence (the pelvis while
// he lies, then the figure's placement through the get-up and the walk back onto the game's spot), for the
// cameras' subject point: the game's spot can be most of a block from the body. Stale after 150 ms.
void KnockdownSetBody(float x, float z);
bool KnockdownPlayerBody(float* x, float* z);
// Drops the ragdolls of bodies not drawn for ten seconds.
void RagdollEndFrame(uint32_t frame);

}  // namespace gta2dx9
