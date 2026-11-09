#!/usr/bin/env python3
"""VEHICLE-REVIEW model card: one 1280x720 image per model from the walk-around run
(door | front quarter / rear quarter | far chase), the sprite inset top-left.
usage: vr_card.py <walk run dir> <out dir> [models...]"""
import glob, os, sys, re
from PIL import Image, ImageDraw
run, out = sys.argv[1:3]
models = [int(m) for m in sys.argv[3:]] or sorted({int(re.search(r'(\d{3})\.png$', f).group(1)) for f in glob.glob(f'{run}/drv_rq_*.png')})
names = {int(os.path.basename(f)[:3]): os.path.basename(f)[:-12] for f in glob.glob('assets-src/cars/sprites_x4/*_default.png')}
os.makedirs(out, exist_ok=True)
def cell(p, crop=None):
    try: im = Image.open(p).convert('RGB')
    except Exception: return Image.new('RGB', (640, 360), (40, 40, 40))
    if crop: im = im.crop(crop)
    return im.resize((640, 360), Image.LANCZOS)
for n in models:
    card = Image.new('RGB', (1280, 720), (20, 20, 20))
    card.paste(cell(f'{run}/drv_door_{n:03d}.png'), (0, 0))
    card.paste(cell(f'{run}/drv_fq_{n:03d}.png'), (640, 0))
    card.paste(cell(f'{run}/drv_rq_{n:03d}.png'), (0, 360))
    card.paste(cell(f'{run}/drv_far3_{n:03d}.png'), (640, 360))
    sp = glob.glob(f'assets-src/cars/sprites_x4/{n:03d}_*_default.png')
    if sp:
        s = Image.open(sp[0]).convert('RGBA'); w, h = s.size; sc = min(90 / w, 170 / h)
        s = s.resize((max(1, int(w * sc)), max(1, int(h * sc)))); card.paste(s, (1180, 540), s)
    d = ImageDraw.Draw(card); d.rectangle((0, 0, 230, 14), fill=(0, 0, 0)); d.text((3, 2), f'{n:03d} {names.get(n, "")}  door | fq / rq | far', fill=(255, 255, 0))
    card.save(f'{out}/card_{n:03d}.png')
print('cards:', len(models))
