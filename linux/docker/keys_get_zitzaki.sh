#!/usr/bin/env bash
# GET ZITZAKI (Downtown, wil_ye1) with the Wave M deliver_intact skill: into the level, then the job's runner.
bash /work/to_level.sh
python3 /work/missions/get_zitzaki.py "$@"
touch /out/.keys_done
