#!/usr/bin/env bash
# ini-sed: s/^scene_key=.*/scene_key=F11/
# FIX-KNOCKDOWN-4: kd4_brush.py from KNOCKDOWN-2's lane jack (KD4_LANE=1).
bash /work/to_level.sh
KD4_LANE=1 python3 /work/kd4_brush.py
echo done >> /out/keys.log
