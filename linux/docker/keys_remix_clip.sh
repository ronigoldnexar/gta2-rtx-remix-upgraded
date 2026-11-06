#!/usr/bin/env bash
# The Remix clip: classic by the plaza with a short walk, V to third person (walk,
# turn, look at the street), V to first person (walk along the plaza toward the
# gate and the street, look round), V back to classic. Marks in /out/marks.txt.
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-20}
mark classic; hold Down 2.5; sleep 1; hold Left 0.8; sleep 1; hold Up 3; sleep 3
tap v; mark third; sleep 5; hold Up 3; sleep 2; hold Right 1.2; sleep 2; hold Up 4; sleep 2; hold Left 1.2; sleep 3; hold Up 3; sleep 3
tap v; mark first; sleep 4; hold Up 3; sleep 2; hold Left 1.2; sleep 3; hold Up 4; sleep 2; hold Right 2.4; sleep 3; hold Up 4; sleep 2; hold Left 1.2; sleep 4
tap v; mark classic_again; sleep 4; hold Up 2; sleep 5
mark done
