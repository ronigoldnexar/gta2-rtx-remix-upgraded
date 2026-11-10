#!/usr/bin/env bash
# ini-sed: s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/
# FIX-COCKPIT-BODY-2: grip probe (cb2grip_probe.py): live [devtools] sweep of fp_hand_scale / fp_grip_tilt / fp_grip_curl, then held turns.
export SCENE_KEY=F11
python3 /work/cb2grip_probe.py
echo done
