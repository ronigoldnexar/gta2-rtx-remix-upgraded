#!/usr/bin/env python3
"""Gives a street-view road tile the photo asphalt of a sibling tile (qav6/qav8, FIX-WORLD-13).

The street views' road set (assets/textures_hd/roads/<style>/, docs/hd-textures.md "Street-view road
set") carries for four tiles the photo set does not have (wil 685, bil 765, ste 696 and 813) QB-24's
plain HD versions. Their asphalt is the upscaler's smooth olive fill (bil 765: high-pass sd 1.8
against ~6 on every neighbour), so in the third and first person a run of 765 cells read as a flat,
crack-free trapezoid with hard edges beside the cracked lanes (qav6 bil 180.5,60.5; qav8 bil
110.5,40.5, where 765's own lane lettering sits on its edge).

This takes the rows of a sibling road tile with the same layout (the kerb, the white edge line and
the cracked photo asphalt: bil 764) and keeps the target's own rows from --keep-from down (765's
yellow lettering strip), cross-faded over --blend rows inside the asphalt, then shifts the donor's
asphalt to the target's own mean colour so the runtime tone match sees the same tile. Written as a
DXT1 DDS with Lanczos mips, as tools/pack_textures_dds.py writes them. Street sets only: never the
HD set under assets/textures_hd/<style>/ (Remix keys its materials by those files' hashes).

    regrain_road_tile.py <donor.dds> <target.dds> <out.dds> --keep-from 446 --blend 16 [--sheet png]
"""
import argparse, io, os, struct, sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pack_textures_dds import dds_header, encode_level  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("donor"); ap.add_argument("target"); ap.add_argument("out")
    ap.add_argument("--keep-from", type=int, required=True, help="first row (at 512 px) kept from the target")
    ap.add_argument("--blend", type=int, default=16)
    ap.add_argument("--asphalt-rows", default="140:420", help="rows whose mean colour is the asphalt's")
    ap.add_argument("--sheet")
    a = ap.parse_args()
    donor = np.asarray(Image.open(a.donor).convert("RGB")).astype(np.float32)
    target = np.asarray(Image.open(a.target).convert("RGB")).astype(np.float32)
    assert donor.shape == target.shape, (donor.shape, target.shape)
    h = target.shape[0]
    r0, r1 = (int(v) for v in a.asphalt_rows.split(":"))
    shift = target[r0:r1].reshape(-1, 3).mean(0) - donor[r0:r1].reshape(-1, 3).mean(0)
    graded = donor.copy()
    graded[:a.keep_from] += shift   # only the asphalt and kerb rows that are used
    w = np.clip((np.arange(h, dtype=np.float32) - (a.keep_from - a.blend)) / max(1, a.blend), 0.0, 1.0)[:, None, None]
    out = np.clip(graded * (1.0 - w) + target * w, 0, 255).astype(np.uint8)
    im = Image.fromarray(out)
    levels, size = [], im.size[0]
    cur = im
    while True:
        levels.append(encode_level(cur, "DXT1"))
        if size == 1: break
        size //= 2
        cur = im.resize((size, size), Image.LANCZOS)
    with open(a.out + ".tmp", "wb") as f:
        f.write(dds_header(im.size[0], im.size[1], len(levels), b"DXT1", len(levels[0])))
        for lv in levels: f.write(lv)
    os.replace(a.out + ".tmp", a.out)   # a new inode: never write through a hard link into a stage
    print(f"{a.out}: donor {a.donor} rows 0..{a.keep_from - a.blend}, target from {a.keep_from}, "
          f"asphalt shift {shift.round(1).tolist()}, {len(levels)} mips")
    if a.sheet:
        s = Image.new("RGB", (h * 3, h))
        for i, arr in enumerate((target, donor, out)): s.paste(Image.fromarray(np.asarray(arr).astype(np.uint8)), (i * h, 0))
        s.save(a.sheet)


if __name__ == "__main__":
    main()
