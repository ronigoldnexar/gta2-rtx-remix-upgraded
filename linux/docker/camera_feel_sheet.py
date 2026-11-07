#!/usr/bin/env python3
"""Before/after sheet for the camera feel: 10 fps strips of each turn capture
plus the measured rates. Usage: camera_feel_sheet.py <before dir> <after dir> <out.png> <rates.txt>"""
import os, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFont

before, after, out, rates = sys.argv[1:5]
phases = [("third_foot", {"BEFORE": "third person on foot: Left tapped 0.5 s (turns the player, camera follows 1:1)",
                          "AFTER": "third person on foot: Left held 2 s (walk to the camera's left; the camera holds its yaw)"}),
          ("third_recentre", {"AFTER": "third person on foot: Up held 5 s (walk away; the slow re-centre starts after 2 s)"}),
          ("first_foot", {"BEFORE": "first person on foot: Left tapped 0.5 s", "AFTER": "first person on foot: Left held 2 s (the view winds up 25 to 70 deg/s; the pedestrian follows)"}),
          ("third_car", {"BEFORE": "third person at the wheel: Left+Up 1 s", "AFTER": "third person at the wheel: Left+Up 2 s (chase camera, cap 90 deg/s, 0.8 s damping)"}),
          ("first_car", {"BEFORE": "first person at the wheel: Right+Up 1 s", "AFTER": "first person at the wheel: Right+Up 2 s (fixed to the car, 120 ms ease)"}),
          ("browser", {"AFTER": "what the browser sees (headless Chromium on the noVNC page, keys through noVNC): third person, Left 2 s, Up 2 s, Right 2 s; one tile a second"})]
W, H, N = 256, 144, 10   # tile size, tiles per strip (1 s at 10 fps from 1.2 s in)
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
rows = []
for key, title in phases:
    for label, d in (("BEFORE", before), ("AFTER", after)):
        if label not in title: continue
        src = os.path.join(d, f"{label.lower()}_{key}.mp4")
        tiles = []
        if os.path.exists(src):
            tmp = tempfile.mkdtemp()
            ss, t, fps = ("0", "12", "1") if key == "browser" else ("1.2", "1.0", "10")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", ss, "-t", t, "-i", src, "-vf", f"fps={fps},scale={W}:{H}", os.path.join(tmp, "f%02d.png")])
            tiles = [Image.open(os.path.join(tmp, f)) for f in sorted(os.listdir(tmp))][:N]
        rows.append((f"{label}: {title[label]}", tiles))
text = open(rates).read().splitlines() if os.path.exists(rates) else []
sheet = Image.new("RGB", (W * N, (H + 22) * len(rows) + 18 * (len(text) + 1)), (16, 16, 16))
dr = ImageDraw.Draw(sheet)
y = 0
for title, tiles in rows:
    dr.text((6, y + 3), title, fill=(255, 230, 120), font=font)
    y += 22
    for i, t in enumerate(tiles):
        sheet.paste(t, (i * W, y))
    if not tiles:
        dr.text((6, y + 60), "(no capture)", fill=(200, 80, 80), font=font)
    y += H
y += 6
for line in text:
    dr.text((6, y), line, fill=(220, 220, 220), font=font)
    y += 18
sheet.save(out)
print(out, sheet.size)
