# Remix parity: what the L4 (Tokyo) initialises against the owner's RTX 5090

REMIX-PARITY-1, 10 Nov 2026, owner's work order "close the Remix gap between Tokyo and the 5090".
Runtime: Remix Plus v1.5.1 x86 (`remix-runtime/`), driver 580.178.04, Vulkan 1.4.312, image
`gta2-remix-gpu2`, GPU 4 (NVIDIA L4), launcher `gamerun/rn_remix.sh` through `gamerun/rp1_take.sh`
(REMIX_NVCACHE=1, PRIO=1, per-GPU lock), fixed cameras `gamerun/rp1_cams.py`.

**Boundary (order section 0).** NVIDIA's driver refuses NGX on datacenter parts
(`NVSDK_NGX_Result_FAIL_FeatureNotSupported`, 0xBAD00001). That is the vendor's licensing decision. Nothing
here patches nvngx, spoofs a device id or shims a SKU check; anything that needs NGX is listed as
"cannot be closed on an L4".

## 1. The true gap: the 5090's log lines against the L4's

Session `out/rp1_base` (19:35-19:39 UTC, the play rig `gamerun/rtx_play.conf.extra` unchanged, warm
shader cache: ready after 34 s). Log: **`out/rp1_base/remix-logs/remix-dxvk.log`** (the runner copies the
runtime's log folder to `remix-logs/`; older runs have it at `out/<run>/remix-dxvk.log`). Line numbers are
that file's.

| 5090 line | L4 (rp1_base) | verdict |
|---|---|---|
| `[RTX info] Neural Radiance Cache: supported` | same line (l. 274: `[RTX info] Neural Radiance Cache: supported`) | same capability check passes |
| `[RTX Neural Radiance Cache] NRC v0.15 Context successfully initialized.` | **error** (l. 363-366): `err: [RTX Neural Radiance Cache] Could not initialize SDK API.` / `Failed to initialize NRC. Reason: Unexpected condition occured during processing` / `Neural Radiance Cache failed to get initialized. Switching to importance sampled indirect illumination mode.` / `Error: NRC Library has not been initialized!` | NRC's SDK refuses on the L4 (the order counts it in the NGX family; no further reason is logged). Cannot be closed on an L4 |
| `[RTX] Integrate Indirect Mode: Neural Radiance Cache - activated` | the line appears (l. 368) and **2.4 s later** l. 369: `[RTX] Integrate Indirect Mode: Importance Sampled - activated` | the fall-back is the runtime's noisiest reference integrator (docs/remix-materials.md "Advanced preset"); stand-in: ReSTIR GI, section 2b |
| `[RTX info] Opacity Micromap: supported / enabled` | same: l. 282 `[RTX info] Opacity Micromap: supported`, l. 359 `[RTX] Opacity Micromap: enabled` (and once per run `[RTX Opacity Micromap] Out of memory budget. Requested: 19154944 bytes. Free: 15673860 bytes, Budget: 1610612736 bytes`, l. 373) | parity (on by default) |
| `[RTX info] Shader Execution Reordering: supported / enabled` | same: l. 283 `... supported`, l. 284 `... enabled` | parity (on by default) |
| `FSR FG: DxvkFSRFrameGen created` | same line (l. 278), right after the two NGX errors (l. 276-277: `err: NVIDIA NGX is not available on this hardware/platform: (code: 0xbad00001, info: NVSDK_NGX_Result_FAIL_FeatureNotSupported)`) | the FSR 3 frame-generation object is built on the L4 even with `rtx.frameGenerationType` = 0; whether it presents generated frames: section 2f |
| `Reflex initialized successfully.` | **nothing**: the play rig sets `rtx.isReflexEnabled = False` (l. 33 of the option echo), which stops Reflex from even trying | measured with Reflex on in section 2g |
| `Present mode: VK_PRESENT_MODE_FIFO_KHR` | same: l. 302 and l. 314 `Present mode: VK_PRESENT_MODE_FIFO_KHR` (the first swap chain, l. 296, is `VK_PRESENT_MODE_IMMEDIATE_KHR`, then recreated as FIFO) | parity |

Lines the L4 prints that bear on the gap:
- l. 275 `warn: NV_present_metering extension not supported` (DLSS 4 frame generation's hardware pacing; NGX family anyway).
- l. 73 / l. 281 `[RTX Neural Radiance Cache] Selected Ultra preset mode.` then `Selected Medium preset mode.`: the play rig's
  `rtx.graphicsPreset = 2` (Medium) pulls NRC's own preset down; irrelevant while NRC does not start.
- The graphics preset. The runtime's Auto preset (`rtx.graphicsPreset = 5`, the default) chooses by architecture; the
  server DLL (`.trex/d3d9.dll`) holds the four messages `NVIDIA Turing|Ampere|Ada|Blackwell architecture detected,
  setting default graphics settings to Low|Medium|High|Ultra`. **The owner's 5090 (Blackwell) runs Ultra.** The play rig
  pins Medium (2); earlier L4 runs on Auto logged Low (docs/remix-materials.md). Ordinals: Ultra 0, High 1, Medium 2,
  Low 3, Custom 4, Auto 5 (upstream's enum; Auto = 5 is the documented default). Section 2a sets Ultra.
- Not in the 5090 list but NGX as well: DLSS upscaling and Ray Reconstruction (the L4 uses TAA-U, `rtx.upscalerType = 3`),
  DLSS frame generation (`rtx.frameGenerationType = 1`).

Frame cost of the baseline (`gamerun/rp1_cost.py out/rp1_base`, 8 s windows on fixed cameras, 1280x720, the game's
30 fps cap): day 13:00 58.2 / 48.6 ms p50 per camera (17-21 fps), night 21:30 41.9 / 45.9 ms (22-24 fps). Frames:
`out/rp1_frames/rp1_base/` (`007_S0_h13_third_c0_0.png` day, `022_S1_h21.5_third_c0_0.png` night, same camera).

## 2. Turning on what legitimately works (same-pose A/B, fixed cameras)

Every session: `gamerun/rp1_take.sh <run> <conf> 420` (Downtown, warp to 169.6,127.5, two fixed street cameras at
13:00 and 21:30 plus a classic frame, `[timeofday]` paused through `SETTINGS_SED`, the hour set with `set_hour_tenths`),
one session at a time on GPU 4. Each conf is the play rig plus the step's lines (`gamerun/rp1_<step>.conf.extra`).
Frames are cut at the marks from `game_full.mp4` (`gamerun/frn9_dump.sh`) and kept in `out/rp1_frames/<run>/`;
cost = `gamerun/rp1_cost.py` (frame interval p50 over an 8 s still window per camera, 30 fps cap).

### 2a. The graphics preset: Ultra (the 5090's) against Medium (the play rig): SUN SHADOWS

`rtx.graphicsPreset = 0` (run `out/rp1_a`, replicate `out/rp1_b`) against `= 2` (`out/rp1_base`, replicate
`out/rp1_base2`). Sheet `out/rp1_frames/sheet_2a_medium_top_ultra_bottom_13h.png` (top: the two Medium sessions,
bottom: the two Ultra sessions, the same fixed camera at 13:00).

- **What changed:** at Ultra the 13:00 sun casts hard shadows (bench, parking meter, hydrant, lamp post, the truck
  on the road, every pedestrian); at Medium there are **no sun shadows at all** in either session (only a faint
  contact smudge near one pedestrian). Two sessions each way, so it is the preset, not the intermittent sunless-day
  bug. At 21:30 the frames are the same within the noise (mean abs diff 2.3 / 1.8 of 255 on the two night cameras;
  `out/rp1_frames/crop_base_vs_a_022_S1_h21.5_third_c0_0.png`).
- **Log proof the preset applied:** Medium logs `[RTX Neural Radiance Cache] Selected Medium preset mode.`
  (rp1_base l. 281); Ultra keeps `Selected Ultra preset mode.` only (rp1_a).
- **Consequence for Group B / the defect files:** every Tokyo Remix frame on the play rig (Medium) and on Auto
  (Low on the L4) was rendered without sun shadows, while the owner's 5090 (Blackwell, Auto = Ultra) has them. The
  "daytime no sun / no shadows" family filed from Tokyo is at least partly the preset. Proposal for the coordinator
  (not changed by this seat): run any Remix check that judges daylight at Ultra. **Adopted:** the coordinator moved
  `rtx_play.conf.extra` to `graphicsPreset = 0` in 56fff34d.
- **Cost:** p50 per camera Medium 58.2 / 48.6 (day), 41.9 / 45.9 ms (night) in rp1_base, 68.6 / 59.1 / 45.7 / 43.8
  in rp1_base2 (GPU shared, noisy); Ultra 55.0 / 48.3 / 46.1 / 44.6 (rp1_a). No measurable cost on the L4 at 1280x720.
- **Trap found:** at Ultra (and any preset other than Custom 4) the preset layer owns `rtx.integrateIndirectMode`:
  rp1_b set `rtx.integrateIndirectMode = 1` with `graphicsPreset = 0` and the log still shows `Integrate Indirect Mode:
  Neural Radiance Cache - activated` then `Importance Sampled - activated` (l. 369-370), never ReSTIR GI. On the 5090
  Ultra means NRC; on the L4 Ultra means NRC -> Importance Sampled. ReSTIR GI needs `graphicsPreset = 4` (Custom) with
  the Ultra-level values written out (2b).

### 2b. ReSTIR GI as the stand-in for NRC (Custom preset with the Ultra values written out)

Conf `gamerun/rp1_b2.conf.extra` = play rig + `rtx.graphicsPreset = 4` + `rtx.integrateIndirectMode = 1` +
`enableRaytracing True`, `pathMinBounces 1`, `pathMaxBounces 4`, `useRTXDI True`, `di.initialSampleCount 4`,
`di.spatialSamples 2`, `di.disocclusionSamples 4`, `denoiseDirectAndIndirectLightingSeparately True` (the option
table's defaults, which this runtime prints no Ultra table to compare against; the frames below match the Ultra
session's sun and shadows, so nothing the preset sets was lost). Run `out/rp1_b2` against `out/rp1_a` (Ultra).

- **Log:** `out/rp1_b2/remix-logs/remix-dxvk.log` l. 335 `[RTX] Integrate Indirect Mode: ReSTIR GI - activated`, and no
  NRC initialisation is attempted (no `[RTX Neural Radiance Cache]` errors). `= 2` (NRC) is NGX-family on the L4
  (section 1) and cannot be closed here.
- **What changed:** at night the lamp-lit tree canopies and the brick behind the fence get a smoother, more even
  bounce fill and the lamp pool behind the fence is less hot (`out/rp1_frames/crop_2b_ultra_vs_restir_026_S1_h21.5_third_c1_0.png`);
  by day the shaded facades sit a little darker with more contrast instead of the flat importance-sampled fill
  (`crop_2b_ultra_vs_restir_011_S0_h13_third_c1_0.png`). Mean luminance moves 1-3 %. The sun shadows of 2a stay.
- **Cost:** p50 63.0 / 50.2 (day), 47.8 / 50.3 ms (night) against Ultra's 55.0 / 48.3 / 46.1 / 44.6: about +2-6 ms,
  i.e. ~20 fps instead of ~21 on the L4 at 1280x720 (single sessions on a GPU other agents share the host with).
- Not the same thing as NRC: NRC is an infinite-bounce learned cache; ReSTIR GI is reservoir-resampled path tracing
  at 4 bounces. Lighting and material defects are judgeable under it; NRC-specific artefacts (cache lag after a light
  change, NRC's own noise pattern) are not.

### 2c. Opacity Micromap (already on; measured off against on)

`rtx.opacityMicromap.enable = False` (run `out/rp1_c02`) against the 2b rig (`out/rp1_b2`, on).
- **Log:** on: `[RTX info] Opacity Micromap: supported` + `[RTX] Opacity Micromap: enabled` (rp1_b2); off: only `supported`
  (rp1_c02 l. 292), no `enabled` line. The once-per-run `[RTX Opacity Micromap] Out of memory budget` info line stays with
  it on (1.5 GB budget; not an error).
- **What changed:** nothing visible: fence spikes, tree canopies and railings cut out identically
  (`out/rp1_frames/crop_omm_on_top_off_bottom_026_S1_h21.5_third_c1_0.png`); OMM is a ray-tracing speed-up, not a look.
- **Cost:** p50 55.0 / 48.7 / 44.9 / 47.0 ms off against 63.0 / 50.2 / 47.8 / 50.3 on: no gain measurable on this
  scene within the session-to-session noise (about +-5 ms). Kept on (it is what the 5090 runs).

### 2d. Shader Execution Reordering (already on; measured off against on)

`rtx.isShaderExecutionReorderingSupported = False` (run `out/rp1_d02`).
- **Log:** on: `[RTX info] Shader Execution Reordering: supported` / `enabled` (`VK_NV_ray_tracing_invocation_reorder` is in
  the device's extension list); off: `... not supported` / `... disabled` (rp1_d02 l. 293-294).
- **What changed:** nothing visible (mean abs frame difference 2-6 of 255, the size of moving traffic); SER is a scheduling
  speed-up for the indirect pass.
- **Cost:** 48.4 / 51.2 / 47.4 / 44.9 ms off: within the noise of on. Kept on (parity).

### 2e. Volumetrics (already on; measured off against on)

`rtx.volumetrics.enable = False` (run `out/rp1_e02`).
- **Log:** the option echo `rtx.volumetrics.enable = False`; the runtime prints no volumetrics init line either way.
- **What changed:** no visible difference at this street's distances
  (`out/rp1_frames/crop_vol_on_top_off_bottom_007_S0_h13_third_c0_0.png`): with the default thin froxel medium the haze
  only matters a few hundred metres out, and GTA2 streets end sooner. Lamp-cone and sun-shaft looks need fog density set
  (rtx_showcase / rtx_advanced do that), not this switch.
- **Cost:** 53.0 / 46.6 / 45.1 / 43.1 ms off, present stage p90 11-14 ms against 21-32 ms on: the froxel pass is the
  one switch here with a measurable GPU share, a few ms. Kept on (parity).

### 2g. Reflex: not SKU-gated on the driver side, blocked by Wine

`rtx.isReflexEnabled = True`, `rtx.reflexMode = 1` (run `out/rp1_g2`).
- **Log:** `out/rp1_g2/remix-logs/remix-dxvk.log` l. 288 `err: Unable to initialize Reflex: NvLLVk support library cannot be loaded.`
- The L4's driver does expose the Reflex extension: `vulkaninfo` in the same image on GPU 4 lists `VK_NV_low_latency2`
  (rev 2) and `VK_NV_present_metering` (rev 1). The runtime nevertheless logs `NV_present_metering extension not supported`
  and cannot start NvLowLatencyVk.dll, whose only import is KERNEL32 and which resolves `nvapi_QueryInterface` at run
  time: the Wine image has no `nvapi64.dll` and winevulkan does not hand the NV low-latency extensions through. So Reflex
  is blocked by the Wine layer here, not by a GeForce check (an open-source NVAPI layer such as dxvk-nvapi in the prefix
  would be the legitimate route; not tried in this pass). Reflex changes input latency, not the picture: nothing a
  frame-based check depends on. Cost: 58.7 / 48.8 / 48.3 / 44.8 ms (the failed init costs nothing).

### The parity rig

`gamerun/rtx_parity_max.conf.extra` (copy in `linux/docker/`), self-contained: the play rig verbatim, then
`graphicsPreset 4` + ReSTIR GI + the Ultra-level path/RTXDI values (2a, 2b), OMM / SER / volumetrics explicitly on
(2c-2e), Reflex off (2g), `frameGenerationType 0` (2f). Use: `-e RTX_EXTRA=/work/rtx_parity_max.conf.extra` on
`rn_remix.sh` / `playtest_remix.sh`, or `gamerun/rp1_take.sh <run> rtx_parity_max.conf.extra <secs>`. Every step conf
of this page is in `linux/docker/rp1_*.conf.extra`.

### 2f. FSR 3 frame generation: initialises on the L4; one hang in two sessions

`rtx.frameGenerationType = 2` on the 2b rig (runs `out/rp1_f2`, replicate `out/rp1_f3`).
- **Log** (`out/rp1_f2/remix-logs/remix-dxvk.log`): the master sets its slave (l. 115 `rtx.fsrfg.enable = True`, echoed by
  the runtime; `rtx.dlfg.enable` stays False), then l. 305-335 `FSR FG: Creating FSR FG Presenter`, `Swapchain proxy created
  successfully`, `Using queues for FFX SDK: game=0, present=2, imageAcquire=1, async=2, asyncEnabled=1`, `Frame gen context
  created successfully`, `FSR FG Presenter: Recreated successfully for 1280x720`. **FSR FG is fully created on an L4.**
- **What changed in the picture:** nothing wrong on the still cameras: sun shadows, people and cars as in 2b
  (`out/rp1_frames/ab_2f_b2_vs_fsrfg_007_S0_h13_third_c0_0.png`); no ghosting seen on these (slow-moving) frames.
- **Presented frame rate: not measured.** The runner records with x11grab at 15 fps, below both the real and the
  generated rate, and the renderer's frame log (`GTA2DX9_FRAME_LOG`) times the game's frames, not the presenter's.
  Game-side cost is unchanged (rp1_f3: 56.9 / 52.3 / 47.5 / 47.2 ms p50), and the present stage's p90 drops from
  21-34 ms (2b) to 12-20 ms (the presenter thread takes the queue). Whether Tokyo shows ~2x presented frames needs a
  presenter-side counter or a faster capture: untested.
- **Stability: one hang in two sessions.** In rp1_f2 the game thread stopped inside the Remix bridge client
  (`d3d9.dll`, waiting on the server) at the switch to 21:30 and did not return before the session ended (`gta2dx9.log`:
  `stall sampler: game thread idle 65719 ms`; `remix_shaders.txt`: `63 stall samples, longest game-thread stall 65.7 s`);
  the server's log just stops. rp1_f3, the same conf, ran clean (0 stall samples). The nine sessions without FG on this
  page had 0 stall samples. Not enough to blame FG; enough to leave it **off** in the parity rig and to say: turn it on
  only for a check about frame pacing, and treat a hang in such a run as possibly FG's.

### The parity rig as a whole (run `out/rp1_rig`)

`gamerun/rp1_take.sh rp1_rig rtx_parity_max.conf.extra 420`, 20:34 UTC: log l. 295-340 `Opacity Micromap: supported`,
`Shader Execution Reordering: supported` / `enabled`, `[RTX] Opacity Micromap: enabled`, `[RTX] Integrate Indirect Mode:
ReSTIR GI - activated`; no NRC errors; 0 stall samples. Frame `out/rp1_frames/rp1_rig/007_S0_h13_third_c0_0.png`: the
13:00 sun shadows of bench, meter, hydrant, lamp post and pedestrians. Cost 81.4 / 66.6 (day) and 50.1 / 45.2 ms (night)
p50: the day figure is the highest of eleven sessions whose effective options equal rp1_b2's (63.0 / 50.2), the same
spread rp1_base2 showed on the unchanged play rig (68.6 against 58.2): session-to-session noise on a shared host is
about +-15 ms by day, so take ~15-22 fps at 1280x720 as the L4's range under this rig.

## 3. The traps (order section 3), as met here

- `rtx.frameGenerationType` is the master: setting it to 2 made the runtime echo `rtx.fsrfg.enable = True` itself. Never set the slaves.
- **New trap:** any `rtx.graphicsPreset` other than 4 (Custom) owns `rtx.integrateIndirectMode`; Ultra forces NRC, which on
  the L4 falls back to Importance Sampled. ReSTIR GI is only reachable with Custom (2a, rp1_b).
- `rtx.showUI = 0` (the default, 0 = don't show) is pinned at the end of the parity rig; no overlay ate keys in any session (the keys script's marks and warps all landed); the
  compositor of `run_game_remix_gpu.sh` keeps the GUI input window transparent (docs/remix-gpu-l4.md).
- Clock: `rn_remix.sh` sets `[timeofday]` `Paused=1` / `StartHour` in `gta2dx9_settings.ini` through `SETTINGS_SED`, and the
  probe moves the hour with `[devtools] set_hour_tenths`; no `[weather] hour_hhmm` was relied on.
- Front end: `remix_keys_lib.sh` `to_level` (two Returns, no arrows); no vehicle entry was needed (`GTA2DX9_SCENE_NO_CAR=1`).

## 4. Replacement for VERIFICATION_TRIAGE.md Group B

What Tokyo can now do with `rtx_parity_max.conf.extra` (or the play rig at Ultra since 56fff34d for daylight checks):
Ultra-preset sun and shadows, ReSTIR GI multi-bounce indirect light, Opacity Micromap, SER, volumetrics, FSR 3 frame
generation (created; presented rate unmeasured). What it cannot: anything NGX.

| item | verdict | evidence |
|---|---|---|
| B1 Remix smoke rendering (puffs as blended particle billboards, lit result) | **partly** | the lit result is now judged under real multi-bounce GI (ReSTIR GI, 2b) and Ultra shadows (2a) instead of importance-sampled noise at Medium; no smoke frame was taken in this pass. The classification itself (billboard flags) is deterministic and reproducible anywhere. What stays 5090-only: the look under NRC + DLSS-RR denoising, which change how a thin blended volume reads |
| B2 LARGEADDRESSAWARE / 32-bit address space | **still 5090-only**, because Wine's allocator and address layout are not Windows'; not a Remix feature, the rig changes nothing | - |
| B3 address-space fragmentation drift | **still 5090-only**, same reason as B2 | - |
| B4 follow_clock=auto and the Remix sun ("night sky, daylit street") | **partly** | the Remix atmosphere's sun is honoured on the L4 and casts shadows at Ultra/Custom (`out/rp1_frames/sheet_2a_medium_top_ultra_bottom_13h.png`, `rp1_rig/007_*`); Tokyo's shadowless days were the Medium preset (2a), so sun-vs-sky checks are reproducible here at the right preset. `follow_clock=auto` itself was not exercised in this pass |
| B5 night exposure / sky fill (1.2/0.3 vs 2.5/1.0 gave a brighter result) | **partly** | auto exposure and the sky fill are post and atmosphere, not NGX, and run here; but the indirect fill they meter is NRC's (infinite bounce) on the 5090 and ReSTIR GI's (4 bounces) on the rig, so absolute night brightness differs. Re-run the two settings as a same-pose A/B on Tokyo under the rig first (the direction of the effect is reproducible); the final numbers on the 5090 |
| B6 NRC, DLSS, frame generation | **split**: NRC, DLSS upscaling, Ray Reconstruction, DLSS frame generation (`frameGenerationType = 1`) **still 5090-only, because** the driver refuses NGX on datacenter parts (`0xbad00001`, section 1) and NRC's SDK does not initialise (`Could not initialize SDK API`). **FSR 3 frame generation (`= 2`) is reproducible on Tokyo**: created on the L4 (2f), with the hang caveat | rp1_f2 / rp1_f3 logs |
| B7 the minimise/focus freeze | **still 5090-only**, because Wine never minimises a window (FIX-STABILITY-1 had to simulate it); not Remix | - |
| B8 camera jitter near a phone box / when a bus passes | **not a Remix gap**: the clearance probe is the renderer's own camera code and runs on Tokyo (plain renderer or Remix, the rig changes nothing). Tokyo can attempt it; the owner's report is from the 5090, so the sign-off stays there | - |

New items for the list (found here): Reflex is blocked by Wine, not by the SKU (2g); it changes latency only, so no
visual check depends on it. DLSS 4 present metering (`NV_present_metering extension not supported`) is NGX-family.

## Verified vs untested

- **Verified** (frames opened and log lines read, GPU 4, 12 sessions `out/rp1_*`): the section 1 table; Ultra casts sun
  shadows that Medium does not (2 sessions each way); Ultra blocks ReSTIR GI, Custom enables it; OMM / SER / volumetrics
  are on by default and their off switches show in the log with no visible change; FSR FG is created; Reflex fails with
  the quoted error while the driver exposes the extension; the committed rig starts ReSTIR GI with OMM and SER enabled
  and keeps the sun shadows.
- **Untested:** the presented frame rate under FSR FG; whether FG caused the rp1_f2 hang (1 of 2); the Ultra preset's
  internal per-option table (the runtime does not print it: the rig writes the option-table defaults and matches Ultra's
  frames, not a dump); dxvk-nvapi for Reflex; first person, driving, other districts and smoke under the rig.
- No DLL, `package/` or classic-path change: the classic top-down view is untouched by construction (no build was made).
