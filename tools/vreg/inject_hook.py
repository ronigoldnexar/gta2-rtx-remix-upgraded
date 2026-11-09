#!/usr/bin/env python3
"""inject_hook.py <worktree> <repo>: make a checkout of any revision draw the visual regression
harness's fixed camera and hold its sky clock. Revisions with dll/src/regress_cam.cpp in git are
left alone. Otherwise regress_cam.{h,cpp} are copied from <repo> (refreshed on every call) and
the two calls are added to world_view.cpp if missing: the camera override at the end of
WorldView::ApplyTransition, and RegressClock() on the sky/water clock. The Makefile builds every
dll/src/*.cpp, so nothing else is needed."""
import os, shutil, subprocess, sys
w, r = sys.argv[1:3]
src = os.path.join(w, "dll/src")
if subprocess.run(["git", "-C", w, "ls-files", "--error-unmatch", "dll/src/regress_cam.cpp"], capture_output=True).returncode == 0:
    print("inject_hook: revision has the regression hooks"); sys.exit(0)
for n in ("regress_cam.h", "regress_cam.cpp"):
    shutil.copyfile(os.path.join(r, "dll/src", n), os.path.join(src, n))
p = os.path.join(src, "world_view.cpp"); t = open(p).read(); done = []
if '#include "regress_cam.h"' not in t:
    t = t.replace('#include "world_view.h"\n', '#include "world_view.h"\n#include "regress_cam.h"\n', 1)
if "RegressCameraOverride" not in t:
    anchor = "    lastPose_ = shown;\n    lastPoseValid_ = true;\n}\n"
    if t.count(anchor) != 1: sys.exit("inject_hook: ApplyTransition's end not found; this revision cannot take the fixed camera")
    t = t.replace(anchor, anchor[:-2] + "    if (mode != ViewMode::Classic && transitionT_ >= 1.0f) RegressCameraOverride(&camera_);\n}\n")
    done.append("camera")
clock = "    const double seconds = static_cast<double>(counter.QuadPart) / static_cast<double>(frequency.QuadPart);\n    renderer_.SetWaterClock(seconds);\n"
if "RegressClock(" not in t:
    if t.count(clock) != 1: sys.exit("inject_hook: the sky clock line not found")
    t = t.replace(clock, clock.replace("const double seconds = static_cast", "const double seconds = RegressClock(static_cast").replace("QuadPart);\n    renderer_", "QuadPart));\n    renderer_", 1))
    done.append("clock")
open(p, "w").write(t)
print("inject_hook: regression hooks " + ("injected: " + ", ".join(done) if done else "refreshed"))
