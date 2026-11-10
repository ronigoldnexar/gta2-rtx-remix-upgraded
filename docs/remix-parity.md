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
