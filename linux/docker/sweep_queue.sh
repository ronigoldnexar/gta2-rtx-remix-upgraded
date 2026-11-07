#!/usr/bin/env bash
# Runs the whole city sweep, one chunk at a time (the slot helper shares the game slots).
cd "$(dirname "$0")/.."
for job in "$@"; do
  d=${job%%:*}; ch=${job#*:}
  gamerun/sweep_run.sh "$d" "$ch" 900 >> out/sweep_queue.log 2>&1
done
echo "queue done" >> out/sweep_queue.log
