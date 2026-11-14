#!/usr/bin/env bash
# ini-sed: s/^scene_key=.*/scene_key=F11/; s/^log_keys=.*/log_keys=1/
# DISTRICTS round 6 drive under RTX Remix (gta2-rtx6000): level up as rn_keys.sh does, wait for the level's shaders,
# then districts_drive.py (DK_ROUTE: the round-5 city route).
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-10}
xdotool mousemove 603 578 click 1; sleep 1; xdotool windowfocus --sync "$W" 2>/dev/null; xdotool windowactivate "$W" 2>/dev/null
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-20}
python3 /work/remix_shaders_wait.py recheck 300
python3 -u /work/districts_drive.py
mark done
touch /out/.keys_done
