# City sweep: every district from the street, automatically

The sweep visits a district's whole map in the street-level views by developer
warp and scores every frame for defects without a person looking, so that
"perfect everywhere" can be checked rather than assumed. Per district:
`docs/city-sweep-<district>.md` (ranked table) and `out/sweep_<district>_sheet.png`
(the worst 20 frames). District files: `wil` is Downtown, `bil` is the
Industrial map and `ste` the Residential one (the file names are swapped
relative to the in-game order; see the tour-fixes commit).

## How it works

1. **Plan** (`tools/sweep_plan.py game/data gamerun --grid 26`): a grid of road
   or pavement cells every 26 blocks snapped to the nearest walkable cell, the
   centroid of every map zone of 30+ cells not already covered, and six cells of
   each map-hole class from `tools/map_holes.py`, so the mesh fixes are looked at
   from the street. Written to `gamerun/sweep_plan_<district>.json`
   (Downtown 183 points, Industrial 188, Residential 145).
2. **Runner** (`gamerun/sweep.py`, `gamerun/sweep_run.sh <district> <i/n>`,
   `gamerun/sweep_queue.sh`): the game on the GPU image with the magenta clear
   (`GTA2DX9_CLEAR_MAGENTA=1`, new in `src/renderer.cpp`) and the sky off, so
   anything the renderer leaves undrawn is magenta; the devtools scene warp on
   `F11` (`SCENE_KEY`; F10 is eaten every other press by Wine's menu-key
   handling) with `GTA2DX9_SCENE_NO_CAR=1` (new in `dll/src/view_modes.cpp`: the
   warp moves the player alone to the point instead of to the nearest parked
   car, which the tour-fixes change made it do); at each point four headings in
   third person and two in first person, a frame each, about 19 s per point;
   deaths and crashes are recorded and the point retried in a later chunk
   (`gamerun/sweep_retry_queue.sh`, `sweep_plan_<district>_retry.json`).
3. **Detectors** (`tools/sweep_detect.py out <district> <md> <sheet>`): per frame
   `hole` = magenta below the horizon band (40 % of the height in the chase
   view, 52 % at eye level; above it magenta is the sky), `black` = near-black
   frame, `flat` = share of 32 px cells with a colour spread under 2/255 (an
   untextured face or the camera inside something; advisory, smooth tiles
   trigger it too); per point the renderer-log slice is counted for `FAULT`,
   `waiting for the player` and hitch lines. One row per cell, worst frame first.

## Result (7 Nov 2026, build 350a3d8 + the two switches above)

| district | planned | landed after retries | frames scored | holes | black | warp crashes | warp deaths (first pass) |
|---|---|---|---|---|---|---|---|
| Downtown (wil) | 183 | 177 of 178 reached (5 unreachable: no floor within six blocks) | 1 062 | 0 | 0 | 1 run | 2 |
| Industrial (bil) | 188 | 188 of 188 | 1 128 | 0 | 0 | 0 | 1 |
| Residential (ste) | 145 | 145 of 145 | 870 | 0 | 0 | 2 runs | 4 |

First-pass landing was 135/113/61 (the F10 key loss, the car redirect and the
warp deaths); the retries with the F11 key and the no-car warp landed every
remaining point in Industrial and Residential and all but one in Downtown.

Across roughly 3 000 scored frames from about 500 viewpoints no frame showed a
hole in the world or a black frame; the two map-hole classes fixed earlier
(`src/world_mesh.cpp`) stay closed everywhere the sweep looked, including the
hole-class seed cells. The `flat` rows are the game's own smooth tiles (for
example Industrial tile 352, a plain concrete pavement with a colour spread of
9/255 at 512 px) or the first-person eye against a wall right after a warp; no
untextured face was found by the sweep (the one known case, Residential
(216,22), is in the tour-fixes stream).

## Result, 8 Nov 2026 (SWEEP-DISTRICTS: Industrial and Residential with the verified swap)

QA3's 8 Nov tables for Industrial and Residential were measured on Downtown's map: the harness never
swapped the level (`data/` was bound read-only by `game_mounts.sh` and the copy failed silently). The
swap now verifies itself (`gamerun/swap_level.sh` compares the copied map, style and script and aborts
the run otherwise; `to_level.sh` checks again in play). Every run below logs
`level 1 is now <district> (map, style, script verified)`, and the frames are the right district (the
Industrial arrival message, Residential's own streets). The Downtown table of 8 Nov stands.

| district | planned | landed | frames scored | holes | black | flat (advisory) | log rows | warps (runs) | warp deaths |
|---|---|---|---|---|---|---|---|---|---|
| Industrial (bil) | 188 | 188 | 1 128 | 0 | 1 | 2 | 0 | 260 (13) | 4 |
| Residential (ste) | 145 | 145 | 870 | 0 | 0 | 24 | 0 | 155 (6) | 1 |

Stage: the gated stage from `a2d66a0`, as a private hard-link copy. Commands (2 slots):
`STAGE=<copy> TAG=sd_ gamerun/sweep_queue.sh bil:0/6 ... bil:5/6` and `ste:0/5 ... ste:4/5` in
parallel, then retries `TAG=sdrK_ SWEEP_PLAN=/work/sweep_plan_<d>_sdretryK.json gamerun/sweep_run.sh <d> i/n`
(the retry plans hold the points that had not landed before a death; cells where someone died go last),
then `tools/sweep_detect.py ../out/sweep_sd/<d> <d> docs/city-sweep-<d>.md ../out/sweep_<d>_sd_sheet.png`.
`out/sweep_sd/<d>/` holds a link folder per run, and for a run with a death a `sweep.jsonl` cut before the
death point (the reason is below).

What the frames show:
- **No hole and no untextured face anywhere** in either district: 0 magenta below the horizon in 1 998 frames.
- **Residential (11,33), chase camera inside geometry**: in all four third-person headings the frame is one
  flat tan field (`flat` 0.90), while first person at the same spot shows a sand yard under steel girders.
  The chase camera ends up inside the girder structure or the ground there. Owner: camera
  (`WorldView::PanelDistance` knows map panels and lamp posts, not this structure).
- **Industrial (250,13), first person at the east map edge**: from a height the eye looks out past the map
  into black (`black` 0.79; the city is drawn below). An edge view, not a hole; with the magenta clear,
  undrawn space would be magenta, so something past the edge draws black.
- The other `flat` rows are the game's smooth tiles or a steep chase view of pavement (props and walls
  textured; checked by eye for Residential's top two; Industrial's two `flat` rows, 0.41 and 0.30, not looked at).
- No `FAULT` and no `waiting for the player` in any scored point.

Found on the way:
- **A death in a swapped district loses the player** (QA3 open 1, now reproduced on the real Industrial
  and Residential maps): five warp deaths in 415 warps, each on landing (state 8, killed within 11 s;
  the three cells that killed in Industrial landed alive on a later try, so the cause is not the cell).
  After the death the renderer's player locator follows another ped: the reported position jumps,
  warps are refused (`player not located on foot`) or land somewhere else, and the third-person frames
  show no player. Once (Industrial retry 1, ten minutes after its death) gta2.exe faulted at
  `gta2.exe+0x3ED37 reading 00000064`, the same address as QA3's. Points from a death onwards are not
  scored and were re-run. Owner: the respawn handling of the swapped level (harness) or the locator
  (`view_modes.cpp`); not seen in Downtown, where deaths respawn cleanly.
- Under heavy host load (1-minute load 78, the governor's hold on) the game window took 5 minutes to
  appear and four warps were logged by the renderer (`moved the player alone ... (written)`) but read
  back at the old position by `sweep.py`. Those points landed on a later retry.
- `sweep_run.sh`: game GPU 3-7 by chunk (`GPU=` overrides; GPU 0 is Remix's on the 8x L4 host), and a
  per-run keys wrapper that ends the chunk when `sweep.py` is done (it sometimes prints `done` and does
  not exit, which held the slot to the time cap) or once two points in the chunk had all four warp
  attempts unseen (the state after a death).
- A workspace-wide migration rsync running at the same time put the old `gamerun/sweep_run.sh` back mid-sweep,
  so four chunks ran on the old script (GPU 0, no early end; their frames are valid). The
  tracked copy is `linux/docker/sweep_run.sh`; keep the two the same.

## Street fill, apron and haze band (FIX-WORLD, 9 Nov 2026)

Defects 9b `pm2-fp-bil-white-void-below-horizon-between-rooftops`, 9c
`pm3-ste-third-white-flat-polygon-between-buildings` and 9d
`pm3-horizon-hard-straight-cut-geometry-ends-before-sky`. Code: `src/world_mesh.cpp`
(`AddStreetFill`, `AddApron`), `src/renderer.cpp` (street-only batches), `src/sky.cpp` (haze band),
`src/water.cpp` (the apron is not the map's water for the shore map).

**What the holes were.** The flat pale colour in both reports is one value, (180,196,218): the fully
fogged sky colour, seen where a ray leaves the city. GTA2's map has no faces a top-down camera never
needed: a column's implicit base and a ground block have no sides. At the Industrial start (44,100)
the player stands one level below the field and pavement to the north ((44,99) level 2, no riser), so
from the roof edge the eye looked under that lid, through the implicit ground and down to the seal.
At the Residential spawn the air block (116,121) level 2 carries a wall face that points into its solid
neighbour (GTA2 draws faces from both sides; this renderer culls the back), so from the courtyard
that wall was not there.

**Fill (street views only).** The world is treated as cells that are solid (implicit base, a lidded
block, a covered ground block that `AddHiddenSurfaces` gave a lid) or air; every side between a
grounded solid cell and an air cell that has no face of its own, or only a face pointing the wrong way,
gets a riser quad, tiled with the wall that cell's column shows on that side higher up, else a wall of
the column or a neighbour at that level or below, else the ground's lid tile (never a facade's windows
from higher up). Columns with nothing at level 0 get a ground plane there (away from water). The
quads go into batches flagged `TileBatch::streetOnly`, appended after every other batch, and the
renderer skips them unless a street view shows (`SetStreetView`). Counts: Industrial 6801 risers and
483 ground cells, Residential 6930 and 201; about +14k triangles (+3 %) and ~340 draw calls.
`GTA2DX9_STREET_FILL=0` builds the mesh without it.

**Apron (9d).** Past each map edge the city continues as flat ground for 640 blocks, at the level and in
the tile the border shows most: water at sea level (tile 608, height 1) in all three districts, drawn by
the water pass (one tile repeat per block, WRAP addressing; the shore map sampled with a white border
so a walled edge is not foam to the horizon). From the Industrial start the west edge is 44 blocks
away and the fog is a quarter in there; the city used to stop in a straight line over the sky's skirt.

**Haze band (9d).** The fogged distance ends in exactly the fog colour, but the dome over the horizon
started at the horizon colour plus the sun's glow: 37 levels brighter in one pixel row toward the sun
(column profile 217 -> 180 at the cut). The lowest ~5 degrees of the dome now rise out of the fog
colour (`kHazeBand`, two more dome rings), and the skirt below the horizon is the fog colour. Same frame
after: 187 -> 180 over 15 rows, no step.

**Whole-map measure (`tools/world_raycast.cpp`).** The city sweep cannot see this class: with the sky
off the fog is off and a hole lands on the black seal, which `sweep_detect.py` does not flag (only
magenta). The ray caster builds the same mesh natively and casts rays below the horizon from an eye
0.45 and 1.6 blocks above every walkable lid on a 4-cell grid (eye in open air only); a leak is a ray
that ends on the seal or nothing while crossing level 0 inside the map. Culled back faces are
transparent to it, as on screen.

| district | rays | leaking, before | leaking, after |
|---|---|---|---|
| Industrial (bil) | 2 734 524 | 1 152 (360 eyes) | 92 (37 eyes) |
| Residential (ste) | 2 866 032 | 1 556 (489 eyes) | 104 (45 eyes) |
| Downtown (wil) | 2 831 868 | 1 625 (481 eyes) | 89 (45 eyes) |

The rest (about 7 %) is mostly at ramps (the sides of slope blocks over slope-63 fill, left alone:
treating slope 63 as solid made it worse) and cells whose eye is within a block of a wall.

**Classic view.** The non-street batches, their vertex and index ranges and the vertices and indices
themselves hash the same as HEAD's mesh in all three districts (bil 582f2059eb45cc13, ste
784ad2dfa842bbf7, wil bfb1c7a1cd502f30), and the renderer draws nothing else while the classic view is
settled. Classic frames of HEAD and this build at the same moment after loading differ only where
cars, peds, the neon and the talking portrait move: 3207 pixels against 3091 between two runs of
HEAD itself.

**Frames** (fixed regression-camera poses, clock held at 12:30; `linux/docker/keys_fixworld.sh`):
`out/fw1_base_{bil,ste}` (HEAD c69c620) and `out/fw1_fill4_{bil,ste}` (this build), `out/fw2_base_bil`
(HEAD again, the noise floor). Frame time, world phase in the street views: 1.42 -> 1.59 ms.

## Found and fixed on the way

- `SWAP_LEVEL=wil` in the run scripts deleted the Downtown mission folder
  (`rm -rf data/wil` before copying it onto itself): guarded in
  `gamerun/run_game*.sh` and the `linux/docker` mirrors.
- The devtools scene key `F10` is seen only every other press under Wine
  (the menu-key handling): `tour_lib.warp` takes `SCENE_KEY`, the sweep uses F11.
- The tour-fixes rewrite of the scene warp walks the player to the nearest
  parked road car within 40 blocks instead of the asked point (85 of the
  Industrial first-pass points landed up to 40 blocks away):
  `GTA2DX9_SCENE_NO_CAR=1` keeps the point.

## Filed, not fixed here

- **Warp crash**: three runs (`out/sweep_wil_0`, `out/sweep_ste_1`,
  `out/sweep_ste_2`) died with `FAULT: code C0000005 at gta2.exe+0x35FDF reading
  00000080` within two seconds of a scene warp on the 12:03 build, each time
  right after the brought car landed on the player's own cell ("WASTED!" then
  the Wine crash dialog: `out/sweep_ste_sheet.png` rows 3-4 of the first
  scoring; the log slice before the fault in `out/sweep_wil_0/gta2dx9.log`
  lines 1985-2000 shows the player object vanishing and the camera jumping).
  Six of 517 first-pass warps killed the player. The no-car warp used for the
  retries never crashed (five chunks, 0 faults, 0 deaths in Downtown and
  Residential). Owner: the devtools warp in `view_modes.cpp`; a car must never
  be placed on the player's cell.
- `waiting for the player` for a second or two after some warps in Residential
  (20 points in the first pass; all of them landed on retry): the locator
  re-scans when the game recycles the ped at the new spot; cosmetic in a
  developer warp, not seen in play.
- Chase camera at road level for a moment after the classic cut
  (`out/sweep_wil_0/t_grid_143_13_ta.png`): the 1.2 s settle in the sweep is
  short for the 1.4 s transition; a sweep artefact.

Rerun (8 Nov, QA3; results in `docs/qa-report.md`; its Industrial and Residential tables were Downtown and are
replaced by the SWEEP-DISTRICTS result above): `STAGE=<private stage> TAG=q3_ gamerun/sweep_queue.sh wil:0/5 ... ste:3/4` (two queues
in parallel), retries with `SWEEP_PLAN=/work/<plan of the unlanded points>.json`, then
`tools/sweep_detect.py <folder of links to the sweep_<d>_q3* runs> <district> ...`. `sweep_run.sh` now
defaults to `GTA2_DIRECT_KEYS=1` (nav_map=0) and takes `STAGE=`.

Rerun (7 Nov): `gamerun/sweep_queue.sh wil:0/4 wil:1/4 ... ste:2/3`, then
`tools/sweep_detect.py out <district> docs/city-sweep-<district>.md out/sweep_<district>_sheet.png`.
