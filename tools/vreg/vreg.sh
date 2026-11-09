#!/usr/bin/env bash
# Visual regression harness (QA-REGRESSION): fixed camera shots, captured every run, diffed
# against golden frames with a tolerance learned from repeat runs. docs/visual-regression.md.
#
#   tools/vreg/vreg.sh stage <stage dir> [name]   capture from your own private stage (your build, before you
#                                                 commit; it must be a stage made with the regression camera:
#                                                 any build of this tree from the commit that added
#                                                 dll/src/regress_cam.cpp on) and diff against the goldens
#   tools/vreg/vreg.sh check <rev>[+<commit>...]  build that committed revision into a private stage
#                                                 (build_stage.sh), capture, diff
#   tools/vreg/vreg.sh diff <run dir>             diff an existing capture again
#   tools/vreg/vreg.sh seed <rev> [n]             n captures (default 3) of <rev>, made the golden set
#                                                 goldens/<rev>, and goldens/current pointed at it
#
# Env: GTA2_GPU (the GPU your runs use), VREG_GOLDEN (golden set dir; default $VREG_HOME/goldens/current),
# VREG_HOME (default <workspace>/vreg: stages, goldens, the numpy venv; nothing of it goes into git: the
# frames are the game's art). Exit status: 0 all PASS/WARN/SKIP, 1 a FAIL, 2 the capture or build failed.
# One capture is ~4-6 minutes of a game slot (queued through gamerun/runq.sh).
set -e
HERE=$(cd "$(dirname "$0")" && pwd); R=$(cd "$HERE/../.." && pwd); ROOT=${GTA2_ROOT:-$(cd "$R/.." && pwd)}   # the workspace (game/, gamerun/, out/); GTA2_ROOT when run from a /tmp worktree
VH=${VREG_HOME:-$ROOT/vreg}; mkdir -p "$VH/goldens" "$VH/stages"
PY=$VH/venv/bin/python
if [ ! -x "$PY" ]; then python3 -m venv "$VH/venv" && "$VH/venv/bin/pip" -q install numpy pillow; fi
G=${VREG_GOLDEN:-$VH/goldens/current}
stamp() { date -u +%m%d_%H%M%S; }

capture() {   # capture <run name> <stage dir>: run the capture, check it completed
  "$HERE/run_capture.sh" "$1" "$2" "${VREG_SECONDS:-2400}" || true
  if [ ! -f "$ROOT/out/$1/.vreg_done" ]; then
    echo "vreg: capture $1 did not complete (see out/$1/keys.log, out/$1.run.log)"; return 2; fi
}

diffrun() {   # diffrun <run dir> <label>
  [ -f "$G/manifest.json" ] || { echo "vreg: no golden set at $G (seed one: vreg.sh seed <rev>)"; return 2; }
  "$PY" "$HERE/vreg_diff.py" check "$G" "$1" --label "$2"
}

case "${1:-}" in
stage)
  ST=$(cd "$2" && pwd); N=${3:-vreg_$(basename "$ST")_$(stamp)}
  capture "$N" "$ST" || exit 2
  diffrun "$ROOT/out/$N" "stage $(basename "$ST")";;
check)
  SPEC=$2; TAG=$(echo "$SPEC" | tr '+/' '__')
  ST=$("$HERE/build_stage.sh" "$SPEC" "$VH/stages/$TAG") || exit 2
  N=vreg_${TAG}_$(stamp)
  capture "$N" "$ST" || exit 2
  diffrun "$ROOT/out/$N" "rev $SPEC";;
diff)
  diffrun "$(cd "$2" && pwd)" "${3:-rerun}";;
seed)
  SPEC=$2; K=${3:-3}; TAG=$(echo "$SPEC" | tr '+/' '__')
  ST=$("$HERE/build_stage.sh" "$SPEC" "$VH/stages/$TAG") || exit 2
  RUNS=()
  for i in $(seq 1 "$K"); do N=vreg_seed_${TAG}_$i; capture "$N" "$ST" || exit 2; RUNS+=("$ROOT/out/$N"); done
  "$PY" "$HERE/vreg_diff.py" seed "$VH/goldens/$TAG" "${RUNS[@]}" --rev "$(cat "$ST/.vreg_rev")"
  ln -sfn "$TAG" "$VH/goldens/current"; echo "goldens/current -> $TAG";;
*) sed -n 2,22p "$0"; exit 2;;
esac
