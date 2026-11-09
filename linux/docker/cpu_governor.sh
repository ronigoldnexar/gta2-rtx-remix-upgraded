#!/usr/bin/env bash
# Runs from cron every minute. Two jobs:
# 1. Lend the player's CPUs (5-7) to scripted game runs while nobody is connected to the play page
#    for IDLE_MIN minutes; pin them back to 0-4 within a minute of a connection.
# 2. Overload watchdog: when the 1-minute load passes LOAD_HIGH, hold the run queue (/tmp/gta2-load-hold,
#    honoured by runq.sh) and pause the newest scripted game containers until the load is under LOAD_LOW;
#    then unpause them oldest-first and release the hold. The play containers are never paused.
# Sizes scale with the host (9 Nov: the 8-CPU defaults 22/15 and the 0-7 pin starved a 96-CPU host, see
# docs/throughput.md "Governor"): LOAD_HIGH = max(22, 1.15*nproc), LOAD_LOW = max(15, 0.85*nproc); the player's
# CPUs are the top three (PLAY_CPUSET, 5-7 on 8 CPUs, 93-95 on 96); the scripted runs get everything below them
# while a player is connected and the whole host otherwise. A container that a launcher pinned to its own CPU set
# (anything other than the two governor sets or none) is left alone: only the governor's own pins are moved.
IDLE_MIN=${IDLE_MIN:-5}; NCPU=$(nproc)
h=$((NCPU*115/100)); l=$((NCPU*85/100)); [ "$h" -lt 22 ] && h=22; [ "$l" -lt 15 ] && l=15
LOAD_HIGH=${LOAD_HIGH:-$h}; LOAD_LOW=${LOAD_LOW:-$l}
PLAY_CPUSET=${PLAY_CPUSET:-$((NCPU-3))-$((NCPU-1))}; play_lo=${PLAY_CPUSET%%-*}
BUSY_SET=0-$((play_lo-1)); IDLE_SET=0-$((NCPU-1))
STAMP=/tmp/gta2-play-last-client; HOLD=/tmp/gta2-load-hold; D="sudo -n docker"
# --- 1. player's cores
for p in $($D ps --format '{{.Names}}' | grep '^gta2-play-'); do
  n=$($D exec "$p" sh -c "awk 'NR>1 && \$4==\"01\" {split(\$2,a,\":\"); if (a[2]==\"170C\") c++} END {print c+0}' /proc/net/tcp" 2>/dev/null)
  [ "${n:-0}" -gt 0 ] && date +%s > "$STAMP"
done
last=$(cat "$STAMP" 2>/dev/null || echo 0); now=$(date +%s)
if [ $((now - last)) -ge $((IDLE_MIN*60)) ]; then want=$IDLE_SET; else want=$BUSY_SET; fi
games=$($D ps --format '{{.Names}}' | grep -v '^gta2-play-')
for c in $games; do
  cur=$($D inspect -f '{{.HostConfig.CpusetCpus}}' "$c" 2>/dev/null)
  [ "$cur" = "$want" ] && continue
  case "$cur" in ""|"$BUSY_SET"|"$IDLE_SET"|0-4|0-7) ;; *) continue ;; esac   # a launcher's own pin stays
  # A --gpus container whose NVIDIA nodes are not also in its --device list must not be updated: on cgroup v2
  # `docker update` rebuilds the device filter from that list and the driver's next open of /dev/nvidiaN
  # gets EPERM (Vulkan "Failed to create fence", commit 68bec1e). Launchers pass the nodes via nv_devices.sh;
  # a container started without them keeps its cpuset.
  gpu=$($D inspect -f '{{len .HostConfig.DeviceRequests}} {{range .HostConfig.Devices}}{{.PathOnHost}} {{end}}' "$c" 2>/dev/null)
  if [ "${gpu%% *}" != 0 ] && ! grep -q '/dev/nvidiactl' <<<"$gpu"; then
    echo "$(date +%T) kept cpuset of $c (GPU container without --device NVIDIA nodes)" >> /tmp/gta2-governor.log; continue
  fi
  $D update --cpuset-cpus "$want" "$c" >/dev/null 2>&1
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
