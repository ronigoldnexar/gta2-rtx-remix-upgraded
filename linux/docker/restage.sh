#!/usr/bin/env bash
# Rebuild the shared stage from COMMITTED code only (a detached worktree of HEAD), so other agents' partial
# working-tree edits never reach the play page, then copy the DLLs in by atomic rename (running games keep
# their mapped copy) and refresh the models folder only when no game run holds a slot.
# Usage: restage.sh            -> DLLs from HEAD, models refreshed if all slots are free (waits up to RESTAGE_WAIT)
#        restage.sh --dll-only -> DLLs from HEAD only, no waiting
set -e
cd "$(dirname "$0")/../.."
W=/tmp/gta2-restage-worktree; W_LOG=/tmp/gta2-restage-build.log
git worktree remove --force "$W" 2>/dev/null || true
git worktree add -f --detach "$W" HEAD >/dev/null
( cd "$W" && flock /tmp/gta2-build.lock nice -n 10 make -j4 dll/build/gta2dx9.dll vid/build/gta2dx9_vid.dll > "$W_LOG" 2>&1 ) || { tail -20 "$W_LOG"; exit 1; }
for f in dll/build/gta2dx9.dll vid/build/gta2dx9_vid.dll; do
  b=$(basename "$f"); cp "$W/$f" "stage/.$b.new" && mv -f "stage/.$b.new" "stage/$b"
done
echo "staged DLLs from $(git -C "$W" rev-parse --short HEAD) at $(date +%H:%M)"
if [ "${1:-}" != "--dll-only" ]; then
  WAIT=${RESTAGE_WAIT:-1800}
  exec 9>/tmp/gta2-build.lock; flock -w "$WAIT" 9
  exec 5>/tmp/gta2-game-slot-1.lock; flock -w "$WAIT" 5
  exec 6>/tmp/gta2-game-slot-2.lock; flock -w "$WAIT" 6
  exec 7>/tmp/gta2-game-slot-3.lock; flock -w "$WAIT" 7
  exec 8>/tmp/gta2-game-slot-4.lock; flock -w "$WAIT" 8
  ( cd "$W" && nice -n 10 make stage > "$W_LOG" 2>&1 ) || { tail -20 "$W_LOG"; exit 1; }
  rsync -a --delete "$W/stage/gta2dx9_models/" stage/gta2dx9_models/ 2>/dev/null || cp -a "$W/stage/gta2dx9_models/." stage/gta2dx9_models/
  echo "models refreshed from HEAD at $(date +%H:%M)"
fi
git worktree remove --force "$W" 2>/dev/null || true
