#!/usr/bin/env bash
# FIX-CLASSIC pm18 A/B on a road: warp (F10, GTA2DX9_SCENE_NO_CAR=1), stand still; 8 settled classic shots, V cycle x2, 8 settled classic shots after each.
export DISPLAY=:99; N=0
tap() { xdotool keydown "$1"; sleep 0.25; xdotool keyup "$1"; }
shot() { N=$((N+1)); ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/fc_$(printf %03d $N)_$1.png; echo "shot $N $1 $(date +%H:%M:%S.%N | cut -c1-12)"; }
bash /work/to_level.sh
sleep 1; tap F10; sleep ${PRE_WAIT:-9}; for i in $(seq 1 8); do shot pre; sleep 0.2; done
for r in 1 2; do
  tap v; sleep 2.5; shot r${r}third
  tap v; sleep 2.5; shot r${r}first
  tap v; for i in $(seq 1 6); do sleep 0.1; shot r${r}move; done; sleep 2; for i in $(seq 1 8); do shot r${r}post; sleep 0.2; done
done
echo done
