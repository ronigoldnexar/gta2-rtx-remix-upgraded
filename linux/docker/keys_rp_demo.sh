#!/usr/bin/env bash
# REMIX-PIPELINE test keys script: a short, fixed-length "demo": level, walk, V to third and first person, walk, then ends.
# Prints its own start / end epoch so a recording's length can be compared with the played length.
export DISPLAY=:99
echo "keys start $(date +%s.%N)"
bash /work/to_level.sh
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
hold Up 4; tap v; sleep 4; hold Up 4; hold Left 1; tap v; sleep 4; hold Up 4; hold Right 1; hold Up 3; tap v; sleep 3
echo "keys end $(date +%s.%N)"
