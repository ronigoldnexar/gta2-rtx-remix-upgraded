#!/usr/bin/env bash
# Remix look development: the key library brings the game to the level, then
# remix_showcase.py plays the take (spawn views, the car-paint sweep, a drive).
# Needs the devtools scene key: INI_SED='s/^scene_key=.*/scene_key=F11/' (and SCENE_KEY=F11).
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-45}
python3 /work/remix_showcase.py
mark done
