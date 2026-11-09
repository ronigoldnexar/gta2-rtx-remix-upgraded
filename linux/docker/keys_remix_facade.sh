#!/usr/bin/env bash
# QB-25 facade-depth take: level up, then remix_facade_take.py (displacement 0/1/2 at fixed poses).
# Needs INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' and SCENE_KEY=F11.
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-45}
python3 /work/remix_facade_take.py
mark done
