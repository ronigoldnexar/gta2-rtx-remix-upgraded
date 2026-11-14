#!/usr/bin/env bash
# DISTRICTS level-change check (linux/docker/districts_levels.py), plain renderer.
# ini-sed: s/^scene_key=.*/scene_key=F11/; s/^facade_kit=.*/facade_kit=1/; s/^log_keys=.*/log_keys=1/
export DISPLAY=:99
bash /work/to_level.sh
python3 -u /work/districts_levels.py
touch /out/.keys_done
