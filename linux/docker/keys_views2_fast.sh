#!/usr/bin/env bash
# To the level with Return, then cycle the views with V held for 0.3 s, a
# screenshot straight after each switch, walking between them.
export DISPLAY=:99
game() { xwininfo -root -tree | grep '"GTA2"' | grep "648x514\|640x480" | head -1 | awk '{print $1}'; }
shot() { ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/view_$1.png; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
bash /work/to_level.sh


echo "t~61 in level, classic"; shot 0_classic
hold Up 3; shot 0_classic_walked
tap v; echo "V -> third person"; sleep 3; shot 1_third
hold Up 4; shot 1_third_walked; hold Left 1; sleep 1; shot 1_third_turned
tap v; echo "V -> first person"; sleep 3; shot 2_first
hold Up 4; shot 2_first_walked; hold Right 1; sleep 1; shot 2_first_turned
tap v; echo "V -> classic"; sleep 3; shot 3_classic_again
