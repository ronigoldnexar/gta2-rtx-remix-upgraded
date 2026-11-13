#!/bin/bash
# dk_id.sh <run name> <lvl> <district key> [secs]: queue the round-4 identity frames of one district on my private stage
set -e
N=$1; L=$2; DK=$3; SECS=${4:-600}
G=/mnt/gta2/gta2-linux; R=$G/wt_districts; W=$G/districts_work
cp $R/linux/docker/districts_capture.py $R/linux/docker/districts_identity.py $R/linux/docker/keys_districts_identity.sh $G/gamerun/
PTS=$(GTA2_DATA=$G/game/data /mnt/gta2/gta2-linux/vreg/venv/bin/python $R/tools/districts/id_plan.py $W/stagework $L $DK)
echo "$PTS" > $W/${N}_points.json
SW=""; [ "$L" != wil ] && SW=$L
cd $G
STAGE=$G/stage_districts GTA2_DIRECT_KEYS=1 FPS=0 GTA2_GPU=0 SWAP_LEVEL=$SW \
SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/' \
nohup gamerun/grun.sh $N $SECS keys_districts_identity.sh -e GTA2DX9_SCENE_NO_CAR=1 -e 'GTA2DX9_REGRESS_CAM=Z:\tmp\vreg_cam.txt' \
  -e VREG_CAM=/tmp/vreg_cam.txt -e SCENE_KEY=F11 -v $G/stage_districts/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro -e "DK_POINTS=$PTS" > $G/out/$N.nohup 2>&1 &
echo "queued $N ($L $DK)"
