#!/usr/bin/env bash
# Tiles/environment check: into the level, scene warp (F11) to the spot the ini
# names, then third person and first person with turns, a shot at each stop.
export DISPLAY=:99
game() { xwininfo -root -tree | grep '"GTA2"' | grep "648x514\|640x480" | head -1 | awk '{print $1}'; }
shot() { ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/view_$1.png; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
for i in $(seq 1 45); do sleep 2; W=$(game); [ -n "$W" ] && break; done; echo "game window $W after $((i*2)) s"; xdotool windowfocus --sync "$W"; xdotool windowactivate "$W" 2>/dev/null
sleep 15
for i in 1 2 3 4 5; do tap Return; sleep 6; done
echo "t~61 in level, classic"; shot 0_classic
tap F11; sleep 3; shot 0_classic_warped
tap v; sleep 3; shot 1_third_a
for k in b c d e f; do hold Left 0.9; sleep 1.2; shot 1_third_$k; done
tap v; sleep 3; shot 2_first_a
for k in b c d e f g h; do hold Left 0.75; sleep 1.2; shot 2_first_$k; done
tap v; sleep 3; shot 3_classic_again
