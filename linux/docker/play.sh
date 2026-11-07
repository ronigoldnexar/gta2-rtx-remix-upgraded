#!/usr/bin/env bash
# Host side: play the modded game in a browser tab, rendered on this machine's
# NVIDIA GPU.   play.sh [plain|remix] [port]   |   play.sh stop   |   play.sh status
#   plain : the mod's own Direct3D 9 picture through VirtualGL (image gta2-play)
#   remix : RTX Remix path tracing (image gta2-play-remix; ~3 min shader warm-up)
# Then open http://localhost:<port>/ (from another machine: ssh -L <port>:localhost:<port> <host>).
# Env: PLAY_PASSWORD (VNC password), PLAY_DEVTOOLS=1 (F9/F11 warps), GPU (device index, 0),
#      SWAP_LEVEL=bil|ste (start in another district's map), INI_SED / SETTINGS_SED as in the run scripts.
set -u
cd "$(dirname "$0")/.."
MODE=${1:-plain}; PORT=${2:-6080}; NAME=gta2-play-$PORT
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
$DOCKER rm -f "$NAME" >/dev/null 2>&1
mkdir -p out/play-$PORT
$DOCKER run -d --name "$NAME" --gpus "\"device=${GPU:-0}\"" -e NVIDIA_DRIVER_CAPABILITIES=all --cpus=${CPUS:-7} -e SCREEN_W=${SCREEN_W:-$([ "${PLAY_RES:-}" = low ] && echo 960 || echo 1280)} -e SCREEN_H=${SCREEN_H:-$([ "${PLAY_RES:-}" = low ] && echo 540 || echo 720)} \
  -p "${PLAY_BIND:-127.0.0.1}:$PORT:$PORT" ${PLAY_VNC:+-p 127.0.0.1:$PLAY_VNC:5900} -e PLAY_PORT=$PORT -e PLAY_MOUSE="${PLAY_MOUSE:-0}" ${GTA2DX9_LOG_CAMERA:+-e GTA2DX9_LOG_CAMERA=$GTA2DX9_LOG_CAMERA} -e PLAY_PASSWORD="${PLAY_PASSWORD:-}" -e PLAY_DEVTOOLS="${PLAY_DEVTOOLS:-0}" \
  -e SWAP_LEVEL="${SWAP_LEVEL:-}" -e INI_SED="${INI_SED:-}" -e SETTINGS_SED="${SETTINGS_SED:-}" -e MODS_HD="${MODS_HD:-1}" \
  -v "$WORK:/work" -v "$PWD/game:/game:ro" -v "$REL:/release:ro" -v "$STAGE:/stage:ro" -v "$RMX:/remix:ro" -v "$PKG:/package:ro" -v "$PWD/out/play-$PORT:/out" \
  -w /work "$IMAGE" bash /work/play_game.sh "$MODE" >/dev/null || { echo "docker run failed"; exit 1; }
echo "started $NAME ($MODE) on http://localhost:$PORT/"
echo "  from another machine:  ssh -L $PORT:localhost:$PORT $(hostname)   then open http://localhost:$PORT/"
[ "${PLAY_BIND:-127.0.0.1}" = 0.0.0.0 ] && echo "  bound on all interfaces: reachable at http://<this host's address>:$PORT/ from any address your firewall allows"
echo "  the game appears after ~40 s (plain) or ~4 min (remix: shader warm-up); the page's Play button connects."
echo "  stop:  $0 stop      log: $DOCKER logs -f $NAME"
