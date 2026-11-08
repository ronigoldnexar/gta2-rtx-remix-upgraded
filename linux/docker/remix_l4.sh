#!/usr/bin/env bash
# Host-side launcher: RTX Remix on this machine's NVIDIA L4, inside the patched
# Wine 10 image, in one of the game-run slots, holding the GPU lock (/tmp/gta2-gpu.lock) for the whole session.  remix_l4.sh <out name> <seconds> [keys script] [extra docker -e flags...]
cd "$(dirname "$0")/.."; NAME=$1; SECS=$2; KEYS=${3:-/work/keys_remix_gpu.sh}; shift 3 2>/dev/null
rm -rf "out/$NAME"; mkdir -p "out/$NAME"
for a in "$@"; do case "$a" in SWAP_LEVEL=*) export "$a";; esac; done   # -e SWAP_LEVEL=x: the level swap writes into data/, so game_mounts.sh must not mount it read-only
flock /tmp/gta2-gpu.lock gamerun/slot.sh sudo -n docker run --rm --gpus '"device=0"' -e NVIDIA_DRIVER_CAPABILITIES=all --cpus=4 "$@" \
  $([ "${GTA2_FAST:-1}" = 1 ] && ROOT=$PWD STAGE=${STAGE:-$PWD/repo/stage} gamerun/game_mounts.sh) -e GTA2_INTRO="${GTA2_INTRO:-1}" -v "$PWD/gamerun:/work" -v "$PWD/game:/game:ro" -v "$PWD/upstream-release/files:/release:ro" -v "${STAGE:-$PWD/repo/stage}:/stage:ro" \
  -v "$PWD/remix-runtime/x86:/remix:ro" -v "$PWD/repo/package:/package:ro" -v "$PWD/out/$NAME:/out" -w /work \
  ${REMIX_IMAGE:-gta2-remix-gpu2} bash /work/run_game_remix_gpu.sh "$SECS" "$KEYS" > "out/$NAME.run.log" 2>&1
grep -v "ALSA\|fixme\|Parent window\|GTA2\|^t=" "out/$NAME.run.log" | tail -12
