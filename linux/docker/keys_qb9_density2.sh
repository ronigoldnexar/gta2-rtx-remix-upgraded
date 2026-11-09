#!/usr/bin/env bash
# QB-9 density pair (INI_SED: scene_key=F10, warp_key=F9): Downtown start, third
# person standing 30 s (people), back to classic, then drive_road.py (F10 car on
# the carriageway; classic 8 s, third 24 s, first 24 s, classic 6 s, frames).
export DISPLAY=:99
shot() { ffmpeg -y -loglevel error -f x11grab -video_size ${SCREEN_W:-1280}x${SCREEN_H:-720} -i :99 -frames:v 1 /out/d_$1.png; }
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
bash /work/to_level.sh
tap v; echo "third person"; sleep 2
for i in 1 2 3; do sleep 10; shot 1_stand_$i; done
tap v; sleep 1; tap v; echo "classic"; sleep 2
python3 /work/drive_road.py
