# QA report: edge cases in the three views (5 Nov 2026, evening build)

Everything below was run by script under Wine 9 in the `gta2-remixbox` container on this
machine (software OpenGL, llvmpipe, 32 CPU threads per run, several runs in parallel on a
loaded box). The scenario scripts are in `gamerun/qa_*.py` (`qa_lib.py` has the helpers:
view switching that reads the view back from the renderer's log, labelled shots, log counts)
and `gamerun/qa_run.sh <name> <seconds>` runs one. Each run leaves `out/qa_<name>/` with
`qa_*.png` shots, `keys.log` (the script's own log with a `CHECK` line: faults, locator
losses, hitches) and `gta2dx9.log`. `out/qa_sheet.png` is the summary; per scenario sheets
are `out/qa_<name>_sheet.png`.

Counts quoted below: `fault` = `FAULT` lines (crashes caught by the SEH stand-in),
`waiting` = `view: waiting for the player` (locator gave up), `lost` = `the remembered
player slot no longer holds a pedestrian; looking again` (locator re-scan), `hitch` = frames
the renderer flagged as slow.

## Scenarios

| # | scenario | run | result | evidence |
|---|---|---|---|---|
| a | walk into a wall and keep pushing (third, first), slide along it, 360 on the spot, back off | `qa_wall` (3 runs) | no faults, locator never lost, views correct. **Fixed**: the chase camera went into the wall when the player stood against one (the 1.4-block minimum pull-in was tuned for a car) | `qa_wall_sheet.png`, `qa_wall2_sheet.png` |
| b | back and forth ten times with V mid-move (third → first → classic) | `qa_backforth` | no faults, every switch landed in the view the renderer reports, no snapping seen in the frames | `qa_backforth_sheet.png` |
| g | V every 0.3 s for 10 s while walking (31 presses) | `qa_backforth` | no faults; ended in first person as the count predicts; walking and the next switches fine | same sheet, `qa_rapidv_*` |
| c | punching in a crowd for 150 s, third then first then third | `qa_fight` | no faults, views correct throughout. The police never reacted (the punches did not land on anyone with the script's aim), so the arrest path is **untested** | `qa_fight_sheet.png` |
| d | take a car (devtools F10 + Return), full speed into traffic and the kerb in the chase view, same from the driver's seat, out of the car in first person, look round, back in, drive in all three views | `qa_crash`, `qa_perf_*`, `qa_drv_*` (6 runs) | no faults; `lost` = 20 per run, all at the moment of getting in (the game recycles the ped's physics object; the locator re-finds him as the driver within a frame, expected); re-entry worked (state 3 → 10); the hood stays in frame from the driver's seat, no roof clipping; the own body is not drawn on foot in first person | `qa_crash_sheet.png` |
| e | die and continue: stand and cross the carriageway for 170 s, three variants (F10 placement, map-route placement, with and without punching passing cars) | `qa_death` (4 runs) | **not achieved**: GTA2's traffic braked for him every time; no death or arrest was provoked by script, so the respawn path is **untested** | `qa_death_sheet.png`, `qa_death2_sheet.png` |
| f | 8 minutes of everything on: in and out of cars, all views, driving and walking | `qa_long` | no faults, 27 frame summaries, car-model textures 184 MB (324 textures) in the managed pool after 8 minutes, no growth-related crash under LAA. Frame time: see "performance" | `out/qa_long/` |

## Fixed in this pass

1. **Chase camera against a wall on foot** (`dll/src/view_modes.cpp`, third-person
   collision): the minimum camera pull-in was 1.4 blocks (a car's length) for both cases, so
   with the player's back to a wall the camera was held inside the wall (whole frame = wall
   texture, player invisible: `out/qa_wall_sheet.png`, `qa_wall_third_turn4`). Now 0.5 blocks
   on foot (the figure is 0.46 blocks tall) and, when a wall still holds it that close, the
   camera rises so the view is down over his head (`qa_wall2_sheet.png`, `third_turn2`).
2. **First-person diagnostics**: once a second in first person the log has
   `view: fp eye x,y,z player y floor lid under the eye`, for the open issue below.

## Open

### Ground void in first person (intermittent)

A region of ground near the player is not drawn in first person: with the sky on it shows
the sky's pale under-colour (RGB 178,195,217), with the sky off it is black. Seen in
`out/final_demo` (t=99..145, standing on the carriageway), `out/void_nosky`, `out/void_nocars`,
`out/qa_fwd`, the first `qa_wall` run, `qa_wall043nohd`, `qa_wall043nohd2`, `qa_death`
(`qa_death_02_first`). Not seen in: `qa_eye078`, `qa_eye060`, `qa_eye043nomodels`,
`qa_noped`, `qa_noprop`, `qa_wall043`, the second and third `qa_wall` runs, `qa_road_*`.

What was ruled out (each by a run with that one thing changed): HD tiles (void with the HD
folder absent and with it capped at 64 px), the sky and fog (void with the sky off), the 3D
cars (void with `car_models3d=0`), the eye height alone (same script, same 0.43 eye: void in
one run, none in two others), the own body hidden/shown. The eye log in the clean rerun shows
the eye 0.43 above the floor lid at the plaza (`eye 2.43, floor 2.00, lid under the eye 2.00`),
so when it is clean the camera is where it should be; a void run with that log line has not
been captured yet. The edge of the void is straight and world-aligned, and the far ground
beyond it and the ground within about a block of the camera are drawn.

Recommended next step for the owner of the world pass: when it happens again (the eye line is
now in the log), compare the eye line with the lid heights, and dump the world batches drawn
that frame; the shape suggests a block of lids skipped or seen from below rather than a
texture problem.

### Performance while driving in the street views (software renderer)

On this machine the street views at 1280x720 hold the 30 fps cap on foot (first and third
person, Downtown plaza and carriageway: `present` 0.0 ms, `wait` 29-30 ms in
`qa_perf_base`, `qa_road_base`), but **while driving** the present stage rises to
130-200 ms per frame (about 5-7 fps): `qa_perf_cars1`, `qa_perf_cars0`, `qa_drv_base`,
`qa_drv_nosky`, `qa_drv_nofog`, `qa_long`. The CPU side stays small (game 2-4 ms, world
0.8 ms, sprites 1-2 ms), so the time is the software rasteriser's. It is the same with the
3D car models off, with the sky off and with the fog pushed out, so none of those is the cause.
The recording `deliverables/gta2_linux_driving.mp4` (build of 18:56) drove at the cap
(`present` 0.2 ms), so the cost came in with the later changes; the bisect runs on the
19:44 commit (`qa_drv_a89`: CPU-bound in the sprite stage instead, 150 ms, a different problem
of that older code) and the 20:09 commit (`qa_drv_67e`, result in `out/qa_drv_67e/gta2dx9.log`
if it finished after this report) narrow it. On a real GPU these numbers do not apply; the
user's own machine should be measured before concluding anything about real-time play.

### Also noticed

- The `view: player` locator logs `lost` 20 times per car entry; harmless but noisy.
- `qa_death`: F10 placed the player at a parked car's door and he could not walk away from it
  until Return was pressed (`qa_death` runs 2 and 3); the map-route placement works.
- Provoking the police by punching needs the hits to land; the script's blind punching did
  not raise a wanted level in 150 s.
- Run-to-run navigation is nondeterministic (traffic), so a scenario sometimes ends at a wall;
  the sheets note which frames are at a wall.

## Not covered

Arrest and respawn (not provoked), long runs beyond 8 minutes, mouse look (the scripts use
keys), the Industrial and Residential districts (all runs are Downtown), RTX Remix (blocked
on this machine, see `linux/README.md`).
