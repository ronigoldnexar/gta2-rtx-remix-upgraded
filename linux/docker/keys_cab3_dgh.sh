#!/usr/bin/env bash
# ini-sed: s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/
# FIX-DRIVER-GEOM pmab1/pfl71: FP hands at fixed wheel locks on three classes, then wall impacts with a held turn.
export SCENE_KEY=F11
bash /work/to_level.sh
python3 /work/cab3_dgh_probe.py
echo done >> /out/keys.log
