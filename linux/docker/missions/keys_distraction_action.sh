#!/usr/bin/env bash
# DISTRACTION ACTION! (Residential file ste, ste_zh2) in the street views: into the level, then the job runner
bash /work/to_level.sh
python3 /work/missions/distraction_action.py "$@"
touch /out/.keys_done
