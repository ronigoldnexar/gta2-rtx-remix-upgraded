#!/usr/bin/env bash
# FIX-ENTRY-1 probe (gamerun/ent1_probe.py): refused Return beside a car, the game's entry facing it, enter_key.
#   PRIO=1 GTA2_DIRECT_KEYS=1 STAGE=<stage> \
#   INI_SED='s/^warp_key=.*/warp_key=F9\nenter_key=B/; s/^scene_key=.*/scene_key=F11/' \
#   gamerun/grun.sh ent1_x 240 keys_ent1.sh -e GTA2DX9_STATE_EVERY=3 -e GTA2DX9_LOG_ENTRY=1 -e GTA2DX9_SCENE_NO_CAR=1
# ini-sed: s/^scene_key=.*/scene_key=F11/
bash /work/to_level.sh
SCENE_KEY=F11 python3 /work/ent1_probe.py
echo done >> /out/keys.log
