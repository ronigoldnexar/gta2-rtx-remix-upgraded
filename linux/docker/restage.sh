#!/usr/bin/env bash
# Rebuild the shared stage safely. Nothing reaches repo/stage (and so the play page) unless a complete
# candidate stage passes stage_check.py (inventory against the manifest) and stage_smoke.sh (a scripted
# 3D run: no model/texture read errors, no faults, late frames in colour).
#   DLLs      : built in a detached worktree of committed HEAD (never the working tree with others' partial edits)
#   ini       : package/gta2dx9.ini from that worktree, with the running stage's overrides re-applied (merge_stage_ini.py)
#   models    : this repo's assets/models (the avatar/car art is not in git; it ships as archives)
#   HD tiles  : this repo's assets/textures_hd
# Usage: restage.sh [--no-smoke]      (--no-smoke skips the game run; the inventory check always runs)
set -e
cd "$(dirname "$0")/../.."
R=$PWD; W=/tmp/gta2-restage-worktree; W_LOG=/tmp/gta2-restage-build.log; C=$R/stage_candidate
# The candidate is cut from THIS checkout's HEAD. If the shared checkout lags the pushed branch, the stage silently
# misses the newest fixes (9 Nov 18:30: a restage meant to ship e93b53c was cut from a HEAD two commits behind it).
# Refuse in that case; run /mnt/gta2/autounify.sh (fast-forwards the shared checkout) and restage again.
if git fetch -q fork 2>/dev/null && git rev-parse -q --verify fork/camera-modes >/dev/null 2>&1; then
  BEHIND=$(git rev-list --count HEAD..fork/camera-modes)
  if [ "$BEHIND" -gt 0 ] && [ -z "$RESTAGE_ALLOW_BEHIND" ]; then
    echo "restage refused: HEAD $(git rev-parse --short HEAD) is $BEHIND commit(s) behind fork/camera-modes ($(git rev-parse --short fork/camera-modes)); run /mnt/gta2/autounify.sh first (or RESTAGE_ALLOW_BEHIND=1 to stage this HEAD on purpose)"
    exit 1
  fi
fi
git worktree remove --force "$W" 2>/dev/null || true
git worktree add -f --detach "$W" HEAD >/dev/null
STAGED_FROM=$(git -C "$W" rev-parse --short HEAD)   # the commit the DLLs come from; the shared checkout may move on (autounify) while the candidate builds
( cd "$W" && flock /tmp/gta2-build.lock nice -n 10 make -j4 dll/build/gta2dx9.dll vid/build/gta2dx9_vid.dll > "$W_LOG" 2>&1 ) || { tail -20 "$W_LOG"; exit 1; }
# repository checks (ini sections, check tools link; load/SEH checks run under Wine, SKIP without it) on the candidate worktree
( cd "$W" && flock /tmp/gta2-build.lock nice -n 10 make -j4 check >> "$W_LOG" 2>&1 ) || { tail -20 "$W_LOG"; echo "restage refused: make check failed on the candidate"; exit 1; }
rm -rf /home/roni_goldshmidt/gta2-linux/repo/stage_candidate; mkdir -p "$C"
cp "$W/dll/build/gta2dx9.dll" "$C/gta2dx9.dll"; cp "$W/dll/build/gta2dx9.dll" "$C/d3ddll.dll"
cp "$W/vid/build/gta2dx9_vid.dll" "$C/gta2dx9_vid.dll"; cp "$W/vid/build/gta2dx9_vid.dll" "$C/Dmavideo.dll"; cp "$W/vid/build/gta2dx9_vid.dll" "$C/DMAGlide.dll"
# ini: the committed package ini (every documented key, one section each) with the stage's deliberate overrides kept
# (tools/merge_stage_ini.py; 9 Nov: the stage ini had gone stale, two [renderer] blocks and 71 keys missing)
# A stage value equal to the package default of the commit the stage was built from (the 'staged from' line of the live
# restage log) is a moved default, not an override: pass that commit's package ini so the merge retires it (shift 79, 10 Nov:
# remix_puff_mode=2, traffic_cap=36 and follow_clock=0 had kept three owner fixes off the play page).
# COORDINATOR shift 103, 11 Nov: the chained restage jobs re-point restage-current.log at their own (still empty) log
# BEFORE running this script, so the live log carried no 'staged from' line and the merge kept a moved default again
# (grid_headroom=1 at 05:56 after FIX-PERF-8 moved it to 2): read the running stage's commit from stage/.stage_commit first.
PREV_STG=$(cat stage/.stage_commit 2>/dev/null | tr -d '[:space:]')
[ -n "$PREV_STG" ] || PREV_STG=$(grep -m1 -oE "staged from [0-9a-f]+" /mnt/gta2/restage-current.log 2>/dev/null | awk '{print $3}')
PREV_INI=""
if [ -n "$PREV_STG" ] && git -C "$W" show "$PREV_STG:package/gta2dx9.ini" > "$C/.prev_package.ini" 2>/dev/null; then PREV_INI="$C/.prev_package.ini"; else rm -f "$C/.prev_package.ini"; fi
python3 "$W/tools/merge_stage_ini.py" "$W/package/gta2dx9.ini" "stage/gta2dx9.ini" "$C/gta2dx9.ini" $PREV_INI
rm -f "$C/.prev_package.ini"
for f in install.reg uninstall.reg; do [ -f "stage/$f" ] && cp "stage/$f" "$C/$f" || cp "$W/package/$f" "$C/$f" 2>/dev/null || true; done
# LIGHTING-V1 (14 Nov): the effects ini ships beside gta2dx9.ini (package/gta2dx9_effects.ini: the v1.1 values every install
# carries, with SirensVersion=2 and the reconciled siren tuning); without it the play page ran the old v1.1 siren tuning.
cp "$W/package/gta2dx9_effects.ini" "$C/gta2dx9_effects.ini" 2>/dev/null || true
cp -al assets/models "$C/gta2dx9_models" 2>/dev/null || cp -a assets/models "$C/gta2dx9_models"
[ -d assets/textures_hd ] && { cp -al assets/textures_hd "$C/gta2dx9_textures_hd" 2>/dev/null || cp -a assets/textures_hd "$C/gta2dx9_textures_hd"; }
git worktree remove --force "$W" 2>/dev/null || true
python3 ../gamerun/stage_check.py "$C" "$R" || { echo "restage refused: candidate failed the inventory check"; exit 1; }
if [ "${1:-}" != "--no-smoke" ]; then
  ../gamerun/stage_smoke.sh "$C" "${SMOKE_SECONDS:-150}" || { echo "restage refused: candidate failed the smoke run"; exit 1; }
fi
# swap in: DLLs by atomic rename, folders by directory rename (running games keep their mapped/open files)
for f in gta2dx9.dll d3ddll.dll gta2dx9_vid.dll Dmavideo.dll DMAGlide.dll gta2dx9.ini gta2dx9_effects.ini install.reg uninstall.reg; do
  [ -f "$C/$f" ] && { cp "$C/$f" "stage/.$f.new" && mv -f "stage/.$f.new" "stage/$f"; }
done
for d in gta2dx9_models gta2dx9_textures_hd; do
  [ -d "$C/$d" ] || continue
  rm -rf "/home/roni_goldshmidt/gta2-linux/repo/stage/.$d.old"
  [ -d "stage/$d" ] && mv "stage/$d" "stage/.$d.old"; mv "$C/$d" "stage/$d"; rm -rf "/home/roni_goldshmidt/gta2-linux/repo/stage/.$d.old"
done
rm -rf /home/roni_goldshmidt/gta2-linux/repo/stage_candidate
python3 ../gamerun/stage_check.py stage "$R"
echo "$STAGED_FROM" > stage/.stage_commit   # a run can prove its stage without the log
echo "staged from $STAGED_FROM at $(date +%H:%M)"
