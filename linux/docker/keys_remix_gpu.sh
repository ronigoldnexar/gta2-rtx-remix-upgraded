#!/usr/bin/env bash
# Remix on a GPU: wait for the game window (shader prewarm can take minutes),
# Return through the front end, then the three views with walking; a Remix
# screenshot (F12) and an x11grab shot at each stop.
export DISPLAY=:99
# The game's own window is the 648x514 / 640x480 one; Remix's present window and ours are the larger ones.
game() { xwininfo -root -tree | grep '"GTA2"' | grep "648x514\|640x480" | head -1 | awk '{print $1}'; }
shot() { ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/view_$1.png; xdotool key F12; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
for i in $(seq 1 120); do sleep 2; W=$(game); [ -n "$W" ] && break; done; echo "$(date +%T) game window $W after $((i*2)) s"; xdotool windowfocus --sync "$W" 2>/dev/null; xdotool windowactivate "$W" 2>/dev/null
# no fixed prewarm sleep: the first view shot waits for the shader compile (remix_shaders_wait.py recheck below)
sleep ${PREWARM_WAIT:-10}
# Remix's welcome dialog sits over the front end: "Never Show This Again", then focus back on the game.
xdotool mousemove 603 578 click 1; sleep 1; xdotool windowfocus --sync "$W" 2>/dev/null; xdotool windowactivate "$W" 2>/dev/null; sleep 1
for i in 1 2 3 4 5 6 7 8; do tap Return; sleep 8; shot menu_$i; done
python3 /work/remix_shaders_wait.py recheck 300   # the level's own shaders compile on first sight
echo "$(date +%T) should be in the level, classic"; shot 0_classic
hold Up 3; shot 0_classic_walked
tap v; echo "V -> third person"; sleep 4; shot 1_third
hold Up 4; shot 1_third_walked; hold Left 1; sleep 1; shot 1_third_turned
tap v; echo "V -> first person"; sleep 4; shot 2_first
hold Up 4; shot 2_first_walked; hold Right 1; sleep 1; shot 2_first_turned; hold Up 3; shot 2_first_walked2
tap v; echo "V -> classic"; sleep 4; shot 3_classic_again
echo "$(date +%T) done"
