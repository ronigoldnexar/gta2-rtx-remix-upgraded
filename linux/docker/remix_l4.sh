#!/usr/bin/env bash
# Host-side launcher: RTX Remix on this machine's NVIDIA L4, inside the patched
# Wine 10 image, in one of the game-run slots, holding THIS GPU's lock (/tmp/gta2-gpu<N>-remix.lock, N = REMIX_GPU) for the whole session; the old global /tmp/gta2-gpu.lock serialised every Remix run on the 8-GPU host (PLAYTEST-REMIX-3, 14:15 UTC).  remix_l4.sh <out name> <seconds> [keys script] [extra docker -e flags...]
cd "$(dirname "$0")/.."; NAME=$1; SECS=$2; KEYS=${3:-/work/keys_remix_gpu.sh}; shift 3 2>/dev/null
# REMIX_NVCACHE=1: keep the NVIDIA driver's shader cache (/root/.nv, /root/.cache) between runs (gamerun/nv_cache): a warm cache makes the "Compiling shaders" wait seconds, not minutes (docs/throughput.md "Remix")
NVC=; [ "${REMIX_NVCACHE:-0}" = 1 ] && { mkdir -p "$PWD/gamerun/nv_cache/nv" "$PWD/gamerun/nv_cache/cache"; NVC="-v $PWD/gamerun/nv_cache/nv:/root/.nv -v $PWD/gamerun/nv_cache/cache:/root/.cache"; }
rm -rf "out/$NAME"; mkdir -p "out/$NAME"
for a in "$@"; do case "$a" in SWAP_LEVEL=*) export "$a";; esac; done   # -e SWAP_LEVEL=x: the level swap writes into data/, so game_mounts.sh must not mount it read-only
# The NVIDIA device nodes are also passed with --device, so they are in Docker's own device rules: a
# `docker update` (cpu_governor.sh changes the cpuset every minute) rewrites the cgroup-v2 device filter from
# those rules and drops the nodes the NVIDIA hook added; the driver re-opens /dev/nvidiaN for host-visible
# mappings, gets EPERM, and Remix dies with "DxvkCommandList: Failed to create fence" (REMIX-VERIFY, 8 Nov).
NVDEV="--device /dev/nvidia${REMIX_GPU:-0} --device /dev/nvidiactl --device /dev/nvidia-uvm --device /dev/nvidia-uvm-tools --device /dev/nvidia-modeset"
flock /tmp/gta2-gpu${REMIX_GPU:-0}-remix.lock gamerun/slot.sh sudo -n docker run --rm --gpus "\"device=${REMIX_GPU:-0}\"" $NVDEV -e NVIDIA_DRIVER_CAPABILITIES=all --cpus=4 "$@" $NVC \
  $([ "${GTA2_FAST:-1}" = 1 ] && ROOT=$PWD STAGE=${STAGE:-$PWD/repo/stage} gamerun/game_mounts.sh) -e GTA2_INTRO="${GTA2_INTRO:-1}" -v "$PWD/gamerun:/work" -v "$PWD/game:/game:ro" -v "$PWD/upstream-release/files:/release:ro" -v "${STAGE:-$PWD/repo/stage}:/stage:ro" \
  -v "$PWD/remix-runtime/x86:/remix:ro" -v "$PWD/repo/package:/package:ro" -v "$PWD/out/$NAME:/out" -w /work \
  ${REMIX_IMAGE:-gta2-remix-gpu2} bash /work/run_game_remix_gpu.sh "$SECS" "$KEYS" > "out/$NAME.run.log" 2>&1
grep -v "ALSA\|fixme\|Parent window\|GTA2\|^t=" "out/$NAME.run.log" | tail -12
