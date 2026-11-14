#!/bin/bash
# levels_run.sh <name> [remix]: the level-change check with the kit on my stage (plain: grun, GPU 0; remix: the L4)
G=/mnt/gta2/gta2-linux; R=$G/wt_districts; N=$1
cp $R/linux/docker/districts_levels.py $R/linux/docker/keys_districts_levels.sh $R/linux/docker/keys_districts_levels_remix.sh $G/gamerun/
cd $G
if [ "${2:-}" = remix ]; then
  STAGE=$G/stage_districts PACKAGE=$G/districts_work/package_kit_r4 GTA2_INTRO=0 REMIX_NVCACHE=1 bash gamerun/remix_l4.sh $N 3000 /work/keys_districts_levels_remix.sh \
    -e MODS_HD=1 -e SWAP_LEVEL=bil -e GTA2_DIRECT_KEYS=1 -e SCENE_KEY=F11 -e DK_LEVEL_LAPS=${LAPS:-5} \
    -e "INI_SED=s/^scene_key=.*/scene_key=F11/; s/^nav_map=.*/nav_map=0/; s/^facade_kit=.*/facade_kit=1/; s/^log_keys=.*/log_keys=1/" \
    -e "SETTINGS_SED=s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/" \
    -v $G/stage_districts/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro
else
  STAGE=$G/stage_districts GTA2_DIRECT_KEYS=1 FPS=0 GTA2_GPU=0 SWAP_LEVEL=bil \
  SETTINGS_SED='s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/' \
  gamerun/grun.sh $N 2400 keys_districts_levels.sh -e DK_LEVEL_LAPS=${LAPS:-5} -e SCENE_KEY=F11 \
    -v $G/stage_districts/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro > $G/out/$N.nohup 2>&1
fi
L=$G/out/$N/gta2dx9.log
echo "$(date +%T) $N: FAULT $(grep -c FAULT $L 2>/dev/null), level loads $(grep -c 'MARK level loaded' $G/out/$N/keys.log 2>/dev/null), stops done $(grep -c 'MARK stop end' $G/out/$N/keys.log 2>/dev/null), kit streams loaded $(grep -ac 'facade kit stream .* loaded' $L 2>/dev/null), style tables $(grep -ac 'districts: style table' $L 2>/dev/null)"
grep -a 'facade kit stream\|districts: style table' $L 2>/dev/null | sed 's/.*gta2dx9_districts.//' | cut -c1-60 | uniq -c | head -8
