#!/usr/bin/env bash
# Pedestrian types dealt out across the crowd (ped_remap_override=-2): third
# person at the plaza, walking round with shots, then first person.
export DISPLAY=:99
game() { xwininfo -root -tree | grep '"GTA2"' | grep "648x514\|640x480" | head -1 | awk '{print $1}'; }
shot() { ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/pt_$1.png; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
for i in $(seq 1 45); do sleep 2; W=$(game); [ -n "$W" ] && break; done; echo "game window $W"; xdotool windowfocus --sync "$W"; xdotool windowactivate "$W" 2>/dev/null
sleep 15
for i in 1 2 3 4 5; do tap Return; sleep 6; done
sleep 2; tap v; sleep 3; shot 00_third
for k in 1 2 3 4 5 6 7 8; do hold Up 1.2; sleep 0.8; shot 0${k}_third_walk; hold Left 0.45; sleep 0.5; done
tap v; sleep 3; shot 10_first
for k in 1 2 3 4 5 6; do hold Left 0.5; sleep 1; shot 1${k}_first_turn; done
hold Up 3; sleep 1; shot 20_first_walked
tap v; sleep 2
