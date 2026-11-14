#pragma once
// The street views' camera against the drawn world (BLOCKER fp-camera-sees-through-wall,
// FIX-OCCLUSION).
//
// The camera's older clearance tests (WorldView::Blocked / Walled / PanelPush) ask the
// map's cells: is this point in a block with a wall face, how far is it from a flat panel
// on a cell edge. A diagonal wall (the chamfered church corner in wil, slope types 45-48),
// a partial block or any face that does not lie on a cell edge is invisible to them, and the
// first-person eye went to 0.03 of such a face: the 0.05 near plane cut the wall open and
// the frame showed the inside of the block (backfaces, a black void, sky).
//
// This module keeps the triangles of the static world mesh (the one the street views draw)
// in a 256x256 cell grid and answers against them:
//   - Push: the eye as a sphere, slid out of every surface it overlaps (front side of a
//     one-sided face, either side of a two-sided one; the floor under him is out of reach, left to the
//     game's own floor logic);
//   - SegmentHit: the first surface a segment crosses (the line from his head to the eye,
//     the camera's path in a view transition), so the eye can never be put on the far side
//     of a wall;
//   - DrawInteriorCaps: the solidity fallback. Back sides of the faces round the eye, drawn
//     opaque in the wall's own darkened tone with the cull reversed: from outside every one of
//     them is behind its own front face (depth-tested away, never seen); they are drawn only
//     while the eye is inside a closed block (InsideSolid), and then close it, so the block
//     reads as a solid mass instead of a hole to the sky. A pocket behind a diagonal or
//     partial face whose other sides are front faces of the next blocks (the wil church
//     corner) is not a closed block: only the collision keeps the eye out of that.
//
// Renderer coordinates (x east, y up, z north = kMapHeight - map y), as WorldMesh.
#ifndef EYECOL_NATIVE
#include <d3d9.h>
#endif

#include "../../src/math3d.h"

namespace gta2 { struct WorldMesh; class Style; }

namespace eyecol {

void Build(const gta2::WorldMesh& mesh, const gta2::Style& style);
bool Ready();

// Moves *p out of every surface closer than radius (a few passes for corners). Returns the
// distance moved (0 when nothing was near).
float Push(gta2::Vec3* p, float radius);
// DISTRICTS (ship candidate): extra clearance from walls (one-sided faces with a horizontal normal) on top of every
// radius, while the facade kit is on: the kit stands up to 0.25 block out of the walls the collision knows, and a
// street camera at 0.12-0.24 from a wall sat inside it (sills, cornices and canopies across the lens). 0 = none.
void SetWallClearance(float extra);

// Push against the railings' sheets only (WorldMesh::railingPanels): a wider berth for the
// chase camera than the general surfaces get, the bars' spear tops being thick near the lens.
float PushPanels(gta2::Vec3* p, float radius);

// The first surface the segment a->b crosses from its front (a one-sided face) or from
// either side (a two-sided one). *t is the fraction along a->b.
bool SegmentHit(const gta2::Vec3& a, const gta2::Vec3& b, float* t);

// SegmentHit against one-sided faces (walls, lids) only, the two-sided panels ignored.
bool SegmentHitWalls(const gta2::Vec3& a, const gta2::Vec3& b, float* t);

// FIX-CAMERA-6: SegmentHitWalls without a railing's bars, rails and finials either (the faces on a railing
// sheet's plane): what the chase boom may not pass at all, as against what it eases in at.
bool SegmentHitSolid(const gta2::Vec3& a, const gta2::Vec3& b, float* t);

// FIX-PERF-7: whether any one-sided face (a wall, a lid) crossed from its front lies on the segment a->b, more than
// `skipA` from a: the car view cull's occlusion ray. A cell walk along the segment that stops at the first such face
// (SegmentHitWalls scans every cell of the segment's bounding box and looks for the nearest).
bool SegmentBlocked(const gta2::Vec3& a, const gta2::Vec3& b, float skipA);

// FIX-CAMERA-7 (pfeel3 residual): while set (> 0), SegmentHit and its variants ignore a two-sided sheet or a
// railing's bar crossed within `distance` of the segment's start. The chase boom's segments start at his
// centre, and the plaza fence's sheet lies on a cell edge his body overlaps: 2 cm past it, every line from
// him crossed it at t=0 and the boom fell into his head (run cam7_base punch_0). 0 turns it off.
void SetNearSoftSkip(float distance);
float NearSoftSkip();

// The nearest surface within maxR of p (no side rule): its distance, or maxR.
float Nearest(const gta2::Vec3& p, float maxR);

// The eye as the camera may show it: from `head` (a point the game keeps outside walls,
// his centre at eye height) toward *eye, stopped `radius` short of the first surface on the
// way, then pushed clear by radius. Returns how far the eye moved.
float Clear(const gta2::Vec3& head, gta2::Vec3* eye, float radius);

// Whether p is inside a closed block of the mesh: straight up is the back of a roof, and all
// eight horizontal ways out leave through the back of a face, none through a front.
bool InsideSolid(const gta2::Vec3& p);

// The solidity fallback, see above: drawn only while InsideSolid(eye). Call after the static world is drawn, street views only.
#ifndef EYECOL_NATIVE
void DrawInteriorCaps(IDirect3DDevice9* device, const gta2::Vec3& eye, DWORD worldCull);
#endif

// Counters for the log line once a second.
struct Stats {
    int pushes = 0;        // frames the eye was moved
    float maxPush = 0.0f;  // the largest move since the last read
    int segmentStops = 0;  // frames the head->eye line crossed a surface
    int capTris = 0;       // triangles in the last cap pass
};
Stats TakeStats();
void NoteSegmentStop();

}  // namespace eyecol
