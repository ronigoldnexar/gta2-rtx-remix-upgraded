#!/usr/bin/env bash
# A FIFO with priorities over the game-run slots, so a queued run starts the
# moment a slot frees instead of polling blindly. Same lock files as slot.sh.
#   runq.sh run [-p PRIO] [-n NAME] -- <command...>   (lower PRIO runs first; default 5)
#   runq.sh status                                   (waiting tickets and busy slots)
#   runq.sh wait                                     (block until the queue is empty)
# GTA2_SLOTS (default 4). A run is not started while the 1-minute load is above GTA2_LOAD_MAX (default 1.5 x nproc: 12 on 8 CPUs, 144 on 96)
# or while /tmp/gta2-load-hold exists (set by cpu_governor.sh when the host is overloaded).
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
# FIX-STAGE-PATH: a bind of a host path that does not exist is created by docker as an EMPTY root-owned directory, so a
# STAGE that is not there (14 Nov: STAGE=/home/ubuntu/stage_lighting, a path from another machine) gave the run an empty
# /stage: the game then ran the upstream v1.1 renderer (lt_cl7/8/10) or, since FIX-STAGE-COPY, the run aborted
# (lt_cl11/12). Refuse such a run here, before it is queued: the host side of a -v ...:/stage bind must be a directory
# holding gta2dx9.dll.
prev=
for a in "$@"; do
  v=
  case "$prev" in -v|--volume) v=$a;; esac
  case "$a" in --volume=*) v=${a#--volume=};; esac
  prev=$a
  [ -n "$v" ] || continue
  host=${v%%:*}; rest=${v#*:}; dest=${rest%%:*}
  [ "$dest" = /stage ] || continue
  if [ ! -f "$host/gta2dx9.dll" ]; then
    echo "runq: refusing run '$NAME': its stage $host has no gta2dx9.dll ($( [ -e "$host" ] && echo 'the directory is there but empty or incomplete' || echo 'no such directory on this host')); check STAGE= (absolute path on THIS host, e.g. /mnt/gta2/gta2-linux/stage_<you>)" >&2
    exit 2
  fi
done
# The player's container (gamerun/play.sh, PLAY_CPUSET=5-7) owns CPUs 5-7: a game container started
# here without a CPU set of its own is pinned to GAME_CPUSET (0-4), so a scripted run can never take
# the player's cores (PERF-2: unpinned runs held CPUs 5-7 at 75-97 % while the player drove).
# GAME_CPUSET= (empty) leaves the command alone.
# Default scripted set: everything below the player's CPUs (PLAY_CPUSET from /etc/profile.d/gta2.sh, 93-95 on the
# 96-CPU host, 5-7 on the 8-CPU host); QA-REGRESSION found every run pinned to 0-4 on 96 CPUs (9 Nov).
_pl=${PLAY_CPUSET:-5-7}; GAME_CPUSET=${GAME_CPUSET-0-$(( ${_pl%%-*} - 1 ))}
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
    # start a run only when the host has headroom: 1-minute load under GTA2_LOAD_MAX, MemAvailable over GTA2_MEM_MIN_GB,
    # and no hold flag from cpu_governor.sh (set when the host is overloaded)
    while [ -e /tmp/gta2-load-hold ] || [ -e /tmp/gta2-manual-hold ] || awk -v m="${GTA2_LOAD_MAX:-$(( $(nproc) * 3 / 2 ))}" '{exit !($1 > m)}' /proc/loadavg \
          || awk -v g="${GTA2_MEM_MIN_GB:-6}" '/MemAvailable/ {exit !($2 < g*1048576)}' /proc/meminfo; do sleep 15; done
    for i in $(seq 1 "$N"); do
      exec {fd}>"/tmp/gta2-game-slot-$i.lock"
      if flock -n "$fd"; then rm -f "$T"; echo "$NAME pid $$ since $(date +%H:%M:%S)" > "/tmp/gta2-game-slot-$i.who"; "$@"; rc=$?; rm -f "/tmp/gta2-game-slot-$i.who"; flock -u "$fd"; exit $rc; fi
      exec {fd}>&-
    done
  fi
  sleep 2
done
