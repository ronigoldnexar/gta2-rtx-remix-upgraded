#!/bin/bash
# on the 6000: my round-6 stage (hard links of the shared stage + my DLL, ini, districts kit) and layer copy
set -e
D=/gta2/dist; cd $D
rm -rf x6; mkdir x6; tar xf r6.tar -C x6
python3 -c "import shutil; shutil.rmtree('$D/stage6', ignore_errors=True); shutil.rmtree('$D/ship6', ignore_errors=True)"
cp -al /gta2/repo/stage $D/stage6
for f in gta2dx9.dll d3ddll.dll gta2dx9.ini gta2dx9.map; do cp --remove-destination x6/$f stage6/$f; done
python3 -c "import shutil; shutil.rmtree('$D/stage6/gta2dx9_districts', ignore_errors=True)"
cp -r x6/gta2dx9_districts stage6/gta2dx9_districts
mkdir -p ship6; cp -al /gta2/ship/gta2hd ship6/gta2hd; cp /gta2/ship/rtx.conf ship6/ 2>/dev/null || true
python3 emis6.py ship6/gta2hd x6/gta2hd/textures
cp districts_drive.py keys_districts_drive_remix.sh /gta2/gamerun/
L=$D/run6.sh
sed -e 's#STAGE=/gta2/repo/stage#STAGE=/gta2/dist/stage6#' \
    -e 's#-v /gta2/repo/stage:/stage:ro#-v /gta2/dist/stage6:/stage:ro#' \
    -e 's#-v /gta2/ship:/ship:ro#-v /gta2/dist/ship6:/ship:ro#' \
    -e 's#rm -rf out/$NAME; mkdir -p out/$NAME#OUTD=/gta2/dist/out/$NAME; python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" $OUTD; mkdir -p $OUTD#' \
    -e 's#-v /gta2/out/$NAME:/out#-v /gta2/dist/out/$NAME:/out#' \
    -e 's#> out/$NAME.run.log#> /gta2/dist/out/$NAME.run.log#' \
    -e 's#s/^nav_map=.\*/nav_map=0/"#s/^nav_map=.*/nav_map=0/; s/^facade_kit=.*/facade_kit=${KIT:-1}/; s/^log_keys=.*/log_keys=1/"#' \
    -e 's#"${DOCKER_MORE\[@\]}"#-e "DK_ROUTE=$DK_ROUTE" -e DK_LEVEL=${DISTRICT:-wil} -e DK_LAPS=1 -e SWAP_LEVEL=${SWAP_LEVEL:-} -v /gta2/dist/stage6/gta2dx9_districts:/tmp/wp/drive_c/Games/GTA2/gta2dx9_districts:ro#' \
    -e 's#out/$NAME/#/gta2/dist/out/$NAME/#g' -e 's#find out/$NAME#find /gta2/dist/out/$NAME#' \
    /gta2/runremix_dlss.sh > $L
chmod +x $L
grep -c 'stage6' $L; grep -c 'ship6' $L; grep -c 'DK_ROUTE' $L
echo setup ok
