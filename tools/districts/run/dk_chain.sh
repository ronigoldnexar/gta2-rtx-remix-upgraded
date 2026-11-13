#!/bin/bash
# dk_chain.sh <tag> [levels]: one capture at a time (AGENTS.md: one run per agent), each waits for the last
G=/mnt/gta2/gta2-linux; W=$G/districts_work; TAG=$1; LV=${2:-wil ste bil}
while pgrep -f "runq.sh run -p 5 -n dk_" > /dev/null; do sleep 10; done   # any capture of mine still running
for l in $LV; do
  bash $W/dk_run.sh dk_${l}${TAG} $l ${SECS:-330} > /dev/null
  sleep 5
  while pgrep -f "runq.sh run -p 5 -n dk_${l}${TAG} " > /dev/null; do sleep 10; done
  echo "$(date +%T) dk_${l}${TAG} done: $(ls $G/out/dk_${l}${TAG} | grep -c dk_) frames, FAULT $(grep -c FAULT $G/out/dk_${l}${TAG}/gta2dx9.log 2>/dev/null)"
done
