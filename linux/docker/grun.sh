#!/usr/bin/env bash
# The fast scripted run: queued on the game slots, prebaked prefix, read-only
# data bind-mounted into the prefix (no heavy copies), intro skipped, GPU render.
#   gamerun/grun.sh <name> <seconds> <keys script> [docker -e ...]
# Output in out/<name>. Env: CPUS (2), CPUSET (0-4: the play container keeps 5-7),
# FPS (15), IMAGE (gta2-gpugl-fast), PRIO (5), SWAP_LEVEL, INI_SED, INI_EXTRA, SETTINGS_SED, GTA2_INTRO (0).
NAME=$1; SECS=$2; KEYS=$3; shift 3
cd "$(dirname "$0")/.."; mkdir -p "out/$NAME"
IMAGE=${IMAGE:-gta2-gpugl-fast}; sudo -n docker image inspect "$IMAGE" >/dev/null 2>&1 || IMAGE=gta2-gpugl
exec "$(dirname "$0")/runq.sh" run -p "${PRIO:-5}" -n "$NAME" -- \
  sudo -n docker run --rm --gpus '"device=0"' -e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility \
  --cpus="${CPUS:-2}" ${CPUSET:+--cpuset-cpus="$CPUSET"} -e FPS="${FPS:-15}" -e GTA2_INTRO="${GTA2_INTRO:-0}" \
  -e SWAP_LEVEL="${SWAP_LEVEL:-}" -e INI_SED="${INI_SED:-}" -e INI_EXTRA="${INI_EXTRA:-}" -e SETTINGS_SED="${SETTINGS_SED:-}" \
  $([ "${GTA2_FAST:-1}" = 1 ] && ROOT=$PWD STAGE=${STAGE:-$PWD/repo/stage} SWAP_LEVEL="${SWAP_LEVEL:-}" gamerun/game_mounts.sh) "$@" \
  -v "$PWD/gamerun:/work" -v "$PWD/game:/game:ro" -v "$PWD/upstream-release/files:/release:ro" -v "${STAGE:-$PWD/repo/stage}:/stage:ro" -v "$PWD/remix-runtime/x86:/remix:ro" -v "$PWD/out/$NAME:/out" \
  -w /work "$IMAGE" bash /work/run_game_gpu.sh win32 "$SECS" 0 "/work/$KEYS"
