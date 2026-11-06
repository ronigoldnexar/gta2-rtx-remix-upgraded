#!/usr/bin/env python3
"""Share of near-black frames per marked segment of a run: blackframes.py <out dir> [secs]"""
import sys, os, subprocess, numpy as np
d = sys.argv[1]; secs = int(sys.argv[2]) if len(sys.argv) > 2 else None
mp4 = os.path.join(d, "game.mp4")
dur = float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",mp4],capture_output=True,text=True).stdout.strip())
end = os.stat(mp4).st_mtime; start = end - (secs or dur)
marks = [l.split() for l in open(os.path.join(d,"marks.txt"))]
marks = [(float(t)-start, w) for t, w in marks]
# sample 2 fps, downscale, mean luma of the game area (left 1024 px of 1280 if windowed)
p = subprocess.run(["ffmpeg","-v","error","-i",mp4,"-vf","fps=2,scale=64:36","-f","rawvideo","-pix_fmt","gray","-"],capture_output=True)
fr = np.frombuffer(p.stdout, np.uint8).reshape(-1,36,64)
lum = fr[:, 2:34, 1:52].mean(axis=(1,2))   # inside the 1024-wide game window, below the HUD bar
dark = lum < 12
segs = []
for i,(t,w) in enumerate(marks):
    t2 = marks[i+1][0] if i+1 < len(marks) else dur
    a, b = int(t*2), int(t2*2)
    n = max(b-a,1); k = int(dark[a:b].sum())
    segs.append((w, round(t,1), round(t2,1), n, k))
    print(f"{w:14s} {t:7.1f}-{t2:7.1f}s  frames {n:4d}  black {k:4d}  ({100*k/n:4.0f}%)")
# runs of black
runs=[]; cur=None
for i,v in enumerate(dark):
    if v and cur is None: cur=i
    if not v and cur is not None: runs.append((cur/2,(i-cur)/2)); cur=None
long=[r for r in runs if r[1]>=1.0]
print("black runs >=1s:", [(round(a,1), round(l,1)) for a,l in long][:40])
