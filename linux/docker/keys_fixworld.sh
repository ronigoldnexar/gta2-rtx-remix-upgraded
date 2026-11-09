#!/usr/bin/env bash
# FIX-WORLD before/after capture: no movement, so two builds see the same scene.
# Classic at the spawn, the views' own third- and first-person cameras at the spawn, then fixed
# poses from /out/poses.txt ("<name> cam ex ey ez tx ty tz [fov]", game coordinates) through the
# regression camera (GTA2DX9_REGRESS_CAM=Z:\tmp\fw_cam.txt), then classic again.
export DISPLAY=:99
CAM=/tmp/fw_cam.txt
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
shot() { ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/fw_$1.png; }
cam() { echo "$1" > $CAM.tmp; mv $CAM.tmp $CAM; }
cam off
bash /work/to_level.sh
sleep 3
shot c1_classic_a; sleep 1; shot c1_classic_b
tap v; sleep 3.5; shot t_spawn_third_a; sleep 1; shot t_spawn_third_b
tap v; sleep 3.5; shot f_spawn_first_a; sleep 1; shot f_spawn_first_b
# fixed poses, while in first person (the regression camera applies in either street view)
while read -r name rest; do
  [ -z "$name" ] && continue
  cam "$rest"; sleep 1.6; shot "p_$name"
done < /out/poses.txt
cam off; sleep 1
tap v; sleep 4; shot c2_classic_a; sleep 1; shot c2_classic_b
echo done
