#!/usr/bin/env bash
# FIX-ENTRY-1: enter_key from a refused spot (GTA2_DIRECT_KEYS=1); gamerun/ent1_f8.py
bash /work/to_level.sh
python3 /work/ent1_f8.py
echo done >> /out/keys.log
