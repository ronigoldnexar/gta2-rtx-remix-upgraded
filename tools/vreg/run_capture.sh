#!/usr/bin/env bash
# tools/vreg/run_capture.sh <run name> <stage dir> [seconds]
# One capture run through the queue (runq.sh: a game slot, the load and memory gates) on GPU
# $GTA2_GPU (default 0), 1280x720, no video. Output: out/<run name>/vr_*.png, vreg.jsonl, gta2dx9.log.
set -e
NAME=$1; ST=$(cd "$2" && pwd); SECS=${3:-2400}   # wall clock, paused time included (cpu_governor.sh pauses runs); the run ends when the capture is done
HERE=$(cd "$(dirname "$0")" && pwd); R=$(cd "$HERE/../.." && pwd); ROOT=${GTA2_ROOT:-$(cd "$R/.." && pwd)}   # the workspace (game/, gamerun/, out/); GTA2_ROOT when run from a /tmp worktree
GPU=${GTA2_GPU:-0}
# a CPU set of its own (runq pins a run without one to GAME_CPUSET, 0-4 by default: on a big host
# every agent's runs would share five cores). Default: ten cores per GPU index, 10*GPU..10*GPU+9.
CPUSET=${VREG_CPUSET:-$((GPU * 10))-$((GPU * 10 + 9))}
cd "$ROOT"
# the container-side scripts live in repo/linux/docker (tracked); /work is gamerun
for f in vreg_capture.py keys_vreg.sh; do cmp -s "$R/linux/docker/$f" "gamerun/$f" || cp "$R/linux/docker/$f" "gamerun/$f"; done
python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "out/$NAME"; mkdir -p "out/$NAME"
cp "${VREG_SHOTS:-$HERE/shots.json}" "out/$NAME/vreg_shots.json"
SED='s/^log_keys=.*/log_keys=1/; s/^scene_key=.*/scene_key=F11/; s/^nav_map=.*/nav_map=0/'
# VREG_INI_SED: more sed over the run's ini (positive controls: a deliberately broken render)
[ -n "${VREG_INI_SED:-}" ] && SED="$SED; $VREG_INI_SED"
# the lighting clock held at 12:30 with a clear sky: the same light every run (the saved settings
# file overrides the ini; these are its keys, see dll/src/settings.cpp)
SSED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/'
IMAGE=${IMAGE:-gta2-gpugl-fast}; sudo -n docker image inspect "$IMAGE" >/dev/null 2>&1 || IMAGE=gta2-gpugl
gamerun/runq.sh run -p "${PRIO:-5}" -n "$NAME" -- \
  sudo -n docker run --rm --gpus "\"device=$GPU\"" $(gamerun/nv_devices.sh "$GPU") -e NVIDIA_DRIVER_CAPABILITIES=graphics,compute,utility \
  --cpus="${CPUS:-2}" --cpuset-cpus="$CPUSET" --cpu-shares=512 -e FPS=0 -e SHOTS_EVERY=20 -e GTA2_SPEED=1 -e GTA2_DIRECT_KEYS=1 \
  -e SCREEN_W=1280 -e SCREEN_H=720 -e GTA2_INTRO=0 -e INI_SED="$SED" -e SETTINGS_SED="$SSED" -e SCENE_KEY=F11 \
  -e GTA2DX9_SCENE_NO_CAR=1 -e 'GTA2DX9_REGRESS_CAM=Z:\tmp\vreg_cam.txt' -e VREG_CAM=/tmp/vreg_cam.txt \
  -e VREG_SHOTS=/out/vreg_shots.json -e VREG_SETTLE="${VREG_SETTLE:-2.0}" \
  $(ROOT=$ROOT STAGE=$ST gamerun/game_mounts.sh) \
  -v "$ROOT/gamerun:/work" -v "$ROOT/game:/game:ro" -v "$ROOT/upstream-release/files:/release:ro" -v "$ST:/stage:ro" \
  -v "$ROOT/remix-runtime/x86:/remix:ro" -v "$ROOT/out/$NAME:/out" \
  -w /work "$IMAGE" bash /work/run_game_gpu.sh win32 "$SECS" 0 /work/keys_vreg.sh > "out/$NAME.run.log" 2>&1
n=$(ls out/$NAME/vr_*.png 2>/dev/null | wc -l)
echo "$NAME: $n frames, $(grep -c FAULT out/$NAME/gta2dx9.log 2>/dev/null) faults, done=$( [ -f out/$NAME/.vreg_done ] && echo yes || echo no)"
