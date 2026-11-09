#!/usr/bin/env bash
# PIZZA CAKE (Downtown, wil_le2) with the Wave M destroy_vehicle skill: into the level, then the job runner.
bash /work/to_level.sh
python3 /work/missions/pizza_cake.py "$@"
touch /out/.keys_done
