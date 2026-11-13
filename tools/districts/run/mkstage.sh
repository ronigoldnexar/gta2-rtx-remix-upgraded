#!/bin/bash
# mkstage.sh: the private stage for the districts POC: hard links of the shared stage, then my DLLs, ini and
# kit replaced by real copies (--remove-destination: never write through a hard link into repo/stage).
set -e
R=/mnt/gta2/gta2-linux/wt_districts; ST=/mnt/gta2/gta2-linux/stage_districts
[ -d $ST ] || cp -al /mnt/gta2/gta2-linux/repo/stage $ST
cd $R
for f in gta2dx9.dll d3ddll.dll; do cp --remove-destination dll/build/gta2dx9.dll $ST/$f; done
cp --remove-destination dll/build/gta2dx9.map $ST/gta2dx9.map
for f in gta2dx9_vid.dll Dmavideo.dll DMAGlide.dll; do cp --remove-destination vid/build/gta2dx9_vid.dll $ST/$f; done
cp --remove-destination package/gta2dx9.ini $ST/gta2dx9.ini
mkdir -p $ST/gta2dx9_districts
for f in assets/districts/*.kit assets/districts/*.dds; do cp --remove-destination $f $ST/gta2dx9_districts/; done
ls -la $ST/gta2dx9.dll $ST/gta2dx9_districts | head -20
