#!/usr/bin/env bash
# CARS-V3: Remix prims for converted cars. The shell atlases (<NNN>_<car>_0[_paint].tga) are image-to-3D atlases: their
# metal / roughness / lamps come from remix_model_pbr's atlas classes (no --src: the GLB's placeholder factors would
# override them); the parts (lamps, wheels, sign) take their source materials (--src: the sign's emissiveFactor).
# usage: remix_prims.sh <pN dir> <layer to merge into>
set -e
P=$1; L=$2; W=/mnt/gta2/gta2-linux/wt_cars3; PY=/mnt/gta2/ab_work/venv/bin/python
cp $P/src/manifest.json $P/models/manifest.json
rm -rf $P/rmx_a $P/rmx_b; mkdir -p $P/rmx_a $P/rmx_b
cd $W
flock /tmp/gta2-gen.lock taskset -c 0-4 nice -n 10 $PY tools/remix_model_materials.py $P/models $P/rmx_a --paint-roughness 0.12 --jobs 4 \
  --pattern '^[0-9]{3}_.*_0(_paint)?\.tga$' 2>&1 | tail -1 | cut -c1-160
flock /tmp/gta2-gen.lock taskset -c 0-4 nice -n 10 $PY tools/remix_model_materials.py $P/models $P/rmx_b --src $P/src --paint-roughness 0.12 --jobs 4 \
  --pattern '^[0-9]{3}_.*_(?!0(_paint)?\.tga$)[a-z].*\.tga$' 2>&1 | tail -1 | cut -c1-160
for d in rmx_a rmx_b; do $PY tools/remix_materials.py - $P/$d --wet-layer >/dev/null 2>&1; $PY tools/remix_layer_merge.py $P/$d $L $P/$d/model_prims.txt | tail -1; done
