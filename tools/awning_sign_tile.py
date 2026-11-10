#!/usr/bin/env python3
"""pm3: a clean awning sign for the photo/ tile set (FIX-WORLD-8, pm3-building-awning-sign-garbled-glyphs).

Residential (ste) tile 283 is an awning strip over the garage doors: an off-white panel with a down arrow,
two blocks of small lettering and a right arrow. In the game's 64 px art the lettering is only faint grey
dashes (pseudo-text), which the HD upscale turned into red wavy pseudo-glyphs. This redraws the strip at
1024 px: the HD panel with its lettering blurred out, crisp grey arrows where the art has them, and real
words in the art's text blocks (DejaVu Sans Condensed Bold, Bitstream Vera Fonts licence, the system's
fonts-dejavu-core; rendered into the tile, not shipped). The transparent rest of the tile stays the HD
tile's alpha. The shipped textures_hd DDS are never touched (Remix keys them by hash); the result goes
into gta2dx9_textures_hd/photo/ste/, bound only in the street views.

    awning_sign_tile.py <hd ste/tile_0283.dds> <out photo/ste/tile_0283.dds> [--preview out.png]
"""
import argparse, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = 1024
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
# in the original's 64 px coordinates (measured on ste 283)
PANEL = (1.0, 16.0)                  # rows of the panel between its two border lines
DOWN = (9.0, 4.0, 12.6)              # down arrow: centre x, top, tip
RIGHT = (49.0, 57.6, 7.5)            # right arrow: tail x, tip x, centre row
TEXT = [((15.5, 31.5), ("GARAGE", "ENTRANCE")), ((33.0, 46.5), ("KEEP", "CLEAR"))]
ARROW = (118, 118, 124)
INK = (64, 62, 66)


def build(src, size=OUT):
    hd = Image.open(src).convert("RGBA")
    s = size / 64.0
    base = hd.resize((size, size), Image.LANCZOS)
    alpha = hd.getchannel("A").resize((size, size), Image.NEAREST)
    rgb = base.convert("RGB")
    # the panel without its lettering: its own median tone, a little lighter toward the top (the awning
    # catches the sky), fine grain; the old glyphs and arrows (and their halos) are gone entirely
    y0, y1 = int(PANEL[0] * s) + 2, int(PANEL[1] * s) - 2
    panel = rgb.crop((0, y0, size, y1))
    med = np.median(np.asarray(panel).reshape(-1, 3), axis=0).astype(np.float32)
    h, w = y1 - y0, size
    ramp = np.linspace(1.04, 0.97, h, dtype=np.float32)[:, None, None]
    rng = np.random.default_rng(283)
    noise = np.asarray(Image.fromarray((rng.normal(0, 1, (h // 2, w // 2)) * 40 + 128).clip(0, 255).astype(np.uint8))
                       .resize((w, h), Image.BICUBIC)).astype(np.float32)[..., None] - 128
    a = med[None, None] * ramp + 0.06 * noise
    rgb.paste(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), (0, y0))
    # drawn at 2x, then reduced: crisp anti-aliased edges
    ss = 2
    big = rgb.resize((size * ss, size * ss), Image.LANCZOS)
    d = ImageDraw.Draw(big)
    k = s * ss
    cx, top, tip = DOWN
    shaft = 1.6
    d.polygon([((cx - shaft) * k, top * k), ((cx + shaft) * k, top * k), ((cx + shaft) * k, (tip - 4.2) * k),
               ((cx + 4.6) * k, (tip - 4.2) * k), (cx * k, tip * k), ((cx - 4.6) * k, (tip - 4.2) * k),
               ((cx - shaft) * k, (tip - 4.2) * k)], fill=ARROW)
    tx, px, cy = RIGHT
    d.polygon([(tx * k, (cy - shaft) * k), ((px - 4.2) * k, (cy - shaft) * k), ((px - 4.2) * k, (cy - 4.6) * k),
               (px * k, cy * k), ((px - 4.2) * k, (cy + 4.6) * k), ((px - 4.2) * k, (cy + shaft) * k),
               (tx * k, (cy + shaft) * k)], fill=ARROW)
    for (x0, x1), lines in TEXT:
        h = 3.3 * k
        font = ImageFont.truetype(FONT, int(h))
        rows = [5.9, 10.3]
        for line, row in zip(lines, rows):
            w = d.textlength(line, font=font)
            room = (x1 - x0) * k
            f = font
            if w > room:      # fit the block's width
                f = ImageFont.truetype(FONT, int(h * room / w))
                w = d.textlength(line, font=f)
            d.text(((x0 + x1) / 2 * k - w / 2, row * k), line, font=f, fill=INK, anchor="ls")
    out = big.resize((size, size), Image.LANCZOS)
    rgba = np.dstack([np.asarray(out), np.asarray(alpha)]).astype(np.float32) / 255
    return rgba


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst"); ap.add_argument("--preview", default="")
    a = ap.parse_args()
    rgba = build(a.src)
    from photoreal_tiles import write_dds
    write_dds(a.dst, rgba)
    if a.preview:
        Image.fromarray((rgba[..., :3] * 255 + 0.5).astype(np.uint8)).crop((0, 0, OUT, OUT // 4)).save(a.preview)
    print("wrote", a.dst)


if __name__ == "__main__":
    main()
