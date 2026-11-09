#!/usr/bin/env bash
# COSSACK CONVERSION! (Industrial, bil_km1) by MISSIONS-BATCH2: into the level, then the runner
bash /work/to_level.sh
python3 /work/missions/b2_cossack.py "$@"
touch /out/.keys_done
