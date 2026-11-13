#!/usr/bin/env bash
# DISTRICTS-POC capture (linux/docker/districts_identity.py): into the level, the frames, end the run.
# ini-sed: s/^scene_key=.*/scene_key=F11/; s/^facade_kit=.*/facade_kit=1/; s/^log_keys=.*/log_keys=1/
export DISPLAY=:99
bash /work/to_level.sh
python3 -u /work/districts_identity.py
touch /out/.keys_done
