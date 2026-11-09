#!/usr/bin/env bash
# IDENTITY-SYSTEM cross-mode parity capture (docs/identity-system.md section 2.5; analyse with
# tools/identity_parity.py). The player stands still; every V press is a 12 s camera move
# (bev_parity.settings), so the frame 1 s after V is the 3D view at the classic camera (the
# same moment, the same footprint as the classic frame); then third person and first person
# once the camera settles. Then the same in the car the warp key puts him in.
# Run with GTA2DX9_IDENTITY_PROBE=1 and SETTINGS_EXTRA=/work/bev_parity.settings.
export DISPLAY=:99
shot() { ffmpeg -y -loglevel error -f x11grab -video_size ${SCREEN_W:-1280}x${SCREEN_H:-720} -i :99 -frames:v 1 /out/idp_$1.png
         echo "idp shot $1 t=$(date +%s.%N)" | tee -a /out/idp_shots.txt; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
cycle() {   # $1: prefix. classic -> (3D at the classic camera) -> third -> first -> classic
  shot "$1_0classic"; sleep 1; shot "$1_0classic_b"
  tap v; sleep 0.9; shot "$1_1at_classic_cam"
  sleep 13; shot "$1_2third"
  tap v; sleep 13; shot "$1_3first"
  tap v; sleep 13; shot "$1_4classic"
}
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
bash /work/to_level.sh
# Out of the spawn corner (the chase camera lands behind the sign there): to the driver's door of
# the nearest parked car on the street (warp_key=F9); the classic camera takes a few seconds to
# arrive. On foot there, then in that car.
# A step away from the door first: at the driver's door itself his figure is not drawn in the
# street views (filed separately: the parity check needs him in the picture).
tap F9; sleep 3; hold Up 1.2; sleep 7
cycle foot
tap Return; sleep 8
cycle car
echo "idp done t=$(date +%s.%N)" | tee -a /out/idp_shots.txt
touch /out/.keys_done
