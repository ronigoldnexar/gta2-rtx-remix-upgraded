#!/usr/bin/env bash
# REMIX-ADVANCED: the key library brings the game to the Downtown level, then remix_adv.py plays
# the matched before/after take. Needs INI_SED (scene_key=F11, warp_key=F9, nav_map=0),
# SCENE_KEY=F11, SETTINGS_SED Paused=1 StartHour=12.5, RTX_EXTRA=<start preset>, ADV_BASE=<same>.
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-30}
python3 /work/remix_adv.py
mark done
