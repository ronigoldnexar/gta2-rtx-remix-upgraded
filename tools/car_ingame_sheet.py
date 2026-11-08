#!/usr/bin/env python3
"""In-game before/after: the chase-camera frame of each model from two car_models_sheet runs.
   car_ingame_sheet.py --before out/carsheet_final --after out/cq_sheet_v2 --models 12,56,... --out out/car_quality_ingame.png"""
import argparse, os
from PIL import Image, ImageDraw
ap = argparse.ArgumentParser()
ap.add_argument('--before', required=True); ap.add_argument('--after', required=True); ap.add_argument('--models', required=True)
ap.add_argument('--out', required=True); ap.add_argument('--crop', default='400,230,1060,440', help='l,t,r,b crop of the 1280x720 frame around the car')
a = ap.parse_args()
l, t, r, b = [int(v) for v in a.crop.split(',')]
models = [int(m) for m in a.models.split(',')]
W, H = r - l, b - t; s = 0.75; w, h = int(W * s), int(H * s); pad = 8; cols = 4
rows = (len(models) + cols - 1) // cols
sheet = Image.new('RGB', (cols * (2 * w + 3 * pad), rows * (h + 24 + pad) + 24), (20, 20, 24))
d = ImageDraw.Draw(sheet)
d.text((pad, 4), 'each pair: BEFORE (v1 model) | AFTER (v2 model), same parked car, chase camera', fill=(230, 230, 230))
for i, m in enumerate(models):
    cx = (i % cols) * (2 * w + 3 * pad); cy = 24 + (i // cols) * (h + 24 + pad)
    for j, run in enumerate((a.before, a.after)):
        p = os.path.join(run, f'drv_model_{m:03d}.png'); x = cx + pad + j * (w + pad)
        if os.path.exists(p):
            sheet.paste(Image.open(p).convert('RGB').crop((l, t, r, b)).resize((w, h), Image.LANCZOS), (x, cy + 16))
        else:
            d.rectangle((x, cy + 16, x + w, cy + 16 + h), outline=(90, 90, 90)); d.text((x + 8, cy + 24), 'missing', fill=(160, 160, 160))
    d.text((cx + pad, cy + 2), f'model {m:03d}', fill=(255, 220, 120))
sheet.save(a.out); print(a.out, sheet.size)
