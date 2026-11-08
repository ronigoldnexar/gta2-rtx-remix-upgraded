#!/usr/bin/env python3
"""Olive-drab copies of the Rocketbox military avatars' ACU (grey digital camo)
colour textures, so GTA2's army reads as green soldiers: every grey camo texel
(low saturation) is mapped by its brightness onto an olive ramp, skin, eyes and
coloured patches are kept. Writes <name>_color_od.tga next to <name>_color_acu.tga.
Usage: army_olive.py <assets-src/humans/rocketbox>   (Rocketbox is MIT)"""
import glob, os, sys
import numpy as np
from PIL import Image

root = sys.argv[1] if len(sys.argv) > 1 else "assets-src/humans/rocketbox"
for src in sorted(glob.glob(os.path.join(root, "Military_*", "*_color_acu.tga"))):
    im = Image.open(src)
    a = np.asarray(im.convert("RGBA")).astype(np.float32)
    rgb = a[..., :3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    # grey camo: saturation under 0.14 fully, fading out by 0.22 (skin is ~0.3+)
    w = np.clip((0.22 - sat) / 0.08, 0.0, 1.0)[..., None]
    olive = np.stack([lum * 0.74, lum * 0.80, lum * 0.52], -1) + np.array([2, 5, 0], np.float32)
    out = rgb * (1 - w) + olive * w
    a[..., :3] = np.clip(out, 0, 255)
    dst = src.replace("_color_acu.tga", "_color_od.tga")
    Image.fromarray(a.astype(np.uint8), "RGBA").convert(im.mode if im.mode in ("RGB", "RGBA") else "RGB").save(dst)
    print(dst)
