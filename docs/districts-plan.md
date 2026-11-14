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

Plain renderer on Tokyo (GPU 0), private stage `stage_districts`, capture runs `dk_wil5`, `dk_ste5`, `dk_bil5`
(day and night x street / graze / across / roof fixed poses, third and first person, the move in and out; every
pair the same frame with `district_kit_show` 1/0), 0 FAULT in every run. Frame time (`dk_perf1`: a 66k-triangle kit
of the 46 buildings round the Downtown spawn, the same pose held 20 s on / 20 s off twice): world draw 1.8-2.1 ms
with the kit, 1.8-2.0 ms without, frame wait unchanged: no measurable cost at this size. Memory: the kit adds its
vertex and index arrays (66k triangles: +4.1 MB vertices, +0.8 MB indices, and the same again in the vertex
buffer; the three POC kits: 1.1, 0.4 and 0.3 MB); the largest free block stayed 2047.9 MB at level load.
Known capture gap: third/first-person frames face the street, not the building (the turn-to-face helper); the
fixed poses carry the comparison. Classic view: kit batches are street-only and skipped in
the classic draw; vreg (`tools/vreg/vreg.sh stage`, run `dk_vreg1`) captured with a kit of the 46 buildings round
the spawn (66k triangles) loaded: `spawn_classic` PASS, 0 changed tiles. The 3D shots all FAIL against the current
goldens (rev b89b95a), uniformly, including shots far from any kit (brightness 0.33 vs 0.21 at the bank): the
goldens predate HEAD's lighting changes; a same-HEAD baseline is needed for a kit-only 3D diff. Remix: staged, not run. `/gta2/dist/stage` on gta2-rtx6000 holds this build and
the kit, `/gta2/dist/runremix_dist.sh` (the shipped `runremix_dlss.sh` pointed at it) and
`/gta2/gamerun/keys_districts_remix.sh` take the same frames:
`DK_POINTS="$(cat <frame_plan json>)" KEYS=/work/keys_districts_remix.sh /gta2/dist/runremix_dist.sh dist_wil 900`
(reboot first, only when no weather run is going). The 6000 was busy with the weather agent's back-to-back runs,
then this session's gcloud credentials expired (IAP needs an interactive re-login).

## 4. Running it on every building

Measured on this branch (every non-structure building of each level, the POC kit, one CPU, `--all`):

| Level | Buildings in catalogue | Kitted | Triangles | Kit file | Kit build | QA run | Flagged by QA |
|---|---|---|---|---|---|---|---|
| Downtown | 1 216 | 1 027 | 2.06 M | 153 MB | 20 s | 142 s | 452 / 878 (51 %) |
| Residential | 1 340 | 1 057 | 1.19 M | 88 MB | 12 s | 81 s | 316 / 780 (41 %) |
| Industrial | 1 807 | 1 469 | 1.16 M | 86 MB | 12 s | 76 s | 405 / 1 126 (36 %) |

Flag classes (a building can have several): low-contrast recesses 701 (the grounding called something a window
that the art does not show as an opening: blinds, louvres, panels), coplanar overlaps 495 (a kit element at the
same depth as another: generator rule fixes, not per-building edits), plinths below the street level 114 (faces
whose foot is lower than the building's street), kit faces in a wall plane 39, over 12k triangles 22. So the whole
city regenerates in about 6 minutes; the cost is in the runtime budget:

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
- Review load: the first full run flags 36-51 % of the buildings, but in five rule classes; each is a generator or
  threshold fix (skip recesses below the contrast floor instead of flagging them, distinct depths for every
  proud element, plinth from the face's own foot) rather than a per-building edit. Two rounds of that took the
  Industrial flags from 59 % to 36 % in this POC (corner overhang clamp, trims kept on their own face, rib and
  frieze depths). Target after the remaining rules: < 10 % flagged, i.e. ~300 buildings for a human to look at
  on their QA sheets (elevation + in-game on/off frames), about a day of review.

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

## 8. Round 2 (13 Nov, after review): bolder kit, decisions applied

Decisions from the review and what was done:

1. **Kits regenerated at stage time, never committed**: `make stage DISTRICTS_DATA=<game/data> DISTRICTS_PY=<python with
   numpy+Pillow> [DISTRICTS_MODE=all]` runs `tools/districts/build_kits.sh` (catalogue, analysis with the committed
   one-time Qwen archetypes, pick, kit, materials) into `stage/gta2dx9_districts`. Deterministic: two independent
   builds of the three levels' kits and materials are byte-identical. `assets/districts/` is gone from git.
2. **No Remix facade parallax on kit tiles**: `remix_nopom.py hashes` lists the Remix hash of every tile a kit skins
   (108 for the three POC streets), `remix_nopom.py patch` writes a layer copy (hard links, mod.usda / mod_wet.usda
   unlinked and rewritten) with `displace_in = 0` and no height texture on those prims (93 in the shipped layer).
   Caveat: the tile hash is shared, so an un-kitted building using the same tile also loses its parallax until the
   kit covers the whole city.
3. **Qwen3-VL for the generic class only** (`qwen_archetype.py`): each "block" building's longest street wall as an
   elevation, Qwen3-VL-8B-Instruct (Apache-2.0, host cache) picks one archetype + confidence; answers >= 0.6 replace
   "block" in analyze.py. Runtime on one L4 (shared GPU 0): 37 s model load, 3.2-3.3 s a building at batch 4-8;
   ~1 250 generic buildings over the three levels is ~70 min, once per map. Downtown (complete): 495 asked in 27.5 min, see the commit for the confident count; first 444:
   confident (255 brick tenement, 83 brownstone, 44 warehouse, 30 civic, 27 shopfront row, 5 office tower). The
   result is committed per level as `tools/districts/qwen/<lvl>.json` (ids and labels, no art).
4. **Kit shadows fade with the kit**: the kit's triangles are a third set in the plain renderer's shadow pass that
   samples an 8x8 ordered-dither cell of the alpha atlas against 1 - the kit's fade, so the shadow fills in over the
   move instead of appearing in one frame (`PostFx::SetKitShadow`).
5. **Bolder kit** (`kit.py` v2; depth ladder in its header; nothing beyond 0.25 block): window reveals 0.15 (was
   0.065) with sill ledges and hood moulds with drips scaled to the window; piers standing out where the art paints
   vertical bands (`analyze.py pier_spans`) or between window bays; string courses at floor lines where the art has a
   band; a heavy cornice (frieze, dentil course, brackets, a crown at 0.25 and a cap, all in the wall's own top-band
   art); a rusticated three-course plinth. Residential: stoops with cheek walls and rails, bay windows (the
   window's own art carried out) and balconies on hashed window columns, fire escapes on side and rear runs first,
   a timber water tower. Industrial: sawtooth (factory) or monitor (warehouse) roofs over the largest all-interior
   roof rectangle, loading docks (platform, rubber bumpers, canopy on tie rods), downpipes and a duct (never across a
   window), stacks, vents. Shopfronts: the sign band stood out and a deep awning whose colour is picked from the art.
6. **Openings**: cut only above a confidence from the opening's contrast against the art round it; edges snapped to
   the strongest luminance step within 3 texels; tops and bottoms of one kind unified within a tile (one window
   grid); wide, short or lighter-than-wall "windows" (panels, plaques, vents) are not cut. This removed the jagged
   dark cut-outs of round 1.
7. **The POC covers a street**: the picked building and every building whose footprint comes within 6 cells
   (Downtown 19 buildings / 106k triangles, Residential 9 / 44k, Industrial 9 / 32k). The pick now also scores what
   the kit can build (street doors, upper windows): Residential #1250 (brownstone row under the elevated rail),
   Industrial #1136 (brick factory); Downtown #490 unchanged.
8. **Capture**: a standing ped's logged facing comes from his sprite and can be half a turn off, so the turn-to-face
   helper now walks from the warp point toward the wall (he ends facing it); third and first person face the
   building.

Whole-city numbers with the v2 kit (one CPU): Downtown 3.24 M triangles / 241 MB / 29 s kit / 228 s QA, 41 %
flagged; Residential 2.39 M / 178 MB / 22 s / 169 s, 39 %; Industrial 1.61 M / 119 MB / 14 s / 96 s, 35 %. The
streaming + LOD plan of section 4 is now a must: a POC street is 30-106k triangles.

Remix: the RTX PRO 6000 is shared with the weather agent, whose back-to-back runs reboot the VM; two of my runs there
were killed by those reboots (the second after it had the Downtown day third, first and street frames, kept). The
remaining Remix captures ran on Tokyo's L4 through `gamerun/remix_l4.sh` (the documented L4 path-tracing route) with
the no-parallax layer copy.

## 9. Round 3 (13 Nov): review fixes, Qwen complete, streaming pilot (Zarelli)

Fixes from the round-2 review:

1. **Roof parts only on real roofs + a QA hard check.** The floating Industrial stack stood on a sloped roof block
   (slope types 19/20) of a column that starts at level 4 over nothing. Stacks, vents, water towers and roof teeth
   now need `roof_host`: the cell's top block at the base height minus one, flat (slope 0), lidded, with a block
   under it. kit.py writes every roof part's host cell to `<kit>.anchors.json`; qa.py flags any part whose cell is not
   such a roof ("N roof parts not on a roof"). Verified: 0 in the POC streets and the whole of Industrial; the round-2
   stack position injected into the anchors is flagged.
2. **Awnings by archetype.** Industrial archetypes get no fabric: a plain steel hood over a shop-window-like opening
   (a third have none), loading canopies and docks as before. Fabric only on shop windows of commercial and
   residential archetypes, varied per shop by hash: a fifth have none; the rest striped or solid canvas (6 new solid
   canvas materials), sloped (two drops) or a flat box canopy; the colour from a three-colour palette per district,
   the entry nearest the art's own colour.
3. **Sills**: half the round-2 depth on small windows (proud 0.15 x window width, 0.012-0.045), thinner, with a
   bevelled top (the front edge lower), so they read as stone, not shelves.
4. **Qwen results committed** (`tools/districts/qwen/{wil,ste,bil}.json`): 1 053 generic buildings asked, 940 answered
   with confidence >= 0.6, in 34 min of model time on one L4 (3.3 s a building). The answers lean heavily to
   "brick_tenement" (597 of 940): a label bias to look at before trusting the class for anything beyond the kit's
   masonry rules.

Remaining QA class (not fixed, flagged): sub-centimetre coplanar sides of drips, cheek walls and the industrial
coping against piers and ribs.

### Streaming pilot: Zarelli (Downtown local-nav m31, 121 kitted buildings)

- `kit.py --district local_nav:m31` (LOD0) and `--coarse` (LOD1: skin without openings, two-course cornice, roof
  silhouettes) -> `pack_kit.py` -> `wil.kit2`: 91 chunk entries (16 x 16 cells, two levels), LOD0 301k triangles,
  LOD1 28k, 15.5 MB with 14-byte packed vertices (int16 position, int8 normal, half uv) against 32-byte floats.
  `make stage DISTRICTS_STREAM=wil:local_nav:m31` builds it; the renderer prefers `<style>.kit2` to `<style>.kit`.
- Runtime (`src/kit_stream.*`): only the chunk table is in memory; a chunk's bytes are read from the file when it
  comes into range and unpacked into a fixed set of 2 MB vertex pages made at level load (first fit; no index
  buffers). LOD0 within 24 blocks of a chunk's box, LOD1 within 56, nothing beyond, 2 blocks of hysteresis, at most
  3 chunks unpacked per 0.2 s, each new chunk or level fading in over 0.4 s while the one it replaces fades out.
- What the memory work found (GTA2DX9_VA_WATCH, MEM-FRAG's watcher):
  - a VB + IB per chunk, made and freed while driving, fragmented the address space (largest free 553 MB, dkd_on2);
  - holding the 15 MB packed file as one block cut the 2 GB free block to 1333 MB at level load (dkd_on5);
  - one 15 MB pool was placed in the middle of it (2047 -> 1543 MB at load, dkd_on6);
  - the kit-off baseline over the same drive also falls to 604 MB (dkd_off3): something outside the kit splits the
    block while driving across the city (a 0.75 MB private block at d1120000 in the watch log).
  - with the table-only reader and 2 MB pages the kit's own load-time block is gone; the 15.8 MB load-time blocks the
    watcher still shows appear in the kit-off baseline too (dkd_off4: three of them), so they are not the kit's.
- **Measured** (plain renderer, Tokyo L4, the same two-lap Zarelli route in a car, chase view, 12:30):

  | run | kit | drive | world draw avg / worst | busy avg / worst window | resident (mean / max) | largest free block (min) | commit max |
  |---|---|---|---|---|---|---|---|
  | dkd_on8 | streamed | 6.6 min | 2.21 / 16.8 ms | 16.6 / 24.4 ms | 25 chunks, 92k tris / 35, 138k tris, 13.0 MB of pages | 792 MB | 1231 MB |
  | dkd_off4 | off | 6.6 min | 1.79 / 23.2 ms | 14.4 / 21.3 ms | - | 1421 MB | 1260 MB |
  | dkd_off3 | off | 5.7 min | 2.38 / 34.9 ms | 21.8 / 33.0 ms | - | 604 MB | 1205 MB |
  | dkd_on5 / on6 | streamed (earlier builds) | 7.6 / 3.3 min | 2.83 / 2.30 ms | 22.5 / 18.8 ms | max 139k / 134k tris | 789 / 792 MB | 1299 / 1219 MB |

  The kit adds about 0.4 ms of world draw at ~90k resident triangles; frame time is inside the run-to-run spread
  (busy 14.4-21.8 ms without it). The largest free block stays well above the agreed 320 MB gate in every kit run
  (min 789-792 MB); the kit-off baseline itself ranges 604-1421 MB over the same route, so the earlier 1.2 GB target
  is not met by the game without the kit either. 0 FAULT in every run.
- **Videos** (H.264 1280x720 15 fps, faststart, ffprobe-checked; on Tokyo, not in git, game art):
  `deliverables/districts/zarelli_drive_plain_kit_on.mp4` (437 s), `..._plain_kit_off.mp4` (450 s),
  `..._remix_L4_kit_on.mp4` (901 s, RTX Remix on the L4 through `remix_l4.sh`, the no-parallax layer copy).
- Streaming leaves the plain renderer's sun shadows out for the streamed kit (the shadow pass reads the static world
  copy); the static per-street kit keeps its dithered shadows. Folding the resident chunks into the shadow pass is the
  next step if the streamed path is kept.

### Next (approved): (3) — done in round 4, section 10.

## 10. Round 4 (13 Nov): gaps closed, Qwen re-asked, style tables, three districts side by side

Rebased onto camera-modes with LIGHTING-V1 (gate C) in it.

### Gaps closed
- **A real bug found on the way:** the renderer had 16 kit material slots (`kKitMaterials`) but the kit uses 22, so
  every group in materials 16+ (the solid canvas awnings `canvas_*` since round 3, and the new shutter) was dropped
  silently, in the static kit and the stream alike. Raised to 32.
- **Roller doors** on industrial loading bays: a corrugated `shutter` (new procedural material) in the opening,
  closed or part way up (deterministic per opening), a bottom rail, a galvanised housing over the head; the dock
  canopy moves above it.
- **Wall-mounted parts on their host:** `qa.py` now checks every wall part (stoop, bay, balcony, shopfront, dock,
  fire escape, hood, downpipe, duct) against the map face it is fixed to: the face is there, flat, and the cell in
  front of it is open at that level. 8 811 wall anchors and 719 roof anchors checked over the three whole
  cities: 0 off host. An injected wrong-side anchor is flagged.
- **Sun shadows for the streamed chunks** (plain renderer): the resident chunks' solid groups are shadow casters,
  culled per cascade by their chunk box, drawn from the stream's own vertex pages, dithered (8 x 8 Bayer texture)
  against the kit's fade times each chunk's own crossfade, so they fade with the move like the static kit's.
  Zarelli drive, same GPU load (Qwen on the GPU): busy 20.6 ms kit on (stream + its shadows, `dkd_r4sh`) vs 19.3 ms
  kit off (`dkd_r4off`), world pass 2.67 vs 2.51 ms; largest free block min 1 101 MB (gate 320), 0 FAULT.
- **Stream fix:** a chunk whose group did not fit the pool stayed resident with that group missing (whole walls of
  the Residential district had no kit). Groups are now split at 4 096 triangles (they fit the holes of a used page)
  and a chunk comes in whole or not at all (retried next plan).

### QA flag rate (generator fixes, the whole city of each level)
| level | buildings | round 3 | round 4 |
|---|---|---|---|
| wil | 874 | 41 % | 7 % |
| ste | 769 | 39 % | 1 % |
| bil | 1 111 | 36 % | 8 % |

What fixed it: openings are cut only where the art sets them off from the wall (the same 3-texel ring contrast the
QA measures; the QA keeps it as a regression guard and counts only openings the kit would cut); proud parts end
their caps a little past their ends in proportion to depth (no two parts of different depth end in one plane), and
the parts that shared a depth by accident moved (balcony 0.235 vs fire escape 0.245, stoop step 0.178 vs plinth
0.185, sills at most 0.19 vs piers 0.195, bay sill 0.232 vs bay 0.24, N/S vs E/W level trims); no parapet inside a
map railing; "below street" measures from the building's lowest wall (a building on a slope has walls under its
street level). QA fix: a facet is put in a plane only if all its vertices are in it (tapered stacks were false
hits). What remains: small coplanar caps (sills vs hood drips) and 15 buildings over 20 000 triangles.

### Qwen archetypes, v2 (label bias)
Spot check of 30 random v1 answers by eye (`scratchpad/districts/r4_qwen_spotcheck_30.jpg`): 597/940 "brick_tenement"
was a bias (office towers, walls, girders, hedges labelled tenement). v2 (`qwen_archetype.py`): the label order
randomised per question, a "not a building" choice, the two longest walls side by side, two questions per building,
an answer kept only when both agree. Run: 1 053 generic buildings, 2 questions each, 6.6-6.9 s a building on one L4
(about 1 h 50 min in all; bil resumed after an OOM when game runs shared the GPU). Both runs agreed on 690 (66 %);
"brick_tenement" fell from 63 % to 33 % of the answers. By eye on 30 random agreed answers
(`r4_qwen_v2_spotcheck_30.jpg`) only 14 were right: the windowless elevations (rock walls, girders, bridge decks)
still got building labels. So a label is now accepted only where the art has a window or a loading door
(`analyze.py`); on the same 30 that keeps 19, 13 of them right (68 %), and rejects 11, 10 of them wrong. In use:
573 Qwen labels (wil 271, ste 171, bil 131). Qwen stays a tie-breaker for the rules' generic class, not a
classifier to trust alone.

### Style tables (`tools/districts/styles.json`, picked per district in `overrides/<lvl>.json`)
| row | silhouette and kit | awnings | props (x the street rules) | grade (fog / ambient) | Remix |
|---|---|---|---|---|---|
| downtown_core (wil Zarelli) | generic buildings recast as towers and shop rows; heavy cornices, 0.14 parapets, plant rooms, rooftop units, antennas; no fire escapes or water towers | every shop window and front door, 3/4 striped, red/green/blue/yellow | furniture 2.2, meters 2.5, roof plant 1.6, trees 0.4 | cool | exposure +0.1, cool balance |
| residential_brownstone (ste Scientists turf) | generic recast as brownstones and tenements; fire escapes on the street front (2+ levels), water towers on 90 %, heavy cornices, stoops, bays | 60 %, solid maroon/green/cream | trees 3, furniture 0.8, meters 0.3 | warm | warm balance |
| industrial_docks (bil Tedium, and the three docks districts) | generic recast as factories (3+ levels) and warehouses: coping, 0.12 parapets, 3 stacks a building, sawtooth/monitor roofs, vents, docks with roller doors, downpipes and ducts | none (steel hoods) | containers 3, roof plant 2, furniture 0.3, meters 0 | grey-green | exposure -0.15 |

Runtime: `dstyle.py` bakes `<lvl>.dstyle` at stage time (rows + the district grid, 2 KB); `dll/src/district_style.*`
reads it, eases the grade over ~2 s as the camera crosses districts (fog, horizon and ambient, weighted by the
street blend: the classic view is untouched), scales the street prop rules (a multiplier of 1 gives exactly the
old props) and pushes the row's Remix options when the street view enters a district (the default row's values
back on leaving, or in the classic view). Logged: `districts: style table ...`, `districts: camera in <row>`.


### Three districts side by side (sheets in `scratchpad/districts/r4_*`)
Same camera in every district: the chase camera's height (2.2 blocks over the street, 3 back, looking 10 ahead at
1.0 up), on the straight road with the most tall district frontage (`id_plan.py`), both ways along it, day and dusk
(18:00), kit on and off. vreg spawn_classic PASS (0 tiles) on this stage. Plain (Tokyo) and RTX Remix (Tokyo L4, a package copy with no parallax on the kit's 243
recessed tiles), 0 FAULT in all six runs; under Remix each district's options were pushed on entry and reset on
leaving (`2 set, 0 refused`).

By eye: **Industrial docks** reads at once (brick stacks over every roof line, copings, downpipes, roller doors);
**Residential brownstone** reads (front fire escapes, heavy cornices, bays, deep reveals, water towers on the
skyline); **Downtown core** is the weakest: its frontages are the art's own towers and signs, its roof plant is
above the chase camera's view and few of its doors and shop windows pass the contrast gate, so its awnings are
rare. The grade is deliberately subtle. Pixels changed by the kit at this camera: 9-16 % (Industrial, Downtown),
11-20 % (Residential).

Next: Downtown needs a street-level lever that does not depend on cut openings (sign bands and canopies along the
whole ground floor of a front, street-level piers), then the district rows for the other gang and local districts.

## 11. Round 5 (14 Nov): Downtown identity, QA remainder, the whole city streamed

### Downtown identity
- **Storefronts** (`storefronts`, the downtown rows and the Mall): along every street-facing ground floor of a
  commercial building, whether or not the analysis cut openings there: a dark fascia sign band over the ground floor
  (0.2 high, at the top of the ground floor), an illuminated sign box on three cells in four (letters in warm or cool,
  per building), a solid canvas canopy with a valance under it (colour from the row's palette, per building; striped
  canvas read as barrier tape from the street), and neon tubes up some cell edges (the row's `neon` share: 0.8 in
  Yakuza turf and Ukita, 0.05 in the Zaibatsu business district). Per-opening awnings are off where the band runs.
- **Tower silhouettes** (`crowns`, 4+ levels): a setback storey over the roof's largest inner rectangle, in the tower's
  own upper wall art, a stone crown step and a dark cap on it, and a 2.2-block mast; **flagpoles** (`flagpoles`) on the
  front roof edge with a canvas flag. All on real flat roof (QA anchors); roof units are kept off the setback.
- **Lit at dusk:** sign faces and neon carry an emissive flag and one of 32 switch-on buckets. The DLL fills the
  buckets' night share each frame from lighting-v1's staggered street-light clock (`DaylightGateFactorKeyed`, the
  same `lights_on_hhmm` and `lights_stagger_minutes` as lamps, windows and cars), and the renderer adds each group's
  `_lit` material, unlit and unfogged, at that share times the chunk's and the kit's fade. Dark while the day/night
  cycle is off (the fixed noon sun) and by day. Plain renderer and Remix draw the same additive pass; under Remix the
  signs show bright but do not emit light into the scene (that would need an emissive entry for the lit textures in
  the gta2hd layer).

### QA remainder (whole city, final code)
| level | round 4 | round 5 | lean rebuilds |
|---|---|---|---|
| wil | 7 % | 5 % | 10 |
| ste | 1 % | 1 % | 3 |
| bil | 8 % | 2 % | 1 |

Over budget: 0 (was 12). A building over 20 000 triangles is now rebuilt lean (no dentils, two brackets a face, half
the ribs and balconies, no hood moulds, sills without end caps). Overlaps: 69 of bil's 84 were chimney stacks
capped twice (the stack's own cap under its iron ring); the setback storey met the plant rooms on towers. What is
left (65 buildings) are small coplanar caps (a sill end against a trim).

### The whole city streamed
Every building of every level streams (`DISTRICTS_STREAM="wil:all ste:all bil:all"`), each district with its row:
the named districts have rows of their own (Yakuza turf and Ukita neon, the Zaibatsu business district corporate,
the University campus, Rednecks, the suburbs, the prison, the Mall, the three Industrial gangs), every other district
the level's mixed row (`default_style` in `overrides/<lvl>.json`); a row can inherit another (`base`). Streams:
wil 3.26 M / 0.40 M triangles (LOD0 / LOD1, 172 MB), ste 2.40 M / 0.26 M (125 MB), bil 1.26 M / 0.22 M (70 MB). The
vertex pool went to 16 pages (32 MB) and LOD0 to 20 blocks: a dense Downtown chunk is 17 000 triangles at LOD0, and
with 8 pages the pool filled with 10 chunks and refused the rest.

### City drives (one leg into each styled district, about 14 min a level, 12:30, kit on unless said)
| run | busy avg (max window) | world pass | resident stream (mean / max triangles) | largest free block min | FAULT |
|---|---|---|---|---|---|
| wil plain, kit on | 20.6 ms (30.8) | 3.22 ms | 214k / 338k | 680 MB | 0 |
| wil plain, kit off | 16.4 ms (33.5) | 1.72 ms | – | 1 234 MB | 0 |
| ste plain, kit on | 24.3 ms (41.9) | 3.13 ms | 220k / 299k | 629 MB | 0 |
| ste plain, kit off | 17.8 ms (27.6) | 1.67 ms | – | 577 MB | 0 |
| bil plain, kit on | 21.4 ms (41.6) | 3.22 ms | 108k / 188k | 721 MB | 0 |
| bil plain, kit off | 14.6 ms (35.0) | 1.89 ms | – | 1 052 MB | 0 |
| wil Remix L4, kit on | 119 ms (139) | 51.5 ms | 251k / 284k | 2 048 MB* | 0 |
| wil Remix L4, kit off | 73 ms (95) | 1.1 ms | – | 2 048 MB* | 0 |
| ste Remix L4, kit on | 161 ms (189) | 70.2 ms | 200k / 218k | 2 048 MB* | 0 |
| bil Remix L4, kit on | 150 ms (165) | 77.6 ms | 122k / 139k | 2 048 MB* | 0 |

\* under Remix the game process keeps its address space free (the bridge holds the GPU side). All nine legs driven
in every run; the drives re-board after losing the car (1-6 times a plain run). The memory gate (320 MB) holds
everywhere with at least 300 MB to spare. Plain cost of the whole city: +4.2 / +6.5 / +6.8 ms a frame (1.4 ms of it
in the world pass, the rest the shadow pass and the post passes over more geometry), from 15-18 ms to 21-24 ms,
under the 33 ms of the 30 fps cap. **Under Remix on the L4 the kit costs ~+46 ms a frame** (the world pass from 1 to
51-78 ms): every streamed group is its own draw call into the bridge, and chunk streaming makes new geometry for
Remix to build every few seconds. That is the release blocker for Remix (below).

Videos (`deliverables/districts/`, H.264 1280x720 15 fps, faststart, ffprobe-checked, 75 s each, five pieces from
legs into differently styled districts, labelled): `r5_highlight_{wil,ste,bil}_plain.mp4`,
`r5_highlight_{wil,ste,bil}_remixL4.mp4`. The full drives are `out/dkc_<lvl>/game.mp4` (plain) and
`out/dkcr_<lvl>/game.mp4` (Remix).

## 12. Shipping proposal

**Ship behind `[districts] facade_kit` (already in `package/gta2dx9.ini`), default OFF for this release; plan
default-on for the next one once the Remix cost is fixed.** (Superseded by section 14: round 6 removed the blockers
and the kit is a ship candidate, default on, pending the 5090 check.)

Why not default-on now:
- **Remix:** +46 ms a frame on the L4 is not shippable as a default; the 6000 will be faster, but most of the cost is
  draw calls into the bridge (CPU), which scales less with the GPU. To measure before deciding: one drive on the
  6000 under `/gta2/remix.lock`, kit on and off.
- **Plain:** +4 to +7 ms a frame is affordable at 30 fps, but it is 30-45 % more frame time for a look that is still
  uneven (Downtown reads less than Industrial and Residential; 65 buildings with small z-fighting caps; Qwen labels
  are right about two times in three).
- **Size:** the streams are 367 MB on disk for the three levels (the stage-time build takes ~7 min and needs Python
  with numpy and Pillow in the build).

What is safe already: the classic view is pixel-identical (vreg `spawn_classic` 0, every round), nothing pops (the
kit fades with the move), 0 FAULT in every run of rounds 1-5, the address-space gate holds with room to spare,
the build is deterministic (byte-identical across two builds), and the switch is read at level load, so a player
who turns it on and dislikes it turns it off with no other effect.

To make it default-on (next release, about 2-3 weeks):
1. **Remix draw cost:** merge a chunk's groups by material into one draw per material per chunk (today a chunk is
   up to ~40 draws after the 4 096-triangle split and the sign buckets), keep chunk geometry stable under Remix
   (a larger LOD0 radius and no crossfade, so the bridge sees few new meshes), and give the lit sign textures an
   emissive entry in the gta2hd layer. Target: under +5 ms on the 6000.
2. **Plain cost:** let the streamed chunks into the shadow pass only within the near cascade, and drop dentil and
   bracket detail from LOD0 beyond 12 blocks (an LOD0.5). Target: under +3 ms.
3. **Size:** shared vertices with 16-bit indices per group and a deduplicated window detail (the same sill and
   hood geometry repeats thousands of times) should take the streams from 367 MB to well under 150 MB.
4. **Look:** a full-city visual QA pass per district with the per-building QA flags as the work list; finish the
   Downtown ground floors; rows for the remaining unnamed districts; Qwen kept only as a tie-breaker.
5. **Build:** ship the generated `gta2dx9_districts` folder in the release package (built once by CI) rather than
   asking the player's install to run Python.

Default-off for the release means: package the folder (or build it in CI), keep `facade_kit=0`, document the switch
in the README as an experimental option, and note the Remix cost next to it.

## 13. Round 6 (14 Nov): the Remix cost, plain cost, disk (next release; districts-poc only)

### Remix cost: measured on the RTX PRO 6000 (under /gta2/remix.lock, one run at a time, no reboot)
Same wil city route as round 5 (nine legs, 12:30), stage = the shared stage + my DLL, ini and kit; layer = the
shipped gta2hd with the kit's three emissive sign materials added.

| run (6000) | frame (busy) avg | world pass | resident stream | FAULT |
|---|---|---|---|---|
| kit off (`r6_wil_off`) | 49.2 ms | 0.36 ms | – | 0 |
| kit on, merged draws + own buffers (`r6_wil_on`) | 48.6 ms | 13.6 ms | 194k tris mean | 0 |
| kit on, + draws sorted and state cached (`r6b_wil_on`) | **50.2 ms (+1.0)** | 7.3 ms | 244k tris mean | 0 |

**+1.0 ms with the kit on the 6000 (target ≤ +10 ms).** The 6000 frame is bound by Remix's GPU work (present), so
the kit's CPU cost in the world pass is mostly hidden behind it. What changed:
- **Draws merged by material:** a chunk's groups of one material are laid out together and drawn as one range
  (the emissive sign buckets only matter to the night pass, which keeps their sub-ranges).
- **Stable geometry under Remix:** each resident chunk gets a buffer of its own, written once and never locked again
  (a write into a shared page made the bridge re-hash every chunk in that page), no crossfade (blended chunks go
  through Remix's translucent path), hysteresis 6 blocks (fewer new meshes).
- **Draws sorted across chunks** by texture, then state, then buffer, with every state set only on change: about
  1.3 device calls a draw instead of ~7 (each call is a bridge message).
- **Emissive signs:** the three `_lit` kit textures are emissive materials in the gta2hd layer
  (`remix_nopom.py emissive`). At dusk on the 6000 the sign lettering reads lit
  (`scratchpad/districts/r6_remix6000_neon_dusk.jpg`); the light they throw on the street is faint.

On the Tokyo L4 the frame is still much slower with the kit (145 ms vs 73 ms kit off; the world pass went 51 → 36
ms): the L4 is GPU-starved under Remix and the kit's ~250k extra triangles cost it path-tracing time. The 6000 is
the reference for the release; the L4 stays a look-check rig.

### Plain cost
| run (Tokyo, plain, wil route) | busy avg | world pass | largest free block min |
|---|---|---|---|
| round 5 kit on / off | 20.6 / 16.4 ms (+4.2) | 3.22 / 1.72 ms | 680 / 1 234 MB |
| round 6 kit on / off (`dkc6c_wil` / `dkc6co_wil`) | 18.6 / 17.7 ms (**+1.0**) | 2.84 / 2.27 ms | 994 / 646 MB |

- **Near-cascade-only shadows** for the streamed chunks (the far cascades skip them).
- **A lighter level beyond 13 blocks, without more data:** fine detail (dentils, brackets, sills, hood mouldings,
  balcony, stoop and fire-escape rails, dock bumpers) is flagged in the kit (flag 32) and drawn only when the
  chunk is within 13 blocks of the eye; it never casts shadows. (A separate "lean" middle level would have added
  ~70 % of LOD0 to the files; `pack_kit.py --mid` and the lod-2 code path are kept but unused.)
- The vertex pool went to 24 pages (48 MB): at 32 MB the city drive refused chunks (`dkc6_wil`). With 48 MB: 0
  refused, and the largest free block stayed ≥ 994 MB (gate 320).

### Disk
| | round 5 | round 6 |
|---|---|---|
| wil.kit2 | 172 MB | 45.8 MB |
| ste.kit2 | 125 MB | 33.0 MB |
| bil.kit2 | 70 MB | 17.0 MB |
| **total** | **367 MB** | **95.8 MB** |

Every chunk entry is raw-deflated (`pack_kit.py`, GDK2 version 3; 3.7-3.9x) and inflated when it streams in by a
small decoder written for this (`src/inflate.cpp`, checked byte-for-byte against Python's zlib on chunk data,
random data and text). Deflate's LZ matches take most of the repetition that instancing the repeated details was
meant to remove (the same sill, hood and dentil geometry thousands of times), so shared vertices and instancing
were not needed for the 150 MB target; they remain possible if the GPU-side memory needs to shrink too.

## 14. Ship candidate (14 Nov)

Rebased onto camera-modes 4b7bd2ff (lighting-v1 with the effects-ini restage change, CITYMAP-1). `facade_kit=1` is the
default in `package/gta2dx9.ini` (one line to turn back), pending the 5090 test agent's kit on/off drive.

### The kit in the normal staging path
The kit is made from the game's maps and HD tiles, so it is never committed (AGENTS.md: generated assets that embed
the game's art ship as release archives); it is built from the commit's own tools, deterministically:
- `tools/districts/build_kits.sh ... ship`: every building of the three levels as streams, the style tables and the
  materials, nothing else; it fails (and so does the caller) with no HD tiles, a missing file or a level stream under
  4 MB. Two builds of the same commit, maps and tiles are byte-identical (checked: sha256 of all 34 files). ~3 min.
- `make districts` builds it into `stage/gta2dx9_districts` (DISTRICTS_DATA, DISTRICTS_HD, DISTRICTS_PY override the
  defaults ../game/data, assets/textures_hd, ../vreg/venv/bin/python); `make stage` keeps the kit the stage has.
- `linux/docker/restage.sh` builds it into the candidate from the candidate worktree and refuses the candidate if it
  does not build; the folder swaps in with the models and HD tiles. `linux/docker/stage_check.py` refuses a stage whose
  ini has `facade_kit=1` without the three streams and style tables.
- Every game launcher copies or mounts `gta2dx9_districts` beside gta2.exe like the HD tiles (game_mounts.sh,
  run_game.sh, run_game_gpu.sh, run_game_remix_gpu.sh, play_game.sh), and `linux/install.sh` installs it.
- `tools/pack_release.py districts` writes `gta2dx9_districts.zip` (store-only: the streams are deflated) from the
  stage; it is in the default set of archives.

### Full-city visual QA (plain)
- **Flag list (final kit):** 16 / 5 / 17 buildings (wil / ste / bil; 2 / 1 / 2 %), all small coplanar caps; corner
  drips now hang 4 mm under their hoods, E/W top caps and level trims sit a hair off the N/S ones and the sills.
  8 809 wall and 1 640 roof anchors on their hosts, 0 off.
- **50-building random sample** (unflagged, 2+ levels, seeded; in-game street and across views, kit on and off;
  `scratchpad/districts/ship_sample50_*`). What it found and what was fixed:
  - Big pale slabs across two views (wil 259, 309): I first took them for setback storeys and limited setbacks to towers
    (5+ levels over the street, at most 3 x 3 cells, centred; kept, a sensible limit), but the recapture
    (`ship_qa_fixes_before_after.jpg`) is unchanged: the test camera stands on the roof edge, inside the cornice and
    parapet. The test poses bypass the camera collision; in play the wall clearance below keeps the eye out.
  - Neon tube supports were open pairs of side faces that read as black slabs close up: now closed thin boxes.
  - **Street cameras inside the kit:** the camera collision keeps 0.12-0.24 block from the walls it knows, and the kit
    stands up to 0.25 out of them, so a camera close to a wall sat inside sills, cornices and canopies. While the kit
    is loaded the collision keeps a further 0.13 from walls (`eyecol::SetWallClearance`).
  - Not kit defects: a few "buildings" in the catalogue are crates, fences or girder bridges (wil 13, bil 140, 818,
    1066); the kit leaves them as they are (lattice tiles are never dressed; crates get no openings). Some test poses
    stand in odd places (frame_plan's poses target a building's middle, not a framed shot).
- vreg spawn_classic 0 tiles, 0 FAULT on the rebased stage (`dk_vreg7`, and `dk_vreg8` after the fixes).
- After the fixes, wil city drive (`dkc8_wil`): 0 FAULT, busy 16.1 ms, largest free block min 657 MB.
- City drives on the rebased stage (`dkc7_*`): 0 FAULT, all nine legs, largest free block min 996 / 617 / 576 MB
  (wil / ste / bil; gate 320).


### 5090 ship check: one FAULT (run 1 of 3), resolved
`C0000005 at gta2dx9.dll+0x10AF33 reading 2993D7BA`, after a level change from Industrial to Downtown. With the map of
that exact build (c5bb93a3, md5 819336b0, `/tmp/rc-dist-wt/dll/build/gta2dx9.map`, image base 0x712C0000):
- +0x10AF33 is in `density.o`, function `gta2dx9::DensityUpdate(bool, bool, float, float)` at +0x503, the inlined
  `PlayerStars()` -> `game::PedWantedStars(ped)`: `movzwl 0x20a(%edi)` with edi = `ViewPlayer().ped` (0x2993D5B0 +
  0x20A = the faulting address). The other stack words: `WorldView::MatchGameViewToFrame` (world_view.o, the caller of
  `DensityUpdate`), `Overlay::RevertToWindowSize` (overlay.o) and `gbh_BeginScene` (dllmain.o).
- **Not kit code** (none of kit_stream.o, district_style.o, post_fx.o, renderer.o, inflate.o): the view player is
  refreshed only by the street camera's locate step and was never reset when a level loaded, so the density hook (and
  city_ai's) could read the previous level's freed ped for the frames between the level change and the next locate.
  `game::PlausiblePointer` checks the range, not that the page is still mapped. The kit's extra level-load allocations
  most likely moved the old pool's pages from "freed but mapped" (a harmless stale read) to unmapped (a fault) - which
  is why the stage without the kit never showed it - but the stale read is there in both.
- **Fix** (`world_view.cpp`, LoadMap): the view player is reset when a new map loads and when the game goes back to the
  menu, so nothing reads a ped pointer from another level until the locate step sets a fresh one.

### Level-change check
`linux/docker/districts_levels.py` (+ `keys_districts_levels*.sh`, `tools/districts/run/levels_run.sh`): Industrial ->
Downtown -> Residential -> Downtown in one game process (frontend PLAYER QUIT, the next district swapped over level 1,
START PLAY), each stop third person + walk + first person + classic; every load verified against the game log (the
kit's stream line). The game's frontend changes after a saved status appears (RESUME SAVED STATUS on top), and after 7
changes the scripted keys picked REPLAY PREVIOUS AREA on swapped files, which ends in GTA2's own script error dialog
and a clean exit (exit 167, no FAULT): so each process does 2 laps (6 changes) and three processes give 6 laps.

| level-change check (3 processes x 2 laps each) | level loads verified | FAULT |
|---|---|---|
| plain, fixed DLL (`dkl3_plain_*`) | 21 / 21 (kit streams bil bil wil ste wil bil wil ste per process) | 0 |
| plain, the 5090's faulting DLL (`dkl3_old_*`) | 21 / 21 | 0 (the stale read is intermittent: not reproduced) |
| RTX Remix, L4, fixed DLL (`dkl3_remix_*`) | 21 / 21 | 0 |
