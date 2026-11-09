#!/usr/bin/env bash
# tools/vreg/build_stage.sh <rev>[+<commit>...] <stage dir>
# A private stage for a visual regression run of committed revision <rev> (with "+<commit>" each
# further commit is cherry-picked on top, conflicts resolved to <rev>'s side with -X ours: for
# testing a commit of one branch on the buildable tip of another; only text such as the ini
# conflicts in practice, and the stage takes its ini from repo/stage anyway):
#   - a detached worktree of <rev> under /tmp (never the shared working tree, which holds
#     other agents' partial edits), built under the build lock;
#   - if <rev> predates the fixed regression camera (dll/src/regress_cam.cpp), it is copied
#     in from this tools/vreg/ checkout and hooked into WorldView::ApplyTransition
#     (inject_hook.py), so older commits can be captured from the same poses;
#   - the stage dir: hard links of the shared repo/stage (models, HD tiles, ini) with the
#     DLLs replaced by rename (new inodes: nothing is written through to repo/stage).
#     VREG_ART=assets takes the models and HD tiles from repo/assets instead, as restage.sh's
#     candidate does: a preview of what the next restage would put on the play page.
# Prints the stage dir on success. A built rev is cached: an existing <stage>/.vreg_rev equal to
# the full hash is reused.
set -e
REV=$1; ST=$2
HERE=$(cd "$(dirname "$0")" && pwd); R=$(cd "$HERE/../.." && pwd)
ROOT=${GTA2_ROOT:-$(cd "$R/.." && pwd)}   # the workspace; its repo/stage holds the shared art
BASE=${REV%%+*}; PICKS=$( [ "$BASE" = "$REV" ] || echo "${REV#*+}" | tr '+' ' ')
FULL=$(git -C "$R" rev-parse "$BASE^{commit}")
for c in $PICKS; do FULL="$FULL+$(git -C "$R" rev-parse --short=10 "$c^{commit}")"; done
if [ -f "$ST/.vreg_rev" ] && [ "$(cat "$ST/.vreg_rev")" = "$FULL" ] && [ -f "$ST/gta2dx9.dll" ]; then echo "$ST"; exit 0; fi
W=/tmp/vreg-wt-$(echo "$FULL" | sha1sum | cut -c1-12)
if [ ! -d "$W" ]; then
  git -C "$R" worktree add -f --detach "$W" "${FULL%%+*}" >/dev/null 2>&1
  for c in $PICKS; do git -C "$W" -c user.name=vreg -c user.email=vreg@localhost cherry-pick -X ours "$c" >/dev/null 2>&1 \
    || { git -C "$W" cherry-pick --abort; echo "cherry-pick of $c onto $BASE failed" >&2; exit 1; }; done
fi
python3 "$HERE/inject_hook.py" "$W" "$R" >&2
( cd "$W" && flock /tmp/gta2-build.lock nice -n 10 make -j8 dll/build/gta2dx9.dll vid/build/gta2dx9_vid.dll ) > "$W.build.log" 2>&1 \
  || { tail -30 "$W.build.log" >&2; echo "build of $REV failed (log $W.build.log)" >&2; exit 1; }
python3 - "$ROOT/repo/stage" "$ST" "$W" "$FULL" "${VREG_ART:-stage}" "$ROOT/repo/assets" <<'PY'
import os, shutil, sys
src, st, w, full, art, assets = sys.argv[1:]
if not os.path.isdir(st):
    tmp = st + ".tmp"
    if os.path.isdir(tmp): shutil.rmtree(tmp)
    if art == "assets":
        # as restage.sh builds its candidate: the ini etc. from repo/stage, the models and HD tiles
        # from the workspace's assets/ (the art the next restage would ship). Hard links only.
        shutil.copytree(src, tmp, copy_function=os.link, symlinks=True,
                        ignore=lambda d, n: ["gta2dx9_models", "gta2dx9_textures_hd"] if os.path.abspath(d) == os.path.abspath(src) else [])
        shutil.copytree(os.path.join(assets, "models"), os.path.join(tmp, "gta2dx9_models"), copy_function=os.link, symlinks=True)
        shutil.copytree(os.path.join(assets, "textures_hd"), os.path.join(tmp, "gta2dx9_textures_hd"), copy_function=os.link, symlinks=True)
    else:
        shutil.copytree(src, tmp, copy_function=os.link, symlinks=True)
    os.rename(tmp, st)
def put(built, name):
    t = os.path.join(st, "." + name + ".new")
    shutil.copyfile(built, t); os.replace(t, os.path.join(st, name))   # rename: the shared inode is untouched
for n in ("gta2dx9.dll", "d3ddll.dll"): put(os.path.join(w, "dll/build/gta2dx9.dll"), n)
for n in ("gta2dx9_vid.dll", "Dmavideo.dll", "DMAGlide.dll"): put(os.path.join(w, "vid/build/gta2dx9_vid.dll"), n)
# the revision's own tracked models (code objects, manifest): a commit that changes a model is tested
# with it. Copied to a new inode and renamed in, so the shared stage's hard-linked files are untouched.
# The untracked art (cars, avatars) stays the shared stage's.
import subprocess
tracked = subprocess.run(["git", "-C", w, "ls-files", "assets/models"], capture_output=True, text=True).stdout.split()
md = os.path.join(st, "gta2dx9_models"); n = 0
for rel in tracked:
    s = os.path.join(w, rel); d = os.path.join(md, rel[len("assets/models/"):])
    if not os.path.isfile(s): continue
    if os.path.isfile(d) and open(s, "rb").read() == open(d, "rb").read(): continue
    os.makedirs(os.path.dirname(d), exist_ok=True)
    shutil.copyfile(s, d + ".vreg_new"); os.replace(d + ".vreg_new", d); n += 1
print(f"build_stage: {n} tracked model file(s) from the revision differ from repo/stage's and were put in", file=sys.stderr)
open(os.path.join(st, ".vreg_rev.new"), "w").write(full); os.replace(os.path.join(st, ".vreg_rev.new"), os.path.join(st, ".vreg_rev"))
PY
echo "$ST"
