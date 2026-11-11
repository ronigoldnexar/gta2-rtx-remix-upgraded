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

struct Model;

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
constexpr float kCarBodyLodBlocks = 60.0f;   // beyond the game's own window, so the dome never swaps in at a visible distance

// One car to stand in for its flat sprite this frame.
struct CarBodyUse {
    const void* texture = nullptr;   // the sprite's TextureRecord
    int sprite = -1;                 // within the car base
    int model = -1;                  // the game's vehicle model number, -1 when unknown
    bool own = false;                // the player's own car, seen from inside in first person
    bool driven = false;             // the car the player is at the wheel of, in any view (the chase camera may sit inside a long one)
    uintptr_t object = 0;            // the game object, for steering memory
    int damage = 0;                  // the vehicle's damage word (int16 at +0x74, 0 fresh .. 32000 explodes), 0 when unknown
    int fireStage = 0;               // the vehicle's damage stage byte (+0x8C): 3 burning (from 16000), 4 burning hard (from 25000)
    // A pedestrian is getting in or out of this car (ped state 3/4) and stands
    // here: the door on his side swings open while he does.
    bool doorPed = false;
    float doorPedX = 0.0f, doorPedZ = 0.0f;
    float fade = 1.0f;               // FIX-CAMERA-18: 1 whole; under 1 the car stands between the chase lens and him, fading
    CarBodyVertex local[4];          // the body quad in its own space
    gta2::Mat4 objectToWorld;
};

// Draws every car listed, building what it has not seen. `frame` is a frame
// counter for the caches. Leaves the device's lighting and texture stage
// states as it found them (off, modulate).
// `eye` is the camera, in the world: a car the eye is inside of is left out
// (the chase camera beside a parked car), except the player's own.
void CarBodiesDraw(IDirect3DDevice9* device, const std::vector<CarBodyUse>& cars, uint32_t frame, const gta2::Vec3& eye);
// Lamps on the bodies: 0 none, 1 headlamps/tail lamps when it is dark (the
// sky's sun is low) plus brake lamps when a car slows, 2 always lit.
void CarBodiesSetLamps(int mode, bool dark);
void CarBodiesReleaseDevice();
// The cabin of a car drawn recently, by its sprite object, in blocks above the
// road and along the car: where the deck (hood/sill line) and the roof are,
// where the windscreen's base is ahead of the car's centre, and half the
// width. For the first-person eye at the wheel. False when the car is unknown.
// FIX-SEAT-ENTRY-4 (pmt6): [devtools] seated_sep=1 lets the figures' draw-only separation push a seated
// driver out of his car (the old behaviour, for A/B); default 0.
bool CarBodiesSeatedSep();
bool CarBodiesCabin(const void* object, float* deck, float* roof, float* windscreen, float* halfWidth);
// The same car's body as drawn: its length and full height (roof gear included)
// in blocks and half its width, for the chase camera's framing. False when unknown.
bool CarBodiesExtent(const void* object, float* length, float* height, float* halfWidth);
// Bodies built and drawn in the last call, for the overlay.
// Developer aid: draw every car as one of the wreck models ([devtools] wreck_models=1).
void CarBodiesSetWreckTest(bool on);
// VEHICLE-ART-3: the charred, roof-sagged copy of a whole car's model that its wreck is drawn
// with (cached; null for a model it cannot copy). Called by identity.cpp only.
const Model* CarWreckCopyOf(const Model& model);
// Developer aid: the ini whose [devtools] force_car_model=N (every traffic car drawn as
// model N, -1 off) is re-read once a second, so a script can step through the models.
void CarBodiesSetDevIni(const char* ini);
// That ini's path ("" when devtools are off), for other [devtools] keys re-read while the game runs.
const char* CarBodiesDevIni();
// The tank's turret / the fire truck's roof gear points along (dirX, dirZ) in the
// world (renderer frame, the ground plane), seen this frame for the car whose
// sprite object is `carObject`: the game's own turret sprite. Held for a second.
void CarBodiesSetTurret(uintptr_t carObject, float dirX, float dirZ, uint32_t frame);
// VEHICLE-GLASS: the world height where this frame's drawn body of `object` meets the road.
bool CarBodiesGround(const void* object, float* y);
// FIX-FIGURE-6 (pm3-third-ped-stands-inside-parked-ambulance): this frame's drawn car footprints (world
// xz, the body's separation push included): centre, road height, across (r) and nose (f) axes, half
// sizes. For the figures' draw-only slide out of a body. Returns how many were written.
struct CarFootprint { uintptr_t object; float cx, cy, cz, rx, rz, fx, fz, hx, hz; };
int CarBodiesFootprints(CarFootprint* out, int max);
// VEHICLE-ART-5: where the drawn car's tyres touch the road (world x, z), their radii and the car's
// nose axis (world xz, unit), for the tyres' own contact shadows; 0 when its wheels are not cut.
bool CarBodiesTyreShadowsOn();   // [devtools] tyre_shadows (default on): the two above, for A/B
int CarBodiesWheelContacts(const void* object, float* x, float* z, float* r, float* ax, float* az, int max);
int CarBodiesBuilt();
int CarBodiesDrawn();
// The last call's time, ms: [0] measuring artwork, [1] building sprite bodies,
// [2] drawing models, [3] drawing sprite bodies; [4..7] the matching counts.
const double* CarBodiesStats();
// FIX-PERF-3: the model-drawn cars' time by part in the last call (ms) and the parts' names; returns the count.
int CarBodiesPartStats(const double** ms, const char* const** names);

// FIX-CAR-RENDER: the luminance floor of a car's live paint, a fraction of white
// ([renderer] car_paint_floor_percent, default 30; 0 off): a near-black repaint keeps
// enough albedo to show its shading, and a dark body gets a broader, sky-tinted sheen.
void SetCarPaintFloor(float fraction);

// FIX-COCKPIT-CAB-4: [devtools] fp_near_min_milli, the first-person look-down near plane floor (-1: the default).
int CarDevFpNearMinMilli();
int CarDevFpNearDeepMilli();   // [devtools] fp_near_deep_milli: the floor looking straight down (-1: the default)
// FIX-FP-EXIT-1 (pfl79, qaf72): the first-person exit. view_modes asks every frame of the exit for the held car's
// driver's door (target 0 shut .. 1 open; the door's side is the one a world point lies on, the seat's eye) and
// car_bodies drives it even while the car is drawn cut round the eye (the swung door drawn, the cab's door card
// left out), and the eye counts as inside the body only while it is within the hull's own sides (the 0.15 margin
// drew the cut hull round an eye already outside it). The request lapses ~0.1 s after the last call.
void CarBodiesFpExitDoor(uintptr_t carObject, float wx, float wz, float target);
// The held car as last drawn (posed car-to-world rows: x across, y up, z forward, unit; origin on the road at its
// middle), its half width and length, the driver's door span along z (hinge, rear edge), its roof, the door's side and
// how far it is open, and the origin's step since the frame before (the camera runs a frame ahead of the draw).
struct FpExitCarFrame { gta2::Mat4 m; float halfW = 0, halfL = 0, zFront = 0, zRear = 0, roof = 0, open = 0, stepX = 0, stepZ = 0; int side = 0; uint32_t age = 0; };
bool CarBodiesFpExitCar(uintptr_t carObject, FpExitCarFrame* out);
}  // namespace gta2dx9
