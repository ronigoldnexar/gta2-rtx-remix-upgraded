#!/usr/bin/env bash
# Texture check: into the level, then first person at the spawn point turning
# through four headings and walking, with a screenshot at each stop. Fixed
# timings so two builds can be compared frame for frame.
export DISPLAY=:99
game() { xwininfo -root -tree | grep '"GTA2"' | grep "648x514\|640x480" | head -1 | awk '{print $1}'; }
shot() { ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/view_$1.png; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
for i in $(seq 1 30); do sleep 2; W=$(game); [ -n "$W" ] && break; done; echo "game window $W after $((i*2)) s"; xdotool windowfocus --sync "$W"; xdotool windowactivate "$W" 2>/dev/null
sleep 15
for i in 1 2 3 4 5; do tap Return; sleep 6; done
echo "t~61 in level, classic"; shot 0_classic
tap v; sleep 2; tap v; echo "V V -> first person"; sleep 3; shot 1_first_a
hold Left 1.2; sleep 1; shot 1_first_b
hold Left 1.2; sleep 1; shot 1_first_c
hold Left 1.2; sleep 1; shot 1_first_d
hold Up 3; sleep 1; shot 2_first_walked
hold Left 0.6; sleep 1; shot 2_first_walked_turned
tap v; echo "V -> classic"; sleep 3; shot 3_classic_again
