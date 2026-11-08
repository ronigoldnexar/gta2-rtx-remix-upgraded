#!/usr/bin/env bash
# swap_level.sh <game dir> <district bil|ste>: inside a run, make "level 1" load another
# district by copying its map, style, main script and mission scripts over Downtown's
# (wil.*, data/wil/) in the prefix copy only. Verifies the copy: data/ must be writable
# (game_mounts.sh binds it read-only unless it is given SWAP_LEVEL), and the swapped files
# must equal the district's. Exits 1 with "LEVEL SWAP FAILED" otherwise, so a run never
# plays Downtown while its plan or keys script believes it is in Industrial/Residential.
G=$1; L=$2
[ -z "$L" ] || [ "$L" = wil ] && exit 0
D="$G/data"
fail() { echo "LEVEL SWAP FAILED ($L): $*"; exit 1; }
[ -f "$D/$L.gmp" ] || fail "no $D/$L.gmp"
mountpoint -q "$D" 2>/dev/null && fail "$D is a bind mount (game_mounts.sh was called without SWAP_LEVEL); the game would play Downtown"
for e in gmp sty; do cp "$D/$L.$e" "$D/wil.$e" || fail "cp $L.$e"; done
S=$(ls "$D/$L."[sS][cC][rR] 2>/dev/null | head -1); [ -n "$S" ] || fail "no main script for $L"
cp "$S" "$D/wil.SCR" || fail "cp $S"
if [ -d "$D/$L" ]; then python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True); shutil.copytree(sys.argv[2], sys.argv[1])" "$D/wil" "$D/$L" || fail "copy $L/"; fi
for e in gmp sty; do cmp -s "$D/$L.$e" "$D/wil.$e" || fail "wil.$e differs from $L.$e after the copy"; done
cmp -s "$S" "$D/wil.SCR" || fail "wil.SCR differs from $(basename "$S") after the copy"
echo "level 1 is now $L (map, style, script verified)"
