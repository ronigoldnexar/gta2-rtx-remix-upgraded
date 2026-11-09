#!/usr/bin/env bash
# usage: rshow_launch.sh <name> <secs> <SWAP_LEVEL> <TAG> <SPOTS>
cd /mnt/gta2/gta2-linux
STAGE=/mnt/gta2/gta2-linux/stage_rshow REMIX_GPU=0 gamerun/remix_l4.sh "$1" "$2" /work/keys_remix_showcase2.sh \
  -e MODS_HD=1 -e LEVEL_WAIT=30 -e RTX_EXTRA=/work/rtx_play.conf.extra -e GTA2_DIRECT_KEYS=1 \
  -e SWAP_LEVEL="$3" -e SHOW_TAG="$4" -e "SHOW_SPOTS=$5" -e SCENE_KEY=F11 \
  -e "INI_SED=s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/" \
  -e "SETTINGS_SED=s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=${CLEARSKY:-1}/" \
  -e "EFFECTS_SED=/^\[Car lamps\]/,/^\[/{s/^Enabled=0/Enabled=1/;s/^Daylight=0/Daylight=1/}"
