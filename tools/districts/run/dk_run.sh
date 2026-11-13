#!/bin/bash
# dk_run.sh <run name> <lvl> [secs]: queue a districts capture of the level's picked building on my private stage
set -e
N=$1; L=$2; SECS=${3:-900}
G=/mnt/gta2/gta2-linux; R=$G/wt_districts; W=$G/districts_work
cp $R/linux/docker/districts_capture.py $R/linux/docker/keys_districts.sh $G/gamerun/
PTS=$(/mnt/gta2/gta2-linux/vreg/venv/bin/python $R/tools/districts/frame_plan.py $W $L)
echo "$PTS" > $W/${N}_points.json
SW=""; [ "$L" != wil ] && SW=$L
cd $G
STAGE=$G/stage_districts GTA2_DIRECT_KEYS=1 FPS=0 GTA2_GPU=0 SWAP_LEVEL=$SW \
SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/' \
nohup gamerun/grun.sh $N $SECS keys_districts.sh -e GTA2DX9_SCENE_NO_CAR=1 -e 'GTA2DX9_REGRESS_CAM=Z:\tmp\vreg_cam.txt' \
  -e VREG_CAM=/tmp/vreg_cam.txt -e SCENE_KEY=F11 -v $G/stage_districts/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro -e "DK_POINTS=$PTS" > $G/out/$N.nohup 2>&1 &
echo "queued $N ($L): $PTS"
