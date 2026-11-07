#!/usr/bin/env python3
"""Tile the chase + first-person frames of a car_models_sheet run: per model a
pair (chase crop | first-person crop), labelled.
    car_models_sheet_make2.py <run dir> <catalog.json> <out.png> [first model] [count]"""
import glob, json, os, sys
from PIL import Image, ImageDraw, ImageFont
run, catalog, out = sys.argv[1:4]
start = int(sys.argv[4]) if len(sys.argv) > 4 else 0
count = int(sys.argv[5]) if len(sys.argv) > 5 else 999
names = {m["model"]: m["name"] for m in json.load(open(catalog))["cars"]}
files = sorted(glob.glob(os.path.join(run, "drv_model_*.png")))
files = [f for f in files if int(os.path.basename(f)[10:13]) >= start][:count]
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
cw, ch = 470, 260            # chase crop target
fw, fh = 560, 260            # first-person crop target
cols = 3
rows = (len(files) + cols - 1) // cols
tilew, tileh = cw + fw + 6, ch + 32
sheet = Image.new("RGB", (cols * tilew, rows * tileh), (18, 18, 18))
d = ImageDraw.Draw(sheet)
for i, f in enumerate(files):
    n = int(os.path.basename(f)[10:13])
    chase = Image.open(f).convert("RGB").crop((600, 255, 990, 470)).resize((cw, ch), Image.LANCZOS)
    fpf = os.path.join(run, f"drv_fp_model_{n:03d}.png")
    x, y = (i % cols) * tilew, (i // cols) * tileh
    sheet.paste(chase, (x, y + 32))
    if os.path.exists(fpf):
        fp = Image.open(fpf).convert("RGB").crop((760, 320, 1280, 560)).resize((fw, fh), Image.LANCZOS)
        sheet.paste(fp, (x + cw + 6, y + 32))
    d.text((x + 6, y + 4), f"{n:03d} {names.get(n, '')}", fill=(255, 230, 90), font=font)
sheet.save(out)
print(out, len(files), "models")
