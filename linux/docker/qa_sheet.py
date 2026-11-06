#!/usr/bin/env python3
"""qa_sheet.py <out.png> <cols> <img[:label]>...  - labelled contact sheet (host side)."""
import sys
from PIL import Image, ImageDraw, ImageFont

out, cols = sys.argv[1], int(sys.argv[2])
items = sys.argv[3:]
W, H, BAR = 640, 360, 22
rows = (len(items) + cols - 1) // cols
sheet = Image.new("RGB", (cols * W, rows * (H + BAR)), (20, 20, 20))
draw = ImageDraw.Draw(sheet)
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
except OSError:
    font = ImageFont.load_default()
for n, item in enumerate(items):
    path, _, label = item.partition(":")
    label = label or path.rsplit("/", 1)[-1]
    x, y = (n % cols) * W, (n // cols) * (H + BAR)
    try:
        im = Image.open(path).convert("RGB").resize((W, H))
        sheet.paste(im, (x, y + BAR))
    except OSError:
        draw.rectangle([x, y + BAR, x + W, y + BAR + H], fill=(60, 0, 0))
    draw.text((x + 4, y + 3), label, fill=(255, 255, 255), font=font)
sheet.save(out)
print(out, sheet.size)
