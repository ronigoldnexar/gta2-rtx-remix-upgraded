#!/usr/bin/env bash
# FIX-AIM-2: the gun gate (fixaim2_gun.py): 20 pistol shots at a civilian inside the reticle at 2, 4, 6 blocks, third + first.
export DEMO_T0=$(date +%s.%N)
bash /work/to_level.sh
python3 /work/fixaim2_gun.py
