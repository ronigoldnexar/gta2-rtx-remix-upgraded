#!/usr/bin/env python3
"""DISTRICTS-POC: the facade kit's materials, procedural and deterministic (fixed seeds: the same bytes every
build, so the same RTX Remix texture hash every build). 128 px, DXT1 (DXT5 for the grating's cut-outs), mips.

    kit_textures.py <out dir> [--png]     -> kit_00.dds .. kit_NN.dds (index = kit.py KIT order)

No art from the game, no third-party texture: plain numpy noise and stripes. Licence: as the repository."""
import io, os, struct, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import KIT

N = 128


def noise(seed, scale):
    r = np.random.default_rng(seed)
    small = r.random((N // scale + 2, N // scale + 2))
    im = Image.fromarray((small * 255).astype(np.uint8)).resize((N + 2 * scale, N + 2 * scale), Image.BICUBIC)
    return np.asarray(im, np.float32)[scale:scale + N, scale:scale + N] / 255.0


def fbm(seed):
    return 0.5 * noise(seed, 16) + 0.3 * noise(seed + 1, 6) + 0.2 * noise(seed + 2, 2)


def tint(base, var, seed, amount=0.12):
    n = fbm(seed)[..., None]
    c = np.array(base, np.float32)[None, None, :] / 255.0
    return np.clip(c * (1.0 - amount + 2 * amount * n) + (var - 0.5) * 0.0, 0, 1)


def make(name, k):
    a = np.ones((N, N, 4), np.float32)
    yy, xx = np.mgrid[0:N, 0:N]
    if name == "stone_light":
        a[..., :3] = tint((196, 186, 166), 0, k, 0.10)
        a[..., :3] *= np.where((yy % 64) < 2, 0.82, 1.0)[..., None]
    elif name == "stone_brown":
        a[..., :3] = tint((122, 84, 62), 0, k, 0.12)
        a[..., :3] *= np.where((yy % 64) < 2, 0.8, 1.0)[..., None]
    elif name == "metal_dark":
        a[..., :3] = tint((46, 54, 50), 0, k, 0.10)
    elif name == "metal_galv":
        a[..., :3] = tint((150, 156, 160), 0, k, 0.14)
        a[..., :3] *= (0.92 + 0.08 * np.sin(xx / N * 2 * np.pi * 16))[..., None]
    elif name == "grate":
        bars = ((xx % 16) < 3) | ((yy % 16) < 3)
        a[..., :3] = tint((52, 56, 54), 0, k, 0.10)
        a[..., 3] = np.where(bars, 1.0, 0.0)
    elif name.startswith("awning_"):
        col = {"awning_red": (168, 36, 34), "awning_green": (34, 104, 58), "awning_blue": (40, 70, 140),
               "awning_yellow": (200, 160, 40), "awning_brown": (110, 70, 40)}[name]
        stripe = ((xx // 16) % 2) == 0
        base = np.where(stripe[..., None], np.array(col, np.float32) / 255.0, np.array((226, 220, 204), np.float32) / 255.0)
        a[..., :3] = base * (0.9 + 0.1 * fbm(k)[..., None])
    elif name == "brick_dark":
        row = yy // 8
        off = (row % 2) * 8
        mortar = ((yy % 8) < 1) | (((xx + off) % 16) < 1)
        a[..., :3] = tint((112, 52, 40), 0, k, 0.14)
        a[..., :3] = np.where(mortar[..., None], np.array((150, 140, 128), np.float32) / 255.0, a[..., :3])
    elif name == "concrete":
        a[..., :3] = tint((150, 148, 140), 0, k, 0.12)
    elif name == "wood":
        plank = (xx // 10) % 2
        a[..., :3] = tint((120, 84, 54), 0, k, 0.16) * np.where(plank[..., None] == 0, 1.0, 0.88)
        a[..., :3] *= np.where((xx % 10) < 1, 0.7, 1.0)[..., None]
    elif name.startswith("canvas_"):
        col = {"canvas_red": (150, 40, 36), "canvas_green": (40, 92, 56), "canvas_navy": (36, 50, 92), "canvas_maroon": (100, 34, 44),
               "canvas_cream": (214, 202, 170), "canvas_ochre": (176, 128, 52)}[name]
        weave = 0.94 + 0.06 * (((xx // 2) + (yy // 2)) % 2)
        a[..., :3] = tint(col, 0, k, 0.06) * weave[..., None]
    elif name == "rubber":
        a[..., :3] = tint((28, 28, 30), 0, k, 0.08)
    elif name == "shutter":
        # a roller shutter: galvanised slats (a rib every 8 px: 16 a block at the kit's scale 2), streaks and grime
        rib = 0.80 + 0.20 * np.sin((yy % 8) / 8.0 * 2 * np.pi) ** 2
        a[..., :3] = tint((132, 138, 140), 0, k, 0.16) * rib[..., None]
        a[..., :3] *= np.where((yy % 8) == 0, 0.62, 1.0)[..., None]
        a[..., :3] *= (0.9 + 0.1 * noise(k + 7, 32)[..., None])
    elif name == "glass_dark":
        a[..., :3] = tint((30, 40, 52), 0, k, 0.06)
    return np.clip(a, 0, 1)


def dds(img, fmt):
    import struct as st
    levels, w = [], img.width
    im = img
    while True:
        buf = io.BytesIO()
        (im.convert("RGB") if fmt == "DXT1" else im.convert("RGBA")).save(buf, format="DDS", pixel_format=fmt)
        levels.append(buf.getvalue()[128:])
        if im.width <= 4:
            break
        im = im.resize((im.width // 2, im.height // 2), Image.BOX)
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000
    caps = 0x1000 | 0x400000 | 0x8
    pf = st.pack("<II4sIIIII", 32, 0x4, fmt.encode(), 0, 0, 0, 0, 0)
    head = b"DDS " + st.pack("<IIIIIII", 124, flags, img.height, img.width, len(levels[0]), 0, len(levels)) + b"\0" * 44 + pf + st.pack("<IIIII", caps, 0, 0, 0, 0)
    return head + b"".join(levels)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for k, name in enumerate(KIT):
        a = make(name, 1000 + k)
        img = Image.fromarray((a * 255 + 0.5).astype(np.uint8), "RGBA")
        fmt = "DXT5" if name == "grate" else "DXT1"
        open(os.path.join(out, f"kit_{k:02d}.dds"), "wb").write(dds(img, fmt))
        if "--png" in sys.argv:
            img.save(os.path.join(out, f"kit_{k:02d}_{name}.png"))
    print(f"{len(KIT)} kit textures -> {out}")


if __name__ == "__main__":
    main()
