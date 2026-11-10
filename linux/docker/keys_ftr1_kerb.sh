#!/usr/bin/env bash
# FIX-TRAFFIC-1 kerb clip (ftr1_kerb.py)
# ini-sed: s/^scene_key=.*/scene_key=F11/
export SCENE_KEY=F11
bash /work/to_level.sh
python3 /work/ftr1_kerb.py
echo done
