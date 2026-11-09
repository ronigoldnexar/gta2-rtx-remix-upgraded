#!/usr/bin/env bash
# Visual regression capture (tools/vreg/vreg.sh): into the level, the fixed frames, end the run.
export DISPLAY=:99
bash /work/to_level.sh
python3 -u /work/vreg_capture.py
touch /out/.keys_done
