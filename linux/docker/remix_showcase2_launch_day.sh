#!/usr/bin/env bash
# REMIX-SHOWCASE daytime session: lightbar2b_a's sunny set-up (StartHour 14, no ClearSky or car-lamp
# overrides) with the play preset.  usage: <name> <secs> <SWAP_LEVEL> <TAG> <SPOTS> [extra docker -e ...]
cd /mnt/gta2/gta2-linux
N=$1; S=$2; L=$3; T=$4; P=$5; shift 5
STAGE=/mnt/gta2/gta2-linux/stage_rshow REMIX_GPU=0 gamerun/remix_l4.sh "$N" "$S" /work/keys_remix_showcase2.sh \
  -e MODS_HD=1 -e LEVEL_WAIT=30 -e RTX_EXTRA=${RTX_EXTRA:-/work/rtx_play.conf.extra} -e GTA2_DIRECT_KEYS=1 \
  -e SWAP_LEVEL="$L" -e SHOW_TAG="$T" -e "SHOW_SPOTS=$P" -e SCENE_KEY=F11 \
  -e "INI_SED=s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/" \
  -e "SETTINGS_SED=s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=14/" "$@"
