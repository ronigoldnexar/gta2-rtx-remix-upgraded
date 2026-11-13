#!/bin/bash
# drive_run.sh <name> <kit 0|1> [remix]: the Zarelli drive-through, plain (grun.sh, 15 fps video) or under Remix on the L4
G=/mnt/gta2/gta2-linux; W=$G/districts_work; R=$G/wt_districts; N=$1; KIT=$2
cp $R/linux/docker/districts_drive.py $R/linux/docker/keys_districts_drive.sh $G/gamerun/
ROUTE=$(cat $W/route_zarelli.json)
cd $G
if [ "${3:-}" = remix ]; then
  STAGE=$G/stage_districts PACKAGE=$W/package_kit GTA2_INTRO=0 REMIX_NVCACHE=1 bash gamerun/remix_l4.sh $N 900 /work/keys_districts_drive.sh \
    -e MODS_HD=1 -e GTA2_DIRECT_KEYS=1 -e SCENE_KEY=F11 -e "DK_ROUTE=$ROUTE" \
    -e "INI_SED=s/^scene_key=.*/scene_key=F11/; s/^nav_map=.*/nav_map=0/; s/^facade_kit=.*/facade_kit=$KIT/; s/^log_keys=.*/log_keys=1/" \
    -e "SETTINGS_SED=s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/" \
    -v $G/stage_districts/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro
else
  STAGE=$G/stage_districts GTA2_DIRECT_KEYS=1 FPS=15 GTA2_GPU=0 INI_SED="s/^facade_kit=.*/facade_kit=$KIT/" \
  SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/' \
  gamerun/grun.sh $N 600 keys_districts_drive.sh -e SCENE_KEY=F11 -e "DK_ROUTE=$ROUTE" \
    -v $G/stage_districts/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro > $G/out/$N.nohup 2>&1
fi
echo "$(date +%T) $N done: FAULT $(grep -c FAULT out/$N/gta2dx9.log 2>/dev/null)"
