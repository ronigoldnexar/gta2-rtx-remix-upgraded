#!/usr/bin/env bash
# DISTRICTS pilot drive-through (linux/docker/districts_drive.py).
# ini-sed: s/^scene_key=.*/scene_key=F11/; s/^log_keys=.*/log_keys=1/
export DISPLAY=:99
bash /work/to_level.sh
python3 -u /work/districts_drive.py
touch /out/.keys_done
