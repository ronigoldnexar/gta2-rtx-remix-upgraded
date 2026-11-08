# QA3: round 2 release check (8 Nov 2026, QA-RELEASE)

Build: the staged DLL of 11:42 (code of `049eb53`, identical in `dll/ src/ vid/` to the release
commit), the round-6 car models and re-imported avatars (stage manifest = committed
`assets/models/manifest.json` of `7bf6a51`), tested from a private hard-linked stage copy
(`stage_qa`). NVIDIA L4 through VirtualGL (`gta2-gpugl-fast`), containers pinned to CPUs 0-4 and
`--cpus=4`, with up to four game containers at once on those five CPUs (the `hitch` counts below
are contention: the 256-frame summaries stay near the cap, wait 21.5 ms average over 100 summaries).
All scripted runs with `GTA2_DIRECT_KEYS=1` (`nav_map=0`), which `qa_run.sh` and `sweep_run.sh`
now default to; both take `STAGE=` for a private stage. Paths below are under `~/gta2-linux/out/`.

## Scenarios (third and first person in each)

| # | scenario | run | result |
|---|---|---|---|
| a | wall push, slide, 360, back off | `qa_q3_wall` | fault 0, waiting 0, lost 0; chase camera clear of the wall, first person at a hand's distance; the black band above the railing in `qa_wall_first_push1..3` is the same as in the 6 Nov run (`qa_wall/`), not new. Sheet `qa3_wall_sheet.png` |
| b | back and forth with V; 29-31 rapid V | `qa_q3_backforth` | fault 0, waiting 0, lost 0, every switch landed. Sheet `qa3_backforth_sheet.png` |
| c | 150 s brawl, 228 punches | `qa_q3_fight` | fault 0, waiting 0. Sheet `qa3_fight_sheet.png` |
| d | car crash in chase and seat views, exit, re-enter | `qa_q3_crash` | fault 0, waiting 0, 100 driving lines; **QA2 open 1 fixed**: leaving the Truck Cab no longer puts the eye in a trash can (`qa_crash_09_first_out.png` vs `qa_crash/` of 6 Nov). Sheet `qa3_crash_sheet.png` |
| e | death and respawn (`respawn4`: provoke, bust, punch the police) | `qa_q3_death` | fault 0; the 520 s run ran out before either: shooting people never raised the wanted level in this take (arrested=False, died=False). Arrest and the police seen in the probes below instead |
| f | 8 min of everything (walk, drive, all views) | `qa_q3_long` | fault 0, waiting 0, lost 20 (the car-entry recycle); car-model textures **356.5 MB, flat from the first summary to the last** (751 textures; QA2's 184 MB predates rounds 4-6). Sheet `qa3_long_sheet.png` |

## Special cases

| case | run | result |
|---|---|---|
| death and respawn in the street views | `v3_a33` (6 stars, `force_wanted=6`) | **verified**: killed by the army five times (lives 5 -> 0, then GAME OVER), each WASTED shown and the view back in a street view after the respawn; fault 0, `waiting for the player` 0. Frames `qa3_army_wasted_third.png`, `qa3_army_respawn_third.png` |
| arrest in the chase view | `q3_police4b` (4 stars, unarmed after the pickup was gone) | **verified**: an officer beside the player and the cop car with its beacons lit, BUSTED with his hands up, then out of the station in third person (`qa3_bust4_99.png` .. `qa3_bust4_103.png`; log `wanted: busted`, `arrest: busted 0.0 s ago, figure at 145.10,105.40, police car at 144.77,104.79`); `q3_police4` busted him five times in 3 minutes, `q3_arrest` (2 stars) once |
| cop-car beacons | `q3_police4b` | verified in play (12 `beacons on model` lines, lit bar in `qa3_bust4_99.png`) |
| ambulance with beacons | `q3_amb`, `q3_amb2` | **not framed**: the first try's bursts hit a wall and nobody died (`q3_amb`); in the second (`q3_amb2`, bursts along the pavement and the road) three ambulances were listed, all driving with **no siren** (0 `beacons on model 34` lines), 27-104 blocks away, and each had moved on by the time the warp ahead of it landed (frames `q3_amb2/qa_amb0*`: the empty street). Still verified only as logged beacons on a driven ambulance (ACTIONS-3D-3, `a33_resc1`) |
| NPC muzzle flash | `q3_police4b` | **not framed**: four `npc shot` lines (an officer's pistol, 13:56:03-04, six blocks from the player) but the shooter was outside the chase camera's frame in every frame of the 15 fps video (video 90.6-94 s); the player's own muzzle flash, tracers and cases are in frame (`q3_amb/qa_amb_fire_07_01.png`). The machine-gun pickup at 166.5,140.5 did not respawn within the run, so the player could not keep shooting back, which is what makes the officers draw |
| SWAT/FBI figures at 5 stars | `q3_police5`, `q3_fbi` | **not seen**: at 5 stars (held by `force_wanted=5`) no police vehicle of any kind came in 150 s on the carriageway (`q3_police5`) nor in 3 minutes driving away and then holding the plaza with the machine gun (`q3_fbi`); the vehicle log lists only trains, the parked tanks, the fire truck, a bus and ambulances. At 4 stars the police came within 35 s in both runs. The SWAT/FBI sprite-body mapping therefore stays unverified (the only `pedestrian without a remap palette` line is body 0, a civilian set). The 8 Nov FBI sightings (`a33_pol5`, `a33_gun1`) were not reproduced |
| tanks, turret | `v3_a33` | verified: tanks and army jeeps on the boulevard, a tank firing its cannon (`qa3_tank_cannon.png`, `qa3_tanks_jeeps.png`) |
| fire truck | `v3_a33` | verified at the wheel in the chase view (`qa3_firetruck_chase.png`), roof gear turned (`turret turned 180 deg` for model 17); no `beacons` line this time (the Tab siren did not register), and the first-person eye still sits behind the roof gear (open since ACTIONS-3D-3) |
| train | `v3_a33` | not seen this time: no train stopped at the station in 180 s (the vehicle log listed both trains elsewhere); the video uses the 8 Nov `a33_train1` frames |
| phone booth | `v3_demo2` | verified: the tutorial phone answered from the booth in third person (`qa3_booth_tutorial_third.png`); see finding 2 |
| new cars in traffic | `v3_demo2` | the round-6 models in Downtown traffic from the chase view while driving the Truck Cab, no missing or white bodies seen (video 318-345 s) |

## City sweep (all three districts, `GTA2DX9_SCENE_NO_CAR=1` warps, magenta clear, sky off)

Plans as on 7 Nov (`gamerun/sweep_plan_<d>.json`), four headings in third and two in first person
per point, two sweep queues in parallel; points lost to a death (finding 1) re-run from plans of the
unlanded points (`gamerun/sweep_plan_bil_q3retry*.json`, `sweep_plan_ste_q3retry.json`). Runs
`out/sweep_<d>_q3_<i>`, retries `sweep_<d>_q3r_*`/`q3s_*`; tables `docs/city-sweep-<d>.md` (regenerated),
worst-20 sheets `out/sweep_<d>_q3_sheet.png`.

| district | planned | landed | frames scored | holes | black | runs with a FAULT | notes |
|---|---|---|---|---|---|---|---|
| Downtown (wil) | 183 | **183** (7 Nov: 177) | 1 098 | 0 | 0 | 0 | 23 `flat` rows, all the first-person eye against a wall right after a warp |
| Industrial (bil) | 188 | 153 | 918 | 0 | 1 (the black frame of a respawn transition, `sweep_bil_q3_3/t_grid_221_40_fa.png`) | 1 (`sweep_bil_q3_1`, after a death) | 34 points not landed: every run that lost the player after a death (finding 1) |
| Residential (ste) | 145 | 134 | 804 | 0 (the 3 `hole` rows are the R.I.P. menu over the magenta clear) | 0 real (the same 3 frames) | 0 | 11 points not landed, same cause |

**No hole in the world and no black street frame** in 2 820 scored frames from 470 viewpoints; the
map-hole fixes hold everywhere the sweep looked, including the hole-class seed cells.

## Regressions and new findings

No regression against QA2 was found in the six scenarios; QA2 open 1 (eye in a trash can after
leaving a car) is fixed. New or still open (none of them in a file this pass owns, so listed, not fixed):

1. **A death in a swapped district ends the sweep run** (Industrial and Residential, `SWAP_LEVEL=bil|ste`;
   seven runs). After a warp death the game shows the R.I.P. screen ("YOU ARE DEAD", although lives
   went only 5 -> 4: `sweep_ste_q3_0/t_zone_164_173_fa.png`, `sweep_ste_q3_1/t_grid_188_246_fa.png`; the
   detector's two `hole`/`black` rows are this menu over the magenta clear, not a hole), or a flat
   changing green classic view with the HUD (`sweep_bil_q3_0`); the renderer logs one `view: waiting for
   the player` and no `view: player` line after it, every later warp is refused (`player not located
   on foot`), and once (`sweep_bil_q3_1`) gta2.exe faulted a minute later (`gta2.exe+0x3ED37 reading
   00000064`, the game camera's bounds at -2..1, the map origin). In Downtown (no swap) deaths respawn
   cleanly (`v3_a33`: five in a row, then the R.I.P. screen at lives 0). So most likely the level swap
   of the test harness (the swapped script's respawn points), not the renderer; not checked in a
   natural Industrial/Residential game. The cost is coverage: each death loses the rest of its chunk,
   so the unlanded points were re-run (`sweep_bil_q3r_0`, `sweep_*_q3s_*`).
2. **Chase camera inside the phone booth** after answering the tutorial phone: the booth model is
   not an obstacle for the camera, so the booth's glass and roof fill the frame (`v3_demo2` video
   about 428-440 s, `qa3_booth_camera_inside.png`). Owner: camera (`WorldView::PanelDistance`
   knows map panels and lamp posts, not code-object models).
3. **First person beside a lamp post** draws the post as a black bar a few centimetres from the eye
   (`qa_q3_crash/qa_crash_10_first_out_turned.png`); the props-off-the-eye rule covers rule-placed
   props, not this post. Owner: props/camera.
4. **Third person after leaving a car against a shop front** frames the wall without the player
   (`qa_q3_crash/qa_crash_11_third_out.png`). Owner: camera.
5. **First person against a wall after a warp** fills the frame with the wall (the sweep's `flat`
   rows, same as on 7 Nov); a sweep artefact, not seen in play.
6. Not framed again: an NPC muzzle flash, the ambulance's beacons (see the table), the train at the
   station this time. Fire-truck beacons not logged this run.
7. Remix: the round-6 cars changed 19 models' texture hashes; the car materials were regenerated
   (`docs/remix-materials.md`, "After car round 6") but **not yet seen under Remix**.

## Release archives and fresh-clone check

Built with `tools/pack_release.py` (new; `docs/HANDOVER.md` section 0 has the layouts) and
attached to the draft release `v1.5-3d-round2`:

| archive | files | bytes | source |
|---|---|---|---|
| `gta2dx9-x86-linux-built.zip` | 262 | 3 659 410 | stage DLLs (md5 `993c6385...` = `dll/build`), ini, reg files, `linux/` from git HEAD with modes |
| `gta2dx9_models_people.zip` | 219 | 135 410 675 | `assets/models/human_*` (41 avatars; every texture the manifest names is present) |
| `gta2dx9_models_cars.zip` | 1 283 | 97 809 314 | `assets/models/0NN_*` after round 6 (all 83 `by_model` entries resolve) |
| `textures_hd_dds.zip` | 2 652 | 246 785 138 | unchanged: the v1.4 asset, CRCs equal to `assets/textures_hd` |
| `remix_mod_gta2hd.zip` | 8 631 | 1 084 585 827 | `gta2hd/` with the round-6 car materials; 8 630 textures, all referenced, none missing |

**Fresh clone** (`git clone` of `camera-modes` at `7bf6a51` into the scratch folder, the archives
unpacked as documented): `assets/models` and `assets/textures_hd` equal `stage/gta2dx9_models` and
`stage/gta2dx9_textures_hd` file for file (`diff -rq` empty), the linux archive's DLLs equal the
staged ones, the Remix layer equals `package/rtx-remix/mods/gta2hd`, `git status` clean (the
archives only add ignored files). `gta2dx9.ini` differs only in line endings (`.gitattributes`
checks `*.ini` out with CRLF; the game reads both). Not done in the dry run: a `make` from the clone
(the DLLs were compared, not rebuilt).

---


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
