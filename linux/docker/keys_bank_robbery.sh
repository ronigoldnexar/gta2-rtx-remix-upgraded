#!/usr/bin/env bash
# BANK ROBBERY (Downtown, wil_ye2) in the street views: into the level, then the job's own runner.
bash /work/to_level.sh
python3 /work/missions/bank_robbery.py "$@"
touch /out/.keys_done
