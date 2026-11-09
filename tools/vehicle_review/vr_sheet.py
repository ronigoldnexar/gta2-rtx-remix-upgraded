#!/usr/bin/env python3
"""VEHICLE-REVIEW contact sheets: per model a row of sprite | traffic far | traffic close (crop) |
eye height (crop) | eye height 2 (crop) | own car chase | own car seat.
usage: vr_sheet.py <traffic run dir> <seat run dir> <out dir> [models...]  (batches of 7 models per sheet)"""
import glob, os, sys, re
from PIL import Image, ImageDraw

traffic, seat, out = sys.argv[1:4]
models = [int(m) for m in sys.argv[4:]] or sorted({int(re.search(r'(\d{3})\.png$', f).group(1))
                                                     for f in glob.glob(f'{traffic}/drv_far_*.png')})
names = {int(os.path.basename(f)[:3]): os.path.basename(f)[:-12] for f in glob.glob('assets-src/cars/sprites_x4/*_default.png')}
os.makedirs(out, exist_ok=True)
W, H = 400, 225
CROP = (240, 150, 1040, 600)      # the car in the lower middle of a 1280x720 frame

def cell(path, crop=None):
    try:
        im = Image.open(path).convert('RGB')
    except Exception:
        im = Image.new('RGB', (W, H), (40, 40, 40)); ImageDraw.Draw(im).text((10, 10), 'missing', fill=(255, 80, 80)); return im
    if crop: im = im.crop(crop)
    return im.resize((W, H), Image.LANCZOS)

cols = [('far', lambda n: cell(f'{traffic}/drv_far_{n:03d}.png')),
        ('close', lambda n: cell(f'{traffic}/drv_close_{n:03d}.png', CROP)),
        ('eye', lambda n: cell(f'{traffic}/drv_fp_{n:03d}.png', CROP)),
        ('eye2', lambda n: cell(f'{traffic}/drv_fp2_{n:03d}.png', CROP)),
        ('own chase', lambda n: cell(f'{seat}/t_own3_{n:03d}.png')),
        ('own seat', lambda n: cell(f'{seat}/t_own1_{n:03d}.png'))]
PER = 7
for b in range(0, len(models), PER):
    batch = models[b:b + PER]
    sheet = Image.new('RGB', (130 + len(cols) * (W + 4), len(batch) * (H + 22)), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    for r, n in enumerate(batch):
        y = r * (H + 22)
        d.text((4, y + 4), f'{n:03d} {names.get(n, "")}', fill=(255, 255, 0))
        sp = glob.glob(f'assets-src/cars/sprites_x4/{n:03d}_*_default.png')
        if sp:
            s = Image.open(sp[0]).convert('RGBA'); sw, sh = s.size; sc = min(110 / sw, (H - 10) / sh)
            s = s.resize((max(1, int(sw * sc)), max(1, int(sh * sc)))); sheet.paste(s, (8, y + 20), s)
        for c, (label, fn) in enumerate(cols):
            x = 130 + c * (W + 4)
            sheet.paste(fn(n), (x, y + 20)); d.text((x + 4, y + 4), label, fill=(200, 200, 200))
    p = f'{out}/sheet_{batch[0]:03d}_{batch[-1]:03d}.png'; sheet.save(p); print(p, sheet.size)
