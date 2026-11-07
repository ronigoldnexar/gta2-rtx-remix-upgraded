#!/usr/bin/env bash
# Remix: to the level, then the driver's-seat check (remix_fixes_drive.py).
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-45}
SKIP_START=1 python3 /work/remix_fixes_drive.py
mark done
