#!/usr/bin/env bash
# The owner's gameplay demo, the 12 beats in ONE continuous take (owner_demo.py): the real spawn, a classic
# (BEV) walk to the road, ONE smooth V to third, three separate pedestrians hit, a kerbside jack, first
# person at the wheel, C = dashcam, reckless driving in the dashcam, V back to classic while moving,
# the exit, a third person walk. Every beat is in /out/marks.txt as '<epoch> <video seconds> <event>'.
#   GTA2_DIRECT_KEYS=1 PRIO=1 GTA2_GPU=2 gamerun/rec_grun.sh <run> 540 keys_owner_demo.sh \
#     -e GTA2DX9_STATE_EVERY=3 -e GTA2DX9_PEDS_EVERY=3 -e GTA2DX9_LOG_PED_FRAMES=1 -e GTA2DX9_LOG_NEAR_PED=1
# (add -e GTA2DX9_FRAME_LOG=... for tools/frame_table.py; wait on 'done' in keys.log)
# ini-sed: s/^scene_key=.*/scene_key=F11/
export DEMO_T0=$(date +%s.%N)
bash /work/to_level.sh
SKIP_START= python3 /work/owner_demo.py
echo done >> /out/keys.log
