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
// Drops the ragdolls of bodies not drawn for ten seconds.
void RagdollEndFrame(uint32_t frame);

}  // namespace gta2dx9
