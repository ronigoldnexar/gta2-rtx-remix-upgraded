# Performance of the ground views

Measured on 5 Nov 2026 with every feature on: 512 px DDS tiles, sky dome with fog and sun,
per-model 3D cars (AI set + parametric fallback, paint split), CPU-skinned Rocketbox
pedestrians, map objects, street props. The renderer prints per-stage frame times every 256
frames (`frame times, avg/worst ms over 256 frames | game … present … wait`) and, for any
frame whose sprites stage passes 12 ms, a breakdown of that stage (`sprites stage was setup …
loop … issue … cars … props … objects … peds … rest`) plus the model draws (`models: N draws
(M skinned) … posing … buffer fills`). Both come from `dll/src/world_view.cpp`; the sub-stage
marks are in `LiveGeometry::Draw` and `ModelDrawBlend`.

## Where the host stands

Every number here comes from the Docker/Wine 9/Xvfb setup on the B200 box, where Direct3D 9 is
wined3d over Mesa's **llvmpipe** software rasteriser: the "present" column is the CPU
rasterising the frame, which a GPU does in well under a millisecond. The box was also running
other jobs (load average 250-370 on 224 cores, ten game containers at once from the other
streams), so absolute times, and "present" in particular, vary run to run by ±10 ms; the
columns that are ours (sprites, world, cars, peds) are what the changes below are judged on.
The frame is capped at 30 fps by `fps_cap` (see the end), so "wait" is the time left over.

## Before (final_demo, final_drive: the build before this pass)

Walk demo, 1280x720, Downtown carriageway:

| window | game | world | sprites | present | wait |
|---|---|---|---|---|---|
| classic, start of level | 2.4/3.6 | 0.5/0.8 | 0.1/1.3 | 0.0/0.0 | 30.3/30.9 |
| third → first person (switch window) | 2.9/7.8 | 1.0/105.2 | **16.9/633.2** | 0.0/2.1 | 27.3/30.7 |
| first person, walking along the road | 3.6/9.2 | 0.8/1.7 | **160.9/436.4** | 4.8/55.1 | 2.4/29.3 |
| classic again | 3.5/15.4 | 0.6/0.9 | 0.2/5.1 | 0.1/4.3 | 28.8/30.2 |

The first-person window averaged 176 ms a frame (about 6 fps). The hitch breakdown put all of
it in "issue", and the finer marks added for this pass found it: **8 skinned pedestrians cost
203.5 ms of "buffer fills"** a frame (25 ms each). Each pedestrian's posed vertices were
written into a *managed* vertex buffer that had just been drawn from, and wined3d answers that
by draining its GL stream and uploading the whole buffer again, every pedestrian, every frame.
Skinning itself was 4 ms.

Driving script (third person behind the bank van, then first person at the wheel):

| window | world | sprites | present | wait |
|---|---|---|---|---|
| third person driving | 1.2/85.6 | **117.6/739.0** | 0.0/3.1 | 11.0/30.8 |
| first person at the wheel | 0.8/1.8 | **88.6/320.3** | 4.1/159.6 | 13.2/31.0 |

The 633/739 ms worst frames were the first ground-view frame: every model's textures (TGA
read + CreateTexture) and managed vertex/index buffers were created on first use, and the
GL driver uploaded them in that same frame (the props alone, 552 ms, in a later measurement).

## What changed

1. **Skinned meshes draw from per-pose dynamic buffers** (`model_store.cpp`, `SkinBufferFor`):
   a `D3DPOOL_DEFAULT` + `D3DUSAGE_DYNAMIC` vertex buffer per (mesh, cached pose), written once
   with `D3DLOCK_DISCARD` when the pose first appears and kept while the pose stays in the
   pose cache (LRU of 96 buffers). The managed per-mesh buffers are still used for the index
   data and for rigid meshes. Released with the device (`ModelsReleaseDevice`, now called at
   shutdown). Result: buffer fills 203 ms → 0.2 ms a frame.
2. **Textures and mesh buffers are created and uploaded ahead of use**, a few per frame after
   the level loads, in draws with colour and depth writes off (so the GL driver loads them
   but nothing is drawn): every model texture (`ModelsWarmTextures`, 2 a frame, then one model's
   buffers a frame) and every tile texture (`Renderer::WarmTileTextures`, 6 a frame, 994 tiles
   in about 5 s of classic view). Log lines `tile textures: all N uploaded ahead of use` and
   `models: every texture created and uploaded ahead of use` say when that is done.
3. **Nothing is drawn behind the camera**: cars (`car_bodies.cpp`, except the own car), props
   and map objects skip anything more than 1.5-2.5 blocks behind the camera's plane
   (`BehindView` in `live_geometry.cpp`). On the software driver each skipped car saves its
   whole vertex transform and clip.
4. **Finer frame-time diagnostics**: the sprites stage breakdown now separates cars, props,
   objects and pedestrians, and reports the model draws' posing and buffer-fill times; the
   hitch log has its own budget (300 lines) for frames that are ours, separate from slow
   presents, so a busy host cannot use it up before a view switch.
5. **`[renderer] anisotropy`** key (default 0 = 8x). Under wined3d the adapter reports a faked
   "NVIDIA GeForce GTX 470", so a software renderer cannot be detected from inside the game;
   the key is there to force 1 on llvmpipe (measured below), 8 is right for a GPU.

## After (perf4, perf_drive4: the staged build, same scripts, same host under heavier load)

Walk demo:

| window | game | world | sprites | present | wait |
|---|---|---|---|---|---|
| classic, start of level | 4.6/18.7 | 0.7/2.9 | 0.3/26.5 | 29.4/53.9 | 1.8/29.2 |
| third → first person (switch window) | 5.3/78.4 | 1.2/44.6 | **3.7/78.1** | 139.4/971.0 | 0.8/29.1 |
| first person, walking along the road | 6.2/57.3 | 0.8/6.3 | **0.2/8.7** | 35.1/151.6 | 1.5/28.0 |
| classic again | 4.4/16.1 | 0.7/2.1 | 0.2/18.7 | 24.1/53.7 | 5.3/30.9 |

Driving script:

| window | world | sprites | present | wait |
|---|---|---|---|---|
| third person driving (switch window) | 2.0/306.3 | **3.3/248.7** | 92.6/674.4 | 0.4/15.8 |
| first person at the wheel | 1.0/4.1 | **3.0/23.4** | 134.6/285.9 | 0.1/5.8 |
| classic again (load eased) | 0.6/1.6 | 0.3/11.6 | 3.0/35.1 | 27.1/32.5 |

Our own cost of a ground-view frame went from 90-160 ms to 0.2-4 ms; the worst frame at the
view switch from 630-740 ms to 78 ms (walk) and 249 ms (driving: the car bodies measuring and
building their sprite-built atlases for the first cars in view, up to three a frame). What is
left in the ground views is "present": the software rasteriser drawing the frame (sky, 512 px
tiles with 8x anisotropy, lit cars, skinned people), 25-135 ms a frame on this loaded host and
not a cost a GPU has. For a sense of scale, the same classic view that read present 0.0 ms in
the quiet "before" run read 20-30 ms in the "after" runs, which is the host, not the build.

Anisotropy A/B (two identical first-person runs at the same time, `keys_tex.sh`, llvmpipe):
8x present 29-33 ms a frame, 1x 22-29 ms. On the software driver `anisotropy=1` is worth
about a fifth of the frame; on a GPU keep 8.

## The frame cap and 60 fps

`fps_cap` (default 30, `[renderer]` in `gta2dx9.ini`, `dll/src/frame_limiter.cpp`) is the game's
speed as well as its smoothness: GTA2 runs one simulation step per rendered frame and scales
nothing by time, so 60 makes the game run twice as fast. There is no renderer-side way to get
60 Hz of motion at normal speed; that needs the game's own per-step constants halved. On a GPU
the 30 fps cap holds with the frame almost entirely idle ("wait" ≈ 30 ms). On this host's
software GL it holds in the classic view and, with the host quiet, in the ground views too
(the "after" first-person window with the load eased ran at the cap); under the load the
measurements were taken with it does not.

## Follow-up: pedestrians and the own car's cab

- **Pedestrians** (`live_geometry.cpp`, pedestrian block): a person more than 0.6 blocks behind
  the camera's plane is not drawn (his motion track still follows him, so there is no jump
  when he comes back), and beyond 8 blocks his walk cycle is quantised to 12 steps and his
  idle to 5 Hz instead of 24 and 10, so distant people share cached poses and cost no
  skinning of their own. The avatars are 4-6k vertices each, so a decimated LOD would save
  the software rasteriser little and a GPU nothing; it was not done. Third person at the
  spawn plaza with the crowd walking through (two identical runs at the same time,
  `gamerun/keys_perf_third.sh`): sprites stage 3.1/7.5 and 2.5/5.6 ms before → 2.0/4.9 and
  1.5/6.7 after (avg/worst over 256 frames); present ~130 ms in both.
- **Own car from the driver's seat**: the second, vertical clip plane at the windscreen line
  (`car_bodies.cpp`, clip plane 1) is in and verified in a Truck Cab (`out/perf_clip`,
  `drv_14_first_wheel.png`, `drv_15_first_*.png`): the road ahead is clear, no flat cut
  surface in the lower half. A sedan was not available in that run (the devtools scene takes
  whichever car is parked nearest); the plane sits 0.10 blocks ahead of the eye, and the eye
  is 0.12 behind the windscreen line, so a sedan's hood ahead of the windscreen stays.
- **What the software rasteriser costs on its own** (third person at the plaza, concurrent
  runs): sky + 8x anisotropy on, present 126/98 ms a frame; sky off and anisotropy 1, present
  106/98. The ground views cost llvmpipe about 100 ms a frame at 1280x720 whatever the
  settings (world, cars and people over the whole frame with depth and alpha test), which is
  why this host's ground-view recordings run at 8-10 fps. That is the driver, not the build:
  the renderer's own stages are 1-4 ms, and a GPU rasterises the same frame in under 1 ms.

## Still open

- Classic view: the sprite loop hitches of 12-30 ms when the game builds artwork for new car
  sprites (the `loop` stage, `textures built=…` in the sprite-trouble lines); the car HD
  material setup (`car setup slow` lines) did not fire in these runs.
- The first ground-view frame builds up to three sprite-based car bodies (`Measured`/`BodyMesh`
  in `car_bodies.cpp`): 77-250 ms once per session when the first cars come into view.
  Pre-building them for the district's traffic list at level load would remove it.
- Pedestrians: posing is 0.7-4 ms for 4-9 people and no longer a cost.
- The pale/black void where the road surface near the camera should be in some first-person
  frames (seen before this pass in `out/final_demo_f110.png`) is unrelated to these changes and
  is being chased separately.
- A software renderer cannot be detected under wined3d (faked adapter name); `anisotropy=1`
  has to be set by hand there.

## L4 GPU host (6 Nov 2026)

Host: one NVIDIA L4 (driver 580.178.04), 8 CPUs, 31 GB; the game in the `gta2-gpugl` image
through VirtualGL (`gamerun/run_game_gpu.sh`, `--cpus=4`, two game slots at a time), 1280x720,
30 fps capture. Script: `gamerun/cars_drive.py` (devtools scene warp, Return, then 14 s in the
chase view and 26 s from the driver's seat with weaving). Per-stage numbers are the renderer's
own 256-frame summaries (avg/worst ms); the hitch lines now also carry a
`car bodies: measured N (ms) built N (ms) model draws N (ms) sprite bodies N (ms)` breakdown
(`CarBodiesStats()` in `car_bodies.cpp`).

**Finding.** The cars stage is not where driving time goes on this host: 0.1-0.4 ms a frame
in the chase and driver views with 8 model draws per frame. What the old QA runs on llvmpipe
saw as "cars 277-369 ms" came from one thing, and it is fixed: `Measured()` read each car's
artwork back from the *device* texture (`LockRect` on the texture the sprite pass had just
uploaded). On a GPU that readback drains the whole pipeline, and a car's door animation is a
new texture every frame, so the frames at the moment of getting in cost 277 and 369 ms
(`out/dp_gpu2`, frames 3311-3312). Now the measurement decodes the game's own palette indices
on the CPU (`SpriteImageFor()` in `texture_store.cpp`, the same decode the texture builder
does), with the device readback left only as the fallback.

| run | view | game | world | sprites | ui | present | wait | car bodies: measure max / model draws |
|---|---|---|---|---|---|---|---|---|
| dp_gpu2 (device readback) | chase, driving | 14.6/190 | 3.6/11 | 9.2/111 | 1.3/19 | 2.1/47 | 9.0/133 | 369 ms at car entry / 0.1 ms |
| dp_gpu2 | first person at the wheel | 13.2/79 | 3.6/15 | 7.0/33 | 1.3/120 | 1.4/101 | 10.7/27 | |
| dp_gpu3 (CPU decode) | chase, driving | 16.4/78 | 3.2/14 | 7.0/29 | 0.9/9 | 0.6/24 | 8.5/25 | 2.0 ms / 0.1 ms |
| dp_gpu3 | first person at the wheel | 16.9/87 | 3.1/9 | 7.7/71 | 0.7/8 | 1.4/42 | 7.1/25 | 2.0 ms / 0.1 ms |

(`game` is GTA2's own step; this host's cores are slower than the B200 box's, and 4 of them are
given to the container, so it sits at 15-19 ms with worst cases of 80-140 ms when the game
builds artwork. That column is the game, not the renderer.)

**What remains while driving, in order of size** (hitch lines of `out/dp_gpu3`): the game's own
step (above); `present` spikes of 100-475 ms a few times a minute (the GPU/VirtualGL path, not
our draw: they come with `game` spikes and texture builds); the pedestrian posing at 10-19 ms
in frames with 7-8 skinned people in view (the 4-CPU container; the posing budget beyond 8
blocks applies); props at 2-7 ms. None of these is in the car code.

## Pedestrian level of detail (POLISH-3, 6 Nov evening, L4 host)

QA pass two found the pedestrian posing the largest of our own costs in slow frames
(`peds` summed over the Downtown soak's flagged frames: 3184 ms, versus 375 for the cars).
`DrawPedFigures` now ranks the people seen each frame by distance from the eye (`PedTrack::rank`,
from the previous frame) and poses them in three tiers: the nearest eight within ten blocks every
frame as before; the rest hold their quantised pose values (`lodU`, `lodIdleT`, weights, action
time) for three frames at a time, so the pose cache answers the two frames in between; beyond
eighteen blocks a figure is the idle key with no blending, one cached pose shared by everyone that
far off (a body lying on the ground keeps its lying key). The drawn position, heading and the
motion smoothing are untouched, only how often a new skin is computed.

Same scenario (`gamerun/qa_soak.py`, 540 s of walking, F10 car, driving and leaving it, all
views, Downtown), same 4-CPU GPU container, both on a host shared with other streams' runs:

| run | frame summaries | frames flagged slow | peds ms in flagged frames: n / sum / mean / max | sprites stage avg (mean / max of summaries) | sprites worst (mean / max) | game avg | wait avg |
|---|---|---|---|---|---|---|---|
| `qa_soak_wil` (before, QA2) | 76 | 1600 | 300 / 3184 / 10.6 / 64.9 | 4.0 / 13.0 ms | 28.0 / 194 ms | 8.8 ms | 19.0 ms |
| `qa_p3soak_wil` (after) | 70 | 100 | 22 / 151 / 6.8 / 16.1 | 2.4 / 5.1 ms | 10.2 / 78 ms | 6.5 ms | 23.9 ms |

Read with the usual caveat (host load differs between the two runs; the `game` column is GTA2's own
step), the sprites stage averages fell by about 40 % and its worst cases by about two thirds, and
the frames our side flagged as slow went from 1600 to 100 over the same nine minutes, with the
posing no longer the top item in them. 0 faults, 8 laps.

## Playing through the browser (7 Nov 2026, PLAY-PERF)

Measured in the play container itself (`gamerun/play.sh plain`, image `gta2-play` on
`gta2-gpugl`, the L4 through VirtualGL, 6 CPUs), driving a car through VNC with
`vncdotool` while the display was captured at 30 fps inside the container and the
renderer's key log timed each key press (`[devtools] log_keys=1`).

| | before (04d747f) | after |
|---|---|---|
| GL renderer inside the play image | NVIDIA L4 (vglrun) | same |
| display frames identical to the previous (30 fps capture, 60 s of driving) | 0.3 %, one stall of 3 frames | 0.1 %, no stall |
| frame rate a local VNC client could pull | 21.0 fps | 22.1-24.9 fps |
| key press to the game (median / max) | 29 / 41 ms | 25 / 32 ms |
| game's spawn window in the street views | 21.6 x 12.2 tiles (x1.8, 16:9): traffic created 6 blocks ahead on the short axis | 31 x 42 tiles (x2.6, square) |
| cars first seen (renderer pop log, 900-frame windows) | at the window edge, 6-10 blocks | mean 21-25 blocks; 1-2 of 35 inside 12 blocks (the own car and respawns) |
| renderer stages while driving, avg ms | game 7.5-8, world 1.9, sprites 2.6-3.4, wait 20 | game 4.8-5.2, world 1.9, sprites 5.0-8.2, wait 17.6-20 (the 30 fps cap holds) |

What was wrong and what changed:

- **Pop-in** was the game's own spawn window. GTA2 creates, draws and removes cars and
  people inside the rectangle its top-down camera frames; the street views scaled it by
  1.8 but kept its 16:9 shape, so looking along the short axis traffic came into being
  six blocks ahead, in clear air. The window is now square and 2.6x in the street views
  (`gameViewScale`, `world_view.cpp`), so objects exist 15 blocks out in every direction
  and first appear 20-25 blocks away, small and already in the haze (fog now starts at 18
  blocks, `[sky] fog_start_blocks`). The car-body LOD switch at 20 blocks
  (`kCarBodyLodBlocks`) is gone (60, beyond the window), and props reach 36 blocks
  (budget 180). A `car pops:` log line every 900 frames counts new bodies and their
  first-seen distance.
- **Lag and stutter** were not in the container: cadence, latency and frame rate are
  clean locally, and the GPU path is confirmed in the play image. A remote player's feel
  is set by the link (full 1280x720 JPEG frames over the internet). `x11vnc` now runs
  `-threads -defer 15 -wait 15 -nocursorshape`; the landing page offers a
  low-bandwidth Play link (noVNC quality 3, compression 6) next to the default one
  (quality 5, compression 3); `PLAY_RES=low` runs the game at 960x540; the container's
  CPU limit defaults to 7.
- Costs: the wider window means more live cars and people to draw (sprites stage up
  from ~3 to ~6 ms, worst frames 27-34 ms, 126 of 355 hitch lines were pedestrian
  posing); the cap still holds on average. A remote link that cannot carry 25 fps will
  still feel laggy; that is the next lever (lower resolution or H.264 streaming), not the
  renderer.

## Frame-time stability while driving (8 Nov 2026, PERF-2)

The complaint, from the browser: lag while driving, movement that felt stuck, distant objects
popping in unstably, freezes. The spawn-window pop-in was fixed in PLAY-PERF; this pass measured
every frame instead of 256-frame summaries.

### The per-frame log

`GTA2DX9_FRAME_LOG=<windows path>` (off by default; e.g. `-e 'GTA2DX9_FRAME_LOG=Z:\out\frames.tsv'`
on a run) writes one tab-separated line per rendered frame (`dll/src/frame_log.cpp`):

- phases in ms: `game` (GTA2's own step, split into `sim` = previous frame end to
  `gbh_BeginScene`, `game_draw` = its draw stream, `hooks` = our code inside that stream),
  `pre_*` (world load, animated tiles, input, `pre_camera` = UpdateCamera with `cam_locate` the
  player locator and `solver` the camera solver, menu, time of day), `lights`, `sky`, `world`,
  the sprites stage's sub-stages (`spr_setup`, `spr_loop`, `spr_skid`, `spr_issue`, `cars`,
  `props`, `objects`, `peds`, `effects`), `ui`, `present`, `wait` (the 30 fps cap's sleep);
- counts: `draws`/`up_draws`/`prims` (the device's draw entries are counted through its vtable
  while the log is on), `tex_created`, `vb_created`, `ib_created`, `tex_uploads` (texture
  UnlockRect), `update_tex`, `model_tex`, `model_buffers`, `new_poses`, `skin_buffers`,
  `model_draws`, `skinned`, `posing`, `fills`, `car_measured`, `car_built`, `guarded_faults`;
- state: `view` (0 classic, 1 third, 2 first), `driving`, the player `px py pz` (game frame) and
  the camera eye `cx cy cz` (renderer frame), `sprite_quads`;
- per stage (FIX-PERF-4, the last 26 columns): `dr_*` draws and `pr_*` primitives of `pre` (before the
  sky), `sky`, `world`, the sprites stage's nine sub-stages (`setup`, `loop`, `skid`, `issue`, `cars`,
  `props`, `objects`, `peds`, `rest`) and `ui` (the 2D layer, the dissolve, the F4 menu).

Tools (`linux/docker/`, copied to `gamerun/`): `perf2_run.sh <name> <wil|bil|ste> [stage]`
runs `perf2_drive.py` at the play container's settings (image `gta2-play`, `--cpuset-cpus=5-7`,
1280x720, `GTA2_SPEED=1`, 15 fps capture): the scene warp puts a parked car on the road by the
spawn, then `drive3` takes it to road cells 25-50 blocks away (seeded route) for 100 s in the
chase view. `perf2_analyze.py` reports the driving window's frame cost (frame time minus the
cap's wait) and every frame over 33 ms with its three largest phases; `perf2_motion.py` the
camera's per-frame steps against the car's; `perf2_sheet.py` draws
`out/perf2_frametimes.png` and `out/perf2_sheet.png` (matplotlib, in a venv).

### Before and after

Third-person driving, ~105-115 s per district (3100-3400 frames), frame cost in ms. Before =
`out/p2_before_*` (the build of 8 Nov morning with the log added), after = `out/p2_final_*`
(this pass). Both with the 15 fps recorder in the container, which competes for the same three
CPUs the way x11vnc does when a player is connected.

| district | p50 | p95 | p99 | max | frames over 33 ms | draws / triangles a frame | camera step jitter p90 | camera jumps / min |
|---|---|---|---|---|---|---|---|---|
| Downtown before | 18.3 | 50.9 | 92.6 | 809 | 577 (18.4 %) | 1598 / 2.05 M | 0.40 | 13.2 |
| Downtown after | 9.0 | 25.4 | 40.9 | 61 | 73 (2.2 %) | 1204 / 1.88 M | 0.03 | 2.1 |
| Downtown after, no recorder | 6.9 | 12.8 | **24.1** | 59 | 18 (0.5 %) | 1193 / 1.63 M | 0.04 | 6.0 |
| Residential before | 14.0 | 40.3 | 84.5 | 654 | 256 (7.9 %) | 1392 / 1.40 M | 0.21 | 9.5 |
| Residential after | 8.6 | 25.7 | 42.5 | 83 | 88 (2.7 %) | 1217 / 1.33 M | 0.10 | 11.0 |
| Industrial before | 17.1 | 47.6 | 75.2 | 632 | 507 (16.3 %) | 1742 / 2.31 M | 0.46 | 40.5 |
| Industrial after | 8.7 | 24.2 | 40.2 | 80 | 63 (1.9 %) | 1269 / 1.37 M | 0.05 | 0.0 |

(The after runs also draw props out to 48 blocks instead of 36, see below.) Camera step jitter
is the frame-to-frame change of the camera's step, in units of the car's step, over stretches
where the car moves at a steady speed; a camera jump is more than 0.6 block in one frame.
Downtown's route differs between before and after (the before route's seed lost the car).

The targets are met only without the recorder: there the 99th percentile is 24 ms and the
interval between frames holds 33.5 ms at the 99th percentile (no missed frame), with 18 frames
over 33 ms in 105 s. With the recorder (or a player's VNC encoder) on the same three CPUs the
99th percentile is 40-43 ms, and the spikes left are, in this order: GTA2's own step (`game`
15-20 ms while the CPUs are shared: 1.8 ms mean and 5.7 ms p99 without the recorder, so it is
contention, not the game), the cars' dent and door copies (below), a crowd's posing, and a
`present` now and then.

### Causes found and fixed

1. **Other runs on the player's CPUs.** `grun.sh` documented `CPUSET=0-4` but only passed it when
   set, and the other runners never did: two unpinned mission runs held CPUs 5-7 (the play
   container's) at 75-97 %. `runq.sh` now pins every `docker run` it starts without a CPU set
   to `GAME_CPUSET` (default `0-4`); the two running containers were moved with
   `docker update --cpuset-cpus 0-4`.
2. **The player locator read memory with ReadProcessMemory**, a wineserver round trip per read,
   and at the wheel it walks the vehicle list every frame (`VehicleDrivenBy`): 3.6 ms per frame,
   21 ms p99, 70 ms when the server was busy (`cam_locate`). Reads now check the address's
   region once with VirtualQuery (committed, readable, no guard page), remember it, and load
   under the fault guard (`view_modes.cpp` `ReadAt`): 0.01 ms.
3. **Props were most of the draw calls and triangles**: up to 180 street lamps (30 k triangles,
   8 meshes), hydrants (86 k, 10 meshes) and bins, rebuilt from a 73 x 73 cell scan every frame
   and drawn whenever in front of the camera: 4.4 ms a frame in Downtown. Now each rigid prop
   is one mesh per texture with its node transforms baked in (`MergeStatic` in
   `model_store.cpp`; lamp 8 draws -> 2, hydrant 10 -> 1, bin 4 -> 1, same triangles), the
   placements are kept while the eye stays in its cell, and a prop outside the view frustum's
   side planes is not drawn (`OutsideViewFrustum`, also used for map objects and people beside
   the picture). Props cost 0.6-1.3 ms with the radius raised to 48 blocks.
4. **The model warm-up ran for 18 s of every level** at two textures a frame, each frame reading
   TGA files on the render thread: 5 ms typical and up to 98 ms (the `effects` spikes), and a
   switch to the street views inside those 18 s built the rest at first sight (`cars` 158 ms).
   A reader thread now reads the ~680 model textures ahead (at most 96 MB waiting); the warm-up
   is bounded by time (8 ms a frame in the classic view, 2 ms in the street views) and is done
   3.5 s after the level loads. Tile textures warm 24 a frame in the classic view (was 6).
5. **Shader compiles at the first street-view frames.** wined3d makes a GL shader for every new
   fixed-function state (fog, sun light, water, glow, paint tint), and the NVIDIA driver
   compiled them in the first frames of every session: `present` 300-700 ms. Its disk cache was
   lost with each container; `play.sh` (and `perf2_run.sh NVCACHE=1`) now mount
   `gamerun/nv_cache_gl` as `__GL_SHADER_DISK_CACHE_PATH`. Second session: those frames'
   `present` is 0-1 ms (runs `p2_a4_bil` -> `p2_a5_bil`).
6. **The sky's cloud texture** (256x256 of noise) was built in the first street-view frame
   (`sky` 130 ms); it is built during the tile warm-up now (`Sky::Warm`).
7. **Skinned pedestrians**: the per-pose vertex buffers were capped at 96, which a crowd cycling
   24 walk poses each thrashed (5 buffer creations a frame); the cap is 256 and evicted buffers
   are reused. New poses are limited to 5 a frame (past that a figure takes the cached pose of
   its model and clips nearest in time, within 0.12 s), and the skinning loop is built for SSE2.
8. **Camera clearance tests** ran over every lamp of the map (1-4 ms a frame in Industrial); a
   lamp grid by map cell answers them now.

### Smoothness of motion (frame pacing)

GTA2 steps its simulation once per rendered frame and scales nothing by time, so at the cap the
car's per-frame step is even (the position trace shows it changing smoothly with the throttle).
The chase camera, though, eased with the wall clock: a frame that came 10 ms late moved the car
no further but the camera further, so at a steady speed the camera's per-frame step ranged
0.08-0.21 blocks for a car moving 0.13-0.15 (jitter p90 0.40 car steps). With the frame limiter
on, the camera now advances one game step (1/30 s) per frame (`UpdateCamera`, `stepLocked`;
uncapped it keeps the wall clock): jitter p90 0.03-0.10. `fps_cap` and `GTA2_SPEED` are
unchanged: at `GTA2_SPEED=2` the camera moves with the game at twice the speed.

The chase camera also jumped: every time the car passed under a sign gantry or a railway
bridge over the road, the line from the car to the camera met it and the camera was pulled 1-4
blocks toward the car in one frame (the ease allows a block of lag), then craned up over it;
cutting a corner pulled it to a block from the car for one frame. It now goes down under an
overhead at the same distance, and an eased eye cut off by a corner moves toward the wanted
spot instead of along the ray (`view_modes.cpp`): camera jumps over 0.6 block 13-40 a minute
before, 0-11 after (what is left is the car scraping walls in the scripted drive).

### Pop-in

Cars: 0 new car bodies within 12 blocks in every 900-frame window of driving (mean first sight
20-28 blocks; windows with the scene warp excepted). People: a new `ped pops:` line counts the
people the renderer had no track for: 3-53 a window, mean first sight 18-33 blocks, 0-2 of them
in the picture within 10 blocks (people stepping out of doors and cars). Props now appear at 48
blocks, a quarter into the fog. Buildings are the whole map's static mesh and never pop.

### Still open

- Car dents and door splits (`car_bodies.cpp` `DentedModelFor`, `DoorSplitFor`) are derived on
  the render thread the first time a car reaches a new dent step or opens a door: 20-70 ms, the
  largest `cars` spikes after this pass (33 copies in a 100 s Downtown drive with crashes).
  Building them on a worker thread, drawing the previous step until ready, would remove them.
- GTA2's own step and `present` spike when the three CPUs are shared with an encoder; without
  the recorder the frame holds the cap (p99 interval 33.5 ms).
- A crowd's posing reaches 10-14 ms in the worst Residential frames.

## Car wear off the render thread, and play with a browser connected (8 Nov 2026, PERF-3)

### Dents and door splits

PERF-2 left one car cost on the render thread: the dented copy of a car model (four steps) and
the door split (the hull without the door panel, and the panel) were derived the first time a
car reached a new step or opened a door, 20-70 ms each and up to 400 ms when several cars did it
in one frame. Now (`car_bodies.cpp`, "PERF-3"):

- **A worker thread builds them** (`WearThread`): the render thread asks (`DentReady`,
  `DoorReady`), draws the highest dent step it already has (or the fresh shell) and keeps the
  door shut until the split is there, and registers finished copies with the model store at the
  start of the next cars stage (`WearCollect`, at most ~2 ms of it a frame). An open door whose
  car changes dent step keeps its earlier split until the new one arrives, so a door never
  snaps shut. The geometry is the same code as before (value-noise dents, door panel cut);
  the position-keyed maps are hashed instead of ordered, which changes no result: across the
  before and after runs, 72 of 72 dent copies moved the same number of vertices and 88 of 88
  door splits cut the same number of triangles (`dented copy of ... N vertices pressed in`,
  `door split of ... N door triangles` lines).
- **Ahead of need:** the first time a car model is drawn, its four dent steps are queued at low
  priority (the worker sleeps as long as each such job took, so it uses at most half of one
  CPU); a crash then usually finds its step built. Queued ahead only while the dent copies hold
  less than 160 MB (`kDentAheadBytes`).
- **Their buffers do not stall the frame.** Moving the build off the thread was not enough
  (`p3_after_wil`: cars spikes of 215 ms remained, all in frames that created a copy's buffers):
  the first draw of a new mesh locked a new managed vertex buffer mid-frame, and wined3d waits
  there for the frame's queued GL work. Copies registered with `ModelRegisterDerived(model,
  true)` now get dynamic default-pool buffers written with `D3DLOCK_DISCARD` (`BuffersFor`,
  `model_store.cpp`), and at most one new copy goes on screen per frame (`WearMayShow`: a forced
  door on every car in view made twelve buffer creations in one frame, 174 ms on a busy host).
- **Memory:** a dent copy is ~0.41 MB (vertices and indices; the same again in GPU buffers once
  drawn). In the 100 s forced drives the copies held 41-62 MB (dents 21-31 MB in 52-76 copies,
  door splits 19-29 MB in 43-69 splits). All 68 car models x 4 steps would be ~111 MB, under
  the 160 MB cap; door splits of dented copies stop at 64 MB (`kDoorSplitBytes`; past it a
  dented car opens the door of its undented copy), and the door panel now keeps only the
  vertices it uses. The store never frees a model, so these caps are the bound; the old
  `g_doorSplits.clear()` at 64 entries leaked every split it dropped and is gone.
- `car wear:` log line every 900 frames: copies built, worker time, MB, and how many frames a
  car waited for its copy.

**The damage word.** PLAYTHROUGH-7 found that the dents read the low byte of the vehicle's
damage, which is an int16 at `+0x74`, 0..32000 (docs/actions-3d.md, "Vehicle fields").
`live_geometry.cpp` now passes the word and the fire stage byte (`+0x8C`); the dent steps are
4000 / 8000 / 16000 / 25000 (under 4000 the shell stays fresh), and from 16000 (the game sets a
car alight there) the paint is scorched to 0.70 of its colour, from 25000 to 0.45, on top of
the dents' dulling. `[devtools] force_car_damage` now takes the word too (0..32000). Verified
with `set_car_damage` 0/4000/8000/16000/25000 written into the player's car
(`out/look_p3e`, log: `the player's car (model 13) at damage 16000: dent step 3, fire stage 3`
... `25000: dent step 4, fire stage 4`; the frames are the last row of the sheet). The ini
comment no longer contains the text `set_car_damage=`: the scripts' "add the key if it is not in
the file" test matched the comment, so the key was never written.

**Measured** with `gamerun/perf3_run.sh` (the PERF-2 drive through Downtown, `perf3_drive.py`,
with `force_car_damage` and `force_car_door` stepped every 5 s so every car in view needs a new
copy at once; 1280x720, `--cpus=3` on CPUs 0-4, frame log on). "Car frames" are frames over
33 ms whose largest phase is the cars stage, from 5 s after the level; the host's load from the
other streams' runs varied a lot (the drive's own p50 column says how busy it was):

| run | build | drive p50 / p99 ms | car frames | cars stage p99 / max ms |
|---|---|---|---|---|
| `p3_before_wil` | before (HEAD 373181f) | 21.3 / 95.7 | 28 | 20.7 / 412 |
| `p3_pb_wil` | before | 25.0 / 134 | 44 | 50.6 / 356 |
| `p3_pb2_wil` | before | 9.7 / 56.7 | 33 | 18.9 / 213 |
| `p3_pb4_wil` | before | 32.6 / 283 | 43 | 87.0 / 749 |
| `p3_after_wil` | worker only (managed buffers) | 14.2 / 73.7 | 22 | 12.6 / 215 |
| `p3_pa2_wil` | worker + dynamic buffers | 10.3 / 53.6 | 1 | 4.9 / 22 |
| `p3_pa3_wil` | worker + dynamic buffers | 8.7 / 37.4 | 1 | 4.0 / 31 |
| `p3_fin_wil` | + damage word (4 distinct steps) | 10.1 / 66.0 | 4 | 6.0 / 223 |
| `p3_fin3_wil`, `p3_fin4_wil`, `p3_fin5_wil` | same, host at load 20-30 | 29.7-31.1 / 199-212 | 9, 16, 11 | 10.9-21.3 / 73-174 |
| `p3_pb5_wil` | before | 16.7 / 95.1 | 46 | 33.4 / 194 |
| `p3_fin6_wil` (run right after `p3_pb5_wil`) | final: + one new copy on screen a frame | 9.6 / 61.5 | 5 | 6.5 / 52 |

On a host of ordinary load the dent and door copies no longer cause a frame over 33 ms: the
one car frame left in `p3_pa2_wil`/`p3_pa3_wil` is a car's **sprite artwork** being created
(`DeviceTextureFor`, `tex_created=1`; the new `the sprite artwork of a car took N ms` log line:
44 such fetches over 8 ms in four runs, median 15 ms, worst 131 ms on the loaded host). On the
heavily loaded host the rest are frames where GTA2's own step took 30-400 ms too and the car
draws waited on Wine's GL thread (`model draws 4 (103 ms)` with no buffer or copy made); one
frame with 12 buffer creations (174 ms) led to the one-copy-a-frame limit, confirmed in the
paired runs `p3_pb5_wil` / `p3_fin6_wil` (46 car frames, worst 194 ms, before; 5, worst 52 ms,
after: two sprite-artwork fetches, one copy's first draw at 35 ms, two first street-view frames
with a crowd's first poses). No dent or door copy
was built on the render thread in any after run (every `dented copy` / `door split` line says
`worker N ms`).

### Play with a browser connected

`gamerun/perf3_play.sh <label> <none|novnc> [quality] [compression]` restarts the play
container (`gta2-play-8090`, CPUs 5-7, image `gta2-play`, with `PLAY_FRAME_LOG=1`: the per-frame
log in `out/play-8090/frames.tsv`) when nobody else is connected, runs the PERF-2 drive inside
it (`docker exec ... perf2_drive.py`, 90 s), and for `novnc` opens the landing page's noVNC
client in headless Chromium on the host (`perf3_vnc_client.py`, pinned to CPUs 0-4, the
default Play link's quality 5 / compression 3 or the low-bandwidth link's 3 / 6), which decodes
and paints every frame the way a browser tab does and counts what arrives on the websocket.

| run | build | client | frame cost p50 / p95 / p99 / max ms | interval p99 ms | frames over 33 ms |
|---|---|---|---|---|---|
| `p_none_base` | HEAD (373181f) | none | 6.7 / 14.7 / 32.9 / 81 | 35.3 | 31 |
| `p_novnc_base` | HEAD | noVNC q5 c3 | 7.4 / 16.1 / 25.2 / 76 | 35.0 | 17 |
| `p_novnc_base2` | HEAD | noVNC q5 c3 | 10.1 / 25.2 / 41.2 / 131 | 41.3 | 59 (16 of the spikes are the cars stage: crashes building dents on the render thread) |
| `p_none_fin` | PERF-3 | none | 7.8 / 16.2 / 25.2 / 61 | 34.0 | 10 |
| `p_novnc_fin` | PERF-3 | noVNC q5 c3, 1.8 MB/s | 10.0 / 21.6 / **29.7** / 59 | 35.7 | 10 |
| `p_novnc_fin2` | PERF-3 | noVNC q5 c3, 2.3 MB/s | 7.8 / 16.0 / **22.8** / 66 | 34.1 | 5 |
| `p_novnc_fin_q3` | PERF-3 | noVNC q3 c6, 1.4 MB/s | 7.7 / 16.6 / **29.6** / 74 | 35.1 | 16 |
| `p_novnc_base3` (PERF-3 build, mislabelled) | PERF-3 | noVNC q5 c3 | 11.2 / 25.4 / 36.7 / 51 | 37.8 | 58 (29 of the spikes are GTA2's own step) |
| a real remote player, 07:10-07:20 (`real_player_session`) | PERF-3 (an earlier step: worker, dynamic buffers, damage word) | a browser over the internet | 7.8 / 15.0 / **26.4** / 252 | 34.8 | 55 spikes in 587 s (he joined during the scripted drive's last 45 s, then sat in the parked car in the chase view) |

The encoder does not starve the game: x11vnc took 17-18 % of one CPU and Xvfb 5-9 % while
`gta2.exe` took 70-80 %, and with a client connected the 99th percentile was 22.8-29.7 ms in
three of four PERF-3 runs, under the 33 ms target; the x11vnc settings are therefore left as
they were. The one run over (36.7 ms) had its spikes in GTA2's own step, and at that time
three host-side Python jobs of another stream (`run_trellis.py`, `fit_r5.py`, a `gen3d`
script) were running unpinned on all eight CPUs, two of them on CPUs 5-7 at 70-100 %; they
were repinned to 0-4 (`taskset -apc 0-4`). Host jobs started outside the run scripts are not
covered by `runq.sh`'s pinning; start them with `taskset -c 0-4`.

Two per-frame costs in the play container were found and removed on the way:

- **`pre_menu` spikes of 15-30 ms** in clusters (16 of the 45 spikes of `p_none_1`): the
  auto-save watcher (`game_save.cpp`) read the score keeper with `ReadProcessMemory`, four
  wineserver round trips a frame, which stall whenever the server is busy with input. It now
  reads like `view_modes.cpp` does since PERF-2 (the region checked once with VirtualQuery,
  then plain loads under the fault guard). The F4 menu and the F9/F10 probe keys asked for the
  foreground window every frame; now only when their key goes down.
- The dents and doors above (the `cars` spikes in `p_novnc_base2`).

Knobs added (defaults unchanged): `PLAY_FRAME_LOG=1` (the per-frame log and the state lines),
`PLAY_X11VNC` (x11vnc's tuning flags, default `-noxdamage -defer 15 -wait 15 -threads`) and
`PLAY_VNC_NICE` (its niceness) in `play.sh` / `play_game.sh`.

### Look check

`gamerun/perf3_look.py` takes the same frames from any build: three Downtown spots after a
scene warp, chase and first-person views on foot; the traffic at the spawn with
`force_car_damage` 0 / 8000 / 25000 and `force_car_door` 1; the player's car with
`set_car_damage` 0..25000, seen on foot beside it. Runs `out/look_p2old` (06d1a97, before
PERF-2), `out/look_p2new` (HEAD, PERF-2) and `out/look_p3e` (this build). In the strip
(`out/perf3_sheet.png`) the buildings, lamps, hydrants, bins, fences and signs are the same in
every pair; what differs is the traffic and the people (the game's own randomness) and, between
the PERF-2 pair, a slightly different chase framing from PERF-2's camera changes, which is why
the coarse difference images are not near zero and are not the criterion. Distance 48 shows
as lamps further down the road in the PERF-2 after frames, the intended change. For the wear
change the geometry check above (identical vertex and triangle counts for every copy) is the
stronger evidence; the frames show the same dents and door at the same steps.

### Still open

- A car's sprite artwork created at first sight or when the game repaints it (`DeviceTextureFor`
  in `texture_store.cpp`): 8-36 ms on an ordinary host, the largest car cost left. The same
  managed-texture lock as the buffers above; a dynamic default-pool texture would remove it,
  but the store serves every sprite and was not changed here.
- A copy's first draw can still cost ~35 ms on a busy host (`p3_fin6_wil` frame 1934, one
  copy, four buffers): the GL upload of a new buffer; uploading them in a no-pixel draw at the
  start of a frame, as the warm-up does, would spread it further.
- On a host at load 20-30 every phase stretches with GTA2's own step, the car draws included;
  that is contention, not the car code.

## Car sprite artwork off the render thread (8 Nov 2026, PERF-4)

PERF-3 left one car cost on the render thread: a car's **sprite artwork** made the first time a
car model or paint came into view, or when the game patched a door, a dent or a lamp into it
(`DeviceTextureFor` in `texture_store.cpp`): 8-36 ms a car on an ordinary host and up to 131 ms
on a busy one. The car models do not even sample that texture (only their paint is measured
from the sprite, on the CPU), but the cars stage and the shells' setup asked for it, and it was
built there: palette decode, the effect classifier, edge bleed, hole closing and a TGA dump,
then a new managed texture whose first lock waited for the frame's queued GL work.

Now (`texture_store.cpp`, "PERF-4"):

- **Car artwork is recognised** by shape and palette: the size of one of the style's car
  sprites in one of the palettes car models are drawn in (each car sprite's own, and every remap
  its CARI entries list; 44 palettes in Downtown). No other sprite of the three districts has a
  car sprite's size in one of those palettes.
- **A worker thread makes it** (`CarArtThread`, the PERF-3 wear thread's pattern): the render
  thread copies the palette indices and the 256 colours (the game rewrites both whenever it
  likes) and queues the job; the worker runs the same pixel work as before (shared
  `ClassifyArtwork` / `FinishArtwork`, so the texels are identical) and the dump. The worker
  polls (2 ms) instead of being woken: a `SetEvent` is a wineserver round trip, and on the busy
  host one cost the render thread 10-27 ms in the first after run.
- **Dynamic textures, a per-frame budget.** A finished frame becomes a `D3DUSAGE_DYNAMIC`
  default-pool texture written with `D3DLOCK_DISCARD`, which wined3d (Wine 10) serves from an
  upload buffer without waiting for the frame (`wined3d_cs_map_upload_bo`); uploads measured
  0.01-0.06 ms. At most 4 asked-for frames (2 ms) and 6 precached frames (1 ms) are uploaded
  per 20 ms window.
- **Until it is there** the car is drawn with the record's previous artwork when it is the same
  size (the same car a door or a dent earlier), else the precached frame of that car sprite in
  that palette whose pixels match best (the car without the patch), else a transparent 8x8
  stand-in. The cars stage only measures the paint from the record's own pixels, so the 3D car
  keeps its colour; in the run below a new frame was on screen after 1-2 draws (at most 72 ms).
- **Precached at level load.** `CarArtPrecache(stylePath)` (the one hook, in `world_view.cpp`
  where the level's style is loaded) has the worker read the style's car sprites and queue every
  sprite in every palette its models use: 656 frames in Downtown, made in 4.9-6.2 s after the
  level loads within the budget above. Afterwards only the game's patched frames (doors, dents,
  lamps) are new: 16 asked-for frames in the 100 s after run, against 656 made ahead.
- **Memory:** 9.1 MB of texels for the 656 precached frames (wined3d keeps a system-memory copy
  of a dynamic texture besides the GL one, so up to ~18 MB), 0.3 MB of sprite indices, and the
  asked-for frames as before. A district change precaches its own style; frames stay keyed by
  content and the 8192-frame flush (which drops all frames) queues the precache again.
- `car art:` log lines: the parse, the precache summary (frames, MB, seconds, upload and worker
  times), each asked-for frame (first 60: worker ms, upload ms, wait, stand-in draws), uploads over
  3 ms and asks over 4 ms.

**Measured** with `gamerun/perf4_run.sh` (`perf4_drive.py`: the PERF-3 Downtown drive, 100 s,
dents and doors forced every 5 s and `force_car_model` stepped every 7 s; `CPUS=1.5`, the slot
size under the new host-capacity rules; the host at load 12-17), one before/after pair built
from the same HEAD (before = HEAD, after = HEAD + this change), `perf4_analyze.py`. "Car
artwork costs" are the log's own timings of a car's artwork on the render thread (`sprite
artwork of a car took`, the shells' `car setup slow ... artwork`, and the new `car art:` ask and
upload lines), mapped to frames through the `view: cars frame=N` lines:

| run | build | car artwork costs >= 4 ms | of them in a frame over 33 ms | worst | frame cost p50 / p99 ms | frames over 33 ms |
|---|---|---|---|---|---|---|
| `p4_bx1_wil` | before | 8 | 5 | 120.9 ms | 19.4 / 134.5 | 733 of 2582 |
| `p4_ax2_wil` | PERF-4 | **0** | **0** | 0.06 ms upload | 19.3 / 167.3 | 807 of 2199 |

Every car artwork spike is gone; the frame cost percentiles did not move with it, because on
this host at 1.5 CPUs a third of all frames are over 33 ms from contention (GTA2's own step,
`ui` and `spr_issue` stalls of 40-80 ms with no texture made), which swamps the 5 frames the
artwork accounted for; the p99 difference is the load, not the change (PERF-3's runs varied as
much between identical builds). The coarser "frames over 33 ms with a texture made in an artwork
stage" count (17 before, 26 after) is mostly pedestrians' animation frames, which this change
does not touch. In the after run 640 of 656 precached frames were never asked for again and 16
patched frames were made on the worker (12 drawn once with a stand-in, 4 twice); the one slow
upload (72 ms) was the very first dynamic texture of the session, at level load in the classic
view. An earlier after run (`p4_ax1_wil`, before the worker was made to poll) still had three
10-27 ms asks, all `SetEvent`. `out/perf4_sheet.png`: the pair.

Not changed: other sprites (pedestrians' animation frames, objects, HUD) are still built on the
render thread; with Remix the car artwork is now a dynamic texture (Remix's hash of it is not
tested here).

**Second series (8 Nov, 8x L4 host, PERF-4-2).** Both DLLs built from the same HEAD `7cc5131`:
after = HEAD, before = HEAD with `texture_store.*` from `76569af^` and the `CarArtPrecache` hook
line removed. Same `perf4_run.sh` drive, `CPUS=1.5`, but `CPUSET=40-47`: the default `0-4` is where
every other agent's container lands on the new host too, and the first before run there
(`p42_b1_wil`, discarded) ran at p50 797 ms with `present` at 186 ms on average. Runs alternated
before/after, one at a time, while the host load rose from 0.4 to 18:

| run | build | car artwork costs >= 4 ms | of them in a frame over 33 ms | worst | frame cost p50 / p99 ms | frames over 33 ms |
|---|---|---|---|---|---|---|
| `p42_b2_wil` | before | 0 | 0 | - | 8.2 / 78.8 | 238 of 2757 |
| `p42_a1_wil` | PERF-4 | 0 | 0 | - | 12.0 / 86.4 | 488 of 2739 |
| `p42_b3_wil` | before | 0 | 0 | - | 14.8 / 97.1 | 619 of 2769 |
| `p42_b4_wil` | before | **3** | **3** | 50.5 ms | 20.0 / 98.8 | 710 of 2374 |
| `p42_a3_wil` | PERF-4 | 0 | 0 | - | 21.8 / 102.9 | 931 of 2744 |

`p42_a2_wil` never started (black screen, no DLL log: a hang before the DLL loaded, not the change).
In `p42_b2_wil` the driver lost its car and warped, and every run took its own route, so the
frame-cost columns follow the route and the rising load, not the build. On a quiet host the old
render-thread path rarely passes the log thresholds (8 ms car bodies, 4 ms shells): 0 in two of
three before runs. Once the host is loaded it does: 3 fetches of 37-51 ms (`p42_b4_wil`), each in a
frame over 33 ms. Across both series the before runs had 8, 0, 0 and 3 such costs; the after runs
had 0, 0 and 0. The precache was the same in both after runs: 656 frames in 4.6-4.7 s, uploads at
0.04 ms on average, and one upload of 19.6-19.7 ms, the session's first dynamic texture, at level
load. Patched frames during the drive were made on the worker in 0.2 ms and uploaded in 0.01-0.03
ms, 0-34 ms after they were asked for (1-2 draws with a stand-in). Third-person frames of the after
runs show the cars in their paint (`out/p42_a3_wil/shot_085.png`).

Still open: pedestrians' and objects' new sprite frames are still built on the render thread and
would take the same worker (recognition by the ped remap palettes); Remix's handling of the dynamic
car textures is untested.

## Traffic and pedestrian density in the street views (9 Nov 2026, QB-9-DENSITY)

QB-9 ("boulevards nearly empty", no driven car past the busiest Downtown kerb in 150 s) and the
people half of QB-42. Code: `dll/src/density.cpp` (hooked from `WorldView::MatchGameViewToFrame`),
ini `[density]`, report `tools/density_report.py`, scenario `linux/docker/keys_qb9_density2.sh`
(Downtown start, third person standing 30 s, then `drive_road.py`: classic, third, first, classic).
Same DLL before and after: `GTA2DX9_DENSITY=0` turns everything off.

**Why the streets were empty.** The street views scale the game's spawn window 2.6x and make it
square (PLAY-PERF above), but gta2.exe's budgets stayed sized for the top-down screen (names from
the CriminalRETeam/gta2_re 10.5 reimplementation, each site checked byte for byte in 9.6):

- Ambient ("recycled") traffic is capped at **16 cars** (imm8 compares at 0x420C9F (< 15),
  0x420D3F (< 16), 0x4B34FE and 0x4B4A88 (== 16)). While driving, the census sat at 16/16.
- A pedestrian is placed only while the window holds fewer than **zone ped_density / 25** people
  (0x441042: `imul 0x51EB851F; sar edx,3`; Downtown 200 -> 8) and fewer than **50** dummies exist
  (PedManager+0 at [0x5E5BC0]).
- The traffic spawner takes its car density from the zone **the player stands in**, not the road
  (TrafficSpawner field_10_zone). Downtown's script sets the church-plaza start zone to 0 cars, so
  on foot there the spawner never ran (pacing threshold stuck at its reset 1000) and ambient
  traffic was 0-1 for the whole stand, on every road in view.

**What changed (street views only; the classic view gets every byte back).** Traffic cap 36
(`traffic_cap`), ped divisor 25 -> 6.25 (`ped_density_scale=4`), dummy cap 80 (`ped_cap`), and a
zone the player stands in with 0 cars gets 400 (`zone_car_density`; each spawn point still checks
its own zone and needs an arrowed lane). Two guards: the ped pool (200, and gta2.exe's
`Pool::Allocate` does not check for empty) must keep 40 free or the game's budgets return; and the
budgets come in four levels, stock to configured, that follow the frame rate (over 15% of frames
later than 1.15 periods in 2 s: down a level; under 5% for two windows: up).

**Census** (`density:` log line every 300 frames; ranges over the segment):

| | before (`qb9_b3`, `qb9_b4`) | after, full budgets (`qb9_a3`, `qb9_a4`, `qb9_a5`) |
|---|---|---|
| on foot, plaza, third person: ambient traffic | 1 | 14-18 (zone fill) |
| driving, street views: ambient traffic / cap | 16 / 16 | 36 / 36 |
| driving: driven cars within 16 blocks (census samples) | 3-14, median 9 (`qb9_before2`, `qb9_b3`) | 2-23, median 16 (`qb9_after1`, `qb9_a3`) |
| people in the game's window | 4-17 | 18-35 |
| ped pool free at peak | 184+ | 153+ (of 200) |
| classic view after a street view | stock caps (16, 50, /25) | same: caps back to 16, 50, /25 |

No `FAULT` in any run.

**Frame cost** (`tools/density_report.py`, per-frame log; work = whole - wait, ms). The host was
shared with 20-odd agents: load 10-40 across these runs, and the CPU governor paused containers
mid-run, so the classic segments (identical code in both builds) are the yardstick for load.

| segment | before `qb9_b4` (load ~10) | after full `qb9_a5` (load ~13) |
|---|---|---|
| classic on foot, work med/p95 | 2.7 / 15.0 | 3.3 / 12.9 |
| third person driving, work med/p95, frames > 33 ms | 8.7 / 50.8, 7.8% | 13.8 / 69.3, 15.4% |
| first person driving, work med/p95, frames > 33 ms | 9.3 / 35.0, 5.5% | 21.8 / 65.0, 25.0% |
| skinned figures a frame (third / first, driving) | 2.1 / 3.4 | 10.3 / 10.7 |
| draw calls a frame (third, driving) | 1282 | 1399 |
| ped stage median (third on foot) | 1.4 | 5.5 |

The full budgets do cost frame time - mostly posing and drawing four times the people - which is
why the levels follow the frame rate. In `qb9_a6` (load ~20, where even the classic view had 13%
of frames over 33 ms) the controller went 3 -> 0 in three windows (83-100% late) and the street
views ran at the game's own budgets. On this shared host the game's own budgets already run a
median 8.6% late frames per 2 s window in the street views, which is why the band is 5-15%.

Not done / untested: QB-45 (street clutter between the rule-placed props) is untouched - it needs
new clutter models and edits to the prop rules in `live_geometry.cpp`. QB-42's pop-in is unchanged
by this (cars still come into being 20-26 blocks out, in the haze). Not tested in Residential or
Industrial, under Remix, in the play container (dedicated CPUs, where the controller should hold
a higher level), or at high wanted levels (the game halves the dummy cap above three stars and the
pool guard covers police and roadblocks, but no run reached them).

**Crash fix (CRASH-BISECT, 9 Nov):** `gta2.exe+0x25486` reading `0x4C` (MISSIONS-BATCH2 GANG CAR BANG
in Residential, 2 of 2 sessions; FIX-CAR-RENDER once) came from this change. Two of the four traffic
sites, SpawnTrafficCar `0x4B34FC` and MakeTrafficForCurrCamera `0x4B4A86`, are `cmp count,cap; je`:
equality, not `<`. When the level stepped down (36 -> 22 -> 16) with more cars alive than the new
cap, or the view went back to classic, the count never met the cap again and ambient traffic grew
without limit (census: 36/36, then 59/16, 90/16, 148/16, 160/16) until the vehicle pool (`Pool<Car,
306>` at `[0x5E4CA0]`, free list through `+0x4C`, Allocate `0x425480` unchecked) ran dry. Now the
written cap never goes below the live recycled count (the stock byte goes back only once the surplus
has drained to 16), and a vehicle-pool guard joins the ped one: under 40 of 306 free, the game's
own budgets until over 60 are free. The census line gains `free_cars=`.

## Sprite stage 2.6 -> 7.7 ms on the Residential cab drive (9 Nov 2026, PERF-BISECT)

FIX-FIGURE measured the sprite stage of `gamerun/keys_ff_cab.sh` (Residential, forced taxi) at
2.6 ms on a81174f and 7.7 ms on bc4f494, in every view (car-3d-pipeline.md, FIX-FIGURE). That
pair compared more than code. What was found, and the one code cause, fixed:

**How it was measured.** Every DLL in the range was built in a private worktree and swapped into
one private copy of the stage, so models, tiles and ini were the same for all of them. The drive
was `gamerun/keys_pb_cab.sh` (`SWAP_LEVEL=ste`, `force_own_car_model=56`, GPU 3, `FPS=0`, fps cap
30, `GTA2_DIRECT_KEYS=1`), with `GTA2DX9_FRAME_LOG` for the sprite stage's sub-stages a frame
(`setup loop skid issue cars props objects peds effects`; the stage total is `whole` minus the
other columns). `keys_pb_cab.sh` is `keys_ff_cab.sh` with a fixed car entry. In `keys_ff_cab.sh`,
F10 races the last Return of `to_level.sh`, the one that walks the player into the spawn car. If
F10 lands first, the scene key moves him on foot to `scene_xy` (164.5,149.5), and the run films a
standing scene, not a drive. That happened in about half the runs; FIX-FIGURE's base run drove
382 of its 391 state samples, the tip runs 115. The copy drops F10 and waits for `driving` in the
log, tapping Return again if needed.

**What differed between the two measurements.**

1. *Not the same stage.* a81174f is not on camera-modes. It is on `anim-audit-on-camera-modes`,
   two commits above 16fcaf8, and its run used that agent's stage: 1895 model files, no
   `[density]` block, `[visuals] enabled=0`. The tip runs used a copy of `repo/stage`. There,
   `restage.sh` (`tools/merge_stage_ini.py`) keeps the stage's own override `[visuals] enabled=1`,
   although the committed `package/gta2dx9.ini` says 0. The same a81174f DLL measured 3.6 ms on the
   old stage and 4.2 ms on today's.
2. *[visuals] post: about 1.2 ms.* `EndWorldShading` -> `post_.Resolve()` runs inside the sprite
   stage, after the last sub-stage mark. With visuals on, the sub-stages add up to 1.0-1.3 ms less
   than the stage total; with `enabled=0` they add up to it (9.13 vs 9.23 ms).
3. *QB-9 density (above), on camera-modes since 3ab8cfe:* about twice the live pedestrians (the
   `view: peds` census: about 30 with 16fcaf8/a81174f, 62-66 with bc4f494, same ini; older DLLs
   ignore `[density]`) and up to 36 ambient cars. The peds sub-stage follows the skinned count
   (posing). Cost per figure is unchanged, so this is the cost the QB-9 section already reports.
4. *The code regression: c2bdb0c's prop overlap fade, +1.7 to +2.0 ms.* Props sub-stage, first
   person, median / 10th percentile:

   | build (today's stage) | props ms |
   |---|---|
   | 16fcaf8 | 0.88 / 0.81 |
   | 47c8641 (c2bdb0c's parent) | 0.90 / 0.80 |
   | c2bdb0c | 2.88 / 2.61 |
   | bc4f494 | 2.68 / 1.56 |
   | bc4f494, `GTA2DX9_PROP_OVERLAP_FADE=0` | 0.94 / 0.81 |

   Prop draw counts are unchanged (`props drawn:` about 230-260 draws a frame either way), so the
   cost is CPU work in `LiveGeometry::DrawProps`. The new `overlapAlpha` runs for every prop in
   range (about 190) against every figure spot of two frames (`g_figuresNow` + `g_figuresLast`,
   which doubled with QB-9) and every car rectangle, each test a `std::hypot`. It also ran before
   the frustum cull, so props beside the picture paid for it too. That is tens of thousands of
   hypot calls a frame, and slow ones in this mingw/Wine build: about 2 ms.

**Fix (PERF-BISECT, `live_geometry.cpp`, `DrawProps`).** Each overlap test now rejects on a
squared distance (eye: r + 0.5, a person: r + 0.3) or on one axis (car rectangle: r + 0.15), the
reach past which its `smooth01` is already 1. The hypot runs only for the few close pairs. The
overlap test also moved after the frustum cull. The fade's output is unchanged: the skipped cases
returned exactly 1, and a prop outside the frustum is not drawn either way. The `hidden` count in
the `props: overlap fade` line now counts props in the picture only. The classic view never runs
`DrawProps`.

Same drive (`keys_pb_cab.sh`), today's stage, first person, unfixed tip d2bbf01 vs the fix:

| run | props median / mean | sprite stage avg (`frame times`) |
|---|---|---|
| d2bbf01 det1 / det2 | 2.66 / 3.51, 2.86 / 4.18 | 14.3, 16.5 |
| fix det1 / det2 | 1.07 / 1.42, 0.97 / 1.45 | 10.3, 12.4 |

The fade's cost grows with the crowd. With the old stage's settings (`[visuals] enabled=0`,
`GTA2DX9_DENSITY=0`), the unfixed tip's props median is 1.36 ms and the fix's 0.81 ms.

**Where the drive stands.** Same drive, first-person median / whole-run average of the sprite
stage:

| build, stage settings | sprite stage |
|---|---|
| a81174f on its own stage (visuals off, no density): FIX-FIGURE's 2.6 ms baseline | 2.18 / 3.29 |
| 16fcaf8 on today's stage (visuals on; this DLL predates density) | 2.81 / 4.57 |
| fixed tip, visuals off, `GTA2DX9_DENSITY=0` | 3.47 / 4.66 |
| unfixed tip d2bbf01, same | 3.37 / 4.93 |
| fixed tip, today's stage (visuals on, QB-9 density) | 8.4-9.2 / 10.3-12.4 |
| unfixed tip, today's stage | 10.8-12.3 / 14.3-16.5 |

So the code regression in FIX-FIGURE's range is gone. Under the old settings the fixed tip is
within about 1.3 ms of the a81174f-era stage. That remainder is spread over today's assets and
later features (more prop models: props 0.94 vs 0.66 ms; zoned avatars: peds cost more per
figure), not one cause. On today's stage most of the sprite stage is the crowd and traffic QB-9
asked for (peds 2-4 ms, and the cars sub-stage 2-6 ms while driving among up to 36 ambient cars)
plus the 1.2 ms visuals post. Both are deliberate, and the density controller steps the budget
down when frames run late. Whether the shared stage should keep `[visuals] enabled=1` while the
committed ini says 0 is for the visuals and play-page owners to decide. Anyone comparing frame
times should take both runs from the same stage copy and check `driving` in the log.

Cars: the cars sub-stage at the tip (2-6 ms while driving on today's stage) is traffic, not a
regression after bc4f494. With fixed traffic (visuals off, `GTA2DX9_DENSITY=0`, same drive) it is
1.33 ms at bc4f494 and 0.77-1.12 ms at the tip. The visual-regression capture of the fix
(`tools/vreg/vreg.sh stage`) matches the unfixed tip's: the same `raised_w03_high` FAIL (22 tiles)
and `bank_chase` WARN (8) against the 16fcaf8 goldens, from later visual commits. The fix's one
extra WARN, `spawn_first`, is a passer-by in the shot. Runs: `out/pb_*` (`det` = the
fixed car entry); scripts `gamerun/pb_grun.sh` (grun.sh on `GTA2_GPU`) and
`gamerun/keys_pb_cab.sh`.

## The first V of a session (9 Nov 2026, FIX-PERF-VSWITCH)

Defect `first-v-press-freezes-game-up-to-9s-world-upload`: the first switch from the classic view
to a street view froze the game for 0.5-9 s (`hitch @237: frame 8798 ms, world 7899` in BEV-PURITY's
`bp_a_vis1`). The 8.8 s run was an extreme. The game ran in a 1.5-CPU container next to two
30 fps captures, so frames came in whole 100 ms CPU-quota periods. Even the settled street view
ran at 100-300 ms a frame there. The measurements below use the same keys scripts at `CPUS=3`.

**Where the time went.** Four things, all first uses at the switch:

1. **GL programs.** wined3d builds a GLSL program for each new fixed-function state and for each
   shader the first time a draw uses it. The street views' first frames use about 110 that the
   classic view never does: sky, lit and fogged world, water, post passes, shadows, lit figures,
   tinted paint, sprites under fog. With the NVIDIA shader disk cache warm, HEAD's switch cost
   371 ms instead of 0.8-2.3 s (`vsw_glcb1` vs `vsw_glcb2`).
   `WINEDEBUG=+timestamp,trace+d3d_shader` counts them (`Compiling shader object`).
2. **The model warm-up.** It ran in manifest order (every car texture before any person), so the
   people were still cold at the V: 170-280 ms per avatar on first draw. Its 8 ms budget also
   counted only the time to *queue* uploads, so the driver thread's backlog grew through the
   classic view. Whichever frame next waited on the driver paid for all of it.
3. **The first lock of a new dynamic vertex buffer** (a figure's posed skin) waits for everything
   queued: 285 ms for the first person drawn (`vsw_probe3`, `model first draw:` line).
4. **The modern HUD's setup** (gxt, ImGui fonts, mini-map): 180-590 ms (`ui` in the hitch line),
   and the post targets (~100 ms, `world`).

**What changed.**

- `model_store.cpp`: the warm-up is a list of steps, one model at a time (its textures, then its
  buffers). Order: street furniture and objects, then people (the player's avatar first,
  `ModelsWarmFirst`), then cars. An event query after each batch holds the next batch until the
  driver has finished the last, plus a byte budget (12 MB a frame in classic, 3 MB in a street
  view). 40 spare skin buffers are made and written once after the people (`SkinBufferFor` takes
  any spare at least as large). The reader thread now softens car paint masks. Log lines:
  `models: warm-up: <group> ready, N s after it began`, and `model first draw: <name> ms (pose,
  buffers, new textures)` for any first draw over 4 ms.
- `live_geometry.cpp`: no warm-up step in a street view's first 120 frames. Once a level, on the
  frame after the ghost frame below, the classic frame's sprites are issued a second time under
  the street fog, with colour, depth and stencil writes off (`live: this frame's N sprites issued
  unseen`).
- `hud3d.cpp`: texts, context and fonts, mini-map, font texture and one invisible ImGui frame are
  made in the classic view, one step every other frame from 2 s into a level
  (`hud3d: made ahead in the classic view: step N`).
- `world_view.cpp` / `renderer.cpp`: `GhostStreetFrame`, once a level on its second classic frame
  (inside the level's own loading stall). One street frame is drawn into a render target and
  depth surface of its own, with every device state captured before and applied after: sky,
  street shading, world with its street fill, post passes and shadows, a prop, the avatar (zone
  tints), a car (paint tint). It runs after the classic frame is complete and kept for the
  dissolve. `GTA2DX9_GHOST_FRAME=0` turns it off. `GTA2DX9_GHOST_VERIFY=1` logs how many pixels of
  the presented classic frame differ after it (0 in `vsw_shtrace1`, `vsw_a3c_3`).

**Before and after** (`CPUS=3`, GPU, 30 fps recording; frames of 100 ms or more from the V on):

| run | keys | first-V frames ≥100 ms | level-start stall* |
|---|---|---|---|
| `vsw_b3c_1` HEAD | keys_bevpurity.sh | 486, 717, 1106, 161, 196, 525, 193, 183 ... | 3.95 s |
| `vsw_a3c_5` fix | keys_bevpurity.sh | 110, 467, 367, 105, 130 | 4.42 s |
| `vsw_pt_b` HEAD | keys_pt_pass.sh (V 2.5 s into the level) | 449, 132, 455, 137, 103 | 3.64 s |
| `vsw_pt_a` fix | keys_pt_pass.sh | 274, 225 | 4.56 s |
| `vsw_glcb2` HEAD, driver shader cache warm | keys_bevpurity.sh | 371 | 3.73 s |
| `vsw_glcw_a` fix, driver shader cache warm | keys_bevpurity.sh | none (frames 65-100 ms are frame-cap `wait`) | 3.94 s |

\* The hitch lines' frame times of 50 ms or more in the first 60 frames after the world upload
(`d3d: hd tiles:`), summed. Most of it is the game's own level load (3.1-3.5 s in one frame).

At `CPUS=1.5` (`vsw_before1`, HEAD) the same V cost 4392 + 1002 + 2345 ms.

The 30 fps recording across the V in `keys_pt_pass.sh` holds one picture for 1067 ms with HEAD
and 667 ms with the fix (longest run of identical frames starting during the camera move; part of
the 667 ms may be the dissolve's slowest first frames).

**Classic view.** The ghost frame draws only into its own targets, and the sprite replay writes
no colour, depth or stencil. With `GTA2DX9_GHOST_VERIFY=1` the frame that runs it compares its
back buffer with its own pre-ghost copy: 0 pixels differ. HEAD vs the fix, 40 classic frames
each at the same spot (`keys_bevpurity.sh BP_NOV=1 BP_CLASSIC=8`, `tools/classic_ab.py`):
96.1 % of pixels static in both, 0 differ.

**Still open.**

- With a cold driver shader cache (every scripted run, and a fresh install) about 29 GL programs
  are still built in the first three street frames: 12 byte-identical "sprite under fog" programs
  and 7 "tinted figure under fog" ones. Their keys depend on what is on screen, so a fixed grid
  of states matched only 9 of them (tried and removed). Two to four frames of 200-470 ms remain
  at `CPUS=3`. The play page keeps the driver's cache on the host (`linux/docker/play.sh`), so
  there only the first session after an install pays this. Replaying more of the sprite pass,
  or reusing one cached program for state keys that generate the same GLSL, would close it.
- The ghost frame costs the level start 0.2-0.9 s of driver time (within the 1 s allowed).
- The burst captures (`keys_bevpurity.sh`'s ffv1 recording) make the settled street view itself
  run at 100-200 ms a frame on a 3-CPU container. That is the host, not the switch.

## The jerky demo (9 Nov 2026, FIX-PERF-2, owner blocker)

The owner watched `DEMO_classic_to_3d_realtime_v6` and called it jerky (`demo_v6`: present worst
332 ms, "1284 hitches"). The question was whether the game was ever juddery, or only the recordings.

**Measurement.** `keys_owner_demo.sh` (the owner's content: classic opening, third-person walk, first
person, a punch, a natural jack, chase drive, driver's seat, classic while driving, out, steps),
`--cpus=8` on a CPU set of its own (80-87), GPU 7, 30 fps recording, `GTA2DX9_FRAME_LOG` on.
Frames after the level load (`tools/frame_table.py`). A and B are stage 8297aab; C and E are this
change on 814fa7e.

| run | logging | NV shader cache | frames | `hitch @` lines | frames > 50 ms | > 100 ms | worst | p99 | present avg/worst |
|---|---|---|---|---|---|---|---|---|---|
| `demo_v6` (operator, `--cpus=1.5`) | 3 | cold | - | 1164 | 561\* | 64\* | 1047 | - | -/78 |
| `fperf2_A_log15` | defaults (15/10) | cold | 6944 | 1243 | 55 | 23 | 870 | 41.4 | 1.7/843 |
| `fperf2_B_log3` | 3/3 + ped frames | cold | 6384 | 898 | 57 | 20 | 663 | 46.7 | 1.3/489 |
| `fperf2_C_fix_nv1` | 3/3 + ped frames | warm | 5308 | 893 (old count) | 9 | 5 | 220 | 33.3 | 0.16/154 |
| `fperf2_E_accept` (`rec_grun.sh`) | 3/3 + ped frames | warm | 5585 | **14** | 13 | 5 | 261 | 41.4 | 1.8/253 |
| `fperf2_F_final` (`rec_grun.sh`, its cache's 2nd run, final DLL) | 3/3 + ped frames | warm | 6579 | **8** | **6** | **0** | **99** | 33.3 | 0.3/46 |

\* from the hitch lines (`demo_v6` has no frame log), level-load frame left out.

**Where the judder came from.**

1. **Capture configuration, CPU (most of it for `keys_video.sh` captures).** At `--cpus=1.5` the game
   and the recorder shared one quota: 561 frames over 50 ms in `demo_v6`, 36 in the same script at
   `CPUS=8` (`demo_smooth`, operator 19:25). `grun.sh` defaults to 8 since then.
2. **Capture configuration, shader cache (most of what was left).** The present stalls (the
   wined3d command thread falling behind, `present` waits on it) line up with GL program builds:
   `fperf2_D_trace` (`WINEDEBUG=+timestamp,trace+d3d_shader`, `frame log: t_ms 0 is GetTickCount`
   in gta2dx9.log lines the two clocks up) saw 278 programs in the run, 136 of them in the 10 s
   after the first V. The play page keeps the NVIDIA cache (`play.sh`); scripted captures did not.
   With it kept, 57 -> 9-13 frames over 50 ms and present worst 489-843 -> 154-253 ms.
   `gamerun/rec_grun.sh` is the recording command now (`docs/throughput.md` "Recordings for people").
3. **Instrumentation: not a cause.** Logging at the defaults vs every 3 frames: 55 vs 57 frames over
   50 ms. The "1234 hitches" of `dh_final` counted three breakdown lines per slow sprites stage and
   frames that made their budget (334 frame lines, 47 over 50 ms). Still, `Log()` flushed every line
   with a `write()` on the render thread, so it now hands lines to a writer thread (15 ms; `FAULT`
   lines and call stacks are written at once; `GTA2DX9_LOG_SYNC=1` restores the old way). The
   `log cost` line every 256 frames: `Log()` 0.03 ms a frame on average, the state lines
   (`view: player/peds/cars`, every 3 frames) 0.02-0.11 ms a frame on average, 0.5 ms worst.
   `hitch @N: frame` is now written once per frame that missed its budget; a slow sprites stage
   inside a frame that made it is `slow sprites @N`, and breakdowns are `... detail @N`.
4. **The game (what a player with a warm cache still sees).** In `fperf2_E_accept` (186 s of play):
   - level start, 2 frames of 143 + 158 ms: the ghost street frame (FIX-PERF-VSWITCH), on purpose
     inside the level's own loading stall, right after the 3 s load frame;
   - the first V: 3-4 frames (68, 261, 100 ms): 14-41 new vertex buffers a frame (the cars'
     wheel splits and dented copies registered for the first street frames) and the GL programs
     the ghost frame does not cover;
   - the first frame in the driver's seat: 91-145 ms in `cars` (the hood copy, seat bonnet and cab
     interior of that model built on the render thread, `car bodies: seat bonnet ... 44.8 ms`);
   - the game's own step: 56 and 88 ms once each (`game`, nothing of ours in the frame);
   - 4 single frames of 52-78 ms (`present`).
   With a COLD cache (a first session on a new machine, or a new driver) the first V, first
   person and driver's seat still cost 0.2-0.9 s each: the ghost frame's ~110 programs are a
   fraction of the ~280 a session builds.

**Classic view.** No drawing changed. HEAD (814fa7e) vs this change, 40 classic frames each at the
spawn (`keys_bevpurity.sh BP_NOV=1 BP_CLASSIC=8`, `tools/classic_ab.py`, runs `fperf2_cls_base` /
`fperf2_cls_fix`): 96.4 % of pixels static in both, 0 differ.

**Short of the acceptance** ("no frame over ~50 ms"): the final capture (`fperf2_F_final`, 224 s, the
second run on the recording cache) has 6 frames over 50 ms and none over 100: three at the level start
(54, 54, 86 ms), two game steps (51, 55 ms) and the first frame in the driver's seat (99 ms, `cars` 89).
The first-V cluster of E (68-261 ms) did not recur there, but it depends on how warm the cache is and
on which cars are on screen, so it is not fixed, only less likely. Filed as follow-ups:
wheel-split/dent buffers and seat-view builds made ahead in the classic view or on the wear thread,
and a ghost frame that draws the real street scene (every program the first V needs).

## First-use stalls at the street-view switches (9 Nov 2026, FIX-PERF-3)

Work orders `perf-first-drivers-seat-view-builds-hood-and-seat-bonnet-on-render-thread-145ms` and
`perf-first-v-wheel-split-buffers-and-uncovered-gl-programs-stall-100-260ms`. The owner demo take v3
(`demo_rc3t`, stage afb3cb6, host load ~60) had one 1072 ms frame (`cars` 1043.6) at the first V, a
236/168 ms pair after it, and 184 ms at the first frame in the driver's seat.

**Measurement.** `keys_owner_demo.sh` through `gamerun/rec_grun.sh` (30 fps, `CPUS=8` on cores no other
container was pinned to, GPU 5, a private copy of the warm `nv_cache_rec`), `GTA2DX9_FRAME_LOG`,
`GTA2DX9_STATE_EVERY=3`. Before and after differ only in `gta2dx9.dll` (same stage, ini, keys, cache).
The windows are the 90 frames (3 s) from the first classic -> third switch and from the first switch
to the driver's seat while driving (`view`/`driving` columns of `frames.tsv`).

**Where the time went** (the new `car parts (ms)` hitch-detail line splits the cars stage by part):

1. **The own-paint lock convoy (the 0.9-1.0 s frame).** `ModelOwnPaint` (identity.cpp asks it for every
   car) starts a low-priority thread at the first car that measures every car model's paint (~12 ms
   each). The thread held the lock for the whole of each measurement and took it straight back for the
   next model, so the render thread asking for the second car on screen waited behind all ~80 models:
   `demo_rc3t` f671 (the log shows `own paint measured` for models 000..083 in order inside that frame,
   then the 063 the frame wanted), `fxp3_base1` f624 934 ms. Now the measurement runs outside the lock
   (two threads may measure one model; the first result stored wins, the numbers are the same), and the
   thread starts after 5 s of classic view (`ModelsOwnPaintAhead`, live_geometry's warm-up block), so all
   83 are measured long before a V (`fxp3_fix1`: 000..083 in 0.95 s, 14 s before the first V).
2. **The driver's seat (91-184 ms).** The seat bonnet (`BonnetSurfaceFor`, the clean bonnet seen from the
   seat) took 45-147 ms for the 063 truck cab (most of it reading the body textures for its colours), and
   the hood copy (`HoodModelFor`) ~30 ms, again for each 0.04-block step the eye crossed while it settled
   (six in the first 0.2 s). On the plain renderer the copy is not drawn when the seat bonnet is (nor for a
   flat front's cab): only its dash line is used. Now:
   - the bonnet is built on the wear thread while the player drives in another view (`SeatBonnetAhead`,
     a `bonnet` job; `RgbFor` and `LumaFor` are locked for it), log `seat bonnet of <model> made ahead of
     the seat view (worker N ms, with its texture samples)`;
   - the hood is measured for its dash only (`HoodDashFor`: the same faces, only those in the dash band
     tested; 1.5-1.8 ms), log `hood dash of <model> ... N ms`. Under Remix, or when no bonnet can be made,
     the copy is built and drawn as before. `[devtools] hood_dash=0` restores the copy for A/B checks.
   - Same-cut check (`fxp3_dash1`, `gamerun/keys_fxp3_dash.sh`: seated in the scene car, still, models 63,
     0, 8, 68, `hood_dash` 0/1/0/1): where both ways measured the same cut they agree to three decimals
     (000 Romero y<0.28 z>0.15: top 0.268, x -0.20..0.23; 063 y<0.52 z>0.23: 0.508, x -0.30..0.30), and the
     cockpit third of the frame differs by 0-38 pixels between adjacent 0/1 shots.
3. **Wear copies' buffers.** A dent, wheel or door copy went on screen one copy a frame, but a wheel split
   is a hull and four wheels of up to 21 meshes each (008 Bug): 33-58 vertex buffers in a frame at the
   first V (`demo_rc3t` f673-674, `fxp3_base1` f631). Now a copy (with its siblings) goes on screen once
   all its mesh buffers exist, made at most 4 a frame (`ModelPrepareBuffers`); until then the car is drawn
   as it was (whole, or the previous dent step).

**Before and after** (same session conditions; `python3 tools/frame_table.py out/<run>`):

| run | DLL | frames | > 50 ms | > 100 ms | worst | p99 | cars worst | first V: worst / cars / model buffers max | driver's seat: worst / cars |
|---|---|---|---|---|---|---|---|---|---|
| `demo_rc3t` (DEMO-RECAPTURE-2, load ~60) | stage afb3cb6 | 5212 | 117 | 7 | 1072 | 54.6 | 1043.6 | 1072 / 1043.6 / 40 | 184 / 174.4 |
| `fxp3_base1` (load ~26-30) | 0fcd9d8 | 5736 | 51 | 2 | 934 | 48.9 | 919.4 | 934 / 919.4 / 40 | 155 / 144.0 |
| `fxp3_fix1` (load 47-52 at 70-150 s) | 0fcd9d8 + this | 5369 | 90 | **0** | **61** | 52.3 | **14.6** | **33 / 14.6 / 4** | **33 / 7.5** |
| `fxp3_base2` (load ~40; 240 s limit hit in the drive's last beat) | 0f15f27 | 6881 | 13 | 2 | 1002 | 42.4 | 988.0 | 1002 / 988.0 / 10 | 167 / 156.8 |
| `fxp3_fix2` (load 43-48) | 0f15f27 + this (rebased build) | 6340 | **8** | **0** | **61** | 45.5 | **14.1** | **36 / 13.6 / 4** | **51 / 9.8** |
| `fxp3_fix3` (load 45-71) | 5af1890 + this (rebased build) | 5584 | 109 | **0** | **67** | 52.9 | **24.1** | **61 / 11.6 / 4** | **41 / 9.7** |
| `fxp3_fix4` | 8b61d70 + this | 5699 | **2** | **0** | **52** | 37.0 | **14.1** | **33 / 14.1 / 4** | **33 / 7.1** |
| `fxp3_fix5` (load 50-58) | fb518e1 + this | 5750 | 19 | **0** | **88** | 44.2 | **17.7** | **41 / 14.4 / 4** | **33 / 9.7** |
| `fxp3_fix6` (load 45-53) | 44b3243 + this | 5149 | **2** | **0** | **65** | 39.0 | **13.9** | **37 / 13.9 / 4** | **45 / 9.2** |
| `fxp3_fix7` (the pushed build, load 52-61; 260 s limit hit in the last drive) | 3c87b70 + this | 7385 | 19 | **0** | **83** | 47.4 | **18.5** | **33 / 18.5 / 4** | **46 / 6.5** |

The frames over 50 ms left in the fix runs: at the level start the ghost street frame (FIX-PERF-VSWITCH,
on purpose inside the load stall: 58-61 ms, `present`/`pre`) and the modern HUD's made-ahead steps
(`ui` 41 ms, f135 of `fxp3_fix2`); the rest are single `present` frames of 30-54 ms with nothing created
(`cars` 2-5 ms). In `fxp3_fix1` 90 such frames came in two bursts at 70-90 s and 140-160 s of the take,
the minutes the governor logged load 52 and 47 (`/tmp/gta2-governor.log` 22:20-22:21): host contention,
not the renderer (the same DLL had 8 in `fxp3_fix2`). The 51 ms frame in `fxp3_fix2`'s seat window is one
of those (`present` 36, `cars` 3.9, no texture or buffer created). `fxp3_fix3` ran at load 45-71 (107 of its 109 such
frames in third person at 65-90 s); its 61 ms first-V frame (f655) has 39 ms of the sprites stage outside
every sub-stage mark and nothing created: unexplained, most likely the thread descheduled at that load. `fxp3_fix5`'s 50-88 ms frames are the level start
(ghost frame 71 + 88 ms, inside the load) and frames where every phase grows at once (`game` 24, `world` 21,
`peds` 18 in f1613-1614 at load 57): CPU starvation, not a first use. `fxp3_fix7` (3c87b70) has four first-person frames at 231 s with the
`peds` stage at 36-55 ms and nothing created while `cars` and `world` stay at 2-5 ms: not first use and
not this change's code; left for the pedestrian/first-person owners (no hitch detail that late in the log).

**Against the acceptance.** First V and the first driver's seat: worst frame 33-36 and 33-51 ms (was
934-1072 and 155-184); `cars` worst 14.1-14.6 ms after the load (was 919-1044); car copy buffers at most
4 a frame (was 40). Not met as written: `vb_created` still reaches 30-48 in single frames of the first
V's three seconds. Those are the posed pedestrians' skin buffers (`skin_buffers` column, `SkinBufferFor`:
the crowd's first poses past the 40 spares made in classic), and those frames run at the 33 ms cap, so
they cost nothing visible; more spares would trade 32-bit address space for a counter. `present` under
20 ms holds at the switches except in the contention bursts above.

**Classic view.** Untouched: the only classic-side change starts a CPU thread after 5 s of play. vreg on
the fix stage (`vreg_fxp3_1` against goldens afb3cb6): PASS 31 of 31, `spawn_classic` 0 changed tiles,
2670-5712 pixels from the three goldens (which differ from each other by 1399-7542: the animated street).

**The level-load frame (3.1-3.6 s, investigated, not changed).** `demo_rc3t` f68: 3356 ms = `game` 1321
(GTA2's own level load) + `pre` 1888 (`pre_load`: our world load, which creates 3337 textures in that
frame, `tex_created`: the HD tile set). It is one frame behind the game's own loading screen; moving the
tile creation into play would put it back into the frames this work removed stalls from. The ghost
street frame and the HUD's made-ahead steps follow it within 2 s (above).

**Still open.**
- Skin buffer creation at the first V (above): harmless at the cap, but the first frames still lock 30+
  new dynamic buffers; raising `kSkinSpares` (model_store.cpp) would move them into the classic view.
- A first person entered directly (getting into a car while already in first person) still builds the
  seat bonnet on the render thread (the ahead job starts when the player drives in another view);
  the boarding target could queue it.
- With a cold NVIDIA shader cache the GL program builds of FIX-PERF-2's notes remain (not measured here;
  every run above used the warm recording cache).

## Into the driver's seat: the first entry's black frames (10 Nov 2026, FIX-SEAT-ENTRY-2)

Work order `fp-first-entry-per-car-two-black-frames-seat-roof-cut-a-frame-late` (MAJOR; pfeel41 folded in).
On 126258a the first V into the 068 van's driver's seat showed 3-9 frames of a black screen or a tan
headliner over black (triage `tri6_cam6` f75-77; `seat2_van2` f87-95 on 4d99b77), then a cut to the cockpit.
Three causes, read from the log lines inside those frames (`GTA2DX9_LOG_CAMERA=1`, `cam: first ... x=`):

1. **The cabin the eye is placed from had no bonnet lift.** The first-person eye comes from last frame's
   `CarBodiesCabin` (deck + 0.62 of the way to the roof). The deck is lifted over the bonnet (QB-5) only when
   the car was drawn from the seat (`use.own`), so the move and its first frames used the chase view's cabin:
   in the van the eye at 0.47, under the dashboard's top (0.506): the dash filled the screen. Now the lift
   applies to the car he drives in every view (`use.own || use.driven`); the eye is at 0.57 from the first
   frame of the move.
2. **The car seen from the seat was chosen a frame late.** The car-body list is collected from the game's
   sprites before the frame's camera update, with the last frame's hidden objects, while the draw uses this
   frame's eye: the frame the move arrived drew the van whole round an eye already in the seat. `own` is now
   refreshed at draw time (live_geometry, just before `CarBodiesDraw`). The other way (V out of the seat), the
   car stays drawn from the seat while the moving eye is still inside its footprint and under its roof
   (world_view `ApplyPresentation`, `seatHeld`).
3. **The first seat frame built the cab on the render thread** (213 ms: cab interior 170, hood 28, run
   `seat2_van2`). While the camera moves down into the seat (`SeatMoveEye`, the move's destination) the seat
   view's parts are made ahead once per model: the hood dash (or copy) and one unseen cab draw (colour and
   depth writes off, `CabInteriorParams::warm`: no HUD band or wheel state kept), which loads the hands' model
   and has the cab's states compiled. Log `car bodies: seat move: the seat view of <model> made ahead (hood N
   ms, cab N ms)`. Plain renderer only (Remix would capture the unseen draw).

Result (`seat2_van5`, 30 fps, keys_cam6 `CAM6_SEGS=vpress`, load ~45): the van's first entry goes from the
chase view over the roof straight to the cockpit (f83 -> f84), lowest luma around the press 83, the
arrival frame 33 ms; the warm-up costs one 101 ms frame at the move's second frame (the camera is high over
the car then). The V out rises over the roof with no dark frame. Also: the steering rim (and so the hands)
follows the steer through a 0.035 rad dead band, eased over 0.12 s (pfeel41's grip swapping on a straight
road).

## The Remix freeze at the level start, and the stall dump (10 Nov 2026, FIX-DEADLOCK-1)

Defect `remix-ste-start-game-thread-heap-deadlock-freeze`: in Remix sessions the game thread stops for good
a few seconds into the level, and the stall sampler repeats one stack until the run ends.

What the stack is (Wine 10.0 builtins of `gta2-remix-gpu2`, symbolised with `i686-w64-mingw32-nm` and
`objdump -d` on `/opt/wine/lib/wine/i386-windows/ntdll.dll`): the pc `ntdll.dll+0x34288` is not a wait.
It is the `pause; lock cmpxchg` loop of `RtlWakeAddressAll`, spinning on the per-bucket spin lock of
Wine's futex queue (`futex_queues[(addr >> 4) & 255]`: a list head and a LONG lock, waiters' entries
`{next, prev, addr, tid}` on their own stacks). The game thread reached it from `free()` (msvcrt
`_free` < `RtlFreeHeap`), after `operator delete` in whatever DLL code freed memory at that moment
(`gta2dx9.dll+0x1AA762` on 126258a is the return after `operator delete` in `LightsReconcile`;
`+0x30962D` and `+0x303C84` are stale stack words, not return addresses). A spin lock has no owner
field, and the thread that took it never let it go.

It is older than 126258a: the same pc, from different `free()` call sites (`gta2dx9.dll+0x148302`,
`+0x14E2F2`, `+0x169F2A`, `+0x182EC2`, `+0x18B0E2`, `+0x18D592`, `+0x1C05CE`), froze nine earlier Remix
runs for good, the first on 9 Nov 14:25 (`grep -l "at ntdll.dll+0x34288" out/*/gta2dx9.log`). Every one
has the Remix bridge client (`d3d9.dll+0x1A85B`) on the game thread's stack. The bridge client calls
`SuspendThread` only through Detours' `DetourUpdateThread`, and every call passes `GetCurrentThread()`
(`d3d9.dll+0x16E60`), so the bridge suspends no other thread.

The stall dump (`dll/src/thread_watch.cpp`): when the sampler finds the game thread at one address for
5 s it writes, once per stall and at most three times a session:
- `stall dump: lock ...`: every critical section on the game thread's stack, with its owner thread
  (named) and recursion;
- `stall dump: thread ...`: every thread of the process, with its name (`NameThisThread`: log writer,
  stall sampler, wear, cache warmup, car art, model prefetch, own paint, car glass build), its start
  address, its registers and its stack as module+offset. Each thread is suspended only while its
  registers and stack words are copied into static memory, and is resumed before anything is
  formatted, logged or allocated;
- `stall dump: ecx ... reads -1`: when the game thread spins, the bucket it spins on and the waiters
  queued there (tid, address);
- `stall sampler: guarded fault N`: one line per fault a `GTA2_TRY` guard swallowed (thread,
  module+offset), always on. The guard's vectored handler runs before Wine's own `__TRY` handlers and
  resumes the thread at the guard, so a fault inside system code that holds a lock (a spin lock, a
  heap lock) leaves that lock held for good.

Proof that it works: `[devtools] stall_dump_test=1` (off by default) makes a test thread hold a critical
section for 10 s while the game thread waits for it. The plain run (`fdl1_dumptest`) logged
`lock on the game thread's stack (word 30) at 759EB364: owner thread 636 (stall-dump test)` and all 15
threads by name.

Five Remix ste sessions with the dump in place (the filer's command on GPU 6, `fdl1_rx1` .. `fdl1_rx5`,
build e6d2f29 on c4fc56a): no freeze, no stall dump, 0 FAULT; each ran 430-460 s past the level start
through the classic, third and first person views and the two warps. The only swallowed faults were
three in our own `ReadDword` probe at start-up. Nothing here proves the freeze gone: since 9 Nov 14:00
it hit about 9 of 200 Remix runs whose log was kept (none of about 113 before), so five clean sessions
are what one would expect either way. The next freeze writes the dump; read it like this:
- a `futex entry` list and an `ecx ... reads -1` line: the bucket the game thread spins on;
- a thread whose pc is inside `RtlWaitOnAddress` / `RtlWakeAddress*` (ntdll `+0x33F80`..`+0x34500` on
  the Wine 10.0 of `gta2-remix-gpu2`) is the holder; its ebp chain names the caller;
- no thread there and a `guarded fault` in ntdll just before: a guard resumed a thread out of the
  futex code and left the lock held;
- neither: the lock word was overwritten (a stray write), look at the `wear`/`own paint`/job threads.
What the game thread was doing: in our DLL the only path to `RtlWakeAddressAll` is libstdc++'s
static-local guard (`__cxa_guard_release` -> `__gthr_win32_cond_broadcast` -> `WakeAllConditionVariable`,
84 guarded statics); the bridge's SRW lock releases are the other way in. The bridge client starts no
thread of its own (it imports neither `CreateThread` nor `_beginthreadex`).
Classic unchanged: `tools/vreg/vreg.sh stage` on the same stage (`vreg_fdl1_a`): `spawn_classic` PASS with 0
changed tiles. The one FAIL (`yakuza1_street`) is the window panes reflecting the sky (3131445), not this change.

## Memory growth and the bad_alloc crash (10 Nov 2026, FIX-PERF-4)

QA-STRESS filed two symptoms of one problem: gta2.exe's resident memory climbing ~10 MB/min in the street
views while the managed pool line stayed flat, and a silent `std::bad_alloc` exit after 21.5 min of rapid
V switching at Industrial. gta2.exe is a 32-bit large-address-aware process: what runs out is the
**4 GB address space** (Linux VSZ), not RAM. RSS is only a proxy.

### The counters (`dll/src/mem_stats.cpp`)

- The DLL's own `operator new`/`delete` are replaced: every C++ allocation of the DLL is counted (live
  bytes, live blocks, peak, allocations so far; a 16-byte size header per block).
- `mem: minute ...` once a minute: the heap counters, a `VirtualQuery` survey of the address space
  (`va commit private/mapped/image`, `reserved`, `free`, `largest_free`: what Wine itself manages) and the
  process's `VmPeak/VmSize/VmRSS/RssAnon/RssFile` in MB from `/proc/<pid>/status` (Wine opens files in the
  wineserver, so `Z:\proc\self` is the server; the game's own entry is found by its `comm`). Under Wine the
  survey's `free` counts the host's own mappings (GL driver, PulseAudio, Mesa) as free: **VmSize is the
  number that hits 4096**.
- `mem: caches ...` after each minute line: every module's caches as `name=entries[/MB]` (`ms.*`
  model_store: models with their CPU mesh bytes, rigid buffers with their D3D sizes, the pose cache, model
  textures with their sizes; `cb.*` car_bodies: dents/doors/wheels with bytes, per-car maps; `ts.*`
  texture_store; `lg.*` live_geometry; `rd.*` ragdoll; `vf.*` vehicle_fx; `cg.*` car_glass; `mo.*`
  map_objects).
- `mem: view A->B #n` at each view change (heap counters; the full line every 32nd change) and
  `mem: startup ...` / `mem: level load: ...` around the model load and each level-load step.
- `GTA2DX9_MEM_LOG=0` turns the periodic and per-view lines off.
- **An allocation that fails** no longer ends the process silently: a 24 MB reserve taken at the top of
  the address space on the first frame is released, a `FAULT: allocation of N bytes failed` line and the
  counters are logged, and the view is dropped to classic and held there
  (`FAULT: memory emergency: the street views are off for the rest of the session`). An exception that
  still escapes is logged by FIX-STABILITY-1's handler (`docs/stability.md`), which then calls this one:
  a `mem: at std::terminate` line with the counters follows its FAULT line.

### Where the address space goes (Industrial, rapid V switching, before any fix)

Run `fp4_sw_base` (the filer's `keys_qa_stress2_switch.sh` at bil, private stage = HEAD cfff2b6 + the
counters, plain GL, 30 fps). VSZ/RSS in MB per minute (`out/fp4_sw_base_mem.txt`):
3134/2199 (1), 3506/2513 (2), 3627/2614 (4), 3824/2741 (6), 3882/2792 (10), 3939/2847 (13),
3956/2860 (16), 3964/2875 (18). At minute 17 a dynamic vertex buffer `Lock` in `vehicle_fx`
returned success with a null pointer (wined3d could not map it) and `memcpy` faulted
(`FAULT: code C0000005 ... msvcrt.dll`, the stack in `VehicleFxDraw` -> `Flush`); the game hung
after it. The same death as the filer's bad_alloc, 4 minutes earlier.

The address space at minute 7 (`/proc/<pid>/maps`, 3831 MB in all):

| What | MB |
|---|---|
| Wine's views (`rwxp` anonymous: everything Windows-side allocated, incl. our heap and wined3d's copies) | 2171 |
| host heap (`rw-p` anonymous: the NVIDIA driver's and glibc's own allocations) | 538 |
| `/dev/nvidiactl` mappings | 296 |
| PulseAudio shared memory pools (4 x 64 MB) | 256 |
| Mesa `libLLVM` / `libgallium` / lavapipe (loaded into the game process, never used for drawing) | ~200 |
| libraries, NVIDIA compiler, the rest | ~370 |

Of the 2.17 GB Windows side, **our C++ heap was 1.22 GB**, and 473 MB of it were held before the first
model was read (`mem: startup: before the models ... heap live=473.0MB blocks=1255`): the upstream
voice-over feature read all 1 235 WAV files of `gta2dx9_voice` into memory at start and kept them for the
session. The models read at start-up add 313 MB (280 models, 99.5 MB of meshes plus their tables), the
level load (style, map, world mesh, camera collision) ~110 MB, and the first minutes of play the rest
as cars and people are seen for the first time.

What kept growing after the warm-up (minute 6 -> 16, `mem: caches`): the model store's derived car
copies. A car model's dent steps (4 whole copies, queued ahead up to 160 MB), its door splits (body +
door, per side) and its wheel split (hull + up to 4 wheels + 4 rims) are each a whole copy of the mesh,
and a dented copy gets door and wheel splits of its own: `ms.models` 739 -> 820 (+53 MB of meshes),
`ms.buffers` +28 MB, doors 29 -> 41, wheels 42 -> 49. The managed texture pool barely moved (+4.6 MB).

### The fix (step 1): the voice clips, a ceiling watchdog, the dent budget

- **Voice-over clips are read when played** (`voice_over.cpp`): the 1 235 files are listed at start
  (`voice: 1235 recordings found (each read from disk when it is played)`), a clip is read and
  volume-scaled when its text first shows, and the last two played are kept for `PlaySound`. 473 MB of
  the address space back; a clip costs one file read (0.4 MB on average) at the moment it plays.
- **Ahead-of-need dent copies** are capped at 48 MB (was 160 MB): ~100 MB of copies were made in the first
  minutes, most never shown. A model past the budget gets its dent step built when one of its cars is
  first dented; the previous step shows for the frames the worker takes (as for any urgent copy before).
- **Ceiling watchdog** (`mem_stats.cpp`): every 5 s the process's VmSize is read; at
  `GTA2DX9_MEM_CEILING_MB` (default 3900; 0 turns it off) a `FAULT: memory ceiling` line is logged and
  the memory emergency above holds the classic view, because wined3d answers a map it cannot back with a
  null pointer long before any allocation of ours fails (without /proc, as on Windows: when less than
  96 MB of the address space is free). The `vehicle_fx` buffer `Lock` that faulted now checks the pointer.

Same scenario as `fp4_sw_base`, build with the fix (`fp4_sw_fix1`, Industrial, V every 0.35 s, 20 min,
27 laps as before, 0 FAULT, `gta2.exe exited 0`), VSZ/RSS MB per minute (`out/fp4_sw_fix1_mem.txt`):

| minute | 1 | 2 | 4 | 6 | 8 | 10 | 13 | 16 | 18 | 21 |
|---|---|---|---|---|---|---|---|---|---|---|
| before: VSZ | 3134 | 3506 | 3627 | 3824 | 3847 | 3882 | 3939 | 3956 | 3964 (dead since 17) | - |
| after: VSZ | 2663 | 2996 | 3089 | 3124 | 3295 | 3339 | 3345 | 3382 | 3402 | 3418 |
| after: RSS | 1731 | 2009 | 2089 | 2132 | 2231 | 2258 | 2264 | 2292 | 2317 | 2335 |
| after: our heap | 528 | 585 | 638 | 675 | 698 | 701 | 705 | 723 | 747 | 754 |

What is **still not flat**: from minute 8 to 21, VSZ +8.2 MB/min, RSS +7.3 MB/min, our heap +4.3 MB/min.
Per-V allocations are not it (the heap's block count is the same before and after a burst of switches);
it is content seen for the first time: a car model's undented door splits (`cb.doors` 26 -> 33 in
minutes 8-15, ~1.2 MB each plus their buffers), new car and figure models, and the sprite store's new
frames (`ts.frames` +37 a minute, bounded at 8192). Each of these caches is bounded by the district's
car set (wheel splits 64 MB, dented-copy door splits 64 MB, ahead dents 48 MB), so the curve must bend
over, but a 60-minute session has not been run. The next step is an eviction of derived car copies
that have not been drawn for a while (the store never frees a model today: pointers to models and
meshes key the glass, buffer and wear caches).

### Frames over 50 ms in the street views: where the submission goes (FIX-PERF-4, measurement)

QA-STRESS filed 3-11 % of third/first-person frames over 50 ms, with the stall in the `sky` phase and
~2.1 M triangles / ~2 900 draws a frame against classic's 0.5 M / 1 200. The per-stage counts (`dr_*`,
`pr_*` in the frame log) on a steady third-person soak at Industrial (`fp4_third1`, the filer's
`keys_qa_stress3_third.sh`, GPU 1, FPS=0), mean per third-person frame after the warm-up:

| stage | draws | triangles |
|---|---|---|
| world (`DrawWorld`: one batch per tile texture over the whole map, plus the eye caps) | 1 371 | 627 k |
| **shadow pass** (`PostFx::Resolve` inside `EndWorldShading`: world chunks per cascade + the recorded casters; booked to `ui` because it runs after the sprites stage) | 874 | 918 k |
| cars | 264 | 275 k |
| props | 265 | 118 k |
| peds | 61 | 136 k |
| map objects, effects, the game's quads, sky | ~40 | ~3 k |

Over the whole soak (32 053 third-person frames after the warm-up, GPU 1, host load 37-56 on 96 CPUs):
avg 35.8 ms, p99 62.6 ms, 4.0 % over 50 ms, 49 over 100 ms; the classic frames of the same run
(1 399) avg 33.3, p99 33.3, 0.07 % over 50 ms. The order's target (p99 under 50 ms, under 1 % over
50 ms) is **not met**; nothing in this pass changes the submission. The frames over 50 ms (5.5 % of
7 923 third-person frames in the first part of the soak) follow a frame
whose shadow pass redrew the far cascade (staggered: on alternate frames): the frame before a slow one
submitted 1 226 k shadow triangles against 920 k on average. In the slow frame the time is in `sky`
(21.2 ms against 2.3 ms in a fast frame: `BeginFrame`'s Clear is the first call that waits for the
previous frame's commands), `cars` (15.7 against 3.8 ms) and `peds` (8.7 against 3.0 ms; both lock
dynamic buffers). `top -H` in the container during the soak: the game thread at 97 % of a core and
**wined3d's command-stream thread at 95 %**. The GPU is not the limit. The limit is wined3d turning about 2 900
draws and their state changes a frame into GL on one thread. The triangle count matters much less than
the call count.

So a cut has to remove D3D calls, not triangles: merged draws of same-texture props and parked cars,
instanced figures, fewer shadow casters (the far cascade's caster replay), and the world's 1 371 batch
draws. None of these is in this pass: each changes how a frame is built, and needs fixed-pose A/B
frames (`GTA2DX9_REGRESS_CAM`) to show it changes nothing visible.

### Steady third person, and what a level restart costs

The same build on the filer's steady third-person soak at Industrial (`fp4_third1`, no V presses,
39 walk/drive laps, `out/fp4_third1_mem.txt`), VSZ/RSS MB: 2657/1722 (1), 3046/2039 (3), 3117/2110 (5),
3306/2231 (8), 3333/2262 (10), 3352/2275 (12), 3357/2293 (15), 3387/2316 (18). Minute 8 -> 18:
VSZ +8.1 MB/min, RSS +8.5 MB/min, our heap +6.3 MB/min (698 -> 761 MB). The switching run grows at the same rate,
so the remaining growth comes from content seen for the first time, not from view switches. Not flat; not READY.

At minute 18 the player lost the level (`level ended: releasing the world mesh`) and the runner
started it again. Our heap was the same afterwards (779 -> 784 MB) and Wine's commit + reserve too
(2 451 -> 2 439 MB), but VSZ went 3 387 -> 3 623 MB: about **240 MB of host-side mappings per level
load** (the GL driver's for the world's re-created vertex buffers and textures; wined3d released them).
A session with three or four level restarts reaches the ceiling watchdog on that alone. Not addressed
here. Keeping the world's GPU resources across a reload of the same district would avoid it.

## The 32-bit address space on the owner's box, and the paced warm-up (10 Nov 2026, FIX-PERF-5)

The operator's measurement on the RTX 5090 (HEAD 16c259ac, 11 minutes of play): the process at 1 988 of
~2 048 MB, `largest_free=8.8MB`, 5 738 regions; `ms.textures=1237/507.2MB`, `ms.models=525/228.8MB`,
`ms.buffers=2277/129.6MB`, `cb.wear=0/68.1MB`, `cb.dents=52/45.6MB`. Two findings change how to read
that list, and one change takes ~400-600 MB of it out of the process. (The warm-up order, board 0c, follows.)

### What `ms.textures` counts: every model texture lived twice in the process

`ms.textures` is the size of the model store's textures, not of a CPU copy. But they were made in
`D3DPOOL_MANAGED`, and in the managed pool both wined3d and the RTX Remix bridge client keep a CPU copy of
every texture **inside the 32-bit process**. Measured with the `mem:` lines, which put our own C++ heap
apart from the address-space survey: in a plain run (`cab3_bus2`, minute 0 -> 1) `ms.textures` went
0 -> 502 MB while the private commit grew 538 -> 1 301 MB and our heap stayed flat (426 -> 425 MB);
under Remix (`fs2_rmx_night`, minute 1 -> 2) `ms.textures` 0 -> 501 MB, private 680 -> 1 313 MB, our
heap 452 -> 442 MB. The private commit was the textures' copy (plus the managed buffers', see below).

**The fix** (`model_store.cpp`, `BaseTextureForImpl`): a model texture read from its file is made in
`D3DPOOL_DEFAULT`, filled from a `D3DPOOL_SYSTEMMEM` staging texture (`UpdateTexture`, the plate mips
built on the staging copy), and the staging copy is released at once. Same texels, so the same Remix
hash; the device is never Reset (`docs/stability.md`: no Reset and no teardown), so nothing needs a
re-upload after alt-tab or minimise. The seven places that read a model texture's texels back (the
charred wreck copies, the player's own-figure copies, tints, merged figure pairs, the texture means, the
Remix layer-prim hash, the alpha masks) go through `LockTexels`, which reads the file again for a
GPU-only texture. A car paint half whose mask the renderer softened stays managed (its texels are not
the file's; plain renderer only). `[renderer] model_textures_gpu_only=0` (or `GTA2DX9_TEX_GPU_ONLY=0`)
brings back the managed pool. A new gauge `ms.texgpuonly=N/MB` says how many have no CPU copy.

Results, same keys, Industrial, plain GL (`qa_perf5_t3a`, the filer's steady third-person soak, against
`fp4_third1` of FIX-PERF-4: same scenario, HEAD of that time), private commit / VmSize in MB:

| minute | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| before (fp4_third1): private | 1 398 | 1 483 | 1 518 | 1 564 | 1 580 | 1 603 |
| after (perf5_t3a): private | 965 | 1 089 | 1 122 | 1 151 | 1 192 | 1 228 |
| before: VmSize | 2 792 | 2 996 | 3 061 | 3 096 | 3 117 | 3 269 |
| after: VmSize | 2 389 | 2 628 | 2 657 | 2 686 | 2 731 | 2 904 |
| before: regions | 1 407 | 1 451 | 1 490 | 1 525 | 1 539 | 1 552 |
| after: regions | 892 | 929 | 963 | 993 | 1 021 | 1 056 |

`ms.texgpuonly=1185/396.8MB` of `ms.textures=1398/516.8MB` (the rest: softened paint halves and derived
copies). Under Wine the survey's `largest_free` counts host mappings as free, so it says nothing here; on
Windows it is the number that matters, and every MB the process no longer commits is address space the
heap can grow into.

Under RTX Remix, a strict A/B of one build (Remix bridge under Wine, GPU 2, VEHICLE-GLASS-5's own-car
poses of 071 at 13:00 and 21:00: `perf5_rxa2` GPU-only, `perf5_rxb` with `GTA2DX9_TEX_GPU_ONLY=0`):

| minute | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| managed (rxb): private / regions | 1 217 / 1 216 | 1 306 / 1 232 | 1 386 / 1 271 | 1 442 / 1 285 |
| GPU-only (rxa2): private / regions | 680 / 739 | 746 / 743 | 888 / 805 | 955 / 818 |

537-560 MB less private commit (our heap within 0-33 MB of each other), 400-480 fewer regions: the bridge
client kept a copy of every managed model texture. The frames of the two takes show the same car: 071's
gta2hd PBR coat (the black lacquer, the white stripes, the chrome bumper and the plate) is on in both at
every pose; the pixel differences between them are the camera's small offset and the background traffic
(the two runs' car is placed by the game). A texture the layer keys by hash would come up as matte clay
if its hash had changed (`docs/remix` notes, memory `remix-stale-car-prims`).

### `cb.wear` is a sum, not a pool

`cb.wear=0/68.1MB` was printed with a hard-coded entry count of 0: it is the running total of
`cb.dents` + `cb.doors` + `cb.wheels` (the derived car copies), not a fourth cache holding memory with
nothing in it. And all of those derived copies are registered with the model store, so their bytes are
**also inside `ms.models`**. On the 5090's line `ms.models=228.8MB` already contains the 68 MB; adding the
two double-counts. The gauge now prints the copies' count (`cb.wear=<dents+doors+wheels>/<MB>`). Freeing
derived copies not drawn for a while is the eviction step of the growth order (14p), not done here.

### Where the allocations come from (`GTA2DX9_ALLOC_SITES=1`)

The operator's 15.4 million allocations in ten minutes are ~25 000 a second. With
`GTA2DX9_ALLOC_SITES=1` every 256th allocation's stack is scanned (bounded by the thread's stack base)
for return addresses in the DLL, and each `mem: minute` line is followed by the commonest twenty sites
of the last minute as DLL offsets (symbolise with `i686-w64-mingw32-nm -C` on the same build's DLL, or its
gta2dx9.map for exported functions).

What the 20-minute soak (`qa_perf5_soak20`, the steady third-person scenario at Industrial, this host:
~1.9 million allocations a minute, 32 000 a second) allocates once the warm-up is over, per minute
(minute 20):
- ~45 % from `NodeWorldsBlend` (model_store.cpp, posing a figure): its working vectors were created per
  call, four to ten per posed figure per frame, plus the caller's matrix vector.
- ~18 % from `LightsReconcile` (an `unordered_map<uint64, ...>` rebuilt node by node each frame) and
  2 % from `LightsAddRaw`.
- The rest is spread thin: the overlay flush, the skin-buffer map, the AimHud map.

`NodeWorldsBlend`'s vectors are now one set per thread, reused (nothing it calls comes back into it),
and `ModelNodeWorld` reuses its matrix vector. `ModelDrawBlend`'s own matrix vector is left as it was,
because a draw may nest. The lights map belongs to the Remix lights module (`remix_lights.cpp`,
`LightsReconcile`): a flat vector or a reserved open-addressing table would take the next ~18 % out. With
Windows' low-fragmentation heap these small blocks are reused; they are not what splits the address
space into regions. The large blocks are: the managed copies above, the derived car meshes and the
D3D buffers.

The same soak, 20 minutes, 0 FAULT (`out/qa_perf5_soak20`, `mem: minute`), private commit / VmSize /
our heap in MB:

| minute | 1 | 3 | 5 | 8 | 10 | 13 | 15 | 18 | 21 |
|---|---|---|---|---|---|---|---|---|---|
| private | 968 | 1 091 | 1 125 | 1 180 | 1 194 | 1 225 | 1 266 | 1 279 | 1 293 |
| VmSize | 2 392 | 2 627 | 2 664 | 2 724 | 2 856 | 2 907 | 2 948 | 2 968 | 2 972 |
| heap | 514 | 612 | 642 | 673 | 681 | 708 | 740 | 747 | 748 |
| FIX-PERF-4's run (fp4_third1): VmSize | 2 657 | 3 046 | 3 117 | 3 306 | 3 333 | - | 3 357 | 3 387 | - |

At minute 18 VmSize is 419 MB below FIX-PERF-4's run, and regions are 1 079 against ~1 550. From
minute 17 on the curve is nearly flat (2 953 -> 2 972 MB in four minutes). Minutes 8 -> 18 still add
~10 MB/min of private commit and ~7 MB/min of heap: the first-seen derived car copies
(`cb.wear=150/143.3MB` at the end, inside `ms.models=718/347.9MB`). Evicting copies not drawn for a while
is the growth order (14p), not done in this pass.

### `/LARGEADDRESSAWARE`: the owner's gta2.exe is a 2 GB process

The original gta2.exe 9.6 has `Characteristics 0x010F`: no `IMAGE_FILE_LARGE_ADDRESS_AWARE` bit. Every
run on this host marks the copy inside the Wine prefix with `linux/laa.sh` (`docs/hd-textures.md`), so
the process here has 4 GB and reached VmSize 3.4 GB (fp4_sw_fix1) without a fault, with the plain
renderer and with the Remix bridge (`run_game_remix_gpu.sh` applies it too). On Windows nobody set it:
that is the ~2 048 MB ceiling of the 5090's measurement. `tools/set_laa.py <gta2.exe> [<out>]` writes a
marked **copy** (default `gta2_laa.exe` beside it; the original is never written; no game binary is ever
committed). Its output is byte-identical to `laa.sh`'s (checked on a copy here: one byte at offset 0x11E,
0x0F -> 0x2F), i.e. the very file every run on this host plays. The DLL was made LAA-safe on 9 Nov
(7b36ca7: pointer checks no longer reject addresses above 2 GB). Not tested here: Windows itself and the
Remix bridge launcher (NvRemixLauncher32) on Windows with the marked exe. NEEDS OWNER: whether to ship
this as the recommended setup.

**For the 5090 box:** back up gta2.exe, `python tools\set_laa.py C:\gta2\gta2.exe`, rename
`gta2_laa.exe` to `gta2.exe`; play 10 minutes as before and send the `mem: minute` lines: `va ... free=`
should start near 2 GB higher and `largest_free` be hundreds of MB, not 8.8. With this build and without
LAA, the same lines should show `private=` ~500 MB lower than before and `ms.texgpuonly=` close to
`ms.textures=`.

### The warm-up paced to a crawl (board 0c)

The operator's 428 s for "street furniture and objects ready" reproduces on this host **only under
Remix**: HEAD Remix runs took 63.6 s (`vg5_rx2`), 64.4 s (`vg5_rx1`), 101.4 s (`tri40_rx_prxr1`) and
313.2 s (`tri40_rx_q11`) for the same 200-230 textures that the plain renderer prepares in 2-4 s. After
that, people and cars (another 1 000 textures, 500 MB) took only 5-30 s more. So neither the
per-frame budget nor the volume was what paced it.

What paced it, from the new `models: warm-up progress:` and `... not delivered by the reader` lines
(Remix takes `perf5_rxa2`, `perf5_rxb`, `perf5_rxc`): the warm-up's first steps are the player's own avatar
(`ModelsWarmFirst`, FIX-PERF-VSWITCH), and its three textures (`human_male_adult_11_m001_body.tga`,
`_body_paint.tga`, `_head.tga`) are not delivered by the reader thread. That thread reads the files in
the warm-up's original order and stops at 96 MB of files nobody has taken yet. The warm-up waited for
the first of them **without a limit** (`if (!PrefetchReady(file)) break;`), so nothing behind them
moved. It went on only when something else (play drawing a model in a street view, a paint
measurement) happened to take a file. One texture every few seconds while the classic view is up, with
the process idle: the owner's picture. In every take of this build the same three files waited 27
frames in all and were then read on the spot. The rest went at the budget.

Changes:
- A texture whose file the reader has not delivered after 10 frames is read on the render thread (one
  file read, logged by name).
- The driver-done event query is read with `D3DGETDATA_FLUSH` and holds the next batch at most 6 frames
  (it never waited in these takes: `waited on the driver 0`).
- In the classic view the warm-up takes up to 64 steps, 12 ms and 24 MB a frame (was 16 / 8 ms / 12 MB).
  The street views keep 2 steps / 2 ms after their first four seconds.
- A `models: warm-up progress:` line every 10 s while it runs says where it waited.

| run | renderer | furniture ready | people ready | all ready |
|---|---|---|---|---|
| vg5_rx1 / vg5_rx2 (HEAD before) | Remix | 64.4 / 63.6 s | 75.6 / 75.6 s | 79.8 / 80.6 s |
| tri40_rx_q11 (HEAD before) | Remix | 313.2 s | 319.9 s | 322.8 s |
| perf5_rxa2 / perf5_rxb (this build) | Remix | 3.1 / 2.8 s | 6.6 / 5.3 s | 10.7 / 8.2 s |
| perf5_rxc (this build, GPU 2 at 95 % from another session: present 70-100 ms a frame) | Remix | 15.8 s | 66.9 s | 97.7 s |
| qa_perf5_c1q (old budget) / qa_perf5_t3a (new) | plain GL | 1.8 / 2.0 s | 3.8 / 4.2 s | 6.4 / 7.1 s |

On the plain renderer nothing changes, neither the time nor the classic frames while it runs (frame-time
line over the warm-up: sprites 4.8/143.6 ms old, 4.8/152.2 ms new; the 3.4-4.0 s worst `game` frame in
both is the level load itself). Under Remix the classic frames during the warm-up average sprites
25 ms (`perf5_rxa2`), inside the 33 ms the frame cap leaves. The time left is the bridge: one texture
upload through it costs more than on the plain device.

Still open:
- The first sight of a model in play still creates per-copy buffers (the `model first draw` lines of
  the filing: buffers, poses).
- The warm-up runs on the render thread. A worker cannot call D3D9 through the bridge, but it could
  decode and stage, as the reader does.

**For the 5090 box:** the log's `models: warm-up: street furniture and objects ready` should come
seconds after the level starts. Send the `models: warm-up progress:` lines and the
`not delivered by the reader` lines if it does not.

## The sprite handoff: 'wrongarray' named, every accepted sprite accounted, conform airborne honest (10 Nov 2026, FIX-SPRITES-1)

The operator's plan ranked B1 first: on the 5090 the log said `sprite trouble @37568: accepted=7908 drawn=339 |
dropped wrongarray=6048` every window, and the owner saw "people whose bodies appear partially empty". This host
gives the same ratio (HEAD a5df3568 third person in wil: `accepted=7660 drawn=140 wrongarray=6727`; classic:
`accepted=1841 wrongarray=1841`). Both numbers are sums over 64 frames, not one frame.

**What wrongarray was.** A probe (`GTA2DX9_LOG_SPRITE_DROPS=1`, `live_geometry.cpp` SpriteDropRecord) names each
dropped draw by its call site in FUN_004BE060, object kind, where its vertices live and whether the same object's
body came through the game's sprite array that frame. Over every 256-frame window of a walk in traffic and three V
moves (out/spr1_a, out/spr1_b) there were exactly three classes, all from **one call site, 0x004BE441, flags
0x2180, a stack copy moved exactly +5,+5 screen pixels, the same size, vertex colour A0000000**: the game's drop
shadow, for cars, pedestrians and code objects alike. **Every one** came with its own object's body through the real
array in the same frame (e.g. 10 467 shadows against 17 460 real draws in 256 frames; 0 unmatched). So nothing the
owner should see was lost there: the shadow is left out on purpose (the "sprouting panels" fix; the street views give
figures and models shadows of their own, and the classic picture never had them), and the counter was misnamed.

**The counter now.** `Drops::gameShadow` counts draws from `game::kObjectDrawShadowReturn` and is not trouble;
`wrongarray` is any other non-array draw (a real loss; 0 on every run since). `accepted != drawn` said nothing either:
`drawn` counts the sprite pass's device draws (a figure, a model or a puff batch stands in for most sprites). Each
sprite `LiveGeometry::Draw` receives now gets one fate, settled when its loop iteration ends (a guard object, so no
exit path was touched): **model** (a 3D model or dome stands in), **own** (his own, unseen from his eyes), **ghost**,
**lamp**, **queued** (a quad, an effect, a soft puff, the boarding UI; of those, **figure** = drawn as a skinned
figure) or **unplaced** by kind (ped / car / other), which is the hole if there is one. The `sprite trouble` line
prints only when something is wrong (wrongarray, nonfinite, outside, degenerate, notexture, unplaced, texture
trouble); otherwise, once per 256 frames, `sprite fates @N (64 frames): accepted=.. shadows=.. | received=..
model=.. own=.. ghost=.. lamp=.. queued=.. (figure=..) unplaced=0 | device draws=..`. (`received` exceeds
`accepted` in a window where the warm-up's ghost street frame issues the classic sprites a second time.)

| run (HEAD + this) | before: per 64 frames | after |
| --- | --- | --- |
| third person, Downtown traffic walk + 3 V moves (out/spr1_d) | `accepted=4159 drawn=205 wrongarray=3262` (same counts, old names) | no `sprite trouble` line in the whole run; `sprite fates @512: accepted=4159 shadows=3262 \| received=4159 model=1905 queued=2254 (figure=2049) unplaced=0` |
| Downtown traffic, F10 scene (out/spr1_c) | `wrongarray` ~3000-4000 a window | no `sprite trouble` line |

Frames opened (plain GL, this host): pedestrians at 1-3 blocks whole in third person (spr1_c qa_12_drive: a file of
four on the pavement; spr1_d qa_40_third straight after the third V move: the hero and two walkers), cars whole and
on four wheels. **The owner's partially empty bodies are therefore not the handoff**: he played under Remix on the
5090, where figures are path-traced through the figure layer prims (memory remix-figure-layer-prims); a body with
holes there is a figure/Remix defect, untested here. The other handoff-side loss the log can name is the game's own
cull: `ped flicker: object .. dropped out of the draw list 3 times in 240 frames` (the game stopped handing that ped
over; see warp-game-camera-sprite-cull), unchanged.

**B2, conform airborne.** `conform grounded=100 airborne=28 maxgap=2.370` counted every sprite above the plane
*fitted* across its footprint. Logged offenders (`GTA2DX9_LOG_CONFORM_AIRBORNE=1`, spr1_b): all were code objects,
none a car or a pedestrian: base 4 numbers 548-551 (a lamp-post head 22x20 and three 18x4 lamp quads, at y 4.00,
2.00 over the street: the game holds them up there) and base 8 number 321 (a 5x5 particle 0.3 up). Half of them
straddled a roof edge (samples [4,4,2,2,2]): on the upper floor, but above the slope fitted between the two. The
counter now measures the gap to the **highest real floor sample** under the footprint: within 0.3 block of it is
**onstep**; a car or pedestrian further up is **airborne** (and `maxgap` is over those only); any other object is
**raised** (`raised=N (max g)`). Every car or pedestrian counted airborne is logged by default (`conform airborne:
object .. base .. at x,y,z fitted .. gap .., .. over the highest floor, samples [..]`, once per object per ~4000
sprites, 300 lines); the probe env lists the steps and raised objects too. Placement is unchanged: no conform
solution was clamped, because no car or pedestrian was found above its floor (a clamp would only pull the lamp heads
and real jumps down). spr1_c / spr1_d: `airborne=0 maxgap=0.000` in every window, `raised` 1-6 (max 2.00, lamp
quads), `onstep` 0-6. The 5090's 28 / 2.37 is very likely the same lamp-post heads and quads (no owner log here to
check; the new line will say so on his box).

Counters and logs only: no picture changes. vreg on the rebased build (out/spr1v2): spawn_classic PASS, 0 tiles;
the street shots WARN/FAIL by the same 15-36 tiles as every other capture on this HEAD (FIX-HUD-4's round mini-map
and hearts against the older goldens). Post-rebase walk + 3 V moves (out/spr1_e): no `sprite trouble` line, every
`sprite fates` window unplaced=0 (e.g. `accepted=5480 shadows=4400 | received=5480 model=3239 queued=2241
(figure=2113)`), `airborne=0 maxgap=0.000`, `raised` 4-7 (max 2.00). Still open: Remix figure holes on the owner's
box; a car genuinely airborne (a jump, a blast) would now be logged by name, not clamped.

## Car copies evicted, model buffers GPU-only, the object grid watched (10 Nov 2026, FIX-PERF-6)

Same scenario as FIX-PERF-4/5 throughout: the steady third-person soak at Industrial (`keys_qa_stress3_third.sh`,
`SOAK_SECONDS=1200`, 22 minutes of log), GPU 6 idle at the start of each run, `FPS=0`, frame log on, private
stages of HEAD 6122943a. `perf6_base20` = HEAD; `perf6_evict20b` = HEAD + the three changes below, both memory switches on
(buffers GPU-only, copies released after 45 s).

### Model vertex and index buffers: no second copy (`model_buffers_gpu_only`)

A rigid mesh's buffers were `D3DPOOL_MANAGED`: wined3d (and the Remix bridge client, and the Windows runtime) keep
a CPU copy of every managed buffer inside the 32-bit process, while the store already holds the mesh itself. They
are now `D3DPOOL_DEFAULT`, write-only, filled once at creation (the device is never Reset). Same vertices, so the
same Remix geometry hashes. New gauge `ms.bufgpuonly=1498/88.4MB` (the static buffers; the derived car copies were
already dynamic default-pool buffers). `[renderer] model_buffers_gpu_only` / `GTA2DX9_BUF_GPU_ONLY`: -1 (default) on
outside Wine and managed under Wine (see the frame-time A/B below), 1 always, 0 never. Private commit at minute 1, where the content seen is still the same: 961 MB (HEAD) -> 887-890 MB.

### Derived car copies give their buffers back when idle (`car_copy_idle_seconds`, the growth order's eviction)

What still grew from minute 10 to 22 on HEAD (`mem: caches`): door splits 38 -> 55 copies (+21.5 MB of mesh),
wheel splits 43 -> 52 (+10.5 MB), dents +3.5 MB, and their dynamic buffers (`ms.buffers` 182 -> 221 MB). A door
split is on screen for the second a door swings; most copies sit unused after their car has gone. A copy (dent step,
door split, wheel split) not shown for 45 s now releases its vertex and index buffers (`ModelReleaseBuffers`); when
it is wanted again it goes back through `WearMayShow`'s budget (4 meshes a frame) and the car is drawn as before
meanwhile (previous dent step, shut door, whole wheels), exactly as for a new copy. The meshes stay: the copies are
pinned by address in the glass, wear and Remix caches. Gauges `cb.evicted=N/MB` (released so far) and
`cb.reshown=N` (came back). `[renderer] car_copy_idle_seconds` / `GTA2DX9_CAR_COPY_IDLE_S`: -1 (default) 120 s outside
Wine and off under Wine (A/B below); the soak ran it at 45 s.
In the soak: 729 releases, 164 MB in all, 513 of them shown again later; `ms.buffers` holds at 115-128 MB.

### The 22-minute table

| minute | 1 | 5 | 10 | 13 | 16 | 19 | 22 |
|---|---|---|---|---|---|---|---|
| HEAD (perf6_base20): VmSize | 2 392 | 2 866 | 2 959 | 2 967 | 3 123 | 3 180 | 3 198 |
| this build (perf6_evict20b): VmSize | 2 447 | 2 692 | 2 765 | 2 774 | 2 793 | 2 794 | 2 816 |
| HEAD: private commit | 961 | 1 199 | 1 265 | 1 278 | 1 313 | 1 373 | 1 378 |
| this build: private commit | 887 | 1 057 | 1 125 | 1 144 | 1 163 | 1 163 | 1 178 |
| HEAD: regions | 894 | 1 022 | 1 049 | 1 064 | 1 085 | 1 112 | 1 120 |
| this build: regions | 879 | 970 | 988 | 1 003 | 1 013 | 1 013 | 1 027 |
| HEAD: ms.buffers MB | 92 | 158 | 182 | 184 | 197 | 220 | 221 |
| this build: ms.buffers MB | 98 | 117 | 119 | 123 | 115 | 125 | 118 |

Minute 10 -> 22: HEAD +239 MB of VmSize (+20 MB/min, in steps as new cars come into view), this build +51 MB
(+4.3 MB/min; 2 794 MB flat from minute 15 to 20). At minute 22: 382 MB less VmSize, 200 MB less private commit,
93 fewer regions. What is left of the slope is the derived copies' meshes (`cb.wear` 126 -> 143 MB: bounded by the
district's car set and the 64 MB wheel/door budgets) and the sprite store's frames (bounded at 8192). 0 FAULT.

### Frames over 50 ms on an idle GPU (14p3): the class is "cars in view", through wined3d's command thread

The rerun the order asked for: `perf6_base20` (HEAD 6122943a, GPU 6 idle at the start, host load 25-60 on 96 CPUs):
31 435 third-person frames, avg 41.9 ms, p99 89 ms, **19.1 % over 50 ms** (FIX-PERF-4's `fp4_third1` on the older
HEAD: 4.0 %). An idle GPU does not help: the GPU sits at 0-30 % while the game thread and wined3d's command-stream
thread are each near a full core (FIX-PERF-4). The slow frames have the same signature as before: the time lands in
`sky` (23.6 ms against 4.1 in a frame under 40 ms: `BeginFrame`'s Clear is the first call that waits for the command
thread to drain the previous frame), `cars` (12.2 against 5.6) and `peds` (8.7 against 3.8), whose dynamic-buffer
locks wait for that thread too.

What the slow frames have more of (slow minus fast, per frame): **car draws +191** (534 against 343, triangles
+237 k) and **shadow-pass draws +239** (1 039 against 800: mostly the same cars' recorded casters replayed into the
cascades); the world (627 k triangles), props and the rest are the same. Frame time against the cars stage's draws:

| car draws in the frame | 0-99 | 100-199 | 200-299 | 300-399 | 400-499 | 500-599 | 600-699 | 700+ |
|---|---|---|---|---|---|---|---|---|
| frames | 3 269 | 2 691 | 3 300 | 4 740 | 6 032 | 5 418 | 2 630 | 3 337 |
| avg ms | 34.1 | 35.2 | 38.3 | 40.6 | 43.2 | 45.0 | 47.0 | 46.8 |
| over 50 ms | 1 % | 4 % | 8 % | 16 % | 24 % | 28 % | 31 % | 31 % |

Over all frames, a least-squares fit gives 24.2 ms + 5.8 us per D3D draw (3 007 draws a frame on average): each
draw costs its command-thread time whatever its triangle count. The median frame has 429 car draws; the cars stage
draws each car's meshes, wheels, glass and, since FIX-CAR-SHADING-1 (7d80fe74, after FIX-PERF-4's measurement), a
second clear-coat pass over every body mesh, and the shadow pass replays the cars' meshes into each cascade. **The
cut that would move the number** is fewer car draws per car: the coat folded into the body's own pass (one draw per
body mesh instead of two), wheels and hull merged into one buffer per split, and the far cascade's caster replay
limited to cars near the eye. Each changes how a car is drawn and needs fixed-pose A/B frames (`GTA2DX9_REGRESS_CAM`);
none is in this pass. The quickest measurement for the coat seat: the same soak with `INI_SED='s/^car_coat=.*/car_coat=0/'`
interleaved with the default, two pairs (single runs swing 19 % <-> 37 % over 50 ms with host load, see below).

### gta2.exe+0x47352 (00y): the game's object grid, and a guard on the renderer's share of it

`FAULT ... at 00447352 (gta2.exe+0x47352), reading 00000004, eax 0` (QA-STRESS, 6 stars at Industrial) is not a null
pointer of ours: gta2.exe+0x47350 is a three-instruction free-list pop (`head = head->next`) and eax=0 means the list
was empty. The pool is `[0x5E6684]` (built at 0x4471B0: 0x8004 bytes = 4 096 nodes of 8 bytes {object, next}); its
sibling `[0x5E6688]` holds 6 000 nodes of 12 bytes. Together they are the game's object grid: 0x447C00 links an
object into every map block its bounding rectangle covers (0x447A60 per column, 0x4479D0 per block), from the
vehicle code and others. Neither pop checks for empty, as with the ped and vehicle pools (memory note
gta2-pool-exhaustion-faults). The renderer hooks nothing on this path; it does raise what goes into it (density.cpp:
traffic, dummies, people; at the fault: 106 vehicles, traffic 36/36, plus a 6-star army).

Measured with the new census field `grid_free=<cells>/<columns> grid_min=<lowest seen>`: in ordinary third-person
play at Industrial the 4 096-node pool idles at **only 450-700 free** (game's own budgets, `perf6_buf20`; raised
budgets, `perf6_evict20b`: 470-650, lowest 352); the 6 000-node pool at ~3 100. At 6 stars (`perf6_want6`,
`keys_qa_stress3_wanted.sh`, `force_wanted=6`, 12 minutes, 0 FAULT) it fell to 152 free, the guard held, and the
lowest seen was **107 of 4 096**. The guard (density.cpp, as for the ped and car pools) stands the raised budgets down
to the game's own under 240 free cells / 400 free columns and raises them again above 400 / 600 (first set at
160/320: the pool went 45 below the hold before the despawns caught up). `[density] grid_headroom=1`,
`GTA2DX9_GRID_HEADROOM=0` for the A/B. The game's own budgets at 6 stars are the game's own risk; the crash was 1
in 2 runs at the raised budgets.

### What the two memory switches cost in frame time under Wine, and the defaults that follow

Interleaved 7-minute runs of one build (third-person soak, bil, GPU 6), X = both switches on, Y = both off
(`GTA2DX9_BUF_GPU_ONLY=0 GTA2DX9_CAR_COPY_IDLE_S=0`), W = GPU-only buffers alone, Z = the 45 s eviction alone:

| run | X1 | Y1 | X2 | Y2 | W1 | Z1 |
|---|---|---|---|---|---|---|
| third frames over 50 ms | 33.5 % | 15.4 % | 21.3 % | 3.6 % | 23.9 % | 36.2 % |
| avg ms | 46.2 | 41.2 | 42.1 | 36.0 | 43.9 | 47.3 |
| median minute, over 50 ms | 36 % | 13 % | 14 % | 3 % | 18 % | 38 % |
| new vertex buffers a frame | 0.42 | 0.29 | 0.41 | 0.24 | 0.33 | 0.45 |
| host 1-min load at the end | 33 | 77 | 31 | 41 | 37 | 30 |

The pushed build with its Wine defaults (`perf6_finC`, both off, grid guard at 240/400): 0 FAULT, 20.0 % over 50 ms,
avg 42.1 ms: HEAD's 19.1 % / 41.9 ms on the same scenario; the same build with the 45 s eviction forced on
(`perf6_finA`): 24.6 % / 43.6 ms.

Single minutes inside one run swing from 1 % to 96 % over 50 ms on this shared host, so one 7-minute run decides
nothing; but both Y runs (both off) beat every run with either switch on, the eviction raises buffer creation by
~60 % (513 of its 729 releases came back within the soak), and the slow frames carry the command-thread signature
(`sky` 28-31 ms against 17-20 in Y). Under Wine both switches therefore default off: there the process is
large-address-aware (4 GB) and the ceiling watchdog stands guard. On Windows (the 5090, where gta2.exe without the
LAA bit has 2 GB and the managed copies are what filled it) both default on, the eviction at 120 s to cut the churn:
**untested there**. For the 5090 box: the log's `models: model_buffers_gpu_only=-1 -> default pool` and
`car bodies: car_copy_idle_seconds=-1 -> 120` lines say what was chosen; the `mem: caches` line's `ms.bufgpuonly=`
and `cb.evicted=` / `cb.reshown=` say what it did; if the frame time drops against the previous build, set both
keys to 0 in gta2dx9.ini and send the two logs.

What this leaves for the memory order on this host: with the Wine defaults the growth is HEAD's (minute 10 -> 22
+20 MB/min, the derived car copies and their buffers, bounded by the 48/64/64 MB copy budgets and the district's
car set); with both switches on (Windows defaults) +4.3 MB/min and 382 MB less at minute 22.

## The wedged-truck spot: 500-750 car draws a frame for cars nobody can see (11 Nov 2026, FIX-PERF-7)

QA-STRESS pass 18 (25-minute wil soak) found the 3D over-50 ms excess is not spread evenly: one 5-minute bucket held
17 % of frames over 50 ms, and that bucket was one spot, the seated 063 truck wedged against the wall corner at wil
x 70-72, y 147-149 for two minutes: 3D frames 55-56 ms on average (35 elsewhere), the cars stage 22 ms (5-6 elsewhere),
675 car draws / 845 k car triangles a frame (326 / 405 k elsewhere), 1 213 shadow-pass draws (862 elsewhere),
71 % of the frames there over 50 ms (3.2-3.7 % elsewhere in the same run). The filer's frames at the spot
(`qa_s18_080_first`, `qa_s18_088_third`) show a wall corner and his own truck: not one other car on screen.

### The census (`GTA2DX9_CAR_CENSUS=N`)

New probe: every N frames, one line per car handed to the car stage (model, distance from the eye, behind the eye,
outside the view frustum, behind walls from the eye, the D3D draws and triangles it submitted, its CPU ms) and a
summary line; with it the shadow pass logs `shadow census:` (casters recorded, replays per cascade). The draw counts
come from the frame log's counters (`FrameLogCounts`), so it needs `GTA2DX9_FRAME_LOG`. Run `perf7_cen1`: on foot at
wil 70.8,147.8 (the truck's spot), the regression camera at the filer's two poses (third: eye 71.9,149.2,3.0 toward
69.0,145.0,2.0; first: eye 70.6,147.6,2.6 toward 68.4,144.3,2.45, game frame), 45 s each, census every 30 frames:

| pose | cars handed to the stage | behind the eye (already skipped) | outside the frustum | in it, behind walls | seen | car draws a frame |
|---|---|---|---|---|---|---|
| third (33 samples) | 19.9 | 5.1 | 8.6 (317 draws) | 6.0 (152 draws) | 0.2 (3 draws) | 473 |
| first (46 samples) | 19.5 | 4.7 | 5.7 (207 draws) | 9.1 (300 draws) | 0 | 507 |

**The cause, named:** the spot sits beside a depot and a street of parked and passing cars (model 63 trucks, 36, 68,
69, 0, 12...), 20 of them within 10-26 blocks; the street view's traffic cap (29/29 at the time) fills it. The only
cull the car stage had was "behind the eye" (`BehindView`, 2.5-block margin). Every other car was drawn in full: a
model car costs **9 to 53 D3D draws** (body meshes, the clear-coat pass over each body mesh, four wheels and their
rims, glass and cabin, lamps) and 14-51 k triangles, and each of those draws is recorded as a shadow caster and
replayed into both cascades (`shadow census`: 670-735 casters, 590-650 replays in the near cascade and 670-735 in the
far one). So at a wall corner the frame paid for ~15 cars that are outside the view or behind the building, ~500 car
draws plus ~600 caster replays, through wined3d's single command thread (FIX-PERF-6's fit: 5.8 us a draw), and
nothing of it reached the screen. It is the same class as FIX-PERF-6's "cars in view" (over 50 ms rises with the
cars stage's draws), with the twist that "in view" meant "near the eye", not "visible".

### The cut: a car nobody can see submits nothing (`[renderer] car_view_cull`, default 3)

Per car, after the "behind the eye" test and before any of its draws (`CarViewHidden`, src/car_bodies.cpp), a volume
is tested: the body's box (the cabin record's length, height and half width, i.e. the model as last drawn, roof gear
and a truck's stacks included; 10 % out plus 0.08-0.12 block) **and that box's shadow on the ground** (its top
corners carried down the sun's direction, never flatter than the shadow maps' 10 degrees). Bit 1: the volume's bounding
sphere wholly outside the view frustum's four side planes. Bit 2: 19 rays from the eye (the box's corners, its
middle, its edges' middles, the shadow's corners) all stopped by a one-sided wall or lid of the world
(`eyecol::SegmentBlocked`: a cell walk that stops at the first face; railings, two-sided sheets and every tile with
more than 0.5 % transparent texels never hide). A car that fails either test is drawn as before; one that passes
has its draws held (`ModelHoldDraws`: body meshes, the clear coat inside them, wheels, doors, its glass path), so it
records no shadow casters either, while everything else about it runs (identity, wear and dents, springs, steering,
lamps, smoke, its door, the cabin record), and the frame it comes into view it is drawn exactly as it would have
been. Never the car he drives or sits in, never a car with no cabin record yet (its first frame), never under RTX
Remix (the path tracer sees what is out of view: Remix untested with the cut, and the cut is off there). The classic
view draws no car bodies. Cost: 0.15-0.3 ms a frame for ~20 cars (census `cull mode` field).

**The proof (`GTA2DX9_CAR_CULL_VERIFY=1`).** Nothing is held; every car the test calls unseen is drawn inside a D3D
occlusion query against the depth of the world and the cars before it, and a call whose draws pass anywhere is
logged (`car cull verify: WRONG CALL`, with the car and the eye). Ten-minute drives on QA-STRESS pass 18's route
(`keys_qa_stress18_drive.sh`, all three views):

| verify drive | unseen calls queried | drew any pixel | drew 16+ | worst | what it was |
|---|---|---|---|---|---|
| `perf7_ver1` (box 1.6 widths tall, 13 rays) | 40 123 | 42 | 2 | 476 px | a 063 cab's exhaust stacks above the estimated box |
| `perf7_ver3` (box from the cabin record) | 44 876 | 61 | 3 | 1 331 px | cars behind see-through art (fences, grilles) counted hidden |
| `perf7_ver4` (see-through tiles never hide, 19 rays) | 54 415 | 19 | 0 | 2 px | single-frame 1-2 px slivers at building corners (15-20 blocks) |

The frustum test made no wrong call in any of them. What is left is 19 one-frame specks of 1-2 pixels in 54 k
calls, cars 15-20 blocks away behind building corners (depth precision or a crack at a wall's edge).

**Fixed-camera A/B, same session, interleaved A B A B** (live `[devtools] car_view_cull=0|3`, regression camera,
fixed at 12:30 with a clear sky; `perf7_ab1` with the clock running, `perf7_pairs` at noon on the rebased build). Frames are
street views only, the first 3 s after each switch left out:

| pose (run) | cull | frames | avg ms | p99 | over 50 ms | cars ms | car draws | shadow-pass draws | all draws |
|---|---|---|---|---|---|---|---|---|---|
| wedge third (ab1) | off / on / off / on | 538 / 660 / 548 / 660 | 39.9 / 33.2 / 40.0 / 33.2 | 168 / 33 / 71 / 33 | 5.4 / 0.0 / 11.1 / 0.0 % | 3.5 / 1.4 / 3.7 / 1.6 | 371 / 5 / 492 / 60 | 824 / 420 / 1 008 / 501 | 2 771 / 2 005 / 3 115 / 2 155 |
| wedge first (ab1) | off / on / off / on | 485 / 630 / 533 / 660 | 45.3 / 33.3 / 41.2 / 33.2 | 64 / 33 / 73 / 33 | 35.9 / 0.0 / 26.3 / 0.2 % | 5.1 / 4.1 / 14.6 / 3.3 | 664 / 3 / 742 / 2 | 1 220 / 439 / 1 260 / 415 | 3 506 / 2 026 / 3 593 / 1 985 |
| wedge third, 3-min take (pairs) | off / on / off / on | 1 160 / 1 287 / 1 288 / 1 288 | 36.1 / 33.3 / 33.3 / 33.3 | 68.5 / 33.3 / 33.3 / 33.3 | 3.1 / 0.3 / 0.2 / 0.1 % | 4.2 / 1.2 / 4.6 / 1.6 | 508 / 20 / 607 / 3 | 965 / 424 / 1 070 / 396 | 3 055 / 2 029 / 3 267 / 1 977 |
| wedge first (pairs) | off / on / off / on | 682 / 660 / 670 / 690 | 33.6 / 33.3 / 34.3 / 33.3 | 40.5 / 33.3 / 43.9 / 33.3 | 0.3 / 0.0 / 0.3 / 0.0 % | 12.6 / 4.0 / 13.3 / 4.4 | 721 / 3 / 851 / 2 | 1 199 / 401 / 1 271 / 425 | 3 504 / 1 982 / 3 718 / 2 020 |
| parked car beside the church (pairs) | off / on / off / on | 234 / 240 / 202 / 240 | 34.2 / 33.2 / 34.6 / 33.2 | 46 / 33 / 45 / 44 | 0.4 / 0.0 / 1.0 / 0.4 % | 12.4 / 5.3 / 13.0 / 5.2 | 650 / 10 / 651 / 10 | 1 100 / 418 / 1 101 / 422 | 3 327 / 2 010 / 3 331 / 2 017 |
| noon plaza, high over the church, cars in view (pairs) | off / on / off / on | 132 / 148 / 142 / 167 | 60.5 / 53.8 / 55.9 / 47.6 | 87 / 68 / 69 / 59 | 87.9 / 68.9 / 77.5 / 28.7 % | 27.1 / 16.2 / 23.9 / 15.7 | 935 / 478 / 935 / 478 | 1 344 / 1 011 / 1 344 / 1 018 | 3 894 / 3 101 / 3 893 / 3 111 |

At the wedge the frame goes back to the 33.3 ms cap: ~1 000-1 700 fewer draws a frame, of them ~400-850 shadow-pass
draws (the held cars' casters). The plaza pose shows what is left: 478 car draws for cars that really are on
screen, still 29-69 % over 50 ms.

**Same-pose frames, opened** (`perf7_ab1`, `perf7_pairs`; HUD corners masked): wedge third and first, cull off against
on: 0 pixels differ (one 3-pixel moving speck in ab1). Parked car beside the church (a near car, both pairs): the
car's crop 0 difference; the frame differs only where a pedestrian walks through (two frames with the cull on differ
there too). Noon plaza: the near cars at the bottom edge and the far red car 0 difference; the far parked car's crop
differs only by a pedestrian entering it; traffic and peds move between the frames (two frames with the cull off
differ by 1.5 % too). Car shading, the clear coat, glass and the cars' shadows: no visible change.

**Drives (interleaved, QA-STRESS pass 18's route, 10 minutes each, `perf7_drv_*`).** GPU 3 is shared with other seats'
runs (QA-STRESS, triage, vreg captures), and this time that load was a strong confound (A1 ran with the GPU
saturated by other runs). GPU 3 utilization is in the table (`nvidia-smi -l 15`, the whole GPU, this run included):

| run | cull | street frames | avg ms | p99 | over 50 ms | per 2-min bucket over 50 ms | car draws | shadow-pass draws | all draws | host 1-min load (start/end) | GPU 3 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 | off | 2 406 | 163.5 | 583 | 82.5 % | 83 / 72 / 94 / 96 / 88 / 100 | 216 | 779 | 2 583 | 77 / 46 | saturated (not logged) |
| B1 | on | 10 788 | 39.3 | 80.6 | 13.1 % | 91 / 5 / 8 / 10 / 17 / 16 | 110 | 596 | 2 257 | 46 / 21 | 74 % (last 2 min) |
| A2 | off | 8 594 | 50.6 | 258 | 25.9 % | 4 / 18 / 21 / 28 / 76 / 26 | 247 | 736 | 2 564 | 21 / 29 | 85 % |
| B2 | on | 11 565 | 36.8 | 80.9 | 7.2 % | 44 / 16 / 6 / 3 / 4 / 0 | 101 | 635 | 2 331 | 29 / 23 | 54 % |

Classic in the same runs: 0.5-2.9 % over 50 ms. The cull halves the car draws on the drive (216-247 down to 101-110 a frame)
and takes 100-180 draws off the shadow pass. Both pairs favour it, but the GPU's other load moves the numbers as
much as the cut does. **The standing acceptance (p99 under 50 ms, under 1 % over 50 ms in the street views) is not
met on the drive:** 7.2-13.1 % over 50 ms with the cull, p99 81 ms. At the wedge spot it is met (0-0.4 %, p99 33.3).

**What is left and the next cut.** The cost now is cars that are on screen: a model car is 9-53 draws (the plaza pose:
478 car draws, 1 011 shadow-pass draws). In order of least visual risk: (1) per-cascade caster limits in the shadow
pass. The `shadow census` field counts replays whose caster centre lies 12+ blocks outside the cascade's slice: only
65 of ~600 near and 4-15 of ~700 far at the wedge, so a slice test needs per-caster bounds to be worth doing;
(2) the clear coat folded into the body pass, one draw per body mesh instead of two. That is FIX-CAR-SHADING-1/2's
look, and it needs pixel-close fixed-pose frames; (3) wheels and hull merged per split. GPU 3's shared load needs
its own measure next to every A/B (`nvidia-smi -i 3 -l 15`).

Classic: `tools/vreg/vreg.sh stage` on this build, `spawn_classic` PASS, 0 tiles changed. The 3D shots differ from
the b89b95a goldens only in the new HUD, the window-glow lighting (yakuza1_street) and the first-person fists
(spawn_first). None of those are cars. Untested: night (lamp pools and glows of held cars: their logic runs, and
their glows are on the hidden body), rain and wet roads, Remix (the cut is off under Remix; the Remix rig was not
this seat's).
