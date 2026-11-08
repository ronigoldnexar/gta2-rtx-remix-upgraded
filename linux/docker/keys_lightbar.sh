#!/usr/bin/env bash
# LIGHTBAR: the light bars under Remix (lightbar_take.py). Needs the devtools scene key:
# INI_SED='s/^scene_key=.*/scene_key=F11/' (and SCENE_KEY=F11).
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-45}
python3 /work/lightbar_take.py
mark done
