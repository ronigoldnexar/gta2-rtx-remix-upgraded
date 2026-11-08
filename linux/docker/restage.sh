#!/usr/bin/env bash
# Rebuild and restage the DLL + models only when no game run can be using the shared stage:
# waits (up to 30 min) for the build lock and all four game slots, then runs make stage.
# A `make stage` during a run recopies the models folder and leaves that run with white figures.
set -e
cd "$(dirname "$0")/../.."
W=${RESTAGE_WAIT:-1800}
exec 9>/tmp/gta2-build.lock; flock -w "$W" 9
exec 5>/tmp/gta2-game-slot-1.lock; flock -w "$W" 5
exec 6>/tmp/gta2-game-slot-2.lock; flock -w "$W" 6
exec 7>/tmp/gta2-game-slot-3.lock; flock -w "$W" 7
exec 8>/tmp/gta2-game-slot-4.lock; flock -w "$W" 8
make -j8 stage 2>&1 | grep -i -E 'error|warning: unused' || true
ls -la --time-style=+%H:%M stage/gta2dx9.dll | awk '{print "staged", $6}'
