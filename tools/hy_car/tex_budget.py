#!/usr/bin/env python3
"""CARS-V3 residency: bring a converted fleet's shell pictures back to the texture budget.

    tex_budget.py <converted models dir> <out dir> [--split 512] [--livery 1024]

The f5 fleet was converted with HY_TEX_SPLIT=1024 (three 1024 px RGBA pictures per remapped car: the shell, its
paint half and the shell rest), which put the 32-bit game past its 3900 MB address-space ceiling in a 12-minute
traffic drive (docs/car-3d-pipeline.md "CARS-V3 memory"). This copies the directory and resizes every picture of a
car above its budget (remapped cars --split, liveries --livery; LIVERY as in hy_convert.py) with Lanczos. UVs are
untouched; all pictures of one car shrink together so the paint/rest pairs keep matching sizes (model_store.cpp
skips a split pair whose sizes differ). Files that are hard links (cp -al) are replaced, never written through."""
import argparse, os, re, shutil, struct, sys
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
LIVERY = {4, 11, 12, 17, 22, 23, 24, 25, 26, 27, 34, 51, 52, 54, 56, 59, 60, 61, 67, 84, 85, 86}   # hy_convert.py


def dims(p):
    with open(p, 'rb') as f:
        h = f.read(18)
    return struct.unpack('<HH', h[12:16])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('out')
    ap.add_argument('--split', type=int, default=512); ap.add_argument('--livery', type=int, default=1024)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    shrunk = kept = 0; before = after = 0
    for f in sorted(os.listdir(a.src)):
        sp, op = os.path.join(a.src, f), os.path.join(a.out, f)
        if os.path.lexists(op):
            os.unlink(op)
        m = re.match(r'(\d\d\d)_', f)
        if not (m and f.endswith('.tga')):
            shutil.copyfile(sp, op); continue
        cap = a.livery if int(m.group(1)) in LIVERY else a.split
        w, h = dims(sp); before += w * h * 4
        if max(w, h) <= cap:
            shutil.copyfile(sp, op); kept += 1; after += w * h * 4; continue
        s = cap / max(w, h); nw, nh = max(1, round(w * s)), max(1, round(h * s))
        im = Image.open(sp)
        im.resize((nw, nh), Image.LANCZOS).save(op)
        shrunk += 1; after += nw * nh * 4
    print(f'tex_budget: {shrunk} pictures resized, {kept} kept; RGBA {before / 2**20:.0f} MB -> {after / 2**20:.0f} MB')


if __name__ == '__main__':
    main()
