#!/usr/bin/env bash
# FIX-AIM-2 first-person punch frames (fixaim2_fpgate.py): 10 single punches at a civilian within reach, third then first person.
export DEMO_T0=$(date +%s.%N)
bash /work/to_level.sh
python3 /work/fixaim2_fpgate.py
