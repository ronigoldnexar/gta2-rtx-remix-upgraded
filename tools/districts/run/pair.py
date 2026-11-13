#!/usr/bin/env python3
"""pair.py <out.png> <label> <img> [<label> <img> ...] : a labelled grid, two images a row"""
import sys
from PIL import Image, ImageDraw
out = sys.argv[1]; items = list(zip(sys.argv[2::2], sys.argv[3::2]))
ims = [(l, Image.open(p).convert("RGB")) for l, p in items]
w = max(i.width for _, i in ims); h = max(i.height for _, i in ims)
cols = 2; rows = (len(ims) + 1) // 2
s = Image.new("RGB", (cols * w + 6, rows * (h + 18)), (0, 0, 0))
for k, (l, i) in enumerate(ims):
    x, y = (k % cols) * (w + 6), (k // cols) * (h + 18)
    s.paste(i, (x, y + 18)); ImageDraw.Draw(s).text((x + 4, y + 3), l, fill=(255, 255, 255))
s.save(out)
