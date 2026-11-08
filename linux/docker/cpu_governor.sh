#!/usr/bin/env bash
# Lets scripted game runs borrow the player's CPUs (5-7) while nobody is connected to the play page,
# and gives them back the moment a client connects. Run from cron every minute.
# Idle = no established connection to the VNC server inside gta2-play-8090 for IDLE_MIN minutes.
IDLE_MIN=${IDLE_MIN:-5}; STAMP=/tmp/gta2-play-last-client
D="sudo -n docker"
if $D ps --format '{{.Names}}' | grep -qx gta2-play-8090; then
  n=$($D exec gta2-play-8090 sh -c "cat /proc/net/tcp 2>/dev/null | awk 'NR>1 && \$4==\"01\" {split(\$2,a,\":\"); if (a[2]==\"170C\") c++} END {print c+0}'" 2>/dev/null)
  [ "${n:-0}" -gt 0 ] && date +%s > "$STAMP"
fi
last=$(cat "$STAMP" 2>/dev/null || echo 0); now=$(date +%s)
if [ $((now - last)) -ge $((IDLE_MIN*60)) ]; then want=0-7; else want=0-4; fi
for c in $($D ps --format '{{.Names}}' | grep -v '^gta2-play-'); do
  cur=$($D inspect -f '{{.HostConfig.CpusetCpus}}' "$c" 2>/dev/null)
  [ "$cur" = "$want" ] || $D update --cpuset-cpus "$want" "$c" >/dev/null 2>&1
done
echo "$want" > /tmp/gta2-game-cpuset
