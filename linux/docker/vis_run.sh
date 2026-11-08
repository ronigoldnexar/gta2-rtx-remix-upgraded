#!/usr/bin/env bash
# VISUALS-PLAIN: a scripted run with the per-frame logs on (GTA2DX9_FRAME_LOG and the post's own
# GTA2DX9_VISUALS_LOG), at the play container's settings (image gta2-play, 1280x720, 3 CPUs) on
# the game CPUs.   vis_run.sh <name> <wil|bil|ste> [stage dir]
#   KEYS   keys script (default keys_perf2_drive.sh: the PERF-2 90-100 s chase-view drive)
#   QUALITY low|medium|high (default: the ini's), VIS 0 turns [visuals] off for the run
cd "$(dirname "$0")/.."
NAME=$1; DIST=$2; ST=${3:-$PWD/repo/stage}
SED='s/^log_keys=.*/log_keys=1/; s/^warp_key=.*/warp_key=F9/; s/^scene_key=.*/scene_key=F10/; s/^mouse_look=.*/mouse_look=0/'
[ -n "${QUALITY:-}" ] && SED="$SED; s/^quality=.*/quality=$QUALITY/"
[ -n "${VIS:-}" ] && SED="$SED; /^\[visuals\]/,/^\[camera\]/ s/^enabled=.*/enabled=$VIS/"
mkdir -p "out/$NAME"; find "out/$NAME" -mindepth 1 -delete
IMAGE=${IMAGE:-gta2-play} CPUS=${CPUS:-3} CPUSET=${CPUSET:-0-4} FPS=${FPS:-15} STAGE=$ST INI_SED="$SED" \
  SWAP_LEVEL=$([ "$DIST" = wil ] || echo "$DIST") GTA2_FAST=${GTA2_FAST:-1} \
  gamerun/grun.sh "$NAME" "${SECS:-230}" "${KEYS:-keys_perf2_drive.sh}" -e 'GTA2DX9_FRAME_LOG=Z:\out\frames.tsv' \
  -e 'GTA2DX9_VISUALS_LOG=Z:\out\visuals.tsv' -e GTA2DX9_STATE_EVERY=5 -e DRIVE_SECS=${DRIVE_SECS:-95} \
  -v $PWD/gamerun/nv_cache_gl:/nvcache -e __GL_SHADER_DISK_CACHE=1 -e __GL_SHADER_DISK_CACHE_PATH=/nvcache -e __GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1 -e ROUTE_SEED=${ROUTE_SEED:-7}
