#!/usr/bin/env bash
# DISTRICTS: regenerate the facade kits at stage time, deterministically (same map, tiles and code: same bytes).
#   tools/districts/build_kits.sh <game data dir> <hd tiles dir> <out dir> [ship|all|poc]
# "ship" (restage.sh, make districts): every building of the three levels as streams (<lvl>.kit2), the style tables and
# the materials, nothing else; it fails (exit 1) if any of them is missing at the end.
# Runs the catalogue, the analysis (with the committed one-time Qwen3-VL archetypes, tools/districts/qwen/<lvl>.json),
# the pick and the kit for wil, ste and bil, and the kit's materials. "poc" (default): the picked building of each
# level and its street; "all": every building (large: see docs/districts-plan.md before staging it).
# Python with numpy and Pillow: DISTRICTS_PY (default python3). The generated meshes are never committed.
set -e
DATA=$1; HD=$2; OUT=$3; MODE=${4:-poc}
HERE=$(cd "$(dirname "$0")" && pwd); R=$(cd "$HERE/../.." && pwd)
PY=${DISTRICTS_PY:-python3}
FAIL=0; [ "$MODE" = ship ] && FAIL=1     # a ship build must not end without the kit
$PY -c "import numpy, PIL" 2>/dev/null || { echo "districts: $PY has no numpy/Pillow; no kits staged"; exit $FAIL; }
[ -f "$DATA/wil.gmp" ] || { echo "districts: no $DATA/wil.gmp; no kits staged"; exit $FAIL; }
[ "$MODE" = ship ] && DISTRICTS_STREAM=${DISTRICTS_STREAM:-"wil:all ste:all bil:all"}
# the analysis needs the HD tiles: without them every building comes out generic and the kit is nearly empty
[ "$MODE" = ship ] && { ls "$HD"/wil/tile_*.dds > /dev/null 2>&1 || { echo "districts: no HD tiles in $HD/wil; no kit built"; exit 1; }; }
WORK=${DISTRICTS_WORK:-$R/dll/build/districts}; mkdir -p "$WORK" "$OUT"
for l in wil ste bil; do
  $PY "$HERE/catalogue.py" "$DATA" $l "$WORK" > /dev/null
  [ -f "$HERE/qwen/$l.json" ] && cp "$HERE/qwen/$l.json" "$WORK/${l}_qwen_archetypes.json"
  $PY "$HERE/analyze.py" "$WORK" $l "$HD" "$R/tools/facade_boxes.json" > /dev/null
  $PY "$HERE/pick.py" "$WORK" $l 1 > /dev/null
  if [ "$MODE" != ship ]; then      # the per-level static kit (round 1-3 path); the streams replace it in a ship build
    GTA2_DATA="$DATA" $PY "$HERE/kit.py" "$WORK" $l "$OUT/$l.kit" --hd "$HD" $([ "$MODE" = all ] && echo --all) | head -1
    rm -f "$OUT/$l.kit.owners.json" "$OUT/$l.kit.anchors.json"
  fi
done
# DISTRICTS_STREAM="<lvl>:<district key> ..." (e.g. "wil:local_nav:m31 ste:gang:sciegang bil:local_nav:b22", or
# "wil:all ste:all bil:all"): each
# such district as that level's streamed kit (<lvl>.kit2: chunks, two levels of detail, packed vertices; the renderer
# prefers it to <lvl>.kit); one district per level
# "<lvl>:all" streams every building of the level (round 5: the whole city, every district with its style row)
for SPEC in ${DISTRICTS_STREAM:-}; do
  SL=${SPEC%%:*}; SD=${SPEC#*:}
  SEL="--district $SD"; [ "$SD" = all ] && SEL="--all"
  GTA2_DATA="$DATA" $PY "$HERE/kit.py" "$WORK" $SL "$WORK/${SL}_stream0.kit" --hd "$HD" $SEL | head -1
  GTA2_DATA="$DATA" $PY "$HERE/kit.py" "$WORK" $SL "$WORK/${SL}_stream1.kit" --hd "$HD" $SEL --coarse | head -1
  $PY "$HERE/pack_kit.py" "$WORK/${SL}_stream0.kit" "$WORK/${SL}_stream1.kit" "$OUT/$SL.kit2"
done
# the per-district style rows (grade, props, Remix options) for the renderer: tools/districts/styles.json
for l in wil ste bil; do $PY "$HERE/dstyle.py" "$WORK" $l "$OUT/$l.dstyle"; done
$PY "$HERE/kit_textures.py" "$OUT"
if [ "$MODE" = ship ]; then
  for f in wil.kit2 ste.kit2 bil.kit2 wil.dstyle ste.dstyle bil.dstyle kit_00.dds kit_27.dds; do
    [ -s "$OUT/$f" ] || { echo "districts: ship build is missing $f"; exit 1; }
  done
  for l in wil ste bil; do     # a whole level's stream is 17-46 MB; a few MB means the analysis or the kit went wrong
    [ "$(stat -c %s "$OUT/$l.kit2")" -gt 4000000 ] || { echo "districts: $l.kit2 is only $(stat -c %s "$OUT/$l.kit2") bytes"; exit 1; }
  done
  echo "districts: ship kit in $OUT: $(du -sm "$OUT" | cut -f1) MB, $(ls "$OUT" | wc -l) files"
fi
