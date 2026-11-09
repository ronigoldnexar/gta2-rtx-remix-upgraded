#!/usr/bin/env bash
# Host side: play the modded game in a browser tab, rendered on this machine's
# NVIDIA GPU.   play.sh [plain|remix] [port]   |   play.sh stop   |   play.sh status
#   plain : the mod's own Direct3D 9 picture through VirtualGL (image gta2-play)
#   remix : RTX Remix path tracing (image gta2-play-remix; ~3 min shader warm-up)
# Then open http://localhost:<port>/ (from another machine: ssh -L <port>:localhost:<port> <host>).
# Env: PLAY_PASSWORD (VNC password), PLAY_DEVTOOLS=1 (F9/F11 warps), GPU (device index, 0),
#      SWAP_LEVEL=bil|ste (start in another district's map), INI_SED / SETTINGS_SED as in the run scripts,
#      PLAY_X11VNC / PLAY_VNC_NICE (the VNC encoder's flags and niceness, see play_game.sh),
#      PLAY_AUDIO=0 (no game sound on the page), PLAY_RTX_PRESET (remix look appended to rtx.conf: rtx_play.conf.extra, or rtx_showcase.conf.extra),
#      PLAY_FRAME_LOG=1 (per-frame log to out/play-<port>/frames.tsv and player state lines, for perf3_play.sh).
set -u
cd "$(dirname "$0")/.."
MODE=${1:-plain}; PORT=${2:-6080}; NAME=${NAME:-gta2-play-$PORT}
DOCKER="sudo -n docker"; $DOCKER version >/dev/null 2>&1 || DOCKER=docker
case "$MODE" in
  stop)   $DOCKER rm -f $($DOCKER ps -q --filter name=gta2-play-) 2>/dev/null; echo "stopped"; exit 0 ;;
  status) $DOCKER ps --filter name=gta2-play- --format '{{.Names}}  {{.Status}}  {{.Ports}}'; exit 0 ;;
  plain)  IMAGE=${PLAY_IMAGE:-gta2-play} ;;
  remix)  IMAGE=${PLAY_IMAGE:-gta2-play-remix} ;;
  *) echo "usage: play.sh [plain|remix] [port] | stop | status"; exit 2 ;;
esac
# The game folder: this working tree's layout (gamerun/ next to game/, repo/stage) or a checkout's (linux/docker next to game/).
if [ -d gamerun ] && [ -d game ]; then WORK=$PWD/gamerun; STAGE=${STAGE:-$PWD/repo/stage}; PKG=$PWD/repo/package; REL=$PWD/upstream-release/files; RMX=$PWD/remix-runtime/x86
else WORK=$PWD/linux/docker; STAGE=${STAGE:-$PWD/stage}; PKG=$PWD/package; REL=${RELEASE_FILES:-$PWD/../upstream-release/files}; RMX=${REMIX_RUNTIME:-$PWD/../remix-runtime/x86}; fi
[ -d "$STAGE/gta2dx9_models" ] || { echo "no staged build at $STAGE (run: make stage)"; exit 1; }
# Gate: refuse a stage that fails the inventory check (PLAY_FORCE=1 overrides, for diagnosis only).
[ "${PLAY_FORCE:-0}" = 1 ] || python3 "$WORK/stage_check.py" "$STAGE" "$(dirname "$STAGE")" || { echo "play.sh: refusing to start on an unhealthy stage"; exit 1; }
$DOCKER rm -f "$NAME" >/dev/null 2>&1
mkdir -p out/play-$PORT
# The NVIDIA driver's GL shader cache, kept on the host: wined3d builds a GL shader for each new
# fixed-function state, and compiling them made the first street-view frames of every session
# freeze for 300-700 ms (PERF-2). With the cache kept they are read back instead.
mkdir -p "$WORK/nv_cache_gl"
$DOCKER run -d --name "$NAME" --gpus "\"device=${GPU:-0}\"" $("$WORK/nv_devices.sh" "${GPU:-0}") -e NVIDIA_DRIVER_CAPABILITIES=all --cpus=${CPUS:-7} ${PLAY_CPUSET:+--cpuset-cpus="$PLAY_CPUSET"} -e SCREEN_W=${SCREEN_W:-$([ "${PLAY_RES:-}" = low ] && echo 960 || echo 1280)} -e SCREEN_H=${SCREEN_H:-$([ "${PLAY_RES:-}" = low ] && echo 540 || echo 720)} \
  -p "${PLAY_BIND:-127.0.0.1}:$PORT:$PORT" ${PLAY_VNC:+-p 127.0.0.1:$PLAY_VNC:5900} -e PLAY_PORT=$PORT -e PLAY_MOUSE="${PLAY_MOUSE:-0}" ${GTA2DX9_LOG_CAMERA:+-e GTA2DX9_LOG_CAMERA=$GTA2DX9_LOG_CAMERA} ${PLAY_FRAME_LOG:+-e 'GTA2DX9_FRAME_LOG=Z:\out\frames.tsv' -e GTA2DX9_STATE_EVERY=5} -e PLAY_PASSWORD="${PLAY_PASSWORD:-}" -e PLAY_DEVTOOLS="${PLAY_DEVTOOLS:-0}" -e PLAY_X11VNC="${PLAY_X11VNC:-}" -e PLAY_VNC_NICE="${PLAY_VNC_NICE:-0}" -e PLAY_AUDIO="${PLAY_AUDIO:-1}" \
  -e SWAP_LEVEL="${SWAP_LEVEL:-}" -e INI_SED="${INI_SED:-}" -e SETTINGS_SED="${SETTINGS_SED:-}" -e MODS_HD="${MODS_HD:-1}" -e PLAY_RTX_PRESET="${PLAY_RTX_PRESET:-rtx_play.conf.extra}" \
  -v "$WORK:/work" -v "$PWD/game:/game:ro" -v "$REL:/release:ro" -v "$STAGE:/stage:ro" -v "$RMX:/remix:ro" -v "$PKG:/package:ro" -v "$PWD/out/play-$PORT:/out" \
  -v "$WORK/nv_cache_gl:/nvcache" -e __GL_SHADER_DISK_CACHE=1 -e __GL_SHADER_DISK_CACHE_PATH=/nvcache -e __GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1 \
  -w /work "$IMAGE" bash /work/play_game.sh "$MODE" >/dev/null || { echo "docker run failed"; exit 1; }
echo "started $NAME ($MODE) on http://localhost:$PORT/"
echo "  from another machine:  ssh -L $PORT:localhost:$PORT $(hostname)   then open http://localhost:$PORT/"
[ "${PLAY_BIND:-127.0.0.1}" = 0.0.0.0 ] && echo "  bound on all interfaces: reachable at http://<this host's address>:$PORT/ from any address your firewall allows"
echo "  the game appears after ~40 s (plain) or ~4 min (remix: shader warm-up); the page's Play button connects."
echo "  stop:  $0 stop      log: $DOCKER logs -f $NAME"
