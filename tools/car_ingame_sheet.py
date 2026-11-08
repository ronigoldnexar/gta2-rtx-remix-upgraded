#!/usr/bin/env python3
"""In-game before/after: the chase-camera frame of each model from two car_models_sheet runs.
   car_ingame_sheet.py --before out/carsheet_final --after out/cq_sheet_v2 --models 12,56,... --out out/car_quality_ingame.png
   --fp adds the after run's first-person frame (drv_fp_model_NNN.png) as a third column; --after may be a
   comma list of run dirs (chunks), the first one holding a model's frame wins."""
import argparse, os
from PIL import Image, ImageDraw
ap = argparse.ArgumentParser()
ap.add_argument('--before', required=True); ap.add_argument('--after', required=True); ap.add_argument('--models', required=True)
ap.add_argument('--out', required=True); ap.add_argument('--fp', action='store_true'); ap.add_argument('--fp-crop', default='0,0,1280,720'); ap.add_argument('--crop', default='400,230,1060,440', help='l,t,r,b crop of the 1280x720 frame around the car')
a = ap.parse_args()
l, t, r, b = [int(v) for v in a.crop.split(',')]
models = [int(m) for m in a.models.split(',')]
W, H = r - l, b - t; s = 0.75; w, h = int(W * s), int(H * s); pad = 8; cols = 4 if not a.fp else 3
fl, ft, fr, fb = [int(v) for v in a.fp_crop.split(',')]
k = 3 if a.fp else 2
rows = (len(models) + cols - 1) // cols
sheet = Image.new('RGB', (cols * (k * w + (k + 1) * pad), rows * (h + 24 + pad) + 24), (20, 20, 24))
d = ImageDraw.Draw(sheet)
d.text((pad, 4), 'each group: BEFORE (v1 model) | AFTER, same parked car, chase camera' + (' | AFTER, first person' if a.fp else ''), fill=(230, 230, 230))
def find(runs, name):
    for run in runs.split(','):
        p = os.path.join(run, name)
        if os.path.exists(p):
            return p
    return ''
for i, m in enumerate(models):
    cx = (i % cols) * (k * w + (k + 1) * pad); cy = 24 + (i // cols) * (h + 24 + pad)
    srcs = [(a.before, f'drv_model_{m:03d}.png', (l, t, r, b)), (a.after, f'drv_model_{m:03d}.png', (l, t, r, b))]
    if a.fp:
        srcs.append((a.after, f'drv_fp_model_{m:03d}.png', (fl, ft, fr, fb)))
    for j, (runs, name, box) in enumerate(srcs):
        p = find(runs, name); x = cx + pad + j * (w + pad)
        if p:
            sheet.paste(Image.open(p).convert('RGB').crop(box).resize((w, h), Image.LANCZOS), (x, cy + 16))
        else:
            d.rectangle((x, cy + 16, x + w, cy + 16 + h), outline=(90, 90, 90)); d.text((x + 8, cy + 24), 'missing', fill=(160, 160, 160))
    d.text((cx + pad, cy + 2), f'model {m:03d}', fill=(255, 220, 120))
sheet.save(a.out); print(a.out, sheet.size)
