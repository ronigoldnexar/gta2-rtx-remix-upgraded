#!/usr/bin/env bash
# PERF-3: frame times of the play container (gta2-play-$PORT on CPUs 5-7) during a chase-view
# drive (perf2_drive.py run inside it, DRIVE_SECS=90), with or without a browser connected
# (headless Chromium on the noVNC page, pinned to CPUs 0-4). Each run restarts the container
# (play.sh, PLAY_FRAME_LOG=1 and the devtools keys) so every run starts from the same state;
# it refuses when anyone else is connected. PLAY_X11VNC / PLAY_VNC_NICE pass encoder settings.
#   perf3_play.sh <label> <none|novnc> [quality] [compression]     env PORT (8090), STAGE
cd "$(dirname "$0")/.."
LABEL=$1; CLIENT=$2; Q=${3:-5}; C=${4:-3}; PORT=${PORT:-8090}; NAME=gta2-play-$PORT
OUT=out/perf3_play; mkdir -p "$OUT"; TSV=out/play-$PORT/frames.tsv
D="sudo -n docker"
N=$($D exec $NAME sh -c 'grep -c "connecting to" /tmp/websockify.log' 2>/dev/null | head -1)
OURS=$(cat "$OUT/.ours" 2>/dev/null | head -1)
if [ "${N:-0}" -gt "$OURS" ]; then echo "someone is connected to $NAME ($N connections, $OURS ours): not restarting"; exit 1; fi
PLAY_BIND=0.0.0.0 PLAY_CPUSET=5-7 PLAY_FRAME_LOG=1 INI_SED='s/^log_keys=.*/log_keys=1/; s/^warp_key=.*/warp_key=F9/; s/^scene_key=.*/scene_key=F10/' \
  gamerun/play.sh plain "$PORT" > /dev/null
echo 0 > "$OUT/.ours"
for i in $(seq 1 40); do $D logs $NAME 2>&1 | grep -q "game window .* focused" && break; sleep 3; done
$D exec $NAME bash /work/to_level.sh
if [ "$CLIENT" = novnc ]; then
  echo 1 > "$OUT/.ours"
  taskset -c 0-4 "$HOME/.cache/pw-venv/bin/python" gamerun/perf3_vnc_client.py "http://127.0.0.1:$PORT" $(( ${DRIVE_SECS:-90} + 70 )) "$OUT/$LABEL.client.json" "$Q" "$C" > "$OUT/$LABEL.client.log" 2>&1 &
  CPID=$!; sleep 8
fi
$D exec $NAME sh -c 'top -b -d 10 -n 12 | grep -A12 "^top -"' > "$OUT/$LABEL.top.txt" 2>&1 &
$D exec -e DRIVE_SECS=${DRIVE_SECS:-90} -e ROUTE_SEED=${ROUTE_SEED:-7} $NAME python3 /work/perf2_drive.py > "$OUT/$LABEL.drive.log" 2>&1
sleep 6; cp "$TSV" "$OUT/$LABEL.tsv"; cp out/play-$PORT/gta2dx9.log "$OUT/$LABEL.gta2dx9.log" 2>/dev/null
[ -n "${CPID:-}" ] && { kill $CPID 2>/dev/null; wait $CPID 2>/dev/null; }
echo "$LABEL ($CLIENT q$Q c$C, x11vnc '${PLAY_X11VNC:-default}', nice ${PLAY_VNC_NICE:-0}):"
python3 gamerun/perf2_analyze.py "$OUT/$LABEL.tsv" | head -3
