#!/usr/bin/env bash
# Runs GTA2 with the mod and RTX Remix in the gta2-remix-gpu container on a
# Linux desktop with an RTX (or RDNA2+) GPU, presenting to the host display.
#
#   linux/docker/run_remix_gpu.sh --game ~/GTA2 --release ~/GTA2_RTX_Upgraded_v1.1 \
#       --stage ./stage --remix ~/Remix_Plus_x86 [--amd]
#
# UNTESTED on real hardware in this repository; see linux/README.md.
set -euo pipefail
GAME=""; RELEASE=""; STAGE="$(pwd)/stage"; REMIX=""; AMD=0; OUT="$(pwd)/out-remix-gpu"
while [ $# -gt 0 ]; do
  case "$1" in
    --game) GAME="$2"; shift 2;; --release) RELEASE="$2"; shift 2;; --stage) STAGE="$2"; shift 2;;
    --remix) REMIX="$2"; shift 2;; --out) OUT="$2"; shift 2;; --amd) AMD=1; shift;;
    *) echo "unknown option $1" >&2; exit 1;;
  esac
done
for v in GAME RELEASE REMIX; do [ -n "${!v}" ] || { echo "--$(echo $v | tr A-Z a-z) is required" >&2; exit 1; }; done
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"
GPU_ARGS=(--gpus all -e NVIDIA_DRIVER_CAPABILITIES=all -e ICD_JSON=/usr/share/vulkan/icd.d/nvidia_icd.json)
[ "$AMD" = 1 ] && GPU_ARGS=(--device /dev/dri -e ICD_JSON=/usr/share/vulkan/icd.d/radeon_icd.x86_64.json)
xhost +local:docker >/dev/null 2>&1 || true
docker run --rm -it "${GPU_ARGS[@]}" \
  -e DISPLAY="$DISPLAY" -v /tmp/.X11-unix:/tmp/.X11-unix \
  -e HOST_DISPLAY=1 \
  -v "$HERE:/work" -v "$GAME:/game:ro" -v "$RELEASE:/release:ro" -v "$STAGE:/stage:ro" -v "$REMIX:/remix:ro" -v "$OUT:/out" \
  -w /work gta2-remix-gpu bash /work/run_game.sh win64 1800 1
