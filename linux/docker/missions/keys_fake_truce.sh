#!/usr/bin/env bash
# FAKE TRUCE! (Residential file ste, ste_se2) in the street views: into the level, then the job runner
bash /work/to_level.sh
python3 /work/missions/fake_truce.py "$@"
touch /out/.keys_done
