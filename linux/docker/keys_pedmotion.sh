#!/usr/bin/env bash
# Pedestrian motion check: third person at the spawn plaza, standing while the
# people walk past (turns, starts, stops), then the player's own start, stop
# and about-turn.
export DISPLAY=:99
game() { xwininfo -root -tree | grep '"GTA2"' | grep "648x514\|640x480" | head -1 | awk '{print $1}'; }
mark() { echo "$(date +%s.%N) $1" >> /out/marks.txt; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
for i in $(seq 1 45); do sleep 2; W=$(game); [ -n "$W" ] && break; done; echo "game window $W after $((i*2)) s"; xdotool windowfocus --sync "$W"; xdotool windowactivate "$W" 2>/dev/null
sleep 15
for i in 1 2 3 4 5; do tap Return; sleep 6; done
mark level; sleep 1
hold Left 1.3; sleep 0.5
tap v; mark third; sleep 30
mark walk1; hold Up 3; mark stop1; sleep 2.5
mark walk2; hold Up 2; mark turn; hold Left 2.6; sleep 0.5; mark walk3; hold Up 3; mark stop3; sleep 3
mark end
