#!/usr/bin/env bash
# FIX-ENTRY-1: Return under the shipped nav_map=1 (run WITHOUT GTA2_DIRECT_KEYS); gamerun/ent1_nav.py
bash /work/to_level.sh
python3 /work/ent1_nav.py
echo done >> /out/keys.log
