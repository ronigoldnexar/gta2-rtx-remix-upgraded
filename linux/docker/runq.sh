#!/usr/bin/env bash
# A FIFO with priorities over the game-run slots, so a queued run starts the
# moment a slot frees instead of polling blindly. Same lock files as slot.sh.
#   runq.sh run [-p PRIO] [-n NAME] -- <command...>   (lower PRIO runs first; default 5)
#   runq.sh status                                   (waiting tickets and busy slots)
#   runq.sh wait                                     (block until the queue is empty)
# GTA2_SLOTS (default 6; 4 when the player is online and CPUs 5-7 are reserved) is the number of concurrent scripted game runs; see docs/throughput.md.
Q=/tmp/gta2-runq; mkdir -p "$Q"; N=${GTA2_SLOTS:-6}
case "${1:-}" in
status)
  echo "slots ($N):"; for i in $(seq 1 "$N"); do if flock -n "/tmp/gta2-game-slot-$i.lock" true 2>/dev/null; then echo "  $i free"; else echo "  $i busy: $(cat /tmp/gta2-game-slot-$i.who 2>/dev/null)"; fi; done
  echo "waiting:"; ls "$Q" 2>/dev/null | sort | while read t; do echo "  $t: $(sed -n 2p "$Q/$t")"; done; exit 0;;
wait) while [ -n "$(ls "$Q" 2>/dev/null)" ]; do sleep 5; done; exit 0;;
run) shift;;
*) sed -n 2,7p "$0"; exit 2;;
esac
PRIO=5; NAME=run
while [ $# -gt 0 ]; do case "$1" in -p) PRIO=$2; shift 2;; -n) NAME=$2; shift 2;; --) shift; break;; *) break;; esac; done
# The player's container (gamerun/play.sh, PLAY_CPUSET=5-7) owns CPUs 5-7: a game container started
# here without a CPU set of its own is pinned to GAME_CPUSET (0-4), so a scripted run can never take
# the player's cores (PERF-2: unpinned runs held CPUs 5-7 at 75-97 % while the player drove).
# GAME_CPUSET= (empty) leaves the command alone.
GAME_CPUSET=${GAME_CPUSET-0-4}
if [ -n "$GAME_CPUSET" ] && [[ " $* " == *" docker run "* ]] && [[ " $* " != *"--cpuset-cpus"* ]]; then
  args=(); done_=0; for a in "$@"; do args+=("$a"); if [ $done_ = 0 ] && [ "$a" = run ] && [ "${args[-2]:-}" = docker ]; then args+=("--cpuset-cpus=$GAME_CPUSET"); done_=1; fi; done
  set -- "${args[@]}"
fi
T="$Q/$(printf %02d "$PRIO")-$(date +%s%N)-$$"; printf '%s\n%s %s\n' "$$" "$NAME" "$*" > "$T"
trap 'rm -f "$T"' EXIT
while true; do
  for t in "$Q"/*; do [ -f "$t" ] || continue; p=$(head -1 "$t"); kill -0 "$p" 2>/dev/null || rm -f "$t"; done   # drop tickets of dead callers
  head=$(ls "$Q" 2>/dev/null | sort | head -1)
  if [ "$Q/$head" = "$T" ]; then
    for i in $(seq 1 "$N"); do
      exec {fd}>"/tmp/gta2-game-slot-$i.lock"
      if flock -n "$fd"; then rm -f "$T"; echo "$NAME pid $$ since $(date +%H:%M:%S)" > "/tmp/gta2-game-slot-$i.who"; "$@"; rc=$?; rm -f "/tmp/gta2-game-slot-$i.who"; flock -u "$fd"; exit $rc; fi
      exec {fd}>&-
    done
  fi
  sleep 2
done
