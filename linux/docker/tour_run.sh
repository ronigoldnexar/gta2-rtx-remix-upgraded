#!/usr/bin/env bash
# tour_run.sh <district bil|ste> <seconds>: one district tour on the GPU image, devtools keys on.
cd "$(dirname "$0")/.."
Dd=$1; S=$2; K=${3:-$Dd}; N=tour_${K}_$Dd; rm -rf "out/$N"; mkdir -p "out/$N"
SED='s/^log_keys=.*/log_keys=1/; s/^warp_key=.*/warp_key=F9/; s/^scene_key=.*/scene_key=F10/'
gamerun/slot.sh sudo -n docker run --rm --gpus '"device=0"' \
  -e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility -e FPS=30 --cpus=4 \
  -e INI_SED="$SED" -e SWAP_LEVEL=$Dd \
  $([ "${GTA2_FAST:-1}" = 1 ] && ROOT=$PWD STAGE=${STAGE:-$PWD/repo/stage} gamerun/game_mounts.sh) -e GTA2_INTRO="${GTA2_INTRO:-1}" -v "$PWD/gamerun:/work" -v "$PWD/game:/game:ro" -v "$PWD/upstream-release/files:/release:ro" \
  -v "$PWD/repo/stage:/stage:ro" -v "$PWD/remix-runtime/x86:/remix:ro" -v "$PWD/out/$N:/out" \
  -w /work ${IMAGE:-$(sudo -n docker image inspect gta2-gpugl-fast >/dev/null 2>&1 && echo gta2-gpugl-fast || echo gta2-gpugl)} bash /work/run_game_gpu.sh win32 "$S" 0 "/work/keys_tour_$K.sh" > "out/$N.run.log" 2>&1
echo "$N finished: $(grep -c FAULT out/$N/gta2dx9.log 2>/dev/null) faults"
