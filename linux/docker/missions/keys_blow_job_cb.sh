#!/usr/bin/env bash
# BLOW JOB! (Residential file ste, ste_re1) played by the car-bomb skill (skills/car_bomb.py)
bash /work/to_level.sh
python3 /work/missions/blow_job_cb.py "$@"
touch /out/.keys_done
