# QA report, second pass (6 Nov 2026, build 72642c6 + the two camera changes below)

Run by script on the NVIDIA L4 through VirtualGL (image `gta2-gpugl`, `gamerun/run_game_gpu.sh`),
4 CPUs per container, two containers at a time on an 8-CPU host shared with other streams'
runs. Runner: `gamerun/qa_run.sh <name> <seconds> [keys]` (now GPU, slot-locked; `QA_DISTRICT`,
`QA_SED`, `QA_ENV`). Scenarios: `gamerun/qa_*.py` on `qa_lib.py`. Each run leaves
`out/qa_<name>/` with labelled `qa_*.png`, `keys.log` (`CHECK` line) and `gta2dx9.log`.
Summary sheet: `out/qa2_sheet.png`; detail sheets `out/qa2_*_sheet.png`.

Counts: `fault` = `FAULT` lines, `waiting` = locator gave up, `lost` = locator re-scan
(20 per car entry is the expected recycle), `hitch` = frames the renderer flagged as slow
(capped at 1600 lines per run).

## Scenarios

| # | scenario | run | result |
|---|---|---|---|
| a | wall pushing, slide, 360 turn, back off, third and first | `qa_wall` | fault 0, waiting 0, lost 0; chase camera pulls in and rises at the wall (pass-one fix holds), first person shows the wall texture at a hand's distance, no camera inside geometry |
| b | back and forth with V mid-move; 30 V presses in 10 s | `qa_backforth` | fault 0, waiting 0, lost 0; every switch landed in the renderer's reported view |
| c | 150 s brawl, third then first then third, 248 punches | `qa_fight` | fault 0; the punch clip plays on the player, NPCs react; police never came (fists do not raise the wanted level) |
| d | take a car, crash into traffic and the kerb in chase and seat views, exit, look round, re-enter, drive in all views | `qa_crash` | fault 0, waiting 0, 99 driving lines; a uniformed police officer walked past after the crash (typed peds) |
| f | 9-12 laps of walk (third, first) + F10 car + drive (third, first, classic) + exit, 540 s per district | `qa_soak_wil`, `qa_soak_bil`, `qa_soak_ste` | fault 0, waiting 0 in all three; HD tiles 818/892/842 loaded, 0 failed; managed texture pool **344.8 MB flat from the first summary to the last** (pre-warm loads everything at level start; no growth); frame summaries at the end: wil game 4.8 ms avg / wait 27 (at the cap), bil game 11.2 / sprites 7.6 / wait 12.5, ste game 9.0 / sprites 5.8 / wait 16.5 |
| g | rapid V (31 presses) | in `qa_backforth` | as pass one, clean |
| h | first person inside a tall vehicle | `qa_tall`, `qa_tallcam` | Truck Cab (63) from the seat: road ahead visible, only a mirror corner in frame; sedan (13): hood in frame; bus (8) and taxi (56) in chase after the fix below |
| i | classic view unchanged | `qa_classic` vs `qa_classic_off` (sky, car models, water, window glow off) | spawn frames: mean abs difference 0.29/255, 0.4 % of pixels differ (moving pedestrians only); the walked frame differs only because the walk endpoint differs between runs. Classic draws no models, props, sky or glow (gated by the ground-view flag) |
| j | mission start by script | `qa_mission` (`mission_play.py wil wil_tra`) | fault 0; the tutorial phone is answered, `view: mission` fields read, the mission car named; the runner then left the car and walked for 5 min toward a far target (runner logic, not the renderer) |
| k | ini keys | `grep GetPrivateProfile` vs `package/gta2dx9.ini` | all 48 documented keys are parsed; 46 parsed keys are undocumented (upstream `car_*`, `skids`, `save`, `voice`, and our `remix.di_*`, `renderer.hud_world_follow`, `renderer.backend`) |
| e | death and arrest | `qa_death2`, `qa_death2b`, `qa_death2c` | **not achieved**: the weapon pickup east of the spawn (map 166.5,139.5) is behind a wall of the plaza (the walker stops at x=163.8); warping onto it with the devtools scene key dropped the player under the map (state 8, see Open 3); fists never raise the wanted level and traffic brakes for the player. Respawn in the new views remains untested |

## Fixed in this pass (uncommitted)

1. **Chase camera inside a lamp post.** The kerb-railing fix (pass one) covered flat map panels only; a rule-placed lamp post could still end up a few centimetres from the camera and draw a black bar down the frame (`out/qa_death2/qa_d2_05_loop016_third.png`). `WorldView::PanelDistance` (`dll/src/world_view.cpp`) now also reports the distance to the nearest map lamp (post radius 0.06) within 1.5 blocks and 3.5 blocks below the lamp, so the existing outward march clears it. Verified only indirectly: none of the 60 later third-person frames show a post bar (scan in the transcript); no frame of the exact earlier situation was reproduced.
2. **Chase camera behind a tall vehicle.** Behind a Truck Cab / bus the body's back filled the frame (`out/qa_soak_wil/qa_soak_wil_09_third_drive.png`, `qa_soak_wil_08_third_drive.png`). `ViewCameraSolver::Solve` (`dll/src/view_modes.cpp`) scales the chase distance and height by the car body's roof height from `CarBodiesCabin` (sedan roof ≈ 0.35 blocks: unchanged; a 0.9-block cab: ×1.7, capped ×1.8). Verified: `out/qa2_tallcam_sheet.png`, bus (model 8) and taxi (56) in chase, road and traffic visible.
3. `gamerun/qa_run.sh` moved to the GPU image and the slot helper; new scenarios `qa_death2.py`, `qa_soak.py`, `qa_tall.py`, `qa_tallcam.py`, `qa_classic.py` (+ `keys_qa_*.sh`, mirrored in `linux/docker/`).

## Open

1. **First-person exit into a prop.** Leaving the Truck Cab beside the pavement put the eye inside a rule-placed trash can (`out/qa_crash/qa_crash_09_first_out.png`). Props placed within ~0.6 block of a car door should be skipped, or the first-person eye nudged off a prop (DrawProps / car exit; props owner).
2. **Death/arrest unprovoked.** Needs a reachable weapon: either the pickup route (the cell is reachable from the terrace side, not from the plaza) or a mission that hands a gun; then shoot a cop. Also the "WASTED"/"BUSTED" respawn in third/first person is unverified.
3. **Devtools scene warp under the map.** `scene_key` with `scene_xy=166.5,139.5` (Downtown terrace spot) and the default `164.5,149.5` in Residential/Industrial put the player in mid-air/under the world (state 8 sub 19, sky-coloured ground, the city seen from below: `out/qa_death2c/qa_d2_05_loop008_third.png`, `out/qa_soak_bil/qa_soak_bil_03_first_drive.png`). The warp must resolve the floor lid at the target (`FloorAt`) and refuse spots with none; the soaks' car laps in bil/ste therefore never got a car (the walk laps are clean: `out/qa2_soak_lap1.png`).
4. **Pedestrian posing is the largest of our costs in slow frames.** Downtown soak hitch breakdown (ms summed over 700 flagged frames): game 28578, sprites 6669 (peds 3184, loop 867, props 866, rest 691, cars 375), present 2122, world 1134. On the 4-CPU container the game's own step dominates; our share is pedestrians. A distance LOD would halve it (perf owner).
5. **One-time first ground-view frame** of 1.1-1.8 s in every district (frame ~650-665: model/texture builds on the first switch), plus 4-9 frames over 100 ms per 10-minute run. Pre-warming the ground-view passes once at level load would remove the first one.
6. **Mission runner** leaves the mission car and walks (MISSIONS stream); the renderer side (phone answer, `view: mission` line, 0 faults) is fine.
7. **Fists never provoke police**, so the brawl path cannot reach the arrest animation (`handsup` stays unverified, as the PED-ANIM agent noted).
8. Undocumented ini keys (list above) should be documented or removed.

## Verified list

- 17 runs, 0 FAULT lines in all; 0 `waiting for the player` in all; locator re-scan only at car entry.
- Views: every V switch landed as reported, in all three districts (soaks), on foot and driving, during crashes, exits and re-entries, and under rapid presses.
- Chase camera: wall, railing (pass one), lamp post and tall-vehicle cases; first person at the wheel of a Truck Cab, bus, taxi, sedans.
- Memory: 344.8 MB managed textures, flat over 10 minutes in each district, LAA on, no out-of-memory.
- Classic view pixel-identical with the ground-view features on and off.
- Typed pedestrians (police uniform seen), punch clip, wrecks (forced), 3D pickups/phone (seen in third and first person), trees, water, animated HD tiles, map-hole fixes: no regressions seen in any run; the two map-hole spots were not revisited here.

---

# History: first pass (5 Nov 2026)

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
The recording `deliverables/gta2_linux_driving.mp4` (build of 18:56, before the car-body
work) drove at the cap (`present` 0.2 ms). The bisect runs of the same driving scenario on the
19:44 commit (`qa_drv_a89`) and the 20:09 commit (`qa_drv_67e`) are also slow, there as CPU
time in the live-geometry pass (`sprites` 130-157 ms per frame; the hitch split names the
per-sprite `loop` and `cars` stages, i.e. `RaiseCarBody`/`car_bodies.cpp` building and
measuring car artwork while traffic streams past), and in the current build the same cost has
moved to `present` (buffer uploads deferred by the driver). So the regression came in with
the car-body pipeline between 18:56 and 19:44 and is independent of the `car_models3d`
switch (the sprite-built fallback path pays it too). Owner: the cars stream
(`dll/src/car_bodies.cpp`, `RaiseCarBody`). Suggested check: how many car bodies are built or
measured per frame while driving (`Measured` reads the artwork back with `LockRect`, a
pipeline stall on this driver), and whether the cache key changes every frame for moving
traffic. On a real GPU the readback is cheaper, but the per-frame rebuilds would still cost.

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
