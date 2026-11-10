#!/usr/bin/env python3
"""Lifts the darkest wall tiles of the street views' photo set to an albedo floor (qav7, FIX-WORLD-13).

qav7 measured the plain renderer's light on ste's shaded walls as right (shade/sun 63 % on one
texture) and the near-black slabs as the art: the dark green stone of ste 103/105/109 and the dark
planks of 168-170 average luma 45-56 in the original, HD and photo sets alike, so in the third and
first person a wall of them turned from the sun reads ~30 and its texture vanishes. Under RTX Remix
FIX-REMIX-MATERIALS-9 lifted the same class of dark ste wall art to an albedo floor in the layer
(remix_pbr.delit_albedo, 6e5d5963). This is the plain twin: each listed photo tile is scaled so its
mean luma reaches --floor (a plain multiply: the stone keeps its hue and its own contrast, the grain
and mortar just become visible), never above --max-gain. Alpha (DXT5 tiles) is kept as it is.

Street set only (assets/textures_hd/photo/<style>/): classic draws the HD set and a Remix device
never loads photo/, so neither changes. Writes a new file (os.replace), never through a hard link.

    photo_albedo_floor.py <photo style dir> <out dir> --tiles 103,105,109 --floor 70 [--max-gain 1.6] [--sheet png]
"""
import argparse, os, sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pack_textures_dds import dds_header, encode_level  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--tiles", required=True)
    ap.add_argument("--floor", type=float, default=70.0)
    ap.add_argument("--max-gain", type=float, default=1.6)
    ap.add_argument("--sheet")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    sheet = []
    for t in [int(v) for v in a.tiles.split(",")]:
        name = f"tile_{t:04d}.dds"
        raw = open(os.path.join(a.src, name), "rb").read()
        fourcc = raw[84:88]
        im = Image.open(os.path.join(a.src, name)).convert("RGBA")
        arr = np.asarray(im).astype(np.float32)
        rgb, alpha = arr[..., :3], arr[..., 3:]
        opaque = alpha[..., 0] > 127
        lum = (rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722)[opaque]
        mean = float(lum.mean()) if lum.size else 255.0
        gain = min(a.max_gain, max(1.0, a.floor / max(1.0, mean)))
        out = np.concatenate([np.clip(rgb * gain, 0, 255), alpha], axis=2).astype(np.uint8)
        fmt = "DXT5" if fourcc == b"DXT5" else "DXT1"
        img = Image.fromarray(out, "RGBA")
        levels, size, cur = [], img.size[0], img
        while True:
            levels.append(encode_level(cur, fmt))
            if size == 1: break
            size //= 2
            cur = img.resize((size, size), Image.LANCZOS)
        dst = os.path.join(a.out, name)
        with open(dst + ".tmp", "wb") as f:
            f.write(dds_header(img.size[0], img.size[1], len(levels), fmt.encode(), len(levels[0])))
            for lv in levels: f.write(lv)
        os.replace(dst + ".tmp", dst)
        print(f"{name}: {fmt} mean luma {mean:.1f} x{gain:.2f} -> {min(255.0, mean * gain):.1f}")
        sheet.append((Image.fromarray(arr.astype(np.uint8), "RGBA").convert("RGB"), img.convert("RGB")))
    if a.sheet and sheet:
        s = Image.new("RGB", (256 * len(sheet), 512))
        for i, (b, c) in enumerate(sheet):
            s.paste(b.resize((256, 256)), (i * 256, 0)); s.paste(c.resize((256, 256)), (i * 256, 256))
        s.save(a.sheet)


if __name__ == "__main__":
    main()
