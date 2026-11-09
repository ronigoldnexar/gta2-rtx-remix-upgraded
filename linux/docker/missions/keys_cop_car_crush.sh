#!/usr/bin/env bash
# COP CAR CRUSH (Downtown, wil_ze1) with the Wave M crusher_crane skill: into the level, then the job runner.
bash /work/to_level.sh
python3 /work/missions/cop_car_crush.py "$@"
touch /out/.keys_done
