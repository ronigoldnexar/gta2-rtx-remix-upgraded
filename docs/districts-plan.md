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

### Next (approved, not started): (3)

QA flags under 10 % through the five rule classes, per-district style tables (prop mix, awning and kit palette,
fog/grade, Remix overrides) keyed by the district map, three districts side by side; rebase onto camera-modes when
the lighting branch lands.
