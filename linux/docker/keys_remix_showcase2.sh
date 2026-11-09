#!/usr/bin/env bash
# REMIX-SHOWCASE: the key library brings the game to the level, then remix_showcase2.py plays
# the showcase take (hours x spots, beacons at night, the showcase preset) for one district.
# Needs INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/',
# SCENE_KEY=F11, SETTINGS_SED Paused=1, RTX_EXTRA=/work/rtx_play.conf.extra.
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-30}
python3 /work/remix_showcase2.py
mark done
