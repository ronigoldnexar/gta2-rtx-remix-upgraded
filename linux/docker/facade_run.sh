#!/usr/bin/env bash
# QB-25: one facade-depth take under Remix. facade_run.sh <name> [MODS_HD_SRC inside the container]
cd "$(dirname "$0")/.."
NAME=$1; SRC=${2:-/work/remix_vis/qb25_gta2hd}
STAGE=${STAGE:-$PWD/repo/stage} gamerun/remix_l4.sh "$NAME" ${SECS:-1300} /work/keys_remix_facade.sh -e MODS_HD=1 -e MODS_HD_SRC="$SRC" \
  -e LEVEL_WAIT=${LEVEL_WAIT:-150} -e RTX_EXTRA=${RTX_EXTRA:-/work/rtx_showcase.conf.extra} \
  -e INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' -e SCENE_KEY=F11 \
  -e SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=14/' \
  -e EFFECTS_SED='/^\[Car lamps\]/,/^\[/{s/^Enabled=0/Enabled=1/;s/^Daylight=0/Daylight=1/}' \
  -e FAC_HOURS="${FAC_HOURS:-14,17.5}" -e FAC_FACTORS="${FAC_FACTORS:-1,0,2,1}" $EXTRA_E
