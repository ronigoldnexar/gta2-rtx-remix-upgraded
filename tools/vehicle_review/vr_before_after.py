#!/usr/bin/env python3
"""Like-for-like before/after contact sheet for one vehicle model, in the vr_sheet.py layout
(sprite | far | close | eye | eye2 | own chase | own seat), one row per take.

usage: vr_before_after.py <out.png> <model> <row> [<row> ...]
  row = "label|far|close|eye|eye2|chase|seat": PNG paths of 1280x720 game frames, '-' for a cell that
  has no valid frame (it is drawn as 'n/a' with the reason given after a colon, e.g. '-:scene car is a 050').
Close/eye/eye2 get vr_sheet.py's crop (the car in the lower middle). Run from the workspace root (the
sprite comes from assets-src/cars/sprites_x4). Only compare rows shot by the same harness, from the same
spot, heading and camera, on the same DLL and ini (docs/vehicle-art-review.md, 'VEHICLE-VERIFY')."""
import glob, sys
from PIL import Image, ImageDraw

W, H = 400, 225
CROP = (240, 150, 1040, 600)
COLS = ['far', 'close', 'eye', 'eye2', 'own chase', 'own seat']
CROPPED = {'close', 'eye', 'eye2'}

def cell(spec, crop):
    if spec.startswith('-'):
        im = Image.new('RGB', (W, H), (45, 45, 45)); d = ImageDraw.Draw(im)
        d.text((10, 10), 'n/a', fill=(255, 120, 80))
        if ':' in spec: d.text((10, 28), spec.split(':', 1)[1][:60], fill=(220, 220, 220))
        return im
    im = Image.open(spec).convert('RGB')
    if crop: im = im.crop(CROP)
    return im.resize((W, H), Image.LANCZOS)

def main():
    out, n, rows = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    LW = 150
    sheet = Image.new('RGB', (LW + len(COLS) * (W + 4), 20 + len(rows) * (H + 22)), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    for c, name in enumerate(COLS):
        d.text((LW + c * (W + 4) + 4, 4), name, fill=(200, 200, 200))
    sp = glob.glob(f'assets-src/cars/sprites_x4/{n:03d}_*_default.png')
    for r, row in enumerate(rows):
        parts = row.split('|')
        if len(parts) != 7: sys.exit(f'row needs 7 fields: {row}')
        y = 20 + r * (H + 22)
        d.text((4, y + 4), parts[0][:22], fill=(255, 255, 0))
        if sp:
            s = Image.open(sp[0]).convert('RGBA'); sw, sh = s.size; sc = min((LW - 20) / sw, (H - 10) / sh)
            s = s.resize((max(1, int(sw * sc)), max(1, int(sh * sc)))); sheet.paste(s, (8, y + 20), s)
        for c, name in enumerate(COLS):
            x = LW + c * (W + 4)
            sheet.paste(cell(parts[c + 1], name in CROPPED), (x, y + 20))
    sheet.save(out); print(out, sheet.size)

if __name__ == '__main__':
    main()
