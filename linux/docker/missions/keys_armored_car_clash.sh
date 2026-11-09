#!/usr/bin/env bash
# ARMORED CAR CLASH! (Downtown, wil_zh1): destroy_vehicle by ramming (MISSIONS-BATCH4)
bash /work/to_level.sh
python3 /work/missions/armored_car_clash.py "$@"
touch /out/.keys_done
