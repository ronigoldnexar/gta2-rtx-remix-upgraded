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

Rerun (8 Nov, QA3; results in `docs/qa-report.md` and the three district files, which now hold the
8 Nov tables): `STAGE=<private stage> TAG=q3_ gamerun/sweep_queue.sh wil:0/5 ... ste:3/4` (two queues
in parallel), retries with `SWEEP_PLAN=/work/<plan of the unlanded points>.json`, then
`tools/sweep_detect.py <folder of links to the sweep_<d>_q3* runs> <district> ...`. `sweep_run.sh` now
defaults to `GTA2_DIRECT_KEYS=1` (nav_map=0) and takes `STAGE=`.

Rerun (7 Nov): `gamerun/sweep_queue.sh wil:0/4 wil:1/4 ... ste:2/3`, then
`tools/sweep_detect.py out <district> docs/city-sweep-<district>.md out/sweep_<district>_sheet.png`.
