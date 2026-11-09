#!/usr/bin/env bash
# GET GAMA REI! (Downtown, wil_ym2) with the escort skill: into the level, the two green Yakuza jobs
# for the respect, then the yellow phone (missions/get_gama_rei.py)
bash /work/to_level.sh
python3 /work/missions/get_gama_rei.py "$@"
touch /out/.keys_done
