#!/usr/bin/env bash
# ini-sed: s/^scene_key=.*/scene_key=F10/; s/^warp_key=.*/warp_key=F9/
bash /work/to_level.sh
python3 /work/fixfp2_f21.py
echo done
