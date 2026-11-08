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
  the camera eye `cx cy cz` (renderer frame), `sprite_quads`.

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
