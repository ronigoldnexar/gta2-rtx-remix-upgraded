#!/usr/bin/env bash
# FIX-FP: seat (F10 retry), a shot after each V (classic/third/first), first person still, steer, drive forward.
export DISPLAY=:99; N=0
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
shot() { N=$((N+1)); ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/fp_$(printf %03d $N)_$1.png; }
bash /work/to_level.sh
LOG=/tmp/wp/drive_c/Games/GTA2/gta2dx9.log
incar() { grep "view: player" "$LOG" | tail -1 | grep -q "carmodel=[0-9]"; }
for i in 1 2 3 4 5 6; do
  incar && break
  tap F10; sleep 2.5; incar && break
  tap Return; sleep 3
done
echo "seated after $i F10 taps"; sleep 1
tap v; sleep 3.5; shot third_ext; sleep 1; shot third_ext2
tap v; for k in 1 2 3 4 5 6; do grep -E "\] view: [A-Z]" "$LOG" | tail -1 | grep -q First && break; sleep 0.5; done; sleep 2
shot first_still; sleep 1; shot first_still2
xdotool keydown Left; sleep 0.6; shot first_left; xdotool keyup Left; sleep 0.3
xdotool keydown Up; for i in 1 2 3 4 5; do sleep 0.7; shot first_fwd; done; xdotool keyup Up
xdotool keydown Down; sleep 1.2; shot first_brake; xdotool keyup Down
echo done
