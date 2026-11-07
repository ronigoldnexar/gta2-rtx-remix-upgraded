#!/usr/bin/env bash
# Inside a run: get into the level fast. Waits for the game window, focuses it,
# then taps Return every 1.5 s until the renderer reports the player in the
# level, instead of fixed sleeps. Prints the time taken. Source or call it from
# a keys script in place of the old "sleep 10; ...; sleep 15; 5 x Return".
export DISPLAY=:99; T0=$(date +%s.%N); LOG=/tmp/wp/drive_c/Games/GTA2/gta2dx9.log
game() { xwininfo -root -tree 2>/dev/null | grep '"GTA2"' | grep "648x514\|640x480" | head -1 | awk '{print $1}'; }
for i in $(seq 1 120); do W=$(game); [ -n "$W" ] && break; sleep 0.5; done
xdotool windowfocus --sync "$W" 2>/dev/null; xdotool windowactivate "$W" 2>/dev/null; sleep 1
for i in $(seq 1 60); do
  grep -q "view: classic (player found" "$LOG" 2>/dev/null && break
  xdotool keydown Return; sleep 0.25; xdotool keyup Return; sleep 1.25
done
sleep 2
python3 -c "import time; print(f'to_level: in the level after {time.time()-$T0:.1f} s (window $W)')"
