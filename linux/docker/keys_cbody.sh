#!/usr/bin/env bash
# ini-sed: s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/
# FIX-COCKPIT-BODY: first-person wheel direction / driver body / dashcam probe (cbody_probe.py).
export SCENE_KEY=F11
python3 /work/cbody_probe.py
echo done
