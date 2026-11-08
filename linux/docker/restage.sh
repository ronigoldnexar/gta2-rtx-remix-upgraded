#!/usr/bin/env bash
# Rebuild the shared stage from COMMITTED code only (a detached worktree of HEAD), so other agents' partial
# working-tree edits never reach the play page, then copy the DLLs in by atomic rename (running games keep
# their mapped copy) and refresh the models folder only when no game run holds a slot.
# Usage: restage.sh              -> DLLs from HEAD by atomic rename, models swapped by directory rename (no slot wait)
#        restage.sh --dll-only    -> DLLs only
#        restage.sh --wait-slots  -> old behaviour: wait for all four game slots before touching the models
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
  # Models: build in the worktree, copy beside the live folder, then swap by rename. Running games keep
  # the files they already opened; no slot wait needed. (--wait-slots keeps the old behaviour.)
  if [ "${1:-}" = "--wait-slots" ]; then
    WAIT=${RESTAGE_WAIT:-1800}
    exec 5>/tmp/gta2-game-slot-1.lock; flock -w "$WAIT" 5
    exec 6>/tmp/gta2-game-slot-2.lock; flock -w "$WAIT" 6
    exec 7>/tmp/gta2-game-slot-3.lock; flock -w "$WAIT" 7
    exec 8>/tmp/gta2-game-slot-4.lock; flock -w "$WAIT" 8
  fi
  ( cd "$W" && flock /tmp/gta2-build.lock nice -n 10 make stage > "$W_LOG" 2>&1 ) || { tail -20 "$W_LOG"; exit 1; }
  rm -rf /home/roni_goldshmidt/gta2-linux/repo/stage/.gta2dx9_models.new /home/roni_goldshmidt/gta2-linux/repo/stage/.gta2dx9_models.old
  cp -al "$W/stage/gta2dx9_models" stage/.gta2dx9_models.new 2>/dev/null || cp -a "$W/stage/gta2dx9_models" stage/.gta2dx9_models.new
  mv stage/gta2dx9_models stage/.gta2dx9_models.old && mv stage/.gta2dx9_models.new stage/gta2dx9_models
  rm -rf /home/roni_goldshmidt/gta2-linux/repo/stage/.gta2dx9_models.old
  echo "models swapped from HEAD at $(date +%H:%M)"
fi
git worktree remove --force "$W" 2>/dev/null || true
