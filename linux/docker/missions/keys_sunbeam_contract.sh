#!/usr/bin/env bash
# SUNBEAM CONTRACT! (Industrial, bil_km2): MISSIONS-BATCH4-2
bash /work/to_level.sh
python3 /work/missions/sunbeam_contract.py "$@"
touch /out/.keys_done
