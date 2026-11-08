#!/usr/bin/env bash
# PLAYTHROUGH-9: wall hits per 100 blocks on a fixed Downtown route (DRIVER=classic|smooth)
bash /work/to_level.sh
python3 /work/drive_bench.py "$@"
touch /out/.keys_done
