#!/usr/bin/env bash
# Remix diagnosis 3: what happens to the X windows while a key is held? xev on the
# present window and the game window, map state and stacking sampled, marks.
export DISPLAY=:99
game() { xwininfo -root -tree | grep '"GTA2"' | grep "648x514\|640x480" | head -1 | awk '{print $1}'; }
present() { xwininfo -root -tree | grep '"GTA2"' | grep "1024x768\|1280x720" | head -1 | awk '{print $1}'; }
mark() { echo "$(date +%s.%N) $1" >> /out/marks.txt; echo "$(date +%T) $1"; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
stamp() { while IFS= read -r l; do echo "$(date +%s.%N) $l"; done; }
for i in $(seq 1 120); do sleep 2; W=$(game); [ -n "$W" ] && break; done; echo "$(date +%T) game window $W after $((i*2)) s"; xdotool windowfocus --sync "$W" 2>/dev/null; xdotool windowactivate "$W" 2>/dev/null
sleep ${PREWARM_WAIT:-200}
mark frontend
for i in 1 2 3 4 5 6; do tap Return; sleep 7; done
mark level_classic; sleep ${LEVEL_WAIT:-40}
P=$(present); G=$(game); echo "present $P game $G"
xev -id "$P" 2>&1 | stamp > /out/xev_present.log &
xev -id "$G" 2>&1 | stamp > /out/xev_game.log &
xprop -spy -id "$P" 2>&1 | stamp > /out/xprop_present.log &
( while true; do echo "$(date +%s.%N) focus=$(xdotool getwindowfocus 2>/dev/null) stack=$(xwininfo -root -tree | grep '"GTA2"' | awk '{print $1}' | tr '\n' ' ') pmap=$(xwininfo -id $P | grep 'Map State' | awk '{print $3}') gmap=$(xwininfo -id $G | grep 'Map State' | awk '{print $3}') geo=$(xwininfo -id $P | grep -E 'Absolute upper-left X|Width|Height' | awk '{print $NF}' | tr '\n' ' ')"; sleep 0.5; done ) > /out/stack.log 2>&1 &
mark idle; sleep 10
mark held_scroll; hold Scroll_Lock 10
mark idle2; sleep 10
mark held_up; hold Up 10
mark idle3; sleep 10
mark taps_scroll; for i in 1 2 3 4 5; do tap Scroll_Lock; sleep 1.7; done
mark idle4; sleep 8
mark done
