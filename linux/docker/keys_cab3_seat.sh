#!/usr/bin/env bash
# ini-sed: s/^warp_key=.*/warp_key=F9/; s/^nav_map=.*/nav_map=0/
# FIX-COCKPIT-CAB-3: the seat view of a real vehicle (cab3_seat.py)
bash /work/to_level.sh
python3 /work/cab3_seat.py
echo done >> /out/keys.log
