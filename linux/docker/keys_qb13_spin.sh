#!/usr/bin/env bash
# QB-13 controlled check: stand still at the Downtown start (a looped ambient source sits a few
# blocks west), go to first person, turn in place in steps and hold each heading 2.5 s while the
# null sink is recorded. Marks in /out/phases.txt. Analysis: linux/docker/audio3d_probe.py --phase spin.
export DISPLAY=:99
tap() { xdotool keydown "$1"; sleep "${2:-0.3}"; xdotool keyup "$1"; }
mark() { echo "$(date -u +%H:%M:%S.%N) $1" >> /out/phases.txt; }
bash /work/to_level.sh
parec -d null.monitor --format=s16le --rate=22050 --channels=2 --file-format=wav /out/audio.wav &
REC=$!; mark rec_start; sleep 1
mark classic; sleep 6
tap v; sleep 1.5; tap v; sleep 3; mark spin
for i in $(seq 1 16); do tap Left 0.18; sleep 2.5; done
mark end; sleep 0.5; kill $REC; sleep 1
ffmpeg -y -loglevel error -f x11grab -video_size 1280x720 -i :99 -frames:v 1 /out/view_end.png
