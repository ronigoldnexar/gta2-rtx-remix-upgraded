#!/usr/bin/env python3
"""Tile the force-model frames of a car_models_sheet run into one labelled sheet.
    car_models_sheet_make.py <run dir> <catalog.json> <out.png> [crop x0,y0,x1,y1]"""
import glob, json, os, sys
from PIL import Image, ImageDraw, ImageFont
run, catalog, out = sys.argv[1:4]
crop = [int(v) for v in sys.argv[4].split(",")] if len(sys.argv) > 4 else None
names = {m["model"]: m["name"] for m in json.load(open(catalog))["cars"]}
files = sorted(glob.glob(os.path.join(run, "drv_model_*.png")))
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
tw, th = 426, 240
cols = 8
rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw, rows * (th + 30)), (18, 18, 18))
d = ImageDraw.Draw(sheet)
for i, f in enumerate(files):
    n = int(os.path.basename(f)[10:13])
    im = Image.open(f).convert("RGB")
    if crop: im = im.crop(crop)
    im = im.resize((tw, th), Image.LANCZOS)
    x, y = (i % cols) * tw, (i // cols) * (th + 30)
    sheet.paste(im, (x, y + 30))
    d.text((x + 6, y + 4), f"{n:03d} {names.get(n, '')}", fill=(255, 230, 90), font=font)
sheet.save(out)
print(out, len(files), "frames")
