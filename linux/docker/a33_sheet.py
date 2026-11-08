#!/usr/bin/env python3
"""ACTIONS-3D-3 contact sheet: out/actions_3d_3_sheet.png from the a33_* probe runs
(linux/docker/a33_probe.py). Each tile is a crop of a 1280x720 frame with a caption.
    a33_sheet.py <out dir> <tiles.json>
tiles.json: [[row title, [[path, [x0,y0,x1,y1] or null, caption], ...]], ...]"""
import json, os, sys
from PIL import Image, ImageDraw

OUT = sys.argv[1]
ROWS = json.load(open(sys.argv[2]))
FULL = (0, 0, 1280, 720)
TW, TH, CAP, HEAD = 320, 200, 28, 22
cols = max(len(r[1]) for r in ROWS)
sheet = Image.new("RGB", (cols * TW, sum(HEAD + TH + CAP for _ in ROWS) + 30), (18, 18, 20))
d = ImageDraw.Draw(sheet)
d.text((6, 8), "ACTIONS-3D-3, 8 Nov 2026: street views on the L4 GPU build, Downtown. Generator linux/docker/a33_sheet.py, runs out/a33_*", fill=(230, 230, 230))
y = 30
for title, tiles in ROWS:
    d.text((6, y + 5), title, fill=(255, 210, 90)); y += HEAD
    for i, (path, box, cap) in enumerate(tiles):
        p = os.path.join(OUT, path)
        if not os.path.exists(p):
            d.text((i * TW + 6, y + TH // 2), "missing: " + path, fill=(255, 80, 80)); continue
        im = Image.open(p).convert("RGB").crop(tuple(box or FULL))
        im.thumbnail((TW - 4, TH - 4))
        sheet.paste(im, (i * TW + (TW - im.width) // 2, y + (TH - im.height) // 2))
        for k, line in enumerate(cap.split("\n")[:2]):
            d.text((i * TW + 4, y + TH + k * 12), line, fill=(220, 220, 220))
    y += TH + CAP
sheet.save(os.path.join(OUT, "actions_3d_3_sheet.png"))
print(os.path.join(OUT, "actions_3d_3_sheet.png"), sheet.size)
