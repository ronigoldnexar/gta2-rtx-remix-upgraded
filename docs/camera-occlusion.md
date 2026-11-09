# Camera against the drawn world (FIX-OCCLUSION, 9 Nov 2026)

BLOCKER `fp-camera-sees-through-wall-backfaces-and-void`, reported by the owner on
`DEMO_classic_to_3d_realtime_v2_20261109.mp4`: switching to first person beside the church in
Downtown, the view went into the wall: a backfacing teal slab, a black void, sky above the wall
line (t=56..58 s).

## Cause

The camera's clearance tests (`WorldView::Blocked`, `Walled`, `PanelPush`, the QB-49 step-back
in `view_modes.cpp`) all ask the map's **cells**: is this point in a block with a wall face, how
far is it from a flat panel on a cell edge. They are blind to every face that does not lie on a
cell edge. The church corner in wil is a **diagonal** block (map cell 164,137, slope 45-48); the
first-person eye (0.12 ahead of his centre) went to **0.01-0.03** of the diagonal brick face. The
renderer's near plane is 0.05 (`src/camera.h`), so the face was cut open and the frame showed
the pocket behind it: the front faces of the neighbouring blocks that bound it (the teal slab),
a dark tile, and sky through the missing ceiling. The run's own log said so:
`view: fp eye: wall 0.00 ahead, eye stepped back 0.00` (the cell test saw the eye's own cell as a
wall and every step back as a wall too, so nothing moved).

The clearance mechanism therefore did **not** test block faces as surfaces at all, only cells,
and it tested thin props (railings, `PanelPush`) only on cell edges.

## The fix (dll/src/eye_collision.cpp)

The street views' camera now collides with the **same triangles the street views draw**: the
static world mesh (`BuildWorldMesh`, street fill included) is kept in a 256x256 cell grid at
world load (448k triangles, 22.6 MB; log line `eye collision: ...`).

- `eyecol::Clear(head, eye, r)`: from his centre at eye height the eye goes no further than the
  first surface on the way (segment test, front faces of one-sided batches, both sides of
  two-sided ones), then is pushed out of every surface closer than `r` (sphere against
  triangles, deepest overlap first, up to six passes for corners), **sideways** where it can,
  so it slides along a wall instead of stopping, and keeps its height at a ramp's edge.
  Standing inside a thin post or a railing's bars (the game walks him into props it does not
  know), the segment test ignores the two-sided panels round him and the eye is taken to the
  clear place outside the post nearest where it was meant; walls still stop it.
  First person: `r` = 0.24 on foot, 0.12 in a car's cabin. Last step of the first-person eye,
  after the bob, the glide and the older tests.
- The QB-49 "wall ahead" distance also takes the mesh ray along the view, so the 0.32 step-back
  of `pt-fp-wall-closeup-smear` now works at a diagonal wall too.
- View transitions (`WorldView::ApplyTransition`): every point of the move into a street view is
  `Clear`ed against the destination (0.15), so the camera never travels through a wall.
- Safety net, every street view (third person and transitions included, never the classic view):
  the shown camera is pushed 0.12 clear of every surface: more than the near plane's corner reach
  (0.093 at the widest field of view), so no wall can be cut open in any mode.
- Solidity fallback (`DrawInteriorCaps`): when the eye is inside a **closed** block
  (`InsideSolid`: straight up is the back of a roof, and all eight horizontal ways out leave
  through the back of a face, none through a front; a transition point found inside one waits at
  the last outside position),
  the backs of the faces within 6 blocks are drawn opaque in each tile's darkened mean colour with
  the cull reversed, so the block reads as a solid mass, not a hole to the sky. It never draws
  with the eye outside a block, so it cannot pop in normal play, and never under RTX Remix.
  A pocket behind a diagonal or partial face whose other sides are front faces of the next
  blocks (the church corner) is **not** a closed block: only the collision keeps the eye out of it.

`GTA2DX9_EYE_COLLISION=0` turns all of it off (the cell tests alone, as before) for a before/after run.

Log: `view: fp eye: surface clearance moved the eye ...` (first 40), the once-a-second
`view: fp eye ... surface <nearest> (clear: <moves>, max, segment stops, caps <tris>)`, and for
every street view once a second `view: camera clearance (<mode>[, moving]): nearest surface <d> at
<x,y,z> over <n> frames, safety net moved <k> frames`.

## Regression probe (tools/eye_probe.cpp)

Native, no game: the real map and style, the DLL's world mesh and the DLL's `eye_collision.cpp`.

```
g++ -O2 -std=c++17 -DEYECOL_NATIVE tools/eye_probe.cpp dll/src/eye_collision.cpp \
    src/world_mesh.cpp src/gta2_map.cpp src/gta2_style.cpp -Isrc -o eye_probe
eye_probe sweep <map.gmp> <style.sty> [x0 y0 x1 y1] [step]   # exit 1 on any failure
eye_probe at    <map> <sty> <hx> <hy> <hz> <heading>          # one case
eye_probe spots <map> <sty> ...                               # places for in-game checks
eye_probe near  <map> <sty> <x> <y> <z> [r]                   # triangles round a point
```

`sweep` stands him at 3x3 points of every walkable cell near a surface, 16 headings each, places
the eye as the game does (0.12 ahead) and as `Clear` leaves it, and casts a 5x4 fan over the view
frustum from the 0.05 near plane. A view **sees through** when a ray's first surface within 3
blocks is the back of a one-sided face; it is **near-clipped** when a surface is closer than
0.115. It also counts eyes left behind a face and eyes judged inside a block (where the caps
would draw). Views seen through from an eye >= 0.2 from every surface are holes in the mesh
(FIX-WORLD's class), counted separately. Whole maps at step 3 (every third cell), 9 Nov:

| map | eyes | raw: sees through | raw: near-clipped | cleared: sees through / near-clipped / behind a wall / judged inside |
|---|---|---|---|---|
| wil | 772,944 | 16,182 | 38,961 | 0 / 0 / 0 / 0 |
| bil | 737,856 | 20,236 | 43,162 | 0 / 0 / 0 / 0 |
| ste | 737,328 | 17,246 | 35,379 | 0 / 0 / 0 / 0 (64 eyes taken out of a post he stood inside, by design) |

"Raw" is the eye 0.12 ahead of him with no clearance at all (the cell tests are not modelled).

Limit: the probe builds the mesh without the game's slope table (`slopes = nullptr`, as
`world_raycast`), so a few sloped cells differ from the game's mesh.

## Verified (9 Nov, private stage, GPU 2)

- Owner's case, A/B with a fixed camera at the demo's exact eye (164.37, 137.61, level 2.43,
  `GTA2DX9_REGRESS_CAM`, which bypasses the camera code): HEAD 4393335 draws the owner's frame
  (teal slab, black void, sky); the fix cannot prevent a pose forced past it (the pocket is not a
  closed block), so the in-game proof is the collision: in play the eye never gets there.
- In game, first person pressed into walls at many angles, turning while pressing, and the view
  switched classic -> third -> first standing at the wall: wil (7 spots incl. the church corner),
  bil (6), ste (6, incl. a railing post). Frames read solid; 0 faults; the once-a-second
  `camera clearance` log never fell below 0.115 in any mode or transition in the final runs
  (wil 251 s, ste 216 s); the caps never drew.
- Classic: the spawn frames of HEAD and the fix are identical in every world pixel (only two
  animated HUD elements differ between the runs); vreg `spawn_classic` PASS, 0 tiles.
- vreg against HEAD (same capture, fix vs base): fixed poses identical but for traffic, except
  `bank_chase` (that pose is inside a roofed structure: the caps now close it where HEAD saw out
  through its walls), `spawn_third` (the chase camera stood 0.02 from the stair railing; the net
  keeps it 0.12 clear) and `spawn_first` (the eye kept 0.24 from the railing). The goldens
  (48a9b58) are older than HEAD's lighting and fail HEAD too; reseed after review.
- Cost: 7.5 us a frame natively for the first-person clear, the net, the clearance log and the
  inside test; 22.6 MB for the collision grid.

Not verified: under RTX Remix (the caps are off there; the collision is renderer-independent).

## Not this fault

The soft, magnified texture when the eye is a hand from a wall (board 15
`fp-wall-texture-soft-at-close-range`, `pt-fp-wall-closeup-smear`) is a separate cosmetic fault:
in the demo, t=54 (third person pressed to the brick) and t=55 (the first first-person frame, one
teal brick filling the screen) show it; t=56-58 are the near-plane cut (this fault).
