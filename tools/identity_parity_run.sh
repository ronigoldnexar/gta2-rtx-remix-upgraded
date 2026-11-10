#!/usr/bin/env bash
# FIX-CAR-IDENTITY-4: the per-build identity parity run, one command (docs/identity-system.md section 9.5).
#
#   tools/identity_parity_run.sh <stage dir> [name]        (from the repository root or anywhere; GTA2_GPU=<n>)
#
# Three queued game sessions on <stage dir> (through gamerun/grun.sh, one after the other, ~13 min together):
#   1. keys_identity_parity.sh: the player on foot and in the car the warp key seats him in, classic / 3D at the
#      classic camera / third / first at the same moment; tools/identity_parity.py checks one record (fingerprint)
#      per entity across the views and the colours against the classic sprite.
#      Twice, as two fresh sessions (same spawn): one fingerprint per entity and per vehicle input across them.
#   2. keys_paint_parity.sh: the player's stopped car forced to one model per body class (PARITY_MODELS, default
#      0 generated, 13/63/68 authored, 18 authored carkit, 4 remapped, 51 livery, 74 wreck) in six sprite paints
#      (the van also in its own sprite's two), from the classic camera; tools/paint_parity.py checks hue and lightness
#      against the paint, and liveries/wrecks against their style sprite (assets-src/cars/sprites).
# Output: out/<name>_idp and out/<name>_paint, and out/<name>_parity.md (both tables). Exit status: the number of
# failures of the two checks (0 = pass), so DEFECT-TRIAGE and the restage gate can call it as a gate.
# The keys scripts are copied from linux/docker into gamerun/ (the /work mount) when missing (never rewritten in
# place: a live run may be reading them).
set -u
STAGE=$(realpath "${1:?stage dir}")
NAME=${2:-parity_$(date +%m%d_%H%M)}
REPO=$(cd "$(dirname "$0")/.." && pwd)
WS=${GTA2_ROOT:-$(cd "$REPO/.." && pwd)}
PY=${PARITY_PY:-$WS/vreg/venv/bin/python}
cd "$WS" || exit 2
# FIX-CAR-IDENTITY-5: refreshed when the tracked copy differs (written beside and moved over: a live run keeps the old inode)
for f in keys_identity_parity.sh bev_parity.settings keys_paint_parity.sh paint_parity_probe.py; do
  cmp -s "$REPO/linux/docker/$f" gamerun/$f || { cp "$REPO/linux/docker/$f" gamerun/.$f.tmp && mv gamerun/.$f.tmp gamerun/$f; }
done
for d in "out/${NAME}_idp" "out/${NAME}_idp2" "out/${NAME}_paint"; do [ -e "$d" ] && { echo "identity_parity_run: $d exists, pick another name" >&2; exit 2; }; done
export STAGE GTA2_DIRECT_KEYS=1 FPS=0 PRIO=${PRIO:-1}
# Two FRESH sessions of the same capture (the owner's acceptance 2: the same spawn gives the same records): the check
# compares the player's and his car's fingerprints and every vehicle input's paint and fingerprint across them.
for s in idp idp2; do
  INI_SED='s/^warp_key=.*/warp_key=F9/' gamerun/grun.sh "${NAME}_$s" 150 keys_identity_parity.sh \
    -e GTA2DX9_IDENTITY_PROBE=1 -e SETTINGS_EXTRA=/work/bev_parity.settings -e GTA2DX9_STATE_EVERY=3 >/dev/null 2>&1
done
# One vehicle of each body class (FIX-CAR-IDENTITY-5): 0 generated, 13/63/68 authored, 18 authored carkit, 4 remapped
# (painted; with its own sprite's two paints, default and remap 36), 51 livery and 74 wreck (their own colours: one frame).
gamerun/grun.sh "${NAME}_paint" 450 keys_paint_parity.sh -e GTA2DX9_STATE_EVERY=3 \
  -e 'GTA2DX9_REGRESS_CAM=Z:\tmp\va2_cam.txt' -e VA2_CAM=/tmp/va2_cam.txt -e MODELS="${PARITY_MODELS:-13,0,18,63,68,4,51,74}" \
  -e POSES=top -e 'MODES=new:paint_ref=1' -e PAINTS=red,navy,black,yellow,green,white \
  -e EXTRA_PAINTS="4:van36,vanblue" -e ONE_PAINT_MODELS="51,56,12,34,74,72,73,75,76,77,78,79,80,81" >/dev/null 2>&1
REPORT="out/${NAME}_parity.md"
"$PY" "$REPO/tools/identity_parity.py" "out/${NAME}_idp" "out/${NAME}_idp2" --report "out/${NAME}_idp.md" --sheet "out/${NAME}_idp.png" >/dev/null 2>&1
A=$?
"$PY" "$REPO/tools/paint_parity.py" "out/${NAME}_paint" --report "out/${NAME}_paint.md" --sprites "$WS/assets-src/cars/sprites" >/dev/null 2>&1
B=$?
{ echo "# Identity parity, stage $STAGE ($(cat "$STAGE/.stage_commit" 2>/dev/null || echo '?')), $(date -u +%F' '%H:%MZ)"; echo
  echo "Record and three-view colours (identity_parity.py, exit $A; sheet out/${NAME}_idp.png):"; echo
  sed 's/^/    /' "out/${NAME}_idp.md" 2>/dev/null; echo
  cat "out/${NAME}_paint.md" 2>/dev/null; } > "$REPORT"
echo "identity_parity_run: $REPORT (failures: record/views $A, paint $B)"
exit $(( A + B > 100 ? 100 : A + B ))
