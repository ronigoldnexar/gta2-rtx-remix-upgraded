#!/usr/bin/env bash
# FIX-FP (pm7): seated by F10, first person, Return out of the car, then walk back / turn / walk on in first person, bursts.
export DISPLAY=:99; N=0
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
shot() { N=$((N+1)); ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/fp_$(printf %03d $N)_$1.png; }
bash /work/to_level.sh
LOG=/tmp/wp/drive_c/Games/GTA2/gta2dx9.log
incar() { grep "view: player" "$LOG" | tail -1 | grep -q "carmodel=[0-9]"; }
for i in 1 2 3 4 5 6; do incar && break; tap F10; sleep 2.5; incar && break; tap Return; sleep 3; done
echo "seated after $i"
tap v; sleep 1.5; tap v; for k in 1 2 3 4 5 6; do grep -E "\] view: [A-Z]" "$LOG" | tail -1 | grep -q First && break; sleep 0.5; done; sleep 1.5
shot seated
for round in 1 2; do
  tap Return; sleep 2.5; shot out
  for leg in Down Left Down Up; do xdotool keydown $leg; for i in 1 2 3 4 5 6; do shot walk_$leg; sleep 0.12; done; xdotool keyup $leg; done
  # back into the car (F10) for round 2
  tap F10; sleep 3
done
echo done
