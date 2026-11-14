#!/bin/bash
# city_drive.sh <name> <lvl> [remix]: the round-5 drive across a level (route_city.py: one leg into each styled
# district), kit on, the whole city streamed; plain (grun.sh, 15 fps video) or under Remix on the L4 (GPU 0)
G=/mnt/gta2/gta2-linux; W=$G/districts_work; R=$G/wt_districts; N=$1; L=$2
cp $R/linux/docker/districts_drive.py $R/linux/docker/keys_districts_drive.sh $G/gamerun/
ROUTE=$(GTA2_DATA=$G/game/data $G/vreg/venv/bin/python $R/tools/districts/route_city.py $W/stagework $L 9)
echo "$ROUTE" > $W/${N}_route.json
SW=""; [ "$L" != wil ] && SW=$L
cd $G
if [ "${3:-}" = remix ]; then
  STAGE=$G/stage_districts PACKAGE=$W/package_kit_r4 GTA2_INTRO=0 REMIX_NVCACHE=1 bash gamerun/remix_l4.sh $N 1500 /work/keys_districts_drive.sh \
    -e MODS_HD=1 -e SWAP_LEVEL=$SW -e GTA2_DIRECT_KEYS=1 -e SCENE_KEY=F11 -e "DK_ROUTE=$ROUTE" -e DK_LEVEL=$L -e DK_LAPS=1 \
    -e "INI_SED=s/^scene_key=.*/scene_key=F11/; s/^nav_map=.*/nav_map=0/; s/^facade_kit=.*/facade_kit=${KIT:-1}/; s/^log_keys=.*/log_keys=1/" \
    -e "SETTINGS_SED=s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/" \
    -v $G/stage_districts/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro
else
  STAGE=$G/stage_districts GTA2_DIRECT_KEYS=1 FPS=15 GTA2_GPU=0 SWAP_LEVEL=$SW INI_SED="s/^facade_kit=.*/facade_kit=${KIT:-1}/" \
  SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/' \
  gamerun/grun.sh $N 1200 keys_districts_drive.sh -e GTA2DX9_VA_WATCH=0 -e SCENE_KEY=F11 -e "DK_ROUTE=$ROUTE" -e DK_LEVEL=$L -e DK_LAPS=1 \
    -v $G/stage_districts/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro > $G/out/$N.nohup 2>&1
fi
echo "$(date +%T) $N done: FAULT $(grep -c FAULT out/$N/gta2dx9.log 2>/dev/null), legs $(grep -c '^[0-9.]* leg ' out/$N/marks.txt 2>/dev/null), reboards $(grep -c 'boarding again' out/$N/marks.txt 2>/dev/null)"
