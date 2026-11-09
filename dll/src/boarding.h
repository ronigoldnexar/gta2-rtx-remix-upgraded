// Getting into and out of a car in the street views, as one continuous piece of
// acting (ANIM-VEHICLE-ENTRY, 9 Nov 2026).
//
// The game boards a ped in a few coarse steps: it walks him to the door (state 3,
// sprite frames 8-23), backs him 0.15 off it and moves him 0.3 in (state 3 sub 6,
// frames 24-35, 0.8 s), then stops drawing him; leaving, he appears at the door
// already outside the body (state 4 sub 7, 0.9 s) and slides out sideways. Drawn
// as is, the figure vanishes at the sill, pops into view outside a shut door and
// slides. This module plans the figure's part instead, in the car's own frame
// (so a car that moves carries the plan with it), and the renderer draws it:
//
//   in:  reach for the handle (the hand on it, following it as the door swings
//        out), a step back as the door opens, a step into the opening, the inner
//        foot over the sill into the footwell, a hand on the roof edge, ducking
//        and sitting down into the seat, the outer foot in, the door pulled shut
//        by its inside handle; the figure is kept (a "ghost" of the last sprite)
//        after the game stops drawing him until the door is shut;
//   out: from the seat, the door pushed open by its inside handle, the outer foot
//        over the sill to the ground, a hand on the roof edge, standing up out of
//        the opening and onto the game's own position by 0.8 s, then free.
//
// Contact is by two-bone IK (model_store ModelSetLimbTarget): hands on the door
// handle, the door's top edge and the roof edge, feet on the sill path, the
// footwell and the ground. The door itself is driven from here (car_bodies asks
// BoardingDoor), so it opens before a leaving figure passes through it and stays
// open until an entering one is inside.
#pragma once

#include <cstdint>

#include "../../src/math3d.h"

namespace gta2dx9 {

// car_bodies, every frame, for every car drawn from a model that can open a door:
// its posed car-to-world matrix (rows: x across, y up, z forward, the origin on the
// ground at its middle), its half width, the door's front (hinge) and rear edges
// along z, the roof height, and the driver's door's state (side +-1, open 0..1).
void BoardingPublishCar(uintptr_t carObject, const gta2::Mat4& carToWorld, float halfW, float zFront, float zRear,
                        float roof, int doorSide, float doorOpen, uint32_t frame);
// car_bodies: whether a boarding drives this car's door now; if so the side, the
// target (0 shut, 1 open) and the rate (per second).
bool BoardingDoor(uintptr_t carObject, int* side, float* target, float* rate);
// car_bodies: the car the player drives (its door split is built ahead, both sides).
bool BoardingWarmDoors(uintptr_t carObject);

struct BoardingIn {
    uintptr_t ped = 0;
    bool own = false;           // the player
    int state = 0, sub = 0;     // the game's state words
    unsigned frame = 0;         // sprite frame within the body (0..157)
    float gameX = 0.0f, gameZ = 0.0f, groundY = 0.0f;
    float drawnX = 0.0f, drawnZ = 0.0f, heading = 0.0f;   // the renderer's figure before this module
    float right = 1.0f;         // which way the figure's own right lies: +1 (x = cos h, z = -sin h)
    bool ghost = false;         // drawn from the last sprite after the game hid him
    float dt = 1.0f / 30.0f;
    uint32_t now = 0;
};
struct BoardingOut {
    float x = 0.0f, z = 0.0f;   // where the figure stands (feet), world
    float sink = 0.0f;          // how far it is lowered (sitting, ducking), blocks
    float heading = 0.0f;       // radians, atan2(x, z) of the way it faces
    int action = 0;             // the action clip to play: 5 enter_car, 6 exit_car
    float clipT = 0.0f;         // seconds into it, at full weight
    float vx = 0.0f, vz = 0.0f; // the figure's velocity (world, per second), for the hand-off back to the renderer
};
// Per figure, every frame, after the renderer has placed it and before it is posed.
// True while a boarding plays: the figure is drawn from `out`.
bool BoardingUpdate(const BoardingIn& in, BoardingOut* out);
// The limb targets for the figure just updated, world space: limb 0 left hand, 1 right
// hand, 2 left foot, 3 right foot; false for a limb left to the clips.
bool BoardingLimb(uintptr_t ped, int limb, gta2::Vec3* target, gta2::Vec3* pole, float* weight);
// The part of a hand's target the figure's pose could not reach (world, blocks), after
// it was drawn: the next frame moves the body toward it (a lean, a half step).
void BoardingReportResidual(uintptr_t ped, int limb, const gta2::Vec3& residual);
// Whether this ped's boarding is the player's (his ghost keeps his avatar).
bool BoardingIsPlayer(uintptr_t ped);
// Whether the figure of this ped is still to be drawn though the game no longer draws
// him (boarding: until the door is shut behind him).
bool BoardingWantsGhost(uintptr_t ped, uint32_t now);
// Once a frame, after the figures: forgets boardings that ended or were abandoned.
void BoardingEndFrame(uint32_t now);
// A world point (dir false) or direction (dir true) into the space of a model drawn with
// `world` (row vectors, p_world = p_model * world): for the IK targets.
void BoardingWorldToModel(const gta2::Mat4& world, const gta2::Vec3& p, bool dir, float out[3]);
// Verification aid, off by default: with GTA2DX9_BOARDING_CAM=1 the street-view camera is
// held beside the door the player is using, for 1.5 s after each boarding frame.
bool BoardingDebugCamera(gta2::Vec3* eye, float* yaw, float* pitch);
// [devtools]-style switch (GTA2DX9_BOARDING=0 turns the module off; default on).
bool BoardingEnabled();
// The GTA2DX9_LOG_FIGURES trace of a boarding (one line a frame per active one).
void BoardingSetLog(bool on);

}  // namespace gta2dx9
