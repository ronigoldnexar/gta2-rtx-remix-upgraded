#!/usr/bin/env bash
# Runs from cron every minute. Two jobs:
# 1. Lend the player's CPUs (5-7) to scripted game runs while nobody is connected to the play page
#    for IDLE_MIN minutes; pin them back to 0-4 within a minute of a connection.
# 2. Overload watchdog: when the 1-minute load passes LOAD_HIGH, hold the run queue (/tmp/gta2-load-hold,
#    honoured by runq.sh) and pause the newest scripted game containers until the load is under LOAD_LOW;
#    then unpause them oldest-first and release the hold. The play containers are never paused.
IDLE_MIN=${IDLE_MIN:-5}; LOAD_HIGH=${LOAD_HIGH:-22}; LOAD_LOW=${LOAD_LOW:-15}
STAMP=/tmp/gta2-play-last-client; HOLD=/tmp/gta2-load-hold; D="sudo -n docker"
# --- 1. player's cores
if $D ps --format '{{.Names}}' | grep -qx gta2-play-8090; then
  n=$($D exec gta2-play-8090 sh -c "awk 'NR>1 && \$4==\"01\" {split(\$2,a,\":\"); if (a[2]==\"170C\") c++} END {print c+0}' /proc/net/tcp" 2>/dev/null)
  [ "${n:-0}" -gt 0 ] && date +%s > "$STAMP"
fi
last=$(cat "$STAMP" 2>/dev/null || echo 0); now=$(date +%s)
if [ $((now - last)) -ge $((IDLE_MIN*60)) ]; then want=0-7; else want=0-4; fi
games=$($D ps --format '{{.Names}}' | grep -v '^gta2-play-')
for c in $games; do
  cur=$($D inspect -f '{{.HostConfig.CpusetCpus}}' "$c" 2>/dev/null)
  [ "$cur" = "$want" ] || $D update --cpuset-cpus "$want" "$c" >/dev/null 2>&1
done
echo "$want" > /tmp/gta2-game-cpuset
# --- 2. overload watchdog
load=$(awk '{print int($1)}' /proc/loadavg)
memavail=$(awk '/MemAvailable/ {print int($2/1048576)}' /proc/meminfo)
if [ "$load" -ge "$LOAD_HIGH" ] || [ "$memavail" -le "${MEM_LOW_GB:-3}" ]; then
  touch "$HOLD"
  # pause the newest running scripted containers, two per minute, until the load drops
  for c in $($D ps --filter status=running --format '{{.CreatedAt}}\t{{.Names}}' | grep -v 'gta2-play-' | sort -r | awk -F'\t' '{print $2}' | head -2); do
    $D pause "$c" >/dev/null 2>&1 && echo "$(date +%T) paused $c (load $load, mem avail ${memavail}G)" >> /tmp/gta2-governor.log
  done
elif [ "$load" -le "$LOAD_LOW" ] && [ "$memavail" -ge "${MEM_OK_GB:-8}" ]; then
  for c in $($D ps --filter status=paused --format '{{.CreatedAt}}\t{{.Names}}' | sort | awk -F'\t' '{print $2}' | head -2); do
    $D unpause "$c" >/dev/null 2>&1 && echo "$(date +%T) unpaused $c (load $load)" >> /tmp/gta2-governor.log
  done
  [ -z "$($D ps --filter status=paused -q)" ] && rm -f "$HOLD"
fi
