#!/bin/bash
# l4_run.sh <tag> [levels]: the districts capture under RTX Remix on Tokyo's L4 (gamerun/remix_l4.sh), one at a time,
# with a hard-link copy of the package whose gta2hd layer has no facade parallax on the kit's tiles.
G=/mnt/gta2/gta2-linux; W=$G/districts_work; R=$G/wt_districts; TAG=$1
PK=$W/package_kit
if [ ! -f $PK/.nopom ]; then
  python3 -c "import shutil; shutil.rmtree('$PK', ignore_errors=True)"
  cp -al $G/repo/package $PK
  /mnt/gta2/gta2-linux/vreg/venv/bin/python $R/tools/districts/remix_nopom.py patch $W/nopom_hashes.json $PK/rtx-remix/mods/gta2hd && touch $PK/.nopom
fi
cp $R/linux/docker/districts_capture.py $R/linux/docker/keys_districts_remix.sh $G/gamerun/
cd $G
for l in ${2:-wil ste bil}; do
  SW=""; [ $l != wil ] && SW=$l
  STAGE=$G/stage_districts PACKAGE=$PK GTA2_INTRO=0 REMIX_NVCACHE=1 bash gamerun/remix_l4.sh dkr_${l}${TAG} 1100 /work/keys_districts_remix.sh \
    -e MODS_HD=1 -e SWAP_LEVEL=$SW -e GTA2_DIRECT_KEYS=1 -e SCENE_KEY=F11 -e GTA2DX9_SCENE_NO_CAR=1 -e 'GTA2DX9_REGRESS_CAM=Z:\tmp\vreg_cam.txt' \
    -e VREG_CAM=/tmp/vreg_cam.txt -e "DK_POINTS=$(cat $W/points_$l.json)" \
    -e "INI_SED=s/^scene_key=.*/scene_key=F11/; s/^nav_map=.*/nav_map=0/; s/^facade_kit=.*/facade_kit=1/; s/^log_keys=.*/log_keys=1/" \
    -e "SETTINGS_SED=s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/" \
    -v $G/stage_districts/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro
  echo "$(date +%T) dkr_${l}${TAG}: $(ls out/dkr_${l}${TAG} | grep -c dk_) frames, FAULT $(grep -c FAULT out/dkr_${l}${TAG}/gta2dx9.log 2>/dev/null)"
done
