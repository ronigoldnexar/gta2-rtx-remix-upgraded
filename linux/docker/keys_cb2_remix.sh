#!/usr/bin/env bash
# FIX-COCKPIT-BODY-2 order 6: the cockpit body and the dashcam under Remix (cbody_probe.py after the Remix level-up).
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-10}
xdotool mousemove 603 578 click 1; sleep 1; xdotool windowfocus --sync "$W" 2>/dev/null; xdotool windowactivate "$W" 2>/dev/null
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-30}
python3 /work/remix_shaders_wait.py views 600
SCENE_KEY=F11 python3 /work/cbody_probe.py
mark done
