#!/usr/bin/env bash
# FIX-CLASSIC pm15 classic check: the level's opening subtitle in the classic view (no V), shots every ~0.4 s for 16 s,
# then one V cycle and 10 s more of classic. Run twice: [hud] modern=1 and modern=0, compare the subtitle rows.
export DISPLAY=:99; N=0
tap() { xdotool keydown "$1"; sleep 0.25; xdotool keyup "$1"; }
shot() { N=$((N+1)); ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/fs_$(printf %03d $N)_$1.png; echo "shot $N $1 $(date +%H:%M:%S.%N | cut -c1-12)"; }
bash /work/to_level.sh
for i in $(seq 1 40); do shot c; sleep 0.15; done
tap v; sleep 2.5; tap v; sleep 2.5; tap v; sleep 3
for i in $(seq 1 20); do shot cpost; sleep 0.15; done
echo done
