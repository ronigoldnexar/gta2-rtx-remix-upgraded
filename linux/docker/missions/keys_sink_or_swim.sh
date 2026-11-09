#!/usr/bin/env bash
# SINK OR SWIM! (Residential file ste, ste_se1) in the street views: into the level, then the job's runner
bash /work/to_level.sh
python3 /work/missions/sink_or_swim.py "$@"
touch /out/.keys_done
