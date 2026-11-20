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

## STAIR-RAILINGS: diagonal and braced railings (20 Nov 2026)

The railings along the flights of steps (Downtown's 'Jesus Saves' church steps at 190-193,177-178 among them)
were the engine's own flat cut-out panels, wil tiles 88-91: a sloped handrail and stringer, posts between them
and knee braces into the posts. QB-11 leaves them alone (it takes only full-width flat rails with vertical bars);
close up, the 8x-upscaled diagonal alpha edge of the art is a sawtooth, and the panel is a sheet of paper.

- `src/world_mesh.cpp` (`AnalyseStair`, `MeshBuilder::StairOf`, the stair branch of `TryRailing`): read from the
  tile's own alpha at world build, no table of tile numbers. A pixel in a row run of 5 or more opaque pixels is
  'rail'; the connected rails that are straight (top edge on one line, level and full width, or at the stairs'
  pitch, slope 0.35-0.7, 40 px or more across; two parallel rails in one set are peeled one by one) become strips:
  an edge line and a thickness read as medians over the columns, so the roots of the braces and the tile border
  clipping a rail do not count. What is left (posts, braces, feet) is read as plain sets. Every set is traced round,
  simplified (Douglas-Peucker, 1 px, the tile's border pinned so a rail leaves a tile where the next one picks it
  up: the 2:1 pixel staircase of the art becomes one straight edge), ear-clipped, and extruded: both faces carry the
  art's own texture coordinates, the sides sample the iron just inside the edge. Depth: a rail 0.8 of its
  thickness (2-5 px), a post or brace its own width (1.5-4 px). A level rail needs to be a landing's (a top rail 4+
  rows over a heavy 10+ one, 2+ posts between), so girders, grilles and fences keep their panels; the cover of the
  rebuilt pieces must be 80% IoU of the mask. Whole-tile vertical faces only, as QB-11; the panel goes through the
  face's own texture mapping, so flips, rotations and both slope directions are honoured. The flat panel is not
  emitted where the model replaces it (its two sides give one model, as in QB-11); the panel's plane still goes into
  `WorldMesh::railingPanels` for the camera.
- Tiles that qualify (wil 88-91; bil 18-20, 844-846, 856-858, 908-910; ste 987-989) and their uses, from the
  maps: wil 1 202 panels, bil 954, ste 340 (flat faces counted per panel plane). Orientations seen: along x and along y,
  rising either way (the flip bit), at the face's low and high levels.
- Toggle: `[renderer] stair_railings=1` (ini, default on), `GTA2DX9_STAIR_RAILINGS=0|1` (environment, read at each
  world build, wins over the ini) gives the flat panels back; `GTA2DX9_RAILINGS=0` still turns QB-11's off. The log
  line `stair railings (STAIR-RAILINGS): modelled, <n> of those panel(s) ...` follows the QB-11 one.
- Classic top-down view: unchanged (it does not draw the world mesh's railings): vreg `spawn_classic` result below.

Triangles (host build, `GTA2DX9_STAIR_RAILINGS=0` vs on; the geometry joins each tile's opaque batch, no new draw):

| district | stair tiles | stair panels | world triangles before | after | added |
|---|---|---|---|---|---|
| wil | 4 | 1 202 | 534 350 | 656 044 | +121 694 (+22.8%) |
| bil | 12 | 954 | 661 845 | 723 855 | +62 010 (+9.4%) |
| ste | 3 | 340 | 762 734 | 807 572 | +44 838 (+5.9%) |

A panel costs 50-190 triangles (wil 91 about 150, a flat tile 88 landing about 100). Downtown's is the big one
because tile 88, the landing piece, is its commonest railing. Not done: leaving the flat panel where the street
never reaches (as QB-11's note says for the Industrial map-edge ring).
