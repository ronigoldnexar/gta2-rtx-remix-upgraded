#!/usr/bin/env bash
# ANIM-WEAPONS copy of grun.sh that renders on GPU $GTA2_GPU (default 0) instead of 0.
# The fast scripted run: queued on the game slots, prebaked prefix, read-only
# data bind-mounted into the prefix (no heavy copies), intro skipped, GPU render.
#   gamerun/grun.sh <name> <seconds> <keys script> [docker -e ...]
# Output in out/<name>. Env: CPUS (2), CPUSET (0-4: the play container keeps 5-7),
# GTA2_DIRECT_KEYS (0), FPS (15), IMAGE (gta2-gpugl-fast), PRIO (5), SWAP_LEVEL, INI_SED, INI_EXTRA, SETTINGS_SED, GTA2_INTRO (0).
# GTA2_SPEED (1): 2 or 3 plays the game that many times faster (fps_cap 60/90; the runners scale their
# timing); FPS=0 records no video (screenshots every SHOTS_EVERY s, default 5); RES=low renders 960x540.
NAME=$1; SECS=$2; KEYS=$3; shift 3
SPEED=${GTA2_SPEED:-1}
if [ "$SPEED" != 1 ]; then CAP=$(python3 -c "print(int(round(30*float('$SPEED'))))"); INI_SED="${INI_SED:+$INI_SED; }s/^fps_cap=.*/fps_cap=$CAP/"; SETTINGS_SED="${SETTINGS_SED:+$SETTINGS_SED; }s/^FpsCap=.*/FpsCap=$CAP/"; fi   # the saved settings file (FpsCap) overrides the ini
# GTA2_DIRECT_KEYS=1: nav_map=0 for this run (the arrows stay the game's own in the 3D views, so a
# scripted walker, aim and trigger work in third/first person; the runners read the same env)
if [ "${GTA2_DIRECT_KEYS:-0}" = 1 ]; then INI_SED="${INI_SED:+$INI_SED; }s/^nav_map=.*/nav_map=0/"; fi
if [ "${RES:-}" = low ]; then export SCREEN_W=960 SCREEN_H=540; fi
cd "$(dirname "$0")/.."; mkdir -p "out/$NAME"
IMAGE=${IMAGE:-gta2-gpugl-fast}; sudo -n docker image inspect "$IMAGE" >/dev/null 2>&1 || IMAGE=gta2-gpugl
exec "$(dirname "$0")/runq.sh" run -p "${PRIO:-5}" -n "$NAME" -- \
  sudo -n docker run --rm --gpus "device=${GTA2_GPU:-0}" $(gamerun/nv_devices.sh ${GTA2_GPU:-0}) -e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility \
  --cpus="${CPUS:-1.5}" --cpu-shares=512 ${CPUSET:+--cpuset-cpus="$CPUSET"} -e FPS="${FPS:-15}" -e SHOTS_EVERY="${SHOTS_EVERY:-5}" -e GTA2_SPEED="$SPEED" -e GTA2_DIRECT_KEYS="${GTA2_DIRECT_KEYS:-0}" -e SCREEN_W="${SCREEN_W:-1280}" -e SCREEN_H="${SCREEN_H:-720}" -e GTA2_INTRO="${GTA2_INTRO:-0}" \
  -e SWAP_LEVEL="${SWAP_LEVEL:-}" -e INI_SED="${INI_SED:-}" -e INI_EXTRA="${INI_EXTRA:-}" -e SETTINGS_SED="${SETTINGS_SED:-}" \
  $([ "${GTA2_FAST:-1}" = 1 ] && ROOT=$PWD STAGE=${STAGE:-$PWD/repo/stage} SWAP_LEVEL="${SWAP_LEVEL:-}" gamerun/game_mounts.sh) "$@" \
  -v "$PWD/gamerun:/work" -v "$PWD/game:/game:ro" -v "$PWD/upstream-release/files:/release:ro" -v "${STAGE:-$PWD/repo/stage}:/stage:ro" -v "$PWD/remix-runtime/x86:/remix:ro" -v "$PWD/out/$NAME:/out" \
  -w /work "$IMAGE" bash /work/run_game_gpu.sh win32 "$SECS" 0 "/work/$KEYS"
