#!/usr/bin/env bash
# Third person for 60 s at the spawn plaza (people walk through it), turning
# slowly so the crowd passes in and out of view; shots every 5 s from run_game.sh.
export DISPLAY=:99
game() { xwininfo -root -tree | grep '"GTA2"' | grep "648x514\|640x480" | head -1 | awk '{print $1}'; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
for i in $(seq 1 45); do sleep 2; W=$(game); [ -n "$W" ] && break; done; echo "game window $W after $((i*2)) s"; xdotool windowfocus --sync "$W"; xdotool windowactivate "$W" 2>/dev/null
sleep 15
for i in 1 2 3 4 5; do tap Return; sleep 6; done
hold Down 2; sleep 1
tap v; echo "V -> third person"; sleep 2
for i in $(seq 1 12); do hold Left 0.5; sleep 4; done
hold Up 3; sleep 2
tap v; echo "V -> first person"; sleep 2
for i in $(seq 1 6); do hold Left 0.5; sleep 4; done
tap v; echo "V -> classic"; sleep 3
