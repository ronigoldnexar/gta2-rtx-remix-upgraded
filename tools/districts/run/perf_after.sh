#!/bin/bash
# after the capture chain (the vreg capture already ran as dk_vreg1): the frame-time A/B run. The spawn-area kit
# (46 buildings, 66k triangles) mounted, the across pose of the near-spawn building with the most kit held 20 s
# kit on / 20 s kit off, twice (districts_capture.py DK_PERF).
G=/mnt/gta2/gta2-linux; W=$G/districts_work; R=$G/wt_districts
while pgrep -f "runq.sh run -p 5 -n dk_" > /dev/null; do sleep 10; done
BID=$(/mnt/gta2/gta2-linux/vreg/venv/bin/python -c "
import json
from collections import Counter
c = Counter()
for t, f, own in json.load(open('$W/vregkit/wil.kit.owners.json')):
    for b, first, n in own: c[b] += n // 3
c.pop(490, None); print(c.most_common(1)[0][0])")
PTS=$(/mnt/gta2/gta2-linux/vreg/venv/bin/python $R/tools/districts/frame_plan.py $W wil $BID)
echo "$PTS" > $W/dk_perf_points.json
cp $R/linux/docker/districts_capture.py $R/linux/docker/keys_districts.sh $G/gamerun/
cd $G
STAGE=$G/stage_districts GTA2_DIRECT_KEYS=1 FPS=0 GTA2_GPU=0 \
SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/' \
gamerun/grun.sh dk_perf1 420 keys_districts.sh -e GTA2DX9_SCENE_NO_CAR=1 -e 'GTA2DX9_REGRESS_CAM=Z:\tmp\vreg_cam.txt' \
  -e VREG_CAM=/tmp/vreg_cam.txt -e SCENE_KEY=F11 -e DK_PERF=across -e "DK_POINTS=$PTS" \
  -v $W/vregkit:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro > $G/out/dk_perf1.nohup 2>&1
