# Shared pieces of the Remix key scripts (sourced). The game log is read live.
export DISPLAY=:99
LOG=/tmp/wp/drive_c/Games/GTA2/gta2dx9.log
game() { xwininfo -root -tree | grep '"GTA2"' | grep "648x514\|640x480" | head -1 | awk '{print $1}'; }
mark() { echo "$(date +%s.%N) $1" >> /out/marks.txt; echo "$(date +%T) $1"; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
focus_game() { for i in $(seq 1 120); do sleep 2; W=$(game); [ -n "$W" ] && break; done; echo "$(date +%T) game window $W after $((i*2)) s"; xdotool windowfocus --sync "$W" 2>/dev/null; xdotool windowactivate "$W" 2>/dev/null; }
# Return until the player's level is up: the attract demo plays Residential (bil)
# on its own, the game proper loads Downtown (wil); after that load the renderer
# logs the player. At most ~4 minutes.
to_level() {
  for i in $(seq 1 60); do
    if grep -q "map wil.gmp is played" "$LOG" 2>/dev/null; then sleep 8; echo "$(date +%T) level up after $i returns"; return 0; fi
    tap Return; sleep 4
  done
  echo "$(date +%T) level NOT reached"; return 1
}
