#!/usr/bin/env bash
# ini-sed: s/^scene_key=.*/scene_key=F11/
# FIX-KNOCKDOWN-4 pm3: the player walked into the parked ambulance at ste (kd4_amb.py). SWAP_LEVEL=ste, GTA2DX9_SCENE_NO_CAR=1.
bash /work/to_level.sh
python3 /work/kd4_amb.py
echo done >> /out/keys.log
