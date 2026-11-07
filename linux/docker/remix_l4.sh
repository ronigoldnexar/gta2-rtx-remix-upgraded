#!/usr/bin/env bash
# Host-side launcher: RTX Remix on this machine's NVIDIA L4, inside the patched
# Wine 10 image, in one of the game-run slots.  remix_l4.sh <out name> <seconds> [keys script] [extra docker -e flags...]
cd "$(dirname "$0")/.."; NAME=$1; SECS=$2; KEYS=${3:-/work/keys_remix_gpu.sh}; shift 3 2>/dev/null
rm -rf "out/$NAME"; mkdir -p "out/$NAME"
gamerun/slot.sh sudo -n docker run --rm --gpus '"device=0"' -e NVIDIA_DRIVER_CAPABILITIES=all --cpus=4 "$@" \
  $([ "${GTA2_FAST:-1}" = 1 ] && ROOT=$PWD STAGE=${STAGE:-$PWD/repo/stage} gamerun/game_mounts.sh) -e GTA2_INTRO="${GTA2_INTRO:-1}" -v "$PWD/gamerun:/work" -v "$PWD/game:/game:ro" -v "$PWD/upstream-release/files:/release:ro" -v "${STAGE:-$PWD/repo/stage}:/stage:ro" \
  -v "$PWD/remix-runtime/x86:/remix:ro" -v "$PWD/repo/package:/package:ro" -v "$PWD/out/$NAME:/out" -w /work \
  ${REMIX_IMAGE:-gta2-remix-gpu2} bash /work/run_game_remix_gpu.sh "$SECS" "$KEYS" > "out/$NAME.run.log" 2>&1
grep -v "ALSA\|fixme\|Parent window\|GTA2\|^t=" "out/$NAME.run.log" | tail -12
