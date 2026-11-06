#!/usr/bin/env bash
# Run a command inside one of N game-run slots on a small host: at most N game
# containers at once, the rest wait. Usage: gamerun/slot.sh <command...>
# GPU generation jobs (SDXL/TRELLIS/ESRGAN) use the separate /tmp/gta2-gpu.lock.
N=${GTA2_SLOTS:-2}
for i in $(seq 1 "$N"); do
  exec {fd}>"/tmp/gta2-game-slot-$i.lock"
  if flock -n "$fd"; then "$@"; rc=$?; flock -u "$fd"; exit $rc; fi
  exec {fd}>&-
done
exec {fd}>"/tmp/gta2-game-slot-1.lock"; flock "$fd"; "$@"; rc=$?; flock -u "$fd"; exit $rc
