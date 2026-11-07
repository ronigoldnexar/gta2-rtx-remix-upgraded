#!/usr/bin/env bash
# Downtown missions in the street views. Fast path: into the level by the log, then the runner.
bash /work/to_level.sh
python3 /work/mission_play_wil.py "$@"
