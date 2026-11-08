#!/usr/bin/env bash
# PERF-2: one district drive at the play container's settings (image gta2-play, CPUs 5-7,
# 1280x720, GTA2_SPEED=1) with the per-frame log on.   perf2_run.sh <name> <wil|bil|ste> [stage dir]
cd "$(dirname "$0")/.."
NAME=$1; DIST=$2; ST=${3:-$PWD/stage_perf}
SED='s/^log_keys=.*/log_keys=1/; s/^warp_key=.*/warp_key=F9/; s/^scene_key=.*/scene_key=F10/; s/^mouse_look=.*/mouse_look=0/'
rm -rf "out/$NAME"
IMAGE=${IMAGE:-gta2-play} CPUS=${CPUS:-3} CPUSET=${CPUSET:-5-7} FPS=${FPS:-15} STAGE=$ST INI_SED="$SED" \
  SWAP_LEVEL=$([ "$DIST" = wil ] || echo "$DIST") GTA2_FAST=${GTA2_FAST:-1} \
  gamerun/grun.sh "$NAME" "${SECS:-230}" keys_perf2_drive.sh -e 'GTA2DX9_FRAME_LOG=Z:\out\frames.tsv' -e GTA2DX9_STATE_EVERY=5 -e DRIVE_SECS=${DRIVE_SECS:-100} ${NVCACHE:+-v $PWD/gamerun/nv_cache_gl:/nvcache -e __GL_SHADER_DISK_CACHE=1 -e __GL_SHADER_DISK_CACHE_PATH=/nvcache -e __GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1} -e ROUTE_SEED=${ROUTE_SEED:-7}
