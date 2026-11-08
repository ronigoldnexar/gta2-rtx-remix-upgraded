#!/usr/bin/env bash
# qa_run.sh <name> <seconds> [keys script name]: one QA scenario in its own container,
# devtools keys on, on the GPU image (VirtualGL on the NVIDIA card), slot-locked so at
# most two game containers run on this host. QA_DISTRICT=bil|ste swaps the district in,
# QA_SED appends extra sed over the ini, QA_CPUS caps the container (default 4),
# STAGE=<dir> runs a private stage copy (default repo/stage).
# QA_ENV passes extra `-e NAME=value` flags to the scenario (SOAK_SECONDS, SOAK_TAG, TALL_TRIES).
# The run's files land in out/qa_<name>/.
cd "$(dirname "$0")/.."
N=$1; S=$2; K=${3:-$N}; rm -rf "out/qa_$N"; mkdir -p "out/qa_$N"
SED='s/^log_keys=.*/log_keys=1/; s/^warp_key=.*/warp_key=F9/; s/^scene_key=.*/scene_key=F10/'
# GTA2_DIRECT_KEYS=1 (default here): nav_map=0, the arrows stay the game's own in the 3D views
# (the scenarios turn and walk with them); 0 keeps the shipped camera-relative controls.
[ "${GTA2_DIRECT_KEYS:-1}" = 1 ] && SED="$SED; s/^nav_map=.*/nav_map=0/"
[ -n "$QA_SED" ] && SED="$SED; $QA_SED"
gamerun/slot.sh sudo -n docker run --rm --gpus '"device=0"' \
  -e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility -e FPS=${QA_FPS:-15} --cpus=${QA_CPUS:-4} \
  -e INI_SED="$SED" -e GTA2_DIRECT_KEYS="${GTA2_DIRECT_KEYS:-1}" ${QA_DISTRICT:+-e SWAP_LEVEL=$QA_DISTRICT} ${QA_ENV} \
  $([ "${GTA2_FAST:-1}" = 1 ] && ROOT=$PWD STAGE=${STAGE:-$PWD/repo/stage} SWAP_LEVEL="${QA_DISTRICT:-}" gamerun/game_mounts.sh) -e GTA2_INTRO="${GTA2_INTRO:-1}" -v "$PWD/gamerun:/work" -v "$PWD/game:/game:ro" -v "$PWD/upstream-release/files:/release:ro" \
  -v "${STAGE:-$PWD/repo/stage}:/stage:ro" -v "$PWD/remix-runtime/x86:/remix:ro" -v "$PWD/out/qa_$N:/out" \
  -w /work ${IMAGE:-$(sudo -n docker image inspect gta2-gpugl-fast >/dev/null 2>&1 && echo gta2-gpugl-fast || echo gta2-gpugl)} bash /work/run_game_gpu.sh win32 "$S" 0 "/work/keys_qa_$K.sh" > "out/qa_$N.run.log" 2>&1
echo "qa_$N finished: $(grep -c FAULT "out/qa_$N/gta2dx9.log" 2>/dev/null) faults"
grep "CHECK\|RESULT\|done" "out/qa_$N/keys.log" 2>/dev/null | tail -4
