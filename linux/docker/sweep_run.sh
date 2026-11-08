#!/usr/bin/env bash
# sweep_run.sh <district> <chunk i/n> [seconds]: one chunk of the city sweep on the GPU
# image, magenta clear, sky off, devtools keys on. Output: out/sweep_<district>_<i>/
cd "$(dirname "$0")/.."
Dd=$1; CH=$2; S=${3:-900}; I=${CH%/*}; N=sweep_${Dd}_${TAG:-}$I; rm -rf "out/$N"; mkdir -p "out/$N"
SED='s/^log_keys=.*/log_keys=1/; s/^warp_key=.*/warp_key=F9/; s/^scene_key=.*/scene_key=F11/; /^\[sky\]/,/^\[/ s/^enabled=.*/enabled=0/'
# GTA2_DIRECT_KEYS=1 (default here): nav_map=0, so the quarter turns are the game's own Left key
[ "${GTA2_DIRECT_KEYS:-1}" = 1 ] && SED="$SED; s/^nav_map=.*/nav_map=0/"
gamerun/slot.sh sudo -n docker run --rm --gpus '"device=0"' $(gamerun/nv_devices.sh 0) \
  -e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility -e FPS=15 --cpus=4 \
  -e INI_SED="$SED" -e GTA2_DIRECT_KEYS="${GTA2_DIRECT_KEYS:-1}" -e SWAP_LEVEL=$Dd -e GTA2DX9_CLEAR_MAGENTA=1 \
  -e SWEEP_DISTRICT=$Dd -e SWEEP_CHUNK=$CH -e SCENE_KEY=F11 -e GTA2DX9_SCENE_NO_CAR=1 -e SWEEP_PLAN=${SWEEP_PLAN:-/work/sweep_plan_$Dd.json} \
  $([ "${GTA2_FAST:-1}" = 1 ] && ROOT=$PWD STAGE=${STAGE:-$PWD/repo/stage} SWAP_LEVEL=$Dd gamerun/game_mounts.sh) -e GTA2_INTRO="${GTA2_INTRO:-1}" -v "$PWD/gamerun:/work" -v "$PWD/game:/game:ro" -v "$PWD/upstream-release/files:/release:ro" \
  -v "${STAGE:-$PWD/repo/stage}:/stage:ro" -v "$PWD/remix-runtime/x86:/remix:ro" -v "$PWD/out/$N:/out" \
  -w /work ${IMAGE:-$(sudo -n docker image inspect gta2-gpugl-fast >/dev/null 2>&1 && echo gta2-gpugl-fast || echo gta2-gpugl)} bash /work/run_game_gpu.sh win32 "$S" 0 /work/keys_sweep.sh > "out/$N.run.log" 2>&1
echo "$N finished: $(grep -c FAULT out/$N/gta2dx9.log 2>/dev/null) faults, $(wc -l < out/$N/sweep.jsonl 2>/dev/null) points"
