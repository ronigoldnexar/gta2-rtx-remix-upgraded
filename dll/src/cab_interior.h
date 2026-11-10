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

enum class CabClass { Car, Van, Truck, Bus, Sports, Tank };

// The class of a CARI model number, from its identity record's cab (IdentityCabFor, identity.cpp owns the
// table: FIX-COCKPIT-CAB-3); a flat-fronted body (bus, train, cab-over) is a bus whatever its number, the tank a tank.
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
    bool dashcam = false;                        // FIX-COCKPIT-BODY: the dashcam view: no wheel, column or hands
};

// FIX-COCKPIT-BODY (owner item 2): the driver's seat as the last drawn cab built it, world space, for his
// own seated figure drawn from the eye (live_geometry): the eye, the car's axes (unit; right is the
// screen's right from the seat, the car frame's +x), each hand's grip on the rim (0 left, 1 right) with the way the rim runs
// there, the rim's radius and turn. False when no cab was drawn in the last ~0.25 s (or the last was a
// dashcam, a warm draw, or had no wheel).
struct CabDriverPose {
    gta2::Vec3 eye, right, up, fwd;
    gta2::Vec3 grip[2], rimTangent[2];
    gta2::Vec3 wheelCentre, wheelAxis;   // the hub, and the column (away from the driver)
    float wheelR = 0.0f, turn = 0.0f;
    float dashBelow = 0.0f;   // the dash line under the eye (blocks)
    gta2::Vec3 pedal[2];      // the brake and the accelerator on the floor (the accelerator on the screen's right... of the two, by `right`)
    bool grip0Right = true;   // FIX-DRIVER-GEOM: grip 0's own side of the rim (its home) is the screen's right: which arm takes it
};
bool CabLastDriverPose(CabDriverPose* out);
// live_geometry, after drawing his body at the wheel this frame: the cab's own hands (fp_arm_right) give way
// to the body's next frame on (no double hands); they come back ~0.25 s after the body stops being drawn.
void CabNoteDriverBody();
bool CabDriverBodyRecent();
// FIX-COCKPIT-BODY-2: where the body's hands hold the rim, radians above its horizontal (0.52: ten to two).
void CabSetGripAngle(float radians);
// FIX-DRIVER-GEOM-2: live_geometry, placing his arms at the wheel: how far ahead of the eye (along the car's forward,
// blocks) the wrist that takes grip `grip` was put this frame. The cab's grip arc ends where a wrist came nearer than
// the 0.05 near plane allows (the fist cut open, a see-through ball: demo2_dep1, dg2_dgh1 042).
void CabReportWristFwd(int grip, float fwd);

// Under Remix (and [devtools] remix_cab_albedo != 0) the surfaces' colours go into their textures,
// the only albedo Remix reads (FIX-REMIX-NIGHT-2). Off: the plain renderer's material colours.
void CabInteriorSetRemixAlbedo(bool on);

// Releases the surface textures (device reset or loss).
void CabInteriorReleaseDevice();
void DrawCabInterior(IDirect3DDevice9* device, const gta2::Mat4& carToWorld, const CabInteriorParams& p,
                     const D3DMATERIAL9& restore);

// The lowest point on screen of the closed cab's roof lining in the middle third of the view,
// as a fraction of the view's height (0 the top), from the last DrawCabInterior within ~0.25 s;
// false when none was drawn or the car is open-topped. The HUD's top plates go under it (pm2).
bool CabHeaderScreenBottom(float* fraction);

}  // namespace gta2dx9
