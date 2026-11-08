#!/usr/bin/env python3
"""Contact strip for the ACTIONS-3D probes: a3_tile.py out.png cols crop|full w file...
crop: the middle of the frame around the third-person figure (x 400-880, y 200-620)."""
import sys
from PIL import Image, ImageDraw
out, cols, mode, w = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
files = sys.argv[5:]
box = {"crop": (400, 180, 880, 620), "full": None, "wide": (240, 120, 1040, 680)}[mode]
ims = []
for f in files:
    im = Image.open(f).convert("RGB")
    if box: im = im.crop(box)
    h = int(im.height * w / im.width)
    im = im.resize((w, h))
    d = ImageDraw.Draw(im); lab = f.split("/")[-1].replace("qa_", "").replace(".png", "")
    d.rectangle((0, 0, 7 * len(lab) + 4, 12), fill=(0, 0, 0)); d.text((2, 0), lab, fill=(255, 255, 0))
    ims.append(im)
rows = (len(ims) + cols - 1) // cols
H = max(i.height for i in ims)
sheet = Image.new("RGB", (cols * w, rows * H), (20, 20, 20))
for k, im in enumerate(ims): sheet.paste(im, ((k % cols) * w, (k // cols) * H))
sheet.save(out); print(out, sheet.size)
