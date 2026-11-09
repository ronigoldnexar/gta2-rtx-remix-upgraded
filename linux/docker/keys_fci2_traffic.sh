#!/usr/bin/env bash
# FIX-CAR-IDENTITY-2: stand still at the spawn and cycle classic -> third -> first -> classic, shots in each,
# so passing traffic is caught in all three views within a few seconds (run with GTA2DX9_IDENTITY_PROBE=1:
# the log names each car's model and rectangle per view). ROUNDS (default 10).
export DISPLAY=:99
shot() { T0=$(date +%s.%N); ffmpeg -y -loglevel error -f x11grab -video_size ${SCREEN_W:-1280}x${SCREEN_H:-720} -i :99 -frames:v 1 /out/tr_$1.png
         echo "shot $1 t=$(date +%s.%N) t0=$T0" >> /out/tr_shots.txt; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
bash /work/to_level.sh
sleep 4
# WARP=1: the scene key (F10 in INI_SED) first, to scene_xy (a busier street than the spawn)
if [ "${WARP:-0}" = 1 ]; then tap F10; sleep 5; fi
for r in $(seq -w 1 ${ROUNDS:-10}); do
  shot ${r}_0c; sleep 0.4; shot ${r}_0c_b
  tap v; sleep 2.2; shot ${r}_1t; sleep 0.4; shot ${r}_1t_b
  tap v; sleep 2.2; shot ${r}_2f; sleep 0.4; shot ${r}_2f_b
  tap v; sleep 2.2
done
echo done
touch /out/.keys_done
