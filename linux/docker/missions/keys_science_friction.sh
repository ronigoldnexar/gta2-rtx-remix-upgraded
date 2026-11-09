#!/usr/bin/env bash
# SCIENCE FRICTION! (Residential ste, ste_ze1) with the car-bomb skill (MISSIONS-BATCH3)
bash /work/to_level.sh
python3 /work/missions/science_friction.py "$@"
touch /out/.keys_done
