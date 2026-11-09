#!/usr/bin/env bash
# QB-13 positional audio: record the PulseAudio null sink while the player turns in the
# classic view and then in third person, phase marks in /out/phases.txt (UTC wall clock,
# same clock as gta2dx9.log). Analysis: linux/docker/audio3d_probe.py.
export DISPLAY=:99
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
hold() { xdotool keydown "$1"; sleep "$2"; xdotool keyup "$1"; }
mark() { echo "$(date -u +%H:%M:%S.%N) $1" >> /out/phases.txt; }
bash /work/to_level.sh
parec -d null.monitor --format=s16le --rate=22050 --channels=2 --file-format=wav /out/audio.wav &
REC=$!; mark rec_start; sleep 1
mark classic
for i in 1 2 3; do hold Up 2; hold Left 0.8; hold Up 2; hold Right 1.2; done
tap v; sleep 2; mark third
for i in 1 2 3 4 5 6; do hold Up 2.5; hold Left 0.9; hold Up 2; hold Right 0.6; done
mark end; sleep 1; kill $REC; sleep 1
ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/view_end.png
