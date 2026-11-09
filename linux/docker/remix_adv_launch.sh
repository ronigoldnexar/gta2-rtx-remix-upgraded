#!/usr/bin/env bash
# REMIX-ADVANCED session launcher (copy to gamerun/remix_adv_launch.sh with remix_adv.py,
# keys_remix_adv.sh, rtx_advanced.conf.extra).  usage: <name> <secs> <tag> <preset file in gamerun>
# e.g.  remix_adv_launch.sh radv_before 1500 before rtx_play.conf.extra
#       remix_adv_launch.sh radv_after  1500 after  rtx_advanced.conf.extra
# Downtown, StartHour 12.5 paused with a clear sky (the start-up that gave the sunless REMIX-SHOWCASE
# frames), per-frame log in out/<name>/frames.tsv. GPU: REMIX_GPU (default $GTA2_GPU or 0).
cd /mnt/gta2/gta2-linux
N=$1; S=$2; T=$3; P=$4; shift 4
STAGE=${STAGE:-/mnt/gta2/gta2-linux/stage_remixadv} REMIX_GPU=${REMIX_GPU:-${GTA2_GPU:-0}} gamerun/remix_l4.sh "$N" "$S" /work/keys_remix_adv.sh \
  -e MODS_HD=1 -e LEVEL_WAIT=30 -e RTX_EXTRA=/work/$P -e ADV_BASE=/work/$P -e ADV_TAG="$T" -e GTA2_DIRECT_KEYS=1 \
  -e SCENE_KEY=F11 -e 'GTA2DX9_FRAME_LOG=Z:\out\frames.tsv' \
  -e "INI_SED=s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/" \
  -e "SETTINGS_SED=s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/" "$@"
