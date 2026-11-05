// Cars in the ground views, built from their own top-down sprites.
//
// The classic view keeps the game's flat car sprites. When the camera is down
// on the street (SetGroundModels), each car is drawn instead as a solid body
// extruded from that very sprite: the opaque outline gives the footprint, the
// style file's CARI chunk says where the wheels sit and where the windscreen
// and rear window are, and the sprite itself - scaled up and edge-extended -
// is painted over the hood, roof and trunk, so the car seen from above is the
// car the game drew. Sides, glass, lamps and tyres are painted into the same
// texture from the sprite's own paint. Bodies are cached by sprite and
// artwork (so a repaint is its own body) and lit by the fixed-function
// pipeline, which is what makes them read as metal rather than cardboard.
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>

#include <cstdint>
#include <vector>

#include "../../src/gta2_style.h"
#include "../../src/math3d.h"

namespace gta2dx9 {

// Same layout as LiveGeometry::Vertex and kWorldFvf.
struct CarBodyVertex {
    float x, y, z;
    float nx, ny, nz;
    float u, v;
};

// The district's car measurements, from the style the level loaded with.
void CarBodiesSetInfo(const std::vector<gta2::CarInfo>& infos);

// Beyond this many blocks from the eye a car keeps its flat sprite and dome:
// the body would be a few pixels, and every body is a draw of its own.
constexpr float kCarBodyLodBlocks = 20.0f;

// One car to stand in for its flat sprite this frame.
struct CarBodyUse {
    const void* texture = nullptr;   // the sprite's TextureRecord
    int sprite = -1;                 // within the car base
    int model = -1;                  // the game's vehicle model number, -1 when unknown
    bool own = false;                // the player's own car, seen from inside in first person
    uintptr_t object = 0;            // the game object, for steering memory
    CarBodyVertex local[4];          // the body quad in its own space
    gta2::Mat4 objectToWorld;
};

// Draws every car listed, building what it has not seen. `frame` is a frame
// counter for the caches. Leaves the device's lighting and texture stage
// states as it found them (off, modulate).
// `eye` is the camera, in the world: a car the eye is inside of is left out
// (the chase camera beside a parked car), except the player's own.
void CarBodiesDraw(IDirect3DDevice9* device, const std::vector<CarBodyUse>& cars, uint32_t frame, const gta2::Vec3& eye);
void CarBodiesReleaseDevice();
// The cabin of a car drawn recently, by its sprite object, in blocks above the
// road and along the car: where the deck (hood/sill line) and the roof are,
// where the windscreen's base is ahead of the car's centre, and half the
// width. For the first-person eye at the wheel. False when the car is unknown.
bool CarBodiesCabin(const void* object, float* deck, float* roof, float* windscreen, float* halfWidth);
// Bodies built and drawn in the last call, for the overlay.
int CarBodiesBuilt();
int CarBodiesDrawn();

}  // namespace gta2dx9
