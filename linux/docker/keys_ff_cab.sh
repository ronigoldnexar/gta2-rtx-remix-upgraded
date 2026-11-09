#!/usr/bin/env bash
# FIX-FIGURE copy of keys_pm3.sh: no Return after F10 (the scene key seats him in a car already).
# PLAYTEST-MODES pass 3: get a car (F10), drive it through all three views, switching while moving.
export DISPLAY=:99; N=0
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
shot() { N=$((N+1)); ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/pm_$(printf %03d $N)_$1.png; }
burst() { for i in $(seq 1 $2); do shot $1; sleep 0.25; done; }
drive() { xdotool keydown Up; for i in $(seq 1 $2); do sleep 0.5; if [ $((i%3)) = 0 ]; then xdotool keydown Left; sleep 0.15; xdotool keyup Left; fi; sleep 0.5; shot $1; done; xdotool keyup Up; }
bash /work/to_level.sh
shot onfoot
tap F10; sleep 2; shot after_f10; sleep 2; shot entered   # F10 seats him in a car (its name banner); Return would get him out
xdotool keydown Right; sleep 0.6; xdotool keyup Right; drive classic_drive 3
xdotool keydown Left; sleep 0.5; xdotool keyup Left
tap v; burst to_third 6
drive third_drive 6
xdotool keydown Right; xdotool keydown Up; sleep 1.5; xdotool keyup Right; shot third_turn_r; sleep 1; xdotool keyup Up
xdotool keydown Down; sleep 1.5; shot third_brake; xdotool keyup Down; sleep 0.5; shot third_stopped
drive third_drive2 3
tap v; burst to_first 6
drive first_drive 6
xdotool keydown Left; xdotool keydown Up; sleep 1.5; xdotool keyup Left; shot first_turn_l; sleep 1; xdotool keyup Up
xdotool keydown Down; sleep 1.5; shot first_brake; xdotool keyup Down
tap v; burst first_to_classic 4
drive classic_drive2 3
tap v; sleep 0.5; xdotool keydown Up; for i in 1 2 3 4; do shot movingswitch; sleep 0.4; done; tap v; for i in 1 2 3 4; do shot movingswitch2; sleep 0.4; done; xdotool keyup Up
tap Return; sleep 2; burst exit_car 6
echo done
