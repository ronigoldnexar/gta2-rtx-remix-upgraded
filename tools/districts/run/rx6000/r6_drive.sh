#!/bin/bash
# on the 6000: one kit-on and one kit-off drive of the round-5 wil route, under /gta2/remix.lock for the whole run;
# never reboots (waits for the lock and for no other container)
D=/gta2/dist; cd /gta2
for spec in "on 1" "off 0"; do
  set -- $spec
  exec 9>/gta2/remix.lock
  echo "$(date +%T) waiting for the lock ($1)"
  flock 9
  while [ -n "$(sudo docker ps -q)" ]; do sleep 20; done
  echo "$(date +%T) lock held, uptime $(uptime -p), run r6_wil_$1"
  KIT=$2 DK_ROUTE="$(cat $D/route_wil.json)" DISTRICT=wil HOURS=12.5 KEYS=/work/keys_districts_drive_remix.sh bash $D/run6.sh r6_wil_$1 1500 2>&1 | tail -4
  flock -u 9; exec 9>&-
  echo "$(date +%T) r6_wil_$1 done: FAULT $(grep -c FAULT $D/out/r6_wil_$1/gta2dx9.log 2>/dev/null), legs $(grep -c ' leg ' $D/out/r6_wil_$1/marks.txt 2>/dev/null)"
done
echo r6 done
