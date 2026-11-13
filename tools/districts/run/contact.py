#!/usr/bin/env python3
"""contact.py <run dir> <point name> <out prefix>: the POC contact sheets of one capture run.
  <out>_ab.jpg    before | after pairs (kit off | on, the same frame): day and night x street, graze, across, roof,
                  third person, first person
  <out>_move.jpg  the move from the classic view into third person and back (kit on), day and night"""
import os, sys
from PIL import Image, ImageDraw
run, name, out = sys.argv[1:4]
CW = 640


def cell(path, label):
    im = Image.open(path).convert("RGB") if os.path.exists(path) else Image.new("RGB", (1280, 720), (60, 0, 0))
    im = im.resize((CW, CW * im.height // im.width), Image.LANCZOS)
    c = Image.new("RGB", (im.width, im.height + 16), (0, 0, 0)); c.paste(im, (0, 16))
    ImageDraw.Draw(c).text((4, 2), label, fill=(255, 255, 255))
    return c


rows = []
for tod in ("day", "night"):
    for v in ("street", "graze", "across", "roof", "third", "first"):
        a = cell(f"{run}/dk_{name}_{tod}_{v}_off.png", f"{name} {tod} {v}: BEFORE (kit off)")
        b = cell(f"{run}/dk_{name}_{tod}_{v}_on.png", f"{name} {tod} {v}: AFTER (kit on)")
        r = Image.new("RGB", (a.width * 2 + 4, a.height), (0, 0, 0)); r.paste(a, (0, 0)); r.paste(b, (a.width + 4, 0))
        rows.append(r)
sheet = Image.new("RGB", (rows[0].width * 2 + 8, (len(rows) + 1) // 2 * (rows[0].height + 4)), (20, 20, 20))
for i, r in enumerate(rows):
    sheet.paste(r, ((i // 6) * (r.width + 8), (i % 6) * (r.height + 4)))
sheet.save(out + "_ab.jpg", quality=88)

CW = 320
strips = []
for tod in ("day", "night"):
    for mv, frames in (("move", range(6, 31, 2)), ("moveout", range(6, 31, 2))):
        cs = [cell(f"{run}/dk_{name}_{tod}_{mv}_{k:02d}.png", f"{tod} {mv} {k:02d} ({k / 6:.2f}s)") for k in frames
              if os.path.exists(f"{run}/dk_{name}_{tod}_{mv}_{k:02d}.png")]
        if cs:
            s = Image.new("RGB", (len(cs) * (cs[0].width + 2), cs[0].height), (0, 0, 0))
            for i, c in enumerate(cs):
                s.paste(c, (i * (c.width + 2), 0))
            strips.append(s)
if strips:
    m = Image.new("RGB", (max(s.width for s in strips), sum(s.height + 4 for s in strips)), (20, 20, 20))
    y = 0
    for s in strips:
        m.paste(s, (0, y)); y += s.height + 4
    m.save(out + "_move.jpg", quality=85)
print("sheets", out)
