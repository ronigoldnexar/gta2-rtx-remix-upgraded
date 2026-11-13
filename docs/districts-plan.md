# District identities and real 3D architecture: POC and scale-up plan (DISTRICTS-POC, 13 Nov 2026)

Branch `districts-poc` only: nothing here is shipped, merged or restaged. Off by default (`[districts] facade_kit=0`).

## 1. What the POC is

Three buildings, one per level, picked from an automatically built catalogue and upgraded by one generic,
parametric facade kit, drawn by the renderer as street-only geometry:

| Level | Building (catalogue id) | Archetype | Kit |
|---|---|---|---|
| Downtown (wil) | #490, cells (110..135, 105..111), 5 levels | office tower | 459 recessed openings, sills, art cornice + parapet, plinth; 14.9k triangles |
| Residential (ste) | #486, cells (206..216, 90..97), 4 levels | brownstone | 72 recesses, sills, lintels, cornice, plinth, fire escape (3 landings, 2 flights, drop ladder); 5.0k triangles |
| Industrial (bil) | #402, cells (109..116, 50..51), 3 levels | factory | 92 recesses, sills, lintels, cornice + parapet, plinth, 4 door canopies; 3.7k triangles |

Pipeline (all in `tools/districts/`, Python + numpy + Pillow; Blender 4.2 for offline previews):

1. `catalogue.py` - per level: the **district map** (cell -> district, from the map's ZONE chunk with priority
   local-nav > gang > nav > level default, smallest zone first within a kind, then the hand-editable
   `overrides/<lvl>.json`: rects, display names, style-table row per district; names from the game's `e.gxt`),
   a coloured map PNG, and the **building catalogue**: cells whose roof stands at least one level over the street
   (the road level spread from the road cells), split into roof-height plateaus; thin parts (roof rims, parapet
   rings, ledges: no 2x2 square of their own) are merged into the neighbour they share most edge with. Per
   building: footprint, bbox, roof height(s), street level, levels, district, every exterior wall face with the
   tile id and raw face word per level.
2. `analyze.py` - per wall tile: openings (window / door / shop window / sill boxes; the Qwen3-VL-8B grounding
   already committed as `tools/facade_boxes.json`, Apache-2.0, cleaned; plus a dark-region detector for doorways
   and arches the grounding missed) and image features (colour, brick score, rib score, window share). Per
   building: an archetype by rules over shape + tiles (brick tenement, brownstone, office tower, shopfront row,
   warehouse, factory, house, block, structure) with the evidence kept.
3. `pick.py` - the representative visible building: target archetypes per level x street-facing wall with
   openings x height term x completeness of that wall x 0.6 inside a landmark (local-nav) zone, bonus near a
   vreg point.
4. `kit.py` + `kit_textures.py` - the facade kit (section 2) and its 11 procedural materials (fixed seeds: same
   bytes, same Remix hash, every build). Output `<lvl>.kit` (binary, groups by texture) + an owners sidecar.
5. `qa.py` - the per-building automated QA metric (section 4).
6. `frame_plan.py` + `linux/docker/districts_capture.py` - where to look from (worked out from the catalogue) and
   the in-game capture: day/night, the move from classic, third and first person, fixed regress-cam poses, each
   kit on/off via `[devtools] district_kit_show` in the same frame.
7. `preview_blender.py`, `sheet.py` - offline before/after renders (the map blocks round a building with the HD
   tiles mapped as the renderer maps them) and archetype / elevation review sheets.

Renderer: `src/district_kit.{h,cpp}` loads `gta2dx9_districts\<style>.kit` at level load (after the camera
collision mesh, after every other batch) as `TileBatch::streetOnly` + `TileBatch::kit` batches; kit materials
take tile slots after the riverbed's (`KitTileIndex`). The kit fades in with the street extras ramp over the
move from classic (and out on the way back) through the existing see-through pass of the fading street lights
(`Renderer::SetKitPresentation`), so nothing pops; it is never drawn in the classic view.

## 2. The facade kit (one generic generator)

Everything is placed in a wall's own frame (h along the wall from outside, y up, d out) from the tile art's
boxes mapped through the renderer's own face orientation tables (`gmap.FaceFrame`, a port of `FaceUvs`), so
geometry lands exactly on what the texture shows. The guiding rule that made it read as GTA2 architecture and
not stuck-on boxes: **extrude the art, do not paint over it**.

- **Skin**: the wall stood 0.065 block proud of the box face, same tile, same UVs, with a hole at every opening:
  the box face behind becomes the recessed glass/door. Corners: N/S walls own convex corners (extend), concave
  corners shorten, so skins meet without overlap. Caps close runs where a face is missing.
- **Reveals**: the hole's sides, textured with the wall 2 texels outside the opening (masonry returns).
- **Sills / lintels / plinth / bottom ledges**: the art region (the painted sill, the band over a window, the
  base course) extruded; a kit stone only where that region is a dark line (it would read as a black bar).
- **Cornice**: stepped courses (profile per archetype) textured with the top band of the wall art; brackets on
  tenements and brownstones; a parapet with coping where the archetype has one; at the top of the solid wall
  under a map railing, not on the railing.
- **Awnings** (striped canvas, colour by district hash) over street-level shop windows; **door / dock canopies**
  over loading doors (industrial); **fire escapes** on the longest street-facing run with windows on 3+ levels
  (grating decks at the window sills, rails, posts, brackets, alternating stair flights, drop ladder);
  **cladding ribs** in the wall's own texture on plain industrial walls; **roof plant** (vents, units,
  chimney on factories) on interior roof cells by cell hash.
- Limits: overhang <= 0.15 block (per axis), nothing below the street, see-through tiles (lattices, railings)
  untouched, openings under 7x9 texels ignored.

## 3. Verification (POC)

Plain renderer on Tokyo (GPU 0), private stage `stage_districts`, capture runs `dk_*`: see the contact sheets
(`districts/` in the session scratchpad) and the report. Classic view: kit batches are street-only and skipped in
the classic draw; vreg `spawn_classic` run on the stage (result in the report). Remix: `/gta2/dist` on
gta2-rtx6000, `runremix_dist.sh` + `keys_districts_remix.sh` (queued for a quiet window when the weather agent's
runs hold the GPU).

## 4. Running it on every building

Measured on this branch (all three levels, every non-structure building, current kit):
see the table in the report and `districts_work/<lvl>_all.log`. Kit generation is ~10-25 s per level and QA
~75-80 s per level on one CPU, so the whole city regenerates in a few minutes; the cost is in the budget:

- Whole-level kits are 1.2-2.2 M triangles (85-170 MB as written). Loading that at level load is not an option in
  a 32-bit process with ~1.5 GB largest free block. Plan: **stream per 16x16-cell chunk** (the kit file gets a
  chunk index; chunks within ~48 blocks of the eye are resident, as props are), **LOD** (beyond ~20 blocks only
  cornices and the skin without holes; beyond 48 nothing: the box face is the far LOD), **merge** skin quads
  along runs, **16-bit indices** per chunk and a packed vertex (half-float position offsets, 8-bit normal):
  target <= 250k resident triangles and <= 12 MB of buffers. The POC loads the three buildings whole (15k, 5k and
  4k triangles; +0.9 MB vertices +0.2 MB indices for Downtown's).
- Per-building **automated QA** (`qa.py`), human review only on flagged buildings:
  - footprint: largest per-axis distance outside the footprint (> 0.16 flags), anything below the street;
  - z-fighting: kit faces lying in a map wall plane facing the same way, and coplanar overlapping kit triangles
    of different materials;
  - texture alignment: every recess's contrast against a 3-texel ring in the tile art (a recess on art with no
    opening contrast is a false window: > 25 % of a building's recesses flags it);
  - pop: geometry above the roof line (reported; all kit geometry fades with the move, the flagged ones get their
    move frames looked at);
  - budget: > 12k triangles for one building.
  The in-game half of QA reuses `frame_plan.py` + `districts_capture.py` on every flagged building and a sample
  of the passed ones (5 %), with an image diff on/off per pose as the "did anything change, where" signal.
- Expected review load: the first full run flags roughly half the buildings (see report); most flags are three
  rule classes (corner overlaps at stepped roofs, plinths on sub-street faces, low-contrast grounding), each a
  generator fix rather than a per-building edit. After those, the target is < 10 % flagged.

## 5. Per-district style tables (keyed by the district map)

The district map gives every cell a key (`gang:yakuzagang`, `local_nav:w03`, ...); `overrides/<lvl>.json` maps
keys to a style row. One table, one row per style:

| style | kit palette (trim / cornice / awnings) | props (DrawProps rules) | atmosphere (fog colour, density) | grade (post LUT) | Remix (rtx.conf overrides) |
|---|---|---|---|---|---|
| downtown_corporate | concrete / metal, no awnings | planters, bollards, flagpoles | clear, blue-grey | cool, high contrast | glossier glass (roughness -0.1) |
| downtown_neon | stone / dark metal, red awnings | vending, neon signs, bins | haze, magenta tint at night | warm-magenta night | emissive x1.5 on sign tiles |
| residential_suburb | brownstone / brown stone, green awnings | trees x2, mailboxes, hydrants | clean, warm | warm, soft | softer sun, more GI bounce |
| residential_redneck | wood / tin, no awnings | pickup wrecks, fences, flags | dusty yellow | desaturated warm | dust volumetrics |
| industrial_russian | concrete / brick, door canopies | containers, pipes, barrels | smog grey-green | green-grey, crushed blacks | stronger fog, volumetric lamps |
| industrial_docks | galvanised metal / concrete | cranes, bollards, crates | sea haze | cold teal | wet roughness on ground |

The renderer reads the row for the eye's cell (one lookup into the baked grid) and eases between rows over a few
blocks; props rules read the row of the cell they place in. Kit palettes are baked into the `.kit` (materials).

## 6. Effort, risks, dependencies

- Effort (one engineer-agent): chunked streaming + LOD + packed format 3-4 days; generator fixes for the top QA
  flag classes 2 days; archetype classifier v2 (Qwen3-VL on per-building facade montages, the rules as features)
  2 days; style-table plumbing (fog/grade/props/Remix per district) 3-4 days; full in-game QA pass with review of
  flagged buildings 2-3 days; Remix materials for the kit (PBR in `gta2hd`) 1-2 days. About 3 weeks.
- Risks: the 32-bit address space (streaming is a must, not an option); the grounding's false windows
  (ornaments, vents, signs) become false recesses (the contrast metric catches most); buildings whose walls the map
  stores on neighbouring blocks or as flats (skipped today: no kit, no harm); the Remix facade POM on the same
  tiles doubles the recess depth under Remix (decide: drop POM on skinned tiles, or keep the skin shallower under
  Remix); the transition: the kit is faded with the street extras ramp, the sun shadows it casts in the plain
  renderer's shadow pass are not faded yet.
- Dependencies: the address-space work (another agent), the weather agent's Remix layer (rtx.conf rows per
  district would go through the same `remix_config` path), the props owner for per-district prop rules.

## 7. Open decisions

1. Commit the generated `.kit` meshes (derived from the map layout, no art) or regenerate at build/stage time.
2. Kit under Remix: keep or drop the facade POM on tiles the skin recesses.
3. Archetype labels: accept the rule classifier (cheap, explainable, ~40 % "block") or pay for a Qwen3-VL pass.
4. Fade policy for kit shadows in the plain renderer.
