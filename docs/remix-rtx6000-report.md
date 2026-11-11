# RTX Remix on the RTX PRO 6000 (GCP vGPU) and the RTX 5090: root causes, fixes, feature matrix — 11 Nov 2026

Operator report. Every line below is backed by a run directory on gta2-rtx6000 (/gta2/out/<name>) or a frame in
/home/ubuntu/gta2-screens on the orchestrator. Runs are named ngx1..ngx44, soak1/2, verify1.

## 1. Feature matrix, RTX PRO 6000 DC-1-24Q (vGPU), driver 580.196.07, Remix Plus 1.5.1

| Capability | Wine 10 (image gta2-remix-gpu3:night1) | Proton-GE 11-12 (i386 image + runner hooks) | Evidence |
|---|---|---|---|
| Path tracing | WORKS | WORKS | ngx2 frames; verify1 PASS |
| DLSS Super Resolution | WORKS (present 57 -> 7.9 ms) | WORKS | ngx7: nvngx.log "feature dlss snippet 310.6.0"; frames |
| Ray Reconstruction | WORKS (present 32 ms) | WORKS alone | ngx12 (dlssd snippet, clean frame); ngx37 |
| Frame Generation | REFUSED by the Windows dlssg ("requires GPU hardware scheduling") | module loads; DEVICE LOST on engage | ngx30/43/44: VK_ERROR_DEVICE_LOST, zero CUDA calls; host vulkaninfo: 0 x VK_NV_optical_flow (L4: 8) |
| Neural Radiance Cache | FAILS: "Could not initialize SDK API" | FAILS: "Could not check GPU device capabilities" | ngx35 relay: NRC_Vulkan loads nvapi64, GetProcAddress("nvapi_Direct_GetMethod") = NULL; dxvk-nvapi lacks it, NVIDIA's Windows nvapi64 has it |
| Game input / gameplay | works (scripted tours, 20-min soak clean) | works once Remix user_settings are seeded for steamuser (first-run dialog ate keys) | soak2; ngx40/41 traces |
| Stability | 0 FAULT, 0 device loss over the scripted tour; one 10 s shader-compile stall at level load | FG off: clean | soak2, verify1, verify2 (stage 13ddc23b: all required PASS) |
| Performance | classic ~7.5 ms, street 20-32 ms present (DLSS+RR), VRAM peak 4.6 GB of 24 | — | soak2.smi.csv |

Verdicts: Frame Generation is unsupported on this vGPU profile by hardware exposure (no optical-flow engine) — it would
work on a pass-through GPU with the Proton path. NRC is unsupported under Wine/Proton: the SDK's capability check uses a
private NVIDIA NVAPI entry that only the Windows driver's nvapi64.dll provides; not spoofable legitimately.

## 2. Root causes found on the way (each with the run that proved it)
- Remix never mounted on the 6000 launchers (game ran plain): nrc/rtxtest logs "not running under Remix". ngx2 fixed.
- NGX "FeatureNotSupported" = NGX core's hardware check calling NvAPI_EnumPhysicalGPUs: -6 without DXVK's dxgi (dxvk-nvapi
  enumerates through DXVK DXGI), then "no suitable device" without DXVK_ENABLE_NVAPI=1 (DXVK hides NVIDIA GPUs). ngx2/6/7.
- Proton: the game's "Incorrect version of DirectX" = LoadLibrary(DDRAW) failing: Proton-GE ships 32-bit wined3d with
  libvkd3d imports it only provides for 64-bit; Wine 10's ddraw+wined3d pair loads once its "Wine builtin DLL" marker is
  neutralised. ngx22/25/26.
- Proton: Vulkan instance failed in the i386 image because apt --fix-broken removed the package owning nvidia_icd.json;
  bind the host manifest. ngx26/27.
- Proton: nvcuda = nvidia-libs winelib module, installed the way the proton script does (copied as system32/nvcuda.dll,
  order n,b). ngx29 onwards. (Turned out irrelevant to NRC, relevant to the driver's Linux dlssg.)
- Proton keys: Remix's first-run "Welcome" dialog (user_settings seeded for root, prefix user is steamuser). ngx37/43.

## 3. RTX 5090 (owner's machine) — the same day
- Settings file found 0 bytes (03:33, harness read-then-write): the "squashed cars" and "milk smoke" regressions.
  Restored, then replaced by a merged file; harnesses now write atomically; the pilot refuses a short ini.
- Night rendered as day / lighting changing with the view: rtx.conf lacked the play look; the mod's own directional
  light became Remix's sun. Fixed (playlook.ps1, carried by every deploy). Measured 23:00: top-down 47, third 43, first 21.
- Exposure per view: hold at the night cap (FIX-REMIX-NIGHT-10, 13ddc23b).
- Traffic jam in first person: street traffic cap 36 -> 24 (classic keeps the stock 16 by rule).
- Open: partial bodies, flying cars, ambulance wreck as sedan (owner pointers pending); HUD/quit-screen style (art).

## 4. Reproducible launcher and test (RTX PRO 6000)
/gta2/runremix_dlss.sh [name] [secs]  — Wine 10 + Remix + NGX/DLSS (+RR via RTX_MORE), documented piece by piece.
/gta2/verify_remix.sh [name] [secs]   — PASS/FAIL per capability from the logs; exit 0 = all required PASS (verify1).
/gta2/soak6000.sh name secs           — extended run with GPU sampling (KEYS=/work/keys_remix_playtest.sh for a tour).
Proton path (for a pass-through GPU): image gta2-remix-gpu3:night1-i386, GE-Proton11-12 at /gta2/dl/geproton_x64,
runner /gta2/gamerun/run_game_remix_proton.sh with PROTON_DIR=/proton, host nvidia_icd.json bound, ~/runngx43.sh as example.

Verification history: verify1 (stage c4cd943b) and verify2 (stage 13ddc23b, 16:03 UTC) both: every required line PASS, FG and NRC n/a with the reasons above.

Deployment state 11 Nov 18:40 UTC: build 13ddc23b on Tokyo's stage, on the RTX 6000 (verify2 PASS) and on the RTX 5090 (hash ba0e8c1c…, play-look rtx.conf, merged ini with the hold at the night cap).
