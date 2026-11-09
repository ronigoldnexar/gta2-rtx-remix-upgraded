#!/usr/bin/env python3
"""Crisp lettering for billboard tiles in the street views (FIX-WORLD-3, pm21-bil-billboard-live-show-sign-illegible-red-mush).

The Industrial "LIVE SHOW" billboards (bil tiles 412 and 413, the two frames of the neon) are a
64 px picture: red serif LIVE / SHOW on a dark red panel with rows of bulbs, in a pink frame.
The HD upscale kept the frame but melted the face: letters run into each other and into the
bulbs, and the lower line is unreadable from the start courtyard. This writes photo-set copies
(street views only: the classic view keeps the HD tile and RTX Remix its hashes) with the frame
taken from the HD tile and the face redrawn at full resolution:

  panel   the original's dark red, a slight vertical gradient
  bulbs   the two corners the lettering leaves free, as in the original, alternate bulbs lit
          in the two frames (the neon's flicker)
  text    LIVE and SHOW in DejaVu Serif Bold (Bitstream Vera licence) in the original's red,
          fitted to the original's boxes, with a dark outline so they stand off the panel

    billboard_text_tiles.py <hd root> <photo root> [--style bil]

hd root: assets/textures_hd (reads bil/tile_0412.dds, tile_0413.dds); photo root:
assets/textures_hd/photo. Needs numpy and Pillow.
"""
import argparse, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from railing_metal_tiles import write_dds   # DXT5 with mips, written as a new inode

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
# In the original's 64 px coordinates.
PANEL = (4, 4, 60, 28)
LIVE_BOX = (5, 5, 39, 15)
SHOW_BOX = (15, 16, 58, 27)
BULB_ZONES = [(41, 5, 59, 14), (5, 16, 14, 27)]
RED = (245, 28, 22)
PANEL_TOP, PANEL_BOTTOM = (78, 6, 12), (52, 3, 8)
OUTLINE = (30, 0, 2)


def fit_text(draw, text, box, scale):
    x0, y0, x1, y1 = [v * scale for v in box]
    size = 8
    while True:
        font = ImageFont.truetype(FONT, size + 2)
        l, t, r, b = draw.textbbox((0, 0), text, font=font, stroke_width=max(2, scale // 2))
        if r - l > x1 - x0 or b - t > y1 - y0: break
        size += 2
    font = ImageFont.truetype(FONT, size)
    l, t, r, b = draw.textbbox((0, 0), text, font=font, stroke_width=max(2, scale // 2))
    return font, (x0 + ((x1 - x0) - (r - l)) / 2 - l, y0 + ((y1 - y0) - (b - t)) / 2 - t)


def face(hd, frame):
    size = hd.size[0]
    s = size // 64
    out = hd.copy()
    px0, py0, px1, py1 = [v * s for v in PANEL]
    panel = Image.new("RGBA", (px1 - px0, py1 - py0))
    g = np.linspace(0, 1, py1 - py0)[:, None, None]
    col = (1 - g) * np.array(PANEL_TOP) + g * np.array(PANEL_BOTTOM)
    arr = np.concatenate([np.broadcast_to(col, (py1 - py0, px1 - px0, 3)), np.full((py1 - py0, px1 - px0, 1), 255)], axis=2)
    panel = Image.fromarray(arr.astype(np.uint8), "RGBA")
    out.paste(panel, (px0, py0))
    d = ImageDraw.Draw(out)
    # bulbs
    glow = Image.new("RGBA", out.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = int(s * 1.1)
    k = 0
    for zx0, zy0, zx1, zy1 in BULB_ZONES:
        for by in range(zy0 * s + 2 * r, zy1 * s - r, int(3.2 * r)):
            for bx in range(zx0 * s + 2 * r, zx1 * s - r, int(3.2 * r)):
                lit = (k + frame) % 2 == 0
                k += 1
                c = (255, 70, 40, 255) if lit else (110, 10, 12, 255)
                d.ellipse((bx - r, by - r, bx + r, by + r), fill=c, outline=OUTLINE, width=max(1, s // 4))
                if lit: gd.ellipse((bx - 2 * r, by - 2 * r, bx + 2 * r, by + 2 * r), fill=(255, 60, 30, 90))
    out = Image.alpha_composite(out, glow.filter(ImageFilter.GaussianBlur(r)))
    d = ImageDraw.Draw(out)
    for text, box in (("LIVE", LIVE_BOX), ("SHOW", SHOW_BOX)):
        font, at = fit_text(d, text, box, s)
        d.text(at, text, font=font, fill=RED + (255,), stroke_width=max(2, s // 2), stroke_fill=OUTLINE + (255,))
    # alpha is the HD tile's, untouched
    a = np.asarray(out).copy()
    a[..., 3] = np.asarray(hd)[..., 3]
    return a.astype(np.float32) / 255.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("hd"); p.add_argument("photo")
    p.add_argument("--style", default="bil")
    a = p.parse_args()
    os.makedirs(os.path.join(a.photo, a.style), exist_ok=True)
    for frame, t in enumerate((412, 413)):
        hd = Image.open(os.path.join(a.hd, a.style, "tile_%04d.dds" % t)).convert("RGBA")
        dst = os.path.join(a.photo, a.style, "tile_%04d.dds" % t)
        write_dds(dst, face(hd, frame))
        print("%s tile %d -> %s" % (a.style, t, dst))


if __name__ == "__main__":
    main()
