# QB-11: railings as models (9 Nov 2026)

Wave C row QB-11 (`docs/quality-bar.md` row 11, "pixel-extruded hedges and fence tops"). The Downtown
park fence is wil tile 635: a flat alpha-tested panel of four bars, three rails and a spear finial on
each bar. Its upscaled HD art turned the finials into dark blocky blobs with orange specks, and from
the street the whole fence read as cut-out paper.

## What changed

- `src/world_mesh.cpp` (`AnalyseRailing`, `MeshBuilder::TryRailing`): at world build, every tile
  that sits on a flat panel (a flat face, or the back of one) is read from its own 64 px alpha mask.
  The tile counts as a railing when the cut-out is nothing but full-width horizontal rails (each 10
  rows or less) and a row of at least three vertical bars (8 px wide or less), with an optional
  finial above each bar, and that rebuild covers the mask at 92% IoU or better. Lattices, X braces,
  hoardings, window frames and single poles fail the test and keep their flat panel.
- Such a panel is built as geometry on the panel's plane instead of the flat quad: square bars (as
  deep as they are wide), flat rails (0.7 of the bar width deep), and each finial as a four-sided
  lathe of the artwork's own outline row by row, simplified (Douglas-Peucker, 0.6 px), so the spear
  keeps its tip, belly, neck and collar. The placement goes through the face's own texture mapping,
  so flips and rotations are honoured. Whole-tile vertical faces only: a ramp-cropped or partial
  face keeps its panel. The two sides of a panel produce one railing.
- The geometry samples the tile's own opaque pixels (bars and rails their own texels; finials a
  band of the bar's iron, not the blobs), so it keeps the tile's texture, its HD replacement and
  its Remix hash. It goes into the tile's opaque batch: no new draw, no new texture.
- `GTA2DX9_RAILINGS=0` (environment, read at each world build) gives the flat panels back, for
  before/after runs. On by default.
- `world_view.cpp` logs `railings (QB-11): modelled, <tiles>, <panels> from <quads>, <triangles>`
  next to `world loaded`.

## Triangle count (host build of the world mesh from the shipped maps, `GTA2DX9_RAILINGS=0` vs on)

| district | railing tiles | panels | world triangles before | after | added |
|---|---|---|---|---|---|
| wil (Downtown) | 2 (635 spear fence, 217 bar fence) | 233 | 408 328 | 441 832 | +33 504 (+8.2%) |
| bil (Residential) | 2 | 288 | 454 585 | 478 777 | +24 192 (+5.3%) |
| ste (Industrial) | 4 (52, 886, 909, 47 on walls) | 895 | 426 384 | 502 538 | +76 154 (+17.9%) |

Per panel: wil 635 about 290 triangles (4 bars, 3 rails, 4 finials of ~6 rings), a plain bar fence
(8 bars, 2 rails) about 90. For scale, one slim street lamp (PROPS-SLIM) is 1 656. The world mesh is
static and uploaded once; the railings add no draw calls (they join the tile's existing opaque batch,
and the alpha-tested batch they leave usually disappears). Industrial's count is high because tile 52
rings the map edge; a later cut could keep the flat panel for panels the street never reaches.

## Verification

- Offline: the world mesh around the park fence (147,116-118) rendered with the HD tiles, flat
  panel vs model (`qb11/r635_flat.png`, `qb11/r635.png`, workspace): bars, rails and spear finials
  with depth; the finial no longer shows the blob and speck art.
- In game (`linux/docker/qb11_railings.py`, run `out/qb11_rl1`, private stage = HEAD + this change, GPU
  build, Downtown): the log has `world loaded: ... 441802 triangles` and `railings (QB-11): modelled,
  2 tile(s), 233 panel(s) from 466 flat quads, 34436 triangles`, the railing numbers the host build gives; 0 FAULT
  lines. Frames at the park's spear fence (146.3,121.5 and 148.5,117.3) and a bar fence
  (205.5,36.2), third and first person at six headings: bars, rails and spear finials stand with
  depth and shading along the pavement, no blob art; the classic view frames at each spot are
  unchanged (the classic view is the game's own drawing, the world mesh is not used there).
- Not run in game: a before/after A/B with `GTA2DX9_RAILINGS=0` (the host was at load 17-85; the
  before is the quality-bar evidence frame `frames/fence_hedges.png`), and frame times.

## Not done / open

- Hedges: Downtown has no hedge tiles on panels; the green pyramids in the park (wil 849, ste 530,
  bil 220 on corner-ramp blocks) are block-built trees, not hedges, and are left as they are.
- Lattices, X-braced girder rails, ornamental scrollwork (wil 536), balustrades on stone (wil 3) and
  the bridge rails (wil 88/194) keep their flat panels.
- Remix: the geometry uses the tile's hash, so its replacement material applies; no Remix frame taken.

## The fence's colour in the street views (FIX-WORLD-3, pm5)

Defect `pm5-iron-fence-renders-solid-black-blocks`. Filmed again on HEAD 91f7442 with fixed poses
(`out/fw3_pm5_base`, poses `gamerun/fw3_poses_wil.txt` along the park fence at y=147): the model is
fine (bars, rails, finials and gaps resolved at 5 m, no stair-stepping), but it read as a black
silhouette. The bars measured 15/255 because wil 635's HD art averages 18/255 over its opaque texels,
with orange specks on the finials. `tools/railing_metal_tiles.py` writes the photo-set copy of the tile
(street views only; classic and Remix keep the HD tile): dark grey painted iron at a mean of 58/255.
The art's own luminance is kept as relief, the colour is a cool neutral grey and the alpha is unchanged.
Run on the fix stage (`out/fw3_pm5_fix`), the bars measure 46-53/255 and the finials' bevels and the
rails catch the light. Classic frames right after load are identical in the centre crop. No specular
term was added: the world shader has none and the defect's luminance bar is met without one.
