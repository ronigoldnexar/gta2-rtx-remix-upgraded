#!/bin/bash
# dk_sample.sh <run name> <lvl> <n> [seed]: the ship QA sample of one level (qa_sample.py over the ship build's QA) on my stage
set -e
N=$1; L=$2; NB=$3; SEED=${4:-14}
G=/mnt/gta2/gta2-linux; R=$G/wt_districts; W=$R/dll/build/districts
cp $R/linux/docker/districts_capture.py $R/linux/docker/districts_sample.py $R/linux/docker/keys_districts_sample.sh $G/gamerun/
PTS=$(GTA2_DATA=$G/game/data $G/vreg/venv/bin/python $R/tools/districts/qa_sample.py $W $L $W/${L}_qa_ship.json $NB $SEED)
echo "$PTS" > $G/districts_work/${N}_points.json
SW=""; [ "$L" != wil ] && SW=$L
cd $G
STAGE=$G/stage_districts GTA2_DIRECT_KEYS=1 FPS=0 GTA2_GPU=0 SWAP_LEVEL=$SW \
SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/' \
nohup gamerun/grun.sh $N 700 keys_districts_sample.sh -v $G/stage_districts/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro -e GTA2DX9_SCENE_NO_CAR=1 -e 'GTA2DX9_REGRESS_CAM=Z:\tmp\vreg_cam.txt' \
  -e VREG_CAM=/tmp/vreg_cam.txt -e SCENE_KEY=F11 -e "DK_POINTS=$PTS" > $G/out/$N.nohup 2>&1 &
echo "queued $N ($L, $(echo "$PTS" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))') buildings)"
