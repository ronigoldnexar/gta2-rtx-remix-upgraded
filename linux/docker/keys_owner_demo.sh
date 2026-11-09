#!/usr/bin/env bash
# The owner's gameplay demo, one continuous take (owner_demo.py): classic opening, third person
# walk, first person look-around, a punch that connects, a car jacked at the kerb lane (developer
# warp only as a marked last resort), chase drive, driver's seat, classic while driving, out, steps.
# Every beat is in /out/marks.txt as '<epoch> <video seconds> <event>'.
#   GTA2_DIRECT_KEYS=1 FPS=30 PRIO=1 GTA2_GPU=3 gamerun/grun.sh <run> 480 keys_owner_demo.sh \
#     -e GTA2DX9_STATE_EVERY=3 -e GTA2DX9_PEDS_EVERY=3 -e GTA2DX9_LOG_PED_FRAMES=1
# ini-sed: s/^scene_key=.*/scene_key=F11/
export DEMO_T0=$(date +%s.%N)
bash /work/to_level.sh
SKIP_START= python3 /work/owner_demo.py
