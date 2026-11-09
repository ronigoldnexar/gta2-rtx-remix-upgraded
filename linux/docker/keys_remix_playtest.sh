#!/usr/bin/env bash
# PLAYTEST-REMIX: level up through remix_keys_lib.sh, then remix_playtest.py (needs SCENE_KEY=F11 in INI_SED).
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-10}   # the launcher held this script back until the shaders were compiled (remix_shaders_wait.py)
xdotool mousemove 603 578 click 1; sleep 1; xdotool windowfocus --sync "$W" 2>/dev/null; xdotool windowactivate "$W" 2>/dev/null
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-30}
python3 /work/remix_shaders_wait.py views 600   # level and street-view shaders compile on first sight: held here, not in a shot (FIX-REMIX-NIGHT)
python3 /work/remix_playtest.py
mark done
