#!/usr/bin/env bash
cd "$(dirname "$0")/.."
for job in "$@"; do
  d=${job%%:*}; ch=${job#*:}
  TAG=r SWEEP_PLAN=/work/sweep_plan_${d}_retry.json gamerun/sweep_run.sh "$d" "$ch" 900 >> out/sweep_retry_queue.log 2>&1
done
echo "retry queue done" >> out/sweep_retry_queue.log
