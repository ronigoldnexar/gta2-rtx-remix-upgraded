#!/usr/bin/env bash
# LABRAT'S PLAN! (Residential file ste, ste_sm1) played by the gunfight skill (MISSIONS-BATCH1)
bash /work/to_level.sh
python3 /work/missions/labrats_plan.py "$@"
touch /out/.keys_done
