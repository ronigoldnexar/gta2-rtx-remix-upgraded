#!/usr/bin/env bash
# ini-sed: s/^scene_key=.*/scene_key=F11/; s/^facade_kit=.*/facade_kit=1/; s/^log_keys=.*/log_keys=1/
# DISTRICTS-POC under RTX Remix (gta2-rtx6000): level up as rn_keys.sh does, wait for the level's shaders, then
# districts_capture.py (DK_POINTS, the same frames as the plain-renderer capture).
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-10}
xdotool mousemove 603 578 click 1; sleep 1; xdotool windowfocus --sync "$W" 2>/dev/null; xdotool windowactivate "$W" 2>/dev/null
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-20}
python3 /work/remix_shaders_wait.py recheck 300
python3 -u /work/districts_capture.py
mark done
touch /out/.keys_done
