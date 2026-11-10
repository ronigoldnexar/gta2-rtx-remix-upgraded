// ANIM-WEAPONS (9 Nov 2026): weapon handling on the street-view figures.
//
// The gun is the master and the body follows it, as in current shooters: each
// frame the weapon's frame is placed from the figure's own pose (the pistol out
// on the eye line, a long gun's stock in the right shoulder pocket, the
// launcher's tube on the shoulder, the flamethrower at the hip; low ready when
// carried; pulled in and canted for a reload), then both arms are solved onto
// its grips with a two-bone IK (elbows down and out), the hands turned to hold
// it and the fingers closed round the grip (the trigger finger along the frame
// until he fires), and the head brought to the sights or to the magazine well.
// A shot drives a per-weapon recoil spring that moves the character, not just
// the gun: the gun goes back and its muzzle climbs, the chest rocks back, the
// right shoulder is driven back, the head nods and the whole figure is pushed a
// little back along the line of fire.
//
// It runs as model_store's pose hook (model space, after the clips), so the
// skin, the hand positions the weapon is drawn from and the reload's magazine
// all see the rigged pose. GTA2DX9_WEAPON_RIG=0 turns it off (the clips alone,
// as before). Files: weapon_rig.cpp, the calls in live_geometry.cpp
// DrawPedFigures. Doc: docs/actions-3d.md "Weapon handling (ANIM-WEAPONS)".
#pragma once

#include <cstdint>

#include "../../src/math3d.h"

namespace gta2dx9 {
struct Model;
namespace weaponrig {

enum Mode { kOff = 0, kAim = 1, kCarry = 2, kReload = 3 };

bool Enabled();

// The reload's event times (seconds into the clip; <0 none), as kReloads.
struct ReloadTimes { float len = 0, drop = -1, grab = -1, insert = -1, rack = -1; };

struct Inputs {
    uintptr_t object = 0;      // the figure's game object (its state is kept by it)
    int weapon = 0;            // PedWeapon numbering (1 pistol .. 10 flamethrower)
    int mode = kOff;           // from the action clip (ModeForAction)
    float modelPerBlock = 1;   // model units per block for this figure
    float lengthBlocks = 0;    // the weapon's length (kWeapons)
    uint32_t muzzleFrame = 0;  // the frame of his last shot (a change is a shot)
    uint32_t frame = 0;        // the renderer's frame counter
    float dt = 1.0f / 30.0f;
    float reloadT = -1.0f;     // seconds into the reload clip, -1 none
    ReloadTimes reload;
    bool closeUp = true;       // lod 0: fingers and head too
    bool throwing = false;     // the throw clip runs (a thrown weapon's kCarry is otherwise the low hold)
};

// The mode an action clip calls for (live_geometry's action numbers).
int ModeForAction(int action);

// Once a frame per armed figure, after the shot is known and before it is
// drawn: steps his recoil spring and mode blend and sets the pose hook (cleared
// by End). False when nothing is rigged (no hook set).
bool Begin(const Model& model, const Inputs& in);
void End();
// FIX-ACTIONS-3 (pfl15): bare fists while a punch clip is on (no gun rigged): both hands
// closed, blended by `weight` (the clip's). Sets the pose hook (cleared by End); false: none set.
bool BeginFists(const Model& model, uintptr_t object, float weight);

// The figure's push back along the line of fire by the recoil, in blocks, and
// that line in the model's own space (to put through the figure's world matrix).
float Shove(uintptr_t object, float dir[3]);

// The gun's frame in model space as the hook last built it for the current
// figure (rows: right, up, forward, unit; origin: the rear of the bore line),
// and the gun's length in model units. False when the rig does not place this
// weapon (dual pistols and the one-handed carry ride on the hand, see
// DrawPedFigures).
int GunSource();   // the last GunFrame's: 0 none, 1 the hook ran, 2 the pose cache's
bool GunFrame(gta2::Mat4* out, float* lengthModel);

// The showcase (GTA2DX9_RIG_TEST_FILE names a file holding "yaw_degrees
// fire_period_seconds"): the forced figure turned on the spot for the camera,
// and a synthetic shot every period. Re-read twice a second.
float TestYaw();
bool TestFire(uint32_t frame);
// FIX-FIGURE-11 (pfl42): the bore line's height over the grip on the weapon model (blocks, model scale 1).
float BoreHeight(int weapon);

}  // namespace weaponrig
}  // namespace gta2dx9
