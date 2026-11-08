#!/usr/bin/env bash
# LIGHTBAR-2: lightbar_take.py on the plain renderer (no Remix). Checks the beacon light
# queue (synthetic totals: siren > 0, with beams >= 1) and the plain bulbs. Needs
# INI_SED='s/^scene_key=.*/scene_key=F11/; s/^warp_key=.*/warp_key=F9/' and -e SCENE_KEY=F11.
export DISPLAY=:99
bash /work/to_level.sh
sleep ${LEVEL_WAIT:-8}
python3 /work/lightbar_take.py
grep "synthetic: totals" /tmp/wp/drive_c/Games/GTA2/gta2dx9.log | tail -3 > /out/lightbar_totals.txt
