#!/usr/bin/env bash
# REMIX-CARPROPS-PBR verification take: VISUALS-REMIX's fixed spots (remix_vis_take.py,
# the same headings in every run, for old-vs-new layer comparison and the frame cost),
# then, with PBR_TAKE=1, remix_pbr_take.py: close-ups of four cars, the booth, the traffic
# lights, a pedestrian and the plaza lamp posts by day and at night.
# Needs INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' and SCENE_KEY=F11.
. /work/remix_keys_lib.sh
focus_game
sleep ${PREWARM_WAIT:-200}
mark frontend
to_level; mark level_classic; sleep ${LEVEL_WAIT:-45}
python3 /work/remix_vis_take.py
[ "${PBR_TAKE:-0}" = 1 ] && python3 /work/remix_pbr_take.py
mark done
