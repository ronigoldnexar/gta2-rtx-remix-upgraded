#!/usr/bin/env bash
# GANG CAR BANG! (Residential, ste_rh1) by MISSIONS-BATCH2: into the level, then the runner
bash /work/to_level.sh
python3 /work/missions/b2_gang_car_bang.py "$@"
touch /out/.keys_done
