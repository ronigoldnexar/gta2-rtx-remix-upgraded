#!/usr/bin/env bash
# A FIFO with priorities over the game-run slots, so a queued run starts the
# moment a slot frees instead of polling blindly. Same lock files as slot.sh.
#   runq.sh run [-p PRIO] [-n NAME] -- <command...>   (lower PRIO runs first; default 5)
#   runq.sh status                                   (waiting tickets and busy slots)
#   runq.sh wait                                     (block until the queue is empty)
# GTA2_SLOTS (default 4) is the number of concurrent scripted game runs; see docs/throughput.md.
Q=/tmp/gta2-runq; mkdir -p "$Q"; N=${GTA2_SLOTS:-4}
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
