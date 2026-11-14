#!/usr/bin/env bash
# DISTRICTS ship: sync the deployed game launchers in gamerun/ with the repo after the merge, so play containers,
# scripted runs and restage's stage check see gta2dx9_districts. Run ONCE, by hand, after the merge go-ahead:
#     bash tools/districts/run/sync_gamerun.sh [REV] [BASE]
# REV  (default camera-modes): the commit whose linux/docker versions are deployed (the merged branch).
# BASE (default 4b7bd2ff): the commit the deployed files must still match before the sync (camera-modes before the
#      merge; checked 14 Nov: all six deployed files equal it). A deployed file that matches neither BASE nor REV has
#      local edits: the script refuses and changes nothing, so nobody's live change is overwritten.
# For each file: back up the deployed one (gamerun/.sync_backup_<time>/), install REV's version via a temp file and an
# atomic rename (a running container keeps the file it opened), then diff-check the installed file against REV's blob.
# Undo: cp -p gamerun/.sync_backup_<time>/* gamerun/
set -euo pipefail
REV=${1:-camera-modes}; BASE=${2:-4b7bd2ff}
cd "$(dirname "$0")/../../.."                       # the repo checkout
G=$(cd ../gamerun && pwd)                           # the deployed launchers
FILES="game_mounts.sh run_game.sh run_game_gpu.sh run_game_remix_gpu.sh play_game.sh stage_check.py"
git rev-parse -q --verify "$REV^{commit}" > /dev/null || { echo "sync refused: no commit $REV"; exit 1; }
git rev-parse -q --verify "$BASE^{commit}" > /dev/null || { echo "sync refused: no commit $BASE"; exit 1; }
# REV must carry the districts changes (guards against syncing from an unmerged branch)
for f in $FILES; do
  git show "$REV:linux/docker/$f" | grep -q 'gta2dx9_districts' || { echo "sync refused: $REV:linux/docker/$f has no gta2dx9_districts (not merged?)"; exit 1; }
done
# 1) every deployed file must be BASE's or REV's version: no drift
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
for f in $FILES; do
  git show "$BASE:linux/docker/$f" > "$TMP/$f.base"; git show "$REV:linux/docker/$f" > "$TMP/$f.rev"
  if cmp -s "$G/$f" "$TMP/$f.rev"; then echo "  $f: already REV's version"; continue; fi
  cmp -s "$G/$f" "$TMP/$f.base" || { echo "sync refused: gamerun/$f has local changes (neither $BASE nor $REV):"; diff -u "$TMP/$f.base" "$G/$f" | head -30; exit 1; }
done
# 2) back up, 3) install atomically, 4) diff-check
B="$G/.sync_backup_$(date +%Y%m%d_%H%M%S)"; mkdir -p "$B"
for f in $FILES; do cp -p "$G/$f" "$B/$f"; done
echo "backup: $B"
for f in $FILES; do
  cmp -s "$G/$f" "$TMP/$f.rev" && continue
  cp "$TMP/$f.rev" "$G/.$f.sync" && chmod --reference="$B/$f" "$G/.$f.sync" && mv -f "$G/.$f.sync" "$G/$f"
done
fail=0
for f in $FILES; do
  if cmp -s "$G/$f" "$TMP/$f.rev"; then
    echo "  $f: installed, matches $REV ($(diff "$B/$f" "$G/$f" | grep -c '^[<>]') changed lines)"
  else
    echo "  $f: MISMATCH after install"; fail=1
  fi
done
[ $fail = 0 ] || { echo "sync FAILED: restore with  cp -p $B/* $G/"; exit 1; }
bash -n "$G/game_mounts.sh" "$G/run_game.sh" "$G/run_game_gpu.sh" "$G/run_game_remix_gpu.sh" "$G/play_game.sh"
python3 -m py_compile "$G/stage_check.py"
echo "sync ok: gamerun launchers = $REV ($(git rev-parse --short "$REV")); undo: cp -p $B/* $G/"
