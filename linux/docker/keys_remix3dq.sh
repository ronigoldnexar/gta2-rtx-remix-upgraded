#!/usr/bin/env bash
# REMIX-3D-QUALITY: into Downtown under Remix (remix_keys_lib.sh), then remix3dq_take.py.
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-30}
python3 /work/remix3dq_take.py
mark done
