#!/usr/bin/env python3
"""grid.py <out.jpg> <cols> <cell width> <label> <img> [<label> <img> ...]: a labelled grid of frames (a missing
frame is a dark red cell), row-major"""
import os, sys
from PIL import Image, ImageDraw
out, cols, cw = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
items = list(zip(sys.argv[4::2], sys.argv[5::2]))
cells = []
for l, p in items:
    im = Image.open(p).convert("RGB") if os.path.exists(p) else Image.new("RGB", (1280, 720), (60, 0, 0))
    cells.append((l, im.resize((cw, cw * im.height // im.width), Image.LANCZOS)))
h = max(i.height for _, i in cells)
rows = (len(cells) + cols - 1) // cols
s = Image.new("RGB", (cols * (cw + 4), rows * (h + 18)), (0, 0, 0))
for k, (l, i) in enumerate(cells):
    x, y = (k % cols) * (cw + 4), (k // cols) * (h + 18)
    s.paste(i, (x, y + 18)); ImageDraw.Draw(s).text((x + 4, y + 3), l, fill=(255, 255, 255))
s.save(out, quality=88)
print(out, s.size)
