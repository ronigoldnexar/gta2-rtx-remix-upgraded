#!/usr/bin/env bash
# SWAT VAN SWIPE! (Downtown, wil_yh1): steal_car + deliver_intact (MISSIONS-BATCH3)
bash /work/to_level.sh
python3 /work/missions/swat_van_swipe.py "$@"
touch /out/.keys_done
