#!/bin/bash
# on the 6000: after the first pair, the sorted-draw DLL and the deflated kit into stage6, then one kit-on drive under
# /gta2/remix.lock (never reboots)
D=/gta2/dist; cd /gta2
until grep -q 'r6 done' $D/r6_drive.log; do sleep 20; done
exec 9>/gta2/remix.lock
flock 9
while [ -n "$(sudo docker ps -q)" ]; do sleep 20; done
mkdir -p $D/x6b && tar xf $D/r6b.tar -C $D/x6b
for f in gta2dx9.dll d3ddll.dll gta2dx9.map; do cp --remove-destination $D/x6b/$f $D/stage6/$f; done
cp --remove-destination $D/x6b/gta2dx9_districts/wil.kit2 $D/x6b/gta2dx9_districts/wil.dstyle $D/stage6/gta2dx9_districts/
echo "$(date +%T) lock held, uptime $(uptime -p), run r6b_wil_on"
KIT=1 DK_ROUTE="$(cat $D/route_wil.json)" DISTRICT=wil HOURS=12.5 KEYS=/work/keys_districts_drive_remix.sh bash $D/run6.sh r6b_wil_on 1500 2>&1 | tail -3
flock -u 9; exec 9>&-
echo "$(date +%T) r6b_wil_on done: FAULT $(grep -c FAULT $D/out/r6b_wil_on/gta2dx9.log 2>/dev/null), legs $(grep -c ' leg ' $D/out/r6b_wil_on/marks.txt 2>/dev/null)"
echo r6b done
