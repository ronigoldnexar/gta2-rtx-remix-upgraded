#!/usr/bin/env bash
# PERF-3: the PERF-2 drive with dents and doors forced while driving (perf3_drive.py), per-frame
# log on, at the play container's settings but on the game CPUs (0-4: 5-7 are the player's).
#   perf3_run.sh <name> <wil|bil|ste> [stage dir]     KEYS=keys_perf2_drive.sh for the plain drive
cd "$(dirname "$0")/.."
NAME=$1; DIST=$2; ST=${3:-$PWD/repo/stage}
SED='s/^log_keys=.*/log_keys=1/; s/^warp_key=.*/warp_key=F9/; s/^scene_key=.*/scene_key=F10/; s/^mouse_look=.*/mouse_look=0/'
mkdir -p "out/$NAME"; find "out/$NAME" -mindepth 1 -delete
IMAGE=${IMAGE:-gta2-play} CPUS=${CPUS:-3} CPUSET=${CPUSET:-0-4} FPS=${FPS:-15} STAGE=$ST INI_SED="$SED" \
  SWAP_LEVEL=$([ "$DIST" = wil ] || echo "$DIST") GTA2_FAST=${GTA2_FAST:-1} \
  gamerun/grun.sh "$NAME" "${SECS:-230}" "${KEYS:-keys_perf3_drive.sh}" -e 'GTA2DX9_FRAME_LOG=Z:\out\frames.tsv' -e GTA2DX9_STATE_EVERY=5 -e DRIVE_SECS=${DRIVE_SECS:-100} ${DAMAGE_STEPS:+-e DAMAGE_STEPS=$DAMAGE_STEPS} \
  -v $PWD/gamerun/nv_cache_gl:/nvcache -e __GL_SHADER_DISK_CACHE=1 -e __GL_SHADER_DISK_CACHE_PATH=/nvcache -e __GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1 -e ROUTE_SEED=${ROUTE_SEED:-7}
