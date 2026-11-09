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
    // Per wheel (0 front-left, 1 front-right, 2 rear-left, 3 rear-right; "right" is +x),
    // VEHICLE-PHYSICS: the wheel's rise off the road (a kerb strike, the inside wheel off
    // the ground), its camber (radians, + top outward: a bent corner) and an extra steer
    // (radians: a bent corner's toe and a bent rim's wobble with the spin).
    float wheelLift[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    float wheelCamber[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    float wheelToe[4] = {0.0f, 0.0f, 0.0f, 0.0f};
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
// VEHICLE-PHYSICS (on by default): the body's motion from a load-transfer model (four
// corners on springs, a friction circle per tyre, impact impulses, damage that stays in
// the corner that took it). 0 = the first VEHICLE-FEEL springs (the "before"); -1 leaves
// it. GTA2DX9_VEHICLE_PHYSICS=0 or [devtools] vehicle_physics=0|1 (re-read once a second).
void VehicleFxSetPhysics(int mode);
// Night: head lamps, exhaust puffs (car_bodies.cpp passes its lamp state).
void VehicleFxSetDark(bool dark);
// Ground views: the smoke, sparks and glow textures are magnified, so sample them bilinearly.
void VehicleFxSetSmooth(bool on);
// FIX-VEHICLES: the drawn lean over the springs', percent ([renderer] car_body_pitch,
// car_body_roll; defaults 220 and 170). The model and its telemetry are unchanged.
void VehicleFxSetLean(int pitchPercent, int rollPercent);
// The player's car as last drawn (FIX-VEHICLES), for the camera: the drawn pitch (nose
// down +) and roll, the heave, and the speed lost to impacts since the last call
// (blocks/s, consumed by the call). False when the player has no car drawn in the
// last 3 frames.
struct VehicleFxMotion {
    uint32_t frame = 0;
    float pitch = 0.0f, roll = 0.0f, heave = 0.0f;
    float impulse = 0.0f;
};
bool VehicleFxPlayerMotion(VehicleFxMotion* out);
// The share of the body's pose the first-person eye rides ([camera] first_body_ride,
// set by the camera): the cut cockpit body is drawn with the same share (at least a
// third), so the bonnet holds still under the eye while the street tilts.
void VehicleFxSetFirstRide(float share);
float VehicleFxFirstRide();

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
// [devtools] spawn_smoke: a tyre-smoke and a steam puff at `at` (call once a frame while wanted).
void VehicleFxSetPuffLevels(bool on);   // [devtools] remix_puff_levels
void VehicleFxProbeSmoke(const gta2::Vec3& at, float groundY);
// For the log: particles alive, skid segments, ms of the last frame (update + draw).
void VehicleFxStats(int* particles, int* skids, double* ms);

}  // namespace gta2dx9
