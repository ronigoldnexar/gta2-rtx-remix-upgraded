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
