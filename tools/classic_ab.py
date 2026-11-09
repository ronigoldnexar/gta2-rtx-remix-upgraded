#!/usr/bin/env python3
# FIX-CLASSIC (pm18): the classic view A/B before and after a V cycle, ignoring whatever moved.
# Classic A/B with a static mask: a pixel counts if it is identical in every "pre" frame and in every "post" frame
# (nothing moved over it in either window); then report how many of those differ between pre and post.
# HUD rows/cols are included (they are static too). Usage: fxc_ab.py <outdir> <preglob> <postglob> [diffpng]
import sys, glob, numpy as np
from PIL import Image
d, pg, qg = sys.argv[1:4]
load = lambda f: np.asarray(Image.open(f).convert('RGB')).astype(np.int16)
pre = [load(f) for f in sorted(glob.glob(f"{d}/{pg}"))]; post = [load(f) for f in sorted(glob.glob(f"{d}/{qg}"))]
st = lambda fs: np.all([np.all(f == fs[0], axis=2) for f in fs], axis=0)
mask = st(pre) & st(post)
diff = np.any(pre[0] != post[0], axis=2) & mask
print(f"pre {len(pre)} post {len(post)} frames; static pixels {mask.mean()*100:.1f}% ({mask.sum()}); "
      f"static pixels that differ pre vs post: {diff.sum()} ({diff.sum()/max(mask.sum(),1)*100:.3f}%)")
if len(sys.argv) > 4:
    vis = (pre[0] // 3).astype(np.uint8); vis[~mask] = [0, 0, 80]; vis[diff] = [255, 0, 0]
    Image.fromarray(vis).save(sys.argv[4])
