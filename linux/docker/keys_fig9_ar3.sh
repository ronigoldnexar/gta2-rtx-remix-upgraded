#!/usr/bin/env bash
# FIX-FIGURE-9 pm7: an arrest in third person (force_wanted=2 from the ini): F10 car, drive in third, get out near the
# police and stand; once the log says busted, film; then first person (the crowd at his shoulder, pm7-fp). game.mp4 is the record.
export DISPLAY=:99; G=/tmp/wp/drive_c/Games/GTA2; LOG=$G/gta2dx9.log
tap() { xdotool keydown "$1"; sleep 0.3; xdotool keyup "$1"; }
mark() { echo "$(date +%s.%N) $1" >> /out/marks.txt; echo "$(date +%T) MARK $1"; }
view() { grep -aoE "\] view: (Classic \(top down\)|Third person|First person)$" "$LOG" | tail -1; }
want() { for i in 1 2 3 4; do view | grep -q "$1" && return 0; tap v; sleep 4; done; }
bash /work/to_level.sh
tap F10; sleep 2; tap Return; sleep 3
want "Third person"; mark "view $(view)"
for r in 1 2 3; do xdotool keydown Up; sleep 3; xdotool keydown Left; sleep 0.4; xdotool keyup Left; sleep 2; xdotool keyup Up; sleep 1; done
tap Return; sleep 2; mark "out of the car"
B=$(grep -ac "wanted: busted" "$LOG")
for i in $(seq 1 120); do
  [ "$(grep -ac "wanted: busted" "$LOG")" -gt "$B" ] && { mark "busted $(view)"; break; }
  view | grep -q "Third person" || want "Third person"
  sleep 1
done
sleep 12; mark "after the arrest $(view)"
want "First person"; mark "view $(view)"
for i in 1 2 3; do xdotool keydown Up; sleep 1.5; xdotool keyup Up; sleep 1; xdotool keydown Down; sleep 1; xdotool keyup Down; sleep 1; done
sleep 4; mark "end"
echo done
