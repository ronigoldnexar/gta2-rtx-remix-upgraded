#!/usr/bin/env python3
"""Crisp graffiti for the street views (FIX-WORLD-7, pm11-third-graffiti-decal-overhangs-wall-corner-and-blurry
and tri-ste-blue-concentric-whirl): the Residential graffiti pieces' HD copies are soft upscales of 64 px art, so
from a block away a piece reads as a smeared sticker with a ragged dark fringe. This writes photo-set copies
(the street views load photo/<style>/tile_NNNN.dds before the HD set; the HD set itself is locked by the RTX
Remix texture hashes and is never rewritten) at 1024 px: the HD art's colours reduced to the piece's own
palette (k-means), cleaned of speckle (majority filter) and given back a little of its spray shading, with
a crisp anti-aliased cut-out edge in place of the dithered one.

    python3 tools/graffiti_crisp_tiles.py <hd root> <photo root> [style:tile ...]

hd root: assets/textures_hd (reads <style>/tile_NNNN.dds); photo root: assets/textures_hd/photo.
Default tiles: ste 355 353 382 383 284. Needs numpy, scipy-free (numpy + Pillow only)."""
import os, sys
import numpy as np
from PIL import Image, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from railing_metal_tiles import write_dds   # DXT5 with mips, written as a new inode

DEFAULT = ["ste:355", "ste:353", "ste:382", "ste:383", "ste:284"]
SIZE = 1024


def kmeans(x, k, iters=12, seed=3):
    rng = np.random.default_rng(seed)
    c = x[rng.choice(len(x), k, replace=False)].copy()
    for _ in range(iters):
        d = ((x[:, None, :] - c[None, :, :]) ** 2).sum(2)
        lab = d.argmin(1)
        for j in range(k):
            m = lab == j
            if m.any(): c[j] = x[m].mean(0)
    return c, lab


def majority(labels, k, mask, passes=2):
    h, w = labels.shape
    for _ in range(passes):
        counts = np.zeros((k, h, w), np.int16)
        pad = np.pad(labels, 1, mode="edge")
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                sl = pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
                for j in range(k):
                    counts[j] += (sl == j)
        labels = np.where(mask, counts.argmax(0), labels)
    return labels


def crisp(hd):
    img = hd.convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS)
    a = np.asarray(img).astype(np.float32) / 255.0
    rgb, alpha = a[..., :3], a[..., 3]
    # the cut-out: the 64 px mask (the HD alpha is its 8x staircase) box-reduced to the art's own grid, a
    # bicubic upscale and a ~1.5-texel smoothing so the edge follows the shape's curve, then a hard step
    # with a one-texel ramp (FIX-WORLD-15 pmq50: the 2 px blur kept the 16 px stairs, seen from half a block)
    a64 = Image.fromarray((alpha * 255).astype(np.uint8)).resize((64, 64), Image.BOX)
    al = np.asarray(a64.resize((SIZE, SIZE), Image.BICUBIC).filter(ImageFilter.GaussianBlur(SIZE / 64 * 0.45))).astype(np.float32) / 255.0
    edge = np.clip((al - 0.46) / 0.08, 0.0, 1.0)
    solid = edge > 0.5
    # palette: k-means on a 64 px-scale sample of the opaque texels
    small = np.asarray(img.resize((128, 128), Image.BOX)).astype(np.float32) / 255.0
    sample = small[..., :3][small[..., 3] > 0.6]
    k = 12
    centres, _ = kmeans(sample, k)
    d = ((rgb[..., None, :] - centres[None, None, :, :]) ** 2).sum(-1)
    lab = d.argmin(-1)
    lab = majority(lab, k, solid, passes=3)
    flat = centres[lab]
    # the spray shading back: the art's own gradients round the flat colour, down to a 3 px scale, so a
    # region is not one flat step (a 6 px blur at 0.35 left contour bands, FIX-WORLD-15 pmq50)
    blur = np.asarray(Image.fromarray((rgb * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3))).astype(np.float32) / 255.0
    flatb = np.asarray(Image.fromarray((flat * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3))).astype(np.float32) / 255.0
    out = np.clip(flat + 0.85 * (blur - flatb), 0.0, 1.0)
    # one-texel anti-aliasing of the colour boundaries
    out = np.asarray(Image.fromarray((out * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.7))).astype(np.float32) / 255.0
    # the colour under the transparent texels: the nearest solid colour (no dark halo in the mips)
    out = np.where(solid[..., None], out, np.asarray(Image.fromarray((out * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))).astype(np.float32) / 255.0)
    return np.concatenate([out, edge[..., None]], -1)


def main():
    hd_root, photo_root = sys.argv[1], sys.argv[2]
    for spec in sys.argv[3:] or DEFAULT:
        style, tile = spec.split(":"); tile = int(tile)
        src = os.path.join(hd_root, style, f"tile_{tile:04d}.dds")
        dst = os.path.join(photo_root, style, f"tile_{tile:04d}.dds")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        rgba = crisp(Image.open(src))
        write_dds(dst, rgba)
        print(spec, "->", dst)


if __name__ == "__main__":
    main()
