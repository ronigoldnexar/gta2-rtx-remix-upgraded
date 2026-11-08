#!/usr/bin/env python3
"""Contact sheet of the district mission attempts: labelled milestone frames."""
import sys, glob, os
from PIL import Image, ImageDraw
out = sys.argv[1]; items = []
for spec in sys.argv[2:]:
    label, path = spec.split("=", 1); items.append((label, path))
cols, W, H = 4, 640, 360
rows = (len(items) + cols - 1) // cols
sheet = Image.new("RGB", (W * cols, H * rows + 0), (18, 18, 18)); d = ImageDraw.Draw(sheet)
for i, (label, p) in enumerate(items):
    try: im = Image.open(p).convert("RGB").resize((W, H))
    except Exception: im = Image.new("RGB", (W, H), (70, 0, 0))
    x, y = (i % cols) * W, (i // cols) * H
    sheet.paste(im, (x, y)); d.rectangle((x, y, x + W, y + 18), fill=(0, 0, 0)); d.text((x + 6, y + 3), label, fill=(255, 230, 0))
sheet.save(out); print(out, len(items), "frames")
