#!/bin/bash
# night_run.sh <name> [remix]: the merge check (a level change, night views of Yakuza turf's sign words, a night drive)
G=/mnt/gta2/gta2-linux; R=$G/wt_districts; W=$G/districts_work; N=$1
cp $R/linux/docker/districts_capture.py $R/linux/docker/districts_night.py $R/linux/docker/keys_districts_night.sh $R/linux/docker/keys_districts_night_remix.sh $G/gamerun/
PTS=$(GTA2_DATA=$G/game/data $G/vreg/venv/bin/python $R/tools/districts/id_plan.py $R/dll/build/districts wil gang:yakuzagang)
ROUTE=$(GTA2_DATA=$G/game/data $G/vreg/venv/bin/python $R/tools/districts/route_city.py $R/dll/build/districts wil 9)
cd $G
if [ "${2:-}" = remix ]; then
  STAGE=$G/stage_districts PACKAGE=$W/package_kit_r4 GTA2_INTRO=0 REMIX_NVCACHE=1 bash gamerun/remix_l4.sh $N 1800 /work/keys_districts_night_remix.sh \
    -e MODS_HD=1 -e SWAP_LEVEL=bil -e GTA2_DIRECT_KEYS=1 -e SCENE_KEY=F11 -e GTA2DX9_SCENE_NO_CAR=1 -e 'GTA2DX9_REGRESS_CAM=Z:\tmp\vreg_cam.txt' \
    -e VREG_CAM=/tmp/vreg_cam.txt -e "DK_POINTS=$PTS" -e "DK_ROUTE=$ROUTE" \
    -e "INI_SED=s/^scene_key=.*/scene_key=F11/; s/^nav_map=.*/nav_map=0/; s/^facade_kit=.*/facade_kit=1/; s/^log_keys=.*/log_keys=1/" \
    -e "SETTINGS_SED=s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/" \
    -v $G/stage_districts/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro
else
  STAGE=$G/stage_districts GTA2_DIRECT_KEYS=1 FPS=0 GTA2_GPU=0 SWAP_LEVEL=bil \
  SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/' \
  gamerun/grun.sh $N 1200 keys_districts_night.sh -e GTA2DX9_SCENE_NO_CAR=1 -e 'GTA2DX9_REGRESS_CAM=Z:\tmp\vreg_cam.txt' \
    -e VREG_CAM=/tmp/vreg_cam.txt -e SCENE_KEY=F11 -e "DK_POINTS=$PTS" -e "DK_ROUTE=$ROUTE" \
    -v $G/stage_districts/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro > $G/out/$N.nohup 2>&1
fi
L=$G/out/$N/gta2dx9.log
echo "$(date +%T) $N: FAULT $(grep -c FAULT $L 2>/dev/null), $(grep -a 'MARK level change\|MARK night drive' $G/out/$N/keys.log | cut -c1-80 | tr '\n' ' '), frames $(ls $G/out/$N | grep -c '^dk_')"
