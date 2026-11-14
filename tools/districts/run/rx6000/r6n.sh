#!/bin/bash
# on the 6000: the Yakuza-turf identity frames (day, dusk 18:20; kit on/off) under /gta2/remix.lock, never rebooting
D=/gta2/dist; cd /gta2
cp $D/districts_identity.py $D/districts_capture.py $D/keys_districts_identity_remix.sh /gta2/gamerun/
grep -q 'DK_POINTS=' $D/run6.sh || sed -i 's#-e "DK_ROUTE=$DK_ROUTE"#-e "DK_ROUTE=$DK_ROUTE" -e "DK_POINTS=$DK_POINTS" -e GTA2DX9_SCENE_NO_CAR=1 -e "GTA2DX9_REGRESS_CAM=Z:\\\\tmp\\\\vreg_cam.txt" -e VREG_CAM=/tmp/vreg_cam.txt#' $D/run6.sh
grep -o 'DK_POINTS[^ ]*\|REGRESS_CAM=[^ ]*' $D/run6.sh | head -3
exec 9>/gta2/remix.lock
flock 9
while [ -n "$(sudo docker ps -q)" ]; do sleep 20; done
echo "$(date +%T) lock held, uptime $(uptime -p), run r6n_wil"
KIT=1 DK_ROUTE='{}' DK_POINTS="$(cat $D/points_neon.json)" DISTRICT=wil HOURS=12.5 KEYS=/work/keys_districts_identity_remix.sh bash $D/run6.sh r6n_wil 900 2>&1 | tail -3
flock -u 9; exec 9>&-
echo "$(date +%T) r6n_wil done: $(ls $D/out/r6n_wil | grep -c dk_) frames, FAULT $(grep -c FAULT $D/out/r6n_wil/gta2dx9.log 2>/dev/null)"
