#!/usr/bin/env bash
# Short Remix check: level, classic idle, third person, first person; marks.
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-15}
hold Down 2; sleep 6
tap v; mark third; sleep 10; hold Left 1.2; sleep 6
tap v; mark first; sleep 8; hold Right 1.2; sleep 6; hold Up 2; sleep 6
mark done
