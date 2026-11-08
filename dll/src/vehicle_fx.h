// Vehicle feel (VEHICLE-FEEL): how the 3D car bodies move and what they leave
// behind, read from the motion the game gives them and nothing else. The game's
// physics is never touched: every effect here is derived from the car's position
// and heading frame to frame, its damage word and the map's ground types.
//
//   - a sprung body: roll in turns and pitch under braking and acceleration
//     (from the measured acceleration in the car's own frame), heave and kicks on
//     kerbs (a wheel crossing road <-> pavement), slopes and impacts;
//   - wheels that turn with the distance covered and steer with the turn rate;
//   - brake lamps while slowing, reverse lamps (and brake lamps) while backing;
//   - head-lamp pools on the road at night (plain renderer only; Remix has lights);
//   - an exhaust puff at idle at night, tyre smoke and skid marks on hard braking,
//     handbrake slides and wheelspin, sparks on wall hits and scrapes, debris and a
//     flying wheel when a car blows up, and a wreck that sits on its lost wheels.
//
// Everything is bounded: a fixed particle pool, a ring of skid segments, a cap on
// lamp pools, and the per-car state is dropped after 20 s unseen. car_bodies.cpp
// calls VehicleFxUpdate for each body it draws and VehicleFxDraw once per frame.
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>

#include <cstdint>

#include "../../src/math3d.h"

namespace gta2dx9 {

class GroundSampler;
struct Model;

// What the body does this frame.
struct VehicleFeel {
    gta2::Mat4 pose;          // car frame -> car frame: the sprung body (roll, pitch, heave); identity when off
    float steer = 0.0f;       // front wheels, radians about the car's up axis
    float spin = 0.0f;        // wheel rotation, radians (rolling forward is positive)
    float brake = 0.0f;       // brake lamps 0..1
    float reverse = 0.0f;     // reverse lamps 0..1
    float speed = 0.0f;       // signed, blocks/s along the nose
    bool on = false;          // the feel is enabled
};

// The car as car_bodies.cpp draws it.
struct VehicleFxCar {
    uintptr_t object = 0;     // the sprite object (the key)
    const gta2::Mat4* carToWorld = nullptr;   // x across, y up, z nose; origin on the road
    float length = 1.0f, width = 0.5f, roof = 0.4f;   // blocks
    float wheelbase = 0.6f;
    float wheelRadius = 0.08f;
    int damage = 0;           // the damage word (+0x74), 0..32000
    bool wreck = false;       // drawn as a burnt-out wreck (sprites 65..74)
    bool driven = false;      // the player's car
    float paint[3] = {0.5f, 0.5f, 0.5f};   // 0..1, for debris
    // The car's flying wheel when it blows up: one of its cut wheels, if it has them
    // (model space, placed by `fit` then about `wheelCentre` in the car frame).
    const Model* wheelPart = nullptr;
    gta2::Mat4 fit;
    gta2::Vec3 wheelCentre;
};

// The map, for the ground under each wheel (world_view.cpp, beside LightsSetGround).
void VehicleFxSetGround(const GroundSampler* ground);
// On by default; GTA2DX9_VEHICLE_FEEL=0 or [devtools] vehicle_feel=0 turns it all off
// (the "before" of the comparison sheet).
void VehicleFxSetEnabled(bool on);
bool VehicleFxEnabled();
// Night: head lamps, exhaust puffs (car_bodies.cpp passes its lamp state).
void VehicleFxSetDark(bool dark);

// One car, once a frame, before it is drawn.
const VehicleFeel& VehicleFxUpdate(const VehicleFxCar& car, uint32_t frame);
// A head-lamp pool for this car this frame (called by the lamps when they are lit).
void VehicleFxQueueHeadlamps(const gta2::Mat4& carToWorld, float length, float width);
// A wreck model's resting pose: each lost corner (bit 0 front-left, 1 front-right,
// 2 rear-left, 3 rear-right) sits on its hub. Car frame -> car frame.
gta2::Mat4 VehicleFxWreckPose(int lostCorners, float length, float width, float wheelRadius);
// Particles, skid marks, lamp pools and flying parts; once a frame after the bodies.
// Leaves lighting off, alpha blending off, z writes on.
void VehicleFxDraw(IDirect3DDevice9* device, const gta2::Vec3& eye, uint32_t frame, bool remix);
void VehicleFxReleaseDevice();
// For the log: particles alive, skid segments, ms of the last frame (update + draw).
void VehicleFxStats(int* particles, int* skids, double* ms);

}  // namespace gta2dx9
