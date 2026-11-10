#!/usr/bin/env bash
# FIX-FX-4: deterministic car blast (or burn) in a street view, player alive; [devtools] force_blast.
# Run: GTA2_DIRECT_KEYS=1 FPS=30 STAGE=<stage> gamerun/grun.sh <name> 150 keys_fx4_blast.sh -e GTA2DX9_STATE_EVERY=3 \
#      [-e VIEW=first] [-e DIST=4] [-e BURN=1] [-e GTA2DX9_BLAST_PROBE=1]    with INI_SED='s/^scene_key=.*/scene_key=F10/'
bash /work/to_level.sh
python3 /work/fx4_blast.py
cp /tmp/wp/drive_c/Games/GTA2/gta2dx9.log /out/ 2>/dev/null
echo done
