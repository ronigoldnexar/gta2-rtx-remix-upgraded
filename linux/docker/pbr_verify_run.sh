#!/usr/bin/env bash
# REMIX-CARPROPS-PBR: one verification session (vremix_run.sh's settings, keys_remix_pbr.sh).
#   pbr_verify_run.sh <name> [MODS_HD_SRC in the container] ; env PBR_TAKE=1 for the close-ups,
#   RTX_EXTRA=<conf> (e.g. /work/rtx_nodisp.conf.extra: displacement off, for the frame cost), SECS.
cd "$(dirname "$0")/.."   # workspace root; STAGE (default repo/stage) picks the stage
NAME=$1; SRC=${2:-/package/rtx-remix/mods/gta2hd}
STAGE=${STAGE:-$PWD/repo/stage} gamerun/remix_l4.sh "$NAME" ${SECS:-900} /work/keys_remix_pbr.sh -e MODS_HD=1 -e MODS_HD_SRC="$SRC" \
  -e LEVEL_WAIT=60 -e RTX_EXTRA=${RTX_EXTRA:-/work/rtx_showcase.conf.extra} \
  -e INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' -e SCENE_KEY=F11 \
  -e SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=14/' \
  -e EFFECTS_SED='/^\[Car lamps\]/,/^\[/{s/^Enabled=0/Enabled=1/;s/^Daylight=0/Daylight=1/}' \
  -e VIS_HOURS="${VIS_HOURS:-14,22}" -e PBR_TAKE="${PBR_TAKE:-0}" -e 'GTA2DX9_FRAME_LOG=Z:\out\frames.tsv'
