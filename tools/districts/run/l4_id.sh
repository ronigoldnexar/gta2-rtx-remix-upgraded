#!/bin/bash
# l4_id.sh <tag>: the round-4 identity frames under RTX Remix on Tokyo's L4 (GPU 0), one district at a time, with a
# fresh hard-link copy of the package (the shipped rtx.conf of today's branch) whose gta2hd layer has no facade
# parallax on the tiles the three streamed kits recess.
G=/mnt/gta2/gta2-linux; W=$G/districts_work; R=$G/wt_districts; TAG=$1; PY=$G/vreg/venv/bin/python
PK=$W/package_kit_r4
if [ ! -f $PK/.nopom ]; then
  python3 -c "import shutil; shutil.rmtree('$PK', ignore_errors=True)"
  cp -al $G/repo/package $PK
  $PY $R/tools/districts/remix_nopom.py hashes $G/repo/assets/textures_hd $W/nopom_hashes_r4.json \
    wil:$W/stagework/wil_stream0.kit ste:$W/stagework/ste_stream0.kit bil:$W/stagework/bil_stream0.kit
  $PY $R/tools/districts/remix_nopom.py patch $W/nopom_hashes_r4.json $PK/rtx-remix/mods/gta2hd && touch $PK/.nopom
fi
cp $R/linux/docker/districts_capture.py $R/linux/docker/districts_identity.py $R/linux/docker/keys_districts_identity_remix.sh $G/gamerun/
cd $G
for spec in "wil local_nav:m31" "ste gang:sciegang" "bil nav:m14"; do
  set -- $spec; l=$1
  SW=""; [ $l != wil ] && SW=$l
  PTS=$(GTA2_DATA=$G/game/data $PY $R/tools/districts/id_plan.py $W/stagework $l $2)
  STAGE=$G/stage_districts PACKAGE=$PK GTA2_INTRO=0 REMIX_NVCACHE=1 bash gamerun/remix_l4.sh dkri_${l}${TAG} 900 /work/keys_districts_identity_remix.sh \
    -e MODS_HD=1 -e SWAP_LEVEL=$SW -e GTA2_DIRECT_KEYS=1 -e SCENE_KEY=F11 -e GTA2DX9_SCENE_NO_CAR=1 -e 'GTA2DX9_REGRESS_CAM=Z:\tmp\vreg_cam.txt' \
    -e VREG_CAM=/tmp/vreg_cam.txt -e "DK_POINTS=$PTS" \
    -e "INI_SED=s/^scene_key=.*/scene_key=F11/; s/^nav_map=.*/nav_map=0/; s/^facade_kit=.*/facade_kit=1/; s/^log_keys=.*/log_keys=1/" \
    -e "SETTINGS_SED=s/^Paused=.*/Paused=1/; s/^StartHour=.*/StartHour=12.5/; s/^ClearSky=.*/ClearSky=1/" \
    -v $G/stage_districts/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro
  echo "$(date +%T) dkri_${l}${TAG}: $(ls out/dkri_${l}${TAG} | grep -c dk_) frames, FAULT $(grep -c FAULT out/dkri_${l}${TAG}/gta2dx9.log 2>/dev/null), $(grep -a 'Remix options' out/dkri_${l}${TAG}/gta2dx9.log | tail -1)"
done
echo "l4_id $TAG done"
