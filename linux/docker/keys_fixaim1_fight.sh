#!/usr/bin/env bash
# FIX-AIM-1: a 3-minute scripted gun fight in third person (fixaim1_fight.py); the owner's aim: counter at the end.
export DEMO_T0=$(date +%s.%N)
bash /work/to_level.sh
python3 /work/fixaim1_fight.py
