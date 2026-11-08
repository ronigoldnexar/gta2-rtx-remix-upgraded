#!/usr/bin/env bash
# Prints the docker -v flags that bind the read-only game data straight into the
# prefix path, so a run copies nothing heavy (saves ~7 s and 2 GB of writes per run).
# The container-side run scripts skip the copy of any of these that is a mountpoint.
# data/ is not bound when SWAP_LEVEL is bil|ste (the level swap writes into data/): callers must
# pass SWAP_LEVEL to this script, not only to docker (swap_level.sh refuses a bound data/).
G=/tmp/wp/drive_c/Games/GTA2; R=${ROOT:-$PWD}
case "${SWAP_LEVEL:-}" in ""|wil) printf -- '-v %s:%s:ro ' "$R/game/data" "$G/data";; esac
printf -- '-v %s:%s:ro ' "$R/upstream-release/files/gta2dx9_hd" "$G/gta2dx9_hd" "$R/upstream-release/files/gta2dx9_voice" "$G/gta2dx9_voice" \
  "${STAGE:-$R/repo/stage}/gta2dx9_models" "$G/gta2dx9_models" "${STAGE:-$R/repo/stage}/gta2dx9_textures_hd" "$G/gta2dx9_textures_hd"
