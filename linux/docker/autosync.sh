#!/usr/bin/env bash
# Every run: snapshot the working tree (tracked + new source/docs/scripts, never out/ or generated art)
# onto the camera-modes-wip branch on GitHub without touching the curated camera-modes branch.
cd "$HOME/gta2-linux/repo" || exit 1
git add -A . ':!out' >/dev/null 2>&1
git diff --cached --quiet && exit 0
tree=$(git write-tree)
parent=$(git rev-parse -q --verify refs/heads/camera-modes-wip 2>/dev/null || git rev-parse HEAD)
commit=$(echo "wip autosave $(date -u +%FT%TZ) on top of $(git rev-parse --short HEAD)" | git commit-tree "$tree" -p "$parent" -p HEAD 2>/dev/null || echo "wip autosave $(date -u +%FT%TZ)" | git commit-tree "$tree" -p "$parent")
git update-ref refs/heads/camera-modes-wip "$commit"
git reset -q
git push -q fork refs/heads/camera-modes-wip:refs/heads/camera-modes-wip 2>&1 | tail -1
