#!/usr/bin/env bash
# ini-sed: s/^scene_key=.*/scene_key=F11/
# FIX-KNOCKDOWN-4 pm24: gang files at the wil gang spots (kd4_gang.py), GTA2DX9_SCENE_NO_CAR=1.
bash /work/to_level.sh
python3 /work/kd4_gang.py
echo done >> /out/keys.log
