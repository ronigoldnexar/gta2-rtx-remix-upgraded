#!/usr/bin/env bash
# FIX-ENTRY-1: the reach sweep (GTA2_DIRECT_KEYS=1); gamerun/ent1_sweep.py
bash /work/to_level.sh
python3 /work/ent1_sweep.py
echo done >> /out/keys.log
