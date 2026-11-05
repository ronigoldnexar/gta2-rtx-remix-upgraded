#!/usr/bin/env bash
# The recording: the game's own opening, the menu, area 1, a walk in the classic
# view, then V to third person and V to first person, walking on in each.
export DISPLAY=:99
game() { xwininfo -root -tree | grep '"GTA2"' | grep "648x514\|640x480" | head -1 | awk '{print $1}'; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
mark() { echo "$(date +%H:%M:%S) $*"; }
W=""; for i in $(seq 1 60); do sleep 1; W=$(game); [ -n "$W" ] && break; done
mark "game window $W"; xdotool windowfocus --sync "$W"
sleep 20                                  # the intro movie plays
for i in 1 2 3 4 5; do tap Return; sleep 6; done   # through the front end into area 1
mark "in the level, classic view"
hold Left 1.2; hold Up 4                  # turn and walk into the open
hold Right 0.5; hold Up 5
mark "V: third person"; tap v
hold Up 5; hold Left 0.5; hold Up 5; hold Right 0.7; hold Up 6
mark "V: first person"; tap v
hold Up 5; hold Left 0.5; hold Up 6; hold Right 0.6; hold Up 6; hold Left 0.4; hold Up 6
mark "V: classic"; tap v
hold Up 4
mark "done"
