#!/usr/bin/env python3
"""ASSET-PEDS-2: bake a hair colour into a Rocketbox head texture (the hair is painted into
the head map, not a separate card mesh, so the renderer's hair tint cannot reach it).
Hair texels = the upper part of the map (above the face) that differ from the face's skin;
their luminance detail is kept and the hue becomes the target.
Also `mul`: multiply a whole texture by a colour (the Hulk's green skin).
Usage: recolor_hair.py hair <head_color.tga> <out.tga> R G B [mask_preview.png]
       recolor_hair.py mul  <color.tga> <out.tga> R G B      (factors 0..2)"""
import sys
import numpy as np
from PIL import Image, ImageFilter

def hair_mask(a):
    h, w, _ = a.shape
    f = a[int(0.22 * h):int(0.42 * h), int(0.40 * w):int(0.60 * w)].reshape(-1, 3)   # forehead/cheeks
    skin = np.median(f, axis=0)
    d = np.sqrt(((a - skin) ** 2).sum(axis=2))
    lum = a.mean(axis=2)
    m = (d > 38) | (lum < skin.mean() * 0.62)
    # only the head's top region; the face, ears and neck keep their skin
    yy, xx = np.mgrid[0:h, 0:w]
    region = (yy < 0.50 * h)
    face = ((xx - 0.5 * w) / (0.19 * w)) ** 2 + ((yy - 0.36 * h) / (0.22 * h)) ** 2 < 1.0
    m &= region & ~face
    img = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.GaussianBlur(3))
    return np.asarray(img).astype(np.float32) / 255.0, skin

def main():
    mode, sys.argv = sys.argv[1], sys.argv[1:]
    src, dst = sys.argv[1], sys.argv[2]
    tgt = np.array([float(x) for x in sys.argv[3:6]])
    if mode == "mul":
        a = np.asarray(Image.open(src).convert("RGB")).astype(np.float32)
        Image.fromarray(np.clip(a * tgt[None, None, :], 0, 255).astype(np.uint8)).save(dst); return
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(np.float32)
    m, skin = hair_mask(a)
    lum = a.mean(axis=2, keepdims=True)
    hm = (lum * m[..., None]).sum() / max((m > 0.5).sum(), 1)
    new = tgt[None, None, :] * (lum / max(hm, 1.0)) * 1.0
    out = a * (1 - m[..., None]) + np.clip(new, 0, 255) * m[..., None]
    Image.fromarray(out.astype(np.uint8)).save(dst)
    if len(sys.argv) > 6: Image.fromarray((m * 255).astype(np.uint8)).resize((512, 512)).save(sys.argv[6])
main()
