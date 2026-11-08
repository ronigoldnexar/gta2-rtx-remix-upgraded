#!/usr/bin/env python3
"""VISUALS-PLAIN sheet: before ([visuals] enabled=0) / after pairs from a vis_look.py run at the
same spot, view and sun, for day / golden hour / night, third and first person; the quality tiers;
and a cost table. vis_sheet.py <out.png> <look run dir> [costs.tsv]
(costs.tsv: label<TAB>text lines printed under the frames)."""
import os, sys
from PIL import Image, ImageDraw, ImageFont

out, run = sys.argv[1], sys.argv[2]
costs = open(sys.argv[3]).read().strip().splitlines() if len(sys.argv) > 3 and os.path.exists(sys.argv[3]) else []
TW, TH, PAD, HEAD = 400, 225, 6, 30
def font(sz):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        if os.path.exists(f): return ImageFont.truetype(f, sz)
    return ImageFont.load_default()
F, FB = font(15), font(20)
TODS = [("day", "day (sun 34 deg)"), ("golden", "golden hour (7 deg)"), ("night", "night (-15 deg)")]
spots = sorted({n.split("_")[1][1:] for n in os.listdir(run) if n.startswith("t_s")})
rows = [(s, v) for s in spots for v in ("third", "first")]
cols = [(t, st) for t, _ in TODS for st in ("off", "on")]
tiers = [(t, q) for t in ("day", "night") for q in ("low", "medium", "high")]
W = PAD + len(cols) * (TW + PAD) + 120
H = 60 + HEAD + len(rows) * (TH + PAD) + 40 + HEAD + (TH + PAD) + 30 + 22 * len(costs) + 20
img = Image.new("RGB", (W, H), (250, 250, 247)); d = ImageDraw.Draw(img)
d.text((PAD, 8), "Plain renderer visuals: v1.5 (off) and VISUALS-PLAIN (on) at the same spot, view and sun; Downtown, 1280x720", fill=(10, 10, 10), font=FB)
d.text((PAD, 34), f"frames: {run}  ([visuals] enabled toggled live; traffic and people move between the pair)", fill=(80, 80, 78), font=F)
y = 60
for i, (t, st) in enumerate(cols):
    label = dict(TODS)[t] + ("  before" if st == "off" else "  after")
    d.text((120 + PAD + i * (TW + PAD), y + 6), label, fill=(10, 10, 10) if st == "on" else (90, 90, 88), font=F)
y += HEAD
def thumb(name):
    p = os.path.join(run, f"t_{name}.png")
    if not os.path.exists(p): return None
    return Image.open(p).convert("RGB").resize((TW, TH), Image.LANCZOS)
for s, v in rows:
    d.text((PAD, y + TH // 2 - 10), f"spot {s}\n{v}", fill=(10, 10, 10), font=F)
    for i, (t, st) in enumerate(cols):
        im = thumb(f"s{s}_{v}_{t}_{st}")
        x = 120 + PAD + i * (TW + PAD)
        if im: img.paste(im, (x, y))
        else: d.rectangle((x, y, x + TW, y + TH), outline=(200, 200, 200))
    y += TH + PAD
y += 20
d.text((PAD, y), "Quality tiers, spot 0, chase view:", fill=(10, 10, 10), font=FB); y += HEAD
for i, (t, q) in enumerate(tiers):
    x = PAD + i * (TW + PAD)
    if x + TW > W: break
    im = thumb(f"tier_{t}_{q}")
    if im: img.paste(im, (x, y))
    d.text((x + 6, y + 4), f"{t} {q}", fill=(255, 255, 255), font=F)
y += TH + PAD + 10
for line in costs:
    d.text((PAD, y), line.replace("\t", "   "), fill=(10, 10, 10), font=F); y += 22
img.save(out); print("wrote", out, img.size)
