#!/usr/bin/env bash
# OPERATION Z! (Residential file ste, ste_zm1) in the street views: into the level, then the job runner
bash /work/to_level.sh
python3 /work/missions/operation_z.py "$@"
touch /out/.keys_done
