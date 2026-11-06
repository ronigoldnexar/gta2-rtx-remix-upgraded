#!/usr/bin/env bash
# Hash probe: level, classic, a capture (Ctrl+Shift+Q), third person, first person at a wall, a second capture.
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-15}
xdotool keydown ctrl keydown shift key q keyup shift keyup ctrl; mark capture1; sleep 25
tap v; mark third; sleep 8; hold Left 1.2; sleep 6
tap v; mark first; sleep 6; hold Right 1.0; sleep 4; hold Up 2; sleep 6
xdotool keydown ctrl keydown shift key q keyup shift keyup ctrl; mark capture2; sleep 25
mark done
