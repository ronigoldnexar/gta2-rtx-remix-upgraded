#!/usr/bin/env bash
# A recording meant for people (FIX-PERF-2, owner blocker "gameplay is jerky"): gamerun/grun.sh with
# what the play page already has, so the video shows the game as a player sees it.
#   gamerun/rec_grun.sh <name> <seconds> <keys script> [docker -e ...]
# - CPUS 8 (grun.sh's default since 9 Nov 19:25; at 1.5 the game and the 30 fps recorder shared one
#   quota and frames came in 100 ms steps), on REC_CPUSET when given (idle cores of your own).
# - FPS 30, PRIO 1.
# - The NVIDIA driver's GL shader cache kept on the host (gamerun/nv_cache_rec, seeded once from the
#   play page's gamerun/nv_cache_gl): wined3d makes a GL program for every new fixed-function state
#   and the driver compiled each one in the run's first frames that used it, 50-850 ms each time
#   (the first V, the first person view, the driver's seat). play.sh mounts its cache; grun.sh does
#   not, so every scripted capture paid them all again. docs/throughput.md "Recordings for people".
# Every other grun.sh variable (GTA2_GPU, STAGE, GTA2_DIRECT_KEYS, INI_SED ...) passes through.
cd "$(dirname "$0")/.."
CACHE=${REC_NVCACHE:-$PWD/gamerun/nv_cache_rec}
if [ ! -d "$CACHE/GLCache" ] && [ -d gamerun/nv_cache_gl/GLCache ]; then
  mkdir -p "$CACHE" && cp -a gamerun/nv_cache_gl/. "$CACHE/"
fi
mkdir -p "$CACHE"
NAME=$1; SECS=$2; KEYS=$3; shift 3
CPUS=${CPUS:-8} CPUSET=${REC_CPUSET:-${CPUSET:-}} FPS=${FPS:-30} PRIO=${PRIO:-1} \
  exec gamerun/grun.sh "$NAME" "$SECS" "$KEYS" \
  -v "$CACHE:/nvcache" -e __GL_SHADER_DISK_CACHE=1 -e __GL_SHADER_DISK_CACHE_PATH=/nvcache \
  -e __GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1 "$@"
