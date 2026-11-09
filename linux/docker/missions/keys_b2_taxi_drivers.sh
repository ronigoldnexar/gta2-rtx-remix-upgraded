#!/usr/bin/env bash
# TAXI DRIVERS MUST DIE! (Downtown, wil_lh1) by MISSIONS-BATCH2: into the level, then the runner
bash /work/to_level.sh
python3 /work/missions/b2_taxi_drivers.py "$@"
touch /out/.keys_done
