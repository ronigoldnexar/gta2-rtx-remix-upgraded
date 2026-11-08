# Migration to the 8x L4 host (written 8 Nov 2026)

What must move from the current host (user yossef.kindi, workspace /home/roni_goldshmidt/gta2-linux, a symlink into
/mnt/b200data/home/roni_goldshmidt/gta2-linux), what comes from GitHub or public downloads, and which NVIDIA pieces
the new host needs. Keep the same path /home/roni_goldshmidt/gta2-linux on the new host so every script works unchanged.

## Transfer from the old host (about 12 GB; rsync -aHAX --info=progress2)

| Path | Size | Why |
|---|---|---|
| gta2-linux/game/ | 386 MB | the owner's licensed GTA 2 data; never download it, never commit it |
| gta2-linux/repo/ | 3.5 GB | the git clone (fork ronigoldnexar/gta2-rtx-remix-upgraded, branch camera-modes, remote "fork") WITH its untracked art: assets/models (avatars, cars) and assets/textures_hd. A fresh clone plus the release archives reproduces it, but copying is faster and keeps the working tree |
| gta2-linux/assets-src/ | 7.9 GB | generation sources: Rocketbox avatars (humans/), car concepts and GLB candidates (cars/), Polyhaven props. Not in git, needed to regenerate or refine assets |
| gta2-linux/upstream-release/ | 1.4 GB | the upstream project's release files (also a public GitHub release download) |
| gta2-linux/remix-runtime/ | 1.1 GB | RTX Remix runtime (also a public NVIDIA download; this copy is the version our configs were tuned on) |
| gta2-linux/gamerun/ | 3.6 GB | run scripts (mirrored in repo/linux/docker) plus the prebaked Wine prefix pieces and nv_cache_gl |
| gta2-linux/deliverables/ | 7.9 GB | videos and release archives (optional; the archives are on the GitHub release) |
| gta2-linux/gen3d/ WITHOUT venv/ | 1.3 GB | TRELLIS checkout and our pipeline scripts; the venv is rebuilt on the new host |
| ~/.cache/huggingface | 30 GB | optional: saves the first-run download of TRELLIS, SDXL, DINOv2 |
| ~/.claude/projects/-home-roni-goldshmidt/memory | small | the coordinator's memory notes |

Do NOT transfer: gta2-linux/out (183 GB of run outputs; keep only out/*sheet*.png and out/quality_bar if wanted),
gta2-linux/stage_* (agents' private stage copies), Docker images (rebuilt from repo/linux/docker/Dockerfile.*),
gen3d/venv (rebuilt), containers.

## From GitHub / public
- Code, tools, docs, issues: git clone of the fork, branch camera-modes. Issues #1 (tracking), #10 (rules), #11 (plan).
- Release v1.4-ground-views and the draft v1.5-3d-round2 hold the art archives (cars 98 MB, people 135 MB, HD tiles 247 MB,
  Remix mod 1.08 GB) if assets/models is not copied.
- Docker images: rebuilt by `docker build` from repo/linux/docker (about 25 min total).

## NVIDIA components on the new host (Ubuntu 24.04)
1. Driver 550 or newer (current host: 580.178.04). `nvidia-smi` must list all 8 L4s.
2. CUDA toolkit 12.x with nvcc (the TRELLIS extensions diff-gaussian-rasterization and nvdiffrast are compiled from
   source for the GPU: `export TORCH_CUDA_ARCH_LIST="8.9"` for L4; delete any stale build/ dirs first; see
   docs/car-3d-pipeline.md "sm_89 rebuild"). Host torch must match the CUDA major (current: torch 2.9.1+cu129).
3. nvidia-container-toolkit, configured for Docker (`docker run --gpus all ... nvidia-smi` works).
4. Vulkan: the NVIDIA Vulkan ICD (ships with the driver) plus vulkan-tools; `vulkaninfo` must list VK_KHR_ray_query
   on each L4 (RTX Remix needs it; the old B200 host failed here).
5. OpenGL: libglvnd, mesa-vulkan-drivers, mesa-utils; VirtualGL (vglrun) for GPU GL inside Xvfb containers.
6. Xvfb must keep GLX on Mesa: set `__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json`
   for Xvfb (the NVIDIA EGL vendor plus libnvidia-egl-gbm segfaults Xvfb); the Dockerfiles already do this.
7. Optional: NVIDIA Video Codec (nvenc) for faster recordings (ffmpeg h264_nvenc); not required.

## After the copy
- Rebuild images: `cd repo && for f in linux/docker/Dockerfile.*; do docker build -f $f ...; done` (see docs/HANDOVER.md section 6 and docs/throughput.md for the fast prefix image).
- Rebuild gen3d/venv (python 3.12) and compile the extensions for sm_89; verify one TRELLIS run.
- Capacity: in repo/linux/docker/runq.sh set GTA2_SLOTS to (vCPUs - 6) / 2 and GTA2_LOAD_MAX to vCPUs x 1.5; keep
  --cpus=1.5 per game container; PLAY_CPUSET = the top 3 vCPUs; cron: cpu_governor.sh (every minute),
  autosync.sh (every 20 min), prune_out.sh (hourly); GPU pinning: Remix on one L4, generation on others
  (CUDA_VISIBLE_DEVICES), game containers round-robin over the rest (--gpus device=N in runq).
- Firewall: replicate allow-jupyter-roni (same source IPs) for tcp 8888, 8090, 8081, 8082, 8811, 8814, 9200, 48620.
- Gate before the play page: `linux/docker/restage.sh` (inventory check + smoke run), then
  `PLAY_BIND=0.0.0.0 PLAY_CPUSET=<top 3 cores> gamerun/play.sh plain 8090`.
- Verify: one slot run with a frame log, a Remix run, a TRELLIS run, `gh issue list`, the play page serving a frame.
