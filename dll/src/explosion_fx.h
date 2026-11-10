// Explosions in the street views (QB-19): a volumetric fireball with light.
//
// GTA2 draws a blast as one flat animated sprite. Stood up for a street-level camera
// (live_geometry.cpp) it reads as a cardboard cut-out. This adds, at every blast the
// sprite loop sees (an effect sprite bigger than [fire] fire_max_size_percent):
//
//   - a fireball: a few dozen camera-facing billows thrown out and up, white-hot at
//     birth, cooling through orange and red, each leaving a dark smoke billow behind
//     as it burns out, so the ball turns into a rolling cloud;
//   - the flash: a glow over the blast, a pool of orange light on the ground around it
//     and a point light on the car models nearby (plain renderer only; under RTX Remix
//     the additive billows are emissive particles and light the street themselves);
//   - a shock wave: a bright ring racing out over the ground and a skirt of dust;
//   - sparks and burning bits on ballistic arcs that bounce once;
//   - a smoke column that keeps rising off the spot for [explosions] smoke_seconds.
//
// The game's own sprite is kept under it, dimmed ([explosions] sprite_percent).
// Street views only: the classic top-down view never sees any of it.
#pragma once

#include <d3d9.h>

#include "../../src/math3d.h"

namespace gta2dx9 {

struct ExplosionSettings {
    bool  enabled = true;
    float size = 1.0f;          // scale on the whole blast
    float flash = 1.0f;         // scale on the flash, the ground light and the car light
    float smokeSeconds = 10.0f; // how long the column keeps rising off the spot
    float spriteBright = 0.35f; // what is kept of the game's own explosion sprite
    bool  carLight = true;      // a point light on the car models while the blast flashes
    float eyeBudget = 0.5f;     // FIX-FX-3: the additive light a blast may throw over the view (full frames)
};
ExplosionSettings& ExplosionFx();
// The [explosions] section of the renderer's ini. GTA2DX9_EXPLOSION_FX=0 turns it off.
void ExplosionFxLoad(const char* iniPath);

// A blast sprite seen this frame at (x, z), its ground at groundY, `size` tiles across.
// The sprite is seen on many frames while it plays: a spot that had one less than half a
// second ago is the same blast.
void ExplosionFxNote(float x, float groundY, float z, float size);

// Steps and draws everything alive. `forward` is the camera's view direction; fvf is
// restored on the way out. Leaves blending on, z-write on, alpha test off.
// The camera's eye, so particles close to it fade out instead of filling the view.
void ExplosionFxSetEye(float x, float y, float z);
// The eye last set (FIX-FX-2: the fire light dims round it); false when no street view drew lately.
bool ExplosionFxEye(float eye[3]);
void ExplosionFxDraw(IDirect3DDevice9* device, const gta2::Vec3& forward, DWORD fvf);

// The strongest light the blasts cast right now: where, its colour (may exceed 1) and
// reach in tiles. False when nothing is lit.
bool ExplosionFxLight(float pos[3], float rgb[3], float* range);

// How fresh a blast within `radius` of (x, z) is: 1 at the bang, 0 two seconds on (FIX-FX-2:
// the fire lights there are the blast's own and are held down while this module's flash plays).
float ExplosionFxBlastShare(float x, float z, float radius);

// FIX-FX-4: [devtools] force_blast / force_burn act here, from gbh_BeginScene (the game's
// logic for the frame is done and its draw has not started), on the car the last street-view
// frame picked. Nothing when no request is pending.
void ExplosionFxGameTick();

// Blasts noted and particles alive, for the log.
int ExplosionFxBlasts();
int ExplosionFxParticles();

}  // namespace gta2dx9
