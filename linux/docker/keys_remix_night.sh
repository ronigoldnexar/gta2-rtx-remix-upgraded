#!/usr/bin/env bash
# Night check of the street views under Remix: level, classic, third person
# looking around, first person walking from the plaza toward the gate and the
# carriageway, looking along the street both ways (lamps, neon, headlights).
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-60}
mark classic; hold Down 2; sleep 4
tap v; mark third; sleep 5; hold Left 1.2; sleep 4; hold Up 3; sleep 3; hold Right 2.4; sleep 4
tap v; mark first; sleep 4; hold Up 4; sleep 2; hold Left 1.2; sleep 4; hold Right 2.4; sleep 4; hold Up 5; sleep 3; hold Left 1.2; sleep 4; hold Up 4; sleep 4
tap v; mark classic_again; sleep 6
mark done
