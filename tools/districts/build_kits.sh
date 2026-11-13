#!/usr/bin/env bash
# DISTRICTS: regenerate the facade kits at stage time, deterministically (same map, tiles and code: same bytes).
#   tools/districts/build_kits.sh <game data dir> <hd tiles dir> <out dir> [all|poc]
# Runs the catalogue, the analysis (with the committed one-time Qwen3-VL archetypes, tools/districts/qwen/<lvl>.json),
# the pick and the kit for wil, ste and bil, and the kit's materials. "poc" (default): the picked building of each
# level and its street; "all": every building (large: see docs/districts-plan.md before staging it).
# Python with numpy and Pillow: DISTRICTS_PY (default python3). The generated meshes are never committed.
set -e
DATA=$1; HD=$2; OUT=$3; MODE=${4:-poc}
HERE=$(cd "$(dirname "$0")" && pwd); R=$(cd "$HERE/../.." && pwd)
PY=${DISTRICTS_PY:-python3}
$PY -c "import numpy, PIL" 2>/dev/null || { echo "districts: $PY has no numpy/Pillow; no kits staged"; exit 0; }
[ -f "$DATA/wil.gmp" ] || { echo "districts: no $DATA/wil.gmp; no kits staged"; exit 0; }
WORK=${DISTRICTS_WORK:-$R/dll/build/districts}; mkdir -p "$WORK" "$OUT"
for l in wil ste bil; do
  $PY "$HERE/catalogue.py" "$DATA" $l "$WORK" > /dev/null
  [ -f "$HERE/qwen/$l.json" ] && cp "$HERE/qwen/$l.json" "$WORK/${l}_qwen_archetypes.json"
  $PY "$HERE/analyze.py" "$WORK" $l "$HD" "$R/tools/facade_boxes.json" > /dev/null
  $PY "$HERE/pick.py" "$WORK" $l 1 > /dev/null
  GTA2_DATA="$DATA" $PY "$HERE/kit.py" "$WORK" $l "$OUT/$l.kit" --hd "$HD" $([ "$MODE" = all ] && echo --all) | head -1
  rm -f "$OUT/$l.kit.owners.json" "$OUT/$l.kit.anchors.json"
done
# DISTRICTS_STREAM="<lvl>:<district key>" (e.g. wil:local_nav:m31): that district of that level as a streamed kit
# (<lvl>.kit2: chunks, two levels of detail, packed vertices; the renderer prefers it to <lvl>.kit)
if [ -n "${DISTRICTS_STREAM:-}" ]; then
  SL=${DISTRICTS_STREAM%%:*}; SD=${DISTRICTS_STREAM#*:}
  GTA2_DATA="$DATA" $PY "$HERE/kit.py" "$WORK" $SL "$WORK/${SL}_stream0.kit" --hd "$HD" --district "$SD" | head -1
  GTA2_DATA="$DATA" $PY "$HERE/kit.py" "$WORK" $SL "$WORK/${SL}_stream1.kit" --hd "$HD" --district "$SD" --coarse | head -1
  $PY "$HERE/pack_kit.py" "$WORK/${SL}_stream0.kit" "$WORK/${SL}_stream1.kit" "$OUT/$SL.kit2"
fi
$PY "$HERE/kit_textures.py" "$OUT"
