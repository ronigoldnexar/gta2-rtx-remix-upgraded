#!/bin/bash
# prev_all.sh [levels]: kit + Blender previews + grids for the picked buildings
cd /mnt/gta2/gta2-linux/wt_districts
P=/mnt/gta2/gta2-linux/vreg/venv/bin/python; W=/mnt/gta2/gta2-linux/districts_work; HD=/mnt/gta2/gta2-linux/repo/assets/textures_hd
for l in ${1:-wil ste bil}; do
  $P tools/districts/kit.py $W $l $W/$l.kit | head -2
  taskset -c 40-71 nice -n 10 /mnt/gta2/tools/blender -b -P tools/districts/preview_blender.py -- $W $l $HD $W/kit $W/$l.kit $W/prev/$l 8 2>&1 | grep 'preview done\|Error\|Traceback' 
  cd $W/prev && $P ../pair.py ${l}_prev.png street-before ${l}_street_before.png street-after ${l}_street_after.png close-before ${l}_close_before.png close-after ${l}_close_after.png corner-before ${l}_corner_before.png corner-after ${l}_corner_after.png high-before ${l}_high_before.png high-after ${l}_high_after.png; cd - >/dev/null
done
