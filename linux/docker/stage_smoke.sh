#!/usr/bin/env bash
# Smoke run of a stage: a scripted 3D run on the GPU image; refuses the stage if the renderer logs missing
# models/textures, if the run faults, or if the late frames are greyscale / have no figure drawn.
# Usage: stage_smoke.sh <stage_dir> [seconds=150]      exit 0 = pass, 1 = refuse (reasons on stdout)
cd "$(dirname "$0")/.."
ST=$(readlink -f "$1"); S=${2:-150}; N=smoke_$(date +%H%M%S)
python3 gamerun/stage_check.py "$ST" "$PWD/repo" || exit 1
STAGE="$ST" GTA2_INTRO=0 QA_PRIO=1 QA_FPS=10 gamerun/qa_run.sh "$N" "$S" fight > "out/qa_$N.smoke.log" 2>&1
LOG="out/qa_$N/gta2dx9.log"; bad=()
[ -f "$LOG" ] || bad+=("no renderer log: the run never started")
if [ -f "$LOG" ]; then
  e=$(grep -c -E 'models: .*could not be read|cars.by_model .*not loaded|models: no .*manifest' "$LOG"); [ "$e" -gt 0 ] && bad+=("$e model/texture read errors in the renderer log")
  f=$(grep -c FAULT "$LOG"); [ "$f" -gt 0 ] && bad+=("$f FAULT lines")
  grep -q 'models: .* nodes' "$LOG" || bad+=("no model loaded at all")
fi
if [ -f "out/qa_$N/game.mp4" ]; then
  python3 - "out/qa_$N/game.mp4" "$S" <<'PY' || bad+=("frame check failed (greyscale or empty late frames)")
import sys, subprocess, numpy as np
from PIL import Image
mp4, S = sys.argv[1], int(sys.argv[2]); ok = 0; checked = 0
for t in range(max(60, S - 70), S - 5, 10):
    p = f"/tmp/smoke_{t}.png"
    if subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", mp4, "-frames:v", "1", p]).returncode: continue
    a = np.asarray(Image.open(p).convert("RGB")).astype(float); checked += 1
    sat = (a.max(2) - a.min(2)).mean()               # mean chroma: greyscale world ~2-7, normal 25+
    if sat > 15: ok += 1
print(f"frames checked {checked}, in colour {ok}")
sys.exit(0 if checked and ok >= max(1, checked // 2) else 1)
PY
else
  bad+=("no recording from the run")
fi
if [ ${#bad[@]} -gt 0 ]; then echo "STAGE SMOKE FAILED for $ST:"; printf ' - %s\n' "${bad[@]}"; exit 1; fi
echo "stage smoke ok: $ST (run out/qa_$N)"
