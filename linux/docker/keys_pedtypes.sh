#!/usr/bin/env bash
# Pedestrian types: third person at the spawn plaza (civilians), punch people
# until the police come, shots along the way, then a first-person look round.
export DISPLAY=:99
game() { xwininfo -root -tree | grep '"GTA2"' | grep "648x514\|640x480" | head -1 | awk '{print $1}'; }
shot() { ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/pt_$1.png; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
for i in $(seq 1 45); do sleep 2; W=$(game); [ -n "$W" ] && break; done; echo "game window $W"; xdotool windowfocus --sync "$W"; xdotool windowactivate "$W" 2>/dev/null
sleep 15
for i in 1 2 3 4 5; do tap Return; sleep 6; done
sleep 2; tap v; sleep 3; shot 00_third_plaza
hold Up 2; sleep 1; shot 01_third_walk; hold Left 0.6; sleep 1; shot 02_third_turn
n=0
for round in $(seq 1 16); do
  hold Up 0.8
  for k in 1 2 3 4; do xdotool keydown Control_L; sleep 0.15; xdotool keyup Control_L; sleep 0.15; done
  [ $((round % 3)) = 0 ] && hold Right 0.5
  [ $((round % 2)) = 0 ] && { n=$((n+1)); shot "1${n}_brawl"; }
done
sleep 2; shot 20_third_after
tap v; sleep 3; shot 21_first
hold Left 0.8; sleep 1; shot 22_first_b; hold Left 0.8; sleep 1; shot 23_first_c; hold Left 0.8; sleep 1; shot 24_first_d
hold Up 3; sleep 1; shot 25_first_walked
tap v; sleep 2
