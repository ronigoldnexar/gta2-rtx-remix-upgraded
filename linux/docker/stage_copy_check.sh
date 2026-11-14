#!/usr/bin/env bash
# stage_copy_check.sh <game dir in the prefix>: inside a run container, right after the run script copied /stage's
# DLLs and ini over the prefix. The prefix first gets /release (the upstream v1.1 renderer: its DLLs and an ini with
# fov_tenths=150 and no devtools keys), so a stage copy that missed left the run on the v1.1 build without a word.
# 14 Nov: three lt_cl*_plain_move runs started while their private stage's DLLs were being rewritten (stage files
# 10:30:28, game up 10:30:38) and ran v1.1 (to_level 97 s, no ini edits, scene_key empty, daytime at spawn).
# Now every /stage DLL and the ini must match the prefix copy byte for byte; a miss is copied again (a stage is
# usually mid-rewrite for under a second), and after ~12 s the run is aborted (exit 3) instead of running the wrong build.
G=${1:?game dir}
bad=
for try in 1 2 3 4 5 6; do
  bad=
  [ -f /stage/gta2dx9.dll ] || bad="$bad gta2dx9.dll[missing-in-stage]"
  [ -f /stage/gta2dx9.ini ] || bad="$bad gta2dx9.ini[missing-in-stage]"
  for f in /stage/*.dll /stage/gta2dx9.ini; do
    [ -f "$f" ] || continue
    cmp -s "$f" "$G/$(basename "$f")" || bad="$bad $(basename "$f")"
  done
  [ -z "$bad" ] && break
  echo "== stage copy check (try $try):$bad not as in /stage; copying the stage again in 2 s"
  sleep 2
  cp /stage/*.dll /stage/gta2dx9.ini $(ls /stage/gta2dx9_effects.ini 2>/dev/null) "$G"/ 2>/dev/null
done
if [ -n "$bad" ]; then
  echo "run aborted: the stage's renderer did not reach the prefix ($bad); is the stage being rewritten? (stage_copy_check.sh)"
  exit 3
fi
commit=; [ -f /stage/.stage_commit ] && commit=" (stage commit $(cat /stage/.stage_commit))"
echo "== stage copy check: gta2dx9.dll $(md5sum < "$G/gta2dx9.dll" | cut -c1-12) as in /stage$commit"
