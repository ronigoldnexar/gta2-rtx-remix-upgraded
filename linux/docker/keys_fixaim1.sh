#!/usr/bin/env bash
# FIX-AIM-1 punch gate (fixaim1_gate.py): 10 single punches at a civilian within reach, third then first person.
export DEMO_T0=$(date +%s.%N)
bash /work/to_level.sh
python3 /work/fixaim1_gate.py
