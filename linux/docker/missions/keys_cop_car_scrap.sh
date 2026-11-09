#!/usr/bin/env bash
# COP CAR SCRAP! (Industrial bil, bil_ke2): steal_car + crusher_crane (MISSIONS-BATCH3)
bash /work/to_level.sh
python3 /work/missions/cop_car_scrap.py "$@"
touch /out/.keys_done
