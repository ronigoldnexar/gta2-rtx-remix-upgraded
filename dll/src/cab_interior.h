// QB-31: the cab seen from the driver's seat, per vehicle class.
//
// In first person the player's own car is its hood copy (car_bodies.cpp,
// HoodModelFor: the hull cut a hand under the eye and just ahead of it). QB-5
// closed the cut with a flat panel in a darker shade of the paint (DrawDash);
// from the seat that read as a dark featureless slab across the bottom of the
// view (quality-bar row 31). This draws a cab instead: a shaped dashboard with
// a defroster vent strip, an instrument binnacle with lit gauges whose needles
// follow the speed, a steering wheel that turns with the front wheels, the
// windscreen header with a rear-view mirror, the near A-pillar and the near
// door mirror. Four classes (car, van, truck, bus) differ in colours, wheel size
// and rake, binnacle width, header depth and mirror size.
//
// Everything is built in the car's own frame (x across, y up from the road, z
// the nose) around the eye, untextured and lit by the scene's lights, and drawn
// with the user clip plane off (the plain renderer clips the own car a hand
// below the eye; the header and mirrors sit above it).
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>

#include "../../src/math3d.h"

namespace gta2dx9 {

enum class CabClass { Car, Van, Truck, Bus, Sports };

// The class of a CARI model number (0..71); a flat-fronted body (bus, train,
// cab-over) is a bus whatever its number.
CabClass CabClassFor(int modelNumber, bool flatFront);
const char* CabClassName(CabClass c);
// An open-top body (roadster, jeep): the cab has no roof lining, only the windscreen frame.
bool CabOpenTop(int modelNumber);

struct CabInteriorParams {
    CabClass cls = CabClass::Car;
    float eyeX = 0, eyeY = 0, eyeZ = 0;          // the eye in the car's frame
    float zCut = 0;                              // the hood copy's windscreen cut (car frame z)
    float dashTop = 0, dashX0 = 0, dashX1 = 0;   // the hood copy's dashboard line (HoodCopy)
    float paint[3] = {0.5f, 0.5f, 0.5f};         // body paint 0..1 (worn)
    float steer = 0;                             // front wheels, radians
    float speed = 0;                             // blocks/s along the nose
    bool night = false;                          // gauges lit
    bool openTop = false;                        // no roof lining (FIX-COCKPIT-2)
    bool taxi = false;                           // a fare meter on the dash (FIX-FIGURE)
    bool hands = true;                           // the driver's hands on the wheel (FIX-FP-2)
    bool warm = false;                           // FIX-SEAT-ENTRY-2: an unseen draw ahead of the seat view (no state kept)
};

// Releases the surface textures (device reset or loss).
void CabInteriorReleaseDevice();
void DrawCabInterior(IDirect3DDevice9* device, const gta2::Mat4& carToWorld, const CabInteriorParams& p,
                     const D3DMATERIAL9& restore);

// The lowest point on screen of the closed cab's roof lining in the middle third of the view,
// as a fraction of the view's height (0 the top), from the last DrawCabInterior within ~0.25 s;
// false when none was drawn or the car is open-topped. The HUD's top plates go under it (pm2).
bool CabHeaderScreenBottom(float* fraction);

}  // namespace gta2dx9
