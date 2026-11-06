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
