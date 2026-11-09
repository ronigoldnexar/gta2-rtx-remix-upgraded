#!/usr/bin/env bash
# ini-sed: s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/
# FIX-FP-2 cockpit probe (fixfp2_cab.py; vr_seat's seating recipe, F11 scene key).
export SCENE_KEY=F11
python3 /work/fixfp2_cab.py
echo done
