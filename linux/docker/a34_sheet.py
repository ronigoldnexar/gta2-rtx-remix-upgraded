#!/usr/bin/env python3
"""ACTIONS-3D-4 sheet: before/after frame strips from the a34 probe's bursts.
    a34_sheet.py <out dir> <tiles.json> <sheet.png>
tiles.json: {"rows": [{"label", "before": [run, burst, first, step, count, [x, y, w, h]],
                        "after": [...same...]}], "width": tile width}
Frames are numbered from 0 at 15 fps within out/<run>/b_<burst>.mp4."""
import json, os, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFont

out, cfg_path, sheet = sys.argv[1:4]
cfg = json.load(open(cfg_path))
TW = cfg.get("width", 200)
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17)
tmp = tempfile.mkdtemp(prefix="a34sheet")


def frames(run, burst):
    d = os.path.join(tmp, f"{run}_{burst}")
    if not os.path.isdir(d):
        os.makedirs(d)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", os.path.join(out, run, f"b_{burst}.mp4"),
                        os.path.join(d, "%03d.png")], check=True)
    return d


def strip(spec):
    run, burst, first, step, count, box = spec
    d = frames(run, burst)
    x, y, w, h = box
    th = int(TW * h / w)
    tiles = []
    for k in range(count):
        f = os.path.join(d, "%03d.png" % (first + k * step + 1))
        if not os.path.exists(f): break
        im = Image.open(f).convert("RGB").crop((x, y, x + w, y + h)).resize((TW, th), Image.LANCZOS)
        ImageDraw.Draw(im).text((4, 2), "%.2fs" % ((first + k * step) / 15.0), fill=(255, 255, 0), font=font)
        tiles.append(im)
    return tiles, th


rows = []
for r in cfg["rows"]:
    for which in ("before", "after"):
        if which not in r: continue
        tiles, th = strip(r[which])
        rows.append((f"{r['label']} - {which}", r.get(which + "_note", ""), tiles, th))
LW = 0
cols = max(len(t) for _, _, t, _ in rows)
W = cols * (TW + 4) + 8
H = sum(th + 30 for _, _, _, th in rows) + 8
img = Image.new("RGB", (W, H), (24, 24, 28))
dr = ImageDraw.Draw(img)
y = 4
for label, note, tiles, th in rows:
    dr.text((6, y + 4), label, fill=(255, 255, 255) if "after" in label else (200, 160, 160), font=bold)
    if note: dr.text((340, y + 6), note, fill=(190, 190, 190), font=font)
    y += 26
    for k, t in enumerate(tiles):
        img.paste(t, (4 + k * (TW + 4), y))
    y += th + 4
img.save(sheet)
print("wrote", sheet, img.size)
