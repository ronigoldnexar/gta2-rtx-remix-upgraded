#!/bin/bash
# mkstage.sh: the private stage for the districts work: hard links of the shared stage, then my DLLs and ini as real
# copies (--remove-destination: never write through a hard link into repo/stage), and the kits regenerated into it
# by the same stage-time build the Makefile runs (tools/districts/build_kits.sh).
set -e
G=/mnt/gta2/gta2-linux; R=$G/wt_districts; ST=$G/stage_districts
[ -d $ST ] || cp -al $G/repo/stage $ST
cd $R
for f in gta2dx9.dll d3ddll.dll; do cp --remove-destination dll/build/gta2dx9.dll $ST/$f; done
cp --remove-destination dll/build/gta2dx9.map $ST/gta2dx9.map
cp --remove-destination package/gta2dx9.ini $ST/gta2dx9.ini
python3 -c "import shutil; shutil.rmtree('$ST/gta2dx9_districts', ignore_errors=True)"
DISTRICTS_STREAM=${DISTRICTS_STREAM:-"wil:local_nav:m31 ste:gang:sciegang bil:nav:m14"} DISTRICTS_PY=$G/vreg/venv/bin/python DISTRICTS_WORK=${DISTRICTS_WORK:-$G/districts_work/stagework} bash tools/districts/build_kits.sh $G/game/data $G/repo/assets/textures_hd $ST/gta2dx9_districts ${1:-poc}
ls -la $ST/gta2dx9_districts | head -20
