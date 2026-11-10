#!/usr/bin/env bash
# FIX-KNOCKDOWN-4: pfl38 near-miss / flank-brush probe (kd4_brush.py), first then third person.
bash /work/to_level.sh
python3 /work/kd4_brush.py
echo done >> /out/keys.log
